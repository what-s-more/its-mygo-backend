from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.user import AdminUser
from backend.tests.test_order_api import create_admin_token, create_on_sale_sku, create_user_token


async def create_merchant_admin_token(client: AsyncClient, merchant_id: int) -> str:
    username = f"merchant_admin_{uuid4().hex[:8]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="Merchant Admin",
                role="merchant_operator",
                merchant_id=merchant_id,
                password_hash=hash_password(password),
            )
        )
        await session.commit()
    response = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_admin_user_order_list_and_dashboard_summary() -> None:
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
        assert order_response.status_code == 200
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]
        await client.post(f"/api/v1/payments/{payment_id}/pay", headers=user_headers)

        users_response = await client.get("/api/v1/admin/users", headers=admin_headers)
        assert users_response.status_code == 200
        assert users_response.json()["data"]["total"] >= 1

        orders_response = await client.get("/api/v1/admin/orders", headers=admin_headers)
        assert orders_response.status_code == 200
        assert any(order["id"] == order_id for order in orders_response.json()["data"]["list"])

        order_detail_response = await client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert order_detail_response.status_code == 200
        order_detail = order_detail_response.json()["data"]
        assert order_detail["id"] == order_id
        assert len(order_detail["items"]) == 1
        merchant_id = order_detail["merchant_id"]

        export_response = await client.get("/api/v1/admin/orders/export", headers=admin_headers)
        assert export_response.status_code == 200
        assert "text/csv" in export_response.headers["content-type"]
        assert str(order_id) in export_response.text
        assert order_detail["order_no"] in export_response.text

        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
        merchant_export_response = await client.get("/api/v1/admin/orders/export", headers=merchant_headers)
        assert merchant_export_response.status_code == 200
        assert order_detail["order_no"] in merchant_export_response.text

        summary_response = await client.get("/api/v1/admin/dashboard/summary", headers=admin_headers)
        assert summary_response.status_code == 200
        summary = summary_response.json()["data"]
        assert summary["user_count"] >= 1
        assert summary["product_count"] >= 1
        assert summary["order_count"] >= 1
        assert summary["paid_order_count"] >= 1
        assert summary["gross_merchandise_cent"] >= 1999


@pytest.mark.asyncio
async def test_merchant_admin_cannot_operate_other_merchant_order() -> None:
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

        order_detail_response = await client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        merchant_id = order_detail_response.json()["data"]["merchant_id"]
        other_merchant_token = await create_merchant_admin_token(client, merchant_id + 999999)
        other_merchant_headers = {"Authorization": f"Bearer {other_merchant_token}"}

        forbidden_detail_response = await client.get(
            f"/api/v1/admin/orders/{order_id}",
            headers=other_merchant_headers,
        )
        assert forbidden_detail_response.status_code == 404

        forbidden_ship_response = await client.post(
            f"/api/v1/admin/orders/{order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "SF000000001"},
            headers=other_merchant_headers,
        )
        assert forbidden_ship_response.status_code == 404


@pytest.mark.asyncio
async def test_admin_operation_logs_for_order_ship() -> None:
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

        ship_response = await client.post(
            f"/api/v1/admin/orders/{order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "LOG-TEST"},
            headers=admin_headers,
        )
        assert ship_response.status_code == 200

        logs_response = await client.get(
            "/api/v1/admin/operation-logs",
            params={"action": "order.ship"},
            headers=admin_headers,
        )
        assert logs_response.status_code == 200
        logs = logs_response.json()["data"]["list"]
        assert any(log["resource_type"] == "order" and log["resource_id"] == order_id for log in logs)

        order_detail_response = await client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        merchant_id = order_detail_response.json()["data"]["merchant_id"]
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
        forbidden_logs_response = await client.get("/api/v1/admin/operation-logs", headers=merchant_headers)
        assert forbidden_logs_response.status_code == 403


