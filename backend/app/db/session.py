from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.app_env == "development")
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app.db.base import Base
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            await _patch_sqlite_order_columns(conn)
            await _patch_sqlite_cart_item_columns(conn)
            await _patch_sqlite_payment_columns(conn)
            await _patch_sqlite_community_post_columns(conn)
            await _patch_sqlite_refund_columns(conn)
            await _patch_sqlite_coupon_template_columns(conn)
            await _patch_sqlite_full_discount_columns(conn)
            await _patch_sqlite_points_log_columns(conn)
            await _patch_sqlite_admin_operation_log_columns(conn)
            await _patch_sqlite_merchant_application_columns(conn)
            await _patch_sqlite_user_columns(conn)
            await _patch_sqlite_user_address_columns(conn)
            await _seed_default_categories(conn)


async def _patch_sqlite_order_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(orders)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "full_discount_amount_cent": "INTEGER DEFAULT 0",
        "coupon_discount_amount_cent": "INTEGER DEFAULT 0",
        "points_discount_amount_cent": "INTEGER DEFAULT 0",
        "points_used": "INTEGER DEFAULT 0",
        "shipping_address_snapshot": "TEXT",
        "logistics_company": "VARCHAR(80)",
        "tracking_no": "VARCHAR(80)",
        "shipped_at": "DATETIME",
        "received_at": "DATETIME",
        "source_post_id": "INTEGER",
        "source_user_id": "INTEGER",
        "grass_rewarded": "BOOLEAN DEFAULT 0",
        "order_type": "VARCHAR(30) DEFAULT 'normal'",
        "group_buy_activity_id": "INTEGER",
        "group_buy_group_id": "INTEGER",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_cart_item_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(cart_item)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "source_post_id": "INTEGER",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE cart_item ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_community_post_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(community_post)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "section": "VARCHAR(30) DEFAULT 'square'",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE community_post ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_payment_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(payment)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "points_used": "INTEGER DEFAULT 0",
        "points_discount_amount_cent": "INTEGER DEFAULT 0",
        "channel": "VARCHAR(30) DEFAULT 'mock'",
        "alipay_trade_no": "VARCHAR(80)",
        "alipay_qr_code": "TEXT",
        "alipay_buyer_logon_id": "VARCHAR(120)",
        "closed_at": "DATETIME",
        "alipay_notify_at": "DATETIME",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE payment ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_refund_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(refund)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "order_item_id": "INTEGER",
        "product_id": "INTEGER",
        "sku_id": "INTEGER",
        "quantity": "INTEGER DEFAULT 0",
        "refund_amount_cent": "INTEGER DEFAULT 0",
        "reason_type": "VARCHAR(50) DEFAULT 'other'",
        "image_urls": "TEXT DEFAULT '[]'",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE refund ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_coupon_template_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(coupon_template)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "scope_type": "VARCHAR(20) DEFAULT 'all'",
        "scope_ids": "VARCHAR(500) DEFAULT '[]'",
        "owner_merchant_id": "INTEGER",
        "created_by_admin_id": "INTEGER",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE coupon_template ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_full_discount_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(full_discount_activity)"))
    if not result.fetchall():
        return
    result = await conn.execute(text("PRAGMA table_info(full_discount_activity)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "owner_merchant_id": "INTEGER",
        "created_by_admin_id": "INTEGER",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE full_discount_activity ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_points_log_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(points_log)"))
    if not result.fetchall():
        return
    result = await conn.execute(text("PRAGMA table_info(points_log)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "source_id": "INTEGER",
        "description": "VARCHAR(255) DEFAULT ''",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE points_log ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_admin_operation_log_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(admin_operation_log)"))
    if not result.fetchall():
        return
    result = await conn.execute(text("PRAGMA table_info(admin_operation_log)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "resource_id": "INTEGER",
        "description": "VARCHAR(255) DEFAULT ''",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE admin_operation_log ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_merchant_application_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(merchant_application)"))
    if not result.fetchall():
        return
    result = await conn.execute(text("PRAGMA table_info(merchant_application)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "merchant_id": "INTEGER",
        "reviewed_by": "INTEGER",
        "reject_reason": "VARCHAR(255)",
        "reviewed_at": "DATETIME",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE merchant_application ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_user_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(user)"))
    if not result.fetchall():
        return
    result = await conn.execute(text("PRAGMA table_info(user)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "gender": "VARCHAR(20)",
        "birthday": "DATE",
        "email": "VARCHAR(120)",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_user_address_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(user_address)"))
    if not result.fetchall():
        return
    result = await conn.execute(text("PRAGMA table_info(user_address)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "street": "VARCHAR(80)",
        "postal_code": "VARCHAR(20)",
        "address_tag": "VARCHAR(30)",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE user_address ADD COLUMN {column_name} {column_type}"))


async def _seed_default_categories(conn) -> None:
    default_categories = [
        "食品生鲜",
        "美妆个护",
        "家居日用",
        "数码家电",
        "服饰鞋包",
        "母婴用品",
        "运动户外",
        "图书文创",
        "宠物生活",
        "本地服务",
    ]
    for index, name in enumerate(default_categories, start=1):
        result = await conn.execute(text("SELECT id FROM category WHERE name = :name LIMIT 1"), {"name": name})
        if result.fetchone() is None:
            await conn.execute(
                text("INSERT INTO category (name, parent_id, sort_order, is_active) VALUES (:name, NULL, :sort_order, 1)"),
                {"name": name, "sort_order": index * 10},
            )
