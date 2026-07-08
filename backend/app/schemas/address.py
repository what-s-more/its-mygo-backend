from pydantic import BaseModel, Field


class AddressBase(BaseModel):
    receiver_name: str = Field(min_length=1, max_length=50)
    receiver_mobile: str = Field(min_length=7, max_length=20)
    province: str = Field(min_length=1, max_length=50)
    city: str = Field(min_length=1, max_length=50)
    district: str | None = Field(default=None, max_length=50)
    street: str | None = Field(default=None, max_length=80)
    detail_address: str = Field(min_length=1, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20)
    address_tag: str | None = Field(default=None, max_length=30)
    is_default: bool = False


class AddressCreateRequest(AddressBase):
    pass


class AddressUpdateRequest(BaseModel):
    receiver_name: str | None = Field(default=None, min_length=1, max_length=50)
    receiver_mobile: str | None = Field(default=None, min_length=7, max_length=20)
    province: str | None = Field(default=None, min_length=1, max_length=50)
    city: str | None = Field(default=None, min_length=1, max_length=50)
    district: str | None = Field(default=None, max_length=50)
    street: str | None = Field(default=None, max_length=80)
    detail_address: str | None = Field(default=None, min_length=1, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20)
    address_tag: str | None = Field(default=None, max_length=30)
    is_default: bool | None = None


class AddressResponse(AddressBase):
    id: int
    user_id: int

    model_config = {"from_attributes": True}
