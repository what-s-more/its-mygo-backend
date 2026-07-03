from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials

from app.core.dependencies import DbSession, bearer_scheme, get_current_admin
from app.core.exceptions import ForbiddenException, UnauthorizedException
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
from app.schemas.admin import (
    AdminAccountResponse,
    AdminAccountResetPasswordRequest,
    AdminAccountStatusRequest,
    AdminOrderDetailResponse,
    DashboardSummaryResponse,
    MerchantApplicationAuditRequest,
    MerchantApplicationResponse,
    MerchantApplicationUpdateRequest,
    MerchantRegisterRequest,
)
from app.schemas.community import CommentAuditRequest, CommentResponse, PostAuditRequest, PostResponse
from app.schemas.product import (
    CategoryCreateRequest,
    CategoryResponse,
    MerchantCreateRequest,
    MerchantResponse,
    ProductAuditRequest,
    ProductBatchRequest,
    ProductCreateRequest,
    ProductDetailResponse,
    ProductUpdateRequest,
    SkuUpdateRequest,
    SkuStockLogResponse,
)
from app.schemas.order import OrderResponse, RefundResponse, ReviewAuditRequest, ReviewResponse, ShipOrderRequest
from app.schemas.promotion import (
    CouponBatchGrantRequest,
    CouponBatchGrantResponse,
    CouponTemplateCreateRequest,
    CouponTemplateResponse,
    CouponTemplateUpdateRequest,
)
from app.services.admin_service import admin_service
from app.services.admin_log_service import admin_log_service
from app.services.auth_service import auth_service
from app.services.community_service import community_service
from app.services.order_service import order_service
from app.services.product_service import product_service
from app.services.promotion_service import promotion_service
from app.utils.response import ApiResponse, success

router = APIRouter()


def ensure_platform_operator(admin: AdminUser) -> None:
    if admin.role != "platform_operator":
        raise ForbiddenException("仅平台运营可执行该操作")


def ensure_coupon_admin_scope(admin: AdminUser, scope_type: str, scope_ids: list[int]) -> None:
    if admin.role not in {"platform_operator", "merchant_operator"}:
        raise ForbiddenException("当前账号尚未获得商家管理权限")
    if admin.role != "merchant_operator":
        return
    if admin.merchant_id is None:
        raise ForbiddenException("商家运营未绑定店铺")
    if scope_type != "merchant" or scope_ids != [admin.merchant_id]:
        raise ForbiddenException("商家运营只能管理本店铺优惠券")


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
    if current_admin.role == "merchant_pending":
        return success(
            [
                AdminMenuItem(
                    key="merchant_application",
                    label="入驻状态",
                    path="/merchant/application",
                    permissions=["merchant_application:view"],
                )
            ]
        )
    menus = [
        AdminMenuItem(key="dashboard", label="数据看板", path="/dashboard", permissions=["dashboard:view"]),
        AdminMenuItem(key="products", label="商品管理", path="/products", permissions=["product:view"]),
        AdminMenuItem(key="orders", label="订单管理", path="/orders", permissions=["order:view"]),
    ]
    if current_admin.role == "platform_operator":
        menus.append(AdminMenuItem(key="system", label="系统管理", path="/system", permissions=["system:view"]))
    return success(menus)


