# tests/unit/test_api_auth.py
"""
Тесты для API аутентификации.
"""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.server.api.auth import create_auth_router
from src.common.identity.account import AccountManager, MAX_CLIENT_ACCOUNTS, MAX_SERVER_ACCOUNTS
from src.common.identity.recovery import RecoveryService
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def geoip():
    def get_region(ip):
        return "ru"
    return get_region


@pytest.fixture
def rate_limiter():
    return MultiRateLimiter()


@pytest.fixture
def account_manager(storage, geoip, rate_limiter):
    return AccountManager(
        storage=storage,
        geoip_func=geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret_key",
    )


@pytest.fixture
def recovery_service(storage, account_manager):
    return RecoveryService(storage, account_manager)


@pytest.fixture
def router(account_manager, recovery_service, rate_limiter):
    return create_auth_router(account_manager, recovery_service, rate_limiter)


@pytest.fixture
def client(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestApiAuth:
    """Тесты для API аутентификации."""

    def test_register_success(self, client):
        """Успешная регистрация клиентского аккаунта."""
        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com моя фраза",
                "password": "secure_password_123",
                "is_server": False,
                "region": "ru",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["public_id"] is not None
        assert data["public_id"].startswith("@")
        assert "token" in data
        assert data["expires_at"] > 0

    def test_register_duplicate(self, client):
        """Регистрация дубликата."""
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "account_exists"

    def test_register_weak_password(self, client):
        """Регистрация со слабым паролем."""
        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "123",
                "region": "ru",
                "is_server": False,
            },
        )

        assert response.status_code == 422

    def test_register_empty_seed(self, client):
        """Регистрация с пустой сид-фразой."""
        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        assert response.status_code == 422

    def test_login_success(self, client):
        """Успешный вход."""
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        response = client.post(
            "/api/auth/login",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data
        assert data["expires_at"] > 0

    def test_login_wrong_password(self, client):
        """Вход с неверным паролем."""
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        response = client.post(
            "/api/auth/login",
            json={
                "seed_phrase": "user@example.com",
                "password": "wrong",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_credentials"

    def test_login_nonexistent(self, client):
        """Вход с несуществующей сид-фразой."""
        response = client.post(
            "/api/auth/login",
            json={
                "seed_phrase": "nonexistent@example.com",
                "password": "pass123456",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_credentials"

    def test_verify_token_valid(self, client):
        """Проверка валидного токена."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        response = client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["valid"] is True
        assert data["public_id"] is not None

    def test_verify_token_invalid(self, client):
        """Проверка невалидного токена."""
        response = client.get(
            "/api/auth/verify",
            headers={"Authorization": "Bearer invalid.token.here"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["valid"] is False

    def test_change_password_success(self, client):
        """Успешная смена пароля."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "old_pass",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "old_password": "old_pass",
                "new_password": "new_pass_123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        login = client.post(
            "/api/auth/login",
            json={
                "seed_phrase": "user@example.com",
                "password": "new_pass_123",
            },
        )
        assert login.status_code == 200
        assert login.json()["success"] is True

    def test_change_password_wrong_old(self, client):
        """Смена пароля с неверным старым паролем."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "old_pass",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "old_password": "wrong",
                "new_password": "new_pass_123",
            },
        )

        assert response.status_code == 400

    def test_recovery_request(self, client):
        """Запрос восстановления пароля."""
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com моя фраза",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        response = client.post(
            "/api/auth/recovery/request",
            json={
                "seed_phrase": "user@example.com моя фраза",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_recovery_request_no_email(self, client):
        """Запрос восстановления без email в сид-фразе."""
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "моя фраза без email",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )

        response = client.post(
            "/api/auth/recovery/request",
            json={
                "seed_phrase": "моя фраза без email",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_account(self, client):
        """Получение информации об аккаунте."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        response = client.get(
            "/api/auth/account",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["public_id"] is not None
        assert "created_at" in data["data"]
        assert "has_recovery" in data["data"]

    def test_unauthorized_access(self, client):
        """Неавторизованный доступ."""
        response = client.get("/api/auth/account")
        assert response.status_code == 401

    def test_logout(self, client):
        """Выход из системы."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_verify_token_expired(self, client):
        """Проверка истекшего токена."""
        from unittest.mock import patch

        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        with patch("src.common.identity.account.AccountManager.verify_token") as mock_verify:
            mock_verify.return_value = None

            response = client.get(
                "/api/auth/verify",
                headers={"Authorization": f"Bearer {token}"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is False

    def test_rate_limiting(self, client):
        """Rate limiting для регистрации."""
        ip = "10.0.0.1"

        for i in range(3):
            response = client.post(
                "/api/auth/register",
                json={
                    "seed_phrase": f"user{i}@example.com",
                    "password": "pass123456",
                    "region": "ru",
                    "is_server": False,
                },
                headers={"X-Forwarded-For": ip},
            )
            assert response.status_code == 200
            assert response.json()["success"] is True

        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user4@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
            headers={"X-Forwarded-For": ip},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "rate_limit_exceeded"

    def test_get_accounts(self, client):
        """Получение списка всех аккаунтов."""
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user1@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        # Регистрируем серверный (создаёт два аккаунта)
        client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user2@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": True,
            },
        )

        response = client.get("/api/auth/accounts")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Должно быть 3 записи: 1 клиентский + (серверный + клиентский) = 3
        assert len(data) == 3

    def test_login_by_id_success(self, client):
        """Успешный вход по public_id."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        public_id = reg.json()["public_id"]

        response = client.post(
            "/api/auth/login-by-id",
            json={
                "public_id": public_id,
                "password": "pass123456",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data

    def test_login_by_id_wrong_password(self, client):
        """Вход по public_id с неверным паролем."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        public_id = reg.json()["public_id"]

        response = client.post(
            "/api/auth/login-by-id",
            json={
                "public_id": public_id,
                "password": "wrong_password",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_credentials"

    def test_login_by_id_nonexistent(self, client):
        """Вход по несуществующему public_id."""
        response = client.post(
            "/api/auth/login-by-id",
            json={
                "public_id": "@NONEXISTENT-1234-5678.ru",
                "password": "pass123456",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_credentials"


# =============================================================================
# Тесты для лимитов аккаунтов
# =============================================================================

class TestApiAuthLimits:
    """Тесты для API эндпоинтов лимитов аккаунтов."""

    # ----- Тесты для клиентского лимита -----

    def test_get_client_limit_success(self, client):
        """Успешное получение информации о лимите клиентов."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": False,
            },
        )
        token = reg.json()["token"]

        response = client.get(
            "/api/auth/client-limit",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "client_count" in data
        assert "max_clients" in data
        assert "remaining" in data
        assert "can_create" in data
        assert data["max_clients"] == MAX_CLIENT_ACCOUNTS

    def test_get_client_limit_unauthorized(self, client):
        """Доступ к лимиту клиентов без авторизации."""
        response = client.get("/api/auth/client-limit")
        assert response.status_code == 401

    def test_register_client_exceeds_limit_via_api(self, client):
        """API: попытка регистрации 4-го клиентского аккаунта."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем 3 клиентских
            for i in range(MAX_CLIENT_ACCOUNTS):
                response = client.post(
                    "/api/auth/register",
                    json={
                        "seed_phrase": f"client{i}@example.com",
                        "password": "pass123456",
                        "region": "ru",
                        "is_server": False,
                    },
                    headers={"X-Forwarded-For": f"10.0.0.{i+1}"},
                )
                assert response.status_code == 200
                assert response.json()["success"] is True

            # "Перематываем время"
            mock_time.time.return_value = base_time + 25 * 3600

            # Пытаемся зарегистрировать 4-й
            response = client.post(
                "/api/auth/register",
                json={
                    "seed_phrase": "client3@example.com",
                    "password": "pass123456",
                    "region": "ru",
                    "is_server": False,
                },
                headers={"X-Forwarded-For": "10.0.0.99"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["error"] == "max_clients_reached"
            assert data["data"]["client_count"] == MAX_CLIENT_ACCOUNTS
            assert data["data"]["max_clients"] == MAX_CLIENT_ACCOUNTS

    # ----- Тесты для серверного лимита -----

    def test_get_server_limit_success(self, client):
        """Успешное получение информации о лимите серверов."""
        reg = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": True,
            },
        )
        token = reg.json()["token"]

        response = client.get(
            "/api/auth/server-limit",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "server_count" in data
        assert "max_servers" in data
        assert "can_create" in data
        assert data["max_servers"] == MAX_SERVER_ACCOUNTS

    def test_get_server_limit_unauthorized(self, client):
        """Доступ к лимиту серверов без авторизации."""
        response = client.get("/api/auth/server-limit")
        assert response.status_code == 401

    def test_register_server_success(self, client):
        """Регистрация первого серверного аккаунта."""
        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "server@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": True,
            },
            headers={"X-Forwarded-For": "10.0.0.1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server_id"] is not None
        assert data["server_id"].endswith(".srv")

    def test_register_server_exceeds_limit_via_api(self, client):
        """API: попытка регистрации второго серверного аккаунта."""
        # Регистрируем первый серверный
        response1 = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "server1@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": True,
            },
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert response1.status_code == 200
        assert response1.json()["success"] is True

        # Пытаемся зарегистрировать второй
        response2 = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "server2@example.com",
                "password": "pass123456",
                "region": "ru",
                "is_server": True,
            },
            headers={"X-Forwarded-For": "10.0.0.2"},
        )

        assert response2.status_code == 200
        data = response2.json()
        assert data["success"] is False
        assert data["error"] == "max_servers_reached"
        assert data["data"]["server_count"] == 1
        assert data["data"]["max_servers"] == 1

    def test_register_server_ignores_client_limit(self, client):
        """Серверный аккаунт можно создать даже если клиентских уже 3."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем 3 клиентских
            for i in range(MAX_CLIENT_ACCOUNTS):
                response = client.post(
                    "/api/auth/register",
                    json={
                        "seed_phrase": f"client{i}@example.com",
                        "password": "pass123456",
                        "region": "ru",
                        "is_server": False,
                    },
                    headers={"X-Forwarded-For": f"10.0.0.{i+1}"},
                )
                assert response.status_code == 200
                assert response.json()["success"] is True

            # "Перематываем время"
            mock_time.time.return_value = base_time + 25 * 3600

            # Регистрируем серверный
            response = client.post(
                "/api/auth/register",
                json={
                    "seed_phrase": "server@example.com",
                    "password": "pass123456",
                    "region": "ru",
                    "is_server": True,
                },
                headers={"X-Forwarded-For": "10.0.0.100"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["server_id"] is not None
