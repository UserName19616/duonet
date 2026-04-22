# src/api/messages/system_endpoints.py
"""
Эндпоинты для системных сообщений:
- system — сохранение системного сообщения
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.common.identity.account import AccountManager
from src.client.messaging.message_router import MessageRouter
from .models import SystemMessageRequest
from .deps import create_dependencies

logger = logging.getLogger(__name__)


def create_system_endpoints(
    account_manager: AccountManager,
    message_router: MessageRouter,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов системных сообщений.

    Args:
        account_manager: Менеджер аккаунтов.
        message_router: Маршрутизатор сообщений.

    Returns:
        Настроенный APIRouter.
    """
    router = APIRouter()

    # Создаём зависимости
    get_current_public_id, get_current_account_id = create_dependencies(account_manager)

    # =========================================================================
    # Эндпоинты
    # =========================================================================

    @router.post("/system", response_model=dict)
    async def save_system_message(
        data: SystemMessageRequest,
        current_public_id: str = Depends(get_current_public_id),
    ) -> dict:
        """Сохранение системного сообщения (о смене ключа, и т.д.)"""
        if data.from_id != current_public_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot send system message on behalf of another user",
            )

        try:
            import sqlite3
            conn = sqlite3.connect("duonet.db")
            conn.execute("""
                INSERT OR REPLACE INTO messages
                (id, from_id, to_id, encrypted, session_key, timestamp, delivered, read, direction,
                 is_system, system_type, system_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.id, data.from_id, data.to_id, "", "", data.timestamp,
                1, 1, "system", data.is_system, data.system_type, data.system_data
            ))
            conn.commit()
            conn.close()
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to save system message: {e}")
            return {"success": False, "error": str(e)}

    return router
