from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.models.community import CommunityComment, CommunityLike, CommunityPost, GrassConversionReward
from app.models.group_buy import GroupBuyActivity, GroupBuyGroup
from app.models.order import Order, OrderItem, Refund
from app.models.product import Merchant, Product
from app.models.promotion import CouponTemplate, FullDiscountActivity, UserCoupon
from app.models.user import AdminUser, User
from app.schemas.report import (
    ReportMetric,
    ReportNameValue,
    ReportOverviewResponse,
    ReportSeriesPoint,
    ReportTimeRange,
    ReportTopProduct,
)


class ReportService:
    effective_order_statuses = {"pending_shipment", "shipping", "pending_receipt", "completed", "after_sale"}

    async def get_overview(self, db: AsyncSession, admin: AdminUser, scope: str) -> ReportOverviewResponse:
        merchant_id = self._resolve_scope(admin, scope)
        today = datetime.now(UTC).date()
        date_from = today - timedelta(days=29)
        return ReportOverviewResponse(
            scope=scope,
            scope_id=merchant_id,
            time_range=ReportTimeRange(date_from=date_from.isoformat(), date_to=today.isoformat()),
            generated_at=datetime.now(UTC),
            summary=await self._summary(db, merchant_id),
            sales_trend=await self._sales_trend(db, merchant_id),
            order_status=await self._order_status(db, merchant_id),
            top_products=await self._top_products(db, merchant_id),
            top_merchants=await self._top_merchants(db) if merchant_id is None else [],
            refund_status=await self._refund_status(db, merchant_id),
            promotion_summary=await self._promotion_summary(db, merchant_id),
            community_summary=await self._community_summary(db, merchant_id),
        )

    def _resolve_scope(self, admin: AdminUser, scope: str) -> int | None:
        if scope == "platform":
            if admin.role != "platform_operator":
                raise ForbiddenException("只有平台运营可查看平台报表")
            return None
        if scope == "merchant":
            if admin.role != "merchant_operator" or admin.merchant_id is None:
                raise ForbiddenException("只有已绑定店铺的商家运营可查看商家报表")
            return admin.merchant_id
        raise ForbiddenException("不支持的报表范围")

    async def _summary(self, db: AsyncSession, merchant_id: int | None) -> list[ReportMetric]:
        order_scope = self._order_scope(select(Order), merchant_id)
        effective_scope = order_scope.where(Order.status.in_(self.effective_order_statuses))
        effective_subquery = effective_scope.subquery()
        refund_scope = self._refund_scope(select(Refund), merchant_id)
        refund_subquery = refund_scope.subquery()
        gmv = await db.scalar(select(func.coalesce(func.sum(effective_subquery.c.pay_amount_cent), 0))) or 0
        refund_amount = await db.scalar(select(func.coalesce(func.sum(refund_subquery.c.refund_amount_cent), 0))) or 0
        return [
            ReportMetric(key="gmv_cent", label="成交额", value=int(gmv), unit="cent"),
            ReportMetric(key="order_count", label="订单数", value=await self._count(db, order_scope)),
            ReportMetric(key="paid_order_count", label="有效订单", value=await self._count(db, effective_scope)),
            ReportMetric(key="refund_count", label="售后数", value=await self._count(db, refund_scope)),
            ReportMetric(key="refund_amount_cent", label="退款金额", value=int(refund_amount), unit="cent"),
            ReportMetric(key="product_count", label="商品数", value=await self._count(db, self._product_scope(select(Product), merchant_id))),
            ReportMetric(key="user_count", label="用户数", value=await self._count(db, select(User)) if merchant_id is None else 0),
            ReportMetric(key="merchant_count", label="商家数", value=await self._count(db, select(Merchant)) if merchant_id is None else 1),
        ]

    async def _sales_trend(self, db: AsyncSession, merchant_id: int | None) -> list[ReportSeriesPoint]:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=6)
        statement = self._order_scope(select(Order), merchant_id).where(
            Order.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
            Order.status.in_(self.effective_order_statuses),
        )
        order_subquery = statement.subquery()
        rows = await db.execute(
            select(
                func.date(order_subquery.c.created_at).label("date"),
                func.count().label("order_count"),
                func.coalesce(func.sum(order_subquery.c.pay_amount_cent), 0).label("gmv_cent"),
            ).group_by("date")
        )
        order_by_date = {str(row.date): row for row in rows}
        refund_rows = await db.execute(
            select(
                func.date(Refund.created_at).label("date"),
                func.coalesce(func.sum(Refund.refund_amount_cent), 0).label("refund_amount_cent"),
            )
            .select_from(Refund)
            .join(Order, Refund.order_id == Order.id)
            .where(
                Refund.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                *([] if merchant_id is None else [Order.merchant_id == merchant_id]),
            )
            .group_by("date")
        )
        refund_by_date = {str(row.date): int(row.refund_amount_cent or 0) for row in refund_rows}
        return [
            ReportSeriesPoint(
                date=(start + timedelta(days=offset)).isoformat(),
                order_count=int(order_by_date.get((start + timedelta(days=offset)).isoformat()).order_count)
                if order_by_date.get((start + timedelta(days=offset)).isoformat())
                else 0,
                gmv_cent=int(order_by_date.get((start + timedelta(days=offset)).isoformat()).gmv_cent)
                if order_by_date.get((start + timedelta(days=offset)).isoformat())
                else 0,
                refund_amount_cent=refund_by_date.get((start + timedelta(days=offset)).isoformat(), 0),
            )
            for offset in range(7)
        ]

    async def _order_status(self, db: AsyncSession, merchant_id: int | None) -> list[ReportNameValue]:
        statement = self._order_scope(select(Order.status, func.count().label("count")), merchant_id).group_by(Order.status)
        rows = await db.execute(statement)
        return [ReportNameValue(name=row.status, value=int(row.count or 0)) for row in rows]

    async def _top_products(self, db: AsyncSession, merchant_id: int | None) -> list[ReportTopProduct]:
        statement = (
            select(
                OrderItem.product_id,
                OrderItem.product_name,
                func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity"),
                func.coalesce(func.sum(OrderItem.total_amount_cent), 0).label("amount_cent"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.status.in_(self.effective_order_statuses))
        )
        if merchant_id is not None:
            statement = statement.where(Order.merchant_id == merchant_id)
        rows = await db.execute(
            statement.group_by(OrderItem.product_id, OrderItem.product_name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(10)
        )
        return [
            ReportTopProduct(
                product_id=row.product_id,
                product_name=row.product_name,
                quantity=int(row.quantity or 0),
                amount_cent=int(row.amount_cent or 0),
            )
            for row in rows
        ]

    async def _top_merchants(self, db: AsyncSession) -> list[ReportNameValue]:
        rows = await db.execute(
            select(
                Merchant.id,
                Merchant.name,
                func.coalesce(func.sum(Order.pay_amount_cent), 0).label("amount_cent"),
            )
            .join(Order, Order.merchant_id == Merchant.id)
            .where(Order.status.in_(self.effective_order_statuses))
            .group_by(Merchant.id, Merchant.name)
            .order_by(func.sum(Order.pay_amount_cent).desc())
            .limit(10)
        )
        return [
            ReportNameValue(id=row.id, name=row.name, value=int(row.amount_cent or 0), amount_cent=int(row.amount_cent or 0))
            for row in rows
        ]

    async def _refund_status(self, db: AsyncSession, merchant_id: int | None) -> list[ReportNameValue]:
        statement = select(Refund.status, func.count().label("count")).select_from(Refund).join(Order, Refund.order_id == Order.id)
        if merchant_id is not None:
            statement = statement.where(Order.merchant_id == merchant_id)
        rows = await db.execute(statement.group_by(Refund.status))
        return [ReportNameValue(name=row.status, value=int(row.count or 0)) for row in rows]

    async def _promotion_summary(self, db: AsyncSession, merchant_id: int | None) -> list[ReportMetric]:
        coupon_scope = select(CouponTemplate)
        full_scope = select(FullDiscountActivity)
        group_scope = select(GroupBuyActivity)
        merchant_filters = []
        if merchant_id is not None:
            coupon_scope = coupon_scope.where(CouponTemplate.owner_merchant_id == merchant_id)
            full_scope = full_scope.where(FullDiscountActivity.owner_merchant_id == merchant_id)
            group_scope = group_scope.where(GroupBuyActivity.merchant_id == merchant_id)
            merchant_filters.append(CouponTemplate.owner_merchant_id == merchant_id)
        claimed = await db.scalar(
            select(func.count()).select_from(UserCoupon).join(CouponTemplate, UserCoupon.coupon_template_id == CouponTemplate.id).where(*merchant_filters)
        ) or 0
        used = await db.scalar(
            select(func.count())
            .select_from(UserCoupon)
            .join(CouponTemplate, UserCoupon.coupon_template_id == CouponTemplate.id)
            .where(UserCoupon.status == "used", *merchant_filters)
        ) or 0
        group_filters = [GroupBuyGroup.status == "success"]
        if merchant_id is not None:
            group_filters.append(GroupBuyActivity.merchant_id == merchant_id)
        group_success = await db.scalar(
            select(func.count())
            .select_from(GroupBuyGroup)
            .join(GroupBuyActivity, GroupBuyGroup.activity_id == GroupBuyActivity.id)
            .where(*group_filters)
        ) or 0
        return [
            ReportMetric(key="coupon_count", label="优惠券模板", value=await self._count(db, coupon_scope)),
            ReportMetric(key="coupon_claimed_count", label="领券数", value=int(claimed)),
            ReportMetric(key="coupon_used_count", label="用券数", value=int(used)),
            ReportMetric(key="full_discount_count", label="满减活动", value=await self._count(db, full_scope)),
            ReportMetric(key="group_buy_count", label="拼团活动", value=await self._count(db, group_scope)),
            ReportMetric(key="group_success_count", label="成团数", value=int(group_success)),
        ]

    async def _community_summary(self, db: AsyncSession, merchant_id: int | None) -> list[ReportMetric]:
        post_scope = select(CommunityPost)
        comment_scope = select(CommunityComment)
        like_scope = select(CommunityLike)
        if merchant_id is not None:
            post_scope = post_scope.where(CommunityPost.merchant_id == merchant_id)
            comment_scope = comment_scope.join(CommunityPost, CommunityComment.post_id == CommunityPost.id).where(
                CommunityPost.merchant_id == merchant_id,
                CommunityComment.status == "published",
            )
            like_scope = like_scope.join(CommunityPost, CommunityLike.post_id == CommunityPost.id).where(
                CommunityPost.merchant_id == merchant_id,
                CommunityPost.status == "published",
            )
        grass_rewards = select(GrassConversionReward)
        if merchant_id is not None:
            grass_rewards = grass_rewards.join(Order, GrassConversionReward.order_id == Order.id).where(Order.merchant_id == merchant_id)
        reward_subquery = grass_rewards.subquery()
        reward_points = await db.scalar(select(func.coalesce(func.sum(reward_subquery.c.points), 0))) or 0
        return [
            ReportMetric(key="post_count", label="帖子数", value=await self._count(db, post_scope)),
            ReportMetric(key="comment_count", label="评论数", value=await self._count(db, comment_scope)),
            ReportMetric(key="like_count", label="点赞数", value=await self._count(db, like_scope)),
            ReportMetric(key="grass_conversion_count", label="种草转化", value=await self._count(db, grass_rewards)),
            ReportMetric(key="grass_reward_points", label="种草奖励积分", value=int(reward_points)),
        ]

    def _order_scope(self, statement: Select, merchant_id: int | None) -> Select:
        if merchant_id is None:
            return statement
        return statement.where(Order.merchant_id == merchant_id, Order.status != "group_pending")

    def _product_scope(self, statement: Select, merchant_id: int | None) -> Select:
        if merchant_id is None:
            return statement
        return statement.where(Product.merchant_id == merchant_id)

    def _refund_scope(self, statement: Select, merchant_id: int | None) -> Select:
        if merchant_id is None:
            return statement
        return statement.join(Order, Refund.order_id == Order.id).where(Order.merchant_id == merchant_id)

    async def _count(self, db: AsyncSession, statement: Select) -> int:
        return await db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0


report_service = ReportService()
