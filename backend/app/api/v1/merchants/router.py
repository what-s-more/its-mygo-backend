from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.schemas.product import MerchantResponse, ProductListItem
from app.services.product_service import product_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/{merchant_id}", response_model=ApiResponse[MerchantResponse])
async def get_merchant(merchant_id: int, db: DbSession) -> ApiResponse[MerchantResponse]:
    merchant = await product_service.get_merchant(db, merchant_id)
    return success(MerchantResponse.model_validate(merchant))


@router.get("/{merchant_id}/products", response_model=ApiResponse[dict])
async def list_merchant_products(
    merchant_id: int,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    products, total = await product_service.list_products(
        db,
        keyword=None,
        category_id=None,
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
