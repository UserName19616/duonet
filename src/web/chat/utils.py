# src/web/chat/utils.py
"""
Вспомогательные функции для веб-чата.
"""

import os
import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from src.common.identity.account import AccountManager

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


def render_template_safe(templates: Jinja2Templates, name: str, context: dict) -> HTMLResponse:
    """
    Безопасный рендеринг шаблона без использования кэша.

    Args:
        templates: Jinja2Templates объект
        name: Имя шаблона
        context: Контекст для рендеринга

    Returns:
        HTMLResponse
    """
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        auto_reload=True,
        cache_size=0
    )
    env.cache = {}

    template = env.get_template(name)
    content = template.render(**context)
    return HTMLResponse(content=content)


def get_client_ip(request: Request) -> str:
    """
    Получение реального IP клиента.

    Args:
        request: FastAPI Request объект

    Returns:
        IP адрес
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def generate_message_id() -> str:
    """
    Генерация уникального ID сообщения.

    Returns:
        message_id в формате msg_ + 16 hex символов
    """
    import secrets
    return "msg_" + secrets.token_hex(8)


def generate_system_message_id(system_type: str) -> str:
    """
    Генерация уникального ID системного сообщения.

    Args:
        system_type: Тип системного сообщения

    Returns:
        system_message_id в формате sys_{type}_{timestamp}_{random}
    """
    import secrets
    import time
    return f"sys_{system_type}_{int(time.time())}_{secrets.token_hex(4)}"
