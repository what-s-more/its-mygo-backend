from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.group_buy import (
    GroupBuyActivityResponse,
    GroupBuyJoinRequest,
    GroupBuyOrderResponse,
    GroupBuyStartRequest,
)
from app.services.group_buy_service import group_buy_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/activities", response_model=ApiResponse[list[GroupBuyActivityResponse]])
async def list_group_buy_activities(
    db: DbSession,
    merchant_id: int | None = None,
) -> ApiResponse[list[GroupBuyActivityResponse]]:
    return success(await group_buy_service.list_activities(db, merchant_id=merchant_id, only_active=True))


@router.post("/groups/start", response_model=ApiResponse[GroupBuyOrderResponse])
async def start_group_buy(
    payload: GroupBuyStartRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[GroupBuyOrderResponse]:
    return success(await group_buy_service.start_group(db, current_user, payload))


@router.post("/groups/join", response_model=ApiResponse[GroupBuyOrderResponse])
async def join_group_buy(
    payload: GroupBuyJoinRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[GroupBuyOrderResponse]:
    return success(await group_buy_service.join_group(db, current_user, payload))
