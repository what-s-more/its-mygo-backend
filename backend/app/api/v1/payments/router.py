from fastapi import APIRouter, Depends, Request, Response

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.order import AlipayPrecreateResponse, PaymentResponse
from app.services.alipay_service import alipay_service
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


@router.post("/{payment_id}/alipay/precreate", response_model=ApiResponse[AlipayPrecreateResponse])
async def precreate_alipay_payment(
    payment_id: int,
    db: DbSession,
    force: bool = False,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[AlipayPrecreateResponse]:
    return success(await order_service.precreate_alipay_payment(db, current_user, payment_id, force=force))


@router.post("/{payment_id}/alipay/sync", response_model=ApiResponse[PaymentResponse])
async def sync_alipay_payment(
    payment_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[PaymentResponse]:
    return success(await order_service.sync_alipay_payment(db, current_user, payment_id))


@router.post("/notify/alipay", response_class=Response)
async def alipay_notify(request: Request, db: DbSession) -> Response:
    payload = alipay_service.parse_notify_body(await request.body())
    handled = await order_service.handle_alipay_notify(db, payload)
    return Response(content="success" if handled else "fail", media_type="text/plain")
