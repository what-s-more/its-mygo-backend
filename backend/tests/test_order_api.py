from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.order import Order, Payment
from app.models.product import Merchant, Sku, SkuStockLog
from app.models.promotion import FullDiscountActivity
from app.models.user import AdminUser, User
from app.services.points_service import points_service
from app.services.order_service import order_service


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
        result = await session.execute(select(FullDiscountActivity).where(FullDiscountActivity.status == "active"))
        for activity in result.scalars():
            activity.status = "disabled"
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


async def create_merchant_admin_token(client: AsyncClient, merchant_id: int) -> str:
    username = f"merchant_order_admin_{uuid4().hex[:8]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="Merchant Order Admin",
                role="merchant_operator",
                merchant_id=merchant_id,
                password_hash=hash_password(password),
            )
        )
        await session.commit()
    response = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


async def create_test_merchant(name_prefix: str = "Order Merchant") -> int:
    async with AsyncSessionLocal() as session:
        merchant = Merchant(name=f"{name_prefix}-{uuid4().hex[:8]}")
        session.add(merchant)
        await session.commit()
        await session.refresh(merchant)
        return merchant.id


async def create_on_sale_sku(client: AsyncClient, admin_headers: dict[str, str]) -> int:
    merchant_id = await create_test_merchant("订单测试店铺")
    merchant_token = await create_merchant_admin_token(client, merchant_id)
    merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
    product_response = await client.post(
        "/api/v1/admin/products",
        json={
            "merchant_id": merchant_id,
            "name": "订单测试商品",
            "description": "订单测试商品描述",
            "image_urls": [],
            "skus": [{"name": "默认规格", "price_cent": 1999, "stock": 5}],
        },
        headers=merchant_headers,
    )
    product_id = product_response.json()["data"]["id"]
    await client.post(f"/api/v1/admin/products/{product_id}/publish", headers=merchant_headers)
    detail_response = await client.get(f"/api/v1/admin/products/{product_id}", headers=merchant_headers)
    return detail_response.json()["data"]["skus"][0]["id"]

async def create_on_sale_sku_with_merchant(client: AsyncClient, admin_headers: dict[str, str], price_cent: int) -> tuple[int, int]:
    merchant_id = await create_test_merchant("Scope Shop")
    merchant_token = await create_merchant_admin_token(client, merchant_id)
    merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
    product_response = await client.post(
        "/api/v1/admin/products",
        json={
            "merchant_id": merchant_id,
            "name": f"Scope Product-{uuid4().hex[:8]}",
            "description": "scope test",
            "image_urls": [],
            "skus": [{"name": "default", "price_cent": price_cent, "stock": 5}],
        },
        headers=merchant_headers,
    )
    product_id = product_response.json()["data"]["id"]
    await client.post(f"/api/v1/admin/products/{product_id}/publish", headers=merchant_headers)
    detail_response = await client.get(f"/api/v1/admin/products/{product_id}", headers=merchant_headers)
    return detail_response.json()["data"]["skus"][0]["id"], merchant_id

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
        address_response = await client.post(
            "/api/v1/addresses",
            json={
                "receiver_name": "Order User",
                "receiver_mobile": "13800000000",
                "province": "Guangdong",
                "city": "Shenzhen",
                "district": "Nanshan",
                "detail_address": "Test Road 1",
                "is_default": True,
            },
            headers=user_headers,
        )
        assert address_response.status_code == 200
        address_id = address_response.json()["data"]["id"]

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
            json={"client_order_token": uuid4().hex, "shipping_address_id": address_id},
            headers=user_headers,
        )
        assert order_response.status_code == 200
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]

        pay_response = await client.post(f"/api/v1/payments/{payment_id}/pay", headers=user_headers)
        assert pay_response.status_code == 200
        assert pay_response.json()["data"]["status"] == "paid"
        assert pay_response.json()["data"]["channel"] == "mock"
        assert pay_response.json()["data"]["order_ids"] == [order_id]

        detail_response = await client.get(f"/api/v1/orders/{order_id}", headers=user_headers)
        assert detail_response.status_code == 200
        assert detail_response.json()["data"]["status"] == "pending_shipment"
        assert detail_response.json()["data"]["shipping_address"]["receiver_name"] == "Order User"

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SkuStockLog).where(
                    SkuStockLog.sku_id == sku_id,
                    SkuStockLog.change_type == "order_lock",
                )
            )
            stock_log = result.scalars().first()
            assert stock_log is not None
            assert stock_log.change_quantity == -2


