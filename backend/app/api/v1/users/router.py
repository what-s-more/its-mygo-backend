from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import UserProfileResponse
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/profile", response_model=ApiResponse[UserProfileResponse])
async def profile(current_user: User = Depends(get_current_user)) -> ApiResponse[UserProfileResponse]:
    return success(UserProfileResponse.model_validate(current_user))
