# src/api/server_db.py
"""
API-эндпоинты для работы с серверной БД (duonet_server.db).

Обеспечивает:
- Просмотр известных серверов
- Просмотр зарегистрированных клиентов
- Управление синхронизацией
- Статистику сети
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..storage.server_db import ServerDatabase, get_server_db

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic модели
# =============================================================================

class ServerResponse(BaseModel):
    """Информация о сервере."""
    server_id: str
    region: str
    ws_url: str
    status: str
    last_seen: int
    created_at: int
    updated_at: int


class ServerListResponse(BaseModel):
    """Список серверов."""
    success: bool
    servers: List[ServerResponse]
    total: int


class ClientResponse(BaseModel):
    """Информация о клиенте."""
    client_id: str
    server_id_hash: str
    region: str
    first_seen: int
    last_seen: int


class ClientListResponse(BaseModel):
    """Список клиентов."""
    success: bool
    clients: List[ClientResponse]
    total: int


class AddServerRequest(BaseModel):
    """Запрос на добавление сервера."""
    server_id: str = Field(..., min_length=1)
    region: str = Field(..., min_length=2, max_length=2)
    ws_url: str = Field(..., min_length=1)
    status: str = Field("active", pattern="^(active|inactive)$")


class AddClientRequest(BaseModel):
    """Запрос на добавление клиента."""
    client_id: str = Field(..., min_length=1)
    server_id: str = Field(..., min_length=1)
    region: str = Field(..., min_length=2, max_length=2)


class SyncRequest(BaseModel):
    """Запрос на синхронизацию."""
    target_server_id: str = Field(..., min_length=1)
    data: dict = Field(default_factory=dict)


class SimpleResponse(BaseModel):
    """Простой ответ."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class StatsResponse(BaseModel):
    """Статистика."""
    success: bool
    total_servers: int
    total_clients: int
    network_nodes: int
    pending_sync: int
    db_path: str


# =============================================================================
# Зависимости
# =============================================================================

def get_db() -> ServerDatabase:
    """Получение экземпляра ServerDatabase."""
    return get_server_db()


# =============================================================================
# Создание роутера
# =============================================================================

