import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.promotion import CouponTemplate, UserCoupon
from app.models.product import Product, Sku
from app.models.user import User
from app.schemas.promotion import (
    CouponBatchGrantResponse,
    CouponTemplateCreateRequest,
    CouponTemplateResponse,
    CouponTemplateUpdateRequest,
    UserCouponResponse,
)


class PromotionService:
    async def create_coupon_template(
        self,
        db: AsyncSession,
        payload: CouponTemplateCreateRequest,
    ) -> CouponTemplateResponse:
        self._validate_template_data(
            payload.scope_type,
            payload.scope_ids,
            payload.discount_type,
            payload.discount_value,
            payload.valid_from,
            payload.valid_to,
        )
        template = CouponTemplate(
            **payload.model_dump(exclude={"scope_ids"}),
            scope_ids=json.dumps(payload.scope_ids),
            status="active",
            claimed_quantity=0,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return self._template_to_response(template)

    async def update_coupon_template(
        self,
        db: AsyncSession,
        template_id: int,
        payload: CouponTemplateUpdateRequest,
    ) -> CouponTemplateResponse:
        template = await self._get_template(db, template_id)
        next_scope_type = payload.scope_type if payload.scope_type is not None else template.scope_type
        next_scope_ids = payload.scope_ids if payload.scope_ids is not None else self._load_scope_ids(template)
        next_discount_type = payload.discount_type if payload.discount_type is not None else template.discount_type
        next_discount_value = payload.discount_value if payload.discount_value is not None else template.discount_value
        next_valid_from = payload.valid_from if "valid_from" in payload.model_fields_set else template.valid_from
        next_valid_to = payload.valid_to if "valid_to" in payload.model_fields_set else template.valid_to
        self._validate_template_data(
            next_scope_type,
            next_scope_ids,
            next_discount_type,
            next_discount_value,
            next_valid_from,
            next_valid_to,
        )

        update_data = payload.model_dump(exclude_unset=True, exclude={"scope_ids"})
        for field, value in update_data.items():
            setattr(template, field, value)
        if payload.scope_ids is not None:
            template.scope_ids = json.dumps(payload.scope_ids)
        await db.commit()
        await db.refresh(template)
        return self._template_to_response(template)

    async def disable_coupon_template(self, db: AsyncSession, template_id: int) -> CouponTemplateResponse:
        template = await self._get_template(db, template_id)
        template.status = "disabled"
        await db.commit()
        await db.refresh(template)
        return self._template_to_response(template)

    async def expire_user_coupons(self, db: AsyncSession) -> int:
        now = datetime.now(UTC)
        result = await db.execute(
            select(UserCoupon, CouponTemplate)
            .join(CouponTemplate, UserCoupon.coupon_template_id == CouponTemplate.id)
            .where(UserCoupon.status == "unused", CouponTemplate.valid_to.is_not(None), CouponTemplate.valid_to < now)
        )
        expired_count = 0
        for user_coupon, _ in result.all():
            user_coupon.status = "expired"
            expired_count += 1
        await db.commit()
        return expired_count

    async def batch_grant_coupon(
        self,
        db: AsyncSession,
        template_id: int,
        user_ids: list[int],
    ) -> CouponBatchGrantResponse:
        template = await self._get_available_template(db, template_id)
        unique_user_ids = list(dict.fromkeys(user_ids))
        result = await db.execute(select(User.id).where(User.id.in_(unique_user_ids), User.is_active.is_(True)))
        active_user_ids = set(result.scalars())

        skipped_user_ids: list[int] = []
        granted_count = 0
        for user_id in unique_user_ids:
            if user_id not in active_user_ids:
                skipped_user_ids.append(user_id)
                continue
            if not self._has_remaining_quantity(template):
                skipped_user_ids.append(user_id)
                continue
            claimed_count = await self._count_user_claimed(db, user_id, template_id)
            if claimed_count >= template.per_user_limit:
                skipped_user_ids.append(user_id)
                continue
            db.add(UserCoupon(user_id=user_id, coupon_template_id=template.id, status="unused"))
            template.claimed_quantity += 1
            granted_count += 1

        await db.commit()
        return CouponBatchGrantResponse(granted_count=granted_count, skipped_user_ids=skipped_user_ids)

    async def list_coupon_templates(
        self,
        db: AsyncSession,
        *,
        only_available: bool,
    ) -> list[CouponTemplateResponse]:
        statement = select(CouponTemplate).order_by(CouponTemplate.created_at.desc())
        if only_available:
            now = datetime.now(UTC)
            statement = statement.where(CouponTemplate.status == "active")
            statement = statement.where((CouponTemplate.valid_from.is_(None)) | (CouponTemplate.valid_from <= now))
            statement = statement.where((CouponTemplate.valid_to.is_(None)) | (CouponTemplate.valid_to >= now))
        result = await db.execute(statement)
        templates = list(result.scalars())
        if only_available:
            templates = [template for template in templates if self._has_remaining_quantity(template)]
        return [self._template_to_response(template) for template in templates]

    async def get_coupon_template(self, db: AsyncSession, template_id: int) -> CouponTemplateResponse:
        template = await self._get_template(db, template_id)
        return self._template_to_response(template)

    async def claim_coupon(self, db: AsyncSession, user: User, template_id: int) -> UserCouponResponse:
        template = await self._get_available_template(db, template_id)
        claimed_count = await self._count_user_claimed(db, user.id, template_id)
        if claimed_count >= template.per_user_limit:
            raise AppException(40005, "已达到领取上限")
        template.claimed_quantity += 1
        user_coupon = UserCoupon(user_id=user.id, coupon_template_id=template.id, status="unused")
        db.add(user_coupon)
        await db.commit()
        await db.refresh(user_coupon)
        return self._user_coupon_to_response(user_coupon, template)

    async def list_user_coupons(
        self,
        db: AsyncSession,
        user: User,
        *,
        status: str | None = None,
    ) -> list[UserCouponResponse]:
        statement = select(UserCoupon, CouponTemplate).join(
            CouponTemplate,
            UserCoupon.coupon_template_id == CouponTemplate.id,
        )
        statement = statement.where(UserCoupon.user_id == user.id).order_by(UserCoupon.claimed_at.desc())
        if status:
            statement = statement.where(UserCoupon.status == status)
        result = await db.execute(statement)
        return [self._user_coupon_to_response(user_coupon, template) for user_coupon, template in result.all()]

    async def calculate_coupon_discount(
        self,
        db: AsyncSession,
        user: User,
        user_coupon_id: int | None,
        amount_cent: int,
        sku_quantities: list[tuple[Sku, int]] | None = None,
    ) -> tuple[int, UserCoupon | None]:
        if user_coupon_id is None:
            return 0, None
        result = await db.execute(
            select(UserCoupon, CouponTemplate)
            .join(CouponTemplate, UserCoupon.coupon_template_id == CouponTemplate.id)
            .where(UserCoupon.id == user_coupon_id)
        )
        row = result.one_or_none()
        if row is None:
            raise AppException(40004, "优惠券不存在", 404)
        user_coupon, template = row
        if user_coupon.user_id != user.id:
            raise AppException(40005, "优惠券不可用")
        if user_coupon.status != "unused":
            raise AppException(40005, "优惠券状态不可用")
        self._ensure_template_can_use(template)
        applicable_amount = amount_cent
        if sku_quantities is not None:
            applicable_amount = self._calculate_applicable_amount(template, sku_quantities)
        if applicable_amount <= 0:
            raise AppException(40005, "优惠券不适用于当前商品")
        if applicable_amount < template.min_amount_cent:
            raise AppException(40005, "未达到优惠券使用门槛")
        if template.discount_type == "amount":
            discount = template.discount_value
        else:
            discount = applicable_amount * (100 - template.discount_value) // 100
        user_coupon.template = template
        return min(discount, applicable_amount), user_coupon

    async def mark_coupon_used(self, db: AsyncSession, user_coupon: UserCoupon | None, order_id: int | None) -> None:
        if user_coupon is None:
            return
        user_coupon.status = "used"
        user_coupon.order_id = order_id
        user_coupon.used_at = datetime.now(UTC)

    def allocate_discount_by_merchant(
        self,
        discount_amount: int,
        user_coupon: UserCoupon | None,
        sku_quantities: list[tuple[Sku, int]],
    ) -> dict[int, int]:
        if discount_amount <= 0:
            return {}
        if user_coupon is None:
            return self._allocate_by_merchant_amount(discount_amount, sku_quantities)
        template = user_coupon.template
        applicable_items = [
            (sku, quantity)
            for sku, quantity in sku_quantities
            if self._is_sku_in_scope(template, sku)
        ]
        return self._allocate_by_merchant_amount(discount_amount, applicable_items)

    async def _get_available_template(self, db: AsyncSession, template_id: int) -> CouponTemplate:
        template = await self._get_template(db, template_id)
        self._ensure_template_can_use(template)
        if not self._has_remaining_quantity(template):
            raise AppException(40005, "优惠券已领完")
        return template

    async def _get_template(self, db: AsyncSession, template_id: int) -> CouponTemplate:
        template = await db.get(CouponTemplate, template_id)
        if template is None:
            raise AppException(40004, "优惠券不存在", 404)
        return template

    def _validate_template_data(
        self,
        scope_type: str,
        scope_ids: list[int],
        discount_type: str,
        discount_value: int,
        valid_from: datetime | None,
        valid_to: datetime | None,
    ) -> None:
        if discount_type == "percent" and discount_value > 100:
            raise AppException(40001, "折扣百分比必须在 1-100 之间")
        if valid_from and valid_to and valid_from >= valid_to:
            raise AppException(40001, "有效期开始时间必须早于结束时间")
        if scope_type not in {"all", "platform"} and not scope_ids:
            raise AppException(40001, "指定范围优惠券必须填写 scope_ids")

    def _ensure_template_can_use(self, template: CouponTemplate) -> None:
        now = datetime.now(UTC)
        if template.status != "active":
            raise AppException(40008, "优惠券不可用")
        if template.valid_from and template.valid_from > now:
            raise AppException(40008, "优惠券未开始")
        if template.valid_to and template.valid_to < now:
            raise AppException(40008, "优惠券已过期")

    def _has_remaining_quantity(self, template: CouponTemplate) -> bool:
        return template.total_quantity == 0 or template.claimed_quantity < template.total_quantity

    async def _count_user_claimed(self, db: AsyncSession, user_id: int, template_id: int) -> int:
        result = await db.execute(
            select(func.count(UserCoupon.id)).where(
                UserCoupon.user_id == user_id,
                UserCoupon.coupon_template_id == template_id,
            )
        )
        return int(result.scalar_one())

    def _user_coupon_to_response(
        self,
        user_coupon: UserCoupon,
        template: CouponTemplate,
    ) -> UserCouponResponse:
        return UserCouponResponse(
            id=user_coupon.id,
            user_id=user_coupon.user_id,
            coupon_template_id=user_coupon.coupon_template_id,
            status=user_coupon.status,
            order_id=user_coupon.order_id,
            claimed_at=user_coupon.claimed_at,
            used_at=user_coupon.used_at,
            template=self._template_to_response(template),
        )

    def _template_to_response(self, template: CouponTemplate) -> CouponTemplateResponse:
        return CouponTemplateResponse(
            id=template.id,
            name=template.name,
            scope_type=template.scope_type,
            scope_ids=self._load_scope_ids(template),
            discount_type=template.discount_type,
            discount_value=template.discount_value,
            min_amount_cent=template.min_amount_cent,
            total_quantity=template.total_quantity,
            claimed_quantity=template.claimed_quantity,
            per_user_limit=template.per_user_limit,
            status=template.status,
            valid_from=template.valid_from,
            valid_to=template.valid_to,
        )

    def _load_scope_ids(self, template: CouponTemplate) -> list[int]:
        try:
            value = json.loads(template.scope_ids or "[]")
        except json.JSONDecodeError:
            return []
        return [int(item) for item in value if isinstance(item, int)]

    def _calculate_applicable_amount(self, template: CouponTemplate, sku_quantities: list[tuple[Sku, int]]) -> int:
        total = 0
        for sku, quantity in sku_quantities:
            if self._is_sku_in_scope(template, sku):
                total += sku.price_cent * quantity
        return total

    def _is_sku_in_scope(self, template: CouponTemplate, sku: Sku) -> bool:
        scope_type = template.scope_type
        if scope_type in {"all", "platform"}:
            return True
        scope_ids = set(self._load_scope_ids(template))
        product: Product = sku.product
        return (
            (scope_type == "merchant" and product.merchant_id in scope_ids)
            or (scope_type == "category" and product.category_id in scope_ids)
            or (scope_type == "product" and product.id in scope_ids)
            or (scope_type == "sku" and sku.id in scope_ids)
        )

    def _allocate_by_merchant_amount(
        self,
        discount_amount: int,
        sku_quantities: list[tuple[Sku, int]],
    ) -> dict[int, int]:
        merchant_amounts: dict[int, int] = {}
        for sku, quantity in sku_quantities:
            merchant_amounts[sku.product.merchant_id] = (
                merchant_amounts.get(sku.product.merchant_id, 0) + sku.price_cent * quantity
            )
        total_amount = sum(merchant_amounts.values())
        if total_amount <= 0:
            return {}
        allocated: dict[int, int] = {}
        remaining_discount = discount_amount
        merchant_items = list(merchant_amounts.items())
        for index, (merchant_id, amount) in enumerate(merchant_items):
            if index == len(merchant_items) - 1:
                share = remaining_discount
            else:
                share = discount_amount * amount // total_amount
                remaining_discount -= share
            allocated[merchant_id] = min(amount, share)
        return allocated


promotion_service = PromotionService()
