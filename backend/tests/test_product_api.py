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


async def create_user_token(client: AsyncClient) -> str:
    mobile = f"136{str(uuid4().int)[-8:]}"
    password = "12345678"
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"mobile": mobile, "password": password, "nickname": "关注用户"},
    )
    assert register_response.status_code == 200
    login_response = await client.post("/api/v1/auth/login", json={"account": mobile, "password": password})
    assert login_response.status_code == 200
    return login_response.json()["data"]["access_token"]


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

        add_sku_response = await client.post(
            f"/api/v1/admin/products/{product_id}/skus",
            json={"name": "Large", "price_cent": 1800, "stock": 4, "spec_values": {"size": "large"}},
            headers=merchant_headers,
        )
        assert add_sku_response.status_code == 200
        assert len(add_sku_response.json()["data"]["skus"]) == 2
        added_sku = next(sku for sku in add_sku_response.json()["data"]["skus"] if sku["name"] == "Large")

        update_added_sku_response = await client.patch(
            f"/api/v1/admin/products/{product_id}/skus/{added_sku['id']}",
            json={"name": "Large Updated", "price_cent": 1900, "stock": 6},
            headers=merchant_headers,
        )
        assert update_added_sku_response.status_code == 200
        updated_sku = next(sku for sku in update_added_sku_response.json()["data"]["skus"] if sku["id"] == added_sku["id"])
        assert updated_sku["name"] == "Large Updated"
        assert updated_sku["price_cent"] == 1900
        assert updated_sku["stock"] == 6

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


@pytest.mark.asyncio
async def test_category_parent_filter_includes_descendant_products() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        merchant_id = await create_test_merchant("Category Tree Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        parent_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Parent Category-{uuid4().hex[:8]}", "sort_order": 1},
            headers=platform_headers,
        )
        assert parent_response.status_code == 200
        parent_id = parent_response.json()["data"]["id"]

        child_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Child Category-{uuid4().hex[:8]}", "parent_id": parent_id, "sort_order": 1},
            headers=platform_headers,
        )
        assert child_response.status_code == 200
        child_id = child_response.json()["data"]["id"]

        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "category_id": child_id,
                "name": "Child Category Product",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        assert product_response.status_code == 200
        product_id = product_response.json()["data"]["id"]

        parent_list_response = await client.get(f"/api/v1/products?category_id={parent_id}")
        assert parent_list_response.status_code == 200
        parent_products = parent_list_response.json()["data"]["list"]
        assert any(item["id"] == product_id for item in parent_products)

        child_list_response = await client.get(f"/api/v1/products?category_id={child_id}")
        assert child_list_response.status_code == 200
        child_products = child_list_response.json()["data"]["list"]
        assert any(item["id"] == product_id for item in child_products)


@pytest.mark.asyncio
async def test_create_category_validates_parent_and_depth() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        headers = {"Authorization": f"Bearer {platform_token}"}

        invalid_parent_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Invalid Parent Category-{uuid4().hex[:8]}", "parent_id": 999999999},
            headers=headers,
        )
        assert invalid_parent_response.status_code == 404

        first_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Level 1-{uuid4().hex[:8]}"},
            headers=headers,
        )
        second_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Level 2-{uuid4().hex[:8]}", "parent_id": first_response.json()["data"]["id"]},
            headers=headers,
        )
        third_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Level 3-{uuid4().hex[:8]}", "parent_id": second_response.json()["data"]["id"]},
            headers=headers,
        )
        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert third_response.status_code == 200

        too_deep_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Level 4-{uuid4().hex[:8]}", "parent_id": third_response.json()["data"]["id"]},
            headers=headers,
        )
        assert too_deep_response.status_code == 400
        assert too_deep_response.json()["code"] == 40005


