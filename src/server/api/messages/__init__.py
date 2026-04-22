# src/server/api/messages/__init__.py
"""
Модуль API сообщений.

Содержит эндпоинты для отправки, получения, удаления сообщений.
(Ротация ключей обрабатывается на клиенте, сервер не участвует)
"""

from fastapi import APIRouter

from .endpoints_main import create_main_endpoints
from .endpoints_status import create_status_endpoints
from .endpoints_delete import create_delete_endpoints


def create_messages_router(account_manager, message_router) -> APIRouter:
    """
    Создание роутера для эндпоинтов сообщений.

    Args:
        account_manager: Менеджер аккаунтов.
        message_router: Маршрутизатор сообщений.

    Returns:
        Настроенный APIRouter.
    """
    router = APIRouter(prefix="/api/messages", tags=["messages"])

    router.include_router(create_main_endpoints(account_manager, message_router))
    router.include_router(create_status_endpoints(account_manager, message_router))
    router.include_router(create_delete_endpoints(account_manager, message_router))

    return router
