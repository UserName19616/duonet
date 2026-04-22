# src/client/storage/contacts.py
"""
Управление контактами пользователя.

Обеспечивает хранение списка контактов с локальными именами.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

# Исправляем импорт: SQLiteStorage из common.storage
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


@dataclass
class ContactInfo:
    """Информация о контакте."""

    public_id: str  # Public ID контакта
    name: str  # локальное имя
    added_at: int  # timestamp добавления
    phrase_hash: Optional[str] = None  # хеш дополнительной фразы (первые 16 символов SHA256)


class ContactsStorage:
    """
    Хранилище контактов пользователя.

    Привязано к конкретному пользователю по user_id.
    """

    def __init__(self, storage: SQLiteStorage, user_id: bytes):
        """
        Инициализация хранилища контактов.

        Args:
            storage: Экземпляр SQLiteStorage.
            user_id: 20-байтовый ID пользователя.
        """
        self._storage = storage
        self._user_id = user_id
        self._prefix = f"contacts:{user_id.hex()}:"

    def _make_key(self, public_id: str) -> bytes:
        """Формирование ключа для контакта."""
        return f"{self._prefix}{public_id}".encode()

    def _validate_public_id(self, public_id: str) -> None:
        """Проверка валидности Public ID."""
        from src.common.identity.public_id import is_valid_format
        if not is_valid_format(public_id):
            raise ValueError(f"Invalid Public ID format: {public_id}")

    def _validate_name(self, name: str) -> None:
        """Проверка валидности имени."""
        if not name or not name.strip():
            raise ValueError("Name cannot be empty")
        if len(name) > 64:
            raise ValueError("Name too long (max 64 characters)")

    def _validate_phrase_hash(self, phrase_hash: Optional[str]) -> None:
        """Проверка валидности хеша фразы."""
        if phrase_hash is not None:
            if len(phrase_hash) != 16:
                raise ValueError("Phrase hash must be 16 hex characters")
            if not all(c in "0123456789abcdef" for c in phrase_hash):
                raise ValueError("Phrase hash must contain only hex characters")

    def add(self, public_id: str, name: str) -> bool:
        """
        Добавление контакта.

        Args:
            public_id: Public ID контакта.
            name: Локальное имя (1-64 символа).

        Returns:
            True если добавлен, False если уже существует.

        Raises:
            ValueError: При невалидных входных данных.
        """
        self._validate_public_id(public_id)
        self._validate_name(name)

        key = self._make_key(public_id)

        # Проверяем существование
        if self._storage.exists(key):
            return False

        # Создаем данные
        data = {
            "name": name.strip(),
            "added_at": int(time.time()),
            "phrase_hash": None,
        }

        self._storage.put(key, json.dumps(data).encode())
        return True

    def get(self, public_id: str) -> Optional[ContactInfo]:
        """
        Получение информации о контакте.

        Args:
            public_id: Public ID контакта.

        Returns:
            ContactInfo или None.
        """
        key = self._make_key(public_id)
        raw = self._storage.get(key)

        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return ContactInfo(
                public_id=public_id,
                name=data["name"],
                added_at=data["added_at"],
                phrase_hash=data.get("phrase_hash"),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse contact data for {public_id}: {e}")
            return None

    def get_all(self) -> List[ContactInfo]:
        """
        Получение всех контактов пользователя.

        Returns:
            Список контактов, отсортированных по added_at.
        """
        contacts = []
        prefix_bytes = self._prefix.encode()

        for key, raw in self._storage.iter_items(prefix_bytes):
            try:
                # Извлекаем public_id из ключа
                key_str = key.decode()
                public_id = key_str[len(self._prefix):]

                data = json.loads(raw)
                contacts.append(
                    ContactInfo(
                        public_id=public_id,
                        name=data["name"],
                        added_at=data["added_at"],
                        phrase_hash=data.get("phrase_hash"),
                    )
                )
            except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as e:
                logger.error(f"Failed to parse contact data: {e}")

        # Сортировка по added_at
        contacts.sort(key=lambda c: c.added_at)
        return contacts

    def update_name(self, public_id: str, new_name: str) -> bool:
        """
        Обновление локального имени контакта.

        Args:
            public_id: Public ID контакта.
            new_name: Новое локальное имя.

        Returns:
            True если обновлено, False если контакт не найден.

        Raises:
            ValueError: При невалидном имени.
        """
        self._validate_name(new_name)

        contact = self.get(public_id)
        if contact is None:
            return False

        # Обновляем данные
        data = {
            "name": new_name.strip(),
            "added_at": contact.added_at,
            "phrase_hash": contact.phrase_hash,
        }

        key = self._make_key(public_id)
        self._storage.put(key, json.dumps(data).encode())
        return True

    def delete(self, public_id: str) -> bool:
        """
        Удаление контакта.

        Args:
            public_id: Public ID контакта.

        Returns:
            True если удален, False если не найден.
        """
        key = self._make_key(public_id)

        if not self._storage.exists(key):
            return False

        self._storage.delete(key)
        return True

    def set_phrase_hash(self, public_id: str, phrase_hash: Optional[str]) -> bool:
        """
        Установка/удаление хеша дополнительной фразы.

        Args:
            public_id: Public ID контакта.
            phrase_hash: Хеш фразы (16 hex символов) или None для удаления.

        Returns:
            True если обновлено, False если контакт не найден.

        Raises:
            ValueError: При невалидном формате phrase_hash.
        """
        self._validate_phrase_hash(phrase_hash)

        contact = self.get(public_id)
        if contact is None:
            return False

        # Обновляем данные
        data = {
            "name": contact.name,
            "added_at": contact.added_at,
            "phrase_hash": phrase_hash,
        }

        key = self._make_key(public_id)
        self._storage.put(key, json.dumps(data).encode())
        return True

    def get_phrase_hash(self, public_id: str) -> Optional[str]:
        """
        Получение хеша дополнительной фразы.

        Args:
            public_id: Public ID контакта.

        Returns:
            Хеш фразы или None.
        """
        contact = self.get(public_id)
        return contact.phrase_hash if contact else None

    def count(self) -> int:
        """
        Количество контактов.

        Returns:
            Количество контактов.
        """
        prefix_bytes = self._prefix.encode()
        return len(list(self._storage.iter_keys(prefix_bytes)))