@router.get("/dashboard/summary", response_model=ApiResponse[DashboardSummaryResponse])
async def admin_dashboard_summary(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[DashboardSummaryResponse]:
    return success(await admin_service.get_dashboard_summary(db, current_admin))


@router.get("/users", response_model=ApiResponse[dict])
async def admin_list_users(
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    users, total = await admin_service.list_users(db, keyword=keyword, page=page, page_size=page_size)
    return success(
        {
            "list": [user.model_dump() for user in users],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/operation-logs", response_model=ApiResponse[dict])
async def admin_list_operation_logs(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    action: str | None = None,
    resource_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    ensure_platform_operator(current_admin)
    logs, total = await admin_log_service.list_logs(
        db,
        action=action,
        resource_type=resource_type,
        page=page,
        page_size=page_size,
    )
    return success({"list": [log.model_dump() for log in logs], "page": page, "page_size": page_size, "total": total})


@router.get("/accounts", response_model=ApiResponse[dict])
async def admin_list_accounts(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    keyword: str | None = None,
    role: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    ensure_platform_operator(current_admin)
    accounts, total = await admin_service.list_admin_accounts(
        db,
        keyword=keyword,
        role=role,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [account.model_dump() for account in accounts],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.patch("/accounts/{admin_id}/status", response_model=ApiResponse[AdminAccountResponse])
async def admin_update_account_status(
    admin_id: int,
    payload: AdminAccountStatusRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[AdminAccountResponse]:
    ensure_platform_operator(current_admin)
    account = await admin_service.update_admin_account_status(
        db,
        operator=current_admin,
        admin_id=admin_id,
        is_active=payload.is_active,
    )
    await admin_log_service.record(
        db,
        current_admin,
        action="admin_account.status",
        resource_type="admin_user",
        resource_id=admin_id,
        description=f"{'启用' if payload.is_active else '禁用'}管理员账号：{account.username}",
    )
    await db.commit()
    return success(account)


@router.post("/accounts/{admin_id}/reset-password", response_model=ApiResponse[AdminAccountResponse])
async def admin_reset_account_password(
    admin_id: int,
    payload: AdminAccountResetPasswordRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[AdminAccountResponse]:
    ensure_platform_operator(current_admin)
    account = await admin_service.reset_admin_account_password(db, admin_id=admin_id, password=payload.password)
    await admin_log_service.record(
        db,
        current_admin,
        action="admin_account.reset_password",
        resource_type="admin_user",
        resource_id=admin_id,
        description=f"重置管理员密码：{account.username}",
    )
    await db.commit()
    return success(account)


@router.post("/merchant/register", response_model=ApiResponse[MerchantApplicationResponse])
async def merchant_register(payload: MerchantRegisterRequest, db: DbSession) -> ApiResponse[MerchantApplicationResponse]:
    return success(await admin_service.register_merchant_account(db, payload))


@router.get("/merchant/application/me", response_model=ApiResponse[MerchantApplicationResponse | None])
async def merchant_application_me(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[MerchantApplicationResponse | None]:
    return success(await admin_service.get_merchant_application_by_admin(db, current_admin))


@router.put("/merchant/application/me", response_model=ApiResponse[MerchantApplicationResponse])
async def merchant_update_application_me(
    payload: MerchantApplicationUpdateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[MerchantApplicationResponse]:
    return success(await admin_service.update_merchant_application_by_admin(db, current_admin, payload))


@router.get("/merchant/applications", response_model=ApiResponse[dict])
async def admin_list_merchant_applications(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    ensure_platform_operator(current_admin)
    applications, total = await admin_service.list_merchant_applications(
        db,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [application.model_dump() for application in applications],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.post("/merchant/applications/{application_id}/audit", response_model=ApiResponse[MerchantApplicationResponse])
async def admin_audit_merchant_application(
    application_id: int,
    payload: MerchantApplicationAuditRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[MerchantApplicationResponse]:
    ensure_platform_operator(current_admin)
    application = await admin_service.audit_merchant_application(
        db,
        current_admin,
        application_id,
        approved=payload.approved,
        reject_reason=payload.reject_reason,
    )
    await admin_log_service.record(
        db,
        current_admin,
        action="merchant_application.audit",
        resource_type="merchant_application",
        resource_id=application_id,
        description=f"商家入驻审核：{'通过' if payload.approved else '拒绝'}",
    )
    await db.commit()
    return success(application)


@router.post("/merchants", response_model=ApiResponse[MerchantResponse])
async def create_merchant(
    payload: MerchantCreateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[MerchantResponse]:
    raise ForbiddenException("店铺必须通过商家入驻审核创建，平台不能手动创建店铺")


@router.post("/categories", response_model=ApiResponse[CategoryResponse])
async def create_category(
    payload: CategoryCreateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CategoryResponse]:
    ensure_platform_operator(current_admin)
    category = await product_service.create_category(db, payload)
    return success(CategoryResponse.model_validate(category))


@router.post("/products", response_model=ApiResponse[ProductDetailResponse])
async def create_product(
    payload: ProductCreateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.create_product_for_admin(db, current_admin, payload)
    return success(product_service.to_detail_response(product))


@router.get("/products", response_model=ApiResponse[dict])
async def admin_list_products(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    keyword: str | None = None,
    category_id: int | None = None,
    merchant_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    products, total = await product_service.list_admin_products(
        db,
        current_admin,
        keyword=keyword,
        category_id=category_id,
        merchant_id=merchant_id,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [product_service.to_detail_response(product).model_dump() for product in products],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/products/{product_id}", response_model=ApiResponse[ProductDetailResponse])
async def admin_get_product(
    product_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.get_product_detail_for_admin(db, current_admin, product_id)
    return success(product_service.to_detail_response(product))


@router.put("/products/{product_id}", response_model=ApiResponse[ProductDetailResponse])
async def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.update_product_for_admin(db, current_admin, product_id, payload)
    return success(product_service.to_detail_response(product))


@router.patch("/products/{product_id}/skus/{sku_id}", response_model=ApiResponse[ProductDetailResponse])
async def update_product_sku(
    product_id: int,
    sku_id: int,
    payload: SkuUpdateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.update_sku_for_admin(db, current_admin, product_id, sku_id, payload)
    return success(product_service.to_detail_response(product))


@router.get("/products/{product_id}/skus/{sku_id}/stock-logs", response_model=ApiResponse[dict])
async def list_sku_stock_logs(
    product_id: int,
    sku_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    logs, total = await product_service.list_sku_stock_logs_for_admin(
        db,
        current_admin,
        product_id,
        sku_id,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [log.model_dump() for log in logs],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.post("/products/{product_id}/publish", response_model=ApiResponse[ProductDetailResponse])
async def publish_product(
    product_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.publish_product_for_admin(db, current_admin, product_id)
    return success(product_service.to_detail_response(product))


@router.post("/products/{product_id}/submit-audit", response_model=ApiResponse[ProductDetailResponse])
async def submit_product_audit(
    product_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.submit_product_audit_for_admin(db, current_admin, product_id)
    return success(product_service.to_detail_response(product))


@router.post("/products/{product_id}/audit", response_model=ApiResponse[ProductDetailResponse])
async def audit_product(
    product_id: int,
    payload: ProductAuditRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    ensure_platform_operator(current_admin)
    product = await product_service.audit_product(db, product_id, payload.approved)
    await admin_log_service.record(
        db,
        current_admin,
        action="product.audit",
        resource_type="product",
        resource_id=product_id,
        description=f"商品监管兼容接口：{'上架' if payload.approved else '下架'}",
    )
    await db.commit()
    return success(product_service.to_detail_response(product))


@router.post("/products/{product_id}/unpublish", response_model=ApiResponse[ProductDetailResponse])
async def unpublish_product(
    product_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.unpublish_product_for_admin(db, current_admin, product_id)
    return success(product_service.to_detail_response(product))


@router.post("/products/batch-publish", response_model=ApiResponse[list[ProductDetailResponse]])
async def batch_publish_products(
    payload: ProductBatchRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[list[ProductDetailResponse]]:
    products = await product_service.batch_update_product_status_for_admin(
        db,
        current_admin,
        payload.product_ids,
        "on_sale",
    )
    return success([product_service.to_detail_response(product) for product in products])


@router.post("/products/batch-unpublish", response_model=ApiResponse[list[ProductDetailResponse]])
async def batch_unpublish_products(
    payload: ProductBatchRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[list[ProductDetailResponse]]:
    products = await product_service.batch_update_product_status_for_admin(
        db,
        current_admin,
        payload.product_ids,
        "off_sale",
    )
    return success([product_service.to_detail_response(product) for product in products])


@router.get("/promotions/coupons", response_model=ApiResponse[list[CouponTemplateResponse]])
async def admin_list_coupon_templates(
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[list[CouponTemplateResponse]]:
    return success(await promotion_service.list_coupon_templates(db, only_available=False))


@router.post("/promotions/coupons", response_model=ApiResponse[CouponTemplateResponse])
async def admin_create_coupon_template(
    payload: CouponTemplateCreateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CouponTemplateResponse]:
    ensure_coupon_admin_scope(current_admin, payload.scope_type, payload.scope_ids)
    return success(await promotion_service.create_coupon_template(db, payload))


@router.put("/promotions/coupons/{coupon_template_id}", response_model=ApiResponse[CouponTemplateResponse])
async def admin_update_coupon_template(
    coupon_template_id: int,
    payload: CouponTemplateUpdateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CouponTemplateResponse]:
    existing = await promotion_service.get_coupon_template(db, coupon_template_id)
    ensure_coupon_admin_scope(current_admin, existing.scope_type, existing.scope_ids)
    next_scope_type = payload.scope_type if payload.scope_type is not None else existing.scope_type
    next_scope_ids = payload.scope_ids if payload.scope_ids is not None else existing.scope_ids
    ensure_coupon_admin_scope(current_admin, next_scope_type, next_scope_ids)
    return success(await promotion_service.update_coupon_template(db, coupon_template_id, payload))


@router.post("/promotions/coupons/{coupon_template_id}/disable", response_model=ApiResponse[CouponTemplateResponse])
async def admin_disable_coupon_template(
    coupon_template_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CouponTemplateResponse]:
    existing = await promotion_service.get_coupon_template(db, coupon_template_id)
    ensure_coupon_admin_scope(current_admin, existing.scope_type, existing.scope_ids)
    return success(await promotion_service.disable_coupon_template(db, coupon_template_id))


@router.post("/promotions/coupons/expire", response_model=ApiResponse[dict])
async def admin_expire_user_coupons(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[dict]:
    ensure_platform_operator(current_admin)
    expired_count = await promotion_service.expire_user_coupons(db)
    return success({"expired_count": expired_count})


@router.post(
    "/promotions/coupons/{coupon_template_id}/batch-grant",
    response_model=ApiResponse[CouponBatchGrantResponse],
)
async def admin_batch_grant_coupon(
    coupon_template_id: int,
    payload: CouponBatchGrantRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CouponBatchGrantResponse]:
    ensure_platform_operator(current_admin)
    result = await promotion_service.batch_grant_coupon(db, coupon_template_id, payload.user_ids)
    await admin_log_service.record(
        db,
        current_admin,
        action="coupon.batch_grant",
        resource_type="coupon_template",
        resource_id=coupon_template_id,
        description=f"批量发券成功 {result.granted_count} 张",
    )
    await db.commit()
    return success(result)


@router.get("/community/posts", response_model=ApiResponse[dict])
async def admin_list_community_posts(
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
    status: str = "published",
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    posts, total = await community_service.list_posts(db, status=status, page=page, page_size=page_size)
    return success({"list": [post.model_dump() for post in posts], "page": page, "page_size": page_size, "total": total})


@router.post("/community/posts/{post_id}/audit", response_model=ApiResponse[PostResponse])
async def admin_audit_community_post(
    post_id: int,
    payload: PostAuditRequest,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[PostResponse]:
    return success(await community_service.audit_post(db, post_id, payload.approved))


@router.post("/community/posts/{post_id}/hide", response_model=ApiResponse[PostResponse])
async def admin_hide_community_post(
    post_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[PostResponse]:
    return success(await community_service.hide_post(db, post_id))


@router.get("/community/comments", response_model=ApiResponse[dict])
async def admin_list_community_comments(
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
    post_id: int | None = None,
    status: str = "published",
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    comments, total = await community_service.list_comments(
        db,
        post_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success(
        {"list": [comment.model_dump() for comment in comments], "page": page, "page_size": page_size, "total": total}
    )


@router.post("/community/comments/{comment_id}/audit", response_model=ApiResponse[CommentResponse])
async def admin_audit_community_comment(
    comment_id: int,
    payload: CommentAuditRequest,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CommentResponse]:
    return success(await community_service.audit_comment(db, comment_id, payload.approved))


@router.post("/community/comments/{comment_id}/hide", response_model=ApiResponse[CommentResponse])
async def admin_hide_community_comment(
    comment_id: int,
    db: DbSession,
    _: AdminUser = Depends(get_current_admin),
) -> ApiResponse[CommentResponse]:
    return success(await community_service.hide_comment(db, comment_id))


@router.get("/orders", response_model=ApiResponse[dict])
async def admin_list_orders(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    orders, total = await admin_service.list_orders(
        db,
        current_admin,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [order.model_dump() for order in orders],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/orders/export")
async def admin_export_orders(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    status: str | None = None,
) -> Response:
    csv_content = await admin_service.export_orders_csv(db, current_admin, status=status)
    filename = f"orders-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.csv"
    return Response(
        content="\ufeff" + csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/orders/{order_id}", response_model=ApiResponse[AdminOrderDetailResponse])
async def admin_get_order(
    order_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[AdminOrderDetailResponse]:
    return success(await admin_service.get_order(db, current_admin, order_id))


@router.post("/orders/{order_id}/ship", response_model=ApiResponse[OrderResponse])
async def ship_order(
    order_id: int,
    payload: ShipOrderRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[OrderResponse]:
    await admin_service.assert_can_operate_order(db, current_admin, order_id)
    order = await order_service.ship_order(db, order_id, payload)
    await admin_log_service.record(
        db,
        current_admin,
        action="order.ship",
        resource_type="order",
        resource_id=order_id,
        description=f"订单发货：{payload.logistics_company} {payload.tracking_no}",
    )
    await db.commit()
    return success(order)


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
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    refund = await order_service.approve_refund(db, refund_id)
    await admin_log_service.record(
        db,
        current_admin,
        action="refund.approve",
        resource_type="refund",
        resource_id=refund_id,
        description="同意售后",
    )
    await db.commit()
    return success(refund)


@router.post("/refunds/{refund_id}/reject", response_model=ApiResponse[RefundResponse])
async def reject_refund(
    refund_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    refund = await order_service.reject_refund(db, refund_id)
    await admin_log_service.record(
        db,
        current_admin,
        action="refund.reject",
        resource_type="refund",
        resource_id=refund_id,
        description="拒绝售后",
    )
    await db.commit()
    return success(refund)


@router.post("/refunds/{refund_id}/receive", response_model=ApiResponse[RefundResponse])
async def receive_refund(
    refund_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    refund = await order_service.receive_refund(db, refund_id)
    await admin_log_service.record(
        db,
        current_admin,
        action="refund.receive",
        resource_type="refund",
        resource_id=refund_id,
        description="确认收到退货",
    )
    await db.commit()
    return success(refund)


@router.post("/refunds/{refund_id}/refund", response_model=ApiResponse[RefundResponse])
async def finish_refund(
    refund_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[RefundResponse]:
    refund = await order_service.finish_refund(db, refund_id)
    await admin_log_service.record(
        db,
        current_admin,
        action="refund.refund",
        resource_type="refund",
        resource_id=refund_id,
        description="确认退款完成",
    )
    await db.commit()
    return success(refund)
