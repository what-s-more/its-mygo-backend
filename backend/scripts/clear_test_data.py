import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, text, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal, init_db
from app.models.community import (
    CommunityComment,
    CommunityLike,
    CommunityPost,
    CommunityPostFavorite,
    GrassConversionReward,
)
from app.models.customer_service import CustomerServiceConversation, CustomerServiceMessage
from app.models.group_buy import GroupBuyActivity, GroupBuyGroup, GroupBuyParticipant
from app.models.order import CartItem, Order, OrderItem, Payment, ProductReview, Refund, RefundLog
from app.models.product import (
    Category,
    HomeBanner,
    Merchant,
    MerchantFollow,
    Product,
    ProductFavorite,
    ProductImage,
    Sku,
    SkuStockLog,
)
from app.models.promotion import CouponTemplate, FullDiscountActivity, UserCoupon
from app.models.user import (
    AdminOperationLog,
    AdminUser,
    MerchantApplication,
    PlatformSetting,
    PointsLog,
    User,
    UserAddress,
    UserSignIn,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clear local test data for the training project.")
    parser.add_argument("--yes", action="store_true", help="confirm clearing data")
    parser.add_argument(
        "--include-platform-admins",
        action="store_true",
        help="also delete platform_operator admin accounts",
    )
    parser.add_argument(
        "--include-platform-settings",
        action="store_true",
        help="also delete platform settings such as points and member benefit configuration",
    )
    return parser


async def clear_test_data(include_platform_admins: bool, include_platform_settings: bool) -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        mysql = settings.database_url.startswith("mysql")
        if mysql:
            await session.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            await session.execute(update(Category).values(parent_id=None))

            for model in [
                CustomerServiceMessage,
                CustomerServiceConversation,
                GroupBuyParticipant,
                GroupBuyGroup,
                GroupBuyActivity,
                GrassConversionReward,
                CommunityPostFavorite,
                CommunityLike,
                CommunityComment,
                CommunityPost,
                ProductReview,
                RefundLog,
                Refund,
                OrderItem,
                Order,
                Payment,
                CartItem,
                UserCoupon,
                CouponTemplate,
                FullDiscountActivity,
                HomeBanner,
                ProductFavorite,
                MerchantFollow,
                SkuStockLog,
                ProductImage,
                Sku,
                Product,
                Category,
                MerchantApplication,
                Merchant,
                UserSignIn,
                PointsLog,
                UserAddress,
                User,
                AdminOperationLog,
            ]:
                await session.execute(delete(model))

            if include_platform_settings:
                await session.execute(delete(PlatformSetting))

            if include_platform_admins:
                await session.execute(delete(AdminUser))
            else:
                await session.execute(delete(AdminUser).where(AdminUser.role != "platform_operator"))

            await session.commit()
        finally:
            if mysql:
                await session.execute(text("SET FOREIGN_KEY_CHECKS=1"))
                await session.commit()


async def main() -> None:
    args = build_parser().parse_args()
    if not args.yes:
        raise SystemExit("Refusing to clear data without --yes")
    await clear_test_data(args.include_platform_admins, args.include_platform_settings)
    parts = ["cleared test data"]
    if args.include_platform_admins:
        parts.append("including platform admin accounts")
    else:
        parts.append("kept platform_operator admin accounts")
    if args.include_platform_settings:
        parts.append("including platform settings")
    else:
        parts.append("kept platform settings")
    print(", ".join(parts))


if __name__ == "__main__":
    asyncio.run(main())
