from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=settings.database_url.startswith("mysql"),
    pool_recycle=1800 if settings.database_url.startswith("mysql") else -1,
)
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
            await _patch_sqlite_product_columns(conn)
            await _patch_sqlite_order_columns(conn)
            await _patch_sqlite_cart_item_columns(conn)
            await _patch_sqlite_payment_columns(conn)
            await _patch_sqlite_community_post_columns(conn)
            await _patch_sqlite_community_post_favorite_table(conn)
            await _patch_sqlite_customer_service_tables(conn)
            await _patch_sqlite_refund_columns(conn)
            await _patch_sqlite_coupon_template_columns(conn)
            await _patch_sqlite_full_discount_columns(conn)
            await _patch_sqlite_points_log_columns(conn)
            await _patch_sqlite_admin_operation_log_columns(conn)
            await _patch_sqlite_merchant_application_columns(conn)
            await _patch_sqlite_user_columns(conn)
            await _patch_sqlite_user_address_columns(conn)
            await _patch_sqlite_home_banner_table(conn)


async def _patch_sqlite_product_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(product)"))
    existing_columns = {row[1] for row in result.fetchall()}
    columns = {
        "detail_image_urls": "TEXT DEFAULT '[]'",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE product ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_home_banner_table(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS home_banner (
                id INTEGER NOT NULL PRIMARY KEY,
                title VARCHAR(80) NOT NULL,
                subtitle VARCHAR(160),
                image_url VARCHAR(255) NOT NULL,
                target_type VARCHAR(30) DEFAULT 'none' NOT NULL,
                target_id INTEGER,
                target_url VARCHAR(255),
                sort_order INTEGER DEFAULT 0 NOT NULL,
                is_active BOOLEAN DEFAULT 1 NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_home_banner_id ON home_banner (id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_home_banner_is_active ON home_banner (is_active)"))


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
        "merchant_id": "INTEGER",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE community_post ADD COLUMN {column_name} {column_type}"))


async def _patch_sqlite_community_post_favorite_table(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS community_post_favorite (
                id INTEGER NOT NULL PRIMARY KEY,
                post_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_community_post_favorite_post_user UNIQUE (post_id, user_id),
                FOREIGN KEY(post_id) REFERENCES community_post (id),
                FOREIGN KEY(user_id) REFERENCES user (id)
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_community_post_favorite_id ON community_post_favorite (id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_community_post_favorite_post_id ON community_post_favorite (post_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_community_post_favorite_user_id ON community_post_favorite (user_id)"))


async def _patch_sqlite_customer_service_tables(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS customer_service_conversation (
                id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                target_type VARCHAR(20) DEFAULT 'merchant',
                merchant_id INTEGER,
                product_id INTEGER,
                order_id INTEGER,
                status VARCHAR(30) DEFAULT 'open',
                last_message_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES user (id),
                FOREIGN KEY(merchant_id) REFERENCES merchant (id),
                FOREIGN KEY(product_id) REFERENCES product (id),
                FOREIGN KEY(order_id) REFERENCES orders (id)
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS customer_service_message (
                id INTEGER NOT NULL PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                sender_type VARCHAR(20) NOT NULL,
                sender_id INTEGER NOT NULL,
                content_type VARCHAR(20) DEFAULT 'text',
                content TEXT DEFAULT '',
                image_urls TEXT DEFAULT '[]',
                is_read BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(conversation_id) REFERENCES customer_service_conversation (id)
            )
            """
        )
    )
    for table, columns in {
        "customer_service_conversation": ["id", "user_id", "target_type", "merchant_id", "status"],
        "customer_service_message": ["id", "conversation_id", "sender_type", "sender_id"],
    }.items():
        for column in columns:
            await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})"))


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
