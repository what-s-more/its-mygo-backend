from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app
from backend.tests.test_admin_operations_api import create_merchant_admin_token
from backend.tests.test_order_api import create_admin_token, create_on_sale_sku, create_user_token


@pytest.mark.asyncio
async def test_customer_service_merchant_and_platform_scope() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        await create_on_sale_sku(client, platform_headers)

        product_response = await client.get("/api/v1/products")
        product = product_response.json()["data"]["list"][0]
        merchant_id = product["merchant_id"]
        product_id = product["id"]
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        merchant_conversation_response = await client.post(
            "/api/v1/customer-service/conversations",
            json={
                "target_type": "merchant",
                "merchant_id": merchant_id,
                "product_id": product_id,
                "initial_message": "请问这个商品什么时候发货？",
            },
            headers=user_headers,
        )
        assert merchant_conversation_response.status_code == 200
        merchant_conversation = merchant_conversation_response.json()["data"]
        assert merchant_conversation["target_type"] == "merchant"
        assert merchant_conversation["merchant_id"] == merchant_id
        assert merchant_conversation["last_message"] == "请问这个商品什么时候发货？"

        merchant_list_response = await client.get("/api/v1/admin/customer-service/conversations", headers=merchant_headers)
        assert merchant_list_response.status_code == 200
        assert any(item["id"] == merchant_conversation["id"] for item in merchant_list_response.json()["data"]["list"])

        platform_list_response = await client.get("/api/v1/admin/customer-service/conversations", headers=platform_headers)
        assert platform_list_response.status_code == 200
        assert all(item["target_type"] == "platform" for item in platform_list_response.json()["data"]["list"])
        assert all(item["id"] != merchant_conversation["id"] for item in platform_list_response.json()["data"]["list"])

        forbidden_platform_messages = await client.get(
            f"/api/v1/admin/customer-service/conversations/{merchant_conversation['id']}/messages",
            headers=platform_headers,
        )
        assert forbidden_platform_messages.status_code == 403

        reply_response = await client.post(
            f"/api/v1/admin/customer-service/conversations/{merchant_conversation['id']}/messages",
            json={"content": "本店会尽快处理。"},
            headers=merchant_headers,
        )
        assert reply_response.status_code == 200
        assert reply_response.json()["data"]["sender_type"] == "merchant"

        platform_conversation_response = await client.post(
            "/api/v1/customer-service/conversations",
            json={
                "target_type": "platform",
                "initial_message": f"平台问题 {uuid4().hex}",
            },
            headers=user_headers,
        )
        assert platform_conversation_response.status_code == 200
        platform_conversation = platform_conversation_response.json()["data"]
        assert platform_conversation["target_type"] == "platform"
        assert platform_conversation["merchant_id"] is None

        merchant_forbidden_platform = await client.get(
            f"/api/v1/admin/customer-service/conversations/{platform_conversation['id']}/messages",
            headers=merchant_headers,
        )
        assert merchant_forbidden_platform.status_code == 403

        platform_reply = await client.post(
            f"/api/v1/admin/customer-service/conversations/{platform_conversation['id']}/messages",
            json={"content": "平台客服已收到。"},
            headers=platform_headers,
        )
        assert platform_reply.status_code == 200
        assert platform_reply.json()["data"]["sender_type"] == "platform"