def create_server_db_router(db: Optional[ServerDatabase] = None) -> APIRouter:
    """
    Создание роутера для эндпоинтов серверной БД.

    Args:
        db: Экземпляр ServerDatabase (если None, используется глобальный)

    Returns:
        Настроенный APIRouter.
    """
    router = APIRouter(prefix="/api/server-db", tags=["server_db"])

    def get_db_dep() -> ServerDatabase:
        """Dependency для получения БД."""
        return db if db is not None else get_server_db()

    # =========================================================================
    # Servers endpoints
    # =========================================================================

    @router.get("/servers", response_model=ServerListResponse)
    async def get_servers(
        region: Optional[str] = None,
        limit: int = 100,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> ServerListResponse:
        """
        Получение списка известных серверов.

        Args:
            region: Фильтр по региону (опционально)
            limit: Максимальное количество
        """
        if region:
            servers_data = db.get_servers_by_region(region, limit)
            servers = []
            for s in servers_data:
                servers.append(ServerResponse(
                    server_id=s["server_id"],
                    region=s["region"],
                    ws_url=s["ws_url"],
                    status=s["status"],
                    last_seen=s.get("last_seen", 0),
                    created_at=s.get("created_at", 0),
                    updated_at=s.get("updated_at", 0),
                ))
        else:
            # Получаем все серверы
            with db._transaction() as conn:
                cursor = conn.execute(
                    "SELECT server_id, region, ws_url_encrypted, status, last_seen, created_at, updated_at "
                    "FROM servers WHERE status = 'active' ORDER BY last_seen DESC LIMIT ?",
                    (limit,)
                )
                servers = []
                for row in cursor.fetchall():
                    from ..storage.server_db import decrypt_data
                    servers.append(ServerResponse(
                        server_id=row["server_id"],
                        region=row["region"],
                        ws_url=decrypt_data(row["ws_url_encrypted"]),
                        status=row["status"],
                        last_seen=row["last_seen"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    ))

        return ServerListResponse(
            success=True,
            servers=servers,
            total=len(servers),
        )

    @router.get("/servers/{server_id}", response_model=ServerResponse)
    async def get_server(
        server_id: str,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> ServerResponse:
        """Получение информации о конкретном сервере."""
        server = db.get_server(server_id)
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server {server_id} not found",
            )

        return ServerResponse(
            server_id=server["server_id"],
            region=server["region"],
            ws_url=server["ws_url"],
            status=server["status"],
            last_seen=server["last_seen"],
            created_at=server["created_at"],
            updated_at=server["updated_at"],
        )

    @router.post("/servers", response_model=SimpleResponse)
    async def add_server(
        data: AddServerRequest,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> SimpleResponse:
        """Добавление или обновление сервера."""
        try:
            db.add_server(
                server_id=data.server_id,
                region=data.region,
                ws_url=data.ws_url,
                status=data.status,
            )
            return SimpleResponse(success=True, message=f"Server {data.server_id} added/updated")
        except Exception as e:
            logger.error(f"Failed to add server: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )

    @router.post("/servers/{server_id}/heartbeat", response_model=SimpleResponse)
    async def server_heartbeat(
        server_id: str,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> SimpleResponse:
        """Обновление времени последнего контакта с сервером."""
        success = db.update_last_seen(server_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server {server_id} not found",
            )
        return SimpleResponse(success=True, message=f"Heartbeat for {server_id} updated")

    # =========================================================================
    # Clients endpoints
    # =========================================================================

    @router.get("/clients", response_model=ClientListResponse)
    async def get_clients(
        region: Optional[str] = None,
        limit: int = 100,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> ClientListResponse:
        """Получение списка зарегистрированных клиентов."""
        with db._transaction() as conn:
            if region:
                cursor = conn.execute(
                    "SELECT client_id, server_id_hash, region, first_seen, last_seen "
                    "FROM clients WHERE region = ? ORDER BY last_seen DESC LIMIT ?",
                    (region, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT client_id, server_id_hash, region, first_seen, last_seen "
                    "FROM clients ORDER BY last_seen DESC LIMIT ?",
                    (limit,)
                )

            clients = []
            for row in cursor.fetchall():
                clients.append({
                    "client_id": row["client_id"],
                    "server_id_hash": row["server_id_hash"],
                    "region": row["region"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                })

        return ClientListResponse(
            success=True,
            clients=[ClientResponse(**c) for c in clients],
            total=len(clients),
        )

    @router.post("/clients", response_model=SimpleResponse)
    async def add_client(
        data: AddClientRequest,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> SimpleResponse:
        """Добавление клиента и привязка к серверу."""
        try:
            db.add_client(
                client_id=data.client_id,
                server_id=data.server_id,
                region=data.region,
            )
            return SimpleResponse(success=True, message=f"Client {data.client_id} added")
        except Exception as e:
            logger.error(f"Failed to add client: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )

    # =========================================================================
    # Sync endpoints
    # =========================================================================

    @router.post("/sync", response_model=SimpleResponse)
    async def sync_request(
        data: SyncRequest,
        db: ServerDatabase = Depends(get_db_dep),
    ) -> SimpleResponse:
        """
        Добавление задачи в очередь синхронизации.
        """
        try:
            sync_id = db.add_to_sync_queue(
                target_server_id=data.target_server_id,
                operation="sync",
                data=data.data,
            )
            return SimpleResponse(
                success=True,
                message=f"Sync task added to queue (id={sync_id})",
            )
        except Exception as e:
            logger.error(f"Failed to add sync task: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )

    @router.get("/sync/pending")
    async def get_pending_sync(
        limit: int = 100,
        db: ServerDatabase = Depends(get_db_dep),
    ):
        """Получение списка задач, ожидающих синхронизации."""
        pending = db.get_pending_sync(limit)
        return {
            "success": True,
            "data": {"pending": pending, "count": len(pending)},
        }

    # =========================================================================
    # Stats endpoint
    # =========================================================================

    @router.get("/stats", response_model=StatsResponse)
    async def get_stats(
        db: ServerDatabase = Depends(get_db_dep),
    ) -> StatsResponse:
        """Получение статистики серверной БД."""
        stats = db.get_stats()
        return StatsResponse(
            success=True,
            total_servers=stats["total_servers"],
            total_clients=stats["total_clients"],
            network_nodes=stats["network_nodes"],
            pending_sync=stats["pending_sync"],
            db_path=stats["db_path"],
        )

    # =========================================================================
    # Health endpoint
    # =========================================================================

    @router.get("/health", response_model=SimpleResponse)
    async def health_check(
        db: ServerDatabase = Depends(get_db_dep),
    ) -> SimpleResponse:
        """Проверка доступности серверной БД."""
        try:
            stats = db.get_stats()
            return SimpleResponse(
                success=True,
                message=f"Server DB healthy. {stats['total_servers']} servers, {stats['total_clients']} clients",
            )
        except Exception as e:
            return SimpleResponse(
                success=False,
                error=str(e),
            )

    return router
