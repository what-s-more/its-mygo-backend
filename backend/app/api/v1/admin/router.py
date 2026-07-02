from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.core.dependencies import DbSession, bearer_scheme, get_current_admin
from app.core.exceptions import UnauthorizedException
from app.core.security import decode_token
from app.core.token_blacklist import add_token_to_blacklist
from app.models.user import AdminUser
from app.schemas.auth import (
    AdminLoginRequest,
    AdminMenuItem,
    AdminProfileResponse,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.product import (
    CategoryCreateRequest,
    CategoryResponse,
    MerchantCreateRequest,
    MerchantResponse,
    ProductCreateRequest,
    ProductDetailResponse,
)
from app.schemas.order import RefundResponse, ReviewAuditRequest, ReviewResponse, OrderResponse
from app.services.auth_service import auth_service
from app.services.order_service import order_service
from app.services.product_service import product_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.post("/auth/login", response_model=ApiResponse[TokenResponse])
async def admin_login(payload: AdminLoginRequest, db: DbSession) -> ApiResponse[TokenResponse]:
    token = await auth_service.login_admin(db, payload)
    return success(token)


@router.post("/auth/refresh", response_model=ApiResponse[TokenResponse])
async def admin_refresh(payload: RefreshTokenRequest) -> ApiResponse[TokenResponse]:
    token = await auth_service.refresh_token(payload, "admin")
    return success(token)


@router.post("/auth/logout", response_model=ApiResponse[None])
async def admin_logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> ApiResponse[None]:
    if credentials is None:
        raise UnauthorizedException()
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedException("token 无效或已过期") from exc
    expire_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    add_token_to_blacklist(payload["jti"], expire_at)
    return success(None)


@router.get("/auth/me", response_model=ApiResponse[AdminProfileResponse])
async def admin_me(current_admin: AdminUser = Depends(get_current_admin)) -> ApiResponse[AdminProfileResponse]:
    return success(AdminProfileResponse.model_validate(current_admin))


@router.get("/auth/menus", response_model=ApiResponse[list[AdminMenuItem]])
async def admin_menus(current_admin: AdminUser = Depends(get_current_admin)) -> ApiResponse[list[AdminMenuItem]]:
    menus = [
        AdminMenuItem(key="dashboard", label="数据看板", path="/dashboard", permissions=["dashboard:view"]),
        AdminMenuItem(key="products", label="商品管理", path="/products", permissions=["product:view"]),
        AdminMenuItem(key="orders", label="订单管理", path="/orders", permissions=["order:view"]),
    ]
    if current_admin.role == "platform_operator":
        menus.append(AdminMenuItem(key="system", label="系统管理", path="/system", permissions=["system:view"]))
    return success(menus)


@router.post("/merchants", response_model=ApiResponse[MerchantResponse])
async def create_merchant(
    payload: MerchantCreateRequest,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[MerchantResponse]:
    merchant = await product_service.create_merchant(db, payload)
    return success(MerchantResponse.model_validate(merchant))


@router.post("/categories", response_model=ApiResponse[CategoryResponse])
async def create_category(
    payload: CategoryCreateRequest,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CategoryResponse]:
    category = await product_service.create_category(db, payload)
    return success(CategoryResponse.model_validate(category))


@router.post("/products", response_model=ApiResponse[ProductDetailResponse])
async def create_product(
    payload: ProductCreateRequest,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.create_product(db, payload)
    return success(product_service.to_detail_response(product))


@router.get("/products", response_model=ApiResponse[dict])
async def admin_list_products(
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
    keyword: str | None = None,
    category_id: int | None = None,
    merchant_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    products, total = await product_service.list_products(
        db,
        keyword=keyword,
        category_id=category_id,
        merchant_id=merchant_id,
        page=page,
        page_size=page_size,
        include_off_sale=True,
    )
    return success(
        {
            "list": [product_service.to_list_item(product).model_dump() for product in products],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/products/{product_id}", response_model=ApiResponse[ProductDetailResponse])
async def admin_get_product(
    product_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.get_product_detail(db, product_id, include_off_sale=True)
    return success(product_service.to_detail_response(product))


@router.post("/products/{product_id}/publish", response_model=ApiResponse[ProductDetailResponse])
async def publish_product(
    product_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.publish_product(db, product_id)
    return success(product_service.to_detail_response(product))


@router.post("/products/{product_id}/unpublish", response_model=ApiResponse[ProductDetailResponse])
async def unpublish_product(
    product_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.unpublish_product(db, product_id)
    return success(product_service.to_detail_response(product))


@router.post("/orders/{order_id}/ship", response_model=ApiResponse[OrderResponse])
async def ship_order(
    order_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[OrderResponse]:
    return success(await order_service.ship_order(db, order_id))


@router.post("/reviews/{review_id}/audit", response_model=ApiResponse[ReviewResponse])
async def audit_review(
    review_id: int,
    payload: ReviewAuditRequest,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ReviewResponse]:
    return success(await order_service.audit_review(db, review_id, payload.approved))


@router.get("/refunds", response_model=ApiResponse[dict])
async def list_refunds(
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    refunds, total = await order_service.list_refunds(db, page=page, page_size=page_size)
    return success(
        {
            "list": [refund.model_dump() for refund in refunds],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.post("/refunds/{refund_id}/approve", response_model=ApiResponse[RefundResponse])
async def approve_refund(
    refund_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    return success(await order_service.approve_refund(db, refund_id))


@router.post("/refunds/{refund_id}/reject", response_model=ApiResponse[RefundResponse])
async def reject_refund(
    refund_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    return success(await order_service.reject_refund(db, refund_id))


@router.post("/refunds/{refund_id}/receive", response_model=ApiResponse[RefundResponse])
async def receive_refund(
    refund_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    return success(await order_service.receive_refund(db, refund_id))


@router.post("/refunds/{refund_id}/refund", response_model=ApiResponse[RefundResponse])
async def finish_refund(
    refund_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    return success(await order_service.finish_refund(db, refund_id))
