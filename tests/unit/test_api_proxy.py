# tests/unit/test_api_proxy.py
"""
Тесты для API прокси.
"""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api.proxy import create_proxy_router
from src.common.identity.account import AccountManager
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.server.proxy.client_crud import ClientManager
from src.common.storage.sqlite import SQLiteStorage
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
def account_manager(storage):
    rate_limiter = MultiRateLimiter()
    ws_manager = MockWebSocketManager()
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
        ws_manager=ws_manager,
    )


@pytest.fixture
def client_manager(storage, account_manager):
    return ClientManager(storage, account_manager)


@pytest.fixture
def server_user(account_manager):
    """Регистрация сервера."""
    result = account_manager.register(
        "server@example.com", "password123", True, "127.0.0.1"
    )
    assert result["success"], f"Server registration failed: {result}"
    return {
        "public_id": result["public_id"],
        "server_id": result["server_id"],
        "account_id": result["account_id"],
        "seed_phrase": "server@example.com",
        "password": "password123",
    }


@pytest.fixture
def regular_user(account_manager):
    """Регистрация обычного пользователя."""
    result = account_manager.register(
        "user@example.com", "password123", False, "127.0.0.1"
    )
    assert result["success"], f"User registration failed: {result}"
    return {
        "public_id": result["public_id"],
        "account_id": result["account_id"],
        "seed_phrase": "user@example.com",
        "password": "password123",
    }


@pytest.fixture
def server_client(account_manager, client_manager, server_user):
    """Тестовый клиент от имени сервера (используем server_id для входа)."""
    # Входим по server_id
    login = account_manager.login_by_server_id(server_user["server_id"], server_user["password"])
    assert login is not None, "Server login failed"

    app = FastAPI()
    router = create_proxy_router(account_manager, client_manager)
    app.include_router(router)

    client = TestClient(app)
    client.headers = {"Authorization": f"Bearer {login['token']}"}
    client._token = login["token"]
    client._public_id = server_user["server_id"]
    return client


@pytest.fixture
def regular_client(account_manager, client_manager, regular_user):
    """Тестовый клиент от имени обычного пользователя."""
    login = account_manager.login(regular_user["seed_phrase"], regular_user["password"])
    assert login is not None, "User login failed"

    app = FastAPI()
    router = create_proxy_router(account_manager, client_manager)
    app.include_router(router)

    client = TestClient(app)
    client.headers = {"Authorization": f"Bearer {login['token']}"}
    client._token = login["token"]
    client._public_id = regular_user["public_id"]
    return client


