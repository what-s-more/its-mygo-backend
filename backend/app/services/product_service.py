import json

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, ForbiddenException
from app.models.product import Category, HomeBanner, Merchant, MerchantFollow, Product, ProductFavorite, ProductImage, Sku, SkuStockLog
from app.models.order import ProductReview
from app.models.user import AdminUser
from app.schemas.product import (
    CategoryCreateRequest,
    CategoryUpdateRequest,
    HomeBannerCreateRequest,
    HomeBannerUpdateRequest,
    MerchantCreateRequest,
    MerchantFollowItemResponse,
    MerchantFollowStatusResponse,
    MerchantResponse,
    MerchantUpdateRequest,
    ProductCreateRequest,
    ProductDetailResponse,
    ProductFavoriteItemResponse,
    ProductFavoriteStatusResponse,
    ProductListItem,
    ProductUpdateRequest,
    SkuResponse,
    SkuCreateRequest,
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
        if payload.parent_id is not None:
            await self._validate_category_parent(db, payload.parent_id)

        category = Category(**payload.model_dump())
        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    async def update_category(self, db: AsyncSession, category_id: int, payload: CategoryUpdateRequest) -> Category:
        category = await self._get_active_category(db, category_id)
        fields = payload.model_fields_set
        if "name" in fields and payload.name is not None:
            category.name = payload.name
        if "parent_id" in fields:
            if payload.parent_id == category.id:
                raise AppException(40005, "分类不能选择自己作为父级")
            if payload.parent_id is not None:
                await self._validate_category_parent(db, payload.parent_id)
                descendant_ids = await self._collect_category_descendant_ids(db, category.id)
                if payload.parent_id in descendant_ids:
                    raise AppException(40005, "分类不能移动到自己的子分类下")
            category.parent_id = payload.parent_id
        if "sort_order" in fields and payload.sort_order is not None:
            category.sort_order = payload.sort_order

        category_depth = await self._category_depth(db, category)
        subtree_depth = await self._category_subtree_depth(db, category.id)
        if category_depth + subtree_depth - 1 > 3:
            raise AppException(40005, "分类最多支持三级")
        await db.commit()
        await db.refresh(category)
        return category

    async def disable_category(self, db: AsyncSession, category_id: int) -> Category:
        category = await self._get_active_category(db, category_id)
        active_child_count = await db.scalar(
            select(func.count(Category.id)).where(
                Category.parent_id == category_id,
                Category.is_active.is_(True),
            )
        )
        if active_child_count:
            raise AppException(40005, "分类下还有启用子分类，不能停用")
        product_count = await db.scalar(select(func.count(Product.id)).where(Product.category_id == category_id))
        if product_count:
            raise AppException(40005, "分类下还有商品，不能停用")
        category.is_active = False
        await db.commit()
        await db.refresh(category)
        return category

    async def list_home_banners(self, db: AsyncSession, *, include_inactive: bool = False) -> list[HomeBanner]:
        statement = select(HomeBanner).order_by(HomeBanner.sort_order, HomeBanner.id)
        if not include_inactive:
            statement = statement.where(HomeBanner.is_active.is_(True))
        result = await db.execute(statement)
        return list(result.scalars())

    async def create_home_banner(self, db: AsyncSession, payload: HomeBannerCreateRequest) -> HomeBanner:
        target_id, target_url = await self._normalize_home_banner_target(
            db,
            payload.target_type,
            payload.target_id,
            payload.target_url,
        )
        data = payload.model_dump()
        data["target_id"] = target_id
        data["target_url"] = target_url
        banner = HomeBanner(**data)
        db.add(banner)
        await db.commit()
        await db.refresh(banner)
        return banner

    async def update_home_banner(
        self,
        db: AsyncSession,
        banner_id: int,
        payload: HomeBannerUpdateRequest,
    ) -> HomeBanner:
        banner = await db.get(HomeBanner, banner_id)
        if banner is None:
            raise AppException(40004, "轮播图不存在", 404)
        fields = payload.model_fields_set
        next_target_type = payload.target_type if "target_type" in fields and payload.target_type is not None else banner.target_type
        next_target_id = payload.target_id if "target_id" in fields else banner.target_id
        next_target_url = payload.target_url if "target_url" in fields else banner.target_url
        next_target_id, next_target_url = await self._normalize_home_banner_target(
            db,
            next_target_type,
            next_target_id,
            next_target_url,
        )
        for field in fields:
            setattr(banner, field, getattr(payload, field))
        banner.target_type = next_target_type
        banner.target_id = next_target_id
        banner.target_url = next_target_url
        await db.commit()
        await db.refresh(banner)
        return banner

    async def delete_home_banner(self, db: AsyncSession, banner_id: int) -> HomeBanner:
        banner = await db.get(HomeBanner, banner_id)
        if banner is None:
            raise AppException(40004, "轮播图不存在", 404)
        await db.delete(banner)
        await db.commit()
        return banner

    async def create_product(self, db: AsyncSession, payload: ProductCreateRequest) -> Product:
        merchant = await db.get(Merchant, payload.merchant_id)
        if merchant is None:
            raise AppException(40004, "店铺不存在", 404)
        if payload.category_id is not None:
            await self._get_active_category(db, payload.category_id)
        if not payload.skus:
            raise AppException(40001, "至少需要一个 SKU")

        product = Product(
            merchant_id=payload.merchant_id,
            category_id=payload.category_id,
            name=payload.name,
            description=payload.description,
            cover_url=payload.cover_url or (payload.image_urls[0] if payload.image_urls else None),
            detail_image_urls=json.dumps(payload.detail_image_urls, ensure_ascii=False),
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
        min_price_cent: int | None = None,
        max_price_cent: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[Product], int]:
        merchant_scope = self._resolve_admin_merchant_scope(admin, merchant_id)
        return await self.list_products(
            db,
            keyword=keyword,
            category_id=category_id,
            merchant_id=merchant_scope,
            min_price_cent=min_price_cent,
            max_price_cent=max_price_cent,
            sort_by=sort_by,
            sort_order=sort_order,
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
            if payload.category_id is not None:
                await self._get_active_category(db, payload.category_id)
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
        if "detail_image_urls" in fields and payload.detail_image_urls is not None:
            product.detail_image_urls = json.dumps(payload.detail_image_urls, ensure_ascii=False)

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

    async def add_sku_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        product_id: int,
        payload: SkuCreateRequest,
    ) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        product.skus.append(
            Sku(
                name=payload.name,
                price_cent=payload.price_cent,
                market_price_cent=payload.market_price_cent,
                stock=payload.stock,
                spec_values=json.dumps(payload.spec_values, ensure_ascii=False),
            )
        )
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
        min_price_cent: int | None = None,
        max_price_cent: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page: int,
        page_size: int,
        include_off_sale: bool = False,
    ) -> tuple[list[Product], int]:
        if min_price_cent is not None and max_price_cent is not None and min_price_cent > max_price_cent:
            raise AppException(40001, "最低价不能大于最高价")
        if sort_by and sort_by not in {"newest", "created_at", "price", "sales"}:
            raise AppException(40001, "不支持的商品排序字段")
        if sort_order and sort_order.lower() not in {"asc", "desc"}:
            raise AppException(40001, "不支持的排序方向")
        statement = self._product_query(include_off_sale)
        if keyword:
            statement = statement.where(Product.name.like(f"%{keyword}%"))
        if category_id:
            category_ids = await self._collect_category_descendant_ids(db, category_id)
            statement = statement.where(Product.category_id.in_(category_ids))
        if merchant_id:
            statement = statement.where(Product.merchant_id == merchant_id)
        if min_price_cent is not None:
            statement = statement.where(Product.skus.any(Sku.price_cent >= min_price_cent))
        if max_price_cent is not None:
            statement = statement.where(Product.skus.any(Sku.price_cent <= max_price_cent))

        total_statement = select(func.count()).select_from(statement.subquery())
        total = await db.scalar(total_statement) or 0
        price_subquery = (
            select(func.min(Sku.price_cent))
            .where(Sku.product_id == Product.id)
            .correlate(Product)
            .scalar_subquery()
        )
        order_expression = Product.created_at.desc()
        normalized_sort = sort_by or "newest"
        normalized_order = (sort_order or "desc").lower()
        if normalized_sort == "price":
            order_expression = price_subquery.asc() if normalized_order == "asc" else price_subquery.desc()
        elif normalized_sort == "sales":
            order_expression = Product.sales_count.asc() if normalized_order == "asc" else Product.sales_count.desc()
        elif normalized_sort == "created_at":
            order_expression = Product.created_at.asc() if normalized_order == "asc" else Product.created_at.desc()
        result = await db.execute(
            statement.order_by(order_expression, Product.id.desc()).offset((page - 1) * page_size).limit(page_size)
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
        result = await db.execute(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.parent_id.is_not(None), Category.parent_id, Category.sort_order, Category.id)
        )
        return list(result.scalars())

    async def get_merchant(self, db: AsyncSession, merchant_id: int) -> Merchant:
        merchant = await db.get(Merchant, merchant_id)
        if merchant is None:
            raise AppException(40004, "店铺不存在", 404)
        return merchant

    async def get_merchant_follow_status(
        self,
        db: AsyncSession,
        user_id: int | None,
        merchant_id: int,
    ) -> MerchantFollowStatusResponse:
        await self.get_merchant(db, merchant_id)
        follower_count = await self._merchant_follower_count(db, merchant_id)
        followed = False
        if user_id is not None:
            followed = await self._is_merchant_followed(db, user_id, merchant_id)
        return MerchantFollowStatusResponse(
            merchant_id=merchant_id,
            followed=followed,
            follower_count=follower_count,
        )

    async def follow_merchant(self, db: AsyncSession, user_id: int, merchant_id: int) -> MerchantFollowStatusResponse:
        await self.get_merchant(db, merchant_id)
        if not await self._is_merchant_followed(db, user_id, merchant_id):
            db.add(MerchantFollow(user_id=user_id, merchant_id=merchant_id))
            await db.commit()
        return await self.get_merchant_follow_status(db, user_id, merchant_id)

    async def unfollow_merchant(self, db: AsyncSession, user_id: int, merchant_id: int) -> MerchantFollowStatusResponse:
        await self.get_merchant(db, merchant_id)
        result = await db.execute(
            select(MerchantFollow).where(
                MerchantFollow.user_id == user_id,
                MerchantFollow.merchant_id == merchant_id,
            )
        )
        follow = result.scalar_one_or_none()
        if follow is not None:
            await db.delete(follow)
            await db.commit()
        return await self.get_merchant_follow_status(db, user_id, merchant_id)

    async def list_user_followed_merchants(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[MerchantFollowItemResponse], int]:
        statement = (
            select(MerchantFollow, Merchant)
            .join(Merchant, Merchant.id == MerchantFollow.merchant_id)
            .where(MerchantFollow.user_id == user_id, Merchant.is_active.is_(True))
        )
        total_statement = select(func.count()).select_from(statement.subquery())
        total = await db.scalar(total_statement) or 0
        result = await db.execute(
            statement.order_by(MerchantFollow.created_at.desc(), MerchantFollow.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        items: list[MerchantFollowItemResponse] = []
        for follow, merchant in result.all():
            items.append(
                MerchantFollowItemResponse(
                    merchant=MerchantResponse.model_validate(merchant),
                    followed_at=follow.created_at,
                    follower_count=await self._merchant_follower_count(db, merchant.id),
                )
            )
        return items, total

    async def get_product_favorite_status(
        self,
        db: AsyncSession,
        user_id: int | None,
        product_id: int,
    ) -> ProductFavoriteStatusResponse:
        await self.get_product_detail(db, product_id)
        favorite_count = await self._product_favorite_count(db, product_id)
        favorited = False
        if user_id is not None:
            favorited = await self._is_product_favorited(db, user_id, product_id)
        return ProductFavoriteStatusResponse(
            product_id=product_id,
            favorited=favorited,
            favorite_count=favorite_count,
        )

    async def favorite_product(self, db: AsyncSession, user_id: int, product_id: int) -> ProductFavoriteStatusResponse:
        await self.get_product_detail(db, product_id)
        if not await self._is_product_favorited(db, user_id, product_id):
            db.add(ProductFavorite(user_id=user_id, product_id=product_id))
            await db.commit()
        return await self.get_product_favorite_status(db, user_id, product_id)

    async def unfavorite_product(self, db: AsyncSession, user_id: int, product_id: int) -> ProductFavoriteStatusResponse:
        await self.get_product_detail(db, product_id)
        result = await db.execute(
            select(ProductFavorite).where(
                ProductFavorite.user_id == user_id,
                ProductFavorite.product_id == product_id,
            )
        )
        favorite = result.scalar_one_or_none()
        if favorite is not None:
            await db.delete(favorite)
            await db.commit()
        return await self.get_product_favorite_status(db, user_id, product_id)

    async def list_user_favorite_products(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[ProductFavoriteItemResponse], int]:
        statement = (
            select(ProductFavorite, Product)
            .join(Product, Product.id == ProductFavorite.product_id)
            .options(
                selectinload(Product.merchant),
                selectinload(Product.skus),
                selectinload(Product.images),
            )
            .where(ProductFavorite.user_id == user_id, Product.status == "on_sale")
        )
        total_statement = select(func.count()).select_from(statement.subquery())
        total = await db.scalar(total_statement) or 0
        result = await db.execute(
            statement.order_by(ProductFavorite.created_at.desc(), ProductFavorite.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        items: list[ProductFavoriteItemResponse] = []
        for favorite, product in result.unique().all():
            items.append(
                ProductFavoriteItemResponse(
                    product=self.to_list_item(product),
                    favorited_at=favorite.created_at,
                    favorite_count=await self._product_favorite_count(db, product.id),
                )
            )
        return items, total

    async def get_merchant_for_admin(self, db: AsyncSession, admin: AdminUser) -> Merchant:
        if admin.role != "merchant_operator" or admin.merchant_id is None:
            raise ForbiddenException("商家账号未绑定店铺，不能维护店铺资料")
        return await self.get_merchant(db, admin.merchant_id)

    async def _is_merchant_followed(self, db: AsyncSession, user_id: int, merchant_id: int) -> bool:
        result = await db.execute(
            select(MerchantFollow.id).where(
                MerchantFollow.user_id == user_id,
                MerchantFollow.merchant_id == merchant_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _merchant_follower_count(self, db: AsyncSession, merchant_id: int) -> int:
        return await db.scalar(select(func.count(MerchantFollow.id)).where(MerchantFollow.merchant_id == merchant_id)) or 0

    async def _is_product_favorited(self, db: AsyncSession, user_id: int, product_id: int) -> bool:
        result = await db.execute(
            select(ProductFavorite.id).where(
                ProductFavorite.user_id == user_id,
                ProductFavorite.product_id == product_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _product_favorite_count(self, db: AsyncSession, product_id: int) -> int:
        return await db.scalar(select(func.count(ProductFavorite.id)).where(ProductFavorite.product_id == product_id)) or 0

    async def update_merchant_for_admin(
        self,
        db: AsyncSession,
        admin: AdminUser,
        payload: MerchantUpdateRequest,
    ) -> Merchant:
        merchant = await self.get_merchant_for_admin(db, admin)
        fields = payload.model_fields_set
        if "name" in fields and payload.name is not None:
            existing_result = await db.execute(
                select(Merchant.id).where(Merchant.name == payload.name, Merchant.id != merchant.id)
            )
            if existing_result.scalar_one_or_none() is not None:
                raise AppException(40005, "店铺名称已存在")
            merchant.name = payload.name
        if "logo_url" in fields:
            merchant.logo_url = payload.logo_url
        if "announcement" in fields:
            merchant.announcement = payload.announcement
        await db.commit()
        await db.refresh(merchant)
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

    async def delete_product_for_admin(self, db: AsyncSession, admin: AdminUser, product_id: int) -> Product:
        product = await self.get_product_detail_for_admin(db, admin, product_id)
        product.status = "deleted"
        await db.commit()
        return product

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

    async def to_detail_response(self, db: AsyncSession, product: Product) -> ProductDetailResponse:
        review_summary = await self.get_review_summary(db, product.id)
        return ProductDetailResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            cover_url=product.cover_url,
            category_id=product.category_id,
            category_name=product.category.name if product.category else None,
            status=product.status,
            sales_count=product.sales_count,
            images=[image.url for image in sorted(product.images, key=lambda item: item.sort_order)],
            detail_images=json.loads(product.detail_image_urls or "[]"),
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
            review_summary=review_summary,
        )

    async def get_review_summary(self, db: AsyncSession, product_id: int) -> dict:
        result = await db.execute(
            select(func.count(ProductReview.id), func.avg(ProductReview.score)).where(
                ProductReview.product_id == product_id,
                ProductReview.status == "published",
            )
        )
        count, average_score = result.one()
        return {
            "count": count or 0,
            "average_score": round(float(average_score), 1) if average_score is not None else None,
        }

    def _product_query(self, include_off_sale: bool) -> Select[tuple[Product]]:
        statement = select(Product).options(
            selectinload(Product.merchant),
            selectinload(Product.category),
            selectinload(Product.skus),
            selectinload(Product.images),
        ).where(Product.status != "deleted")
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

    async def _get_active_category(self, db: AsyncSession, category_id: int) -> Category:
        category = await db.get(Category, category_id)
        if category is None or not category.is_active:
            raise AppException(40004, "分类不存在", 404)
        return category

    async def _category_depth(self, db: AsyncSession, category: Category) -> int:
        depth = 1
        parent_id = category.parent_id
        visited = {category.id}
        while parent_id is not None:
            if parent_id in visited:
                raise AppException(40005, "分类父子关系异常")
            visited.add(parent_id)
            parent = await self._get_active_category(db, parent_id)
            depth += 1
            parent_id = parent.parent_id
        return depth

    async def _validate_category_parent(self, db: AsyncSession, parent_id: int) -> Category:
        parent = await self._get_active_category(db, parent_id)
        if await self._category_depth(db, parent) >= 3:
            raise AppException(40005, "分类最多支持三级，不能继续添加子分类")
        return parent

    async def _normalize_home_banner_target(
        self,
        db: AsyncSession,
        target_type: str,
        target_id: int | None,
        target_url: str | None,
    ) -> tuple[int | None, str | None]:
        if target_type == "product":
            if target_id is None:
                raise AppException(40001, "跳转商品时必须填写商品 ID")
            await self.get_product_detail(db, target_id, include_off_sale=True)
            return target_id, None
        elif target_type == "url":
            if not target_url:
                raise AppException(40001, "外部链接轮播图必须填写链接")
            return None, target_url
        elif target_type == "none":
            return None, None
        else:
            raise AppException(40001, "轮播图跳转类型不正确")

    async def _category_subtree_depth(self, db: AsyncSession, category_id: int) -> int:
        result = await db.execute(
            select(Category.id, Category.parent_id).where(Category.is_active.is_(True))
        )
        children_by_parent: dict[int | None, list[int]] = {}
        for child_id, parent_id in result.all():
            children_by_parent.setdefault(parent_id, []).append(child_id)

        def walk(current_id: int) -> int:
            children = children_by_parent.get(current_id, [])
            if not children:
                return 1
            return 1 + max(walk(child_id) for child_id in children)

        return walk(category_id)

    async def _collect_category_descendant_ids(self, db: AsyncSession, category_id: int) -> list[int]:
        await self._get_active_category(db, category_id)
        result = await db.execute(
            select(Category.id, Category.parent_id).where(Category.is_active.is_(True))
        )
        children_by_parent: dict[int | None, list[int]] = {}
        for child_id, parent_id in result.all():
            children_by_parent.setdefault(parent_id, []).append(child_id)

        collected: list[int] = []
        stack = [category_id]
        while stack:
            current_id = stack.pop()
            if current_id in collected:
                continue
            collected.append(current_id)
            stack.extend(children_by_parent.get(current_id, []))
        return collected


product_service = ProductService()