@pytest.mark.asyncio
async def test_merchant_register_login_audit_then_gets_merchant_permission() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        username = f"merchant_apply_{uuid4().hex[:8]}"
        merchant_name = f"Apply Shop-{uuid4().hex[:8]}"

        register_response = await client.post(
            "/api/v1/admin/merchant/register",
            json={
                "username": username,
                "password": "12345678",
                "real_name": "Merchant Applicant",
                "merchant_name": merchant_name,
                "announcement": "申请入驻",
            },
        )
        assert register_response.status_code == 200
        application = register_response.json()["data"]
        assert application["status"] == "pending"
        application_id = application["id"]

        login_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": "12345678"},
        )
        assert login_response.status_code == 200
        pending_headers = {"Authorization": f"Bearer {login_response.json()['data']['access_token']}"}
        me_response = await client.get("/api/v1/admin/auth/me", headers=pending_headers)
        assert me_response.status_code == 200
        assert me_response.json()["data"]["role"] == "merchant_pending"
        assert me_response.json()["data"]["merchant_id"] is None

        forbidden_products_response = await client.get("/api/v1/admin/products", headers=pending_headers)
        assert forbidden_products_response.status_code == 403
        my_application_response = await client.get("/api/v1/admin/merchant/application/me", headers=pending_headers)
        assert my_application_response.status_code == 200
        assert my_application_response.json()["data"]["id"] == application_id

        pending_list_response = await client.get(
            "/api/v1/admin/merchant/applications",
            params={"status": "pending"},
            headers=platform_headers,
        )
        assert pending_list_response.status_code == 200
        assert any(item["id"] == application_id for item in pending_list_response.json()["data"]["list"])

        audit_response = await client.post(
            f"/api/v1/admin/merchant/applications/{application_id}/audit",
            json={"approved": True},
            headers=platform_headers,
        )
        assert audit_response.status_code == 200
        audited = audit_response.json()["data"]
        assert audited["status"] == "approved"
        assert audited["merchant_id"] is not None

        login_after_audit_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": "12345678"},
        )
        assert login_after_audit_response.status_code == 200
        merchant_headers = {"Authorization": f"Bearer {login_after_audit_response.json()['data']['access_token']}"}
        merchant_me_response = await client.get("/api/v1/admin/auth/me", headers=merchant_headers)
        assert merchant_me_response.json()["data"]["role"] == "merchant_operator"
        assert merchant_me_response.json()["data"]["merchant_id"] == audited["merchant_id"]
        merchant_admin_id = merchant_me_response.json()["data"]["id"]

        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": audited["merchant_id"],
                "name": "Merchant Product",
                "description": "After audit",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        assert product_response.status_code == 200

        disable_response = await client.patch(
            f"/api/v1/admin/accounts/{merchant_admin_id}/status",
            json={"is_active": False},
            headers=platform_headers,
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["data"]["is_active"] is False

        disabled_login_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": "12345678"},
        )
        assert disabled_login_response.status_code == 401

        enable_response = await client.patch(
            f"/api/v1/admin/accounts/{merchant_admin_id}/status",
            json={"is_active": True},
            headers=platform_headers,
        )
        assert enable_response.status_code == 200
        assert enable_response.json()["data"]["is_active"] is True

        reset_response = await client.post(
            f"/api/v1/admin/accounts/{merchant_admin_id}/reset-password",
            json={"password": "87654321"},
            headers=platform_headers,
        )
        assert reset_response.status_code == 200
        assert reset_response.json()["data"]["username"] == username

        old_password_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": "12345678"},
        )
        assert old_password_response.status_code == 401
        new_password_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": "87654321"},
        )
        assert new_password_response.status_code == 200

        platform_me_response = await client.get("/api/v1/admin/auth/me", headers=platform_headers)
        platform_admin_id = platform_me_response.json()["data"]["id"]
        self_disable_response = await client.patch(
            f"/api/v1/admin/accounts/{platform_admin_id}/status",
            json={"is_active": False},
            headers=platform_headers,
        )
        assert self_disable_response.status_code == 400


@pytest.mark.asyncio
async def test_rejected_merchant_application_can_be_resubmitted_without_limit() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        username = f"merchant_retry_{uuid4().hex[:8]}"
        before_name = f"Before Retry-{uuid4().hex[:8]}"
        after_name = f"After Retry-{uuid4().hex[:8]}"

        register_response = await client.post(
            "/api/v1/admin/merchant/register",
            json={
                "username": username,
                "password": "12345678",
                "real_name": "Retry Applicant",
                "merchant_name": before_name,
            },
        )
        assert register_response.status_code == 200
        application_id = register_response.json()["data"]["id"]
        login_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": "12345678"},
        )
        pending_headers = {"Authorization": f"Bearer {login_response.json()['data']['access_token']}"}

        reject_response = await client.post(
            f"/api/v1/admin/merchant/applications/{application_id}/audit",
            json={"approved": False, "reject_reason": "资料不完整"},
            headers=platform_headers,
        )
        assert reject_response.status_code == 200
        assert reject_response.json()["data"]["status"] == "rejected"

        retry_response = await client.put(
            "/api/v1/admin/merchant/application/me",
            json={"merchant_name": after_name, "announcement": "补充资料"},
            headers=pending_headers,
        )
        assert retry_response.status_code == 200
        retry_data = retry_response.json()["data"]
        assert retry_data["status"] == "pending"
        assert retry_data["merchant_name"] == after_name
        assert retry_data["reject_reason"] is None

        approve_response = await client.post(
            f"/api/v1/admin/merchant/applications/{application_id}/audit",
            json={"approved": True},
            headers=platform_headers,
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["data"]["status"] == "approved"

        update_after_approved_response = await client.put(
            "/api/v1/admin/merchant/application/me",
            json={"merchant_name": "Should Not Change"},
            headers=pending_headers,
        )
        assert update_after_approved_response.status_code == 400


@pytest.mark.asyncio
async def test_merchant_application_rejects_duplicate_merchant_name() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        merchant_name = f"Duplicate Shop-{uuid4().hex[:8]}"

        first_register_response = await client.post(
            "/api/v1/admin/merchant/register",
            json={
                "username": f"merchant_dup_a_{uuid4().hex[:8]}",
                "password": "12345678",
                "real_name": "First Applicant",
                "merchant_name": merchant_name,
            },
        )
        assert first_register_response.status_code == 200
        first_application_id = first_register_response.json()["data"]["id"]
        approve_response = await client.post(
            f"/api/v1/admin/merchant/applications/{first_application_id}/audit",
            json={"approved": True},
            headers=platform_headers,
        )
        assert approve_response.status_code == 200

        duplicate_register_response = await client.post(
            "/api/v1/admin/merchant/register",
            json={
                "username": f"merchant_dup_b_{uuid4().hex[:8]}",
                "password": "12345678",
                "real_name": "Second Applicant",
                "merchant_name": merchant_name,
            },
        )
        assert duplicate_register_response.status_code == 400
        assert duplicate_register_response.json()["code"] == 40005
