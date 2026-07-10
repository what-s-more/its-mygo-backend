from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.core.token_blacklist import is_token_blacklisted
from app.db.session import AsyncSessionLocal
from app.services.auth_service import auth_service
from app.services.customer_service import customer_service
from app.schemas.customer_service import CustomerServiceMessageCreateRequest
from app.websocket.manager import websocket_manager

router = APIRouter()


@router.websocket("/chat/{conversation_id}")
async def customer_service_chat(websocket: WebSocket, conversation_id: int) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = decode_token(token)
    except ValueError:
        await websocket.close(code=4401)
        return
    if is_token_blacklisted(payload.get("jti")) or payload.get("token_type") != "access":
        await websocket.close(code=4401)
        return
    channel = f"customer_service:{conversation_id}"
    async with AsyncSessionLocal() as db:
        user = None
        admin = None
        if payload.get("account_type") == "consumer":
            user = await auth_service.get_user_by_id(db, int(payload["sub"]))
        elif payload.get("account_type") == "admin":
            admin = await auth_service.get_admin_by_id(db, int(payload["sub"]))
        if user is None and admin is None:
            await websocket.close(code=4403)
            return
        try:
            await customer_service.list_messages(db, conversation_id, user=user, admin=admin, page=1, page_size=1)
        except Exception:
            await websocket.close(code=4403)
            return
    await websocket_manager.connect(channel, websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type")
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if message_type != "chat.send":
                await websocket.send_json({"type": "error", "message": "unsupported message type"})
                continue
            async with AsyncSessionLocal() as db:
                try:
                    token_payload = decode_token(token)
                    if token_payload.get("account_type") == "consumer":
                        current_user = await auth_service.get_user_by_id(db, int(token_payload["sub"]))
                        if current_user is None:
                            raise ValueError("user missing")
                        message = await customer_service.send_user_message(
                            db,
                            current_user,
                            conversation_id,
                            CustomerServiceMessageCreateRequest(**(payload.get("data") or {})),
                        )
                    else:
                        current_admin = await auth_service.get_admin_by_id(db, int(token_payload["sub"]))
                        if current_admin is None:
                            raise ValueError("admin missing")
                        message = await customer_service.send_admin_message(
                            db,
                            current_admin,
                            conversation_id,
                            CustomerServiceMessageCreateRequest(**(payload.get("data") or {})),
                        )
                    await websocket.send_json({"type": "chat.ack", "data": message.model_dump(mode="json")})
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)[:200]})
    except WebSocketDisconnect:
        websocket_manager.disconnect(channel, websocket)
