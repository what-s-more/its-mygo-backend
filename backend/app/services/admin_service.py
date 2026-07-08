import csv
import io
import json
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, ForbiddenException
from app.core.security import hash_password
from app.models.order import Order
from app.models.order import Refund
from app.models.product import Merchant, Product
from app.models.user import AdminUser, MerchantApplication, User
from app.schemas.admin import (
    AdminAccountResponse,
    AdminOrderDetailResponse,
    AdminOrderListItem,
    AdminUserListItem,
    DashboardSummaryResponse,
    MerchantApplicationResponse,
    MerchantApplicationUpdateRequest,
    MerchantRegisterRequest,
)
from app.schemas.order import OrderItemResponse, ShippingAddressSnapshot


class AdminService:
    effective_order_statuses = {"pending_shipment", "shipping", "pending_receipt", "completed", "after_sale"}

    async def list_users(
        self,
        db: AsyncSession,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AdminUserListItem], int]:
        statement = select(User).order_by(User.created_at.desc())
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(or_(User.mobile.like(like_keyword), User.nickname.like(like_keyword)))

        total = await self._count(db, statement)
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [AdminUserListItem.model_validate(user) for user in result.scalars()], total

    async def list_admin_accounts(
        self,
        db: AsyncSession,
        *,
        keyword: str | None,
        role: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AdminAccountResponse], int]:
        statement = select(AdminUser).order_by(AdminUser.created_at.desc())
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(
                or_(AdminUser.username.like(like_keyword), AdminUser.real_name.like(like_keyword))
            )
        if role:
            statement = statement.where(AdminUser.role == role)

        total = await self._count(db, statement)
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [AdminAccountResponse.model_validate(admin) for admin in result.scalars()], total

    async def get_admin_account(self, db: AsyncSession, admin_id: int) -> AdminUser:
        admin = await db.get(AdminUser, admin_id)
        if admin is None:
            raise AppException(40004, "管理员账号不存在", 404)
        return admin

    async def update_admin_account_status(
        self,
        db: AsyncSession,
        *,
        operator: AdminUser,
        admin_id: int,
        is_active: bool,
    ) -> AdminAccountResponse:
        admin = await self.get_admin_account(db, admin_id)
        if admin.id == operator.id and not is_active:
            raise AppException(40005, "不能禁用当前登录账号")
        admin.is_active = is_active
        await db.flush()
        return AdminAccountResponse.model_validate(admin)

    async def reset_admin_account_password(
        self,
        db: AsyncSession,
        *,
        admin_id: int,
        password: str,
    ) -> AdminAccountResponse:
        admin = await self.get_admin_account(db, admin_id)
        admin.password_hash = hash_password(password)
        await db.flush()
        return AdminAccountResponse.model_validate(admin)

    async def register_merchant_account(
        self,
        db: AsyncSession,
        payload: MerchantRegisterRequest,
    ) -> MerchantApplicationResponse:
        existing_result = await db.execute(select(AdminUser).where(AdminUser.username == payload.username))
        if existing_result.scalar_one_or_none() is not None:
            raise AppException(40005, "管理员用户名已存在")
        await self._ensure_merchant_name_available(db, payload.merchant_name)
        admin = AdminUser(
            username=payload.username,
            password_hash=hash_password(payload.password),
            real_name=payload.real_name,
            role="merchant_pending",
            merchant_id=None,
        )
        db.add(admin)
        await db.flush()
        application = MerchantApplication(
            admin_id=admin.id,
            merchant_name=payload.merchant_name,
            logo_url=payload.logo_url,
            announcement=payload.announcement,
            status="pending",
        )
        db.add(application)
        await db.commit()
        await db.refresh(application)
        return MerchantApplicationResponse.model_validate(application)

    async def get_merchant_application_by_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
    ) -> MerchantApplicationResponse | None:
        result = await db.execute(select(MerchantApplication).where(MerchantApplication.admin_id == admin.id))
        application = result.scalar_one_or_none()
        return MerchantApplicationResponse.model_validate(application) if application is not None else None

    async def update_merchant_application_by_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        payload: MerchantApplicationUpdateRequest,
    ) -> MerchantApplicationResponse:
        result = await db.execute(select(MerchantApplication).where(MerchantApplication.admin_id == admin.id))
        application = result.scalar_one_or_none()
        if application is None:
            raise AppException(40004, "商家入驻申请不存在", 404)
        if application.status == "approved":
            raise AppException(40008, "已通过的入驻申请不允许重新提交")
        fields = payload.model_fields_set
        if "merchant_name" in fields and payload.merchant_name is not None:
            await self._ensure_merchant_name_available(db, payload.merchant_name)
            application.merchant_name = payload.merchant_name
        if "logo_url" in fields:
            application.logo_url = payload.logo_url
        if "announcement" in fields:
            application.announcement = payload.announcement
        application.status = "pending"
        application.reject_reason = None
        application.reviewed_by = None
        application.reviewed_at = None
        await db.commit()
        await db.refresh(application)
        return MerchantApplicationResponse.model_validate(application)

    async def list_merchant_applications(
        self,
        db: AsyncSession,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[MerchantApplicationResponse], int]:
        statement = select(MerchantApplication).order_by(MerchantApplication.created_at.desc())
        if status:
            statement = statement.where(MerchantApplication.status == status)
        total = await self._count(db, statement)
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [MerchantApplicationResponse.model_validate(item) for item in result.scalars()], total

    async def audit_merchant_application(
        self,
        db: AsyncSession,
        reviewer: AdminUser,
        application_id: int,
        *,
        approved: bool,
        reject_reason: str | None = None,
    ) -> MerchantApplicationResponse:
        application = await db.get(MerchantApplication, application_id)
        if application is None:
            raise AppException(40004, "商家入驻申请不存在", 404)
        if application.status != "pending":
            raise AppException(40008, "当前入驻申请状态不允许审核")
        applicant = await db.get(AdminUser, application.admin_id)
        if applicant is None:
            raise AppException(40004, "申请账号不存在", 404)
        application.reviewed_by = reviewer.id
        application.reviewed_at = datetime.now(UTC)
        if approved:
            await self._ensure_merchant_name_available(db, application.merchant_name)
            merchant = Merchant(
                name=application.merchant_name,
                logo_url=application.logo_url,
                announcement=None,
            )
            db.add(merchant)
            await db.flush()
            applicant.role = "merchant_operator"
            applicant.merchant_id = merchant.id
            application.merchant_id = merchant.id
            application.status = "approved"
            application.reject_reason = None
        else:
            application.status = "rejected"
            application.reject_reason = reject_reason or "平台审核未通过"
        await db.commit()
        await db.refresh(application)
        return MerchantApplicationResponse.model_validate(application)

    async def list_orders(
        self,
        db: AsyncSession,
        admin: AdminUser,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AdminOrderListItem], int]:
        statement = self._order_scope(select(Order), admin).order_by(Order.created_at.desc())
        if status:
            statement = statement.where(Order.status == status)

        total = await self._count(db, statement)
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        return [AdminOrderListItem.model_validate(order) for order in result.scalars()], total

    async def export_orders_csv(
        self,
        db: AsyncSession,
        admin: AdminUser,
        *,
        status: str | None,
    ) -> str:
        statement = self._order_scope(select(Order), admin).order_by(Order.created_at.desc())
        if status:
            statement = statement.where(Order.status == status)
        result = await db.execute(statement)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "order_no",
                "payment_id",
                "user_id",
                "merchant_id",
                "status",
                "total_amount_cent",
                "pay_amount_cent",
                "created_at",
            ]
        )
        for order in result.scalars():
            writer.writerow(
                [
                    order.id,
                    order.order_no,
                    order.payment_id,
                    order.user_id,
                    order.merchant_id,
                    order.status,
                    order.total_amount_cent,
                    order.pay_amount_cent,
                    order.created_at.isoformat() if order.created_at else "",
                ]
            )
        return output.getvalue()

    async def get_order(self, db: AsyncSession, admin: AdminUser, order_id: int) -> AdminOrderDetailResponse:
        result = await db.execute(
            self._order_scope(select(Order), admin)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
        )
        order = result.scalars().unique().one_or_none()
        if order is None:
            raise AppException(40004, "订单不存在", 404)
        return self._to_order_detail_response(order)

    async def assert_can_operate_order(self, db: AsyncSession, admin: AdminUser, order_id: int) -> None:
        await self.get_order(db, admin, order_id)

    async def assert_can_operate_refund(self, db: AsyncSession, admin: AdminUser, refund_id: int) -> None:
        refund = await db.get(Refund, refund_id)
        if refund is None:
            raise AppException(40004, "售后单不存在", 404)
        await self.get_order(db, admin, refund.order_id)

    async def get_dashboard_summary(self, db: AsyncSession, admin: AdminUser) -> DashboardSummaryResponse:
        order_statement = self._order_scope(select(Order), admin)
        effective_statement = order_statement.where(Order.status.in_(self.effective_order_statuses))

        user_count = await db.scalar(select(func.count()).select_from(User)) or 0
        product_count_statement = select(func.count()).select_from(Product)
        if admin.role == "merchant_operator":
            if admin.merchant_id is None:
                product_count = 0
            else:
                product_count = (
                    await db.scalar(product_count_statement.where(Product.merchant_id == admin.merchant_id)) or 0
                )
        else:
            product_count = await db.scalar(product_count_statement) or 0

        order_count = await self._count(db, order_statement)
        paid_order_count = await self._count(db, effective_statement)
        gross_merchandise_cent = await db.scalar(
            select(func.coalesce(func.sum(effective_statement.subquery().c.pay_amount_cent), 0))
        ) or 0
        pending_shipment_count = await self._count(db, order_statement.where(Order.status == "pending_shipment"))
        after_sale_count = await self._count(db, order_statement.where(Order.status == "after_sale"))

        return DashboardSummaryResponse(
            user_count=user_count,
            product_count=product_count,
            order_count=order_count,
            paid_order_count=paid_order_count,
            gross_merchandise_cent=gross_merchandise_cent,
            pending_shipment_count=pending_shipment_count,
            after_sale_count=after_sale_count,
        )

    def _order_scope(self, statement: Select[tuple[Order]], admin: AdminUser) -> Select[tuple[Order]]:
        if admin.role not in {"platform_operator", "merchant_operator"}:
            raise ForbiddenException("当前账号尚未获得商家管理权限")
        if admin.role == "merchant_operator":
            if admin.merchant_id is None:
                raise ForbiddenException("商家管理员未绑定店铺")
            return statement.where(
                Order.merchant_id == admin.merchant_id,
                Order.status != "group_pending",
            )
        return statement

    async def _count(self, db: AsyncSession, statement: Select) -> int:
        return await db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0

    async def _ensure_merchant_name_available(
        self,
        db: AsyncSession,
        merchant_name: str,
        *,
        exclude_merchant_id: int | None = None,
    ) -> None:
        statement = select(Merchant.id).where(Merchant.name == merchant_name)
        if exclude_merchant_id is not None:
            statement = statement.where(Merchant.id != exclude_merchant_id)
        existing_result = await db.execute(statement)
        if existing_result.scalar_one_or_none() is not None:
            raise AppException(40005, "店铺名称已存在")

    def _to_order_detail_response(self, order: Order) -> AdminOrderDetailResponse:
        shipping_address = None
        if order.shipping_address_snapshot:
            shipping_address = ShippingAddressSnapshot(**json.loads(order.shipping_address_snapshot))
        return AdminOrderDetailResponse(
            id=order.id,
            order_no=order.order_no,
            payment_id=order.payment_id,
            user_id=order.user_id,
            merchant_id=order.merchant_id,
            status=order.status,
            total_amount_cent=order.total_amount_cent,
            pay_amount_cent=order.pay_amount_cent,
            created_at=order.created_at,
            shipping_address=shipping_address,
            logistics_company=order.logistics_company,
            tracking_no=order.tracking_no,
            shipped_at=order.shipped_at.isoformat() if order.shipped_at else None,
            received_at=order.received_at.isoformat() if order.received_at else None,
            items=[OrderItemResponse.model_validate(item) for item in order.items],
        )


admin_service = AdminService()
