#!/usr/bin/env python3
"""
Тесты для SystemMessageHandler V4
Обработка системных сообщений ротации ключей
"""

import pytest
import tempfile
import json
import time
from unittest.mock import MagicMock, patch

from src.client.messaging.system_messages import SystemMessageHandler
from src.client.messaging.rotation_manager import RotationManager
from src.client.crypto.ecdh import generate_ecdh_keypair
from src.client.crypto.rotation_id import generate_rotation_id
from src.common.identity.account import AccountManager
from src.common.storage.sqlite import SQLiteStorage
from src.client.storage.messages import MessagesStorage
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        # Создаём таблицу messages для системных сообщений
        db.execute_sql("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                encrypted TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                delivered INTEGER DEFAULT 0,
                read INTEGER DEFAULT 0,
                direction TEXT DEFAULT 'outgoing',
                has_phrase INTEGER DEFAULT 0,
                is_system INTEGER DEFAULT 0,
                system_type TEXT,
                system_data TEXT
            )
        """)
        yield db
        db.close()


@pytest.fixture
def ws_manager():
    return MockWebSocketManager()


@pytest.fixture
def account_manager(storage, ws_manager):
    rate_limiter = MultiRateLimiter()
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
        ws_manager=ws_manager,
    )


@pytest.fixture
def messages_storage(storage):
    return MessagesStorage("duonet.db")


@pytest.fixture
def rotation_manager(account_manager, storage, messages_storage, ws_manager):
    return RotationManager(
        account_manager=account_manager,
        storage=storage,
        messages_storage=messages_storage,
        ws_manager=ws_manager,
    )


@pytest.fixture
def system_handler(rotation_manager, messages_storage, storage):
    return SystemMessageHandler(
        rotation_manager=rotation_manager,
        messages_storage=messages_storage,
        storage=storage,
    )


@pytest.fixture
def test_users(account_manager):
    """Создание двух тестовых пользователей"""
    alice = account_manager.register(
        "alice_system@test.com", "pass123456", False, "127.0.0.1"
    )
    bob = account_manager.register(
        "bob_system@test.com", "pass123456", False, "127.0.0.1"
    )
    assert alice["success"]
    assert bob["success"]
    return {
        "alice": {
            "public_id": alice["public_id"],
            "account_id": alice["account_id"],
        },
        "bob": {
            "public_id": bob["public_id"],
            "account_id": bob["account_id"],
        },
    }


class TestSystemMessageHandlerInit:
    """Тесты инициализации"""

    def test_init(self, system_handler):
        """Проверка создания обработчика"""
        assert system_handler is not None
        assert hasattr(system_handler, "_rotation_manager")
        assert hasattr(system_handler, "_messages_storage")


class TestSystemMessageHandlerHandle:
    """Тесты обработки входящих системных сообщений"""

    def test_handle_request_message(self, system_handler, test_users):
        """Обработка REQUEST сообщения"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        eph_priv, eph_pub = generate_ecdh_keypair()
        session_key = b"test_key_32_bytes_test_key_32_b"

        system_data = {
            "rotation_id": rotation_id,
            "eph_public_key": eph_pub.hex(),
            "expires_at": int(time.time()) + 86400,
        }

        result = system_handler.handle(
            from_id=alice,
            to_id=bob,
            system_type="REQUEST",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert result["success"] is True
        assert result["rotation_id"] == rotation_id
        assert result["action"] == "pending_waiting_user"

    def test_handle_accept_message(self, system_handler, test_users):
        """Обработка ACCEPT сообщения - используем реальный rotation_id от REQUEST"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # 1. Инициируем ротацию и получаем реальный rotation_id
        init_result = system_handler._rotation_manager.initiate_key_rotation(
            alice, bob, session_key
        )
        assert init_result["success"] is True
        rotation_id = init_result["rotation_id"]
        eph_pub_a = init_result["eph_public_key"]

        # 2. Генерируем ключи Боба для ACCEPT
        eph_priv_b, eph_pub_b = generate_ecdh_keypair()

        # 3. Отправляем ACCEPT
        system_data = {
            "rotation_id": rotation_id,
            "eph_public_key": eph_pub_b.hex(),
        }

        result = system_handler.handle(
            from_id=bob,
            to_id=alice,
            system_type="ACCEPT",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        # ACCEPT должен обработаться успешно
        assert result["success"] is True
        assert result["rotation_id"] == rotation_id

    def test_handle_confirm_message(self, system_handler, test_users):
        """Обработка CONFIRM сообщения"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Создаём REQUEST и получаем ACCEPT
        init_result = system_handler._rotation_manager.initiate_key_rotation(
            alice, bob, session_key
        )
        assert init_result["success"] is True
        rotation_id = init_result["rotation_id"]

        # Боб генерирует ACCEPT
        eph_priv_b, eph_pub_b = generate_ecdh_keypair()

        accept_result = system_handler.handle(
            from_id=bob,
            to_id=alice,
            system_type="ACCEPT",
            system_data={
                "rotation_id": rotation_id,
                "eph_public_key": eph_pub_b.hex(),
            },
            timestamp=int(time.time()),
            current_session_key=session_key,
        )
        assert accept_result["success"] is True

        # Алиса отправляет CONFIRM
        confirm_result = system_handler.handle(
            from_id=alice,
            to_id=bob,
            system_type="CONFIRM",
            system_data={"rotation_id": rotation_id},
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert confirm_result["success"] is True
        assert confirm_result["rotation_id"] == rotation_id

    def test_handle_reject_message(self, system_handler, test_users):
        """Обработка REJECT сообщения"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        session_key = b"test_key_32_bytes_test_key_32_b"

        system_data = {"rotation_id": rotation_id}

        result = system_handler.handle(
            from_id=bob,
            to_id=alice,
            system_type="REJECT",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert result["success"] is True
        assert result["rotation_id"] == rotation_id
        assert result["action"] == "rotation_rejected"

    def test_handle_timeout_message(self, system_handler, test_users):
        """Обработка TIMEOUT сообщения"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        session_key = b"test_key_32_bytes_test_key_32_b"

        system_data = {"rotation_id": rotation_id}

        result = system_handler.handle(
            from_id=bob,
            to_id=alice,
            system_type="TIMEOUT",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert result["success"] is True
        assert result["rotation_id"] == rotation_id
        assert result["action"] == "timeout_processed"

    def test_handle_unknown_type(self, system_handler, test_users):
        """Обработка неизвестного типа сообщения - должно вернуть ошибку с unknown_type"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Для UNKNOWN_TYPE нужно передать rotation_id, иначе вернётся missing_rotation_id
        system_data = {"rotation_id": "test_rotation_id"}

        result = system_handler.handle(
            from_id=alice,
            to_id=bob,
            system_type="UNKNOWN_TYPE",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert result["success"] is False
        # Должна быть ошибка unknown_type
        assert "unknown_type" in result["error"].lower()

    def test_handle_missing_rotation_id(self, system_handler, test_users):
        """Отсутствует rotation_id в данных"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        system_data = {}

        result = system_handler.handle(
            from_id=alice,
            to_id=bob,
            system_type="REQUEST",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert result["success"] is False
        assert "missing_rotation_id" in result["error"]


class TestSystemMessageHandlerDuplicate:
    """Тесты защиты от дубликатов"""

    def test_duplicate_message_ignored(self, system_handler, test_users):
        """Повторное сообщение игнорируется"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        eph_priv, eph_pub = generate_ecdh_keypair()
        session_key = b"test_key_32_bytes_test_key_32_b"

        system_data = {
            "rotation_id": rotation_id,
            "eph_public_key": eph_pub.hex(),
            "expires_at": int(time.time()) + 86400,
        }

        # Первая обработка
        result1 = system_handler.handle(
            from_id=alice,
            to_id=bob,
            system_type="REQUEST",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )
        assert result1["success"] is True

        # Вторая обработка (дубликат)
        result2 = system_handler.handle(
            from_id=alice,
            to_id=bob,
            system_type="REQUEST",
            system_data=system_data,
            timestamp=int(time.time()),
            current_session_key=session_key,
        )

        assert result2["success"] is True
        assert result2["action"] == "duplicate_ignored"


class TestSystemMessageHandlerSend:
    """Тесты отправки системных сообщений"""

    def test_send_rotation_request(self, system_handler, test_users):
        """Отправка REQUEST"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        eph_priv, eph_pub = generate_ecdh_keypair()

        message_id = system_handler.send_rotation_request(
            from_id=alice,
            to_id=bob,
            rotation_id=rotation_id,
            eph_public_key_hex=eph_pub.hex(),
            expires_at=int(time.time()) + 86400,
        )

        assert message_id is not None
        assert message_id.startswith("sys_")
        assert rotation_id in message_id

    def test_send_rotation_accept(self, system_handler, test_users):
        """Отправка ACCEPT"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        eph_priv, eph_pub = generate_ecdh_keypair()

        message_id = system_handler.send_rotation_accept(
            from_id=bob,
            to_id=alice,
            rotation_id=rotation_id,
            eph_public_key_hex=eph_pub.hex(),
        )

        assert message_id is not None
        assert message_id.startswith("sys_")

    def test_send_rotation_confirm(self, system_handler, test_users):
        """Отправка CONFIRM"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()

        message_id = system_handler.send_rotation_confirm(
            from_id=alice,
            to_id=bob,
            rotation_id=rotation_id,
        )

        assert message_id is not None

    def test_send_rotation_complete(self, system_handler, test_users):
        """Отправка COMPLETE"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()

        message_id = system_handler.send_rotation_complete(
            from_id=bob,
            to_id=alice,
            rotation_id=rotation_id,
        )

        assert message_id is not None

    def test_send_rotation_reject(self, system_handler, test_users):
        """Отправка REJECT"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()

        message_id = system_handler.send_rotation_reject(
            from_id=bob,
            to_id=alice,
            rotation_id=rotation_id,
        )

        assert message_id is not None

    def test_send_rotation_timeout(self, system_handler, test_users):
        """Отправка TIMEOUT"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()

        message_id = system_handler.send_rotation_timeout(
            from_id=bob,
            to_id=alice,
            rotation_id=rotation_id,
        )

        assert message_id is not None


class TestSystemMessageHandlerSave:
    """Тесты сохранения системных сообщений"""

    def test_system_message_saved_to_db(self, system_handler, test_users, storage):
        """Проверка сохранения системного сообщения в БД"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        rotation_id = generate_rotation_id()
        eph_priv, eph_pub = generate_ecdh_keypair()

        message_id = system_handler.send_rotation_request(
            from_id=alice,
            to_id=bob,
            rotation_id=rotation_id,
            eph_public_key_hex=eph_pub.hex(),
            expires_at=int(time.time()) + 86400,
        )

        # Проверяем, что сообщение сохранено в БД
        cursor = storage.execute_sql(
            "SELECT id, system_type, is_system FROM messages WHERE id = ?",
            (message_id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[1] == "REQUEST"
        assert row[2] == 1  # is_system = 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
