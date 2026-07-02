from pydantic import BaseModel, Field


class MerchantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    logo_url: str | None = None
    announcement: str | None = None


class MerchantResponse(BaseModel):
    id: int
    name: str
    logo_url: str | None = None
    announcement: str | None = None

    model_config = {"from_attributes": True}


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    parent_id: int | None = None
    sort_order: int = 0


class CategoryResponse(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    sort_order: int

    model_config = {"from_attributes": True}


class SkuCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price_cent: int = Field(ge=0)
    market_price_cent: int | None = Field(default=None, ge=0)
    stock: int = Field(default=0, ge=0)
    spec_values: dict = Field(default_factory=dict)


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
    skus: list[SkuCreateRequest]


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


class ProductDetailResponse(BaseModel):
    id: int
    name: str
    description: str
    cover_url: str | None = None
    status: str
    images: list[str]
    merchant: MerchantResponse
    skus: list[SkuResponse]
    review_summary: dict = Field(default_factory=lambda: {"count": 0, "average_score": None})


class ProductStatusRequest(BaseModel):
    status: str
