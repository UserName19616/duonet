# src/web/multi_client.py
"""
Поддержка одновременного запуска нескольких клиентов на одной машине для демонстрации.
"""

import asyncio
import logging
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.common.identity.account import AccountManager
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

BASE_PORT = 8000
MAX_CLIENTS = 5
CLIENT_TIMEOUT = 30
TEST_MODE = False


class ClientConfig(BaseModel):
    client_id: str
    port: int
    status: str = "stopped"
    created_at: float
    last_heartbeat: float
    process_id: Optional[int] = None


class CreateClientResponse(BaseModel):
    success: bool
    client_id: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None
    error: Optional[str] = None


class SimpleResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class MultiClientManager:
    def __init__(self, base_port: int = BASE_PORT, max_clients: int = MAX_CLIENTS):
        self.base_port = base_port
        self.max_clients = max_clients
        self._clients: Dict[str, ClientConfig] = {}
        self._port_allocations: Dict[int, str] = {}
        self._processes: Dict[str, subprocess.Popen] = {}
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._clients.clear()
        self._port_allocations.clear()
        self._processes.clear()

    def _get_next_port(self) -> Optional[int]:
        for i in range(1, self.max_clients + 1):
            port = self.base_port + i
            if port not in self._port_allocations:
                return port
        return None

    async def create_client(self) -> Optional[ClientConfig]:
        async with self._lock:
            if len(self._clients) >= self.max_clients:
                return None
            port = self._get_next_port()
            if not port:
                return None
            client_id = str(uuid.uuid4())[:8]
            config = ClientConfig(client_id=client_id, port=port, status="starting",
                                  created_at=time.time(), last_heartbeat=time.time())
            self._clients[client_id] = config
            self._port_allocations[port] = client_id
            asyncio.create_task(self._start_client_async(config))
            return config

    async def _start_client_async(self, config: ClientConfig) -> None:
        await self.start_client(config.client_id)

    async def start_client(self, client_id: str, base_dir: str = None) -> bool:
        async with self._lock:
            config = self._clients.get(client_id)
            if not config:
                return False
            if config.status == "running":
                return True
            config.status = "starting"
            if TEST_MODE:
                config.status = "running"
                config.process_id = 12345
                logger.info(f"Test mode: started mock client {client_id} on port {config.port}")
                return True
            try:
                db_file = tempfile.NamedTemporaryFile(suffix=f"_{client_id}.db", delete=False)
                db_path = db_file.name
                db_file.close()
                env_file = tempfile.NamedTemporaryFile(mode="w", suffix=f"_{client_id}.env", delete=False)
                env_file.write(f"""
JWT_SECRET_KEY={secrets.token_urlsafe(32)}
DUONET_DB_PATH={db_path}
API_HOST=127.0.0.1
API_PORT={config.port}
RENDEZVOUS_URL=http://127.0.0.1:9878
""")
                env_file.close()
                cmd = [sys.executable, "-m", "uvicorn", "src.server.api.main:app",
                       "--host", "127.0.0.1", "--port", str(config.port), "--env-file", env_file.name]
                process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
                self._processes[client_id] = process
                config.process_id = process.pid
                config.status = "running"
                logger.info(f"Started client {client_id} on port {config.port} (PID: {process.pid})")
                return True
            except Exception as e:
                logger.error(f"Failed to start client {client_id}: {e}")
                config.status = "stopped"
                return False

    async def stop_client(self, client_id: str) -> bool:
        async with self._lock:
            config = self._clients.get(client_id)
            if not config:
                return False
            if config.status == "stopped":
                return True
            config.status = "stopping"
            process = self._processes.get(client_id)
            if process and not TEST_MODE:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if client_id in self._processes:
                    del self._processes[client_id]
            config.status = "stopped"
            config.process_id = None
            logger.info(f"Stopped client {client_id}")
            return True

    async def delete_client(self, client_id: str) -> bool:
        await self.stop_client(client_id)
        async with self._lock:
            config = self._clients.get(client_id)
            if config:
                if config.port in self._port_allocations:
                    del self._port_allocations[config.port]
                del self._clients[client_id]
                return True
            return False

    async def get_client(self, client_id: str) -> Optional[ClientConfig]:
        async with self._lock:
            return self._clients.get(client_id)

    async def get_all_clients(self) -> List[ClientConfig]:
        async with self._lock:
            return list(self._clients.values())

    async def update_heartbeat(self, client_id: str) -> bool:
        async with self._lock:
            config = self._clients.get(client_id)
            if not config:
                return False
            config.last_heartbeat = time.time()
            return True

    async def cleanup_stale(self) -> int:
        now = time.time()
        stale = []
        async with self._lock:
            for client_id, config in self._clients.items():
                if config.status == "running" and now - config.last_heartbeat > CLIENT_TIMEOUT:
                    stale.append(client_id)
        for client_id in stale:
            await self.stop_client(client_id)
        return len(stale)


