# src/api/messages/endpoints_main.py
"""
Основные эндпоинты для работы с сообщениями:
- send — отправка сообщения
- poll — получение новых сообщений
- history — история сообщений с контактом
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.config import MAX_TEXT_LENGTH, MAX_FILE_SIZE_BYTES
from src.common.identity.account import AccountManager
from src.common.identity.public_id import is_client_id, is_server_id, is_valid_format
from src.client.messaging.message_router import MessageRouter
from .models import (
    SendMessageRequest,
    SendMessageResponse,
    PollResponse,
    MessageResponse,
)
from .deps import create_dependencies

logger = logging.getLogger(__name__)


def create_main_endpoints(
    account_manager: AccountManager,
    message_router: MessageRouter,
) -> APIRouter:
    """
    Создание роутера для основных эндпоинтов сообщений.

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
    # Вспомогательная функция для получения фразы из кэша
    # =========================================================================
    def get_phrase_from_cache(user_id: str, contact_id: str) -> Optional[str]:
        """
        Получение дополнительной фразы из кэша.
        В реальной реализации фраза хранится в сессии или localStorage.
        """
        return None

    # =========================================================================
    # Эндпоинты
    # =========================================================================

    @router.post("/send", response_model=SendMessageResponse)
    async def send_message(
        data: SendMessageRequest,
        current_public_id: str = Depends(get_current_public_id),
        current_account_id: bytes = Depends(get_current_account_id),
    ) -> SendMessageResponse:
        """Отправка сообщения."""
        to_id = data.to

        if not is_valid_format(to_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_recipient_id",
            )

        if not data.is_file and data.text_length is not None:
            if data.text_length > MAX_TEXT_LENGTH:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Text message too long (max {MAX_TEXT_LENGTH} chars)",
                )

        if data.is_file and data.file_size is not None:
            if data.file_size > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)} MB)",
                )

        if is_server_id(to_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot_send_to_server",
            )

        if not is_client_id(to_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_recipient_id",
            )

        try:
            encrypted_bytes = bytes.fromhex(data.encrypted)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_encrypted_format",
            )

        try:
            session_key_bytes = bytes.fromhex(data.session_key)
            if len(session_key_bytes) != 32:
                raise ValueError()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_session_key_format",
            )

        phrase = None
        if data.has_phrase:
            phrase = get_phrase_from_cache(current_public_id, to_id)
            if not phrase:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="phrase_required",
                )

        result = message_router.send_encrypted_message(
            from_id=current_public_id,
            to_id=to_id,
            encrypted_hex=data.encrypted,
            session_key=session_key_bytes,
            has_phrase=data.has_phrase,
            phrase=phrase,
            plaintext_len=data.plaintext_len,
            prev_padding=data.prev_padding,
            message_counter=data.message_counter,
        )

        if not result.get("success", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "send_failed"),
            )

        return SendMessageResponse(
            success=True,
            message_id=result.get("message_id"),
            timestamp=result.get("timestamp"),
            padding_size=result.get("padding_size"),
            key_index=result.get("key_index"),
        )

    @router.get("/poll", response_model=PollResponse)
    async def poll_messages(
        since: Optional[int] = Query(None, ge=0),
        limit: int = Query(100, ge=1, le=500),
        current_public_id: str = Depends(get_current_public_id),
        current_account_id: bytes = Depends(get_current_account_id),
    ) -> PollResponse:
        """Получение новых сообщений (polling)."""
        messages = message_router.get_messages(
            user_id=current_public_id,
            limit=limit,
        )

        if since is not None:
            messages = [m for m in messages if m["timestamp"] > since]

        return PollResponse(
            success=True,
            messages=[
                MessageResponse(
                    id=m["id"],
                    from_id=m["from_id"],
                    encrypted=m["encrypted"],
                    session_key=m["session_key"],
                    timestamp=m["timestamp"],
                    has_phrase=m["has_phrase"],
                    delivered=m["delivered"],
                    read=m["read"],
                    padding_size=m.get("padding_size"),
                    key_index=m.get("key_index"),
                    flags=m.get("flags"),
                    is_system=m.get("is_system", 0),
                    system_type=m.get("system_type"),
                    system_data=m.get("system_data"),
                )
                for m in messages
            ],
        )

    @router.get("/history/{contact_id}", response_model=PollResponse)
    async def get_message_history(
        contact_id: str,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        current_public_id: str = Depends(get_current_public_id),
        current_account_id: bytes = Depends(get_current_account_id),
    ) -> PollResponse:
        """Получение полной истории сообщений с контактом."""
        if not is_valid_format(contact_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_contact_id",
            )

        messages = message_router.get_messages(
            user_id=current_public_id,
            contact_id=contact_id,
            limit=limit,
            offset=offset,
        )

        messages.sort(key=lambda m: m["timestamp"])

        return PollResponse(
            success=True,
            messages=[
                MessageResponse(
                    id=m["id"],
                    from_id=m["from_id"],
                    encrypted=m["encrypted"],
                    session_key=m["session_key"],
                    timestamp=m["timestamp"],
                    has_phrase=m["has_phrase"],
                    delivered=m["delivered"],
                    read=m["read"],
                    padding_size=m.get("padding_size"),
                    key_index=m.get("key_index"),
                    flags=m.get("flags"),
                    is_system=m.get("is_system", 0),
                    system_type=m.get("system_type"),
                    system_data=m.get("system_data"),
                )
                for m in messages
            ],
        )

    return router
