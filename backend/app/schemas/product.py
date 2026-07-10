from datetime import datetime

from pydantic import BaseModel, Field


class MerchantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    logo_url: str | None = None
    announcement: str | None = None


class MerchantUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    logo_url: str | None = Field(default=None, max_length=255)
    announcement: str | None = Field(default=None, max_length=255)


class MerchantResponse(BaseModel):
    id: int
    name: str
    logo_url: str | None = None
    announcement: str | None = None

    model_config = {"from_attributes": True}


class MerchantFollowStatusResponse(BaseModel):
    merchant_id: int
    followed: bool
    follower_count: int


class MerchantFollowItemResponse(BaseModel):
    merchant: MerchantResponse
    followed_at: datetime
    follower_count: int


class ProductFavoriteStatusResponse(BaseModel):
    product_id: int
    favorited: bool
    favorite_count: int


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    parent_id: int | None = None
    sort_order: int = 0


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    parent_id: int | None = None
    sort_order: int | None = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    sort_order: int

    model_config = {"from_attributes": True}


class HomeBannerCreateRequest(BaseModel):
    title: str = Field(default="", max_length=80)
    subtitle: str | None = Field(default=None, max_length=160)
    image_url: str = Field(min_length=1, max_length=255)
    target_type: str = Field(default="none", pattern="^(none|product|url)$")
    target_id: int | None = Field(default=None, ge=1)
    target_url: str | None = Field(default=None, max_length=255)
    sort_order: int = 0
    is_active: bool = True


class HomeBannerUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    subtitle: str | None = Field(default=None, max_length=160)
    image_url: str | None = Field(default=None, min_length=1, max_length=255)
    target_type: str | None = Field(default=None, pattern="^(none|product|url)$")
    target_id: int | None = Field(default=None, ge=1)
    target_url: str | None = Field(default=None, max_length=255)
    sort_order: int | None = None
    is_active: bool | None = None


class HomeBannerResponse(BaseModel):
    id: int
    title: str
    subtitle: str | None = None
    image_url: str
    target_type: str
    target_id: int | None = None
    target_url: str | None = None
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class SkuCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price_cent: int = Field(ge=0)
    market_price_cent: int | None = Field(default=None, ge=0)
    stock: int = Field(default=0, ge=0)
    spec_values: dict = Field(default_factory=dict)


class SkuUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    price_cent: int | None = Field(default=None, ge=0)
    market_price_cent: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    spec_values: dict | None = None


class SkuResponse(BaseModel):
    id: int
    name: str
    price_cent: int
    market_price_cent: int | None = None
    stock: int
    spec_values: dict


class ProductCreateRequest(BaseModel):
    merchant_id: int
    category_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    cover_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    detail_image_urls: list[str] = Field(default_factory=list)
    skus: list[SkuCreateRequest]


class ProductUpdateRequest(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    cover_url: str | None = None
    image_urls: list[str] | None = None
    detail_image_urls: list[str] | None = None


class ProductListItem(BaseModel):
    id: int
    name: str
    cover_url: str | None = None
    price_cent: int
    market_price_cent: int | None = None
    merchant_id: int
    merchant_name: str
    sales_count: int
    tags: list[str] = []


class ProductFavoriteItemResponse(BaseModel):
    product: ProductListItem
    favorited_at: datetime
    favorite_count: int


class ProductDetailResponse(BaseModel):
    id: int
    name: str
    description: str
    cover_url: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    status: str
    sales_count: int = 0
    images: list[str]
    detail_images: list[str] = Field(default_factory=list)
    merchant: MerchantResponse
    skus: list[SkuResponse]
    review_summary: dict = Field(default_factory=lambda: {"count": 0, "average_score": None})


class ProductStatusRequest(BaseModel):
    status: str


class ProductAuditRequest(BaseModel):
    approved: bool


class ProductBatchRequest(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=100)


class SkuStockLogResponse(BaseModel):
    id: int
    product_id: int
    sku_id: int
    before_stock: int
    change_quantity: int
    after_stock: int
    change_type: str
    remark: str
    admin_id: int | None = None

    model_config = {"from_attributes": True}
