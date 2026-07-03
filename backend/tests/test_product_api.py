from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.product import Merchant
from app.models.user import AdminUser


async def create_admin_token(client: AsyncClient) -> str:
    username = f"product_admin_{str(uuid4().int)[-8:]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="商品管理员",
                role="platform_operator",
                password_hash=hash_password(password),
            )
        )
        await session.commit()
    response = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


async def create_merchant_admin_token(client: AsyncClient, merchant_id: int) -> str:
    username = f"merchant_product_admin_{uuid4().hex[:8]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="Merchant Product Admin",
                role="merchant_operator",
                merchant_id=merchant_id,
                password_hash=hash_password(password),
            )
        )
        await session.commit()
    response = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


async def create_test_merchant(name_prefix: str = "Test Merchant") -> int:
    async with AsyncSessionLocal() as session:
        merchant = Merchant(name=f"{name_prefix}-{uuid4().hex[:8]}")
        session.add(merchant)
        await session.commit()
        await session.refresh(merchant)
        return merchant.id


@pytest.mark.asyncio
async def test_admin_create_publish_and_user_read_product() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await create_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        forbidden_merchant_response = await client.post(
            "/api/v1/admin/merchants",
            json={"name": f"测试店铺-{uuid4().hex[:8]}"},
            headers=headers,
        )
        assert forbidden_merchant_response.status_code == 403
        merchant_id = await create_test_merchant("Product Flow Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        category_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"测试分类-{uuid4().hex[:8]}"},
            headers=headers,
        )
        assert category_response.status_code == 200
        category_id = category_response.json()["data"]["id"]

        forbidden_product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "category_id": category_id,
                "name": "平台不应创建商品",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "默认规格", "price_cent": 9900, "stock": 10}],
            },
            headers=headers,
        )
        assert forbidden_product_response.status_code == 403

        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "category_id": category_id,
                "name": "测试商品",
                "description": "商品详情",
                "image_urls": ["/static/uploads/demo.jpg"],
                "skus": [{"name": "默认规格", "price_cent": 9900, "stock": 10}],
            },
            headers=merchant_headers,
        )
        assert product_response.status_code == 200
        product_id = product_response.json()["data"]["id"]

        publish_response = await client.post(f"/api/v1/admin/products/{product_id}/publish", headers=merchant_headers)
        assert publish_response.status_code == 200

        list_response = await client.get("/api/v1/products")
        assert list_response.status_code == 200
        assert list_response.json()["data"]["total"] >= 1

        detail_response = await client.get(f"/api/v1/products/{product_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["data"]["id"] == product_id


@pytest.mark.asyncio
async def test_merchant_admin_product_scope_and_edit_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        merchant_id = await create_test_merchant("Scope Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "name": "Scoped Product",
                "description": "Before update",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        product_id = product_response.json()["data"]["id"]
        sku_id = product_response.json()["data"]["skus"][0]["id"]

        forbidden_merchant_response = await client.post(
            "/api/v1/admin/merchants",
            json={"name": f"Forbidden Merchant-{uuid4().hex[:8]}"},
            headers=merchant_headers,
        )
        assert forbidden_merchant_response.status_code == 403

        product_list_response = await client.get("/api/v1/admin/products", headers=merchant_headers)
        assert product_list_response.status_code == 200
        assert any(item["id"] == product_id for item in product_list_response.json()["data"]["list"])

        update_response = await client.put(
            f"/api/v1/admin/products/{product_id}",
            json={"name": "Updated Scoped Product", "description": "After update"},
            headers=merchant_headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["data"]["name"] == "Updated Scoped Product"

        sku_update_response = await client.patch(
            f"/api/v1/admin/products/{product_id}/skus/{sku_id}",
            json={"price_cent": 1200, "stock": 8},
            headers=merchant_headers,
        )
        assert sku_update_response.status_code == 200
        sku = sku_update_response.json()["data"]["skus"][0]
        assert sku["price_cent"] == 1200
        assert sku["stock"] == 8

        stock_logs_response = await client.get(
            f"/api/v1/admin/products/{product_id}/skus/{sku_id}/stock-logs",
            headers=merchant_headers,
        )
        assert stock_logs_response.status_code == 200
        stock_logs = stock_logs_response.json()["data"]["list"]
        assert stock_logs[0]["before_stock"] == 3
        assert stock_logs[0]["after_stock"] == 8
        assert stock_logs[0]["change_quantity"] == 5
        assert stock_logs[0]["change_type"] == "manual_adjust"

        publish_response = await client.post(
            f"/api/v1/admin/products/{product_id}/publish",
            headers=merchant_headers,
        )
        assert publish_response.status_code == 200
        assert publish_response.json()["data"]["status"] == "on_sale"

        other_merchant_token = await create_merchant_admin_token(client, merchant_id + 999999)
        other_merchant_headers = {"Authorization": f"Bearer {other_merchant_token}"}

        forbidden_detail_response = await client.get(
            f"/api/v1/admin/products/{product_id}",
            headers=other_merchant_headers,
        )
        assert forbidden_detail_response.status_code == 403

        forbidden_create_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "name": "Wrong Scope Product",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 1}],
            },
            headers=other_merchant_headers,
        )
        assert forbidden_create_response.status_code == 403


