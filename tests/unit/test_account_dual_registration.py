# tests/unit/test_account_dual_registration.py
"""
Тесты для регистрации двойных аккаунтов (серверный + клиентский).
"""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from src.common.identity.account import AccountManager, MAX_CLIENT_ACCOUNTS, MAX_SERVER_ACCOUNTS
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage


def mock_geoip(ip):
    return "ru"


@pytest.fixture
def storage():
    """Фикстура для SQLiteStorage."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def rate_limiter():
    """Фикстура для MultiRateLimiter."""
    return MultiRateLimiter()


@pytest.fixture
def account_manager(storage, rate_limiter):
    """Фикстура для AccountManager."""
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret_key",
    )


class TestDualRegistration:
    """Тесты для регистрации двойных аккаунтов (is_server=True)."""

    def test_dual_registration_creates_two_accounts(self, account_manager):
        """При is_server=True создаются 2 записи: серверная и клиентская."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            result = account_manager.register(
                seed_phrase="test@example.com seed phrase",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )

            assert result["success"] is True
            assert result["public_id"] is not None
            assert result["server_id"] is not None
            assert result["public_id"] != result["server_id"]
            assert result["server_id"].endswith(".srv")

            # Проверяем, что в БД 2 записи (ищем по seed_hash, а не по account_id)
            seed_hash = account_manager._compute_seed_hash("test@example.com seed phrase")
            cursor = account_manager._storage.execute_sql(
                "SELECT COUNT(*) FROM accounts WHERE seed_hash = ?",
                (seed_hash,)
            )
            count = cursor.fetchone()[0]
            assert count == 2

    def test_dual_registration_client_account_has_correct_fields(self, account_manager):
        """Клиентский аккаунт при двойной регистрации имеет правильные поля."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            result = account_manager.register(
                seed_phrase="test@example.com seed phrase",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )

            # Получаем клиентский аккаунт по client_account_id
            cursor = account_manager._storage.execute_sql(
                "SELECT public_id, server_id, is_server FROM accounts WHERE account_id = ?",
                (result["client_account_id"],)
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == result["public_id"]  # public_id
            assert row[1] is None  # server_id = None
            assert row[2] == 0  # is_server = 0

    def test_dual_registration_server_account_has_correct_fields(self, account_manager):
        """Серверный аккаунт при двойной регистрации имеет правильные поля."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            result = account_manager.register(
                seed_phrase="test@example.com seed phrase",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )

            # Получаем серверный аккаунт по server_id
            cursor = account_manager._storage.execute_sql(
                "SELECT public_id, server_id, is_server FROM accounts WHERE server_id = ?",
                (result["server_id"],)
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] is None  # public_id = None
            assert row[1] == result["server_id"]  # server_id
            assert row[2] == 1  # is_server = 1

    def test_dual_registration_server_limit_enforced(self, account_manager):
        """Нельзя создать второй серверный аккаунт."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Первая регистрация (серверный + клиентский)
            result1 = account_manager.register(
                seed_phrase="test1@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )
            assert result1["success"] is True

            # Вторая регистрация с другой сид-фразой
            result2 = account_manager.register(
                seed_phrase="test2@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.2",
            )
            assert result2["success"] is False
            assert result2["error"] == "max_servers_reached"

    def test_dual_registration_client_limit_enforced(self, account_manager):
        """При двойной регистрации проверяется лимит клиентских аккаунтов."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Сначала создаём 3 клиентских аккаунта
            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            # Пытаемся создать серверный
            # При достижении лимита клиентских (3), серверный создаётся, но клиентский не создаётся
            result = account_manager.register(
                seed_phrase="server@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.100",
            )
            # Серверный аккаунт должен создаться
            assert result["success"] is True
            assert result["server_id"] is not None
            # Клиентский аккаунт не создаётся из-за лимита
            assert result.get("public_id") is None

    def test_dual_registration_same_seed_phrase_fails(self, account_manager):
        """Повторная регистрация с той же сид-фразой должна завершиться ошибкой."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Первая регистрация
            result1 = account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )
            assert result1["success"] is True

            # Вторая регистрация с той же сид-фразой
            result2 = account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.2",
            )
            assert result2["success"] is False
            # Может быть либо account_exists (если аккаунт уже есть)
            # либо max_servers_reached (если пытаемся создать второй серверный)
            assert result2["error"] in ["account_exists", "max_servers_reached"]

    def test_dual_registration_login_works_with_client_id(self, account_manager):
        """Вход по сид-фразе должен давать клиентский аккаунт."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            result = account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )
            assert result["success"] is True

            # Вход по сид-фразе
            login_result = account_manager.login("test@example.com", "password123")
            assert login_result is not None
            assert login_result["public_id"] == result["public_id"]
            assert login_result["server_id"] is None
            assert login_result["is_server"] is False

    def test_dual_registration_login_by_server_id_works(self, account_manager):
        """Вход по серверному ID должен работать."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            result = account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )
            assert result["success"] is True

            # Вход по серверному ID
            login_result = account_manager.login_by_server_id(result["server_id"], "password123")
            assert login_result is not None
            assert login_result["server_id"] == result["server_id"]
            assert login_result["public_id"] is None
            assert login_result["is_server"] is True


class TestClientOnlyRegistration:
    """Тесты для регистрации только клиентских аккаунтов (is_server=False)."""

    def test_client_only_registration_creates_one_account(self, account_manager):
        """При is_server=False создаётся только одна запись."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            result = account_manager.register(
                seed_phrase="client@example.com",
                password="password123",
                is_server=False,
                client_ip="10.0.0.1",
            )
            assert result["success"] is True
            assert result["public_id"] is not None
            assert result["server_id"] is None

            # Проверяем, что в БД 1 запись
            cursor = account_manager._storage.execute_sql(
                "SELECT COUNT(*) FROM accounts WHERE account_id = ?",
                (result["account_id"],)
            )
            count = cursor.fetchone()[0]
            assert count == 1

            # Проверяем, что это клиентский аккаунт
            cursor = account_manager._storage.execute_sql(
                "SELECT is_server FROM accounts WHERE account_id = ?",
                (result["account_id"],)
            )
            row = cursor.fetchone()
            assert row[0] == 0

    def test_client_only_registration_limit_enforced(self, account_manager):
        """Нельзя создать больше MAX_CLIENT_ACCOUNTS клиентских аккаунтов."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Создаём MAX_CLIENT_ACCOUNTS клиентских аккаунтов
            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            # Пытаемся создать ещё один
            result = account_manager.register(
                seed_phrase="client3@example.com",
                password="password123",
                is_server=False,
                client_ip="10.0.0.99",
            )
            assert result["success"] is False
            assert result["error"] == "max_clients_reached"


class TestAccountCounts:
    """Тесты для подсчёта аккаунтов."""

    def test_count_client_accounts_after_dual_registration(self, account_manager):
        """После двойной регистрации count_client_accounts = 1."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )

            client_count = account_manager.count_client_accounts()
            assert client_count == 1

    def test_count_server_accounts_after_dual_registration(self, account_manager):
        """После двойной регистрации count_server_accounts = 1."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )

            server_count = account_manager.count_server_accounts()
            assert server_count == 1

    def test_count_client_accounts_after_multiple_clients(self, account_manager):
        """После нескольких клиентских регистраций счётчик увеличивается."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Сначала двойная регистрация (1 клиент)
            account_manager.register(
                seed_phrase="test@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.1",
            )

            assert account_manager.count_client_accounts() == 1

            # Добавляем ещё 2 клиентских
            for i in range(2):
                account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+2}",
                )

            assert account_manager.count_client_accounts() == 3
