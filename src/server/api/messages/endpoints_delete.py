# src/api/messages/endpoints_delete.py
"""
Эндпоинты для удаления сообщений:
- delete — удаление одного сообщения
- conversation — удаление всей переписки с контактом
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from src.common.identity.account import AccountManager
from src.common.identity.public_id import is_valid_format
from src.client.messaging.message_router import MessageRouter
from .models import ReadAllResponse
from .deps import create_dependencies

logger = logging.getLogger(__name__)


def create_delete_endpoints(
    account_manager: AccountManager,
    message_router: MessageRouter,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов удаления сообщений.

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

    @router.delete("/{message_id}", response_model=dict)
    async def delete_message(
        message_id: str,
        current_public_id: str = Depends(get_current_public_id),
    ) -> dict:
        """Удаление сообщения."""
        success = message_router.delete_message(message_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="message_not_found",
            )

        return {"success": True}

    @router.delete("/conversation/{contact_id}", response_model=ReadAllResponse)
    async def delete_conversation(
        contact_id: str,
        current_public_id: str = Depends(get_current_public_id),
        current_account_id: bytes = Depends(get_current_account_id),
    ) -> ReadAllResponse:
        """Удаление всех сообщений с контактом."""
        if not is_valid_format(contact_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_contact_id",
            )

        count = message_router.delete_conversation(current_public_id, contact_id)

        return ReadAllResponse(success=True, count=count)

    return router
