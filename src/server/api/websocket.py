# src/server/api/websocket.py
"""
WebSocket-сервер для real-time взаимодействия с клиентами мессенджера.
Сервер выступает только как слепой ретранслятор, не анализируя содержимое сообщений.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from starlette.websockets import WebSocketDisconnect, WebSocketState

from src.common.identity.account import AccountManager
from src.client.messaging.message_router import MessageRouter
from src.client.storage.messages import MessagesStorage
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.config import WS_HEARTBEAT_INTERVAL, WS_IDLE_TIMEOUT

logger = logging.getLogger(__name__)


class ConnectionInfo:
    def __init__(self, websocket, public_id: str, client_ip: str, contact_id: str = None):
        self.websocket = websocket
        self.public_id = public_id
        self.client_ip = client_ip
        self.contact_id = contact_id
        self.connected_at = time.time()
        self.last_heartbeat = time.time()
        self.load = 0.0
        self.is_proxy = False
        self.proxy_group: Optional[str] = None


class WebSocketManager:
    def __init__(self):
        self._connections: Dict[str, ConnectionInfo] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def _close_websocket_safe(self, websocket, code: int = 1000, reason: str = "") -> None:
        try:
            if not hasattr(websocket, 'client_state'):
                await websocket.close(code=code, reason=reason)
                return
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close(code=code, reason=reason)
        except Exception as e:
            logger.debug(f"Error closing websocket: {e}")

    async def add_connection(self, websocket, public_id: str, client_ip: str,
                            is_proxy: bool = False, proxy_group: Optional[str] = None,
                            contact_id: str = None) -> None:
        async with self._lock:
            if public_id in self._connections:
                old = self._connections[public_id]
                await self._close_websocket_safe(old.websocket, code=1000, reason="Replaced by new connection")
                del self._connections[public_id]
            conn = ConnectionInfo(websocket, public_id, client_ip, contact_id)
            conn.is_proxy = is_proxy
            conn.proxy_group = proxy_group
            self._connections[public_id] = conn
            logger.info(f"✅ CONNECTION ADDED: {public_id} (contact: {contact_id}) (total: {len(self._connections)})")

    async def remove_connection(self, public_id: str) -> bool:
        async with self._lock:
            if public_id not in self._connections:
                return False
            conn = self._connections[public_id]
            await self._close_websocket_safe(conn.websocket, code=1000)
            del self._connections[public_id]
            logger.info(f"WebSocket connection removed: {public_id} (remaining: {len(self._connections)})")
            return True

    def get_connection(self, public_id: str) -> Optional[ConnectionInfo]:
        return self._connections.get(public_id)

    def get_all_connections(self) -> List[Dict[str, Any]]:
        result = []
        for public_id, conn in self._connections.items():
            result.append({
                "public_id": public_id,
                "connected_at": conn.connected_at,
                "last_heartbeat": conn.last_heartbeat,
                "is_proxy": conn.is_proxy,
                "proxy_group": conn.proxy_group,
            })
        return result

    def get_connection_count(self) -> int:
        return len(self._connections)

    async def send_to_client(self, public_id: str, message: Dict[str, Any]) -> bool:
        """Send JSON message to client."""
        # Защита от строк
        if isinstance(message, str):
            logger.error(f"String message received for {public_id}, expected dict. Converting...")
            message = {"type": "raw", "data": message}

        conn = self.get_connection(public_id)
        if not conn:
            return False

        try:
            await conn.websocket.send_json(message)
            logger.debug(f"Message sent to {public_id}: {message.get('type')}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {public_id}: {e}")
            await self.remove_connection(public_id)
            return False

    async def broadcast_to_region(self, region: str, message: Dict[str, Any], exclude: Optional[List[str]] = None) -> int:
        exclude_set = set(exclude or [])
        count = 0
        for public_id, conn in self._connections.items():
            if public_id in exclude_set:
                continue
            if public_id.endswith(f".{region}") or public_id.endswith(f".{region}.srv"):
                if await self.send_to_client(public_id, message):
                    count += 1
        return count

    async def broadcast_to_all(self, message: Dict[str, Any]) -> int:
        count = 0
        for public_id in list(self._connections.keys()):
            if await self.send_to_client(public_id, message):
                count += 1
        return count

    async def update_heartbeat(self, public_id: str) -> None:
        conn = self.get_connection(public_id)
        if conn:
            conn.last_heartbeat = time.time()

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
            now = time.time()
            async with self._lock:
                expired = [
                    pid for pid, conn in self._connections.items()
                    if now - conn.last_heartbeat > WS_IDLE_TIMEOUT
                ]
                for pid in expired:
                    conn = self._connections[pid]
                    await self._close_websocket_safe(conn.websocket, code=1001, reason="Heartbeat timeout")
                    del self._connections[pid]
                    logger.info(f"Removed inactive connection: {pid}")

    async def start_cleanup_task(self) -> None:
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def close_all(self) -> None:
        async with self._lock:
            for conn in self._connections.values():
                await self._close_websocket_safe(conn.websocket, code=1000)
            self._connections.clear()


_ws_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> Optional[WebSocketManager]:
    return _ws_manager


def set_ws_manager(manager: WebSocketManager) -> None:
    global _ws_manager
    _ws_manager = manager
    logger.info(f"✅ WebSocketManager set globally")


async def _deliver_offline_messages(
    public_id: str,
    message_router: MessageRouter,
    messages_storage: MessagesStorage,
) -> None:
    unread = messages_storage.get_unread(public_id)
    for msg in unread:
        await message_router.send_to_client(
            public_id,
            {
                "type": "new_message",
                "data": {
                    "id": msg.id,
                    "from": msg.from_id,
                    "encrypted": msg.encrypted.hex() if isinstance(msg.encrypted, bytes) else msg.encrypted,
                    "timestamp": msg.timestamp,
                    "has_phrase": msg.has_phrase,
                },
            }
        )


async def _get_status_response(
    public_id: str,
    account_manager: AccountManager,
    rendezvous_client: RendezvousClient,
) -> Dict[str, Any]:
    parts = public_id.split(".")
    region = parts[1] if len(parts) >= 2 else "ru"
    servers = rendezvous_client.get_servers_by_region_with_load(region)
    return {
        "type": "status_response",
        "data": {
            "online": True,
            "server_load": 0.5,
            "server_overloaded": False,
            "recommend_servers": [
                {"ws_url": s.get("ws_url"), "load": s.get("load", 0) / 100}
                for s in servers[:3]
            ],
            "reconnect": False,
        },
    }


async def _handle_message(
    public_id: str,
    data: str,
    account_manager: AccountManager,
    message_router: MessageRouter,
    rendezvous_client: RendezvousClient,
    ws_manager: WebSocketManager,
) -> None:
    """
    Обработка входящего WebSocket сообщения.
    Сервер выступает только как слепой ретранслятор.
    """
    # Парсим JSON
    if isinstance(data, str):
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            await ws_manager.send_to_client(
                public_id,
                {"type": "error", "data": {"code": "invalid_json", "message": "Invalid JSON"}},
            )
            return
    else:
        msg = data

    msg_type = msg.get("type")
    msg_data = msg.get("data", {})

    logger.debug(f"Received message type '{msg_type}' from {public_id}")

    # ========== СЛУЖЕБНЫЕ СООБЩЕНИЯ (heartbeat, status, typing) ==========

    if msg_type == "status":
        await ws_manager.update_heartbeat(public_id)
        conn = ws_manager.get_connection(public_id)
        if conn:
            conn.last_heartbeat = time.time()
        await ws_manager.send_to_client(public_id, {
            "type": "status_response",
            "data": {"online": True, "timestamp": int(time.time())}
        })
        logger.info(f"Status received from {public_id}")
        return

    if msg_type == "ping" or (isinstance(msg, str) and msg == "ping"):
        await ws_manager.update_heartbeat(public_id)
        if ws_manager.get_connection(public_id):
            await ws_manager.send_to_client(public_id, {"type": "pong", "data": {}})
        return

    if msg_type == "pong":
        await ws_manager.update_heartbeat(public_id)
        return

    if msg_type == "typing":
        to_id = msg_data.get("to")
        if to_id:
            await ws_manager.send_to_client(
                to_id,
                {"type": "typing", "data": {"from": public_id, "is_typing": msg_data.get("is_typing", True)}},
            )
            logger.debug(f"Typing notification from {public_id} to {to_id}")
        return

    # ========== ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ (слепой ретранслятор) ==========
    if msg_type == "message":
        # Нормализуем msg_data - если это строка, парсим JSON
        if isinstance(msg_data, str):
            try:
                msg_data = json.loads(msg_data)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message data: {e}")
                await ws_manager.send_to_client(
                    public_id,
                    {"type": "error", "data": {"code": "invalid_json", "message": "Invalid message data"}}
                )
                return

        # Получаем to_id
        to_id = msg.get("to") or msg_data.get("to")

        if not to_id:
            logger.warning(f"Missing recipient")
            await ws_manager.send_to_client(
                public_id,
                {"type": "error", "data": {"code": "missing_to", "message": "Missing recipient"}}
            )
            return

        # Получаем данные сообщения
        message_id = msg_data.get("message_id") or msg_data.get("id")
        encrypted = msg_data.get("encrypted", "")
        session_key = msg_data.get("session_key", "")
        has_phrase = msg_data.get("has_phrase", False)
        plaintext = msg_data.get("plaintext", "")
        timestamp = msg_data.get("timestamp", int(time.time()))

        logger.info(f"📨 Processing message: {message_id} from {public_id} to {to_id}")

        # СОХРАНЯЕМ СООБЩЕНИЕ В БД (сервер не знает о системных сообщениях)
        try:
            import sqlite3
            conn = sqlite3.connect("duonet.db")
            conn.execute("""
                INSERT OR REPLACE INTO messages
                (id, from_id, to_id, session_key, encrypted, timestamp,
                 delivered, read, direction, has_phrase)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_id,
                public_id,
                to_id,
                session_key,
                encrypted,
                timestamp,
                0,  # delivered
                0,  # read
                "outgoing",
                1 if has_phrase else 0,
            ))
            conn.commit()
            conn.close()
            logger.info(f"✅ Message saved to DB: {message_id}")
        except Exception as e:
            logger.error(f"❌ Failed to save message: {e}")

        # Пересылаем сообщение получателю
        success = await ws_manager.send_to_client(to_id, {
            "type": "message",
            "data": {
                "message_id": message_id,
                "from": public_id,
                "encrypted": encrypted,
                "session_key": session_key,
                "timestamp": timestamp,
                "has_phrase": has_phrase,
                "is_own": False,
                "plaintext": plaintext if public_id == to_id else None,
            }
        })

        if success:
            logger.info(f"✅ Message forwarded to {to_id}")
            # Отправляем подтверждение отправителю
            await ws_manager.send_to_client(public_id, {
                "type": "message_delivered",
                "data": {"message_id": message_id}
            })
        else:
            logger.warning(f"⚠️ Recipient {to_id} offline, message saved for later")

        return

    # Если тип сообщения не распознан
    logger.warning(f"Unknown message type from {public_id}: {msg_type}")
    await ws_manager.send_to_client(
        public_id,
        {"type": "error", "data": {"code": "unknown_type", "message": f"Unknown type: {msg_type}"}},
    )


