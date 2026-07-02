import pytest
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

pytest.importorskip("aiosqlite")

from app.core.security import hash_password
from app.db.session import init_db
from app.main import app
from app.models.user import AdminUser
from app.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_user_register_login_and_profile() -> None:
    await init_db()
    mobile = f"139{str(uuid4().int)[-8:]}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"mobile": mobile, "password": "12345678", "nickname": "测试用户"},
        )
        assert register_response.status_code in (200, 400)
        assert register_response.json()["code"] in (0, 40005)

        login_response = await client.post(
            "/api/v1/auth/login",
            json={"account": mobile, "password": "12345678"},
        )
        assert login_response.status_code == 200
        login_data = login_response.json()["data"]

        profile_response = await client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )
        assert profile_response.status_code == 200
        assert profile_response.json()["data"]["mobile"] == mobile


@pytest.mark.asyncio
async def test_admin_login_and_profile() -> None:
    await init_db()
    username = f"admin_{str(uuid4().int)[-8:]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        admin = AdminUser(
            username=username,
            real_name="测试管理员",
            role="platform_operator",
            password_hash=hash_password(password),
        )
        session.add(admin)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": password},
        )
        assert login_response.status_code == 200
        token = login_response.json()["data"]["access_token"]

        profile_response = await client.get(
            "/api/v1/admin/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert profile_response.status_code == 200
        assert profile_response.json()["data"]["username"] == username
