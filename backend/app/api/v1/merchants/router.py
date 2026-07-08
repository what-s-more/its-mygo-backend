from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.core.dependencies import DbSession, bearer_scheme, get_current_user
from app.core.security import decode_token
from app.core.token_blacklist import is_token_blacklisted
from app.models.user import User
from app.schemas.product import MerchantFollowStatusResponse, MerchantResponse, ProductListItem
from app.services.product_service import product_service
from app.utils.response import ApiResponse, success

router = APIRouter()


def optional_consumer_user_id(credentials: HTTPAuthorizationCredentials | None) -> int | None:
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        return None
    if is_token_blacklisted(payload.get("jti")):
        return None
    if payload.get("token_type") != "access" or payload.get("account_type") != "consumer":
        return None
    return int(payload["sub"])


@router.get("/{merchant_id}", response_model=ApiResponse[MerchantResponse])
async def get_merchant(merchant_id: int, db: DbSession) -> ApiResponse[MerchantResponse]:
    merchant = await product_service.get_merchant(db, merchant_id)
    return success(MerchantResponse.model_validate(merchant))


@router.get("/{merchant_id}/follow", response_model=ApiResponse[MerchantFollowStatusResponse])
async def get_merchant_follow_status(
    merchant_id: int,
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> ApiResponse[MerchantFollowStatusResponse]:
    user_id = optional_consumer_user_id(credentials)
    return success(await product_service.get_merchant_follow_status(db, user_id, merchant_id))


@router.post("/{merchant_id}/follow", response_model=ApiResponse[MerchantFollowStatusResponse])
async def follow_merchant(
    merchant_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[MerchantFollowStatusResponse]:
    return success(await product_service.follow_merchant(db, current_user.id, merchant_id))


@router.delete("/{merchant_id}/follow", response_model=ApiResponse[MerchantFollowStatusResponse])
async def unfollow_merchant(
    merchant_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[MerchantFollowStatusResponse]:
    return success(await product_service.unfollow_merchant(db, current_user.id, merchant_id))


@router.get("/{merchant_id}/products", response_model=ApiResponse[dict])
async def list_merchant_products(
    merchant_id: int,
    db: DbSession,
    min_price_cent: int | None = None,
    max_price_cent: int | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    products, total = await product_service.list_products(
        db,
        keyword=None,
        category_id=None,
        merchant_id=merchant_id,
        min_price_cent=min_price_cent,
        max_price_cent=max_price_cent,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            "list": [product_service.to_list_item(product).model_dump() for product in products],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )
