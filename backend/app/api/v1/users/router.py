from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.auth import UserProfileResponse
from app.services.points_service import points_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/profile", response_model=ApiResponse[UserProfileResponse])
async def profile(current_user: User = Depends(get_current_user)) -> ApiResponse[UserProfileResponse]:
    return success(UserProfileResponse.model_validate(current_user))


@router.get("/points/logs", response_model=ApiResponse[dict])
async def points_logs(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    logs, total = await points_service.list_logs(db, current_user, page=page, page_size=page_size)
    return success({"list": [log.model_dump() for log in logs], "page": page, "page_size": page_size, "total": total})
