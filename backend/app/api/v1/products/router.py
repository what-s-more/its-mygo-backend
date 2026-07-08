from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.merchants.router import optional_consumer_user_id
from app.core.dependencies import DbSession, bearer_scheme, get_current_user
from app.models.user import User
from app.schemas.product import ProductDetailResponse, ProductFavoriteStatusResponse
from app.services.order_service import order_service
from app.services.product_service import product_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("", response_model=ApiResponse[dict])
async def list_products(
    db: DbSession,
    keyword: str | None = None,
    category_id: int | None = None,
    merchant_id: int | None = None,
    min_price_cent: int | None = None,
    max_price_cent: int | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    products, total = await product_service.list_products(
        db,
        keyword=keyword,
        category_id=category_id,
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


@router.get("/{product_id}", response_model=ApiResponse[ProductDetailResponse])
async def get_product(product_id: int, db: DbSession) -> ApiResponse[ProductDetailResponse]:
    product = await product_service.get_product_detail(db, product_id)
    return success(await product_service.to_detail_response(db, product))


@router.get("/{product_id}/favorite", response_model=ApiResponse[ProductFavoriteStatusResponse])
async def get_product_favorite_status(
    product_id: int,
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> ApiResponse[ProductFavoriteStatusResponse]:
    user_id = optional_consumer_user_id(credentials)
    return success(await product_service.get_product_favorite_status(db, user_id, product_id))


@router.post("/{product_id}/favorite", response_model=ApiResponse[ProductFavoriteStatusResponse])
async def favorite_product(
    product_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ProductFavoriteStatusResponse]:
    return success(await product_service.favorite_product(db, current_user.id, product_id))


@router.delete("/{product_id}/favorite", response_model=ApiResponse[ProductFavoriteStatusResponse])
async def unfavorite_product(
    product_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ProductFavoriteStatusResponse]:
    return success(await product_service.unfavorite_product(db, current_user.id, product_id))


@router.get("/{product_id}/reviews", response_model=ApiResponse[dict])
async def list_product_reviews(
    product_id: int,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
    score: int | None = None,
    has_image: bool | None = None,
) -> ApiResponse[dict]:
    reviews, total = await order_service.list_product_reviews(
        db,
        product_id,
        page=page,
        page_size=page_size,
        score=score,
        has_image=has_image,
    )
    return success(
        {
            "list": [review.model_dump() for review in reviews],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )
