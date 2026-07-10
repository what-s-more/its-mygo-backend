import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.promotion import CouponTemplate, FullDiscountActivity, UserCoupon
from app.models.product import Product, Sku
from app.models.user import User
from app.schemas.order import CouponOptionResponse, PromotionOptionResponse
from app.schemas.promotion import (
    CouponBatchGrantResponse,
    CouponTemplateCreateRequest,
    CouponTemplateResponse,
    CouponTemplateUpdateRequest,
    FullDiscountCreateRequest,
    FullDiscountResponse,
    FullDiscountUpdateRequest,
    UserCouponResponse,
)


class PromotionService:
    async def create_full_discount(
        self,
        db: AsyncSession,
        payload: FullDiscountCreateRequest,
        *,
        owner_merchant_id: int | None = None,
        created_by_admin_id: int | None = None,
    ) -> FullDiscountResponse:
        self._validate_activity_data(
            payload.scope_type,
            payload.scope_ids,
            payload.min_amount_cent,
            payload.discount_amount_cent,
            payload.valid_from,
            payload.valid_to,
        )
        activity = FullDiscountActivity(
            **payload.model_dump(exclude={"scope_ids"}),
            scope_ids=json.dumps(payload.scope_ids),
            owner_merchant_id=owner_merchant_id,
            created_by_admin_id=created_by_admin_id,
            status="active",
        )
        db.add(activity)
        await db.commit()
        await db.refresh(activity)
        return self._full_discount_to_response(activity)

    async def update_full_discount(
        self,
        db: AsyncSession,
        activity_id: int,
        payload: FullDiscountUpdateRequest,
    ) -> FullDiscountResponse:
        activity = await self._get_full_discount(db, activity_id)
        next_scope_type = payload.scope_type if payload.scope_type is not None else activity.scope_type
        next_scope_ids = payload.scope_ids if payload.scope_ids is not None else self._load_activity_scope_ids(activity)
        next_min_amount = payload.min_amount_cent if payload.min_amount_cent is not None else activity.min_amount_cent
        next_discount_amount = (
            payload.discount_amount_cent
            if payload.discount_amount_cent is not None
            else activity.discount_amount_cent
        )
        next_valid_from = payload.valid_from if "valid_from" in payload.model_fields_set else activity.valid_from
        next_valid_to = payload.valid_to if "valid_to" in payload.model_fields_set else activity.valid_to
        self._validate_activity_data(
            next_scope_type,
            next_scope_ids,
            next_min_amount,
            next_discount_amount,
            next_valid_from,
            next_valid_to,
        )

        update_data = payload.model_dump(exclude_unset=True, exclude={"scope_ids"})
        for field, value in update_data.items():
            setattr(activity, field, value)
        if payload.scope_ids is not None:
            activity.scope_ids = json.dumps(payload.scope_ids)
        await db.commit()
        await db.refresh(activity)
        return self._full_discount_to_response(activity)

    async def disable_full_discount(self, db: AsyncSession, activity_id: int) -> FullDiscountResponse:
        activity = await self._get_full_discount(db, activity_id)
        activity.status = "disabled"
        await db.commit()
        await db.refresh(activity)
        return self._full_discount_to_response(activity)

    async def list_full_discounts(
        self,
        db: AsyncSession,
        *,
        only_available: bool,
        merchant_id: int | None = None,
        owner_only: bool = False,
    ) -> list[FullDiscountResponse]:
        statement = select(FullDiscountActivity).order_by(FullDiscountActivity.created_at.desc())
        if only_available:
            now = datetime.now(UTC)
            statement = statement.where(FullDiscountActivity.status == "active")
            statement = statement.where(
                (FullDiscountActivity.valid_from.is_(None)) | (FullDiscountActivity.valid_from <= now)
            )
            statement = statement.where(
                (FullDiscountActivity.valid_to.is_(None)) | (FullDiscountActivity.valid_to >= now)
            )
        result = await db.execute(statement)
        activities = list(result.scalars())
        if merchant_id is not None:
            if owner_only:
                activities = [activity for activity in activities if activity.owner_merchant_id == merchant_id]
            else:
                activities = await self._filter_activities_for_merchant(db, activities, merchant_id)
        return [self._full_discount_to_response(activity) for activity in activities]

    async def get_full_discount(self, db: AsyncSession, activity_id: int) -> FullDiscountResponse:
        activity = await self._get_full_discount(db, activity_id)
        return self._full_discount_to_response(activity)

    async def calculate_full_discount(
        self,
        db: AsyncSession,
        sku_quantities: list[tuple[Sku, int]],
        full_discount_id: int | None = None,
    ) -> tuple[int, FullDiscountActivity | None]:
        activities = await self._list_available_full_discount_models(db)
        if full_discount_id is not None:
            activity = next((item for item in activities if item.id == full_discount_id), None)
            if activity is None:
                raise AppException(40005, "满减活动不可用")
            applicable_amount = self._calculate_activity_applicable_amount(activity, sku_quantities)
            discount = self._calculate_repeat_full_discount(applicable_amount, activity)
            if discount <= 0:
                raise AppException(40005, "满减活动未达到使用门槛")
            return discount, activity

        best_activity: FullDiscountActivity | None = None
        best_discount = 0
        for activity in activities:
            applicable_amount = self._calculate_activity_applicable_amount(activity, sku_quantities)
            discount = self._calculate_repeat_full_discount(applicable_amount, activity)
            if discount > best_discount:
                best_discount = discount
                best_activity = activity
        return best_discount, best_activity

    async def list_full_discount_options(
        self,
        db: AsyncSession,
        sku_quantities: list[tuple[Sku, int]],
        *,
        selected_id: int | None = None,
    ) -> list[PromotionOptionResponse]:
        activities = await self._list_available_full_discount_models(db)
        options: list[PromotionOptionResponse] = []
        for activity in activities:
            applicable_amount = self._calculate_activity_applicable_amount(activity, sku_quantities)
            discount = self._calculate_repeat_full_discount(applicable_amount, activity)
            available = discount > 0
            options.append(
                PromotionOptionResponse(
                    id=activity.id,
                    name=activity.name,
                    scope_type=activity.scope_type,
                    scope_ids=self._load_activity_scope_ids(activity),
                    min_amount_cent=activity.min_amount_cent,
                    discount_amount_cent=discount,
                    applicable_amount_cent=applicable_amount,
                    available=available,
                    unavailable_reason=None if available else "未达到满减门槛或当前商品不适用",
                    selected=activity.id == selected_id,
                )
            )
        return options

    async def create_coupon_template(
        self,
        db: AsyncSession,
        payload: CouponTemplateCreateRequest,
        *,
        owner_merchant_id: int | None = None,
        created_by_admin_id: int | None = None,
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
            owner_merchant_id=owner_merchant_id,
            created_by_admin_id=created_by_admin_id,
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
        merchant_id: int | None = None,
        owner_only: bool = False,
        user_id: int | None = None,
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
        if merchant_id is not None:
            if owner_only:
                templates = [template for template in templates if template.owner_merchant_id == merchant_id]
            else:
                templates = await self._filter_templates_for_merchant(db, templates, merchant_id)
        claimed_ids: set[int] = set()
        if user_id is not None:
            claimed_result = await db.execute(
                select(UserCoupon.coupon_template_id).where(UserCoupon.user_id == user_id)
            )
            claimed_ids = {row[0] for row in claimed_result.all()}
        return [self._template_to_response(template, template.id in claimed_ids) for template in templates]

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
            applicable_amount = min(amount_cent, self._calculate_applicable_amount(template, sku_quantities))
        if applicable_amount <= 0:
            raise AppException(40005, "优惠券不适用于当前商品")
        if applicable_amount < template.min_amount_cent:
            raise AppException(40005, "未达到优惠券使用门槛")
        discount = self._calculate_coupon_discount_amount(template, applicable_amount)
        user_coupon.template = template
        return min(discount, applicable_amount), user_coupon

    async def list_coupon_options(
        self,
        db: AsyncSession,
        user: User,
        amount_cent: int,
        sku_quantities: list[tuple[Sku, int]],
        *,
        selected_id: int | None = None,
    ) -> list[CouponOptionResponse]:
        result = await db.execute(
            select(UserCoupon, CouponTemplate)
            .join(CouponTemplate, UserCoupon.coupon_template_id == CouponTemplate.id)
            .where(UserCoupon.user_id == user.id)
            .order_by(UserCoupon.claimed_at.desc())
        )
        options: list[CouponOptionResponse] = []
        for user_coupon, template in result.all():
            applicable_amount = min(amount_cent, self._calculate_applicable_amount(template, sku_quantities))
            discount = 0
            available = True
            unavailable_reason = None
            if user_coupon.status != "unused":
                available = False
                unavailable_reason = "用户券不是未使用状态"
            else:
                try:
                    self._ensure_template_can_use(template)
                except AppException as exc:
                    available = False
                    unavailable_reason = exc.message
            if available and applicable_amount <= 0:
                available = False
                unavailable_reason = "当前商品不在优惠券适用范围"
            if available and applicable_amount < template.min_amount_cent:
                available = False
                unavailable_reason = "未达到优惠券门槛"
            if available:
                discount = self._calculate_coupon_discount_amount(template, applicable_amount)
            options.append(
                CouponOptionResponse(
                    id=user_coupon.id,
                    coupon_template_id=template.id,
                    name=template.name,
                    scope_type=template.scope_type,
                    scope_ids=self._load_scope_ids(template),
                    discount_type=template.discount_type,
                    discount_value=template.discount_value,
                    min_amount_cent=template.min_amount_cent,
                    applicable_amount_cent=applicable_amount,
                    discount_amount_cent=discount,
                    status=user_coupon.status,
                    available=available,
                    unavailable_reason=unavailable_reason,
                    selected=user_coupon.id == selected_id,
                )
            )
        return options

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

    def allocate_full_discount_by_merchant(
        self,
        discount_amount: int,
        activity: FullDiscountActivity | None,
        sku_quantities: list[tuple[Sku, int]],
    ) -> dict[int, int]:
        if discount_amount <= 0:
            return {}
        if activity is None:
            return self._allocate_by_merchant_amount(discount_amount, sku_quantities)
        applicable_items = [
            (sku, quantity)
            for sku, quantity in sku_quantities
            if self._is_sku_in_activity_scope(activity, sku)
        ]
        return self._allocate_by_merchant_amount(discount_amount, applicable_items)

    async def _list_available_full_discount_models(self, db: AsyncSession) -> list[FullDiscountActivity]:
        now = datetime.now(UTC)
        result = await db.execute(
            select(FullDiscountActivity)
            .where(FullDiscountActivity.status == "active")
            .where((FullDiscountActivity.valid_from.is_(None)) | (FullDiscountActivity.valid_from <= now))
            .where((FullDiscountActivity.valid_to.is_(None)) | (FullDiscountActivity.valid_to >= now))
            .order_by(FullDiscountActivity.discount_amount_cent.desc(), FullDiscountActivity.id.asc())
        )
        return list(result.scalars())

    async def _get_full_discount(self, db: AsyncSession, activity_id: int) -> FullDiscountActivity:
        activity = await db.get(FullDiscountActivity, activity_id)
        if activity is None:
            raise AppException(40004, "满减活动不存在", 404)
        return activity

    def _validate_activity_data(
        self,
        scope_type: str,
        scope_ids: list[int],
        min_amount_cent: int,
        discount_amount_cent: int,
        valid_from: datetime | None,
        valid_to: datetime | None,
    ) -> None:
        if scope_type not in {"all", "platform"} and not scope_ids:
            raise AppException(40001, "指定范围满减活动必须填写 scope_ids")
        if discount_amount_cent <= 0:
            raise AppException(40001, "满减优惠金额必须大于 0")
        if min_amount_cent < 0:
            raise AppException(40001, "满减门槛不能小于 0")
        if min_amount_cent > 0 and discount_amount_cent > min_amount_cent:
            raise AppException(40001, "满减优惠金额不能大于使用门槛")
        if valid_from and valid_to and valid_from >= valid_to:
            raise AppException(40001, "有效期开始时间必须早于结束时间")

    def _full_discount_to_response(self, activity: FullDiscountActivity) -> FullDiscountResponse:
        return FullDiscountResponse(
            id=activity.id,
            name=activity.name,
            scope_type=activity.scope_type,
            scope_ids=self._load_activity_scope_ids(activity),
            owner_merchant_id=activity.owner_merchant_id,
            created_by_admin_id=activity.created_by_admin_id,
            min_amount_cent=activity.min_amount_cent,
            discount_amount_cent=activity.discount_amount_cent,
            status=activity.status,
            valid_from=activity.valid_from,
            valid_to=activity.valid_to,
        )

    def _load_activity_scope_ids(self, activity: FullDiscountActivity) -> list[int]:
        try:
            value = json.loads(activity.scope_ids or "[]")
        except json.JSONDecodeError:
            return []
        return [int(item) for item in value if isinstance(item, int)]

    def _is_activity_visible_for_merchant(self, activity: FullDiscountActivity, merchant_id: int) -> bool:
        if activity.scope_type in {"all", "platform"}:
            return True
        scope_ids = set(self._load_activity_scope_ids(activity))
        return activity.scope_type == "merchant" and merchant_id in scope_ids

    async def _filter_activities_for_merchant(
        self,
        db: AsyncSession,
        activities: list[FullDiscountActivity],
        merchant_id: int,
    ) -> list[FullDiscountActivity]:
        product_scope_ids = {
            scope_id
            for activity in activities
            if activity.scope_type == "product"
            for scope_id in self._load_activity_scope_ids(activity)
        }
        sku_scope_ids = {
            scope_id
            for activity in activities
            if activity.scope_type == "sku"
            for scope_id in self._load_activity_scope_ids(activity)
        }
        owned_product_ids: set[int] = set()
        owned_sku_ids: set[int] = set()
        if product_scope_ids:
            result = await db.execute(
                select(Product.id).where(Product.id.in_(product_scope_ids), Product.merchant_id == merchant_id)
            )
            owned_product_ids = set(result.scalars())
        if sku_scope_ids:
            result = await db.execute(
                select(Sku.id)
                .join(Product, Sku.product_id == Product.id)
                .where(Sku.id.in_(sku_scope_ids), Product.merchant_id == merchant_id)
            )
            owned_sku_ids = set(result.scalars())
        visible: list[FullDiscountActivity] = []
        for activity in activities:
            scope_ids = set(self._load_activity_scope_ids(activity))
            if self._is_activity_visible_for_merchant(activity, merchant_id):
                visible.append(activity)
            elif activity.scope_type == "product" and scope_ids & owned_product_ids:
                visible.append(activity)
            elif activity.scope_type == "sku" and scope_ids & owned_sku_ids:
                visible.append(activity)
        return visible

    def _calculate_activity_applicable_amount(
        self,
        activity: FullDiscountActivity,
        sku_quantities: list[tuple[Sku, int]],
    ) -> int:
        total = 0
        for sku, quantity in sku_quantities:
            if self._is_sku_in_activity_scope(activity, sku):
                total += sku.price_cent * quantity
        return total

    def _calculate_repeat_full_discount(self, applicable_amount: int, activity: FullDiscountActivity) -> int:
        if applicable_amount <= 0:
            return 0
        if activity.min_amount_cent <= 0:
            return min(activity.discount_amount_cent, applicable_amount)
        if applicable_amount < activity.min_amount_cent:
            return 0
        return min((applicable_amount // activity.min_amount_cent) * activity.discount_amount_cent, applicable_amount)

    def _is_sku_in_activity_scope(self, activity: FullDiscountActivity, sku: Sku) -> bool:
        scope_type = activity.scope_type
        if scope_type in {"all", "platform"}:
            return True
        scope_ids = set(self._load_activity_scope_ids(activity))
        product: Product = sku.product
        return (
            (scope_type == "merchant" and product.merchant_id in scope_ids)
            or (scope_type == "category" and product.category_id in scope_ids)
            or (scope_type == "product" and product.id in scope_ids)
            or (scope_type == "sku" and sku.id in scope_ids)
        )

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

    def _template_to_response(self, template: CouponTemplate, received: bool = False) -> CouponTemplateResponse:
        return CouponTemplateResponse(
            id=template.id,
            name=template.name,
            scope_type=template.scope_type,
            scope_ids=self._load_scope_ids(template),
            owner_merchant_id=template.owner_merchant_id,
            created_by_admin_id=template.created_by_admin_id,
            discount_type=template.discount_type,
            discount_value=template.discount_value,
            min_amount_cent=template.min_amount_cent,
            total_quantity=template.total_quantity,
            claimed_quantity=template.claimed_quantity,
            per_user_limit=template.per_user_limit,
            status=template.status,
            valid_from=template.valid_from,
            valid_to=template.valid_to,
            received=received,
        )

    def _load_scope_ids(self, template: CouponTemplate) -> list[int]:
        try:
            value = json.loads(template.scope_ids or "[]")
        except json.JSONDecodeError:
            return []
        return [int(item) for item in value if isinstance(item, int)]

    def _is_template_visible_for_merchant(self, template: CouponTemplate, merchant_id: int) -> bool:
        if template.scope_type in {"all", "platform"}:
            return True
        scope_ids = set(self._load_scope_ids(template))
        return template.scope_type == "merchant" and merchant_id in scope_ids

    async def _filter_templates_for_merchant(
        self,
        db: AsyncSession,
        templates: list[CouponTemplate],
        merchant_id: int,
    ) -> list[CouponTemplate]:
        product_scope_ids = {
            scope_id
            for template in templates
            if template.scope_type == "product"
            for scope_id in self._load_scope_ids(template)
        }
        sku_scope_ids = {
            scope_id
            for template in templates
            if template.scope_type == "sku"
            for scope_id in self._load_scope_ids(template)
        }
        owned_product_ids: set[int] = set()
        owned_sku_ids: set[int] = set()
        if product_scope_ids:
            result = await db.execute(
                select(Product.id).where(Product.id.in_(product_scope_ids), Product.merchant_id == merchant_id)
            )
            owned_product_ids = set(result.scalars())
        if sku_scope_ids:
            result = await db.execute(
                select(Sku.id)
                .join(Product, Sku.product_id == Product.id)
                .where(Sku.id.in_(sku_scope_ids), Product.merchant_id == merchant_id)
            )
            owned_sku_ids = set(result.scalars())
        visible: list[CouponTemplate] = []
        for template in templates:
            scope_ids = set(self._load_scope_ids(template))
            if self._is_template_visible_for_merchant(template, merchant_id):
                visible.append(template)
            elif template.scope_type == "product" and scope_ids & owned_product_ids:
                visible.append(template)
            elif template.scope_type == "sku" and scope_ids & owned_sku_ids:
                visible.append(template)
        return visible

    def _calculate_applicable_amount(self, template: CouponTemplate, sku_quantities: list[tuple[Sku, int]]) -> int:
        total = 0
        for sku, quantity in sku_quantities:
            if self._is_sku_in_scope(template, sku):
                total += sku.price_cent * quantity
        return total

    def _calculate_coupon_discount_amount(self, template: CouponTemplate, applicable_amount: int) -> int:
        if template.discount_type == "amount":
            return min(template.discount_value, applicable_amount)
        return min(applicable_amount * (100 - template.discount_value) // 100, applicable_amount)

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