class TestApiProxy:
    """Тесты для API прокси."""

    def test_generate_invite_as_server(self, server_client):
        """Генерация приглашения от имени сервера."""
        response = server_client.post(
            "/api/proxy/invite",
            json={
                "client_name": "Телефон Маши",
                "expires_in": 86400,
                "group": "basic",
                "daily_limit_mb": 1024,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data
        assert "qr_code" in data
        assert data["expires_at"] > time.time()

    def test_generate_invite_as_regular_user(self, regular_client):
        """Генерация приглашения от имени обычного пользователя (запрещено)."""
        response = regular_client.post(
            "/api/proxy/invite",
            json={
                "client_name": "Телефон",
                "expires_in": 86400,
                "group": "basic",
            },
        )

        assert response.status_code == 403
        data = response.json()
        assert "not_a_server_owner" in data["detail"]

    def test_get_clients_empty(self, server_client):
        """Получение пустого списка клиентов."""
        response = server_client.get("/api/proxy/clients")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["clients"] == []
        assert data["total_clients"] == 0

    def test_get_clients_after_invite(self, server_client, account_manager, client_manager):
        """Получение списка клиентов после создания приглашений."""
        # Создаем несколько приглашений
        tokens = []
        for i in range(2):
            response = server_client.post(
                "/api/proxy/invite",
                json={"client_name": f"Клиент {i}", "group": "basic"},
            )
            assert response.status_code == 200
            tokens.append(response.json()["token"])

        # Регистрируем клиентов
        for i, token in enumerate(tokens):
            # Регистрируем нового пользователя как клиента
            client_result = account_manager.register(
                f"client{i}@example.com", "password123", False, "127.0.0.1"
            )
            assert client_result["success"]
            client_manager.add_client(token, client_result["public_id"])

        response = server_client.get("/api/proxy/clients")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_clients"] == 2

    def test_get_client_by_id(self, server_client, client_manager, account_manager):
        """Получение информации о клиенте по ID."""
        # Создаем приглашение
        invite = server_client.post(
            "/api/proxy/invite",
            json={"client_name": "Маша", "group": "basic"},
        ).json()
        token = invite["token"]

        # Регистрируем клиента
        client_result = account_manager.register(
            "masha@example.com", "password123", False, "127.0.0.1"
        )
        assert client_result["success"]

        # Имитируем подключение клиента
        client_manager.add_client(token, client_result["public_id"])

        # Получаем список клиентов
        clients_resp = server_client.get("/api/proxy/clients")
        clients = clients_resp.json()["clients"]
        assert len(clients) == 1
        client_id = clients[0]["client_id"]

        response = server_client.get(f"/api/proxy/clients/{client_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["client_id"] == client_id
        assert data["name"] == "Маша"
        assert data["group"] == "basic"

    def test_get_client_not_found(self, server_client):
        """Получение несуществующего клиента."""
        response = server_client.get("/api/proxy/clients/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "client_not_found" in data["detail"]

    def test_update_client(self, server_client, client_manager, account_manager):
        """Обновление настроек клиента."""
        # Создаем приглашение
        invite = server_client.post(
            "/api/proxy/invite",
            json={"client_name": "Маша", "group": "basic"},
        ).json()
        token = invite["token"]

        # Регистрируем клиента
        client_result = account_manager.register(
            "masha@example.com", "password123", False, "127.0.0.1"
        )
        assert client_result["success"]
        client_manager.add_client(token, client_result["public_id"])

        # Получаем список клиентов
        clients_resp = server_client.get("/api/proxy/clients")
        clients = clients_resp.json()["clients"]
        client_id = clients[0]["client_id"]

        response = server_client.patch(
            f"/api/proxy/clients/{client_id}",
            json={"group": "standard", "daily_limit_mb": 5120},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["client"]["group"] == "standard"
        assert data["client"]["daily_limit_mb"] == 5120

    def test_revoke_client(self, server_client, client_manager, account_manager):
        """Отзыв доступа клиента."""
        # Создаем приглашение
        invite = server_client.post(
            "/api/proxy/invite",
            json={"client_name": "Маша", "group": "basic"},
        ).json()
        token = invite["token"]

        # Регистрируем клиента
        client_result = account_manager.register(
            "masha@example.com", "password123", False, "127.0.0.1"
        )
        assert client_result["success"]
        client_manager.add_client(token, client_result["public_id"])

        # Получаем список клиентов
        clients_resp = server_client.get("/api/proxy/clients")
        clients = clients_resp.json()["clients"]
        client_id = clients[0]["client_id"]

        response = server_client.delete(f"/api/proxy/clients/{client_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем, что клиент удален
        clients_resp = server_client.get("/api/proxy/clients")
        assert len(clients_resp.json()["clients"]) == 0

    def test_get_stats(self, server_client):
        """Получение статистики."""
        response = server_client.get("/api/proxy/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "total_today_mb" in data
        assert "active_clients" in data
        assert "total_clients" in data

    def test_get_settings(self, server_client):
        """Получение настроек."""
        response = server_client.get("/api/proxy/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "max_clients" in data
        assert "default_daily_limit_mb" in data
        assert "default_group" in data
        assert "proxy_enabled" in data

    def test_update_settings(self, server_client):
        """Обновление настроек."""
        response = server_client.patch(
            "/api/proxy/settings",
            json={"max_clients": 20, "default_daily_limit_mb": 2048},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["max_clients"] == 20
        assert data["default_daily_limit_mb"] == 2048

    def test_reset_traffic(self, server_client):
        """Сброс трафика."""
        response = server_client.post("/api/proxy/reset-traffic")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["reset_count"] == 0

    def test_max_clients_limit(self, server_client, client_manager, account_manager):
        """Проверка лимита клиентов."""
        # Устанавливаем лимит 1
        server_client.patch("/api/proxy/settings", json={"max_clients": 1})

        # Создаем первое приглашение
        invite1 = server_client.post(
            "/api/proxy/invite",
            json={"client_name": "Клиент 1", "group": "basic"},
        ).json()
        token1 = invite1["token"]

        # Регистрируем первого клиента
        client1_result = account_manager.register(
            "client1@example.com", "password123", False, "127.0.0.1"
        )
        assert client1_result["success"]
        assert client_manager.add_client(token1, client1_result["public_id"]) is True

        # Создаем второе приглашение
        invite2 = server_client.post(
            "/api/proxy/invite",
            json={"client_name": "Клиент 2", "group": "basic"},
        ).json()
        token2 = invite2["token"]

        # Регистрируем второго клиента
        client2_result = account_manager.register(
            "client2@example.com", "password123", False, "127.0.0.1"
        )
        assert client2_result["success"]

        # Пытаемся добавить второго клиента (должно провалиться из-за лимита)
        result = client_manager.add_client(token2, client2_result["public_id"])
        assert result is False

    def test_unauthorized_access(self, account_manager, client_manager):
        """Неавторизованный доступ."""
        app = FastAPI()
        router = create_proxy_router(account_manager, client_manager)
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.get("/api/proxy/clients")
        assert response.status_code == 401
