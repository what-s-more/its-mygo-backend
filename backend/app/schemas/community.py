from datetime import datetime

from pydantic import BaseModel, Field


class AuthorSummary(BaseModel):
    id: int
    nickname: str
    avatar_url: str | None = None


class PostCreateRequest(BaseModel):
    type: str = Field(default="normal", pattern="^(normal|grass|merchant_ad)$")
    section: str = Field(default="square", pattern="^(square|grass|merchant|help|experience)$")
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=5000)
    image_urls: list[str] = Field(default_factory=list)
    product_ids: list[int] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)


class PostAuditRequest(BaseModel):
    approved: bool


class CommentCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class CommentAuditRequest(BaseModel):
    approved: bool


class CommentResponse(BaseModel):
    id: int
    post_id: int
    author: AuthorSummary
    content: str
    status: str
    created_at: datetime


class PostResponse(BaseModel):
    id: int
    merchant_id: int | None = None
    type: str
    section: str
    title: str
    content: str
    image_urls: list[str]
    product_ids: list[int]
    topic_tags: list[str]
    status: str
    author: AuthorSummary
    like_count: int
    favorite_count: int
    favorited: bool = False
    comment_count: int
    created_at: datetime


class CommunityUserProfileResponse(BaseModel):
    user: AuthorSummary
    post_count: int
    grass_post_count: int
    comment_count: int
    like_received_count: int
    recent_posts: list[PostResponse]


class TopicResponse(BaseModel):
    name: str
    post_count: int


class LikeToggleResponse(BaseModel):
    liked: bool
    like_count: int


class FavoriteToggleResponse(BaseModel):
    favorited: bool
    favorite_count: int


class FavoritePostItem(BaseModel):
    post: PostResponse
    favorited_at: datetime
