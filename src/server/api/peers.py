# src/api/peers.py
"""
API эндпоинты для управления пирами (подключениями между серверами).
"""

import time
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field

from src.common.identity.account import AccountManager
from ..storage.server_db import get_server_db

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic модели
# =============================================================================

class PeerAddRequest(BaseModel):
    """Запрос на добавление пира."""
    peer_id: str = Field(..., min_length=1)
    ws_url: str = Field(..., min_length=1)
    region: str = Field("ru", min_length=2, max_length=2)
    signature: Optional[str] = None


class PeerResponse(BaseModel):
    """Информация о пире."""
    peer_id: str
    ws_url: str
    region: str
    status: str
    last_connected: Optional[int] = None
    added_at: int
    updated_at: int


class PeerListResponse(BaseModel):
    """Список пиров."""
    success: bool
    peers: List[PeerResponse]
    total: int


class SimpleResponse(BaseModel):
    """Простой ответ."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Вспомогательные функции для авторизации (заглушка)
# =============================================================================

def get_current_user_dep(request: Request):
    """Получение текущего пользователя из cookie."""
    token = request.cookies.get("token")
    if not token:
        return {"public_id": None, "is_server": False}
    # В реальном коде здесь проверка токена через account_manager
    return {"public_id": None, "is_server": True}


# =============================================================================
# Создание роутера
# =============================================================================

def create_peers_router(account_manager: AccountManager) -> APIRouter:
    """
    Создание роутера для управления пирами.
    """
    router = APIRouter(prefix="/api/peers", tags=["peers"])
    db = get_server_db()

    # Инициализируем таблицу peers
    with db._transaction() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS peers (
                peer_id TEXT PRIMARY KEY,
                ws_url TEXT NOT NULL,
                region TEXT,
                status TEXT DEFAULT 'disconnected',
                last_connected INTEGER,
                added_by TEXT DEFAULT 'manual',
                added_at INTEGER,
                updated_at INTEGER
            )
        """)
        # Добавляем индексы
        conn.execute("CREATE INDEX IF NOT EXISTS idx_peers_status ON peers(status)")

    @router.post("/add", response_model=SimpleResponse)
    async def add_peer(data: PeerAddRequest) -> SimpleResponse:
        """Добавление пира в БД."""
        now = int(time.time())

        try:
            with db._transaction() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO peers
                    (peer_id, ws_url, region, status, added_by, added_at, updated_at)
                    VALUES (?, ?, ?, 'disconnected', 'manual', ?, ?)
                """, (data.peer_id, data.ws_url, data.region, now, now))

            logger.info(f"Peer added: {data.peer_id} -> {data.ws_url}")
            return SimpleResponse(success=True, message=f"Peer {data.peer_id} added")
        except Exception as e:
            logger.error(f"Failed to add peer: {e}")
            return SimpleResponse(success=False, error=str(e))

    @router.get("/list", response_model=PeerListResponse)
    async def list_peers() -> PeerListResponse:
        """Получение списка всех пиров."""
        peers = []
        with db._transaction() as conn:
            cursor = conn.execute("""
                SELECT peer_id, ws_url, region, status, last_connected, added_at, updated_at
                FROM peers
                ORDER BY status DESC, added_at ASC
            """)
            for row in cursor.fetchall():
                peers.append(PeerResponse(
                    peer_id=row[0],
                    ws_url=row[1],
                    region=row[2] or "ru",
                    status=row[3],
                    last_connected=row[4],
                    added_at=row[5],
                    updated_at=row[6],
                ))

        return PeerListResponse(success=True, peers=peers, total=len(peers))

    @router.post("/{peer_id}/connect", response_model=SimpleResponse)
    async def connect_peer(peer_id: str) -> SimpleResponse:
        """Инициировать подключение к пиру."""
        # Получаем информацию о пире
        with db._transaction() as conn:
            cursor = conn.execute(
                "SELECT ws_url FROM peers WHERE peer_id = ?",
                (peer_id,)
            )
            row = cursor.fetchone()
            if not row:
                return SimpleResponse(success=False, error="Peer not found")
            ws_url = row[0]

        # Обновляем статус на "connecting"
        with db._transaction() as conn:
            conn.execute(
                "UPDATE peers SET status = 'connecting', updated_at = ? WHERE peer_id = ?",
                (int(time.time()), peer_id)
            )

        # TODO: Реальная логика подключения через WebSocket
        logger.info(f"Connecting to peer {peer_id} at {ws_url}")

        # Имитируем успешное подключение
        with db._transaction() as conn:
            conn.execute("""
                UPDATE peers
                SET status = 'connected', last_connected = ?, updated_at = ?
                WHERE peer_id = ?
            """, (int(time.time()), int(time.time()), peer_id))

        return SimpleResponse(success=True, message=f"Connected to {peer_id}")

    @router.post("/{peer_id}/disconnect", response_model=SimpleResponse)
    async def disconnect_peer(peer_id: str) -> SimpleResponse:
        """Отключение от пира."""
        with db._transaction() as conn:
            conn.execute("""
                UPDATE peers
                SET status = 'disconnected', updated_at = ?
                WHERE peer_id = ?
            """, (int(time.time()), peer_id))

        logger.info(f"Disconnected from peer {peer_id}")
        return SimpleResponse(success=True, message=f"Disconnected from {peer_id}")

    @router.delete("/{peer_id}", response_model=SimpleResponse)
    async def delete_peer(peer_id: str) -> SimpleResponse:
        """Удаление пира из БД."""
        with db._transaction() as conn:
            conn.execute("DELETE FROM peers WHERE peer_id = ?", (peer_id,))

        logger.info(f"Peer deleted: {peer_id}")
        return SimpleResponse(success=True, message=f"Peer {peer_id} deleted")

    @router.post("/reconnect-all", response_model=SimpleResponse)
    async def reconnect_all() -> SimpleResponse:
        """Переподключение ко всем пирам."""
        with db._transaction() as conn:
            cursor = conn.execute(
                "SELECT peer_id FROM peers WHERE status != 'connected'"
            )
            peers = [row[0] for row in cursor.fetchall()]

        success_count = 0
        for peer_id in peers:
            # TODO: реальное подключение
            success_count += 1

        return SimpleResponse(
            success=True,
            message=f"Reconnected to {success_count}/{len(peers)} peers"
        )

    @router.get("/server-info")
    async def get_server_info(request: Request) -> dict:
        """Получение информации о текущем сервере (IP, WS URL)."""
        import socket
        import requests

        # Получаем локальные IP
        local_ips = []
        try:
            hostname = socket.gethostname()
            local_ips = list(set(socket.gethostbyname_ex(hostname)[2]))
            if not local_ips:
                local_ips = ['127.0.0.1']
        except:
            local_ips = ['127.0.0.1']

        # Получаем публичный IP
        public_ip = None
        try:
            response = requests.get('https://api.ipify.org', timeout=3)
            public_ip = response.text.strip()
        except:
            pass

        # Формируем WS URL (берём первый не-localhost IP)
        ws_url = None
        for ip in local_ips:
            if not ip.startswith('127.'):
                ws_url = f"wss://{ip}:8443/ws"
                break
        if not ws_url:
            ws_url = f"wss://localhost:8443/ws"

        return {
            "success": True,
            "data": {
                "server_id": request.cookies.get("server_id", "Unknown"),
                "local_ips": [ip for ip in local_ips if not ip.startswith('127.')] or local_ips,
                "public_ip": public_ip,
                "ws_url": ws_url,
                "is_public": public_ip is not None,
            }
        }

    return router
