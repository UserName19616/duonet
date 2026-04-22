# tests/unit/test_server_db.py
"""
Тесты для модуля ServerDatabase.
"""

import json
import os
import tempfile
import time
from unittest.mock import patch

import pytest

from src.server.storage.server_db import ServerDatabase
from src.server.storage.crypto import KeyManager, encrypt_data, decrypt_data, hmac_server_id, sign_server_record, verify_signature
from src.server.storage.server_db import get_server_db


@pytest.fixture
def temp_db():
    """Фикстура для временной БД."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = ServerDatabase(f.name)
        yield db
        db.close()


class TestKeyManager:
    """Тесты для KeyManager."""

    def test_get_enc_key(self):
        """Получение ключа шифрования."""
        km = KeyManager()
        key = km.get_enc_key()
        assert len(key) == 32

    def test_get_hmac_key(self):
        """Получение HMAC ключа."""
        km = KeyManager()
        key = km.get_hmac_key()
        assert len(key) == 32

    def test_keys_are_deterministic(self):
        """Ключи детерминированы для одного мастер-ключа."""
        with patch.dict(os.environ, {'DUONET_MASTER_KEY': '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef'}):
            KeyManager._instance = None
            KeyManager._master_key = None
            KeyManager._enc_key = None
            KeyManager._hmac_key = None
            KeyManager._sign_key = None

            km1 = KeyManager()
            km2 = KeyManager()
            assert km1.get_enc_key() == km2.get_enc_key()
            assert km1.get_hmac_key() == km2.get_hmac_key()


class TestEncryption:
    """Тесты для шифрования/расшифровки."""

    def test_encrypt_decrypt(self):
        """Шифрование и расшифровка строки."""
        original = "test_string_123"
        encrypted = encrypt_data(original)
        decrypted = decrypt_data(encrypted)
        assert decrypted == original

    def test_encrypt_different_outputs(self):
        """Разные вызовы дают разные результаты."""
        data = "same_data"
        enc1 = encrypt_data(data)
        enc2 = encrypt_data(data)
        assert enc1 != enc2

    def test_decrypt_empty(self):
        """Расшифровка пустых данных."""
        assert decrypt_data(b"") == ""

    def test_decrypt_invalid(self):
        """Расшифровка неверных данных."""
        result = decrypt_data(b"too_short")
        assert result == ""


class TestHMAC:
    """Тесты для HMAC функций."""

    def test_hmac_server_id(self):
        """Вычисление HMAC для server_id."""
        server_id = "@TEST-1234-5678.ru.srv"
        h1 = hmac_server_id(server_id)
        h2 = hmac_server_id(server_id)
        assert h1 == h2
        assert len(h1) == 32

    def test_hmac_different_ids(self):
        """Разные ID дают разные HMAC."""
        h1 = hmac_server_id("@A.ru.srv")
        h2 = hmac_server_id("@B.ru.srv")
        assert h1 != h2


class TestSignatures:
    """Тесты для подписей."""

    def test_sign_and_verify(self):
        """Подпись и верификация."""
        server_id = "@TEST.ru.srv"
        region = "ru"
        ws_url = "wss://test.local:9877"
        timestamp = int(time.time())

        signature = sign_server_record(server_id, region, ws_url, timestamp)
        assert len(signature) == 64
        assert verify_signature(server_id, region, ws_url, timestamp, signature) is True

    def test_verify_wrong_signature(self):
        """Верификация с неверной подписью."""
        server_id = "@TEST.ru.srv"
        region = "ru"
        ws_url = "wss://test.local:9877"
        timestamp = int(time.time())

        signature = sign_server_record(server_id, region, ws_url, timestamp)
        wrong_signature = "a" * 64
        assert verify_signature(server_id, region, ws_url, timestamp, wrong_signature) is False


class TestServerDatabase:
    """Тесты для ServerDatabase."""

    def test_add_server(self, temp_db):
        """Добавление сервера."""
        result = temp_db.add_server(
            server_id="@TEST.ru.srv",
            region="ru",
            ws_url="wss://localhost:9877",
        )
        assert result is True

        server = temp_db.get_server("@TEST.ru.srv")
        assert server is not None
        assert server["server_id"] == "@TEST.ru.srv"
        assert server["region"] == "ru"
        assert server["ws_url"] == "wss://localhost:9877"
        assert server["status"] == "active"

    def test_get_servers_by_region(self, temp_db):
        """Получение серверов по региону."""
        temp_db.add_server("@A.ru.srv", "ru", "wss://a:9877")
        temp_db.add_server("@B.ru.srv", "ru", "wss://b:9877")
        temp_db.add_server("@C.us.srv", "us", "wss://c:9877")

        ru_servers = temp_db.get_servers_by_region("ru")
        assert len(ru_servers) == 2

    def test_add_client(self, temp_db):
        """Добавление клиента."""
        result = temp_db.add_client(
            client_id="@CLIENT.ru",
            server_id="@SERVER.ru.srv",
            region="ru"
        )
        assert result is True

    def test_get_stats(self, temp_db):
        """Статистика БД."""
        stats = temp_db.get_stats()
        assert stats["total_servers"] == 0
        assert stats["total_clients"] == 0


class TestGlobalInstance:
    """Тесты для глобального экземпляра."""

    def test_get_server_db(self):
        """Получение глобального экземпляра."""
        db1 = get_server_db()
        db2 = get_server_db()
        assert db1 is db2
