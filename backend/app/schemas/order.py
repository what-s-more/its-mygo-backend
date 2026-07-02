from pydantic import BaseModel, Field


class CartAddRequest(BaseModel):
    sku_id: int
    quantity: int = Field(default=1, ge=1)


class CartUpdateRequest(BaseModel):
    quantity: int = Field(default=1, ge=1)
    checked: bool = True


class CartItemResponse(BaseModel):
    sku_id: int
    product_id: int
    product_name: str
    sku_name: str
    price_cent: int
    quantity: int
    checked: bool
    invalid_reason: str | None = None


class CheckoutItemRequest(BaseModel):
    sku_id: int
    quantity: int = Field(ge=1)


class CheckoutRequest(BaseModel):
    items: list[CheckoutItemRequest] | None = None
    coupon_id: int | None = None
    points_used: int = Field(default=0, ge=0)


class CheckoutResponse(BaseModel):
    items: list[CartItemResponse]
    total_amount_cent: int
    discount_amount_cent: int = 0
    pay_amount_cent: int


class CreateOrderRequest(BaseModel):
    client_order_token: str = Field(min_length=1, max_length=80)
    shipping_address_id: int | None = None
    items: list[CheckoutItemRequest] | None = None


class CreateOrderResponse(BaseModel):
    payment_id: int
    payment_no: str
    order_ids: list[int]
    pay_amount_cent: int
    expire_at: str | None = None


class OrderItemResponse(BaseModel):
    product_id: int
    sku_id: int
    product_name: str
    sku_name: str
    unit_price_cent: int
    quantity: int
    total_amount_cent: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: int
    order_no: str
    payment_id: int
    merchant_id: int
    status: str
    total_amount_cent: int
    pay_amount_cent: int
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: int
    payment_no: str
    status: str
    pay_amount_cent: int

    model_config = {"from_attributes": True}


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
    order_id: int
    product_id: int
    score: int
    content: str
    image_urls: list[str]
    status: str


class RefundCreateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class RefundResponse(BaseModel):
    id: int
    order_id: int
    user_id: int
    reason: str
    status: str
    origin_order_status: str

    model_config = {"from_attributes": True}