@pytest.mark.asyncio
async def test_cart_batch_update_and_delete_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        first_sku_id = await create_on_sale_sku(client, admin_headers)
        second_sku_id = await create_on_sale_sku(client, admin_headers)

        await client.post("/api/v1/cart", json={"sku_id": first_sku_id, "quantity": 1}, headers=user_headers)
        await client.post("/api/v1/cart", json={"sku_id": second_sku_id, "quantity": 2}, headers=user_headers)

        unchecked_response = await client.patch(
            "/api/v1/cart/batch",
            json={"sku_ids": [first_sku_id], "checked": False},
            headers=user_headers,
        )
        assert unchecked_response.status_code == 200
        unchecked_items = {item["sku_id"]: item for item in unchecked_response.json()["data"]}
        assert unchecked_items[first_sku_id]["checked"] is False
        assert unchecked_items[second_sku_id]["checked"] is True

        checkout_response = await client.post("/api/v1/cart/checkout", json={}, headers=user_headers)
        assert checkout_response.status_code == 200
        assert checkout_response.json()["data"]["total_amount_cent"] == 3998

        checked_response = await client.patch(
            "/api/v1/cart/batch",
            json={"sku_ids": [first_sku_id, second_sku_id], "checked": True},
            headers=user_headers,
        )
        assert checked_response.status_code == 200
        assert all(item["checked"] for item in checked_response.json()["data"])

        delete_one_response = await client.request(
            "DELETE",
            "/api/v1/cart",
            json={"sku_ids": [first_sku_id]},
            headers=user_headers,
        )
        assert delete_one_response.status_code == 200
        assert {item["sku_id"] for item in delete_one_response.json()["data"]} == {second_sku_id}

        clear_response = await client.request("DELETE", "/api/v1/cart", json={}, headers=user_headers)
        assert clear_response.status_code == 200
        assert clear_response.json()["data"] == []


@pytest.mark.asyncio
async def test_cross_merchant_order_group_cancel_restores_all_stock() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        first_sku_id, first_merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 1999)
        second_sku_id, second_merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 2999)

        await client.post("/api/v1/cart", json={"sku_id": first_sku_id, "quantity": 1}, headers=user_headers)
        await client.post("/api/v1/cart", json={"sku_id": second_sku_id, "quantity": 1}, headers=user_headers)
        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=user_headers,
        )
        assert order_response.status_code == 200
        order_data = order_response.json()["data"]
        assert order_data["pay_amount_cent"] == 4998
        assert len(order_data["order_ids"]) == 2
        first_order_id, second_order_id = order_data["order_ids"]
        payment_id = order_data["payment_id"]

        first_order_response = await client.get(f"/api/v1/orders/{first_order_id}", headers=user_headers)
        second_order_response = await client.get(f"/api/v1/orders/{second_order_id}", headers=user_headers)
        assert {first_order_response.json()["data"]["merchant_id"], second_order_response.json()["data"]["merchant_id"]} == {
            first_merchant_id,
            second_merchant_id,
        }
        assert first_order_response.json()["data"]["payment_id"] == payment_id
        assert second_order_response.json()["data"]["payment_id"] == payment_id

        first_merchant_token = await create_merchant_admin_token(client, first_merchant_id)
        first_merchant_orders = await client.get(
            "/api/v1/admin/orders",
            headers={"Authorization": f"Bearer {first_merchant_token}"},
        )
        assert first_merchant_orders.status_code == 200
        first_merchant_order_ids = {order["id"] for order in first_merchant_orders.json()["data"]["list"]}
        assert first_order_id in first_merchant_order_ids
        assert second_order_id not in first_merchant_order_ids

        cancel_response = await client.post(f"/api/v1/orders/{first_order_id}/cancel", headers=user_headers)
        assert cancel_response.status_code == 200
        assert cancel_response.json()["data"]["status"] == "cancelled"

        first_cancelled = await client.get(f"/api/v1/orders/{first_order_id}", headers=user_headers)
        second_cancelled = await client.get(f"/api/v1/orders/{second_order_id}", headers=user_headers)
        payment_response = await client.get(f"/api/v1/payments/{payment_id}", headers=user_headers)
        assert first_cancelled.json()["data"]["status"] == "cancelled"
        assert second_cancelled.json()["data"]["status"] == "cancelled"
        assert payment_response.json()["data"]["status"] == "closed"

        async with AsyncSessionLocal() as session:
            first_sku = await session.get(Sku, first_sku_id)
            second_sku = await session.get(Sku, second_sku_id)
            assert first_sku is not None
            assert second_sku is not None
            assert first_sku.stock == 5
            assert second_sku.stock == 5


