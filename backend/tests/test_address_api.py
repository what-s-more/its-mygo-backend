from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app


async def create_user_token(client: AsyncClient) -> str:
    mobile = f"136{str(uuid4().int)[-8:]}"
    password = "12345678"
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"mobile": mobile, "password": password, "nickname": "地址用户"},
    )
    assert register_response.status_code == 200
    login_response = await client.post("/api/v1/auth/login", json={"account": mobile, "password": password})
    assert login_response.status_code == 200
    return login_response.json()["data"]["access_token"]


def address_payload(name: str, *, is_default: bool = False) -> dict:
    return {
        "receiver_name": name,
        "receiver_mobile": "13800000000",
        "province": "广东省",
        "city": "深圳市",
        "district": "南山区",
        "detail_address": f"{name}测试路 1 号",
        "is_default": is_default,
    }


@pytest.mark.asyncio
async def test_address_crud_and_default_flow() -> None:
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await create_user_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        first_response = await client.post("/api/v1/addresses", json=address_payload("张三"), headers=headers)
        assert first_response.status_code == 200
        first_address = first_response.json()["data"]
        assert first_address["is_default"] is True

        second_response = await client.post(
            "/api/v1/addresses",
            json=address_payload("李四", is_default=True),
            headers=headers,
        )
        assert second_response.status_code == 200
        second_address = second_response.json()["data"]
        assert second_address["is_default"] is True

        list_response = await client.get("/api/v1/addresses", headers=headers)
        assert list_response.status_code == 200
        addresses = list_response.json()["data"]
        assert len(addresses) >= 2
        assert addresses[0]["id"] == second_address["id"]

        update_response = await client.put(
            f"/api/v1/addresses/{first_address['id']}",
            json={"is_default": True, "detail_address": "张三测试路 2 号"},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["data"]["is_default"] is True
        assert update_response.json()["data"]["detail_address"] == "张三测试路 2 号"

        delete_response = await client.delete(f"/api/v1/addresses/{first_address['id']}", headers=headers)
        assert delete_response.status_code == 200

        final_response = await client.get("/api/v1/addresses", headers=headers)
        assert final_response.status_code == 200
        assert any(address["id"] == second_address["id"] for address in final_response.json()["data"])
