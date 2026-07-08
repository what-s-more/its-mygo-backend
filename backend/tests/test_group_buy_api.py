from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.group_buy import GroupBuyGroup, GroupBuyParticipant
from app.models.order import Order
from backend.tests.test_order_api import (
    create_admin_token,
    create_merchant_admin_token,
    create_on_sale_sku_with_merchant,
    create_user_token,
)


@pytest.mark.asyncio
async def test_group_buy_start_join_and_success_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        first_user_token = await create_user_token(client)
        second_user_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        first_headers = {"Authorization": f"Bearer {first_user_token}"}
        second_headers = {"Authorization": f"Bearer {second_user_token}"}
        sku_id, merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 2000)
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        detail_response = await client.get("/api/v1/admin/products", headers=merchant_headers)
        product_id = detail_response.json()["data"]["list"][0]["id"]

        activity_response = await client.post(
            "/api/v1/admin/promotions/group-buy",
            json={
                "product_id": product_id,
                "sku_id": sku_id,
                "name": "2 person group buy",
                "group_size": 2,
                "group_price_cent": 1500,
            },
            headers=merchant_headers,
        )
        assert activity_response.status_code == 200
        activity_id = activity_response.json()["data"]["id"]

        public_response = await client.get("/api/v1/group-buy/activities")
        assert public_response.status_code == 200
        assert any(activity["id"] == activity_id for activity in public_response.json()["data"])

        start_response = await client.post(
            "/api/v1/group-buy/groups/start",
            json={"activity_id": activity_id, "quantity": 2, "client_order_token": uuid4().hex},
            headers=first_headers,
        )
        assert start_response.status_code == 200
        assert start_response.json()["data"]["order"]["pay_amount_cent"] == 3000
        group_id = start_response.json()["data"]["group"]["id"]
        first_payment_id = start_response.json()["data"]["order"]["payment_id"]
        first_order_id = start_response.json()["data"]["order"]["order_ids"][0]
        first_pay_response = await client.post(f"/api/v1/payments/{first_payment_id}/pay", headers=first_headers)
        assert first_pay_response.status_code == 200

        first_order_response = await client.get(f"/api/v1/orders/{first_order_id}", headers=first_headers)
        assert first_order_response.json()["data"]["status"] == "group_pending"
        merchant_orders_before = await client.get("/api/v1/admin/orders", headers=merchant_headers)
        assert first_order_id not in {order["id"] for order in merchant_orders_before.json()["data"]["list"]}

        join_response = await client.post(
            "/api/v1/group-buy/groups/join",
            json={"group_id": group_id, "client_order_token": uuid4().hex},
            headers=second_headers,
        )
        assert join_response.status_code == 200
        second_payment_id = join_response.json()["data"]["order"]["payment_id"]
        second_order_id = join_response.json()["data"]["order"]["order_ids"][0]
        second_pay_response = await client.post(f"/api/v1/payments/{second_payment_id}/pay", headers=second_headers)
        assert second_pay_response.status_code == 200

        async with AsyncSessionLocal() as session:
            group = await session.get(GroupBuyGroup, group_id)
            first_order_result = await session.execute(
                select(Order).where(Order.id == first_order_id).options(selectinload(Order.items))
            )
            second_order_result = await session.execute(
                select(Order).where(Order.id == second_order_id).options(selectinload(Order.items))
            )
            first_order = first_order_result.scalars().unique().one_or_none()
            second_order = second_order_result.scalars().unique().one_or_none()
            participant_result = await session.execute(
                select(GroupBuyParticipant).where(GroupBuyParticipant.group_id == group_id)
            )
            participants = list(participant_result.scalars())
            assert group is not None
            assert group.status == "success"
            assert first_order is not None
            assert second_order is not None
            assert first_order.status == "pending_shipment"
            assert second_order.status == "pending_shipment"
            assert first_order.order_type == "group_buy"
            assert second_order.order_type == "group_buy"
            assert first_order.items[0].quantity == 2
            assert first_order.items[0].total_amount_cent == 3000
            assert len(participants) == 2
            assert {participant.status for participant in participants} == {"paid"}

        merchant_orders_after = await client.get("/api/v1/admin/orders", headers=merchant_headers)
        merchant_order_ids = {order["id"] for order in merchant_orders_after.json()["data"]["list"]}
        assert first_order_id in merchant_order_ids
        assert second_order_id in merchant_order_ids


@pytest.mark.asyncio
async def test_merchant_cannot_create_group_buy_for_other_shop_sku() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        sku_id, merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 2000)
        other_sku_id, other_merchant_id = await create_on_sale_sku_with_merchant(client, admin_headers, 2000)
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
        other_merchant_token = await create_merchant_admin_token(client, other_merchant_id)
        other_merchant_headers = {"Authorization": f"Bearer {other_merchant_token}"}

        other_products_response = await client.get("/api/v1/admin/products", headers=other_merchant_headers)
        other_product_id = other_products_response.json()["data"]["list"][0]["id"]

        response = await client.post(
            "/api/v1/admin/promotions/group-buy",
            json={
                "product_id": other_product_id,
                "sku_id": other_sku_id,
                "name": "forbidden group buy",
                "group_size": 2,
                "group_price_cent": 1500,
            },
            headers=merchant_headers,
        )
        assert response.status_code == 403

        own_products_response = await client.get("/api/v1/admin/products", headers=merchant_headers)
        own_product_id = own_products_response.json()["data"]["list"][0]["id"]
        own_response = await client.post(
            "/api/v1/admin/promotions/group-buy",
            json={
                "product_id": own_product_id,
                "sku_id": sku_id,
                "name": "owned group buy",
                "group_size": 3,
                "group_price_cent": 1500,
            },
            headers=merchant_headers,
        )
        assert own_response.status_code == 200
