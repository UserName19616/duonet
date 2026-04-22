# src/client/messaging/message_receiver.py
"""
Получение сообщений через маршрутизатор.
"""

import logging
import secrets
import time
from typing import Any, Dict, Optional

from src.common.identity.account import AccountManager
from src.client.storage.messages import MessageInfo, MessagesStorage
from src.common.storage.sqlite import SQLiteStorage
from src.common.crypto.padding import generate_message_id_with_counter
from .invite import InviteProtocol
from .dialog_state import DialogStateManager

logger = logging.getLogger(__name__)


class MessageReceiver:
    """Получатель сообщений."""

    def __init__(
        self,
        account_manager: AccountManager,
        messages_storage: MessagesStorage,
        invite_protocol: InviteProtocol,
        ws_manager: Any,
        storage: Optional[SQLiteStorage],
        rotation_manager: Any,
        dialog_manager: DialogStateManager,
        system_handler: Any,
    ):
        self._account_manager = account_manager
        self._messages_storage = messages_storage
        self._invite_protocol = invite_protocol
        self._ws_manager = ws_manager
        self._storage = storage
        self._rotation_manager = rotation_manager
        self._dialog_manager = dialog_manager
        self._system_handler = system_handler

    def receive(
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
        # Системные сообщения не требуют расшифровки
        if is_system and system_type:
            if timestamp is None:
                timestamp = int(time.time())

            # Обработка через SystemMessageHandler
            result = self._system_handler.handle(
                from_id=from_id,
                to_id=to_id,
                system_type=system_type,
                system_data=json.loads(system_data) if system_data else {},
                timestamp=timestamp,
                current_session_key=session_key,
            )

            # Сохраняем системное сообщение в БД
            if self._storage:
                self._storage.save_system_message(
                    msg_id=message_id or f"sys_{system_type}_{timestamp}_{secrets.token_hex(4)}",
                    from_id=from_id,
                    to_id=to_id,
                    timestamp=timestamp,
                    system_type=system_type,
                    system_data=system_data,
                )

            msg = MessageInfo(
                id=message_id or f"sys_{system_type}_{timestamp}_{secrets.token_hex(4)}",
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
                system_data=system_data,
            )
            self._messages_storage.save(msg)

            return {
                "success": True,
                "is_system": True,
                "system_type": system_type,
                "action": result.get("action"),
            }

        # Обычное сообщение — расшифровываем
        try:
            encrypted_bytes = bytes.fromhex(encrypted_hex)
        except ValueError:
            return {"success": False, "error": "invalid_hex", "plaintext": None}

        # Устанавливаем активный ключ в RotationManager
        self._rotation_manager.set_active_key(to_id, from_id, session_key)

        # Расшифровка (простая, без LRP)
        from src.client.crypto.directional import decrypt_directional

        plaintext = decrypt_directional(
            encrypted_bytes,
            session_key,
            from_id,
            to_id,
            phrase=phrase if has_phrase else None,
        )

        if plaintext is None:
            return {"success": False, "error": "decryption_failed", "plaintext": None}

        if message_id is None:
            counter = self._dialog_manager.get_next_counter(self._get_dialog_id(to_id, from_id))
            message_id = generate_message_id_with_counter(counter)

        if timestamp is None:
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
                direction="incoming",
            )
        else:
            message = MessageInfo(
                id=message_id,
                from_id=from_id,
                to_id=to_id,
                session_key=session_key.hex(),
                encrypted=encrypted_hex,
                timestamp=timestamp,
                delivered=True,
                read=False,
                has_phrase=has_phrase,
                direction="incoming",
            )
            self._messages_storage.save(message)

        # Отправка подтверждения доставки
        self._send_delivery_confirmation(from_id, message_id)

        return {
            "success": True,
            "message_id": message_id,
            "plaintext": plaintext,
        }

    def decrypt_message_by_id(
        self,
        message_id: str,
        session_key: bytes,
        phrase: Optional[str] = None,
    ) -> Optional[str]:
        """Расшифровка сообщения по ID."""
        msg = self._messages_storage.get(message_id)
        if not msg:
            return None

        try:
            encrypted_bytes = bytes.fromhex(msg.encrypted)
            key = session_key

            from src.client.crypto.directional import decrypt_directional

            decrypted = decrypt_directional(
                encrypted_bytes,
                key,
                msg.from_id,
                msg.to_id,
                phrase=phrase if msg.has_phrase else None,
            )

            return decrypted
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None

    def _send_delivery_confirmation(self, to_id: str, message_id: str) -> None:
        """Отправка подтверждения доставки."""
        if self._ws_manager and self._account_manager.is_online(to_id):
            self._ws_manager.send_to_client(to_id, {
                "type": "message_delivered",
                "data": {"message_id": message_id},
            })

    def _get_dialog_id(self, user_id: str, contact_id: str) -> str:
        return f"{user_id}:{contact_id}" if user_id < contact_id else f"{contact_id}:{user_id}"


# Добавляем импорт json, который использовался выше
import json