async def websocket_endpoint(
    websocket,
    account_manager: AccountManager,
    message_router: MessageRouter,
    messages_storage: MessagesStorage,
    rendezvous_client: RendezvousClient,
    ws_manager: WebSocketManager,
    token: str,
    contact: str = None,
):
    global _ws_manager
    _ws_manager = ws_manager
    logger.info(f"✅ Global WebSocketManager set in websocket_endpoint")

    payload = account_manager.verify_token(token)
    if not payload:
        logger.warning(f"WebSocket rejected: invalid token")
        await websocket.close(code=1008, reason="Invalid token")
        return

    public_id = payload["sub"]
    is_server = payload.get("is_server", False)
    client_ip = websocket.client.host if websocket.client else "unknown"

    await websocket.accept()
    logger.info(f"WebSocket accepted for {public_id}")

    await ws_manager.add_connection(
        websocket=websocket,
        public_id=public_id,
        client_ip=client_ip,
        is_proxy=is_server,
        contact_id=contact,
    )

    welcome_msg = {
        "type": "connected",
        "data": {
            "public_id": public_id,
            "timestamp": int(time.time()),
            "message": "WebSocket connected successfully"
        }
    }
    await ws_manager.send_to_client(public_id, welcome_msg)

    status_response = await _get_status_response(public_id, account_manager, rendezvous_client)
    await ws_manager.send_to_client(public_id, status_response)
    logger.info(f"Auto-status sent to {public_id}")

    await ws_manager.update_heartbeat(public_id)
    logger.info(f"WebSocket fully connected and registered: {public_id}")

    await _deliver_offline_messages(public_id, message_router, messages_storage)

    try:
        while True:
            data = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=WS_HEARTBEAT_INTERVAL + 10,
            )
            await _handle_message(
                public_id,
                data,
                account_manager,
                message_router,
                rendezvous_client,
                ws_manager,
            )
            await ws_manager.update_heartbeat(public_id)

    except asyncio.TimeoutError:
        logger.warning(f"Heartbeat timeout for {public_id}")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {public_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {public_id}: {e}")
    finally:
        await ws_manager.remove_connection(public_id)
        logger.info(f"WebSocket cleanup completed for {public_id}")


debug_router = APIRouter(prefix="/api/debug", tags=["debug"])


@debug_router.get("/ws-connections")
async def debug_ws_connections():
    global _ws_manager
    if _ws_manager is None:
        return {"connections": [], "error": "ws_manager not initialized", "hint": "No WebSocket connections yet"}
    return {"connections": _ws_manager.get_all_connections(), "count": _ws_manager.get_connection_count()}
