from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CartItem(Base):
    __tablename__ = "cart_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    checked: Mapped[bool] = mapped_column(Boolean, default=True)
    source_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Payment(Base):
    __tablename__ = "payment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payment_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="unpaid", index=True)
    pay_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    points_used: Mapped[int] = mapped_column(Integer, default=0)
    points_discount_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(30), default="mock", index=True)
    alipay_trade_no: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    alipay_qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    alipay_buyer_logon_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alipay_notify_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    orders: Mapped[list["Order"]] = relationship(back_populates="payment")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", index=True)
    total_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    pay_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    full_discount_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    coupon_discount_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    points_discount_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    points_used: Mapped[int] = mapped_column(Integer, default=0)
    client_order_token: Mapped[str] = mapped_column(String(80), index=True)
    source_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    grass_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    order_type: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    group_buy_activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    group_buy_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    shipping_address_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    logistics_company: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    payment: Mapped[Payment] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(120))
    sku_name: Mapped[str] = mapped_column(String(80))
    unit_price_cent: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    total_amount_cent: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


class ProductReview(Base):
    __tablename__ = "product_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, default="")
    image_urls: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="pending_audit", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Refund(Base):
    __tablename__ = "refund"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_item.id"), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"), nullable=True, index=True)
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("sku.id"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    refund_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    reason_type: Mapped[str] = mapped_column(String(50), default="other")
    reason: Mapped[str] = mapped_column(String(255))
    image_urls: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", index=True)
    origin_order_status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RefundLog(Base):
    __tablename__ = "refund_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    refund_id: Mapped[int] = mapped_column(ForeignKey("refund.id"), index=True)
    operator_type: Mapped[str] = mapped_column(String(20), default="system")
    operator_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
