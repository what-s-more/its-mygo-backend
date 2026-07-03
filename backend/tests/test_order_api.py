from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.order import Order, Payment
from app.models.product import Merchant, Sku, SkuStockLog
from app.models.user import AdminUser
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
    merchant_id = await create_test_merchant("????")
    merchant_token = await create_merchant_admin_token(client, merchant_id)
    merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
    product_response = await client.post(
        "/api/v1/admin/products",
        json={
            "merchant_id": merchant_id,
            "name": "??????",
            "description": "??????",
            "image_urls": [],
            "skus": [{"name": "????", "price_cent": 1999, "stock": 5}],
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
        review_response = await client.post(
            f"/api/v1/orders/{order_id}/reviews",
            json={"product_id": product_id, "score": 5, "content": "很好"},
            headers=user_headers,
        )
        assert review_response.status_code == 200
        review_id = review_response.json()["data"]["id"]
        assert review_response.json()["data"]["status"] == "published"

        public_reviews_before = await client.get(f"/api/v1/products/{product_id}/reviews")
        assert public_reviews_before.json()["data"]["total"] >= 1

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
        refund_data = refund_response.json()["data"]
        refund_id = refund_data["id"]
        assert refund_data["reason_type"] == "other"
        assert refund_data["refund_amount_cent"] == confirm_response.json()["data"]["pay_amount_cent"]

        approve_response = await client.post(f"/api/v1/admin/refunds/{refund_id}/approve", headers=admin_headers)
        assert approve_response.status_code == 200
        assert approve_response.json()["data"]["status"] == "approved"

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