@pytest.mark.asyncio
async def test_alipay_precreate_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "alipay_enabled", False)
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

        alipay_response = await client.post(f"/api/v1/payments/{payment_id}/alipay/precreate", headers=user_headers)
        assert alipay_response.status_code == 400
        assert alipay_response.json()["code"] == 40005


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

        ship_response = await client.post(
            f"/api/v1/admin/orders/{order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "SF123456789"},
            headers=admin_headers,
        )
        assert ship_response.status_code == 200
        assert ship_response.json()["data"]["status"] == "shipping"
        assert ship_response.json()["data"]["logistics_company"] == "SF Express"
        assert ship_response.json()["data"]["tracking_no"] == "SF123456789"

        confirm_response = await client.post(f"/api/v1/orders/{order_id}/confirm", headers=user_headers)
        assert confirm_response.status_code == 200
        assert confirm_response.json()["data"]["status"] == "completed"
        assert confirm_response.json()["data"]["received_at"] is not None

        product_id = confirm_response.json()["data"]["items"][0]["product_id"]
        order_item_id = confirm_response.json()["data"]["items"][0]["id"]
        review_response = await client.post(
            f"/api/v1/orders/{order_id}/reviews",
            json={
                "product_id": product_id,
                "score": 5,
                "content": "很好",
                "image_urls": ["/static/uploads/review-1.jpg"],
            },
            headers=user_headers,
        )
        assert review_response.status_code == 200
        review_id = review_response.json()["data"]["id"]
        assert review_response.json()["data"]["status"] == "published"
        assert review_response.json()["data"]["image_urls"] == ["/static/uploads/review-1.jpg"]

        public_reviews_before = await client.get(f"/api/v1/products/{product_id}/reviews")
        assert public_reviews_before.json()["data"]["total"] >= 1
        first_review = public_reviews_before.json()["data"]["list"][0]
        assert first_review["image_urls"] == ["/static/uploads/review-1.jpg"]
        assert first_review["user_nickname"]
        image_reviews_response = await client.get(
            f"/api/v1/products/{product_id}/reviews",
            params={"has_image": True, "score": 5},
        )
        assert image_reviews_response.status_code == 200
        assert image_reviews_response.json()["data"]["total"] >= 1
        no_match_reviews_response = await client.get(
            f"/api/v1/products/{product_id}/reviews",
            params={"has_image": True, "score": 1},
        )
        assert no_match_reviews_response.status_code == 200
        assert no_match_reviews_response.json()["data"]["total"] == 0
        product_detail_with_review = await client.get(f"/api/v1/products/{product_id}")
        assert product_detail_with_review.status_code == 200
        review_summary = product_detail_with_review.json()["data"]["review_summary"]
        assert review_summary["count"] >= 1
        assert review_summary["average_score"] == 5.0

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
            json={
                "order_item_id": order_item_id,
                "quantity": 1,
                "reason": "不想要了",
                "image_urls": ["/static/uploads/refund-1.jpg"],
            },
            headers=user_headers,
        )
        assert refund_response.status_code == 200
        refund_data = refund_response.json()["data"]
        refund_id = refund_data["id"]
        assert refund_data["reason_type"] == "other"
        assert refund_data["order_item_id"] == order_item_id
        assert refund_data["quantity"] == 1
        assert refund_data["image_urls"] == ["/static/uploads/refund-1.jpg"]
        assert refund_data["logs"][0]["action"] == "create"
        assert refund_data["created_at"] is not None
        assert refund_data["updated_at"] is not None
        assert refund_data["refund_amount_cent"] == confirm_response.json()["data"]["pay_amount_cent"]

        my_refunds_response = await client.get("/api/v1/orders/refunds", headers=user_headers)
        assert my_refunds_response.status_code == 200
        my_refunds_data = my_refunds_response.json()["data"]
        assert my_refunds_data["total"] >= 1
        assert any(item["id"] == refund_id for item in my_refunds_data["list"])

        refund_detail_response = await client.get(f"/api/v1/orders/refunds/{refund_id}", headers=user_headers)
        assert refund_detail_response.status_code == 200
        assert refund_detail_response.json()["data"]["status"] == "pending_approval"
        assert refund_detail_response.json()["data"]["created_at"] is not None
        assert refund_detail_response.json()["data"]["updated_at"] is not None

        approve_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/approve", headers=admin_headers)
        assert approve_response.status_code == 200
        assert approve_response.json()["data"]["status"] == "approved"
        assert any(log["action"] == "approve" for log in approve_response.json()["data"]["logs"])

        receive_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/receive", headers=admin_headers)
        assert receive_response.status_code == 200
        assert receive_response.json()["data"]["status"] == "received"

        finish_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/refund", headers=admin_headers)
        assert finish_response.status_code == 200
        assert finish_response.json()["data"]["status"] == "refunded"

        payment_response = await client.get(f"/api/v1/payments/{payment_id}", headers=user_headers)
        assert payment_response.status_code == 200
        assert payment_response.json()["data"]["status"] == "refunded"

        async with AsyncSessionLocal() as session:
            sku = await session.get(Sku, sku_id)
            assert sku is not None
            assert sku.stock == 5
            result = await session.execute(
                select(SkuStockLog).where(
                    SkuStockLog.sku_id == sku_id,
                    SkuStockLog.change_type == "refund_restore",
                )
            )
            restore_log = result.scalars().first()
            assert restore_log is not None
            assert restore_log.change_quantity == 1


