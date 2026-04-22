# src/client/messaging/system_messages.py
"""
Обработчик системных сообщений для протокола ротации ключей V3.
Статусы: REQUEST, ACCEPT, CONFIRM, COMPLETE, REJECT, TIMEOUT
"""

import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

from src.client.storage.messages import MessagesStorage, MessageInfo
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

# Статусы ротации (дублируем для независимости)
ROTATION_STATUS_REQUEST = "REQUEST"
ROTATION_STATUS_ACCEPT = "ACCEPT"
ROTATION_STATUS_CONFIRM = "CONFIRM"
ROTATION_STATUS_COMPLETE = "COMPLETE"
ROTATION_STATUS_REJECT = "REJECT"
ROTATION_STATUS_TIMEOUT = "TIMEOUT"


class SystemMessageHandler:
    """
    Обработчик системных сообщений для ротации ключей V3.
    """

    def __init__(
        self,
        rotation_manager,
        messages_storage: MessagesStorage,
        storage: Optional[SQLiteStorage] = None,
    ):
        self._rotation_manager = rotation_manager
        self._messages_storage = messages_storage
        self._storage = storage
        self._processed_messages: set = set()

    def _get_dialog_id(self, user_id: str, contact_id: str) -> str:
        """Возвращает ID диалога (лексикографический порядок)."""
        return f"{user_id}:{contact_id}" if user_id < contact_id else f"{contact_id}:{user_id}"

    def _save_system_message(
        self,
        from_id: str,
        to_id: str,
        system_type: str,
        system_data: Dict[str, Any],
        timestamp: Optional[int] = None,
    ) -> str:
        """Сохранение системного сообщения."""
        if timestamp is None:
            timestamp = int(time.time())

        # Формируем ID сообщения: sys_{rotation_id}_{status}
        rotation_id = system_data.get("rotation_id", "")
        message_id = f"sys_{rotation_id}_{system_type}" if rotation_id else f"sys_{system_type}_{timestamp}_{secrets.token_hex(4)}"

        msg = MessageInfo(
            id=message_id,
            from_id=from_id,
            to_id=to_id,
            session_key="",
            encrypted="",
            timestamp=timestamp,
            delivered=True,
            read=True,
            has_phrase=False,
            direction="system",
            is_system=1,
            system_type=system_type,
            system_data=json.dumps(system_data),
        )
        self._messages_storage.save(msg)

        if self._storage:
            self._storage.save_system_message(
                msg_id=message_id,
                from_id=from_id,
                to_id=to_id,
                timestamp=timestamp,
                system_type=system_type,
                system_data=json.dumps(system_data),
            )

        return message_id

    def _is_duplicate(self, message_id: str) -> bool:
        """Проверка, не обрабатывалось ли уже это сообщение."""
        if message_id in self._processed_messages:
            return True
        self._processed_messages.add(message_id)

        # Очистка старых ID (храним не более 100)
        if len(self._processed_messages) > 100:
            old = list(self._processed_messages)[:50]
            for old_id in old:
                self._processed_messages.discard(old_id)

        return False

    def handle(
        self,
        from_id: str,
        to_id: str,
        system_type: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка входящего системного сообщения.

        Args:
            from_id: Отправитель
            to_id: Получатель (текущий пользователь)
            system_type: Тип системного сообщения
            system_data: Данные сообщения (должны содержать rotation_id)
            timestamp: Время получения
            current_session_key: Текущий активный ключ диалога

        Returns:
            Результат обработки
        """
        rotation_id = system_data.get("rotation_id")
        if not rotation_id:
            logger.warning(f"System message without rotation_id: {system_type}")
            return {"success": False, "error": "missing_rotation_id"}

        # Защита от дубликатов
        msg_id = f"{rotation_id}_{system_type}"
        if self._is_duplicate(msg_id):
            logger.info(f"Duplicate system message {msg_id}, ignoring")
            return {"success": True, "action": "duplicate_ignored"}

        logger.info(f"Handling system message: {system_type} rotation_id={rotation_id} from {from_id} to {to_id}")

        if system_type == ROTATION_STATUS_REQUEST:
            return self._handle_request(from_id, to_id, system_data, timestamp, current_session_key)
        elif system_type == ROTATION_STATUS_ACCEPT:
            return self._handle_accept(from_id, to_id, system_data, timestamp, current_session_key)
        elif system_type == ROTATION_STATUS_CONFIRM:
            return self._handle_confirm(from_id, to_id, system_data, timestamp, current_session_key)
        elif system_type == ROTATION_STATUS_COMPLETE:
            return self._handle_complete(from_id, to_id, system_data, timestamp, current_session_key)
        elif system_type == ROTATION_STATUS_REJECT:
            return self._handle_reject(from_id, to_id, system_data, timestamp, current_session_key)
        elif system_type == ROTATION_STATUS_TIMEOUT:
            return self._handle_timeout(from_id, to_id, system_data, timestamp, current_session_key)
        else:
            logger.warning(f"Unknown system message type: {system_type}")
            return {"success": False, "error": f"unknown_type_{system_type}"}

    def _handle_request(
        self,
        from_id: str,
        to_id: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка REQUEST (шаг 2: получатель видит запрос).

        Возвращает action="pending_waiting_user" — UI должен показать кнопки.
        """
        rotation_id = system_data.get("rotation_id")
        eph_public_key = system_data.get("eph_public_key")
        expires_at = system_data.get("expires_at", timestamp + 86400)

        if not rotation_id or not eph_public_key:
            return {"success": False, "error": "missing_fields"}

        result = self._rotation_manager.process_rotation_request(
            from_id=from_id,
            to_id=to_id,
            rotation_id=rotation_id,
            eph_public_key_hex=eph_public_key,
            timestamp=timestamp,
            expires_at=expires_at,
            current_session_key=current_session_key,
        )

        if not result.get("success"):
            return result

        return {
            "success": True,
            "rotation_id": rotation_id,
            "action": "pending_waiting_user",
            "expires_at": expires_at,
        }

    def _handle_accept(
        self,
        from_id: str,
        to_id: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка ACCEPT (шаг 3: инициатор получает accept).

        Инициатор вычисляет общий ключ и отправляет CONFIRM.
        """
        rotation_id = system_data.get("rotation_id")
        eph_public_key = system_data.get("eph_public_key")

        if not rotation_id or not eph_public_key:
            return {"success": False, "error": "missing_fields"}

        result = self._rotation_manager.confirm_key_rotation(
            user_id=to_id,
            contact_id=from_id,
            rotation_id=rotation_id,
            eph_public_key_hex=eph_public_key,
        )

        if not result.get("success"):
            return result

        # Отправляем CONFIRM обратно
        self.send_rotation_confirm(
            from_id=to_id,
            to_id=from_id,
            rotation_id=rotation_id,
        )

        return {
            "success": True,
            "rotation_id": rotation_id,
            "action": "rotation_confirmed",
        }

    def _handle_confirm(
        self,
        from_id: str,
        to_id: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка CONFIRM (шаг 4: получатель завершает).

        Получатель активирует ключ и отправляет COMPLETE.
        """
        rotation_id = system_data.get("rotation_id")

        if not rotation_id:
            return {"success": False, "error": "missing_rotation_id"}

        result = self._rotation_manager.complete_key_rotation(
            user_id=to_id,
            contact_id=from_id,
            rotation_id=rotation_id,
        )

        if not result.get("success"):
            return result

        # Отправляем COMPLETE обратно
        self.send_rotation_complete(
            from_id=to_id,
            to_id=from_id,
            rotation_id=rotation_id,
        )

        return {
            "success": True,
            "rotation_id": rotation_id,
            "action": "rotation_completed",
        }

    def _handle_complete(
        self,
        from_id: str,
        to_id: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка COMPLETE (финальное подтверждение).

        Инициатор просто отмечает ротацию как завершённую.
        """
        rotation_id = system_data.get("rotation_id")

        if not rotation_id:
            return {"success": False, "error": "missing_rotation_id"}

        # Отмечаем ротацию как завершённую у инициатора
        result = self._rotation_manager.complete_key_rotation(
            user_id=to_id,
            contact_id=from_id,
            rotation_id=rotation_id,
        )

        return {
            "success": True,
            "rotation_id": rotation_id,
            "action": "complete_received",
        }

    def _handle_reject(
        self,
        from_id: str,
        to_id: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка REJECT (отказ).
        """
        rotation_id = system_data.get("rotation_id")

        if not rotation_id:
            return {"success": False, "error": "missing_rotation_id"}

        result = self._rotation_manager.reject_key_rotation(
            user_id=to_id,
            contact_id=from_id,
            rotation_id=rotation_id,
        )

        return {
            "success": True,
            "rotation_id": rotation_id,
            "action": "rotation_rejected",
        }

    def _handle_timeout(
        self,
        from_id: str,
        to_id: str,
        system_data: Dict[str, Any],
        timestamp: int,
        current_session_key: bytes,
    ) -> Dict[str, Any]:
        """
        Обработка TIMEOUT (уведомление об истечении).
        """
        rotation_id = system_data.get("rotation_id")

        if not rotation_id:
            return {"success": False, "error": "missing_rotation_id"}

        result = self._rotation_manager.timeout_key_rotation(
            user_id=to_id,
            contact_id=from_id,
            rotation_id=rotation_id,
        )

        return {
            "success": True,
            "rotation_id": rotation_id,
            "action": "timeout_processed",
        }

    # =========================================================================
    # Методы отправки системных сообщений
    # =========================================================================

    def send_rotation_request(
        self,
        from_id: str,
        to_id: str,
        rotation_id: str,
        eph_public_key_hex: str,
        expires_at: int,
    ) -> str:
        """
        Отправка REQUEST.
        """
        system_data = {
            "rotation_id": rotation_id,
            "eph_public_key": eph_public_key_hex,
            "timestamp": int(time.time()),
            "expires_at": expires_at,
        }
        return self._save_system_message(
            from_id=from_id,
            to_id=to_id,
            system_type=ROTATION_STATUS_REQUEST,
            system_data=system_data,
        )

    def send_rotation_accept(
        self,
        from_id: str,
        to_id: str,
        rotation_id: str,
        eph_public_key_hex: str,
    ) -> str:
        """
        Отправка ACCEPT.
        """
        system_data = {
            "rotation_id": rotation_id,
            "eph_public_key": eph_public_key_hex,
            "timestamp": int(time.time()),
        }
        return self._save_system_message(
            from_id=from_id,
            to_id=to_id,
            system_type=ROTATION_STATUS_ACCEPT,
            system_data=system_data,
        )

    def send_rotation_confirm(
        self,
        from_id: str,
        to_id: str,
        rotation_id: str,
    ) -> str:
        """
        Отправка CONFIRM.
        """
        system_data = {
            "rotation_id": rotation_id,
            "timestamp": int(time.time()),
        }
        return self._save_system_message(
            from_id=from_id,
            to_id=to_id,
            system_type=ROTATION_STATUS_CONFIRM,
            system_data=system_data,
        )

    def send_rotation_complete(
        self,
        from_id: str,
        to_id: str,
        rotation_id: str,
    ) -> str:
        """
        Отправка COMPLETE.
        """
        system_data = {
            "rotation_id": rotation_id,
            "timestamp": int(time.time()),
        }
        return self._save_system_message(
            from_id=from_id,
            to_id=to_id,
            system_type=ROTATION_STATUS_COMPLETE,
            system_data=system_data,
        )

    def send_rotation_reject(
        self,
        from_id: str,
        to_id: str,
        rotation_id: str,
    ) -> str:
        """
        Отправка REJECT.
        """
        system_data = {
            "rotation_id": rotation_id,
        }
        return self._save_system_message(
            from_id=from_id,
            to_id=to_id,
            system_type=ROTATION_STATUS_REJECT,
            system_data=system_data,
        )

    def send_rotation_timeout(
        self,
        from_id: str,
        to_id: str,
        rotation_id: str,
    ) -> str:
        """
        Отправка TIMEOUT (уведомление об истечении).
        """
        system_data = {
            "rotation_id": rotation_id,
            "timestamp": int(time.time()),
        }
        return self._save_system_message(
            from_id=from_id,
            to_id=to_id,
            system_type=ROTATION_STATUS_TIMEOUT,
            system_data=system_data,
        )
