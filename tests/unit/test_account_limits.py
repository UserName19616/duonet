# tests/unit/test_account_limits.py
"""
Тесты для лимитов клиентских и серверных аккаунтов.
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


class TestClientAccountLimit:
    """Тесты для лимита клиентских аккаунтов (максимум 3)."""

    def test_count_client_accounts_empty(self, account_manager):
        """Подсчёт клиентских аккаунтов когда их нет."""
        count = account_manager.count_client_accounts()
        assert count == 0

    def test_count_client_accounts_after_register(self, account_manager):
        """Подсчёт после регистрации клиентского аккаунта."""
        result = account_manager.register(
            seed_phrase="client1@example.com",
            password="password123",
            is_server=False,
            client_ip="10.0.0.1",
        )
        assert result["success"] is True

        count = account_manager.count_client_accounts()
        assert count == 1

    def test_count_client_accounts_server_not_counted(self, account_manager):
        """Серверные аккаунты не учитываются в лимите."""
        # Регистрируем серверный аккаунт (создаётся серверный + клиентский)
        result_server = account_manager.register(
            seed_phrase="server@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result_server["success"] is True

        count = account_manager.count_client_accounts()
        # При регистрации серверного создаётся и клиентский, поэтому count = 1
        assert count == 1

    def test_register_client_within_limit(self, account_manager):
        """Регистрация клиентского аккаунта в пределах лимита (до 3)."""
        # Мокаем время для обхода rate limiter
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True, f"Failed at iteration {i}"

            count = account_manager.count_client_accounts()
            assert count == MAX_CLIENT_ACCOUNTS

    def test_register_client_at_limit(self, account_manager):
        """Попытка регистрации при достижении лимита (уже 3 аккаунта)."""
        # Мокаем время для обхода rate limiter
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем первые 3 аккаунта
            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            # Пытаемся зарегистрировать 4-й
            result = account_manager.register(
                seed_phrase="client3@example.com",
                password="password123",
                is_server=False,
                client_ip="10.0.0.99",
            )

            assert result["success"] is False
            assert result["error"] == "max_clients_reached"
            assert result["client_count"] == MAX_CLIENT_ACCOUNTS
            assert result["max_clients"] == MAX_CLIENT_ACCOUNTS

    def test_register_client_with_same_ip_different_days(self, account_manager):
        """Регистрация 3 аккаунтов с одного IP в разные дни."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Первые 3 регистрации (должны пройти)
            for i in range(3):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip="10.0.0.1",
                )
                assert result["success"] is True

            # 4-я регистрация в тот же день (должна быть отклонена rate limiter)
            result = account_manager.register(
                seed_phrase="client3@example.com",
                password="password123",
                is_server=False,
                client_ip="10.0.0.1",
            )
            assert result["success"] is False
            assert result["error"] == "rate_limit_exceeded"

            # "Перематываем время" на 25 часов вперёд
            mock_time.time.return_value = base_time + 25 * 3600

            # 4-я регистрация на следующий день (должна быть отклонена лимитом клиентов)
            result = account_manager.register(
                seed_phrase="client3@example.com",
                password="password123",
                is_server=False,
                client_ip="10.0.0.1",
            )
            assert result["success"] is False
            assert result["error"] == "max_clients_reached"

    def test_get_client_accounts(self, account_manager):
        """Получение списка клиентских аккаунтов."""
        # Мокаем время для обхода rate limiter
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Создаём 3 клиентских аккаунта
            for i in range(MAX_CLIENT_ACCOUNTS):
                account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )

            # Создаём серверный аккаунт (не должен попасть в список)
            account_manager.register(
                seed_phrase="server@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.100",
            )

            clients = account_manager.get_client_accounts()
            assert len(clients) == MAX_CLIENT_ACCOUNTS
            for client in clients:
                assert "public_id" in client
                assert "created_at" in client


class TestServerAccountLimit:
    """Тесты для лимита серверных аккаунтов (максимум 1)."""

    def test_count_server_accounts_empty(self, account_manager):
        """Подсчёт серверных аккаунтов когда их нет."""
        count = account_manager.count_server_accounts()
        assert count == 0

    def test_count_server_accounts_after_register(self, account_manager):
        """Подсчёт после регистрации серверного аккаунта."""
        result = account_manager.register(
            seed_phrase="server@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result["success"] is True

        count = account_manager.count_server_accounts()
        assert count == 1

    def test_register_server_success(self, account_manager):
        """Регистрация первого серверного аккаунта."""
        result = account_manager.register(
            seed_phrase="server@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result["success"] is True
        assert result["server_id"] is not None
        assert result["server_id"].endswith(".srv")

    def test_register_second_server_fails(self, account_manager):
        """Попытка регистрации второго серверного аккаунта."""
        # Регистрируем первый серверный
        result1 = account_manager.register(
            seed_phrase="server1@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result1["success"] is True

        # Пытаемся зарегистрировать второй
        result2 = account_manager.register(
            seed_phrase="server2@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.2",
        )

        assert result2["success"] is False
        assert result2["error"] == "max_servers_reached"
        assert result2["server_count"] == 1
        assert result2["max_servers"] == 1

    def test_register_server_ignores_client_limit(self, account_manager):
        """Серверный аккаунт можно создать даже если клиентских уже 3."""
        # Мокаем время для обхода rate limiter
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Создаём 3 клиентских аккаунта
            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            # "Перематываем время"
            mock_time.time.return_value = base_time + 25 * 3600

            # Регистрируем серверный (должен пройти)
            result = account_manager.register(
                seed_phrase="server@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.100",
            )
            assert result["success"] is True
            assert result["server_id"] is not None

            # Количество клиентских не изменилось
            client_count = account_manager.count_client_accounts()
            assert client_count == MAX_CLIENT_ACCOUNTS
