import json

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, ForbiddenException
from app.models.product import Category, Merchant, Product, ProductImage, Sku, SkuStockLog
from app.models.user import AdminUser
from app.schemas.product import (
    CategoryCreateRequest,
    MerchantCreateRequest,
    ProductCreateRequest,
    ProductDetailResponse,
    ProductListItem,
    ProductUpdateRequest,
    SkuResponse,
    SkuStockLogResponse,
    SkuUpdateRequest,
)
from app.services.inventory_service import inventory_service


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
            status="on_sale",
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

    async def create_product_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        payload: ProductCreateRequest,
    ) -> Product:
        if admin.role != "merchant_operator":
            raise ForbiddenException("商品必须由已入驻商家创建，平台仅负责分类和商品监管")
        self._assert_can_manage_merchant(admin, payload.merchant_id)
        return await self.create_product(db, payload)

    async def list_admin_products(
        self,
        db: AsyncSession,
        admin: AdminUser,
        *,
        keyword: str | None,
        category_id: int | None,
        merchant_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Product], int]:
        merchant_scope = self._resolve_admin_merchant_scope(admin, merchant_id)
        return await self.list_products(
            db,
            keyword=keyword,
            category_id=category_id,
            merchant_id=merchant_scope,
            page=page,
            page_size=page_size,
            include_off_sale=True,
        )

    async def get_product_detail_for_admin(self, db: AsyncSession, admin: AdminUser, product_id: int) -> Product:
        product = await self.get_product_detail(db, product_id, include_off_sale=True)
        self._assert_can_manage_merchant(admin, product.merchant_id)
        return product

    async def update_product_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        product_id: int,
        payload: ProductUpdateRequest,
    ) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        fields = payload.model_fields_set
        if "category_id" in fields:
            if payload.category_id is not None and await db.get(Category, payload.category_id) is None:
                raise AppException(40004, "分类不存在", 404)
            product.category_id = payload.category_id
        if "name" in fields and payload.name is not None:
            product.name = payload.name
        if "description" in fields and payload.description is not None:
            product.description = payload.description
        if "cover_url" in fields:
            product.cover_url = payload.cover_url
        if "image_urls" in fields and payload.image_urls is not None:
            product.images = [
                ProductImage(url=url, sort_order=index) for index, url in enumerate(payload.image_urls)
            ]
            if "cover_url" not in fields and payload.image_urls:
                product.cover_url = payload.image_urls[0]

        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def update_sku_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        product_id: int,
        sku_id: int,
        payload: SkuUpdateRequest,
    ) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        sku = next((item for item in product.skus if item.id == sku_id), None)
        if sku is None:
            raise AppException(40004, "SKU 不存在", 404)

        fields = payload.model_fields_set
        if "name" in fields and payload.name is not None:
            sku.name = payload.name
        if "price_cent" in fields and payload.price_cent is not None:
            sku.price_cent = payload.price_cent
        if "market_price_cent" in fields:
            sku.market_price_cent = payload.market_price_cent
        if "stock" in fields and payload.stock is not None:
            await inventory_service.set_stock(
                db,
                sku,
                target_stock=payload.stock,
                change_type="manual_adjust",
                remark="管理端手动调整库存",
                admin_id=admin.id,
            )
        if "spec_values" in fields and payload.spec_values is not None:
            sku.spec_values = json.dumps(payload.spec_values, ensure_ascii=False)

        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def list_sku_stock_logs_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        product_id: int,
        sku_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[SkuStockLogResponse], int]:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        if not any(item.id == sku_id for item in product.skus):
            raise AppException(40004, "SKU 不存在", 404)
        statement = select(SkuStockLog).where(
            SkuStockLog.product_id == product_id,
            SkuStockLog.sku_id == sku_id,
        )
        total_statement = select(func.count()).select_from(statement.subquery())
        total = await db.scalar(total_statement) or 0
        result = await db.execute(
            statement.order_by(SkuStockLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        return [SkuStockLogResponse.model_validate(log) for log in result.scalars()], total

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

    async def publish_product_for_admin(self, db: AsyncSession, admin: AdminUser, product_id: int) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        product.status = "on_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def submit_product_audit_for_admin(self, db: AsyncSession, admin: AdminUser, product_id: int) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        if product.status not in {"draft", "off_sale", "audit_rejected", "on_sale"}:
            raise AppException(40008, "当前商品状态不允许提交")
        product.status = "on_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def audit_product(self, db: AsyncSession, product_id: int, approved: bool) -> Product:
        product = await self.get_product_detail(db, product_id, include_off_sale=True)
        product.status = "on_sale" if approved else "off_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def unpublish_product(self, db: AsyncSession, product_id: int) -> Product:
        product = await self.get_product_detail(db, product_id, include_off_sale=True)
        product.status = "off_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def unpublish_product_for_admin(self, db: AsyncSession, admin: AdminUser, product_id: int) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        product.status = "off_sale"
        await db.commit()
        return await self.get_product_detail(db, product_id, include_off_sale=True)

    async def batch_update_product_status_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        product_ids: list[int],
        status: str,
    ) -> list[Product]:
        products: list[Product] = []
        for product_id in dict.fromkeys(product_ids):
            product = await self.get_product_detail_for_admin(db, admin, product_id)
            product.status = status
            products.append(product)
        await db.commit()
        refreshed_products = [
            await self.get_product_detail(db, product.id, include_off_sale=True)
            for product in products
        ]
        return refreshed_products

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
            category_id=product.category_id,
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

    def _assert_can_manage_merchant(self, admin: AdminUser, merchant_id: int) -> None:
        if admin.role not in {"platform_operator", "merchant_operator"}:
            raise ForbiddenException("当前账号尚未获得商家管理权限")
        if admin.role == "merchant_operator":
            if admin.merchant_id is None:
                raise ForbiddenException("商家管理员未绑定店铺")
            if admin.merchant_id != merchant_id:
                raise ForbiddenException("不能操作其他店铺数据")

    def _resolve_admin_merchant_scope(self, admin: AdminUser, merchant_id: int | None) -> int | None:
        if admin.role not in {"platform_operator", "merchant_operator"}:
            raise ForbiddenException("当前账号尚未获得商家管理权限")
        if admin.role == "merchant_operator":
            if admin.merchant_id is None:
                raise ForbiddenException("商家管理员未绑定店铺")
            if merchant_id is not None and merchant_id != admin.merchant_id:
                raise ForbiddenException("不能查看其他店铺数据")
            return admin.merchant_id
        return merchant_id


product_service = ProductService()