@pytest.mark.asyncio
async def test_refund_one_quantity_from_multi_quantity_order_item() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 2}, headers=user_headers)
        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=user_headers,
        )
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]
        await client.post(f"/api/v1/payments/{payment_id}/pay", headers=user_headers)
        await client.post(
            f"/api/v1/admin/orders/{order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "REFUND-ONE"},
            headers=admin_headers,
        )
        confirm_response = await client.post(f"/api/v1/orders/{order_id}/confirm", headers=user_headers)
        item = confirm_response.json()["data"]["items"][0]

        refund_response = await client.post(
            f"/api/v1/orders/{order_id}/refunds",
            json={"order_item_id": item["id"], "quantity": 1, "reason": "只退其中一件"},
            headers=user_headers,
        )
        assert refund_response.status_code == 200
        refund_data = refund_response.json()["data"]
        assert refund_data["quantity"] == 1
        assert refund_data["refund_amount_cent"] == item["unit_price_cent"]

        refund_id = refund_data["id"]
        await client.post(f"/api/v1/admin/refunds/{refund_id}/approve", headers=admin_headers)
        await client.post(f"/api/v1/admin/refunds/{refund_id}/receive", headers=admin_headers)
        finish_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/refund", headers=admin_headers)
        assert finish_response.status_code == 200

        order_detail = await client.get(f"/api/v1/orders/{order_id}", headers=user_headers)
        assert order_detail.json()["data"]["status"] == "completed"
        payment_response = await client.get(f"/api/v1/payments/{payment_id}", headers=user_headers)
        assert payment_response.json()["data"]["status"] == "partial_refunded"

        async with AsyncSessionLocal() as session:
            sku = await session.get(Sku, sku_id)
            assert sku is not None
            assert sku.stock == 4
            result = await session.execute(
                select(SkuStockLog).where(
                    SkuStockLog.sku_id == sku_id,
                    SkuStockLog.change_type == "refund_restore",
                )
            )
            restore_log = result.scalars().first()
            assert restore_log is not None
            assert restore_log.change_quantity == 1


@pytest.mark.asyncio
async def test_coupon_claim_checkout_and_order_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "测试满减券",
                "discount_type": "amount",
                "discount_value": 500,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        coupon_template_id = coupon_response.json()["data"]["id"]

        claim_response = await client.post(
            f"/api/v1/promotions/coupons/{coupon_template_id}/claim",
            headers=user_headers,
        )
        assert claim_response.status_code == 200
        user_coupon_id = claim_response.json()["data"]["id"]

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 1}, headers=user_headers)
        checkout_response = await client.post(
            "/api/v1/cart/checkout",
            json={"coupon_id": user_coupon_id},
            headers=user_headers,
        )
        assert checkout_response.status_code == 200
        checkout_data = checkout_response.json()["data"]
        assert checkout_data["total_amount_cent"] == 1999
        assert checkout_data["discount_amount_cent"] == 500
        assert checkout_data["pay_amount_cent"] == 1499

        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex, "coupon_id": user_coupon_id},
            headers=user_headers,
        )
        assert order_response.status_code == 200
        assert order_response.json()["data"]["pay_amount_cent"] == 1499

        my_coupon_response = await client.get("/api/v1/promotions/my-coupons", headers=user_headers)
        assert my_coupon_response.status_code == 200
        user_coupon = next(
            coupon for coupon in my_coupon_response.json()["data"] if coupon["id"] == user_coupon_id
        )
        assert user_coupon["status"] == "used"


