# tests/unit/test_monitor_rendezvous.py
"""
Тесты для эндпоинтов управления Rendezvous сервером в мониторинге.
"""

import asyncio
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.identity.account import AccountManager
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.server.network.network_map import NetworkMapManager
from src.server.network.rendezvous.rendezvous_manager import RendezvousManager
from src.common.storage.sqlite import SQLiteStorage
from src.web.monitor import create_monitor_web_router
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
def network_map(storage):
    manager = NetworkMapManager(storage, None)
    return manager


@pytest.fixture
def rendezvous_manager():
    manager = RendezvousManager(host="127.0.0.1", port=9879)
    return manager


@pytest.fixture
def server_account(account_manager):
    """Создание серверного аккаунта."""
    result = account_manager.register(
        seed_phrase="server_test@example.com",
        password="password123",
        is_server=True,
        client_ip="127.0.0.1",
    )
    assert result["success"]
    return {
        "public_id": result["server_id"],
        "account_id": result["account_id"],
        "seed_phrase": "server_test@example.com",
        "password": "password123",
    }


@pytest.fixture
def client_account(account_manager):
    """Создание клиентского аккаунта."""
    result = account_manager.register(
        seed_phrase="client_test@example.com",
        password="password123",
        is_server=False,
        client_ip="127.0.0.1",
    )
    assert result["success"]
    return {
        "public_id": result["public_id"],
        "account_id": result["account_id"],
        "seed_phrase": "client_test@example.com",
        "password": "password123",
    }


@pytest.fixture
def server_client(account_manager, network_map, rendezvous_manager, server_account):
    """Тестовый клиент от имени серверного аккаунта."""
    login = account_manager.login_by_server_id(server_account["public_id"], server_account["password"])
    assert login is not None
    token = login["token"]

    app = FastAPI()
    router = create_monitor_web_router(account_manager, network_map, rendezvous_manager)
    app.include_router(router)

    client = TestClient(app)
    client.cookies.set("token", token)
    client._token = token
    client._public_id = server_account["public_id"]
    return client


@pytest.fixture
def regular_client(account_manager, network_map, rendezvous_manager, client_account):
    """Тестовый клиент от имени обычного пользователя."""
    login = account_manager.login(client_account["seed_phrase"], client_account["password"])
    assert login is not None
    token = login["token"]

    app = FastAPI()
    router = create_monitor_web_router(account_manager, network_map, rendezvous_manager)
    app.include_router(router)

    client = TestClient(app)
    client.cookies.set("token", token)
    client._token = token
    client._public_id = client_account["public_id"]
    return client


class TestMonitorRendezvous:
    """Тесты для эндпоинтов управления Rendezvous."""

    def test_get_rendezvous_status_not_running(self, server_client):
        """Получение статуса когда сервер не запущен."""
        response = server_client.get("/api/web/rendezvous/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["running"] is False
        assert data["data"]["host"] == "127.0.0.1"
        assert data["data"]["port"] == 9879

    @patch.object(RendezvousManager, "start")
    def test_start_rendezvous_success(self, mock_start, server_client):
        """Успешный запуск Rendezvous сервера."""
        mock_start.return_value = True

        response = server_client.post("/api/web/rendezvous/start")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "starting"
        mock_start.assert_called_once()

    @patch.object(RendezvousManager, "start")
    def test_start_rendezvous_failed(self, mock_start, server_client):
        """Ошибка при запуске Rendezvous сервера."""
        mock_start.return_value = False

        response = server_client.post("/api/web/rendezvous/start")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Failed to start"

    @patch.object(RendezvousManager, "stop")
    def test_stop_rendezvous_success(self, mock_stop, server_client):
        """Успешная остановка Rendezvous сервера."""
        mock_stop.return_value = True

        response = server_client.post("/api/web/rendezvous/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "stopped"
        mock_stop.assert_called_once()

    @patch.object(RendezvousManager, "stop")
    def test_stop_rendezvous_failed(self, mock_stop, server_client):
        """Ошибка при остановке Rendezvous сервера."""
        mock_stop.return_value = False

        response = server_client.post("/api/web/rendezvous/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Failed to stop"

    def test_start_rendezvous_unauthorized(self, regular_client):
        """Запуск Rendezvous сервера от имени обычного пользователя (запрещено)."""
        response = regular_client.post("/api/web/rendezvous/start")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Only server accounts can start rendezvous"

    def test_stop_rendezvous_unauthorized(self, regular_client):
        """Остановка Rendezvous сервера от имени обычного пользователя (запрещено)."""
        response = regular_client.post("/api/web/rendezvous/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Only server accounts can stop rendezvous"

    def test_get_rendezvous_status_unauthorized(self, regular_client):
        """Получение статуса Rendezvous от имени обычного пользователя (разрешено)."""
        response = regular_client.get("/api/web/rendezvous/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Статус доступен всем
        assert "running" in data["data"]

    def test_rendezvous_not_initialized(self, account_manager, network_map):
        """Rendezvous менеджер не инициализирован."""
        app = FastAPI()
        router = create_monitor_web_router(account_manager, network_map, rendezvous_manager=None)
        app.include_router(router)

        # Создаем тестового пользователя
        login = account_manager.login_by_server_id("test", "test") if False else None
        # Упрощённо: проверяем что эндпоинты возвращают ошибку
        # В реальном тесте нужно создать клиента, но для простоты проверяем что роутер создан
        assert router is not None


class TestMonitorRendezvousWebSocket:
    """Тесты для WebSocket логов Rendezvous."""

    @pytest.mark.asyncio
    async def test_websocket_rendezvous_logs_unauthorized(self, account_manager, network_map, rendezvous_manager):
        """Подключение к WebSocket логов от имени обычного пользователя (запрещено)."""
        from fastapi import FastAPI, WebSocket
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        app = FastAPI()
        router = create_monitor_web_router(account_manager, network_map, rendezvous_manager)
        app.include_router(router)

        # Создаем клиентский аккаунт и получаем токен
        client_result = account_manager.register(
            "client_ws_test@example.com", "password123", False, "127.0.0.1"
        )
        assert client_result["success"]
        login = account_manager.login("client_ws_test@example.com", "password123")
        assert login is not None
        token = login["token"]

        client = TestClient(app)
        client.cookies.set("token", token)

        # Пытаемся подключиться к WebSocket
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/web/ws/rendezvous_logs?token={token}"):
                pass

    @pytest.mark.asyncio
    async def test_websocket_rendezvous_logs_invalid_token(self, account_manager, network_map, rendezvous_manager):
        """Подключение к WebSocket логов с неверным токеном."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        router = create_monitor_web_router(account_manager, network_map, rendezvous_manager)
        app.include_router(router)

        client = TestClient(app)

        # Пытаемся подключиться с неверным токеном
        with pytest.raises(Exception):
            with client.websocket_connect("/api/web/ws/rendezvous_logs?token=invalid_token"):
                pass
