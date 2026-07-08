from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, ForbiddenException
from app.models.group_buy import GroupBuyActivity, GroupBuyGroup, GroupBuyParticipant
from app.models.order import Order, Payment
from app.models.product import Product, Sku
from app.models.user import AdminUser, User
from app.schemas.group_buy import (
    GroupBuyActivityCreateRequest,
    GroupBuyActivityResponse,
    GroupBuyGroupSummary,
    GroupBuyJoinRequest,
    GroupBuyOrderResponse,
    GroupBuyStartRequest,
)
from app.services.order_service import order_service
from app.services.product_service import product_service


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class GroupBuyService:
    async def create_activity(
        self,
        db: AsyncSession,
        admin: AdminUser,
        payload: GroupBuyActivityCreateRequest,
    ) -> GroupBuyActivityResponse:
        sku = await self._get_sku(db, payload.sku_id)
        if sku.product_id != payload.product_id:
            raise AppException(40005, "SKU 不属于该商品")
        if admin.role != "merchant_operator" or admin.merchant_id is None:
            raise ForbiddenException("拼团活动必须由已入驻商家创建")
        if sku.product.merchant_id != admin.merchant_id:
            raise ForbiddenException("只能为本店商品创建拼团")
        if payload.group_price_cent >= sku.price_cent:
            raise AppException(40005, "拼团价应低于商品原价")
        activity = GroupBuyActivity(
            merchant_id=admin.merchant_id,
            product_id=payload.product_id,
            sku_id=payload.sku_id,
            name=payload.name,
            group_size=payload.group_size,
            group_price_cent=payload.group_price_cent,
            valid_from=_to_naive_utc(payload.valid_from),
            valid_to=_to_naive_utc(payload.valid_to),
            created_by_admin_id=admin.id,
            status="active",
        )
        db.add(activity)
        await db.commit()
        await db.refresh(activity)
        return await self.to_activity_response(db, activity)

    async def list_activities(
        self,
        db: AsyncSession,
        *,
        merchant_id: int | None = None,
        only_active: bool = True,
    ) -> list[GroupBuyActivityResponse]:
        statement = select(GroupBuyActivity).order_by(GroupBuyActivity.created_at.desc())
        if merchant_id is not None:
            statement = statement.where(GroupBuyActivity.merchant_id == merchant_id)
        if only_active:
            now = _utc_now_naive()
            statement = statement.where(GroupBuyActivity.status == "active")
            statement = statement.where(
                (GroupBuyActivity.valid_from.is_(None)) | (GroupBuyActivity.valid_from <= now)
            )
            statement = statement.where((GroupBuyActivity.valid_to.is_(None)) | (GroupBuyActivity.valid_to >= now))
        result = await db.execute(statement)
        return [await self.to_activity_response(db, activity) for activity in result.scalars()]

    async def list_admin_activities(self, db: AsyncSession, admin: AdminUser) -> list[GroupBuyActivityResponse]:
        merchant_id = admin.merchant_id if admin.role == "merchant_operator" else None
        return await self.list_activities(db, merchant_id=merchant_id, only_active=False)

    async def disable_activity(self, db: AsyncSession, admin: AdminUser, activity_id: int) -> GroupBuyActivityResponse:
        activity = await self._get_activity(db, activity_id)
        if admin.role == "merchant_operator" and activity.merchant_id != admin.merchant_id:
            raise ForbiddenException("只能停用本店拼团活动")
        if admin.role not in {"platform_operator", "merchant_operator"}:
            raise ForbiddenException()
        activity.status = "disabled"
        await db.commit()
        await db.refresh(activity)
        return await self.to_activity_response(db, activity)

    async def start_group(self, db: AsyncSession, user: User, payload: GroupBuyStartRequest) -> GroupBuyOrderResponse:
        activity = await self._get_available_activity(db, payload.activity_id)
        group = GroupBuyGroup(
            activity_id=activity.id,
            leader_user_id=user.id,
            status="pending",
            expire_at=_utc_now_naive() + timedelta(hours=24),
        )
        db.add(group)
        await db.flush()
        return await self._create_participation_order(db, user, activity, group, payload)

    async def join_group(self, db: AsyncSession, user: User, payload: GroupBuyJoinRequest) -> GroupBuyOrderResponse:
        group = await self._get_group(db, payload.group_id)
        activity = await self._get_available_activity(db, group.activity_id)
        if group.status != "pending":
            raise AppException(40008, "当前团不可加入")
        if _to_naive_utc(group.expire_at) <= _utc_now_naive():
            group.status = "expired"
            await db.commit()
            raise AppException(40008, "拼团已过期")
        if await self._user_joined_group(db, group.id, user.id):
            raise AppException(40005, "同一用户不能重复加入同一个团")
        if await self._paid_participant_count(db, group.id) >= activity.group_size:
            group.status = "success"
            await db.commit()
            raise AppException(40008, "拼团已满员")
        return await self._create_participation_order(db, user, activity, group, payload)

    async def sync_group_after_payment(self, db: AsyncSession, group_id: int) -> None:
        group = await self._get_group(db, group_id)
        activity = await self._get_activity(db, group.activity_id)
        paid_count = await self._paid_participant_count(db, group.id)
        if group.status == "pending" and paid_count >= activity.group_size:
            group.status = "success"
            group.success_at = _utc_now_naive()
            await order_service.mark_group_success_orders(db, group.id)

    async def sync_groups_for_payment(self, db: AsyncSession, payment: Payment) -> None:
        group_ids = {order.group_buy_group_id for order in payment.orders if order.group_buy_group_id is not None}
        for group_id in group_ids:
            await self.sync_group_after_payment(db, group_id)

    async def to_activity_response(
        self,
        db: AsyncSession,
        activity: GroupBuyActivity,
    ) -> GroupBuyActivityResponse:
        product_result = await db.execute(
            select(Product)
            .where(Product.id == activity.product_id)
            .options(selectinload(Product.merchant), selectinload(Product.skus), selectinload(Product.images))
        )
        product = product_result.scalars().unique().one_or_none()
        active_groups = await self.list_active_groups(db, activity.id)
        return GroupBuyActivityResponse(
            id=activity.id,
            merchant_id=activity.merchant_id,
            product_id=activity.product_id,
            sku_id=activity.sku_id,
            name=activity.name,
            group_size=activity.group_size,
            group_price_cent=activity.group_price_cent,
            status=activity.status,
            valid_from=activity.valid_from,
            valid_to=activity.valid_to,
            created_by_admin_id=activity.created_by_admin_id,
            product=product_service.to_list_item(product) if product is not None else None,
            active_groups=active_groups,
        )

    async def list_active_groups(self, db: AsyncSession, activity_id: int) -> list[GroupBuyGroupSummary]:
        now = _utc_now_naive()
        result = await db.execute(
            select(GroupBuyGroup)
            .where(
                GroupBuyGroup.activity_id == activity_id,
                GroupBuyGroup.status == "pending",
                GroupBuyGroup.expire_at > now,
            )
            .order_by(GroupBuyGroup.created_at.asc())
        )
        groups = list(result.scalars())
        activity = await self._get_activity(db, activity_id)
        return [
            GroupBuyGroupSummary(
                id=group.id,
                activity_id=group.activity_id,
                leader_user_id=group.leader_user_id,
                status=group.status,
                joined_count=await self._paid_participant_count(db, group.id),
                group_size=activity.group_size,
                expire_at=group.expire_at,
                success_at=group.success_at,
            )
            for group in groups
        ]

    async def _create_participation_order(
        self,
        db: AsyncSession,
        user: User,
        activity: GroupBuyActivity,
        group: GroupBuyGroup,
        payload: GroupBuyStartRequest | GroupBuyJoinRequest,
    ) -> GroupBuyOrderResponse:
        sku = await self._get_sku(db, activity.sku_id)
        order_response = await order_service.create_group_buy_order(
            db,
            user,
            sku=sku,
            quantity=payload.quantity,
            unit_price_cent=activity.group_price_cent,
            client_order_token=payload.client_order_token,
            shipping_address_id=payload.shipping_address_id,
            points_used=payload.points_used,
            group_id=group.id,
            activity_id=activity.id,
        )
        participant = GroupBuyParticipant(
            group_id=group.id,
            activity_id=activity.id,
            user_id=user.id,
            order_id=order_response.order_ids[0],
            payment_id=order_response.payment_id,
            status="pending_payment",
        )
        db.add(participant)
        await db.commit()
        await db.refresh(group)
        return GroupBuyOrderResponse(group=await self._group_summary(db, group), order=order_response)

    async def _group_summary(self, db: AsyncSession, group: GroupBuyGroup) -> GroupBuyGroupSummary:
        activity = await self._get_activity(db, group.activity_id)
        return GroupBuyGroupSummary(
            id=group.id,
            activity_id=group.activity_id,
            leader_user_id=group.leader_user_id,
            status=group.status,
            joined_count=await self._paid_participant_count(db, group.id),
            group_size=activity.group_size,
            expire_at=group.expire_at,
            success_at=group.success_at,
        )

    async def _get_activity(self, db: AsyncSession, activity_id: int) -> GroupBuyActivity:
        activity = await db.get(GroupBuyActivity, activity_id)
        if activity is None:
            raise AppException(40004, "拼团活动不存在", 404)
        return activity

    async def _get_available_activity(self, db: AsyncSession, activity_id: int) -> GroupBuyActivity:
        activity = await self._get_activity(db, activity_id)
        now = _utc_now_naive()
        if activity.status != "active":
            raise AppException(40008, "拼团活动不可用")
        if activity.valid_from is not None and activity.valid_from > now:
            raise AppException(40008, "拼团活动未开始")
        if activity.valid_to is not None and activity.valid_to < now:
            raise AppException(40008, "拼团活动已结束")
        return activity

    async def _get_group(self, db: AsyncSession, group_id: int) -> GroupBuyGroup:
        group = await db.get(GroupBuyGroup, group_id)
        if group is None:
            raise AppException(40004, "拼团不存在", 404)
        return group

    async def _get_sku(self, db: AsyncSession, sku_id: int) -> Sku:
        result = await db.execute(
            select(Sku).where(Sku.id == sku_id).options(selectinload(Sku.product).selectinload(Product.merchant))
        )
        sku = result.scalars().one_or_none()
        if sku is None:
            raise AppException(40004, "SKU 不存在", 404)
        return sku

    async def _paid_participant_count(self, db: AsyncSession, group_id: int) -> int:
        result = await db.execute(
            select(GroupBuyParticipant).where(GroupBuyParticipant.group_id == group_id, GroupBuyParticipant.status == "paid")
        )
        return len(list(result.scalars()))

    async def _user_joined_group(self, db: AsyncSession, group_id: int, user_id: int) -> bool:
        result = await db.execute(
            select(GroupBuyParticipant).where(
                GroupBuyParticipant.group_id == group_id,
                GroupBuyParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None


group_buy_service = GroupBuyService()
