from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.auth import UserProfileResponse, UserProfileUpdateRequest
from app.schemas.user import MemberLevelResponse, PointsAccountResponse, SignInResponse
from app.services.product_service import product_service
from app.services.points_service import points_service
from app.services.user_service import user_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/profile", response_model=ApiResponse[UserProfileResponse])
async def profile(current_user: User = Depends(get_current_user)) -> ApiResponse[UserProfileResponse]:
    return success(UserProfileResponse.model_validate(current_user))


@router.put("/profile", response_model=ApiResponse[UserProfileResponse])
async def update_profile(
    payload: UserProfileUpdateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[UserProfileResponse]:
    return success(await user_service.update_profile(db, current_user, payload))


@router.get("/points", response_model=ApiResponse[PointsAccountResponse])
async def points_account(
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[PointsAccountResponse]:
    return success(await user_service.get_points_account(db, current_user))


@router.get("/points/logs", response_model=ApiResponse[dict])
async def points_logs(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    logs, total = await points_service.list_logs(db, current_user, page=page, page_size=page_size)
    return success({"list": [log.model_dump() for log in logs], "page": page, "page_size": page_size, "total": total})


@router.get("/level", response_model=ApiResponse[MemberLevelResponse])
async def member_level(
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[MemberLevelResponse]:
    return success(await user_service.get_member_level(db, current_user))


@router.post("/sign-in", response_model=ApiResponse[SignInResponse])
async def sign_in(
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[SignInResponse]:
    return success(await user_service.sign_in(db, current_user))


@router.get("/followed-merchants", response_model=ApiResponse[dict])
async def followed_merchants(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    merchants, total = await product_service.list_user_followed_merchants(
        db,
        current_user.id,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [item.model_dump() for item in merchants],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/favorite-products", response_model=ApiResponse[dict])
async def favorite_products(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    products, total = await product_service.list_user_favorite_products(
        db,
        current_user.id,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [item.model_dump() for item in products],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )
