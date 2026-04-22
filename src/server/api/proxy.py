# src/api/proxy.py
"""
API-эндпоинты для управления прокси-сервисом.

Доступны только для владельца сервера (NAT-сервера).
Обеспечивают генерацию приглашений, управление клиентами,
просмотр статистики и настройку ограничений.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.common.identity.account import AccountManager
from src.server.proxy.client_crud import ClientManager   # <-- ИСПРАВЛЕНО

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic модели
# =============================================================================

class InviteRequest(BaseModel):
    """Запрос на генерацию приглашения."""
    client_name: str = Field(..., min_length=1, max_length=64)
    expires_in: int = Field(86400, ge=3600, le=2592000)  # 1 час - 30 дней
    group: str = Field("basic", pattern="^(basic|standard|privileged)$")
    daily_limit_mb: Optional[int] = Field(None, ge=0, le=5120)


class InviteResponse(BaseModel):
    """Ответ с приглашением."""
    success: bool
    token: Optional[str] = None
    invite_url: Optional[str] = None
    qr_code: Optional[str] = None  # base64 PNG
    expires_at: Optional[int] = None
    error: Optional[str] = None


class ClientInfoResponse(BaseModel):
    """Информация о прокси-клиенте."""
    client_id: str
    public_id: str
    name: str
    group: str
    connected: bool
    last_seen: Optional[int] = None
    traffic_today_mb: float
    traffic_total_mb: float
    daily_limit_mb: Optional[int] = None
    expires_at: Optional[int] = None
    created_at: int


class ClientsListResponse(BaseModel):
    """Ответ со списком клиентов."""
    success: bool
    clients: List[ClientInfoResponse]
    total_clients: int
    max_clients: int


class UpdateClientRequest(BaseModel):
    """Запрос на обновление клиента."""
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    group: Optional[str] = Field(None, pattern="^(basic|standard|privileged)$")
    daily_limit_mb: Optional[int] = Field(None, ge=0, le=5120)
    expires_at: Optional[int] = Field(None, ge=0)


class TrafficStatsResponse(BaseModel):
    """Ответ со статистикой трафика."""
    success: bool
    total_today_mb: float
    total_month_mb: float
    total_all_mb: float
    active_clients: int
    total_clients: int


class SettingsResponse(BaseModel):
    """Ответ с настройками."""
    success: bool
    max_clients: int
    default_daily_limit_mb: int
    default_group: str
    proxy_enabled: bool
    proxy_port: int = 9879


class UpdateSettingsRequest(BaseModel):
    """Запрос на обновление настроек."""
    max_clients: Optional[int] = Field(None, ge=0, le=1000)
    default_daily_limit_mb: Optional[int] = Field(None, ge=0, le=10240)
    default_group: Optional[str] = Field(None, pattern="^(basic|standard|privileged)$")
    proxy_enabled: Optional[bool] = None
    proxy_port: Optional[int] = Field(None, ge=1024, le=65535)


class ResetTrafficResponse(BaseModel):
    """Ответ на сброс трафика."""
    success: bool
    reset_count: int


class SimpleResponse(BaseModel):
    """Простой ответ."""
    success: bool
    client: Optional[ClientInfoResponse] = None
    settings: Optional[SettingsResponse] = None


# =============================================================================
# Создание роутера
# =============================================================================

def create_proxy_router(
    account_manager: AccountManager,
    client_manager: ClientManager,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов прокси.

    Args:
        account_manager: Менеджер аккаунтов.
        client_manager: Менеджер прокси-клиентов.

    Returns:
        Настроенный APIRouter.
    """
    router = APIRouter(prefix="/api/proxy", tags=["proxy"])

    # =========================================================================
    # Вспомогательные функции
    # =========================================================================

    def get_auth_token(authorization: Optional[str] = Header(None)) -> str:
        """Извлечение токена из заголовка Authorization."""
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization header",
            )
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format",
            )
        return authorization[7:]

    def get_current_user(token: str = Depends(get_auth_token)) -> dict:
        """Получение информации о текущем пользователе."""
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return {
            "public_id": payload["sub"],
            "account_id": bytes.fromhex(payload["account_id"]),
            "is_server": payload.get("is_server", False),
        }

    def check_server_owner(current_user: dict = Depends(get_current_user)) -> dict:
        """Проверка, что пользователь является владельцем сервера."""
        if not current_user["is_server"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not_a_server_owner",
            )
        return current_user

    # =========================================================================
    # Эндпоинты
    # =========================================================================

    @router.post("/invite", response_model=InviteResponse)
    async def generate_invite(
        data: InviteRequest,
        current_user: dict = Depends(check_server_owner),
    ) -> InviteResponse:
        """
        Генерация приглашения для нового клиента.

        Доступно только владельцу сервера.
        """
        result = client_manager.generate_invite(
            client_name=data.client_name,
            expires_in=data.expires_in,
            group=data.group,
            daily_limit_mb=data.daily_limit_mb,
        )

        if not result["success"]:
            return InviteResponse(
                success=False,
                error=result.get("error"),
            )

        return InviteResponse(
            success=True,
            token=result.get("token"),
            invite_url=result.get("invite_url"),
            qr_code=result.get("qr_code"),
            expires_at=int(result["expires_at"]) if result.get("expires_at") else None,
        )

    @router.get("/clients", response_model=ClientsListResponse)
    async def get_clients(
        current_user: dict = Depends(check_server_owner),
    ) -> ClientsListResponse:
        """
        Получение списка прокси-клиентов.

        Доступно только владельцу сервера.
        """
        clients = client_manager.get_all_clients()
        settings = client_manager.get_settings()

        result = []
        for client in clients:
            result.append(ClientInfoResponse(
                client_id=client.client_id,
                public_id=client.public_id,
                name=client.name,
                group=client.group,
                connected=client.connected,
                last_seen=int(client.last_seen) if client.last_seen else None,
                traffic_today_mb=round(client.traffic_today / (1024 * 1024), 2),
                traffic_total_mb=round(client.traffic_total / (1024 * 1024), 2),
                daily_limit_mb=round(client.daily_limit / (1024 * 1024), 2) if client.daily_limit else None,
                expires_at=int(client.expires_at) if client.expires_at else None,
                created_at=int(client.created_at),
            ))

        return ClientsListResponse(
            success=True,
            clients=result,
            total_clients=len(result),
            max_clients=settings["max_clients"],
        )

    @router.get("/clients/{client_id}", response_model=ClientInfoResponse)
    async def get_client(
        client_id: str,
        current_user: dict = Depends(check_server_owner),
    ) -> ClientInfoResponse:
        """
        Получение информации о клиенте.

        Доступно только владельцу сервера.
        """
        client = client_manager.get_client(client_id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="client_not_found",
            )

        return ClientInfoResponse(
            client_id=client.client_id,
            public_id=client.public_id,
            name=client.name,
            group=client.group,
            connected=client.connected,
            last_seen=int(client.last_seen) if client.last_seen else None,
            traffic_today_mb=round(client.traffic_today / (1024 * 1024), 2),
            traffic_total_mb=round(client.traffic_total / (1024 * 1024), 2),
            daily_limit_mb=round(client.daily_limit / (1024 * 1024), 2) if client.daily_limit else None,
            expires_at=int(client.expires_at) if client.expires_at else None,
            created_at=int(client.created_at),
        )

    @router.patch("/clients/{client_id}", response_model=SimpleResponse)
    async def update_client(
        client_id: str,
        data: UpdateClientRequest,
        current_user: dict = Depends(check_server_owner),
    ) -> SimpleResponse:
        """
        Обновление настроек клиента.

        Доступно только владельцу сервера.
        """
        # Проверяем существование клиента
        client = client_manager.get_client(client_id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="client_not_found",
            )

        # Обновляем
        update_kwargs = {}
        if data.name is not None:
            update_kwargs["name"] = data.name
        if data.group is not None:
            update_kwargs["group"] = data.group
        if data.daily_limit_mb is not None:
            update_kwargs["daily_limit_mb"] = data.daily_limit_mb
        if data.expires_at is not None:
            update_kwargs["expires_at"] = float(data.expires_at)

        if update_kwargs:
            client_manager.update_client(client_id, **update_kwargs)

        # Получаем обновленного клиента
        updated = client_manager.get_client(client_id)

        return SimpleResponse(
            success=True,
            client=ClientInfoResponse(
                client_id=updated.client_id,
                public_id=updated.public_id,
                name=updated.name,
                group=updated.group,
                connected=updated.connected,
                last_seen=int(updated.last_seen) if updated.last_seen else None,
                traffic_today_mb=round(updated.traffic_today / (1024 * 1024), 2),
                traffic_total_mb=round(updated.traffic_total / (1024 * 1024), 2),
                daily_limit_mb=round(updated.daily_limit / (1024 * 1024), 2) if updated.daily_limit else None,
                expires_at=int(updated.expires_at) if updated.expires_at else None,
                created_at=int(updated.created_at),
            ),
        )

    @router.delete("/clients/{client_id}", response_model=SimpleResponse)
    async def revoke_client(
        client_id: str,
        current_user: dict = Depends(check_server_owner),
    ) -> SimpleResponse:
        """
        Отзыв доступа клиента.

        Доступно только владельцу сервера.
        """
        success = client_manager.revoke_access(client_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="client_not_found",
            )

        return SimpleResponse(success=True)

    @router.get("/stats", response_model=TrafficStatsResponse)
    async def get_stats(
        current_user: dict = Depends(check_server_owner),
    ) -> TrafficStatsResponse:
        """
        Получение статистики прокси-сервиса.

        Доступно только владельцу сервера.
        """
        stats = client_manager.get_aggregated_stats()

        return TrafficStatsResponse(
            success=True,
            total_today_mb=stats["total_today_mb"],
            total_month_mb=stats["total_today_mb"],  # В прототипе то же что и today
            total_all_mb=stats["total_all_mb"],
            active_clients=stats["active_clients"],
            total_clients=stats["total_clients"],
        )

    @router.get("/settings", response_model=SettingsResponse)
    async def get_settings(
        current_user: dict = Depends(check_server_owner),
    ) -> SettingsResponse:
        """
        Получение настроек прокси-сервиса.

        Доступно только владельцу сервера.
        """
        settings = client_manager.get_settings()

        # Получаем порт из client_manager или используем значение по умолчанию
        proxy_port = getattr(client_manager, 'proxy_port', 9879)

        return SettingsResponse(
            success=True,
            max_clients=settings["max_clients"],
            default_daily_limit_mb=settings["default_daily_limit_mb"],
            default_group=settings["default_group"],
            proxy_enabled=settings["proxy_enabled"],
            proxy_port=proxy_port,
        )

    @router.patch("/settings", response_model=SettingsResponse)
    async def update_settings(
        data: UpdateSettingsRequest,
        current_user: dict = Depends(check_server_owner),
    ) -> SettingsResponse:
        """
        Обновление настроек прокси-сервиса.

        Доступно только владельцу сервера.
        """
        update_kwargs = {}
        if data.max_clients is not None:
            update_kwargs["max_clients"] = data.max_clients
        if data.default_daily_limit_mb is not None:
            update_kwargs["default_daily_limit_mb"] = data.default_daily_limit_mb
        if data.default_group is not None:
            update_kwargs["default_group"] = data.default_group
        if data.proxy_enabled is not None:
            update_kwargs["proxy_enabled"] = data.proxy_enabled

        if update_kwargs:
            client_manager.update_settings(**update_kwargs)

        settings = client_manager.get_settings()

        # Обновляем порт если передан
        if data.proxy_port is not None:
            client_manager.proxy_port = data.proxy_port

        proxy_port = getattr(client_manager, 'proxy_port', 9879)

        return SettingsResponse(
            success=True,
            max_clients=settings["max_clients"],
            default_daily_limit_mb=settings["default_daily_limit_mb"],
            default_group=settings["default_group"],
            proxy_enabled=settings["proxy_enabled"],
            proxy_port=proxy_port,
        )

    @router.post("/reset-traffic", response_model=ResetTrafficResponse)
    async def reset_traffic(
        current_user: dict = Depends(check_server_owner),
    ) -> ResetTrafficResponse:
        """
        Сброс дневного трафика всех клиентов (принудительно).

        Доступно только владельцу сервера.
        """
        count = client_manager.reset_daily_traffic()

        return ResetTrafficResponse(
            success=True,
            reset_count=count,
        )

    return router
