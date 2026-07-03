from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.product import Sku, SkuStockLog


class InventoryService:
    async def change_stock(
        self,
        db: AsyncSession,
        sku: Sku,
        *,
        change_quantity: int,
        change_type: str,
        remark: str = "",
        admin_id: int | None = None,
        allow_negative: bool = False,
    ) -> SkuStockLog | None:
        if change_quantity == 0:
            return None
        before_stock = sku.stock
        after_stock = before_stock + change_quantity
        if after_stock < 0 and not allow_negative:
            raise AppException(40007, "库存不足")
        sku.stock = after_stock
        log = SkuStockLog(
            product_id=sku.product_id,
            sku_id=sku.id,
            before_stock=before_stock,
            change_quantity=change_quantity,
            after_stock=after_stock,
            change_type=change_type,
            remark=remark,
            admin_id=admin_id,
        )
        db.add(log)
        return log

    async def set_stock(
        self,
        db: AsyncSession,
        sku: Sku,
        *,
        target_stock: int,
        change_type: str = "manual_adjust",
        remark: str = "",
        admin_id: int | None = None,
    ) -> SkuStockLog | None:
        return await self.change_stock(
            db,
            sku,
            change_quantity=target_stock - sku.stock,
            change_type=change_type,
            remark=remark,
            admin_id=admin_id,
        )


inventory_service = InventoryService()