@pytest.mark.asyncio
async def test_full_discount_and_points_deduction_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)
        update_config = await client.put(
            "/api/v1/admin/settings/member-points",
            json={
                "level_rules": [
                    {"level": "normal", "name": "普通会员", "threshold_cent": 0, "benefits": ["基础积分"]},
                ],
                "sign_in_base_points": 2,
                "sign_in_streak_increment": 1,
                "sign_in_max_points": 10,
                "points_to_yuan_rate": 100,
                "max_points_discount_percent": 10,
            },
            headers=admin_headers,
        )
        assert update_config.status_code == 200

        profile_response = await client.get("/api/v1/auth/me", headers=user_headers)
        user_id = profile_response.json()["data"]["id"]
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            assert user is not None
            await points_service.change_points(
                session,
                user,
                change_points=500,
                source_type="test_grant",
                source_id=user_id,
                description="测试发放积分",
            )
            await session.commit()

        full_discount_response = await client.post(
            "/api/v1/admin/promotions/full-discounts",
            json={
                "name": "满 30 减 3",
                "scope_type": "all",
                "scope_ids": [],
                "min_amount_cent": 3000,
                "discount_amount_cent": 300,
            },
            headers=admin_headers,
        )
        assert full_discount_response.status_code == 200
        full_discount_id = full_discount_response.json()["data"]["id"]

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "满 10 减 2",
                "discount_type": "amount",
                "discount_value": 200,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        claim_response = await client.post(
            f"/api/v1/promotions/coupons/{coupon_response.json()['data']['id']}/claim",
            headers=user_headers,
        )
        user_coupon_id = claim_response.json()["data"]["id"]

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 2}, headers=user_headers)
        checkout_response = await client.post(
            "/api/v1/cart/checkout",
            json={"coupon_id": user_coupon_id, "points_used": 34},
            headers=user_headers,
        )
        assert checkout_response.status_code == 200
        checkout_data = checkout_response.json()["data"]
        assert checkout_data["total_amount_cent"] == 3998
        assert checkout_data["full_discount_amount_cent"] == 300
        assert checkout_data["coupon_discount_amount_cent"] == 200
        assert checkout_data["points_used"] == 34
        assert checkout_data["points_discount_amount_cent"] == 34
        assert checkout_data["discount_amount_cent"] == 534
        assert checkout_data["pay_amount_cent"] == 3464
        assert checkout_data["max_points_usable"] == 349

        too_many_points_response = await client.post(
            "/api/v1/cart/checkout",
            json={"coupon_id": user_coupon_id, "points_used": 350},
            headers=user_headers,
        )
        assert too_many_points_response.status_code == 400

        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex, "coupon_id": user_coupon_id, "points_used": 34},
            headers=user_headers,
        )
        assert order_response.status_code == 200
        order_data = order_response.json()["data"]
        assert order_data["pay_amount_cent"] == 3464
        payment_id = order_data["payment_id"]
        order_id = order_data["order_ids"][0]

        payment_response = await client.get(f"/api/v1/payments/{payment_id}", headers=user_headers)
        assert payment_response.json()["data"]["points_used"] == 34

        points_after_order = await client.get("/api/v1/users/points", headers=user_headers)
        assert points_after_order.json()["data"]["points"] == 466

        cancel_response = await client.post(f"/api/v1/orders/{order_id}/cancel", headers=user_headers)
        assert cancel_response.status_code == 200
        points_after_cancel = await client.get("/api/v1/users/points", headers=user_headers)
        assert points_after_cancel.json()["data"]["points"] == 500

        disable_full_discount = await client.post(
            f"/api/v1/admin/promotions/full-discounts/{full_discount_id}/disable",
            headers=admin_headers,
        )
        assert disable_full_discount.status_code == 200


@pytest.mark.asyncio
async def test_checkout_returns_selectable_promotions_and_repeat_full_discount() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id, merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 1999)

        full_discount_response = await client.post(
            "/api/v1/admin/promotions/full-discounts",
            json={
                "name": "Every 30 minus 3",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "min_amount_cent": 3000,
                "discount_amount_cent": 300,
            },
            headers=admin_headers,
        )
        assert full_discount_response.status_code == 200
        full_discount_id = full_discount_response.json()["data"]["id"]

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "After full discount coupon",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "discount_type": "amount",
                "discount_value": 500,
                "min_amount_cent": 9000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        claim_response = await client.post(
            f"/api/v1/promotions/coupons/{coupon_response.json()['data']['id']}/claim",
            headers=user_headers,
        )
        assert claim_response.status_code == 200
        user_coupon_id = claim_response.json()["data"]["id"]

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 5}, headers=user_headers)
        checkout_response = await client.post(
            "/api/v1/cart/checkout",
            json={"full_discount_id": full_discount_id, "coupon_id": user_coupon_id},
            headers=user_headers,
        )
        assert checkout_response.status_code == 200
        data = checkout_response.json()["data"]
        assert data["total_amount_cent"] == 9995
        assert data["full_discount_amount_cent"] == 900
        assert data["coupon_discount_amount_cent"] == 500
        assert data["pay_amount_cent"] == 8595
        assert data["selected_full_discount_id"] == full_discount_id
        assert data["selected_coupon_id"] == user_coupon_id
        full_option = next(option for option in data["available_full_discounts"] if option["id"] == full_discount_id)
        assert full_option["available"] is True
        assert full_option["discount_amount_cent"] == 900
        coupon_option = next(option for option in data["available_coupons"] if option["id"] == user_coupon_id)
        assert coupon_option["available"] is True
        assert coupon_option["applicable_amount_cent"] == 9095


