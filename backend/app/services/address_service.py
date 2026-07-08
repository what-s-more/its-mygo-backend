from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.models.user import User, UserAddress
from app.schemas.address import AddressCreateRequest, AddressResponse, AddressUpdateRequest


class AddressService:
    async def list_addresses(self, db: AsyncSession, user: User) -> list[AddressResponse]:
        result = await db.execute(
            select(UserAddress)
            .where(UserAddress.user_id == user.id)
            .order_by(UserAddress.is_default.desc(), UserAddress.updated_at.desc())
        )
        return [AddressResponse.model_validate(address) for address in result.scalars()]

    async def create_address(
        self,
        db: AsyncSession,
        user: User,
        payload: AddressCreateRequest,
    ) -> AddressResponse:
        has_address = await self._has_address(db, user.id)
        address = UserAddress(
            user_id=user.id,
            receiver_name=payload.receiver_name,
            receiver_mobile=payload.receiver_mobile,
            province=payload.province,
            city=payload.city,
            district=payload.district,
            street=payload.street,
            detail_address=payload.detail_address,
            postal_code=payload.postal_code,
            address_tag=payload.address_tag,
            is_default=payload.is_default or not has_address,
        )
        if address.is_default:
            await self._clear_default(db, user.id)
        db.add(address)
        await db.commit()
        await db.refresh(address)
        return AddressResponse.model_validate(address)

    async def update_address(
        self,
        db: AsyncSession,
        user: User,
        address_id: int,
        payload: AddressUpdateRequest,
    ) -> AddressResponse:
        address = await self.get_owned_address(db, user, address_id)
        update_data = payload.model_dump(exclude_unset=True)
        if update_data.get("is_default") is True:
            await self._clear_default(db, user.id, exclude_address_id=address_id)
        for key, value in update_data.items():
            setattr(address, key, value)
        await db.commit()
        await db.refresh(address)
        return AddressResponse.model_validate(address)

    async def delete_address(self, db: AsyncSession, user: User, address_id: int) -> None:
        address = await self.get_owned_address(db, user, address_id)
        was_default = address.is_default
        await db.delete(address)
        await db.flush()
        if was_default:
            result = await db.execute(
                select(UserAddress)
                .where(UserAddress.user_id == user.id)
                .order_by(UserAddress.updated_at.desc())
                .limit(1)
            )
            next_address = result.scalar_one_or_none()
            if next_address is not None:
                next_address.is_default = True
        await db.commit()

    async def get_owned_address(self, db: AsyncSession, user: User, address_id: int) -> UserAddress:
        address = await db.get(UserAddress, address_id)
        if address is None:
            raise AppException(40004, "地址不存在", 404)
        if address.user_id != user.id:
            raise ForbiddenException()
        return address

    async def _has_address(self, db: AsyncSession, user_id: int) -> bool:
        result = await db.execute(select(UserAddress.id).where(UserAddress.user_id == user_id).limit(1))
        return result.scalar_one_or_none() is not None

    async def _clear_default(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        exclude_address_id: int | None = None,
    ) -> None:
        result = await db.execute(select(UserAddress).where(UserAddress.user_id == user_id))
        for address in result.scalars():
            if exclude_address_id is None or address.id != exclude_address_id:
                address.is_default = False


address_service = AddressService()
