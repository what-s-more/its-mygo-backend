from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app
from backend.tests.test_admin_operations_api import create_merchant_admin_token
from backend.tests.test_order_api import create_admin_token, create_on_sale_sku, create_user_token


@pytest.mark.asyncio
async def test_platform_and_merchant_report_overview_permissions() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, platform_headers)

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 2}, headers=user_headers)
        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=user_headers,
        )
        assert order_response.status_code == 200
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]
        await client.post(f"/api/v1/payments/{payment_id}/pay", headers=user_headers)

        order_detail_response = await client.get(f"/api/v1/admin/orders/{order_id}", headers=platform_headers)
        merchant_id = order_detail_response.json()["data"]["merchant_id"]
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        merchant_post_response = await client.post(
            "/api/v1/admin/community/posts",
            json={
                "type": "normal",
                "section": "square",
                "title": "本店报表动态",
                "content": "用于统计本店社区互动",
            },
            headers=merchant_headers,
        )
        assert merchant_post_response.status_code == 200
        merchant_post_id = merchant_post_response.json()["data"]["id"]
        assert merchant_post_response.json()["data"]["merchant_id"] == merchant_id
        comment_response = await client.post(
            f"/api/v1/community/posts/{merchant_post_id}/comments",
            json={"content": "本店动态评论"},
            headers=user_headers,
        )
        assert comment_response.status_code == 200
        like_response = await client.post(f"/api/v1/community/posts/{merchant_post_id}/like", headers=user_headers)
        assert like_response.status_code == 200

        platform_report_response = await client.get("/api/v1/admin/reports/platform/overview", headers=platform_headers)
        assert platform_report_response.status_code == 200
        platform_report = platform_report_response.json()["data"]
        assert platform_report["scope"] == "platform"
        assert platform_report["scope_id"] is None
        assert len(platform_report["sales_trend"]) == 7
        assert any(metric["key"] == "gmv_cent" and metric["value"] >= 3998 for metric in platform_report["summary"])
        assert any(product["quantity"] >= 2 for product in platform_report["top_products"])

        merchant_report_response = await client.get("/api/v1/admin/reports/merchant/overview", headers=merchant_headers)
        assert merchant_report_response.status_code == 200
        merchant_report = merchant_report_response.json()["data"]
        assert merchant_report["scope"] == "merchant"
        assert merchant_report["scope_id"] == merchant_id
        assert merchant_report["top_merchants"] == []
        assert any(metric["key"] == "gmv_cent" and metric["value"] >= 3998 for metric in merchant_report["summary"])
        assert any(metric["key"] == "post_count" and metric["value"] >= 1 for metric in merchant_report["community_summary"])
        assert any(metric["key"] == "comment_count" and metric["value"] >= 1 for metric in merchant_report["community_summary"])
        assert any(metric["key"] == "like_count" and metric["value"] >= 1 for metric in merchant_report["community_summary"])

        forbidden_platform_response = await client.get("/api/v1/admin/reports/platform/overview", headers=merchant_headers)
        assert forbidden_platform_response.status_code == 403

        forbidden_merchant_response = await client.get("/api/v1/admin/reports/merchant/overview", headers=platform_headers)
        assert forbidden_merchant_response.status_code == 403