@pytest.mark.asyncio
async def test_merchant_coupon_uses_only_scoped_items() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        scoped_sku_id, scoped_merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 1999)
        other_sku_id, _ = await create_on_sale_sku_with_merchant(client, admin_headers, 9999)

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Scoped merchant coupon",
                "scope_type": "merchant",
                "scope_ids": [scoped_merchant_id],
                "discount_type": "amount",
                "discount_value": 5000,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        coupon_data = coupon_response.json()["data"]
        assert coupon_data["scope_type"] == "merchant"
        assert coupon_data["scope_ids"] == [scoped_merchant_id]

        claim_response = await client.post(
            f"/api/v1/promotions/coupons/{coupon_data['id']}/claim",
            headers=user_headers,
        )
        assert claim_response.status_code == 200
        user_coupon_id = claim_response.json()["data"]["id"]

        await client.post("/api/v1/cart", json={"sku_id": scoped_sku_id, "quantity": 1}, headers=user_headers)
        await client.post("/api/v1/cart", json={"sku_id": other_sku_id, "quantity": 1}, headers=user_headers)

        checkout_response = await client.post(
            "/api/v1/cart/checkout",
            json={"coupon_id": user_coupon_id},
            headers=user_headers,
        )
        assert checkout_response.status_code == 200
        checkout_data = checkout_response.json()["data"]
        assert checkout_data["total_amount_cent"] == 11998
        assert checkout_data["discount_amount_cent"] == 1999
        assert checkout_data["pay_amount_cent"] == 9999


@pytest.mark.asyncio
async def test_coupon_list_can_filter_by_merchant_scope() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        first_merchant_id = await create_test_merchant("Coupon Visible Shop")
        second_merchant_id = await create_test_merchant("Coupon Hidden Shop")

        platform_coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Platform visible coupon",
                "scope_type": "all",
                "scope_ids": [],
                "discount_type": "amount",
                "discount_value": 300,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        first_coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "First merchant coupon",
                "scope_type": "merchant",
                "scope_ids": [first_merchant_id],
                "discount_type": "amount",
                "discount_value": 500,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        second_coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Second merchant coupon",
                "scope_type": "merchant",
                "scope_ids": [second_merchant_id],
                "discount_type": "amount",
                "discount_value": 700,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert platform_coupon_response.status_code == 200
        assert first_coupon_response.status_code == 200
        assert second_coupon_response.status_code == 200

        list_response = await client.get("/api/v1/promotions/coupons", params={"merchant_id": first_merchant_id})
        assert list_response.status_code == 200
        coupon_ids = {coupon["id"] for coupon in list_response.json()["data"]}
        assert platform_coupon_response.json()["data"]["id"] in coupon_ids
        assert first_coupon_response.json()["data"]["id"] in coupon_ids
        assert second_coupon_response.json()["data"]["id"] not in coupon_ids


@pytest.mark.asyncio
async def test_admin_can_update_and_disable_coupon_template() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Editable coupon",
                "discount_type": "amount",
                "discount_value": 300,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        coupon_id = coupon_response.json()["data"]["id"]

        update_response = await client.put(
            f"/api/v1/admin/promotions/coupons/{coupon_id}",
            json={"name": "Updated coupon", "discount_value": 600},
            headers=admin_headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["data"]["name"] == "Updated coupon"
        assert update_response.json()["data"]["discount_value"] == 600

        disable_response = await client.post(
            f"/api/v1/admin/promotions/coupons/{coupon_id}/disable",
            headers=admin_headers,
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["data"]["status"] == "disabled"

        claim_response = await client.post(f"/api/v1/promotions/coupons/{coupon_id}/claim", headers=user_headers)
        assert claim_response.status_code == 400


@pytest.mark.asyncio
async def test_disabled_coupon_template_cannot_be_used_for_checkout() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Disabled before use coupon",
                "discount_type": "amount",
                "discount_value": 500,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        coupon_id = coupon_response.json()["data"]["id"]

        claim_response = await client.post(f"/api/v1/promotions/coupons/{coupon_id}/claim", headers=user_headers)
        assert claim_response.status_code == 200
        user_coupon_id = claim_response.json()["data"]["id"]

        disable_response = await client.post(
            f"/api/v1/admin/promotions/coupons/{coupon_id}/disable",
            headers=admin_headers,
        )
        assert disable_response.status_code == 200

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 1}, headers=user_headers)
        checkout_response = await client.post(
            "/api/v1/cart/checkout",
            json={"coupon_id": user_coupon_id},
            headers=user_headers,
        )
        assert checkout_response.status_code == 400
        assert checkout_response.json()["code"] == 40008


