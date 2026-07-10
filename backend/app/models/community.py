from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommunityPost(Base):
    __tablename__ = "community_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchant.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    section: Mapped[str] = mapped_column(String(30), default="square", index=True)
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, default="")
    image_urls: Mapped[str] = mapped_column(Text, default="[]")
    product_ids: Mapped[str] = mapped_column(Text, default="[]")
    topic_tags: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="pending_audit", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CommunityComment(Base):
    __tablename__ = "community_comment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("community_post.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending_audit", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommunityLike(Base):
    __tablename__ = "community_like"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_community_like_post_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("community_post.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommunityPostFavorite(Base):
    __tablename__ = "community_post_favorite"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_community_post_favorite_post_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("community_post.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GrassConversionReward(Base):
    __tablename__ = "grass_conversion_reward"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("community_post.id"), index=True)
    source_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    buyer_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