_client_manager = MultiClientManager()


def get_client_manager() -> MultiClientManager:
    return _client_manager


def reset_client_manager() -> None:
    _client_manager.reset()


def set_test_mode(enabled: bool = True) -> None:
    global TEST_MODE
    TEST_MODE = enabled


def get_current_user(request: Request, account_manager: AccountManager) -> Optional[dict]:
    token = request.cookies.get("token")
    if not token:
        return None
    payload = account_manager.verify_token(token)
    if not payload:
        return None
    return {"public_id": payload["sub"], "account_id": bytes.fromhex(payload.get("account_id", "")),
            "is_server": payload.get("is_server", False)}


def create_multi_client_web_router(account_manager: AccountManager, storage: SQLiteStorage) -> APIRouter:
    router = APIRouter(prefix="/api/web", tags=["web_multi_client"])

    def get_current_user_dep(request: Request) -> dict:
        user = get_current_user(request, account_manager)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user

    @router.post("/clients/create", response_model=CreateClientResponse)
    async def create_client(user: dict = Depends(get_current_user_dep)) -> CreateClientResponse:
        config = await _client_manager.create_client()
        if not config:
            return CreateClientResponse(success=False, error="max_clients_reached")
        return CreateClientResponse(success=True, client_id=config.client_id, port=config.port,
                                    url=f"http://127.0.0.1:{config.port}")

    @router.get("/clients/{client_id}/url", response_model=SimpleResponse)
    async def get_client_url(client_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        config = await _client_manager.get_client(client_id)
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client_not_found")
        return SimpleResponse(success=True, data={"url": f"http://127.0.0.1:{config.port}"})

    @router.get("/clients/{client_id}/status", response_model=SimpleResponse)
    async def get_client_status(client_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        config = await _client_manager.get_client(client_id)
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client_not_found")
        return SimpleResponse(success=True, data={"status": config.status, "port": config.port,
                                                  "created_at": config.created_at, "last_heartbeat": config.last_heartbeat})

    @router.post("/clients/{client_id}/stop", response_model=SimpleResponse)
    async def stop_client(client_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        success = await _client_manager.stop_client(client_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client_not_found")
        return SimpleResponse(success=True)

    @router.delete("/clients/{client_id}", response_model=SimpleResponse)
    async def delete_client(client_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        success = await _client_manager.delete_client(client_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client_not_found")
        return SimpleResponse(success=True)

    @router.get("/clients", response_model=SimpleResponse)
    async def list_clients(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        clients = await _client_manager.get_all_clients()
        return SimpleResponse(success=True, data={"clients": [{"client_id": c.client_id, "port": c.port,
                                                               "status": c.status, "created_at": c.created_at,
                                                               "last_heartbeat": c.last_heartbeat} for c in clients],
                                                  "max_clients": MAX_CLIENTS, "total_clients": len(clients)})

    @router.post("/clients/heartbeat/{client_id}", response_model=SimpleResponse)
    async def client_heartbeat(client_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        success = await _client_manager.update_heartbeat(client_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client_not_found")
        return SimpleResponse(success=True)

    return router
