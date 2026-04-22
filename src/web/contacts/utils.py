# src/web/contacts/utils.py
"""
Вспомогательные функции для веб-контактов.
"""

import logging
from typing import Optional

from fastapi import Request, HTTPException, status

from src.common.identity.account import AccountManager
from src.client.storage.contacts import ContactsStorage
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


def get_current_user(request: Request, account_manager: AccountManager) -> Optional[dict]:
    """
    Получение текущего пользователя из cookie.

    Args:
        request: FastAPI Request объект
        account_manager: Менеджер аккаунтов

    Returns:
        Информация о пользователе или None
    """
    token = request.cookies.get("token")
    if not token:
        return None

    payload = account_manager.verify_token(token)
    if not payload:
        return None

    account_id_hex = payload.get("account_id", "")
    return {
        "public_id": payload["sub"],
        "account_id": bytes.fromhex(account_id_hex) if account_id_hex else None,
        "is_server": payload.get("is_server", False),
    }


def get_current_user_dep(request: Request, account_manager: AccountManager) -> dict:
    """
    Dependency для получения текущего пользователя (с проверкой авторизации).

    Args:
        request: FastAPI Request объект
        account_manager: Менеджер аккаунтов

    Returns:
        Информация о пользователе

    Raises:
        HTTPException: Если пользователь не авторизован
    """
    user = get_current_user(request, account_manager)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def get_user_contacts_storage(user_id: bytes, storage: SQLiteStorage) -> ContactsStorage:
    """
    Получение хранилища контактов для пользователя.

    Args:
        user_id: ID пользователя (20 байт)
        storage: Хранилище SQLite

    Returns:
        ContactsStorage для пользователя
    """
    return ContactsStorage(storage, user_id)


def escape_html(text: str) -> str:
    """
    Экранирование HTML символов.

    Args:
        text: Исходный текст

    Returns:
        Текст с экранированными HTML символами
    """
    if not text:
        return ""
    html_escape_table = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
        ">": "&gt;",
        "<": "&lt;",
    }
    return "".join(html_escape_table.get(c, c) for c in text)


def validate_public_id(public_id: str) -> bool:
    """
    Проверка валидности Public ID.

    Args:
        public_id: Public ID для проверки

    Returns:
        True если формат корректен
    """
    from src.common.identity.public_id import is_valid_format
    return is_valid_format(public_id)


def validate_contact_name(name: str) -> bool:
    """
    Проверка валидности имени контакта.

    Args:
        name: Имя для проверки

    Returns:
        True если имя корректно (1-64 символа, не пустое)
    """
    if not name or not name.strip():
        return False
    if len(name) > 64:
        return False
    return True
