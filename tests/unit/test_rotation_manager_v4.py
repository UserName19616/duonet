#!/usr/bin/env python3
"""
Тесты для RotationManager V4 (клиент-клиент, сервер слепой)
"""

import pytest
import tempfile
import time
from unittest.mock import MagicMock, patch

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
def messages_storage():
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
def test_users(account_manager):
    """Создание двух тестовых пользователей"""
    alice = account_manager.register(
        "alice_rotation@test.com", "pass123456", False, "127.0.0.1"
    )
    bob = account_manager.register(
        "bob_rotation@test.com", "pass123456", False, "127.0.0.1"
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


class TestRotationManagerInit:
    """Тесты инициализации RotationManager"""

    def test_init_db_tables(self, rotation_manager, storage):
        """Проверка создания таблицы rotation_state"""
        cursor = storage.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rotation_state'"
        )
        assert cursor.fetchone() is not None

    def test_get_dialog_id(self, rotation_manager, test_users):
        """Формирование ID диалога"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]

        dialog_id = rotation_manager._get_dialog_id(alice, bob)
        assert dialog_id == f"{alice}:{bob}" or dialog_id == f"{bob}:{alice}"
        assert ":" in dialog_id


class TestRotationManagerCanRotate:
    """Тесты проверки возможности ротации"""

    def test_can_rotate_no_state(self, rotation_manager, test_users):
        """Нет состояния диалога → можно ротировать"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]

        can_rotate, remaining, reason = rotation_manager.can_rotate_key(alice, bob)
        assert can_rotate is True
        assert reason == "ok"

    def test_can_rotate_with_pending(self, rotation_manager, test_users):
        """Есть pending запрос → нельзя ротировать"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Создаём состояние с pending
        state = rotation_manager._get_or_create_state(alice, bob, session_key)
        state.start_transition("test_rotation_id", "REQUEST", "abc123")
        rotation_manager._save_state(state)

        can_rotate, remaining, reason = rotation_manager.can_rotate_key(alice, bob)
        assert can_rotate is False
        assert reason == "rotation_pending"


class TestRotationManagerFullCycle:
    """Полный цикл ротации (имитация)"""

    def test_initiate_rotation_success(self, rotation_manager, test_users):
        """Успешная инициация ротации"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        result = rotation_manager.initiate_key_rotation(alice, bob, session_key)

        assert result["success"] is True
        assert "rotation_id" in result
        assert result["status"] == "REQUEST"
        assert "eph_public_key" in result
        assert len(result["eph_public_key"]) == 64  # 32 bytes = 64 hex chars

    def test_initiate_rotation_when_pending_fails(self, rotation_manager, test_users):
        """Повторная инициация при pending запросе должна失敗"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Первая инициация
        result1 = rotation_manager.initiate_key_rotation(alice, bob, session_key)
        assert result1["success"] is True

        # Вторая инициация (должна провалиться)
        result2 = rotation_manager.initiate_key_rotation(alice, bob, session_key)
        assert result2["success"] is False
        assert result2["error"] == "rotation_pending"

    def test_process_rotation_request(self, rotation_manager, test_users):
        """Обработка входящего REQUEST"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"
        rotation_id = generate_rotation_id()
        eph_priv, eph_pub = generate_ecdh_keypair()

        result = rotation_manager.process_rotation_request(
            from_id=alice,
            to_id=bob,
            rotation_id=rotation_id,
            eph_public_key_hex=eph_pub.hex(),
            timestamp=int(time.time()),
            expires_at=int(time.time()) + 86400,
            current_session_key=session_key,
        )

        assert result["success"] is True
        assert result["action"] == "pending_waiting_user"

    def test_accept_key_rotation(self, rotation_manager, test_users):
        """Принятие ротации (ACCEPT)"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Сначала инициируем
        init_result = rotation_manager.initiate_key_rotation(alice, bob, session_key)
        assert init_result["success"] is True
        rotation_id = init_result["rotation_id"]

        # Затем принимаем
        accept_result = rotation_manager.accept_key_rotation(
            user_id=bob,
            contact_id=alice,
            rotation_id=rotation_id,
            current_session_key=session_key,
        )

        assert accept_result["success"] is True
        assert accept_result["status"] == "ACCEPT"
        assert "eph_public_key" in accept_result

    def test_rotation_idempotency(self, rotation_manager, test_users):
        """Повторный вызов accept с тем же rotation_id не должен создавать дубликат"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        init_result = rotation_manager.initiate_key_rotation(alice, bob, session_key)
        rotation_id = init_result["rotation_id"]

        # Первый accept
        result1 = rotation_manager.accept_key_rotation(bob, alice, rotation_id, session_key)
        assert result1["success"] is True

        # Второй accept (должен вернуть уже обработано)
        result2 = rotation_manager.process_rotation_request(
            from_id=alice,
            to_id=bob,
            rotation_id=rotation_id,
            eph_public_key_hex=init_result["eph_public_key"],
            timestamp=int(time.time()),
            expires_at=int(time.time()) + 86400,
            current_session_key=session_key,
        )

        # Не должен создать новый pending
        assert result2["success"] is True

    def test_get_rotation_status(self, rotation_manager, test_users):
        """Получение статуса ротации"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Нет диалога → статус "none"
        status = rotation_manager.get_rotation_status(alice, bob)
        assert status["success"] is True
        assert status["mode"] == "none"
        assert status["can_rotate"] is True

        # Создаём диалог
        rotation_manager._get_or_create_state(alice, bob, session_key)

        status = rotation_manager.get_rotation_status(alice, bob)
        assert status["success"] is True
        assert status["mode"] == "normal"


class TestRotationManagerReject:
    """Тесты отклонения ротации"""

    def test_reject_key_rotation(self, rotation_manager, test_users):
        """Отклонение запроса ротации"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        init_result = rotation_manager.initiate_key_rotation(alice, bob, session_key)
        rotation_id = init_result["rotation_id"]

        reject_result = rotation_manager.reject_key_rotation(bob, alice, rotation_id)

        assert reject_result["success"] is True
        assert reject_result["status"] == "REJECT"

        # Проверяем, что состояние очищено
        status = rotation_manager.get_rotation_status(alice, bob)
        assert status["pending_rotation_id"] is None


class TestRotationManagerTimeout:
    """Тесты таймаута ротации"""

    def test_check_expired_rotations(self, rotation_manager, test_users):
        """Проверка и очистка истекших запросов"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Создаём запрос с истекшим временем
        with patch("src.client.messaging.rotation_manager.ROTATION_TIMEOUT", 1):
            init_result = rotation_manager.initiate_key_rotation(alice, bob, session_key)
            rotation_id = init_result["rotation_id"]

            # Ждём истечения
            time.sleep(1.5)

            rotation_manager.check_expired_rotations()

            # Проверяем, что запрос удалён
            status = rotation_manager.get_rotation_status(alice, bob)
            assert status["pending_rotation_id"] is None


class TestRotationManagerDeleteDialog:
    """Тесты удаления диалога"""

    def test_delete_dialog_state(self, rotation_manager, test_users):
        """Удаление состояния диалога"""
        alice = test_users["alice"]["public_id"]
        bob = test_users["bob"]["public_id"]
        session_key = b"test_key_32_bytes_test_key_32_b"

        # Создаём состояние
        rotation_manager._get_or_create_state(alice, bob, session_key)

        # Удаляем
        rotation_manager.delete_dialog_state(alice, bob)

        # Проверяем, что состояние удалено
        dialog_id = rotation_manager._get_dialog_id(alice, bob)
        assert dialog_id not in rotation_manager._dialog_states


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
