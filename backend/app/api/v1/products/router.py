from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.schemas.product import ProductDetailResponse
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
    return success(product_service.to_detail_response(product))


@router.get("/{product_id}/reviews", response_model=ApiResponse[dict])
async def list_product_reviews(
    product_id: int,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    reviews, total = await order_service.list_product_reviews(db, product_id, page=page, page_size=page_size)
    return success(
        {
            "list": [review.model_dump() for review in reviews],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )
