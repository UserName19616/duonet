# src/client/messaging/message_router.py
"""
Маршрутизатор сообщений (фасад).
Интегрирует новый RotationManager V2 с ECDH.
"""

import asyncio
import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from src.common.crypto.padding import generate_message_id_with_counter, extract_counter_from_message_id
from src.common.identity.account import AccountManager
from src.client.storage.messages import MessageInfo, MessagesStorage
from src.common.storage.sqlite import SQLiteStorage
from src.client.crypto.aes import generate_session_key
from .invite import InviteProtocol
from .crypto_logger import log_crypto_event
from .rotation_manager import RotationManager
from .system_messages import SystemMessageHandler
from .dialog_state import DialogStateManager
from .message_sender import MessageSender
from .message_receiver import MessageReceiver

logger = logging.getLogger(__name__)


class MessageRouter:
    def __init__(
        self,
        account_manager: AccountManager,
        messages_storage: MessagesStorage,
        invite_protocol: InviteProtocol,
        ws_manager: Any = None,
        storage: Optional[SQLiteStorage] = None,
    ):
        self._account_manager = account_manager
        self._messages_storage = messages_storage
        self._invite_protocol = invite_protocol
        self._ws_manager = ws_manager
        self._storage = storage
        self._message_cache: Dict[str, MessageInfo] = {}
        self._resync_callbacks: Dict[str, asyncio.Future] = {}

        # Новый RotationManager V2 (вместо LRP)
        self._rotation_manager = RotationManager(
            account_manager=self._account_manager,
            storage=self._storage,
            messages_storage=self._messages_storage,
            ws_manager=self._ws_manager,
        )

        # SystemMessageHandler для обработки системных сообщений
        self._system_handler = SystemMessageHandler(
            rotation_manager=self._rotation_manager,
            messages_storage=self._messages_storage,
            storage=self._storage,
        )

        self._dialog_manager = DialogStateManager(self._storage)

        self._message_sender = MessageSender(
            account_manager, messages_storage, invite_protocol, ws_manager, storage,
            self._rotation_manager, self._dialog_manager
        )

        self._message_receiver = MessageReceiver(
            account_manager, messages_storage, invite_protocol, ws_manager, storage,
            self._rotation_manager, self._dialog_manager, self._system_handler
        )

    def _get_dialog_id(self, user_id: str, contact_id: str) -> str:
        return f"{user_id}:{contact_id}" if user_id < contact_id else f"{contact_id}:{user_id}"

    # =========================================================================
    # Методы ротации ключей (V2)
    # =========================================================================

    def can_rotate_key(self, user_id: str, contact_id: str) -> Tuple[bool, int, str]:
        """Проверка, можно ли инициировать ротацию."""
        return self._rotation_manager.can_rotate_key(user_id, contact_id)

    def initiate_key_rotation(self, user_id: str, contact_id: str) -> Dict[str, Any]:
        """Инициирование ротации ключа (шаг 1)."""
        # Получаем текущий session_key
        session_key = self._rotation_manager.get_active_key(user_id, contact_id)
        if not session_key:
            dialog = self._storage.get_dialog(user_id, contact_id) if self._storage else None
            if dialog:
                session_key = bytes.fromhex(dialog)
            else:
                return {"success": False, "error": "no_session_key"}

        return self._rotation_manager.initiate_key_rotation(user_id, contact_id, session_key)

    def accept_key_rotation(self, user_id: str, contact_id: str, request_id: str) -> Dict[str, Any]:
        """Принятие запроса на ротацию (шаг 3: получатель → инициатор)."""
        session_key = self._rotation_manager.get_active_key(user_id, contact_id)
        if not session_key:
            dialog = self._storage.get_dialog(user_id, contact_id) if self._storage else None
            if dialog:
                session_key = bytes.fromhex(dialog)
            else:
                return {"success": False, "error": "no_session_key"}

        return self._rotation_manager.accept_key_rotation(user_id, contact_id, request_id, session_key)

    def confirm_key_rotation(self, user_id: str, contact_id: str, request_id: str, eph_public_key_hex: str) -> Dict[str, Any]:
        """Подтверждение ротации (шаг 4: инициатор → получатель)."""
        return self._rotation_manager.confirm_key_rotation(user_id, contact_id, request_id, eph_public_key_hex)

    def complete_key_rotation(self, user_id: str, contact_id: str, request_id: str) -> Dict[str, Any]:
        """Завершение ротации (получатель после получения confirm)."""
        return self._rotation_manager.complete_key_rotation(user_id, contact_id, request_id)

    def reject_key_rotation(self, user_id: str, contact_id: str, request_id: str) -> Dict[str, Any]:
        """Отклонение запроса на ротацию."""
        return self._rotation_manager.reject_key_rotation(user_id, contact_id, request_id)

    def get_rotation_status(self, user_id: str, contact_id: str) -> Dict[str, Any]:
        """Получение статуса ротации."""
        return self._rotation_manager.get_rotation_status(user_id, contact_id)

    def handle_system_message(
        self,
        from_id: str,
        to_id: str,
        system_type: str,
        system_data: Dict[str, Any],
        timestamp: int
    ) -> Dict[str, Any]:
        """Обработка системного сообщения."""
        # Получаем текущий session_key
        session_key = self._rotation_manager.get_active_key(to_id, from_id)
        if not session_key:
            dialog = self._storage.get_dialog(to_id, from_id) if self._storage else None
            if dialog:
                session_key = bytes.fromhex(dialog)

        return self._system_handler.handle(
            from_id=from_id,
            to_id=to_id,
            system_type=system_type,
            system_data=system_data,
            timestamp=timestamp,
            current_session_key=session_key or b"",
        )

    def send_rotation_request_system_message(
        self,
        from_id: str,
        to_id: str,
        request_id: str,
        eph_public_key_hex: str,
        expires_at: int,
    ) -> str:
        """Отправка системного сообщения rotation_request."""
        return self._system_handler.send_rotation_request(
            from_id=from_id,
            to_id=to_id,
            request_id=request_id,
            eph_public_key_hex=eph_public_key_hex,
            expires_at=expires_at,
        )

    def send_rotation_accept_system_message(
        self,
        from_id: str,
        to_id: str,
        request_id: str,
        eph_public_key_hex: str,
    ) -> str:
        """Отправка системного сообщения rotation_accept."""
        return self._system_handler.send_rotation_accept(
            from_id=from_id,
            to_id=to_id,
            request_id=request_id,
            eph_public_key_hex=eph_public_key_hex,
        )

    def send_rotation_confirm_system_message(
        self,
        from_id: str,
        to_id: str,
        request_id: str,
    ) -> str:
        """Отправка системного сообщения rotation_confirm."""
        return self._system_handler.send_rotation_confirm(
            from_id=from_id,
            to_id=to_id,
            request_id=request_id,
        )

    def send_rotation_reject_system_message(
        self,
        from_id: str,
        to_id: str,
        request_id: str,
    ) -> str:
        """Отправка системного сообщения rotation_reject."""
        return self._system_handler.send_rotation_reject(
            from_id=from_id,
            to_id=to_id,
            request_id=request_id,
        )

    def send_rotation_timeout_system_message(
        self,
        from_id: str,
        to_id: str,
        request_id: str,
    ) -> str:
        """Отправка системного сообщения rotation_timeout."""
        return self._system_handler.send_rotation_timeout(
            from_id=from_id,
            to_id=to_id,
            request_id=request_id,
        )

    def check_expired_rotations(self) -> None:
        """Проверка истекших запросов ротации."""
        self._rotation_manager.check_expired_rotations()

    # =========================================================================
    # Методы для работы с сообщениями (обёртки)
    # =========================================================================

    def send_encrypted_message(
        self,
        from_id: str,
        to_id: str,
        encrypted_hex: str,
        session_key: bytes,
        has_phrase: bool = False,
        phrase: Optional[str] = None,
        plaintext_len: Optional[int] = None,
        prev_padding: Optional[int] = None,
        message_counter: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Отправка уже зашифрованного сообщения."""
        return self._message_sender.send_encrypted(
            from_id, to_id, encrypted_hex, session_key,
            has_phrase, phrase, plaintext_len, prev_padding, message_counter
        )

    def receive_message(
        self,
        encrypted_hex: str,
        from_id: str,
        to_id: str,
        session_key: bytes,
        message_id: Optional[str] = None,
        has_phrase: bool = False,
        phrase: Optional[str] = None,
        is_system: bool = False,
        system_type: Optional[str] = None,
        system_data: Optional[str] = None,
        timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Получение сообщения с расшифровкой."""
        return self._message_receiver.receive(
            encrypted_hex, from_id, to_id, session_key,
            message_id, has_phrase, phrase, is_system,
            system_type, system_data, timestamp
        )

    def get_messages(
        self,
        user_id: str,
        contact_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Получение сообщений."""
        if contact_id:
            messages = self._messages_storage.get_dialog(user_id, contact_id, limit, offset)
        else:
            messages = []

        result = []
        for msg in messages:
            msg_dict = {
                "id": msg.id,
                "from_id": msg.from_id,
                "to_id": msg.to_id,
                "encrypted": msg.encrypted,
                "session_key": msg.session_key,
                "timestamp": msg.timestamp,
                "delivered": msg.delivered,
                "read": msg.read,
                "has_phrase": msg.has_phrase,
                "is_system": getattr(msg, 'is_system', 0),
                "system_type": getattr(msg, 'system_type', None),
                "system_data": getattr(msg, 'system_data', None),
            }
            result.append(msg_dict)
        return result

    def get_unread_count(self, user_id: str, contact_id: Optional[str] = None) -> int:
        """Количество непрочитанных сообщений."""
        return self._messages_storage.get_unread_count(user_id, contact_id)

    def mark_delivered(self, message_id: str) -> bool:
        """Отметка сообщения как доставленного."""
        return self._messages_storage.mark_delivered(message_id)

    def mark_read(self, message_id: str) -> bool:
        """Отметка сообщения как прочитанного."""
        return self._messages_storage.mark_read(message_id)

    def mark_all_read(self, user_id: str, contact_id: str) -> int:
        """Отметка всех сообщений от контакта как прочитанных."""
        return self._messages_storage.mark_all_read(user_id, contact_id)

    def delete_message(self, message_id: str) -> bool:
        """Удаление сообщения."""
        return self._messages_storage.delete(message_id)

    def delete_conversation(self, user_id: str, contact_id: str) -> int:
        """Удаление всей переписки с контактом."""
        self._rotation_manager.delete_dialog_state(user_id, contact_id)
        return self._messages_storage.delete_dialog(user_id, contact_id)

    def get_connected_clients(self) -> List[Dict[str, Any]]:
        """Получение списка подключённых клиентов."""
        if self._ws_manager:
            return self._ws_manager.get_all_connections()
        return []

    def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        """Отправка сообщения клиенту."""
        if not self._ws_manager:
            return False
        return self._ws_manager.send_to_client(client_id, message)

    def close_connection(self, client_id: str) -> bool:
        """Закрытие соединения с клиентом."""
        if self._ws_manager:
            return self._ws_manager.remove_connection(client_id)
        return False

    def get_active_connection_count(self) -> int:
        """Количество активных соединений."""
        if self._ws_manager:
            return self._ws_manager.get_connection_count()
        return 0

    def load_dialogs_from_db(self, user_id: str) -> None:
        """Загрузка диалогов из БД (устарело в V4, ротация только на клиенте)"""
        # V4: ротация ключей полностью на клиенте, сервер не участвует
        # Этот метод больше не нужен
        pass

    def decrypt_message(
        self,
        message_id: str,
        session_key: bytes,
        phrase: Optional[str] = None,
    ) -> Optional[str]:
        """Расшифровка сообщения по ID."""
        return self._message_receiver.decrypt_message_by_id(message_id, session_key, phrase)

    def get_message_packets(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о пакетах сообщения (для крипто-лога)."""
        return None
