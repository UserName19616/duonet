# src/api/messages/endpoints_status.py
"""
Эндпоинты для управления статусами сообщений:
- delivered — подтверждение доставки
- read — подтверждение прочтения
- read-all — отметить все сообщения как прочитанные
- unread — количество непрочитанных сообщений
"""

import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.common.identity.account import AccountManager
from src.common.identity.public_id import is_valid_format
from src.client.messaging.message_router import MessageRouter
from .models import MarkRequest, ReadAllResponse, UnreadResponse
from .deps import create_dependencies

logger = logging.getLogger(__name__)


def create_status_endpoints(
    account_manager: AccountManager,
    message_router: MessageRouter,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов статусов сообщений.

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

    @router.post("/delivered", response_model=dict)
    async def mark_delivered(
        data: MarkRequest,
        current_public_id: str = Depends(get_current_public_id),
    ) -> dict:
        """Подтверждение доставки сообщения."""
        success = message_router.mark_delivered(data.message_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="message_not_found",
            )

        return {"success": True}

    @router.post("/read", response_model=dict)
    async def mark_read(
        data: MarkRequest,
        current_public_id: str = Depends(get_current_public_id),
    ) -> dict:
        """Подтверждение прочтения сообщения."""
        success = message_router.mark_read(data.message_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="message_not_found",
            )

        return {"success": True}

    @router.post("/read-all/{contact_id}", response_model=ReadAllResponse)
    async def mark_all_read(
        contact_id: str,
        current_public_id: str = Depends(get_current_public_id),
        current_account_id: bytes = Depends(get_current_account_id),
    ) -> ReadAllResponse:
        """Отметить все сообщения от контакта как прочитанные."""
        if not is_valid_format(contact_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_contact_id",
            )

        count = message_router.mark_all_read(current_public_id, contact_id)

        return ReadAllResponse(success=True, count=count)

    @router.get("/unread", response_model=UnreadResponse)
    async def get_unread_count(
        contact_id: Optional[str] = Query(None),
        current_public_id: str = Depends(get_current_public_id),
        current_account_id: bytes = Depends(get_current_account_id),
    ) -> UnreadResponse:
        """Количество непрочитанных сообщений."""
        count = message_router.get_unread_count(current_public_id, contact_id)

        return UnreadResponse(success=True, count=count)

    return router
