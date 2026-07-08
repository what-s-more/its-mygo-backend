from fastapi import APIRouter
from fastapi import Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.order import (
    CartAddRequest,
    CartBatchDeleteRequest,
    CartBatchUpdateRequest,
    CartItemResponse,
    CartUpdateRequest,
    CheckoutRequest,
    CheckoutResponse,
)
from app.services.order_service import order_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("", response_model=ApiResponse[list[CartItemResponse]])
async def list_cart(db: DbSession, current_user: User = Depends(get_current_user)) -> ApiResponse[list[CartItemResponse]]:
    return success(await order_service.list_cart(db, current_user))


@router.post("", response_model=ApiResponse[list[CartItemResponse]])
async def add_cart_item(
    payload: CartAddRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[CartItemResponse]]:
    return success(await order_service.add_cart_item(db, current_user, payload))


@router.put("/{sku_id}", response_model=ApiResponse[list[CartItemResponse]])
async def update_cart_item(
    sku_id: int,
    payload: CartUpdateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[CartItemResponse]]:
    return success(await order_service.update_cart_item(db, current_user, sku_id, payload))


@router.patch("/batch", response_model=ApiResponse[list[CartItemResponse]])
async def batch_update_cart_items(
    payload: CartBatchUpdateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[CartItemResponse]]:
    return success(await order_service.batch_update_cart_items(db, current_user, payload))


@router.delete("", response_model=ApiResponse[list[CartItemResponse]])
async def batch_delete_cart_items(
    payload: CartBatchDeleteRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[CartItemResponse]]:
    return success(await order_service.batch_delete_cart_items(db, current_user, payload))


@router.delete("/{sku_id}", response_model=ApiResponse[list[CartItemResponse]])
async def delete_cart_item(
    sku_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[CartItemResponse]]:
    return success(await order_service.delete_cart_item(db, current_user, sku_id))


@router.post("/checkout", response_model=ApiResponse[CheckoutResponse])
async def checkout(
    payload: CheckoutRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[CheckoutResponse]:
    return success(await order_service.checkout(db, current_user, payload))
