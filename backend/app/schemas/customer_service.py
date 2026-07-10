from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CustomerServiceConversationCreateRequest(BaseModel):
    target_type: str = Field(default="merchant", pattern="^(merchant|platform)$")
    merchant_id: int | None = Field(default=None, ge=1)
    product_id: int | None = Field(default=None, ge=1)
    order_id: int | None = Field(default=None, ge=1)
    initial_message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_type == "merchant" and self.merchant_id is None:
            raise ValueError("商家客服会话必须指定 merchant_id")
        if self.target_type == "platform":
            self.merchant_id = None
        return self


class CustomerServiceMessageCreateRequest(BaseModel):
    content_type: str = Field(default="text", pattern="^(text|image)$")
    content: str = Field(default="", max_length=2000)
    image_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_content(self):
        if not self.content.strip() and not self.image_urls:
            raise ValueError("消息内容不能为空")
        return self


class CustomerServiceConversationResponse(BaseModel):
    id: int
    user_id: int
    user_nickname: str | None = None
    target_type: str
    merchant_id: int | None = None
    merchant_name: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    order_id: int | None = None
    order_no: str | None = None
    status: str
    last_message_at: datetime | None = None
    last_message: str | None = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class CustomerServiceMessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_type: str
    sender_id: int
    sender_name: str | None = None
    content_type: str
    content: str
    image_urls: list[str]
    is_read: bool
    created_at: datetime
