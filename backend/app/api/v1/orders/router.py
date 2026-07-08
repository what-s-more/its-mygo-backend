from fastapi import APIRouter
from fastapi import Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.order import (
    CreateOrderRequest,
    CreateOrderResponse,
    OrderResponse,
    RefundCreateRequest,
    RefundResponse,
    ReviewCreateRequest,
    ReviewResponse,
)
from app.services.order_service import order_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.post("", response_model=ApiResponse[CreateOrderResponse])
async def create_order(
    payload: CreateOrderRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[CreateOrderResponse]:
    return success(await order_service.create_order(db, current_user, payload))


@router.get("", response_model=ApiResponse[dict])
async def list_orders(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    orders, total = await order_service.list_orders(db, current_user, status=status, page=page, page_size=page_size)
    return success(
        {
            "list": [order.model_dump() for order in orders],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/refunds", response_model=ApiResponse[dict])
async def list_refunds(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    refunds, total = await order_service.list_user_refunds(
        db,
        current_user,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [refund.model_dump() for refund in refunds],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/refunds/{refund_id}", response_model=ApiResponse[RefundResponse])
async def get_refund(
    refund_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[RefundResponse]:
    return success(await order_service.get_user_refund(db, current_user, refund_id))


@router.get("/{order_id}", response_model=ApiResponse[OrderResponse])
async def get_order(
    order_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[OrderResponse]:
    return success(await order_service.get_order(db, current_user, order_id))


@router.post("/{order_id}/cancel", response_model=ApiResponse[OrderResponse])
async def cancel_order(
    order_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[OrderResponse]:
    return success(await order_service.cancel_order(db, current_user, order_id))


@router.post("/{order_id}/confirm", response_model=ApiResponse[OrderResponse])
async def confirm_order(
    order_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[OrderResponse]:
    return success(await order_service.confirm_order(db, current_user, order_id))


@router.post("/{order_id}/reviews", response_model=ApiResponse[ReviewResponse])
async def create_review(
    order_id: int,
    payload: ReviewCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ReviewResponse]:
    return success(await order_service.create_review(db, current_user, order_id, payload))


@router.post("/{order_id}/refunds", response_model=ApiResponse[RefundResponse])
async def create_refund(
    order_id: int,
    payload: RefundCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[RefundResponse]:
    return success(await order_service.create_refund(db, current_user, order_id, payload))
