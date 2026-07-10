from datetime import datetime

from pydantic import BaseModel, Field


class CouponTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope_type: str = Field(default="all", pattern="^(all|platform|merchant|category|product|sku)$")
    scope_ids: list[int] = Field(default_factory=list)
    discount_type: str = Field(default="amount", pattern="^(amount|percent)$")
    discount_value: int = Field(gt=0)
    min_amount_cent: int = Field(default=0, ge=0)
    total_quantity: int = Field(default=0, ge=0)
    per_user_limit: int = Field(default=1, ge=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CouponTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    scope_type: str | None = Field(default=None, pattern="^(all|platform|merchant|category|product|sku)$")
    scope_ids: list[int] | None = None
    discount_type: str | None = Field(default=None, pattern="^(amount|percent)$")
    discount_value: int | None = Field(default=None, gt=0)
    min_amount_cent: int | None = Field(default=None, ge=0)
    total_quantity: int | None = Field(default=None, ge=0)
    per_user_limit: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CouponBatchGrantRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)


class CouponBatchGrantResponse(BaseModel):
    granted_count: int
    skipped_user_ids: list[int]


class CouponTemplateResponse(BaseModel):
    id: int
    name: str
    scope_type: str
    scope_ids: list[int]
    owner_merchant_id: int | None = None
    created_by_admin_id: int | None = None
    discount_type: str
    discount_value: int
    min_amount_cent: int
    total_quantity: int
    claimed_quantity: int
    per_user_limit: int
    status: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    received: bool = False

    model_config = {"from_attributes": True}


class UserCouponResponse(BaseModel):
    id: int
    user_id: int
    coupon_template_id: int
    status: str
    order_id: int | None = None
    claimed_at: datetime
    used_at: datetime | None = None
    template: CouponTemplateResponse


class FullDiscountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope_type: str = Field(default="all", pattern="^(all|platform|merchant|category|product|sku)$")
    scope_ids: list[int] = Field(default_factory=list)
    min_amount_cent: int = Field(ge=0)
    discount_amount_cent: int = Field(gt=0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class FullDiscountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    scope_type: str | None = Field(default=None, pattern="^(all|platform|merchant|category|product|sku)$")
    scope_ids: list[int] | None = None
    min_amount_cent: int | None = Field(default=None, ge=0)
    discount_amount_cent: int | None = Field(default=None, gt=0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class FullDiscountResponse(BaseModel):
    id: int
    name: str
    scope_type: str
    scope_ids: list[int]
    owner_merchant_id: int | None = None
    created_by_admin_id: int | None = None
    min_amount_cent: int
    discount_amount_cent: int
    status: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    model_config = {"from_attributes": True}
