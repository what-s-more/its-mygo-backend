from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GroupBuyActivity(Base):
    __tablename__ = "group_buy_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    group_size: Mapped[int] = mapped_column(Integer, default=2)
    group_price_cent: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class GroupBuyGroup(Base):
    __tablename__ = "group_buy_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("group_buy_activity.id"), index=True)
    leader_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupBuyParticipant(Base):
    __tablename__ = "group_buy_participant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("group_buy_group.id"), index=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("group_buy_activity.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