@pytest.mark.asyncio
async def test_expire_user_coupons_marks_unused_expired() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Soon expired coupon",
                "discount_type": "amount",
                "discount_value": 300,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        coupon_id = coupon_response.json()["data"]["id"]

        claim_response = await client.post(f"/api/v1/promotions/coupons/{coupon_id}/claim", headers=user_headers)
        assert claim_response.status_code == 200

        update_response = await client.put(
            f"/api/v1/admin/promotions/coupons/{coupon_id}",
            json={"valid_to": "2020-01-01T00:00:00+00:00"},
            headers=admin_headers,
        )
        assert update_response.status_code == 200

        expire_response = await client.post("/api/v1/admin/promotions/coupons/expire", headers=admin_headers)
        assert expire_response.status_code == 200
        assert expire_response.json()["data"]["expired_count"] >= 1

        my_coupon_response = await client.get("/api/v1/promotions/my-coupons", headers=user_headers)
        assert my_coupon_response.status_code == 200
        user_coupon = next(
            coupon for coupon in my_coupon_response.json()["data"] if coupon["coupon_template_id"] == coupon_id
        )
        assert user_coupon["status"] == "expired"


@pytest.mark.asyncio
async def test_merchant_admin_cannot_manage_other_merchant_coupon_scope() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        _, merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 1999)
        _, other_merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 2999)
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Merchant coupon",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "discount_type": "amount",
                "discount_value": 300,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=merchant_headers,
        )
        assert coupon_response.status_code == 200
        coupon_id = coupon_response.json()["data"]["id"]

        update_response = await client.put(
            f"/api/v1/admin/promotions/coupons/{coupon_id}",
            json={"scope_ids": [other_merchant_id]},
            headers=merchant_headers,
        )
        assert update_response.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_can_batch_grant_coupon_to_users() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        first_user_token = await create_user_token(client)
        second_user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        first_user_headers = {"Authorization": f"Bearer {first_user_token}"}
        second_user_headers = {"Authorization": f"Bearer {second_user_token}"}

        first_user_response = await client.get("/api/v1/auth/me", headers=first_user_headers)
        second_user_response = await client.get("/api/v1/auth/me", headers=second_user_headers)
        first_user_id = first_user_response.json()["data"]["id"]
        second_user_id = second_user_response.json()["data"]["id"]

        coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Batch grant coupon",
                "discount_type": "amount",
                "discount_value": 500,
                "min_amount_cent": 1000,
                "total_quantity": 10,
                "per_user_limit": 1,
            },
            headers=admin_headers,
        )
        assert coupon_response.status_code == 200
        coupon_id = coupon_response.json()["data"]["id"]

        grant_response = await client.post(
            f"/api/v1/admin/promotions/coupons/{coupon_id}/batch-grant",
            json={"user_ids": [first_user_id, second_user_id, first_user_id]},
            headers=admin_headers,
        )
        assert grant_response.status_code == 200
        assert grant_response.json()["data"]["granted_count"] == 2
        assert grant_response.json()["data"]["skipped_user_ids"] == []

        first_coupons = await client.get("/api/v1/promotions/my-coupons", headers=first_user_headers)
        second_coupons = await client.get("/api/v1/promotions/my-coupons", headers=second_user_headers)
        assert any(coupon["coupon_template_id"] == coupon_id for coupon in first_coupons.json()["data"])
        assert any(coupon["coupon_template_id"] == coupon_id for coupon in second_coupons.json()["data"])