@pytest.mark.asyncio
async def test_update_and_disable_category_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}

        parent_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Editable Parent-{uuid4().hex[:8]}", "sort_order": 10},
            headers=platform_headers,
        )
        child_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Editable Child-{uuid4().hex[:8]}", "parent_id": parent_response.json()["data"]["id"]},
            headers=platform_headers,
        )
        assert parent_response.status_code == 200
        assert child_response.status_code == 200
        parent_id = parent_response.json()["data"]["id"]
        child_id = child_response.json()["data"]["id"]

        update_response = await client.put(
            f"/api/v1/admin/categories/{child_id}",
            json={"name": "Updated Child Category", "sort_order": 3},
            headers=platform_headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["data"]["name"] == "Updated Child Category"
        assert update_response.json()["data"]["sort_order"] == 3

        self_parent_response = await client.put(
            f"/api/v1/admin/categories/{child_id}",
            json={"parent_id": child_id},
            headers=platform_headers,
        )
        assert self_parent_response.status_code == 400

        disable_parent_response = await client.delete(
            f"/api/v1/admin/categories/{parent_id}",
            headers=platform_headers,
        )
        assert disable_parent_response.status_code == 400
        assert disable_parent_response.json()["code"] == 40005

        disable_child_response = await client.delete(
            f"/api/v1/admin/categories/{child_id}",
            headers=platform_headers,
        )
        assert disable_child_response.status_code == 200

        categories_response = await client.get("/api/v1/categories")
        assert categories_response.status_code == 200
        category_ids = {category["id"] for category in categories_response.json()["data"]}
        assert child_id not in category_ids


@pytest.mark.asyncio
async def test_category_with_products_cannot_be_disabled() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        platform_token = await create_admin_token(client)
        platform_headers = {"Authorization": f"Bearer {platform_token}"}
        merchant_id = await create_test_merchant("Category Occupied Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        category_response = await client.post(
            "/api/v1/admin/categories",
            json={"name": f"Occupied Category-{uuid4().hex[:8]}"},
            headers=platform_headers,
        )
        category_id = category_response.json()["data"]["id"]

        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "category_id": category_id,
                "name": "Category Occupied Product",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        assert product_response.status_code == 200

        disable_response = await client.delete(
            f"/api/v1/admin/categories/{category_id}",
            headers=platform_headers,
        )
        assert disable_response.status_code == 400
        assert disable_response.json()["code"] == 40005


@pytest.mark.asyncio
async def test_product_list_price_filter_and_sort() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        merchant_id = await create_test_merchant("Filter Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

        cheap_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "name": f"Cheap Product {uuid4().hex[:8]}",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        expensive_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "name": f"Expensive Product {uuid4().hex[:8]}",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 5000, "stock": 3}],
            },
            headers=merchant_headers,
        )
        assert cheap_response.status_code == 200
        assert expensive_response.status_code == 200
        cheap_id = cheap_response.json()["data"]["id"]
        expensive_id = expensive_response.json()["data"]["id"]

        filtered_response = await client.get(
            f"/api/v1/products?merchant_id={merchant_id}&min_price_cent=2000&max_price_cent=6000"
        )
        assert filtered_response.status_code == 200
        filtered_ids = {item["id"] for item in filtered_response.json()["data"]["list"]}
        assert expensive_id in filtered_ids
        assert cheap_id not in filtered_ids

        sorted_response = await client.get(
            f"/api/v1/products?merchant_id={merchant_id}&sort_by=price&sort_order=asc"
        )
        assert sorted_response.status_code == 200
        sorted_ids = [item["id"] for item in sorted_response.json()["data"]["list"]]
        assert sorted_ids.index(cheap_id) < sorted_ids.index(expensive_id)

        invalid_response = await client.get("/api/v1/products?min_price_cent=6000&max_price_cent=2000")
        assert invalid_response.status_code == 400
        assert invalid_response.json()["code"] == 40001


@pytest.mark.asyncio
async def test_user_can_follow_and_unfollow_merchant() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        merchant_id = await create_test_merchant("Follow Merchant")
        user_token = await create_user_token(client)
        user_headers = {"Authorization": f"Bearer {user_token}"}

        public_status_response = await client.get(f"/api/v1/merchants/{merchant_id}/follow")
        assert public_status_response.status_code == 200
        assert public_status_response.json()["data"] == {
            "merchant_id": merchant_id,
            "followed": False,
            "follower_count": 0,
        }

        follow_response = await client.post(f"/api/v1/merchants/{merchant_id}/follow", headers=user_headers)
        assert follow_response.status_code == 200
        assert follow_response.json()["data"]["followed"] is True
        assert follow_response.json()["data"]["follower_count"] == 1

        repeat_follow_response = await client.post(f"/api/v1/merchants/{merchant_id}/follow", headers=user_headers)
        assert repeat_follow_response.status_code == 200
        assert repeat_follow_response.json()["data"]["follower_count"] == 1

        authed_status_response = await client.get(f"/api/v1/merchants/{merchant_id}/follow", headers=user_headers)
        assert authed_status_response.status_code == 200
        assert authed_status_response.json()["data"]["followed"] is True

        unfollow_response = await client.delete(f"/api/v1/merchants/{merchant_id}/follow", headers=user_headers)
        assert unfollow_response.status_code == 200
        assert unfollow_response.json()["data"]["followed"] is False
        assert unfollow_response.json()["data"]["follower_count"] == 0


