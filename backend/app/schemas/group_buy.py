from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.order import CreateOrderResponse
from app.schemas.product import ProductListItem


class GroupBuyActivityCreateRequest(BaseModel):
    product_id: int
    sku_id: int
    name: str = Field(min_length=1, max_length=120)
    group_size: int = Field(default=2, ge=2, le=3)
    group_price_cent: int = Field(gt=0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class GroupBuyActivityUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    group_size: int | None = Field(default=None, ge=2, le=3)
    group_price_cent: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class GroupBuyGroupSummary(BaseModel):
    id: int
    activity_id: int
    leader_user_id: int
    status: str
    joined_count: int
    group_size: int
    expire_at: datetime
    success_at: datetime | None = None


class GroupBuyActivityResponse(BaseModel):
    id: int
    merchant_id: int
    product_id: int
    sku_id: int
    name: str
    group_size: int
    group_price_cent: int
    status: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_by_admin_id: int | None = None
    product: ProductListItem | None = None
    active_groups: list[GroupBuyGroupSummary] = Field(default_factory=list)


class GroupBuyStartRequest(BaseModel):
    activity_id: int
    quantity: int = Field(default=1, ge=1)
    shipping_address_id: int | None = None
    points_used: int = Field(default=0, ge=0)
    client_order_token: str = Field(min_length=1, max_length=80)


class GroupBuyJoinRequest(BaseModel):
    group_id: int
    quantity: int = Field(default=1, ge=1)
    shipping_address_id: int | None = None
    points_used: int = Field(default=0, ge=0)
    client_order_token: str = Field(min_length=1, max_length=80)


class GroupBuyOrderResponse(BaseModel):
    group: GroupBuyGroupSummary
    order: CreateOrderResponse
