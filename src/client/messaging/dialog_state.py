# src/client/messaging/dialog_state.py
"""
Управление состоянием диалогов.
"""

import logging
from typing import Optional, Dict, Any

from src.common.storage.sqlite import SQLiteStorage
from src.client.crypto.pfs import DialogState

logger = logging.getLogger(__name__)


class DialogStateManager:
    """Менеджер состояния диалогов."""

    def __init__(self, storage: Optional[SQLiteStorage] = None):
        self._storage = storage
        self._dialog_states: Dict[str, DialogState] = {}
        self._dialog_padding_state: Dict[str, int] = {}
        self._dialog_message_counter: Dict[str, int] = {}

    def get_dialog_state(self, dialog_id: str) -> Optional[DialogState]:
        """Получение состояния диалога."""
        return self._dialog_states.get(dialog_id)

    def set_dialog_state(self, dialog_id: str, state: DialogState) -> None:
        """Установка состояния диалога."""
        self._dialog_states[dialog_id] = state

    def get_padding(self, dialog_id: str) -> int:
        """Получение размера паддинга для диалога."""
        return self._dialog_padding_state.get(dialog_id, 0)

    def set_padding(self, dialog_id: str, padding: int) -> None:
        """Установка размера паддинга для диалога."""
        self._dialog_padding_state[dialog_id] = padding

    def get_next_counter(self, dialog_id: str) -> int:
        """Получение следующего счётчика сообщений для диалога."""
        counter = self._dialog_message_counter.get(dialog_id, 0)
        self._dialog_message_counter[dialog_id] = counter + 1
        return counter

        def load_dialogs_from_db(self, user_id: str, rotation_manager) -> None:
            """
            Загрузка диалогов пользователя из БД и восстановление состояния ротации.
            """
            if not self._storage:
                return

            try:
                dialogs = self._storage.get_all_dialogs(user_id)
                for contact_id, session_key_hex in dialogs:
                    try:
                        session_key = bytes.fromhex(session_key_hex)
                        dialog_id = self._get_dialog_id(user_id, contact_id)

                        # Сохраняем состояние PFS
                        state = DialogState(
                            contact_id=contact_id,
                            session_key=session_key,
                            current_key=session_key,
                            outgoing_counter=0,
                            incoming_counter=0,
                            pending_rotate=False,
                            retry_count=0,
                            last_message_id=None,
                        )
                        self._dialog_states[dialog_id] = state

                        # Восстанавливаем состояние ротации (V3)
                        rotation_manager.set_active_key(user_id, contact_id, session_key)

                        # Загружаем состояние из rotation_state таблицы (V3)
                        if rotation_manager._storage:
                            cursor = rotation_manager._storage.execute_sql(
                                "SELECT pending_rotation_id, pending_status, pending_expires_at "
                                "FROM rotation_state WHERE dialog_id = ?",
                                (dialog_id,)
                            )
                            row = cursor.fetchone()
                            # Состояние уже загружено в rotation_manager при инициализации
                            # Не пытаемся читать колонку pending_key

                    except Exception as e:
                        logger.error(f"Failed to load dialog with {contact_id}: {e}")
            except Exception as e:
                logger.error(f"Failed to load dialogs: {e}")

    def _get_dialog_id(self, user_id: str, contact_id: str) -> str:
        return f"{user_id}:{contact_id}" if user_id < contact_id else f"{contact_id}:{user_id}"
