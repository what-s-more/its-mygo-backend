from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from app.schemas.order import OrderItemResponse, ShippingAddressSnapshot


class AdminUserListItem(BaseModel):
    id: int
    mobile: str
    nickname: str
    avatar_url: str | None = None
    level: str
    points: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminAccountResponse(BaseModel):
    id: int
    username: str
    real_name: str
    role: str
    merchant_id: int | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminAccountStatusRequest(BaseModel):
    is_active: bool


class AdminAccountResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=64)


class MerchantRegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=64)
    real_name: str = Field(min_length=1, max_length=50)
    merchant_name: str = Field(min_length=1, max_length=80)
    logo_url: str | None = Field(default=None, max_length=255)
    announcement: str | None = Field(default=None, max_length=255)


class MerchantApplicationUpdateRequest(BaseModel):
    merchant_name: str | None = Field(default=None, min_length=1, max_length=80)
    logo_url: str | None = Field(default=None, max_length=255)
    announcement: str | None = Field(default=None, max_length=255)


class MerchantApplicationAuditRequest(BaseModel):
    approved: bool
    reject_reason: str | None = Field(default=None, max_length=255)


class MerchantApplicationResponse(BaseModel):
    id: int
    admin_id: int
    merchant_id: int | None = None
    merchant_name: str
    logo_url: str | None = None
    announcement: str | None = None
    status: str
    reviewed_by: int | None = None
    reject_reason: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None

    model_config = {"from_attributes": True}


class AdminOrderListItem(BaseModel):
    id: int
    order_no: str
    payment_id: int
    user_id: int
    merchant_id: int
    status: str
    total_amount_cent: int
    pay_amount_cent: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminOrderDetailResponse(AdminOrderListItem):
    shipping_address: ShippingAddressSnapshot | None = None
    logistics_company: str | None = None
    tracking_no: str | None = None
    shipped_at: str | None = None
    received_at: str | None = None
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


class DashboardSummaryResponse(BaseModel):
    user_count: int
    product_count: int
    order_count: int
    paid_order_count: int
    gross_merchandise_cent: int
    pending_shipment_count: int
    after_sale_count: int


class AdminOperationLogResponse(BaseModel):
    id: int
    admin_id: int
    action: str
    resource_type: str
    resource_id: int | None = None
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberLevelRule(BaseModel):
    level: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=30)
    threshold_cent: int = Field(ge=0)
    benefits: list[str] = Field(default_factory=list, max_length=20)


class MemberPointsConfig(BaseModel):
    level_rules: list[MemberLevelRule] = Field(min_length=1, max_length=10)
    sign_in_base_points: int = Field(default=2, ge=0, le=1000)
    sign_in_streak_increment: int = Field(default=1, ge=0, le=1000)
    sign_in_max_points: int = Field(default=10, ge=0, le=10000)
    points_to_yuan_rate: int = Field(default=100, ge=1)
    max_points_discount_percent: int = Field(default=10, ge=0, le=100)
