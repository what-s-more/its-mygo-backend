from pydantic import BaseModel, Field

from app.schemas.address import AddressResponse


class CartAddRequest(BaseModel):
    sku_id: int
    quantity: int = Field(default=1, ge=1)
    source_post_id: int | None = None


class CartUpdateRequest(BaseModel):
    quantity: int = Field(default=1, ge=1)
    checked: bool = True


class CartBatchUpdateRequest(BaseModel):
    sku_ids: list[int] = Field(min_length=1, max_length=100)
    checked: bool


class CartBatchDeleteRequest(BaseModel):
    sku_ids: list[int] | None = Field(default=None, max_length=100)


class CartItemResponse(BaseModel):
    sku_id: int
    product_id: int
    merchant_id: int
    merchant_name: str
    merchant_logo_url: str | None = None
    product_name: str
    sku_name: str
    price_cent: int
    quantity: int
    checked: bool
    cover_url: str | None = None
    source_post_id: int | None = None
    source_label: str | None = None
    invalid_reason: str | None = None


class CheckoutItemRequest(BaseModel):
    sku_id: int
    quantity: int = Field(ge=1)


class CheckoutRequest(BaseModel):
    items: list[CheckoutItemRequest] | None = None
    full_discount_id: int | None = None
    coupon_id: int | None = None
    points_used: int = Field(default=0, ge=0)


class PromotionOptionResponse(BaseModel):
    id: int
    name: str
    scope_type: str
    scope_ids: list[int] = Field(default_factory=list)
    min_amount_cent: int
    discount_amount_cent: int
    applicable_amount_cent: int
    available: bool = True
    unavailable_reason: str | None = None
    selected: bool = False


class CouponOptionResponse(BaseModel):
    id: int
    coupon_template_id: int
    name: str
    scope_type: str
    scope_ids: list[int] = Field(default_factory=list)
    discount_type: str
    discount_value: int
    min_amount_cent: int
    applicable_amount_cent: int
    discount_amount_cent: int
    status: str
    available: bool = True
    unavailable_reason: str | None = None
    selected: bool = False


class CheckoutResponse(BaseModel):
    items: list[CartItemResponse]
    addresses: list[AddressResponse] = Field(default_factory=list)
    available_full_discounts: list[PromotionOptionResponse] = Field(default_factory=list)
    available_coupons: list[CouponOptionResponse] = Field(default_factory=list)
    selected_full_discount_id: int | None = None
    selected_coupon_id: int | None = None
    total_amount_cent: int
    discount_amount_cent: int = 0
    full_discount_amount_cent: int = 0
    coupon_discount_amount_cent: int = 0
    points_discount_amount_cent: int = 0
    points_used: int = 0
    max_points_usable: int = 0
    pay_amount_cent: int


class CreateOrderRequest(BaseModel):
    client_order_token: str = Field(min_length=1, max_length=80)
    shipping_address_id: int | None = None
    full_discount_id: int | None = None
    coupon_id: int | None = None
    points_used: int = Field(default=0, ge=0)
    source_post_id: int | None = None
    items: list[CheckoutItemRequest] | None = None


class CreateOrderResponse(BaseModel):
    payment_id: int
    payment_no: str
    order_ids: list[int]
    pay_amount_cent: int
    expire_at: str | None = None


class ShippingAddressSnapshot(BaseModel):
    receiver_name: str
    receiver_mobile: str
    province: str
    city: str
    district: str | None = None
    street: str | None = None
    detail_address: str
    postal_code: str | None = None
    address_tag: str | None = None


class ShipOrderRequest(BaseModel):
    logistics_company: str = Field(min_length=1, max_length=80)
    tracking_no: str = Field(min_length=1, max_length=80)


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    sku_id: int
    product_name: str
    sku_name: str
    cover_url: str | None = None
    unit_price_cent: int
    quantity: int
    total_amount_cent: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: int
    order_no: str
    payment_id: int
    merchant_id: int
    merchant_name: str
    merchant_logo_url: str | None = None
    status: str
    total_amount_cent: int
    pay_amount_cent: int
    full_discount_amount_cent: int = 0
    coupon_discount_amount_cent: int = 0
    points_discount_amount_cent: int = 0
    points_used: int = 0
    source_post_id: int | None = None
    source_user_id: int | None = None
    order_type: str = "normal"
    group_buy_activity_id: int | None = None
    group_buy_group_id: int | None = None
    shipping_address: ShippingAddressSnapshot | None = None
    logistics_company: str | None = None
    tracking_no: str | None = None
    created_at: str | None = None
    shipped_at: str | None = None
    received_at: str | None = None
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: int
    payment_no: str
    status: str
    pay_amount_cent: int
    points_used: int = 0
    points_discount_amount_cent: int = 0
    channel: str = "mock"
    alipay_trade_no: str | None = None
    alipay_qr_code: str | None = None
    alipay_buyer_logon_id: str | None = None
    order_ids: list[int] = Field(default_factory=list)
    paid_at: str | None = None

    model_config = {"from_attributes": True}


class AlipayPrecreateResponse(BaseModel):
    payment: PaymentResponse
    qr_code: str
    payment_no: str
    expire_minutes: int


class AlipayNotifyResponse(BaseModel):
    success: bool


class ReviewCreateRequest(BaseModel):
    product_id: int
    score: int = Field(ge=1, le=5)
    content: str = Field(default="", max_length=1000)
    image_urls: list[str] = Field(default_factory=list)


class ReviewAuditRequest(BaseModel):
    approved: bool


class ReviewResponse(BaseModel):
    id: int
    user_id: int
    user_nickname: str | None = None
    user_avatar_url: str | None = None
    order_id: int
    product_id: int
    score: int
    content: str
    image_urls: list[str]
    status: str


class RefundCreateRequest(BaseModel):
    order_item_id: int
    quantity: int = Field(default=1, ge=1)
    reason_type: str = Field(default="other", max_length=50)
    reason: str = Field(min_length=1, max_length=255)
    image_urls: list[str] = Field(default_factory=list)


class RefundLogResponse(BaseModel):
    id: int
    operator_type: str
    operator_id: int | None = None
    action: str
    message: str
    created_at: str | None = None


class RefundResponse(BaseModel):
    id: int
    order_id: int
    order_item_id: int | None = None
    product_id: int | None = None
    sku_id: int | None = None
    user_id: int
    quantity: int = 0
    refund_amount_cent: int
    reason_type: str
    reason: str
    image_urls: list[str] = Field(default_factory=list)
    status: str
    origin_order_status: str
    created_at: str | None = None
    updated_at: str | None = None
    logs: list[RefundLogResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
