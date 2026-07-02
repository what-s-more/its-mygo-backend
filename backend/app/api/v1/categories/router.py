from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.schemas.product import CategoryResponse
from app.services.product_service import product_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("", response_model=ApiResponse[list[CategoryResponse]])
async def list_categories(db: DbSession) -> ApiResponse[list[CategoryResponse]]:
    categories = await product_service.list_categories(db)
    return success([CategoryResponse.model_validate(category) for category in categories])

