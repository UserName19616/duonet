# tests/unit/test_storage_contacts.py
"""
Тесты для модуля хранения контактов.
"""

import hashlib
import json
import tempfile
import time

import pytest

from src.common.identity.public_id import generate_public_id
from src.client.storage.contacts import ContactsStorage, ContactInfo
from src.common.storage.sqlite import SQLiteStorage


def make_valid_public_id() -> str:
    """Генерирует валидный Public ID для тестов."""
    seed_hash = hashlib.sha256(b"test_contact_seed").digest()
    return generate_public_id(seed_hash, "ru", is_server=False)


def make_valid_public_id2() -> str:
    """Генерирует второй валидный Public ID для тестов."""
    seed_hash = hashlib.sha256(b"test_contact_seed_2").digest()
    return generate_public_id(seed_hash, "ru", is_server=False)


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def contacts(storage):
    user_id = b"\x01" * 20
    return ContactsStorage(storage, user_id)


class TestContactsStorage:
    """Тесты для ContactsStorage."""

    def test_add_and_get(self, contacts):
        """Добавление и получение контакта."""
        public_id = make_valid_public_id()
        result = contacts.add(public_id, "Алиса")
        assert result is True

        contact = contacts.get(public_id)
        assert contact is not None
        assert contact.public_id == public_id
        assert contact.name == "Алиса"
        assert contact.added_at > 0
        assert contact.phrase_hash is None

    def test_add_duplicate(self, contacts):
        """Добавление дубликата."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        result = contacts.add(public_id, "Алиса 2")
        assert result is False

    def test_get_all(self, contacts):
        """Получение всех контактов."""
        public_id1 = make_valid_public_id()
        public_id2 = make_valid_public_id2()
        contacts.add(public_id1, "Алиса")
        contacts.add(public_id2, "Боб")

        all_contacts = contacts.get_all()
        assert len(all_contacts) == 2
        assert all_contacts[0].public_id == public_id1
        assert all_contacts[1].public_id == public_id2

    def test_get_all_empty(self, contacts):
        """Получение всех контактов, когда их нет."""
        all_contacts = contacts.get_all()
        assert all_contacts == []

    def test_update_name(self, contacts):
        """Обновление имени контакта."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        result = contacts.update_name(public_id, "Алиса (работа)")
        assert result is True

        contact = contacts.get(public_id)
        assert contact.name == "Алиса (работа)"

    def test_update_name_not_found(self, contacts):
        """Обновление имени несуществующего контакта."""
        result = contacts.update_name("@NONEXISTENT-1234-5678.ru", "Имя")
        assert result is False

    def test_delete(self, contacts):
        """Удаление контакта."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        result = contacts.delete(public_id)
        assert result is True
        assert contacts.get(public_id) is None

    def test_delete_not_found(self, contacts):
        """Удаление несуществующего контакта."""
        result = contacts.delete("@NONEXISTENT-1234-5678.ru")
        assert result is False

    def test_set_phrase_hash(self, contacts):
        """Установка хеша фразы."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        phrase_hash = "a1b2c3d4e5f67890"

        result = contacts.set_phrase_hash(public_id, phrase_hash)
        assert result is True

        stored = contacts.get_phrase_hash(public_id)
        assert stored == phrase_hash

    def test_clear_phrase_hash(self, contacts):
        """Удаление хеша фразы."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        contacts.set_phrase_hash(public_id, "a1b2c3d4e5f67890")

        result = contacts.set_phrase_hash(public_id, None)
        assert result is True

        stored = contacts.get_phrase_hash(public_id)
        assert stored is None

    def test_get_phrase_hash_not_set(self, contacts):
        """Получение хеша фразы, который не установлен."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        stored = contacts.get_phrase_hash(public_id)
        assert stored is None

    def test_count(self, contacts):
        """Количество контактов."""
        assert contacts.count() == 0

        public_id1 = make_valid_public_id()
        public_id2 = make_valid_public_id2()
        contacts.add(public_id1, "Алиса")
        assert contacts.count() == 1

        contacts.add(public_id2, "Боб")
        assert contacts.count() == 2

    def test_different_users(self):
        """Разные пользователи имеют разные контакты."""
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            db = SQLiteStorage(f.name)

            user1 = b"\x01" * 20
            user2 = b"\x02" * 20

            contacts1 = ContactsStorage(db, user1)
            contacts2 = ContactsStorage(db, user2)

            public_id1 = make_valid_public_id()
            public_id2 = make_valid_public_id2()
            contacts1.add(public_id1, "Алиса")
            contacts2.add(public_id2, "Боб")

            assert len(contacts1.get_all()) == 1
            assert len(contacts2.get_all()) == 1
            assert contacts1.get(public_id2) is None
            assert contacts2.get(public_id1) is None

            db.close()

    def test_add_invalid_public_id(self, contacts):
        """Добавление с невалидным Public ID."""
        with pytest.raises(ValueError, match="Invalid Public ID format"):
            contacts.add("invalid", "Имя")

    def test_add_empty_name(self, contacts):
        """Добавление с пустым именем."""
        public_id = make_valid_public_id()
        with pytest.raises(ValueError, match="Name cannot be empty"):
            contacts.add(public_id, "")

        with pytest.raises(ValueError, match="Name cannot be empty"):
            contacts.add(public_id, "   ")

    def test_add_name_too_long(self, contacts):
        """Добавление с слишком длинным именем."""
        public_id = make_valid_public_id()
        long_name = "x" * 65
        with pytest.raises(ValueError, match="Name too long"):
            contacts.add(public_id, long_name)

    def test_update_name_empty(self, contacts):
        """Обновление имени на пустое."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")
        with pytest.raises(ValueError, match="Name cannot be empty"):
            contacts.update_name(public_id, "")

    def test_set_phrase_hash_invalid_format(self, contacts):
        """Установка хеша фразы в неверном формате."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")

        # Слишком длинный
        with pytest.raises(ValueError, match="Phrase hash must be 16 hex characters"):
            contacts.set_phrase_hash(public_id, "a1b2c3d4e5f67890i9j0")

        # Слишком короткий
        with pytest.raises(ValueError, match="Phrase hash must be 16 hex characters"):
            contacts.set_phrase_hash(public_id, "a1b2c3d4")

        # Не hex символы
        with pytest.raises(ValueError, match="Phrase hash must contain only hex characters"):
            contacts.set_phrase_hash(public_id, "g1b2c3d4e5f67890")

    def test_corrupted_data_handling(self, contacts, storage):
        """Обработка поврежденных данных."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")

        # Повреждаем данные
        key = contacts._make_key(public_id)
        storage.put(key, b"invalid json{")

        # Должен вернуть None и залогировать ошибку
        contact = contacts.get(public_id)
        assert contact is None

    def test_json_schema(self, contacts):
        """Проверка структуры JSON."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")

        key = contacts._make_key(public_id)
        raw = contacts._storage.get(key)
        data = json.loads(raw)

        assert "name" in data
        assert "added_at" in data
        assert "phrase_hash" in data or data.get("phrase_hash") is None
        assert isinstance(data["name"], str)
        assert isinstance(data["added_at"], int)

    def test_phrase_hash_format(self, contacts):
        """Проверка формата phrase_hash."""
        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")

        valid_hash = "a1b2c3d4e5f67890"
        result = contacts.set_phrase_hash(public_id, valid_hash)
        assert result is True

        stored = contacts.get_phrase_hash(public_id)
        assert stored == valid_hash
        assert len(stored) == 16
        assert all(c in "0123456789abcdef" for c in stored)

    def test_added_at_timestamp(self, contacts):
        """Проверка timestamp добавления."""
        before = int(time.time())
        time.sleep(0.01)

        public_id = make_valid_public_id()
        contacts.add(public_id, "Алиса")

        after = int(time.time())
        contact = contacts.get(public_id)

        assert before <= contact.added_at <= after

    def test_contact_info_dataclass(self):
        """Тест dataclass ContactInfo."""
        now = int(time.time())
        contact = ContactInfo(
            public_id="@TEST.ru",
            name="Тест",
            added_at=now,
            phrase_hash="a1b2c3d4e5f67890",
        )

        assert contact.public_id == "@TEST.ru"
        assert contact.name == "Тест"
        assert contact.added_at == now
        assert contact.phrase_hash == "a1b2c3d4e5f67890"

    def test_contact_info_without_phrase(self):
        """ContactInfo без хеша фразы."""
        now = int(time.time())
        contact = ContactInfo(
            public_id="@TEST.ru",
            name="Тест",
            added_at=now,
        )

        assert contact.phrase_hash is None


# =============================================================================
# Дополнительные тесты для контактов (без зависимости от account_manager)
# =============================================================================

class TestStorageContactsExtra:
    """Дополнительные тесты для хранилища контактов."""

    def test_contacts_storage_works_independently(self, contacts):
        """Проверка, что хранилище контактов работает независимо."""
        public_id = make_valid_public_id()

        # Добавляем контакт
        result = contacts.add(public_id, "Тестовый контакт")
        assert result is True

        # Получаем контакт
        contact = contacts.get(public_id)
        assert contact is not None
        assert contact.name == "Тестовый контакт"

        # Обновляем имя
        result = contacts.update_name(public_id, "Новое имя")
        assert result is True

        contact = contacts.get(public_id)
        assert contact.name == "Новое имя"

        # Удаляем контакт
        result = contacts.delete(public_id)
        assert result is True

        contact = contacts.get(public_id)
        assert contact is None
