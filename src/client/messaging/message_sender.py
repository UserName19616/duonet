# src/client/messaging/message_sender.py
"""
Отправка сообщений через маршрутизатор.
"""

import logging
import time
from typing import Any, Dict, Optional

from src.common.identity.account import AccountManager
from src.client.storage.messages import MessageInfo, MessagesStorage
from src.common.storage.sqlite import SQLiteStorage
from src.common.crypto.padding import generate_message_id_with_counter
from .invite import InviteProtocol
from .dialog_state import DialogStateManager

logger = logging.getLogger(__name__)


class MessageSender:
    """Отправитель сообщений."""

    def __init__(
        self,
        account_manager: AccountManager,
        messages_storage: MessagesStorage,
        invite_protocol: InviteProtocol,
        ws_manager: Any,
        storage: Optional[SQLiteStorage],
        rotation_manager: Any,
        dialog_manager: DialogStateManager,
    ):
        self._account_manager = account_manager
        self._messages_storage = messages_storage
        self._invite_protocol = invite_protocol
        self._ws_manager = ws_manager
        self._storage = storage
        self._rotation_manager = rotation_manager
        self._dialog_manager = dialog_manager

    def send_encrypted(
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
        # Проверка существования контакта
        if not self._check_contact_exists(from_id, to_id):
            return {
                "success": False,
                "error": "contact_not_found",
                "message": "Contact not found",
            }

        dialog_id = self._get_dialog_id(from_id, to_id)

        # Получение или создание состояния ротации
        self._rotation_manager.set_active_key(from_id, to_id, session_key)

        # Генерация ID сообщения
        counter = self._dialog_manager.get_next_counter(dialog_id)
        message_id = generate_message_id_with_counter(counter)
        timestamp = int(time.time())

        # Сохранение в БД
        if self._storage:
            self._storage.save_message_with_lrp(
                msg_id=message_id,
                from_id=from_id,
                to_id=to_id,
                session_key=session_key.hex(),
                encrypted=encrypted_hex,
                timestamp=timestamp,
                key_index=0,
                flags=0,
                pool_version=0,
                has_phrase=has_phrase,
                direction="outgoing",
            )

        message = MessageInfo(
            id=message_id,
            from_id=from_id,
            to_id=to_id,
            session_key=session_key.hex(),
            encrypted=encrypted_hex,
            timestamp=timestamp,
            delivered=False,
            read=False,
            has_phrase=has_phrase,
            direction="outgoing",
        )
        self._messages_storage.save(message)

        # Отправка через WebSocket
        delivered = False
        if self._ws_manager and self._account_manager.is_online(to_id):
            ws_message = {
                "type": "new_message",
                "data": {
                    "id": message_id,
                    "from": from_id,
                    "encrypted": encrypted_hex,
                    "session_key": session_key.hex(),
                    "timestamp": timestamp,
                    "has_phrase": has_phrase,
                    "key_index": 0,
                    "flags": 0,
                },
            }
            delivered = self._ws_manager.send_to_client(to_id, ws_message)
            if delivered:
                self._messages_storage.mark_delivered(message_id)

        return {
            "success": True,
            "message_id": message_id,
            "timestamp": timestamp,
            "delivered": delivered,
            "key_index": 0,
        }

    def _check_contact_exists(self, user_id: str, contact_id: str) -> bool:
        """Проверка, является ли contact_id контактом пользователя."""
        contacts = self._invite_protocol.get_contacts(user_id)
        return contact_id in contacts

    def _get_dialog_id(self, user_id: str, contact_id: str) -> str:
        return f"{user_id}:{contact_id}" if user_id < contact_id else f"{contact_id}:{user_id}"
