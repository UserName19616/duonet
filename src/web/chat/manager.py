# src/web/chat/manager.py
"""
Менеджер WebSocket соединений для чата.
"""

import asyncio
import logging
import time
from typing import Dict, Optional

from src.server.api.websocket import WebSocketManager, get_ws_manager

logger = logging.getLogger(__name__)


class ChatConnectionManager:
    """
    Менеджер WebSocket соединений для чата.

    Управляет соединениями между конкретными парами пользователей,
    статусами печатает и дополнительными фразами.
    """

    def __init__(self):
        self._connections: Dict[str, Dict[str, any]] = {}  # user_id -> {contact_id -> websocket}
        self._typing_status: Dict[str, Dict[str, float]] = {}  # user_id -> {contact_id -> timestamp}
        self._phrases: Dict[str, Dict[str, str]] = {}  # user_id -> {contact_id -> phrase}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, contact_id: str, websocket) -> None:
        """
        Добавление WebSocket соединения.

        Args:
            user_id: Public ID пользователя
            contact_id: Public ID контакта
            websocket: WebSocket соединение
        """
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = {}
            self._connections[user_id][contact_id] = websocket
            logger.debug(f"Chat WebSocket connected: {user_id} <-> {contact_id}")

    async def disconnect(self, user_id: str, contact_id: str) -> None:
        """
        Удаление WebSocket соединения.

        Args:
            user_id: Public ID пользователя
            contact_id: Public ID контакта
        """
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].pop(contact_id, None)
                if not self._connections[user_id]:
                    del self._connections[user_id]
            logger.debug(f"Chat WebSocket disconnected: {user_id} <-> {contact_id}")

    async def send_to_user(self, user_id: str, contact_id: str, message: dict) -> bool:
        """
        Отправка сообщения конкретному пользователю.

        Args:
            user_id: Public ID получателя
            contact_id: Public ID отправителя (для поиска соединения)
            message: Сообщение для отправки

        Returns:
            True если отправлено успешно
        """
        async with self._lock:
            if user_id in self._connections and contact_id in self._connections[user_id]:
                try:
                    await self._connections[user_id][contact_id].send_json(message)
                    return True
                except Exception as e:
                    logger.error(f"Failed to send message to {user_id}: {e}")
                    return False
            return False

    async def broadcast_typing(self, from_id: str, to_id: str, is_typing: bool) -> None:
        """
        Рассылка статуса печатает.

        Args:
            from_id: Public ID отправителя
            to_id: Public ID получателя
            is_typing: Статус печатает
        """
        await self.send_to_user(to_id, from_id, {
            "type": "typing",
            "data": {"from": from_id, "is_typing": is_typing},
        })

    async def set_typing(self, from_id: str, to_id: str) -> None:
        """
        Установка статуса печатает с автоматическим сбросом через 3 секунды.

        Args:
            from_id: Public ID отправителя
            to_id: Public ID получателя
        """
        async with self._lock:
            if from_id not in self._typing_status:
                self._typing_status[from_id] = {}
            self._typing_status[from_id][to_id] = time.time()

        await self.broadcast_typing(from_id, to_id, True)

        async def clear_typing():
            await asyncio.sleep(3)
            async with self._lock:
                if (from_id in self._typing_status and
                    to_id in self._typing_status[from_id] and
                    time.time() - self._typing_status[from_id][to_id] >= 3):
                    del self._typing_status[from_id][to_id]
            await self.broadcast_typing(from_id, to_id, False)

        asyncio.create_task(clear_typing())

    def set_phrase(self, user_id: str, contact_id: str, phrase: str) -> None:
        """
        Сохранение дополнительной фразы для контакта.

        Args:
            user_id: Public ID пользователя
            contact_id: Public ID контакта
            phrase: Дополнительная фраза
        """
        if user_id not in self._phrases:
            self._phrases[user_id] = {}
        self._phrases[user_id][contact_id] = phrase
        logger.debug(f"Phrase set for {user_id} <-> {contact_id}")

    def get_phrase(self, user_id: str, contact_id: str) -> Optional[str]:
        """
        Получение дополнительной фразы для контакта.

        Args:
            user_id: Public ID пользователя
            contact_id: Public ID контакта

        Returns:
            Дополнительная фраза или None
        """
        return self._phrases.get(user_id, {}).get(contact_id)

    def clear_phrase(self, user_id: str, contact_id: str) -> None:
        """
        Удаление дополнительной фразы для контакта.

        Args:
            user_id: Public ID пользователя
            contact_id: Public ID контакта
        """
        if user_id in self._phrases:
            self._phrases[user_id].pop(contact_id, None)
            logger.debug(f"Phrase cleared for {user_id} <-> {contact_id}")

    async def register_with_global_manager(self, user_id: str, websocket, client_ip: str) -> None:
        """
        Регистрация соединения в глобальном WebSocketManager для online статуса.

        Args:
            user_id: Public ID пользователя
            websocket: WebSocket соединение
            client_ip: IP клиента
        """
        ws_manager = get_ws_manager()
        if ws_manager is None:
            from src.server.api.websocket import WebSocketManager, set_ws_manager
            ws_manager = WebSocketManager()
            set_ws_manager(ws_manager)
            logger.warning("Created temporary WebSocketManager")

        await ws_manager.add_connection(
            websocket=websocket,
            public_id=user_id,
            client_ip=client_ip
        )
        logger.info(f"Chat connection registered in global manager: {user_id}")

    async def unregister_from_global_manager(self, user_id: str) -> None:
        """
        Удаление соединения из глобального WebSocketManager.

        Args:
            user_id: Public ID пользователя
        """
        ws_manager = get_ws_manager()
        if ws_manager:
            await ws_manager.remove_connection(user_id)
            logger.info(f"Chat connection unregistered from global manager: {user_id}")


# Глобальный экземпляр менеджера чата
_chat_manager: Optional[ChatConnectionManager] = None


def get_chat_manager() -> ChatConnectionManager:
    """Получение глобального экземпляра ChatConnectionManager."""
    global _chat_manager
    if _chat_manager is None:
        _chat_manager = ChatConnectionManager()
    return _chat_manager
