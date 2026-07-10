from collections import defaultdict

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[channel].add(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        self._connections[channel].discard(websocket)

    async def broadcast(self, channel: str, message: dict) -> None:
        for websocket in list(self._connections[channel]):
            if websocket.client_state != WebSocketState.CONNECTED:
                self.disconnect(channel, websocket)
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(channel, websocket)


websocket_manager = WebSocketManager()
