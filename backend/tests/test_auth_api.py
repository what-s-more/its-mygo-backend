import pytest
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

from app.core.security import hash_password
from app.db.session import init_db
from app.main import app
from app.models.user import AdminUser
from app.db.session import AsyncSessionLocal
from app.services.platform_setting_service import platform_setting_service


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

        update_response = await client.put(
            "/api/v1/users/profile",
            json={
                "nickname": "新昵称",
                "gender": "female",
                "birthday": "2000-01-02",
                "email": "user@example.com",
            },
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )
        assert update_response.status_code == 200
        update_data = update_response.json()["data"]
        assert update_data["nickname"] == "新昵称"
        assert update_data["gender"] == "female"
        assert update_data["birthday"] == "2000-01-02"
        assert update_data["email"] == "user@example.com"


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


@pytest.mark.asyncio
async def test_member_points_config_and_sign_in_flow() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        await platform_setting_service.update_member_points_config(
            session,
            platform_setting_service.DEFAULT_MEMBER_POINTS_CONFIG,
        )
    username = f"points_admin_{str(uuid4().int)[-8:]}"
    password = "12345678"
    async with AsyncSessionLocal() as session:
        session.add(
            AdminUser(
                username=username,
                real_name="积分管理员",
                role="platform_operator",
                password_hash=hash_password(password),
            )
        )
        await session.commit()

    mobile = f"136{str(uuid4().int)[-8:]}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_login = await client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['data']['access_token']}"}

        default_config = await client.get("/api/v1/admin/settings/member-points", headers=admin_headers)
        assert default_config.status_code == 200
        assert default_config.json()["data"]["max_points_discount_percent"] == 10

        update_config = await client.put(
            "/api/v1/admin/settings/member-points",
            json={
                "level_rules": [
                    {"level": "normal", "name": "普通会员", "threshold_cent": 0, "benefits": ["基础积分"]},
                    {"level": "vip", "name": "VIP会员", "threshold_cent": 10000, "benefits": ["积分加速"]},
                ],
                "sign_in_base_points": 5,
                "sign_in_streak_increment": 2,
                "sign_in_max_points": 20,
                "points_to_yuan_rate": 100,
                "max_points_discount_percent": 15,
            },
            headers=admin_headers,
        )
        assert update_config.status_code == 200
        assert update_config.json()["data"]["sign_in_base_points"] == 5

        await client.post(
            "/api/v1/auth/register",
            json={"mobile": mobile, "password": password, "nickname": "积分用户"},
        )
        user_login = await client.post("/api/v1/auth/login", json={"account": mobile, "password": password})
        user_headers = {"Authorization": f"Bearer {user_login.json()['data']['access_token']}"}

        account_before = await client.get("/api/v1/users/points", headers=user_headers)
        assert account_before.status_code == 200
        assert account_before.json()["data"]["today_reward_points"] == 5

        sign_response = await client.post("/api/v1/users/sign-in", headers=user_headers)
        assert sign_response.status_code == 200
        assert sign_response.json()["data"]["reward_points"] == 5

        repeat_response = await client.post("/api/v1/users/sign-in", headers=user_headers)
        assert repeat_response.status_code == 200
        assert repeat_response.json()["data"]["reward_points"] == 0

        logs_response = await client.get("/api/v1/users/points/logs", headers=user_headers)
        assert logs_response.status_code == 200
        assert any(log["source_type"] == "sign_in" for log in logs_response.json()["data"]["list"])

        level_response = await client.get("/api/v1/users/level", headers=user_headers)
        assert level_response.status_code == 200
        assert level_response.json()["data"]["level"] == "normal"
