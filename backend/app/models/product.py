from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Merchant(Base):
    __tablename__ = "merchant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    announcement: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    products: Mapped[list["Product"]] = relationship(back_populates="merchant")


class MerchantFollow(Base):
    __tablename__ = "merchant_follow"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductFavorite(Base):
    __tablename__ = "product_favorite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    sales_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    merchant: Mapped[Merchant] = relationship(back_populates="products")
    skus: Mapped[list["Sku"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    images: Mapped[list["ProductImage"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Sku(Base):
    __tablename__ = "sku"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    price_cent: Mapped[int] = mapped_column(Integer)
    market_price_cent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    spec_values: Mapped[str] = mapped_column(Text, default="{}")

    product: Mapped[Product] = relationship(back_populates="skus")


class SkuStockLog(Base):
    __tablename__ = "sku_stock_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku.id"), index=True)
    before_stock: Mapped[int] = mapped_column(Integer)
    change_quantity: Mapped[int] = mapped_column(Integer)
    after_stock: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(30), default="manual_adjust", index=True)
    remark: Mapped[str] = mapped_column(String(255), default="")
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductImage(Base):
    __tablename__ = "product_image"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    url: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="images")
