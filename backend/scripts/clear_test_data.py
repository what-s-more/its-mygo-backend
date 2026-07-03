import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete

from app.db.session import AsyncSessionLocal, init_db
from app.models.community import CommunityComment, CommunityLike, CommunityPost, GrassConversionReward
from app.models.order import CartItem, Order, OrderItem, Payment, ProductReview, Refund
from app.models.product import Category, Merchant, Product, ProductImage, Sku, SkuStockLog
from app.models.promotion import CouponTemplate, UserCoupon
from app.models.user import AdminOperationLog, AdminUser, MerchantApplication, PointsLog, User, UserAddress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clear local test data for the training project.")
    parser.add_argument("--yes", action="store_true", help="confirm clearing data")
    parser.add_argument(
        "--include-platform-admins",
        action="store_true",
        help="also delete platform_operator admin accounts",
    )
    return parser


async def clear_test_data(include_platform_admins: bool) -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        for model in [
            GrassConversionReward,
            CommunityLike,
            CommunityComment,
            CommunityPost,
            ProductReview,
            Refund,
            OrderItem,
            Order,
            Payment,
            CartItem,
            UserCoupon,
            CouponTemplate,
            SkuStockLog,
            ProductImage,
            Sku,
            Product,
            Category,
            MerchantApplication,
            Merchant,
            PointsLog,
            UserAddress,
            User,
            AdminOperationLog,
        ]:
            await session.execute(delete(model))

        if include_platform_admins:
            await session.execute(delete(AdminUser))
        else:
            await session.execute(delete(AdminUser).where(AdminUser.role != "platform_operator"))

        await session.commit()


async def main() -> None:
    args = build_parser().parse_args()
    if not args.yes:
        raise SystemExit("Refusing to clear data without --yes")
    await clear_test_data(args.include_platform_admins)
    if args.include_platform_admins:
        print("cleared test data, including platform admin accounts")
    else:
        print("cleared test data, kept platform_operator admin accounts")


if __name__ == "__main__":
    asyncio.run(main())
