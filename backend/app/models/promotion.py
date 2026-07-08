from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CouponTemplate(Base):
    __tablename__ = "coupon_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    scope_type: Mapped[str] = mapped_column(String(20), default="all", index=True)
    scope_ids: Mapped[str] = mapped_column(String(500), default="[]")
    owner_merchant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_type: Mapped[str] = mapped_column(String(20), default="amount")
    discount_value: Mapped[int] = mapped_column(Integer)
    min_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    total_quantity: Mapped[int] = mapped_column(Integer, default=0)
    claimed_quantity: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user_coupons: Mapped[list["UserCoupon"]] = relationship(back_populates="template")


class UserCoupon(Base):
    __tablename__ = "user_coupon"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    coupon_template_id: Mapped[int] = mapped_column(ForeignKey("coupon_template.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="unused", index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped[CouponTemplate] = relationship(back_populates="user_coupons")


class FullDiscountActivity(Base):
    __tablename__ = "full_discount_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    scope_type: Mapped[str] = mapped_column(String(20), default="all", index=True)
    scope_ids: Mapped[str] = mapped_column(String(500), default="[]")
    owner_merchant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    discount_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
