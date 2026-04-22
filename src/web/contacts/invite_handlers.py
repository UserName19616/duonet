# src/web/contacts/invite_handlers.py
"""
Обработчики приглашений для веб-контактов.
"""

import logging
from typing import Optional

from fastapi import HTTPException, status

from src.common.identity.account import AccountManager
from src.client.messaging.invite import InviteProtocol
from src.client.messaging.spam_protection import SpamProtection
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


async def send_invite(
    from_id: str,
    to_id: str,
    message: str,
    account_manager: AccountManager,
    invite_protocol: InviteProtocol,
    spam_protection: SpamProtection,
    rendezvous_client: RendezvousClient,
) -> dict:
    """
    Отправка приглашения.

    Args:
        from_id: Public ID отправителя
        to_id: Public ID получателя
        message: Текст приглашения
        account_manager: Менеджер аккаунтов
        invite_protocol: Протокол приглашений
        spam_protection: Защита от спама
        rendezvous_client: Клиент сервера знакомств

    Returns:
        Результат отправки

    Raises:
        HTTPException: При ошибке
    """
    # Проверяем, не заблокирован ли отправитель
    if spam_protection.is_blocked(from_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sender_blocked",
        )

    # Проверяем лимит приглашений
    remaining = spam_protection.get_remaining_invites(from_id)
    if remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="invite_limit_reached",
        )

    # Получаем приватный ключ из сессии
    private_key = account_manager.get_session_private_key(from_id)
    if private_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_expired",
        )

    def get_public_key(public_id: str) -> Optional[bytes]:
        return account_manager.get_public_key_by_id(public_id)

    # Отправляем приглашение
    result = invite_protocol.send_invite(
        from_id=from_id,
        to_id=to_id,
        message=message,
        private_key=private_key,
        get_public_key_func=get_public_key,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "invite_failed"),
        )

    return {"invite_id": result["invite_id"]}


async def accept_invite(
    invite_id: str,
    accepter_id: str,
    account_manager: AccountManager,
    invite_protocol: InviteProtocol,
) -> dict:
    """
    Принятие приглашения.

    Args:
        invite_id: ID приглашения
        accepter_id: Public ID принимающего
        account_manager: Менеджер аккаунтов
        invite_protocol: Протокол приглашений

    Returns:
        Результат принятия

    Raises:
        HTTPException: При ошибке
    """
    # Получаем приватный ключ из сессии
    private_key = account_manager.get_session_private_key(accepter_id)
    if private_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_expired",
        )

    result = invite_protocol.accept_invite(
        invite_id=invite_id,
        accepter_id=accepter_id,
        private_key=private_key,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "accept_failed"),
        )

    return {
        "dialog_id": result.get("dialog_id"),
        "peer_id": result.get("peer_id"),
        "session_key": result.get("session_key"),
    }


async def reject_invite(
    invite_id: str,
    rejecter_id: str,
    invite_protocol: InviteProtocol,
) -> dict:
    """
    Отклонение приглашения.

    Args:
        invite_id: ID приглашения
        rejecter_id: Public ID отклоняющего
        invite_protocol: Протокол приглашений

    Returns:
        Результат отклонения

    Raises:
        HTTPException: При ошибке
    """
    result = invite_protocol.reject_invite(invite_id, rejecter_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "reject_failed"),
        )

    return {"success": True}


async def revoke_invite(
    invite_id: str,
    from_id: str,
    invite_protocol: InviteProtocol,
) -> dict:
    """
    Отзыв отправленного приглашения.

    Args:
        invite_id: ID приглашения
        from_id: Public ID отправителя
        invite_protocol: Протокол приглашений

    Returns:
        Результат отзыва

    Raises:
        HTTPException: При ошибке
    """
    result = invite_protocol.revoke_invite(invite_id, from_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "revoke_failed"),
        )

    return {"success": True}
