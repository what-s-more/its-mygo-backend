from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.address import AddressCreateRequest, AddressResponse, AddressUpdateRequest
from app.services.address_service import address_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("", response_model=ApiResponse[list[AddressResponse]])
async def list_addresses(
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[AddressResponse]]:
    return success(await address_service.list_addresses(db, current_user))


@router.post("", response_model=ApiResponse[AddressResponse])
async def create_address(
    payload: AddressCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[AddressResponse]:
    return success(await address_service.create_address(db, current_user, payload))


@router.put("/{address_id}", response_model=ApiResponse[AddressResponse])
async def update_address(
    address_id: int,
    payload: AddressUpdateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[AddressResponse]:
    return success(await address_service.update_address(db, current_user, address_id, payload))


@router.delete("/{address_id}", response_model=ApiResponse[None])
async def delete_address(
    address_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[None]:
    await address_service.delete_address(db, current_user, address_id)
    return success(None)
