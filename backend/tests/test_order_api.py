from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.user import AdminUser


async def create_user_token(client: AsyncClient) -> str:
    mobile = f"137{str(uuid4().int)[-8:]}"
    password = "12345678"
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"mobile": mobile, "password": password, "nickname": "订单用户"},
    )
    assert register_response.status_code == 200
    login_response = await client.post("/api/v1/auth/login", json={"account": mobile, "password": password})
    assert login_response.status_code == 200
    return login_response.json()["data"]["access_token"]


async def create_admin_token(client: AsyncClient) -> str:
    username = f"order_admin_{str(uuid4().int)[-8:]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="订单管理员",
                role="platform_operator",
                password_hash=hash_password(password),
            )
        )
        await session.commit()
    response = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


async def create_on_sale_sku(client: AsyncClient, admin_headers: dict[str, str]) -> int:
    merchant_response = await client.post(
        "/api/v1/admin/merchants",
        json={"name": f"订单店铺-{uuid4().hex[:8]}"},
        headers=admin_headers,
    )
    merchant_id = merchant_response.json()["data"]["id"]
    product_response = await client.post(
        "/api/v1/admin/products",
        json={
            "merchant_id": merchant_id,
            "name": "订单测试商品",
            "description": "订单测试详情",
            "image_urls": [],
            "skus": [{"name": "默认规格", "price_cent": 1999, "stock": 5}],
        },
        headers=admin_headers,
    )
    product_id = product_response.json()["data"]["id"]
    await client.post(f"/api/v1/admin/products/{product_id}/publish", headers=admin_headers)
    detail_response = await client.get(f"/api/v1/admin/products/{product_id}", headers=admin_headers)
    return detail_response.json()["data"]["skus"][0]["id"]


@pytest.mark.asyncio
async def test_cart_checkout_order_and_pay_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        cart_response = await client.post(
            "/api/v1/cart",
            json={"sku_id": sku_id, "quantity": 2},
            headers=user_headers,
        )
        assert cart_response.status_code == 200
        assert cart_response.json()["data"][0]["quantity"] == 2

        checkout_response = await client.post("/api/v1/cart/checkout", json={}, headers=user_headers)
        assert checkout_response.status_code == 200
        assert checkout_response.json()["data"]["pay_amount_cent"] == 3998

        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=user_headers,
        )
        assert order_response.status_code == 200
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]

        pay_response = await client.post(f"/api/v1/payments/{payment_id}/pay", headers=user_headers)
        assert pay_response.status_code == 200
        assert pay_response.json()["data"]["status"] == "paid"

        detail_response = await client.get(f"/api/v1/orders/{order_id}", headers=user_headers)
        assert detail_response.status_code == 200
        assert detail_response.json()["data"]["status"] == "pending_shipment"


@pytest.mark.asyncio
async def test_receipt_review_and_refund_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 1}, headers=user_headers)
        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=user_headers,
        )
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]
        await client.post(f"/api/v1/payments/{payment_id}/pay", headers=user_headers)

        ship_response = await client.post(f"/api/v1/admin/orders/{order_id}/ship", headers=admin_headers)
        assert ship_response.status_code == 200
        assert ship_response.json()["data"]["status"] == "shipping"

        confirm_response = await client.post(f"/api/v1/orders/{order_id}/confirm", headers=user_headers)
        assert confirm_response.status_code == 200
        assert confirm_response.json()["data"]["status"] == "completed"

        product_id = confirm_response.json()["data"]["items"][0]["product_id"]
        review_response = await client.post(
            f"/api/v1/orders/{order_id}/reviews",
            json={"product_id": product_id, "score": 5, "content": "很好"},
            headers=user_headers,
        )
        assert review_response.status_code == 200
        review_id = review_response.json()["data"]["id"]

        public_reviews_before = await client.get(f"/api/v1/products/{product_id}/reviews")
        assert public_reviews_before.json()["data"]["total"] == 0

        audit_response = await client.post(
            f"/api/v1/admin/reviews/{review_id}/audit",
            json={"approved": True},
            headers=admin_headers,
        )
        assert audit_response.status_code == 200
        assert audit_response.json()["data"]["status"] == "published"

        public_reviews_after = await client.get(f"/api/v1/products/{product_id}/reviews")
        assert public_reviews_after.json()["data"]["total"] >= 1

        refund_response = await client.post(
            f"/api/v1/orders/{order_id}/refunds",
            json={"reason": "不想要了"},
            headers=user_headers,
        )
        assert refund_response.status_code == 200
        refund_id = refund_response.json()["data"]["id"]

        approve_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/approve", headers=admin_headers)
        assert approve_response.status_code == 200
        assert approve_response.json()["data"]["status"] == "approved"

        finish_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/refund", headers=admin_headers)
        assert finish_response.status_code == 200
        assert finish_response.json()["data"]["status"] == "refunded"
