# src/web/monitor.py
"""
Панель мониторинга сети для демонстрации состояния соединений.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from src.common.identity.account import AccountManager
from src.server.network.network_map import NetworkMapManager
from src.server.network.rendezvous.rendezvous_manager import RendezvousManager
from src.server.network.rendezvous.rendezvous_client import RendezvousClient

logger = logging.getLogger(__name__)


class SimpleResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


def get_current_user(request: Request, account_manager: AccountManager) -> Optional[dict]:
    token = request.cookies.get("token")
    if not token:
        return None
    payload = account_manager.verify_token(token)
    if not payload:
        return None
    return {"public_id": payload["sub"], "account_id": bytes.fromhex(payload.get("account_id", "")),
            "is_server": payload.get("is_server", False)}


async def register_nat_server(account_manager: AccountManager, server_id: str,
                              rendezvous_port: int = 9878, api_port: int = 8443) -> bool:
    try:
        client = RendezvousClient(f"http://127.0.0.1:{rendezvous_port}")
        parts = server_id.split(".")
        region = parts[1] if len(parts) >= 2 else "ru"
        result = client.register_server(public_id=server_id, server_type="nat", region=region,
                                        ws_url=f"wss://127.0.0.1:{api_port}/ws", capacity=100, provides_proxy=True)
        if result:
            logger.info(f"NAT server {server_id} registered in Rendezvous")
        else:
            logger.error(f"Failed to register NAT server {server_id}")
        return result
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return False


class MonitorConnectionManager:
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()
        self._log_buffer: List[Dict] = []
        self._max_log_size = 100

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[client_id] = websocket

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            self._connections.pop(client_id, None)

    async def broadcast(self, message: dict) -> int:
        async with self._lock:
            disconnected = []
            for client_id, websocket in self._connections.items():
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(client_id)
            for client_id in disconnected:
                self._connections.pop(client_id, None)
            return len(self._connections)

    def add_log(self, message: str, level: str = "info") -> None:
        entry = {"timestamp": time.time(), "level": level, "message": message}
        self._log_buffer.insert(0, entry)
        if len(self._log_buffer) > self._max_log_size:
            self._log_buffer.pop()

    def get_logs(self, limit: int = 100) -> List[Dict]:
        return self._log_buffer[:limit]

    def clear_logs(self) -> None:
        self._log_buffer.clear()


_monitor_manager = MonitorConnectionManager()


async def websocket_monitor_handler(websocket: WebSocket, token: str, account_manager: AccountManager,
                                    network_map: NetworkMapManager) -> None:
    payload = account_manager.verify_token(token)
    if not payload:
        await websocket.close(code=1008, reason="Invalid token")
        return
    client_id = payload["sub"]
    await websocket.accept()
    await _monitor_manager.connect(client_id, websocket)
    logger.info(f"WebSocket monitor connected: {client_id}")
    await websocket.send_json({"type": "server_status", "data": {"status": "online", "uptime": time.time(),
                                                                 "active_connections": 0, "registered_servers": 0}})
    try:
        while True:
            await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
    except asyncio.TimeoutError:
        pass
    except WebSocketDisconnect:
        logger.info(f"WebSocket monitor disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket monitor error: {e}")
    finally:
        await _monitor_manager.disconnect(client_id)


async def websocket_rendezvous_logs_handler(websocket: WebSocket, token: str, account_manager: AccountManager,
                                            rendezvous_manager: Optional[RendezvousManager]) -> None:
    payload = account_manager.verify_token(token)
    if not payload:
        await websocket.close(code=1008, reason="Invalid token")
        return
    if not payload.get("is_server", False):
        await websocket.close(code=1003, reason="Only server accounts can access")
        return
    await websocket.accept()

    def on_log(log: str):
        asyncio.create_task(websocket.send_json({"type": "log", "data": log}))

    def on_status(status: str, message: str):
        asyncio.create_task(websocket.send_json({"type": "status", "data": {"status": status, "message": message}}))

    if rendezvous_manager:
        rendezvous_manager.add_log_listener(on_log)
        rendezvous_manager.add_status_listener(on_status)

    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info("WebSocket rendezvous logs disconnected")
    except Exception as e:
        logger.error(f"WebSocket rendezvous logs error: {e}")


def create_monitor_web_router(account_manager: AccountManager, network_map: NetworkMapManager,
                              rendezvous_manager: Optional[RendezvousManager] = None, api_port: int = 8443) -> APIRouter:
    router = APIRouter(prefix="/api/web", tags=["web_monitor"])

    def get_current_user_dep(request: Request) -> dict:
        user = get_current_user(request, account_manager)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user

    @router.get("/monitor/status", response_model=SimpleResponse)
    async def get_status(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        stats = await network_map.get_stats()
        nodes = await network_map.get_all_nodes()
        return SimpleResponse(success=True, data={"status": "online", "uptime": time.time(),
                                                  "active_connections": len(nodes), "registered_servers": len(await network_map.get_nodes_by_type("rendezvous")),
                                                  "stats": stats})

    @router.get("/monitor/server-info")
    async def monitor_server_info(request: Request, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        import socket, requests, netifaces
        local_ips = []
        try:
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr['addr']
                        if not ip.startswith('127.'):
                            local_ips.append(ip)
            if not local_ips:
                local_ips = ['127.0.0.1']
        except:
            local_ips = ['127.0.0.1']
        public_ip = None
        try:
            response = requests.get('https://api.ipify.org', timeout=3)
            public_ip = response.text.strip()
        except:
            pass
        ws_url = None
        for ip in local_ips:
            if not ip.startswith('127.'):
                ws_url = f"wss://{ip}:8443/ws"
                break
        if not ws_url:
            ws_url = f"wss://localhost:8443/ws"
        cursor = account_manager._storage.execute_sql("SELECT server_id FROM accounts WHERE account_id = ?", (user["account_id"],))
        row = cursor.fetchone()
        server_id = row[0] if row else user.get("public_id")
        return SimpleResponse(success=True, data={"server_id": server_id, "local_ips": local_ips,
                                                  "public_ip": public_ip, "ws_url": ws_url, "is_public": public_ip is not None})

    @router.get("/monitor/nodes", response_model=SimpleResponse)
    async def get_nodes(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        nodes = await network_map.get_all_nodes()
        result = [{"node_id": n.node_id, "node_type": n.node_type, "address": n.address, "port": n.port,
                   "ws_url": n.ws_url, "public_id": n.public_id, "last_seen": n.last_seen, "expires_at": n.expires_at,
                   "is_active": n.is_active(), "metadata": n.metadata} for n in nodes]
        return SimpleResponse(success=True, data={"nodes": result})

    @router.get("/monitor/logs", response_model=SimpleResponse)
    async def get_logs(limit: int = 100, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        logs = _monitor_manager.get_logs(limit)
        return SimpleResponse(success=True, data={"logs": logs})

    @router.post("/monitor/logs/clear", response_model=SimpleResponse)
    async def clear_logs(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        _monitor_manager.clear_logs()
        return SimpleResponse(success=True)

    @router.post("/rendezvous/start", response_model=SimpleResponse)
    async def start_rendezvous(request: Request, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        if not rendezvous_manager:
            return SimpleResponse(success=False, error="Rendezvous manager not initialized")
        if not user.get("is_server", False):
            return SimpleResponse(success=False, error="Only server accounts can start rendezvous")
        cursor = account_manager._storage.execute_sql("SELECT server_id FROM accounts WHERE account_id = ?", (user["account_id"],))
        row = cursor.fetchone()
        server_id = row[0] if row else user.get("public_id")
        _monitor_manager.add_log(f"DEBUG: server_id = {server_id}", "info")
        if rendezvous_manager.start():
            _monitor_manager.add_log("Rendezvous server starting...", "info")
            await asyncio.sleep(1)
            _monitor_manager.add_log(f"Регистрация NAT-сервера {server_id}...", "info")
            success = await register_nat_server(account_manager=account_manager, server_id=server_id,
                                                rendezvous_port=9878, api_port=api_port)
            if success:
                _monitor_manager.add_log(f"✅ NAT-сервер {server_id} зарегистрирован в Rendezvous", "info")
            else:
                _monitor_manager.add_log(f"❌ Ошибка регистрации NAT-сервера {server_id}", "error")
            return SimpleResponse(success=True, data={"status": "starting"})
        return SimpleResponse(success=False, error="Failed to start")

    @router.post("/rendezvous/stop", response_model=SimpleResponse)
    async def stop_rendezvous(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        if not rendezvous_manager:
            return SimpleResponse(success=False, error="Rendezvous manager not initialized")
        if not user.get("is_server", False):
            return SimpleResponse(success=False, error="Only server accounts can stop rendezvous")
        if rendezvous_manager.stop():
            _monitor_manager.add_log("Rendezvous server stopped", "info")
            return SimpleResponse(success=True, data={"status": "stopped"})
        return SimpleResponse(success=False, error="Failed to stop")

    @router.get("/rendezvous/status", response_model=SimpleResponse)
    async def get_rendezvous_status(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        if not rendezvous_manager:
            return SimpleResponse(success=False, error="Rendezvous manager not initialized")
        status_data = rendezvous_manager.get_status()
        return SimpleResponse(success=True, data=status_data)

    @router.websocket("/ws/monitor")
    async def websocket_monitor(websocket: WebSocket, token: str) -> None:
        await websocket_monitor_handler(websocket, token, account_manager, network_map)

    @router.websocket("/ws/rendezvous_logs")
    async def websocket_rendezvous_logs(websocket: WebSocket, token: str) -> None:
        await websocket_rendezvous_logs_handler(websocket, token, account_manager, rendezvous_manager)

    return router
