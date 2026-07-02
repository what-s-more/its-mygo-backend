from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
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


@pytest.mark.asyncio
async def test_admin_create_publish_and_user_read_product() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await create_admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        merchant_response = await client.post(
            "/api/v1/admin/merchants",
            json={"name": f"测试店铺-{uuid4().hex[:8]}"},
            headers=headers,
        )
        assert merchant_response.status_code == 200
        merchant_id = merchant_response.json()["data"]["id"]

        category_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"测试分类-{uuid4().hex[:8]}"},
            headers=headers,
        )
        assert category_response.status_code == 200
        category_id = category_response.json()["data"]["id"]

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
            headers=headers,
        )
        assert product_response.status_code == 200
        product_id = product_response.json()["data"]["id"]

        publish_response = await client.post(f"/api/v1/admin/products/{product_id}/publish", headers=headers)
        assert publish_response.status_code == 200

        list_response = await client.get("/api/v1/products")
        assert list_response.status_code == 200
        assert list_response.json()["data"]["total"] >= 1

        detail_response = await client.get(f"/api/v1/products/{product_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["data"]["id"] == product_id
