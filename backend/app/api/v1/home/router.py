from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.schemas.product import HomeBannerResponse
from app.services.product_service import product_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/banners", response_model=ApiResponse[list[HomeBannerResponse]])
async def list_home_banners(db: DbSession) -> ApiResponse[list[HomeBannerResponse]]:
    banners = await product_service.list_home_banners(db)
    return success([HomeBannerResponse.model_validate(banner) for banner in banners])
