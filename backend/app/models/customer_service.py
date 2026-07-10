from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CustomerServiceConversation(Base):
    __tablename__ = "customer_service_conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(20), default="merchant", index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchant.id"), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CustomerServiceMessage(Base):
    __tablename__ = "customer_service_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("customer_service_conversation.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(20), index=True)
    sender_id: Mapped[int] = mapped_column(Integer, index=True)
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    image_urls: Mapped[str] = mapped_column(Text, default="[]")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
