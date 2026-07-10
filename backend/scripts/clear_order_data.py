import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, select, text, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal, init_db
from app.models.community import GrassConversionReward
from app.models.customer_service import CustomerServiceConversation, CustomerServiceMessage
from app.models.group_buy import GroupBuyGroup, GroupBuyParticipant
from app.models.order import Order, OrderItem, Payment, ProductReview, Refund, RefundLog
from app.models.promotion import UserCoupon
from app.models.user import PointsLog, User


ORDER_POINT_SOURCE_TYPES = {
    "order_points_deduction",
    "order_points_restore",
    "grass_conversion_reward",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clear only order-related data. Users, admins, merchants, products, "
            "categories, promotion templates, community posts, and cart items are kept."
        )
    )
    parser.add_argument("--yes", action="store_true", help="confirm clearing order data")
    parser.add_argument(
        "--restore-points",
        action="store_true",
        help=(
            "also reverse order-related point logs against user.points, then delete those logs. "
            "Use this if test orders consumed or granted points and you want user point balances restored."
        ),
    )
    return parser


async def clear_order_data(restore_points: bool) -> dict[str, int]:
    await init_db()
    async with AsyncSessionLocal() as session:
        mysql = settings.database_url.startswith("mysql")
        if mysql:
            await session.execute(text("SET FOREIGN_KEY_CHECKS=0"))

        try:
            order_ids = list((await session.execute(select(Order.id))).scalars().all())
            payment_ids = list((await session.execute(select(Payment.id))).scalars().all())
            conversation_ids = list(
                (
                    await session.execute(
                        select(CustomerServiceConversation.id).where(CustomerServiceConversation.order_id.is_not(None))
                    )
                )
                .scalars()
                .all()
            )

            counts = {
                "orders": len(order_ids),
                "payments": len(payment_ids),
                "order_customer_service_conversations": len(conversation_ids),
                "point_logs_deleted": 0,
                "users_points_adjusted": 0,
            }

            if restore_points:
                rows = (
                    await session.execute(
                        select(PointsLog.user_id, func.coalesce(func.sum(PointsLog.change_points), 0))
                        .where(
                            PointsLog.source_type.in_(ORDER_POINT_SOURCE_TYPES),
                            PointsLog.source_id.in_(order_ids) if order_ids else False,
                        )
                        .group_by(PointsLog.user_id)
                    )
                ).all()
                for user_id, change_sum in rows:
                    # Reverse the logged order-side effect: deduction logs are negative, rewards are positive.
                    await session.execute(
                        update(User)
                        .where(User.id == user_id)
                        .values(points=User.points - int(change_sum or 0))
                    )
                counts["users_points_adjusted"] = len(rows)
                result = await session.execute(
                    delete(PointsLog).where(
                        PointsLog.source_type.in_(ORDER_POINT_SOURCE_TYPES),
                        PointsLog.source_id.in_(order_ids) if order_ids else False,
                    )
                )
                counts["point_logs_deleted"] = int(result.rowcount or 0)

            if order_ids:
                await session.execute(
                    update(UserCoupon)
                    .where(UserCoupon.order_id.in_(order_ids))
                    .values(status="unused", order_id=None, used_at=None)
                )

            if conversation_ids:
                await session.execute(
                    delete(CustomerServiceMessage).where(CustomerServiceMessage.conversation_id.in_(conversation_ids))
                )
                await session.execute(delete(CustomerServiceConversation).where(CustomerServiceConversation.id.in_(conversation_ids)))

            for model in [
                GrassConversionReward,
                GroupBuyParticipant,
                GroupBuyGroup,
                ProductReview,
                RefundLog,
                Refund,
                OrderItem,
                Order,
                Payment,
            ]:
                await session.execute(delete(model))

            await session.commit()
            return counts
        finally:
            if mysql:
                await session.execute(text("SET FOREIGN_KEY_CHECKS=1"))
                await session.commit()


async def main() -> None:
    args = build_parser().parse_args()
    if not args.yes:
        raise SystemExit("Refusing to clear order data without --yes")

    counts = await clear_order_data(args.restore_points)
    print("cleared order data")
    print(f"- orders: {counts['orders']}")
    print(f"- payments: {counts['payments']}")
    print(f"- order customer service conversations: {counts['order_customer_service_conversations']}")
    if args.restore_points:
        print(f"- point logs deleted: {counts['point_logs_deleted']}")
        print(f"- users point balances adjusted: {counts['users_points_adjusted']}")
    else:
        print("- points were not restored; rerun with --restore-points if needed")


if __name__ == "__main__":
    asyncio.run(main())
