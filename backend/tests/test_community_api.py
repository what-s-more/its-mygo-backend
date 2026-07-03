from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.user import AdminUser
from backend.tests.test_order_api import create_on_sale_sku


async def create_user_token(client: AsyncClient) -> str:
    mobile = f"135{str(uuid4().int)[-8:]}"
    password = "12345678"
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"mobile": mobile, "password": password, "nickname": "社区用户"},
    )
    assert register_response.status_code == 200
    login_response = await client.post("/api/v1/auth/login", json={"account": mobile, "password": password})
    assert login_response.status_code == 200
    return login_response.json()["data"]["access_token"]


async def create_admin_token(client: AsyncClient) -> str:
    username = f"community_admin_{str(uuid4().int)[-8:]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="社区管理员",
                role="platform_operator",
                password_hash=hash_password(password),
            )
        )
        await session.commit()
    response = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_community_post_audit_like_and_comment_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user_token = await create_user_token(client)
        admin_token = await create_admin_token(client)
        user_headers = {"Authorization": f"Bearer {user_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        create_post_response = await client.post(
            "/api/v1/community/posts",
            json={
                "type": "normal",
                "title": "社区测试帖",
                "content": "这是一条待审核帖子",
                "topic_tags": ["测试"],
            },
            headers=user_headers,
        )
        assert create_post_response.status_code == 200
        post_id = create_post_response.json()["data"]["id"]
        assert create_post_response.json()["data"]["status"] == "published"

        public_before = await client.get("/api/v1/community/posts")
        assert any(post["id"] == post_id for post in public_before.json()["data"]["list"])

        pending_posts = await client.get("/api/v1/admin/community/posts", headers=admin_headers)
        assert pending_posts.status_code == 200
        assert any(post["id"] == post_id for post in pending_posts.json()["data"]["list"])

        audit_post_response = await client.post(
            f"/api/v1/admin/community/posts/{post_id}/audit",
            json={"approved": True},
            headers=admin_headers,
        )
        assert audit_post_response.status_code == 200
        assert audit_post_response.json()["data"]["status"] == "published"

        like_response = await client.post(f"/api/v1/community/posts/{post_id}/like", headers=user_headers)
        assert like_response.status_code == 200
        assert like_response.json()["data"]["liked"] is True
        assert like_response.json()["data"]["like_count"] == 1

        comment_response = await client.post(
            f"/api/v1/community/posts/{post_id}/comments",
            json={"content": "评论也需要审核"},
            headers=user_headers,
        )
        assert comment_response.status_code == 200
        comment_id = comment_response.json()["data"]["id"]
        assert comment_response.json()["data"]["status"] == "published"

        public_comments_before = await client.get(f"/api/v1/community/posts/{post_id}/comments")
        assert public_comments_before.json()["data"]["total"] == 1

        pending_comments = await client.get("/api/v1/admin/community/comments", headers=admin_headers)
        assert pending_comments.status_code == 200
        assert any(comment["id"] == comment_id for comment in pending_comments.json()["data"]["list"])

        audit_comment_response = await client.post(
            f"/api/v1/admin/community/comments/{comment_id}/audit",
            json={"approved": True},
            headers=admin_headers,
        )
        assert audit_comment_response.status_code == 200
        assert audit_comment_response.json()["data"]["status"] == "published"

        public_comments_after = await client.get(f"/api/v1/community/posts/{post_id}/comments")
        assert public_comments_after.json()["data"]["total"] == 1


@pytest.mark.asyncio
async def test_grass_post_source_order_rewards_author_points() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await create_admin_token(client)
        author_token = await create_user_token(client)
        buyer_token = await create_user_token(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        author_headers = {"Authorization": f"Bearer {author_token}"}
        buyer_headers = {"Authorization": f"Bearer {buyer_token}"}
        sku_id = await create_on_sale_sku(client, admin_headers)

        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 1}, headers=author_headers)
        author_order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex},
            headers=author_headers,
        )
        author_payment_id = author_order_response.json()["data"]["payment_id"]
        author_order_id = author_order_response.json()["data"]["order_ids"][0]
        await client.post(f"/api/v1/payments/{author_payment_id}/pay", headers=author_headers)
        await client.post(
            f"/api/v1/admin/orders/{author_order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "SF-GRASS-AUTHOR"},
            headers=admin_headers,
        )
        author_confirm_response = await client.post(
            f"/api/v1/orders/{author_order_id}/confirm",
            headers=author_headers,
        )
        product_id = author_confirm_response.json()["data"]["items"][0]["product_id"]

        grass_response = await client.post(
            "/api/v1/community/posts",
            json={
                "type": "grass",
                "title": "真实购买后的种草帖",
                "content": "这个商品不错",
                "product_ids": [product_id],
                "topic_tags": ["种草"],
            },
            headers=author_headers,
        )
        assert grass_response.status_code == 200
        post_id = grass_response.json()["data"]["id"]
        await client.post(
            f"/api/v1/admin/community/posts/{post_id}/audit",
            json={"approved": True},
            headers=admin_headers,
        )

        author_before = await client.get("/api/v1/auth/me", headers=author_headers)
        before_points = author_before.json()["data"]["points"]
        await client.post("/api/v1/cart", json={"sku_id": sku_id, "quantity": 1}, headers=buyer_headers)
        buyer_order_response = await client.post(
            "/api/v1/orders",
            json={"client_order_token": uuid4().hex, "source_post_id": post_id},
            headers=buyer_headers,
        )
        buyer_payment_id = buyer_order_response.json()["data"]["payment_id"]
        buyer_order_id = buyer_order_response.json()["data"]["order_ids"][0]
        await client.post(f"/api/v1/payments/{buyer_payment_id}/pay", headers=buyer_headers)
        await client.post(
            f"/api/v1/admin/orders/{buyer_order_id}/ship",
            json={"logistics_company": "SF Express", "tracking_no": "SF-GRASS-BUYER"},
            headers=admin_headers,
        )
        buyer_confirm_response = await client.post(f"/api/v1/orders/{buyer_order_id}/confirm", headers=buyer_headers)
        assert buyer_confirm_response.status_code == 200
        assert buyer_confirm_response.json()["data"]["source_post_id"] == post_id

        author_after = await client.get("/api/v1/auth/me", headers=author_headers)
        assert author_after.json()["data"]["points"] == before_points + 10
        points_logs = await client.get("/api/v1/users/points/logs", headers=author_headers)
        assert points_logs.status_code == 200
        assert any(
            log["source_type"] == "grass_conversion"
            and log["source_id"] == buyer_order_id
            and log["change_points"] == 10
            for log in points_logs.json()["data"]["list"]
        )
