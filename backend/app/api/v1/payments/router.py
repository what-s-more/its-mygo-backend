from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.order import PaymentResponse
from app.services.order_service import order_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/{payment_id}", response_model=ApiResponse[PaymentResponse])
async def get_payment(
    payment_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[PaymentResponse]:
    return success(await order_service.get_payment(db, current_user, payment_id))


@router.post("/{payment_id}/pay", response_model=ApiResponse[PaymentResponse])
async def pay_payment(
    payment_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[PaymentResponse]:
    return success(await order_service.pay_payment(db, current_user, payment_id))
