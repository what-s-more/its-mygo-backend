import json

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.models.product import Category, Merchant, Product, ProductImage, Sku
from app.schemas.product import (
    CategoryCreateRequest,
    MerchantCreateRequest,
    ProductCreateRequest,
    ProductDetailResponse,
    ProductListItem,
    SkuResponse,
)


class ProductService:
    async def create_merchant(self, db: AsyncSession, payload: MerchantCreateRequest) -> Merchant:
        merchant = Merchant(**payload.model_dump())
        db.add(merchant)
        await db.commit()
        await db.refresh(merchant)
        return merchant

    async def create_category(self, db: AsyncSession, payload: CategoryCreateRequest) -> Category:
        category = Category(**payload.model_dump())
        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    async def create_product(self, db: AsyncSession, payload: ProductCreateRequest) -> Product:
        merchant = await db.get(Merchant, payload.merchant_id)
        if merchant is None:
            raise AppException(40004, "店铺不存在", 404)
        if payload.category_id is not None and await db.get(Category, payload.category_id) is None:
            raise AppException(40004, "分类不存在", 404)
        if not payload.skus:
            raise AppException(40001, "至少需要一个 SKU")

        product = Product(
            merchant_id=payload.merchant_id,
            category_id=payload.category_id,
            name=payload.name,
            description=payload.description,
            cover_url=payload.cover_url or (payload.image_urls[0] if payload.image_urls else None),
            status="draft",
        )
        product.skus = [
            Sku(
                name=sku.name,
                price_cent=sku.price_cent,
                market_price_cent=sku.market_price_cent,
                stock=sku.stock,
                spec_values=json.dumps(sku.spec_values, ensure_ascii=False),
            )
            for sku in payload.skus
        ]
        product.images = [
            ProductImage(url=url, sort_order=index) for index, url in enumerate(payload.image_urls)
        ]
        db.add(product)
        await db.commit()
        return await self.get_product_detail(db, product.id, include_off_sale=True)

    async def list_products(
        self,
        db: AsyncSession,
        *,
        keyword: str | None,
        category_id: int | None,
        merchant_id: int | None,
        page: int,
        page_size: int,
        include_off_sale: bool = False,
    ) -> tuple[list[Product], int]:
        statement = self._product_query(include_off_sale)
        if keyword:
            statement = statement.where(Product.name.like(f"%{keyword}%"))
        if category_id:
            statement = statement.where(Product.category_id == category_id)
        if merchant_id:
            statement = statement.where(Product.merchant_id == merchant_id)

        total_statement = select(func.count()).select_from(statement.subquery())
        total = await db.scalar(total_statement) or 0
        result = await db.execute(
            statement.order_by(Product.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().unique()), total

    async def get_product_detail(
        self,
        db: AsyncSession,
        product_id: int,
        *,
        include_off_sale: bool = False,
    ) -> Product:
        statement = self._product_query(include_off_sale).where(Product.id == product_id)
        result = await db.execute(statement)
        product = result.scalars().unique().one_or_none()
        if product is None:
            raise AppException(40004, "商品不存在", 404)
        return product

    async def list_categories(self, db: AsyncSession) -> list[Category]:
        result = await db.execute(select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order))
        return list(result.scalars())

    async def get_merchant(self, db: AsyncSession, merchant_id: int) -> Merchant:
        merchant = await db.get(Merchant, merchant_id)
        if merchant is None:
            raise AppException(40004, "店铺不存在", 404)
        return merchant

    async def publish_product(self, db: AsyncSession, product_id: int) -> Product:
        product = await self.get_product_detail(db, product_id, include_off_sale=True)
        product.status = "on_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def unpublish_product(self, db: AsyncSession, product_id: int) -> Product:
        product = await self.get_product_detail(db, product_id, include_off_sale=True)
        product.status = "off_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    def to_list_item(self, product: Product) -> ProductListItem:
        first_sku = product.skus[0] if product.skus else None
        return ProductListItem(
            id=product.id,
            name=product.name,
            cover_url=product.cover_url,
            price_cent=first_sku.price_cent if first_sku else 0,
            market_price_cent=first_sku.market_price_cent if first_sku else None,
            merchant_id=product.merchant_id,
            merchant_name=product.merchant.name,
            sales_count=product.sales_count,
            tags=[],
        )

    def to_detail_response(self, product: Product) -> ProductDetailResponse:
        return ProductDetailResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            cover_url=product.cover_url,
            status=product.status,
            images=[image.url for image in sorted(product.images, key=lambda item: item.sort_order)],
            merchant=product.merchant,
            skus=[
                SkuResponse(
                    id=sku.id,
                    name=sku.name,
                    price_cent=sku.price_cent,
                    market_price_cent=sku.market_price_cent,
                    stock=sku.stock,
                    spec_values=json.loads(sku.spec_values or "{}"),
                )
                for sku in product.skus
            ],
        )

    def _product_query(self, include_off_sale: bool) -> Select[tuple[Product]]:
        statement = select(Product).options(
            selectinload(Product.merchant),
            selectinload(Product.skus),
            selectinload(Product.images),
        )
        if not include_off_sale:
            statement = statement.where(Product.status == "on_sale")
        return statement


product_service = ProductService()
