# tests/unit/test_api_auth_limits.py
"""
Тесты для API эндпоинтов лимитов аккаунтов.
"""

import tempfile
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api.auth import create_auth_router
from src.common.identity.account import AccountManager, MAX_CLIENT_ACCOUNTS, MAX_SERVER_ACCOUNTS
from src.common.identity.recovery import RecoveryService
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage


def mock_geoip(ip):
    return "ru"


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def rate_limiter():
    return MultiRateLimiter()


@pytest.fixture
def account_manager(storage, rate_limiter):
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
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
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestApiAuthClientLimit:
    """Тесты для API эндпоинтов лимита клиентских аккаунтов."""

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
        """API: попытка регистрации 4-го клиентского аккаунта (лимит 3)."""
        # Мокаем время для обхода rate limiter
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем первые 3 аккаунта с разными IP
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

            # "Перематываем время" на 25 часов вперёд
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


class TestApiAuthServerLimit:
    """Тесты для API эндпоинтов лимита серверных аккаунтов."""

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

    def test_register_second_server_fails_via_api(self, client):
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
        # Мокаем время для обхода rate limiter
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем 3 клиентских с разными IP
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

            # Регистрируем серверный (должен пройти)
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