@pytest.mark.asyncio
async def test_product_submit_audit_and_platform_audit_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        merchant_id = await create_test_merchant("Audit Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "name": "Audit Product",
                "description": "Need audit",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        assert product_response.status_code == 200
        product_id = product_response.json()["data"]["id"]
        assert product_response.json()["data"]["status"] == "on_sale"

        submit_response = await client.post(
            f"/api/v1/admin/products/{product_id}/submit-audit",
            headers=merchant_headers,
        )
        assert submit_response.status_code == 200
        assert submit_response.json()["data"]["status"] == "on_sale"

        public_detail_before = await client.get(f"/api/v1/products/{product_id}")
        assert public_detail_before.status_code == 200

        merchant_audit_response = await client.post(
            f"/api/v1/admin/products/{product_id}/audit",
            json={"approved": True},
            headers=merchant_headers,
        )
        assert merchant_audit_response.status_code == 403

        platform_audit_response = await client.post(
            f"/api/v1/admin/products/{product_id}/audit",
            json={"approved": True},
            headers=platform_headers,
        )
        assert platform_audit_response.status_code == 200
        assert platform_audit_response.json()["data"]["status"] == "on_sale"

        public_detail_after = await client.get(f"/api/v1/products/{product_id}")
        assert public_detail_after.status_code == 200


@pytest.mark.asyncio
async def test_batch_publish_and_merchant_scope() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        first_merchant_id = await create_test_merchant("Batch Merchant A")
        second_merchant_id = await create_test_merchant("Batch Merchant B")
        first_merchant_token = await create_merchant_admin_token(client, first_merchant_id)
        second_merchant_token = await create_merchant_admin_token(client, second_merchant_id)
        first_merchant_headers = {"Authorization": f"Bearer {first_merchant_token}"}
        second_merchant_headers = {"Authorization": f"Bearer {second_merchant_token}"}

        first_product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": first_merchant_id,
                "name": "Batch Product A",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=first_merchant_headers,
        )
        second_product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": second_merchant_id,
                "name": "Batch Product B",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=second_merchant_headers,
        )
        first_product_id = first_product_response.json()["data"]["id"]
        second_product_id = second_product_response.json()["data"]["id"]

        batch_publish_response = await client.post(
            "/api/v1/admin/products/batch-publish",
            json={"product_ids": [first_product_id, second_product_id, first_product_id]},
            headers=platform_headers,
        )
        assert batch_publish_response.status_code == 200
        batch_products = batch_publish_response.json()["data"]
        assert len(batch_products) == 2
        assert {product["status"] for product in batch_products} == {"on_sale"}

        forbidden_batch_response = await client.post(
            "/api/v1/admin/products/batch-unpublish",
            json={"product_ids": [first_product_id, second_product_id]},
            headers=first_merchant_headers,
        )
        assert forbidden_batch_response.status_code == 403