@pytest.mark.asyncio
async def test_cancel_expired_unpaid_orders_restores_stock() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 2}, headers=user_headers)
        order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=user_headers,
        )
        payment_id = order_response.json()["data"]["payment_id"]
        order_id = order_response.json()["data"]["order_ids"][0]

        async with AsyncSessionLocal() as session:
            payment = await session.get(Payment, payment_id)
            assert payment is not None
            payment.created_at = datetime.now(UTC) - timedelta(minutes=30)
            await session.commit()
            cancelled_count = await order_service.cancel_expired_unpaid_orders(
                session,
                now=datetime.now(UTC),
                expire_minutes=15,
            )
            assert cancelled_count >= 1

            order = await session.get(Order, order_id)
            sku = await session.get(Sku, sku_id)
            payment_after = await session.get(Payment, payment_id)
            assert order is not None
            assert sku is not None
            assert payment_after is not None
            assert order.status == "cancelled"
            assert payment_after.status == "closed"
            assert sku.stock == 5
            result = await session.execute(
                select(SkuStockLog).where(
                    SkuStockLog.sku_id == sku_id,
                    SkuStockLog.change_type == "order_cancel_restore",
                )
            )
            restore_log = result.scalars().first()
            assert restore_log is not None
            assert restore_log.change_quantity == 2


@pytest.mark.asyncio
async def test_auto_confirm_received_orders() -> None:
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
        await client.post(
            f"/api/v1/admin/orders/{order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "AUTO-CONFIRM"},
            headers=admin_headers,
        )

        async with AsyncSessionLocal() as session:
            order = await session.get(Order, order_id)
            assert order is not None
            order.shipped_at = datetime.now(UTC) - timedelta(days=8)
            await session.commit()
            confirmed_count = await order_service.auto_confirm_received_orders(
                session,
                now=datetime.now(UTC),
                auto_confirm_days=7,
            )
            assert confirmed_count >= 1

            confirmed_order = await session.get(Order, order_id)
            assert confirmed_order is not None
            assert confirmed_order.status == "completed"
            assert confirmed_order.received_at is not None


@pytest.mark.asyncio
async def test_merchant_admin_only_lists_and_disables_owned_promotions() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        merchant_id = await create_test_merchant("Owned Promotion Shop")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        platform_coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Platform created merchant coupon",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "discount_type": "amount",
                "discount_value": 100,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=admin_headers,
        )
        assert platform_coupon_response.status_code == 200
        platform_coupon_id = platform_coupon_response.json()["data"]["id"]

        merchant_coupon_response = await client.post(
            "/api/v1/admin/promotions/coupons",
            json={
                "name": "Merchant owned coupon",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "discount_type": "amount",
                "discount_value": 200,
                "min_amount_cent": 1000,
                "total_quantity": 10,
            },
            headers=merchant_headers,
        )
        assert merchant_coupon_response.status_code == 200
        merchant_coupon_id = merchant_coupon_response.json()["data"]["id"]

        list_response = await client.get("/api/v1/admin/promotions/coupons", headers=merchant_headers)
        assert list_response.status_code == 200
        coupon_ids = {coupon["id"] for coupon in list_response.json()["data"]}
        assert merchant_coupon_id in coupon_ids
        assert platform_coupon_id not in coupon_ids

        forbidden_disable = await client.post(
            f"/api/v1/admin/promotions/coupons/{platform_coupon_id}/disable",
            headers=merchant_headers,
        )
        assert forbidden_disable.status_code == 403

        owned_disable = await client.post(
            f"/api/v1/admin/promotions/coupons/{merchant_coupon_id}/disable",
            headers=merchant_headers,
        )
        assert owned_disable.status_code == 200
        assert owned_disable.json()["data"]["status"] == "disabled"

        platform_full_response = await client.post(
            "/api/v1/admin/promotions/full-discounts",
            json={
                "name": "Platform created merchant full discount",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "min_amount_cent": 1000,
                "discount_amount_cent": 100,
            },
            headers=admin_headers,
        )
        assert platform_full_response.status_code == 200
        merchant_full_response = await client.post(
            "/api/v1/admin/promotions/full-discounts",
            json={
                "name": "Merchant owned full discount",
                "scope_type": "merchant",
                "scope_ids": [merchant_id],
                "min_amount_cent": 1000,
                "discount_amount_cent": 100,
            },
            headers=merchant_headers,
        )
        assert merchant_full_response.status_code == 200

        list_full_response = await client.get("/api/v1/admin/promotions/full-discounts", headers=merchant_headers)
        assert list_full_response.status_code == 200
        full_ids = {activity["id"] for activity in list_full_response.json()["data"]}
        assert merchant_full_response.json()["data"]["id"] in full_ids
        assert platform_full_response.json()["data"]["id"] not in full_ids

        forbidden_full_disable = await client.post(
            f"/api/v1/admin/promotions/full-discounts/{platform_full_response.json()['data']['id']}/disable",
            headers=merchant_headers,
        )
        assert forbidden_full_disable.status_code == 403
