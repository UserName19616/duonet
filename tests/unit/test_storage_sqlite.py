# tests/unit/test_storage_sqlite.py
"""
Тесты для модуля SQLiteStorage.
"""

import tempfile

import pytest

from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    """Фикстура для SQLiteStorage."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


class TestSQLiteStorage:
    """Тесты для SQLiteStorage."""

    def test_put_and_get(self, storage):
        """Тест записи и чтения."""
        storage.put(b"key1", b"value1")
        assert storage.get(b"key1") == b"value1"

    def test_get_nonexistent(self, storage):
        """Тест чтения несуществующего ключа."""
        assert storage.get(b"nonexistent") is None

    def test_delete(self, storage):
        """Тест удаления."""
        storage.put(b"key1", b"value1")
        storage.delete(b"key1")
        assert storage.get(b"key1") is None

    def test_exists(self, storage):
        """Тест проверки существования."""
        assert storage.exists(b"key1") is False
        storage.put(b"key1", b"value1")
        assert storage.exists(b"key1") is True

    def test_overwrite(self, storage):
        """Тест перезаписи."""
        storage.put(b"key1", b"value1")
        storage.put(b"key1", b"value2")
        assert storage.get(b"key1") == b"value2"

    def test_iter_keys(self, storage):
        """Тест итерации по ключам."""
        storage.put(b"user:1", b"alice")
        storage.put(b"user:2", b"bob")
        storage.put(b"msg:1", b"hello")

        keys = list(storage.iter_keys(b"user:"))
        assert len(keys) == 2
        assert b"user:1" in keys
        assert b"user:2" in keys

    def test_iter_keys_list(self, storage):
        """Тест получения списка ключей."""
        storage.put(b"user:1", b"alice")
        storage.put(b"user:2", b"bob")

        keys = storage.iter_keys_list(b"user:")
        assert isinstance(keys, list)
        assert len(keys) == 2

    def test_iter_items(self, storage):
        """Тест итерации по парам."""
        storage.put(b"user:1", b"alice")
        storage.put(b"user:2", b"bob")

        items = list(storage.iter_items(b"user:"))
        assert len(items) == 2
        assert (b"user:1", b"alice") in items
        assert (b"user:2", b"bob") in items

    def test_iter_items_list(self, storage):
        """Тест получения списка пар."""
        storage.put(b"user:1", b"alice")
        storage.put(b"user:2", b"bob")

        items = storage.iter_items_list(b"user:")
        assert isinstance(items, list)
        assert len(items) == 2

    def test_batch_write(self, storage):
        """Тест пакетной записи."""
        operations = [
            ("put", b"batch1", b"value1"),
            ("put", b"batch2", b"value2"),
            ("delete", b"batch1", b""),
        ]
        storage.batch_write(operations)

        assert storage.get(b"batch1") is None
        assert storage.get(b"batch2") == b"value2"

    def test_context_manager(self):
        """Тест контекстного менеджера."""
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            with SQLiteStorage(f.name) as db:
                db.put(b"test", b"data")
            with pytest.raises(RuntimeError):
                db.get(b"test")

    def test_operations_after_close(self, storage):
        """Тест операций после закрытия."""
        storage.close()
        with pytest.raises(RuntimeError):
            storage.put(b"key", b"value")

    def test_put_invalid_key_type(self, storage):
        """Тест put с неверным типом ключа."""
        with pytest.raises(ValueError, match="Key must be bytes"):
            storage.put("string_key", b"value")  # type: ignore

    def test_put_invalid_value_type(self, storage):
        """Тест put с неверным типом значения."""
        with pytest.raises(ValueError, match="Value must be bytes"):
            storage.put(b"key", "string_value")  # type: ignore

    def test_get_invalid_key_type(self, storage):
        """Тест get с неверным типом ключа."""
        with pytest.raises(ValueError, match="Key must be bytes"):
            storage.get("string_key")  # type: ignore

    def test_delete_invalid_key_type(self, storage):
        """Тест delete с неверным типом ключа."""
        with pytest.raises(ValueError, match="Key must be bytes"):
            storage.delete("string_key")  # type: ignore

    def test_exists_invalid_key_type(self, storage):
        """Тест exists с неверным типом ключа."""
        with pytest.raises(ValueError, match="Key must be bytes"):
            storage.exists("string_key")  # type: ignore

    def test_iter_keys_invalid_prefix(self, storage):
        """Тест iter_keys с неверным префиксом."""
        with pytest.raises(ValueError, match="Prefix must be bytes"):
            list(storage.iter_keys("string_prefix"))  # type: ignore

    def test_execute_sql(self, storage):
        """Тест выполнения SQL."""
        storage.execute_sql(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)"
        )
        storage.execute_sql(
            "INSERT INTO test (name) VALUES (?)", ("test",)
        )

        cursor = storage.execute_sql("SELECT * FROM test")
        assert cursor.fetchone() == (1, "test")

    def test_wal_mode(self):
        """Тест включения WAL режима."""
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            db = SQLiteStorage(f.name)
            cursor = db.execute_sql("PRAGMA journal_mode")
            assert cursor.fetchone()[0] == "wal"
            db.close()

    def test_multiple_connections(self):
        """Тест работы с несколькими соединениями."""
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            db1 = SQLiteStorage(f.name)
            db2 = SQLiteStorage(f.name)

            db1.put(b"key", b"value1")
            assert db2.get(b"key") == b"value1"

            db2.put(b"key", b"value2")
            assert db1.get(b"key") == b"value2"

            db1.close()
            db2.close()
