from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user, get_optional_current_user
from app.models.user import User
from app.schemas.promotion import CouponTemplateResponse, FullDiscountResponse, UserCouponResponse
from app.services.promotion_service import promotion_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/coupons", response_model=ApiResponse[list[CouponTemplateResponse]])
async def list_available_coupons(
    db: DbSession,
    merchant_id: int | None = None,
    current_user: User | None = Depends(get_optional_current_user),
) -> ApiResponse[list[CouponTemplateResponse]]:
    return success(
        await promotion_service.list_coupon_templates(
            db,
            only_available=True,
            merchant_id=merchant_id,
            user_id=current_user.id if current_user else None,
        )
    )


@router.post("/coupons/{coupon_template_id}/claim", response_model=ApiResponse[UserCouponResponse])
async def claim_coupon(
    coupon_template_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[UserCouponResponse]:
    return success(await promotion_service.claim_coupon(db, current_user, coupon_template_id))


@router.get("/my-coupons", response_model=ApiResponse[list[UserCouponResponse]])
async def list_my_coupons(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    status: str | None = None,
) -> ApiResponse[list[UserCouponResponse]]:
    return success(await promotion_service.list_user_coupons(db, current_user, status=status))


@router.get("/full-discounts/active", response_model=ApiResponse[list[FullDiscountResponse]])
async def list_active_full_discounts(
    db: DbSession,
    merchant_id: int | None = None,
) -> ApiResponse[list[FullDiscountResponse]]:
    return success(await promotion_service.list_full_discounts(db, only_available=True, merchant_id=merchant_id))