@pytest.mark.asyncio
async def test_user_can_list_followed_merchants() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first_merchant_id = await create_test_merchant("Followed List Merchant A")
        second_merchant_id = await create_test_merchant("Followed List Merchant B")
        user_token = await create_user_token(client)
        user_headers = {"Authorization": f"Bearer {user_token}"}

        empty_response = await client.get("/api/v1/users/followed-merchants", headers=user_headers)
        assert empty_response.status_code == 200
        assert empty_response.json()["data"]["total"] == 0

        await client.post(f"/api/v1/merchants/{first_merchant_id}/follow", headers=user_headers)
        await client.post(f"/api/v1/merchants/{second_merchant_id}/follow", headers=user_headers)

        list_response = await client.get("/api/v1/users/followed-merchants?page=1&page_size=10", headers=user_headers)
        assert list_response.status_code == 200
        data = list_response.json()["data"]
        assert data["total"] == 2
        merchant_ids = {item["merchant"]["id"] for item in data["list"]}
        assert merchant_ids == {first_merchant_id, second_merchant_id}
        assert all(item["follower_count"] == 1 for item in data["list"])
        assert all(item["followed_at"] for item in data["list"])

        await client.delete(f"/api/v1/merchants/{first_merchant_id}/follow", headers=user_headers)
        after_unfollow_response = await client.get("/api/v1/users/followed-merchants", headers=user_headers)
        assert after_unfollow_response.status_code == 200
        after_unfollow_ids = {item["merchant"]["id"] for item in after_unfollow_response.json()["data"]["list"]}
        assert after_unfollow_ids == {second_merchant_id}


@pytest.mark.asyncio
async def test_user_can_favorite_and_list_products() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        merchant_id = await create_test_merchant("Favorite Product Merchant")
        merchant_token = await create_merchant_admin_token(client, merchant_id)
        merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
        product_response = await client.post(
            "/api/v1/admin/products",
            json={
                "merchant_id": merchant_id,
                "name": f"Favorite Product {uuid4().hex[:8]}",
                "description": "",
                "image_urls": [],
                "skus": [{"name": "Default", "price_cent": 1990, "stock": 5}],
            },
            headers=merchant_headers,
        )
        assert product_response.status_code == 200
        product_id = product_response.json()["data"]["id"]
        user_token = await create_user_token(client)
        user_headers = {"Authorization": f"Bearer {user_token}"}

        public_status_response = await client.get(f"/api/v1/products/{product_id}/favorite")
        assert public_status_response.status_code == 200
        assert public_status_response.json()["data"] == {
            "product_id": product_id,
            "favorited": False,
            "favorite_count": 0,
        }

        favorite_response = await client.post(f"/api/v1/products/{product_id}/favorite", headers=user_headers)
        assert favorite_response.status_code == 200
        assert favorite_response.json()["data"]["favorited"] is True
        assert favorite_response.json()["data"]["favorite_count"] == 1

        repeat_response = await client.post(f"/api/v1/products/{product_id}/favorite", headers=user_headers)
        assert repeat_response.status_code == 200
        assert repeat_response.json()["data"]["favorite_count"] == 1

        list_response = await client.get("/api/v1/users/favorite-products", headers=user_headers)
        assert list_response.status_code == 200
        list_data = list_response.json()["data"]
        assert list_data["total"] == 1
        assert list_data["list"][0]["product"]["id"] == product_id
        assert list_data["list"][0]["favorite_count"] == 1
        assert list_data["list"][0]["favorited_at"]

        unfavorite_response = await client.delete(f"/api/v1/products/{product_id}/favorite", headers=user_headers)
        assert unfavorite_response.status_code == 200
        assert unfavorite_response.json()["data"]["favorited"] is False
        assert unfavorite_response.json()["data"]["favorite_count"] == 0

        empty_list_response = await client.get("/api/v1/users/favorite-products", headers=user_headers)
        assert empty_list_response.status_code == 200
        assert empty_list_response.json()["data"]["total"] == 0
