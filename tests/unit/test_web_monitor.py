# tests/unit/test_web_monitor.py
"""
Тесты для модуля веб-мониторинга.
"""

import asyncio
import hashlib
import json
import tempfile
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.identity.account import AccountManager
from src.common.identity.public_id import generate_public_id
from src.server.network.network_map import NetworkMapManager, NetworkNode
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage
from src.web.monitor import create_monitor_web_router, _monitor_manager
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


def make_valid_public_id() -> str:
    """Генерирует валидный Public ID для тестов."""
    seed_hash = hashlib.sha256(b"test_user_seed").digest()
    return generate_public_id(seed_hash, "ru", is_server=False)


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
def test_user(account_manager):
    public_id = make_valid_public_id()
    seed_phrase = f"user_{public_id}"
    result = account_manager.register(seed_phrase, "password123", False, "127.0.0.1")
    assert result["success"]
    return {
        "public_id": result["public_id"],
        "account_id": result["account_id"],
        "seed_phrase": seed_phrase,
        "password": "password123",
    }


@pytest.fixture
def router(account_manager, network_map):
    return create_monitor_web_router(account_manager, network_map)


@pytest.fixture
def client(router, account_manager, test_user):
    app = FastAPI()
    app.include_router(router)

    login = account_manager.login(test_user["seed_phrase"], test_user["password"])
    assert login is not None
    token = login["token"]

    client = TestClient(app)
    client.cookies.set("token", token)
    client._token = token
    client._public_id = test_user["public_id"]
    client._account_manager = account_manager
    return client


class TestWebMonitor:
    """Тесты для веб-мониторинга."""

    def test_get_status(self, client):
        """Получение статуса сервера."""
        response = client.get("/api/web/monitor/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "status" in data["data"]
        assert "uptime" in data["data"]
        assert "active_connections" in data["data"]

    def test_get_nodes_empty(self, client):
        """Получение пустого списка узлов."""
        response = client.get("/api/web/monitor/nodes")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["nodes"] == []

    def test_get_logs_empty(self, client):
        """Получение пустого лога."""
        # Очищаем лог перед тестом
        from src.web.monitor import _monitor_manager
        _monitor_manager.clear_logs()

        response = client.get("/api/web/monitor/logs")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["logs"] == []

    def test_clear_logs(self, client):
        """Очистка лога."""
        # Добавляем тестовый лог
        _monitor_manager.add_log("Test log message", "info")

        # Проверяем, что лог не пуст
        response = client.get("/api/web/monitor/logs")
        assert len(response.json()["data"]["logs"]) > 0

        # Очищаем лог
        response = client.post("/api/web/monitor/logs/clear")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем, что лог пуст
        response = client.get("/api/web/monitor/logs")
        assert len(response.json()["data"]["logs"]) == 0

    def test_unauthorized_access(self, router):
        """Неавторизованный доступ."""
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.get("/api/web/monitor/status")
        assert response.status_code == 401

    def test_add_node_and_get_nodes(self, client, network_map):
        """Добавление узла и получение списка узлов."""
        # Создаем тестовый узел
        node = NetworkNode(
            node_id="test_node_1",
            node_type="client",
            address="192.168.1.100",
            port=8080,
            ws_url="ws://192.168.1.100:8080",
            public_id="test_public_id",
        )

        # Добавляем узел (синхронно через asyncio)
        async def add_node():
            await network_map.add_node(node)

        asyncio.run(add_node())

        # Получаем список узлов
        response = client.get("/api/web/monitor/nodes")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["nodes"]) >= 1

        # Находим наш узел
        found = False
        for n in data["data"]["nodes"]:
            if n["node_id"] == "test_node_1":
                found = True
                assert n["node_type"] == "client"
                assert n["address"] == "192.168.1.100"
                assert n["port"] == 8080
                break
        assert found is True

    @pytest.mark.asyncio
    async def test_websocket_monitor_connect_valid_token(self, client, test_user, storage, network_map):
        """Подключение WebSocket мониторинга с валидным токеном."""
        import websockets
        from uvicorn import Server, Config

        # Подавляем deprecation warnings
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        # Создаём приложение с роутером
        app = FastAPI()
        router = create_monitor_web_router(client._account_manager, network_map)
        app.include_router(router)

        # Запускаем сервер в отдельном потоке
        config = Config(app=app, host="127.0.0.1", port=8891, log_level="error")
        server = Server(config)

        server_thread = threading.Thread(target=server.run)
        server_thread.daemon = True
        server_thread.start()

        await asyncio.sleep(0.5)

        try:
            uri = f"ws://127.0.0.1:8891/api/web/ws/monitor?token={client._token}"

            async with websockets.connect(uri) as websocket:
                # Получаем начальное состояние
                response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                data = json.loads(response)

                assert data["type"] == "server_status"
                assert data["data"]["status"] == "online"

        finally:
            server.should_exit = True
            server_thread.join(timeout=2)

    @pytest.mark.asyncio
    async def test_websocket_monitor_connect_invalid_token(self, client, storage, network_map):
        """Подключение WebSocket мониторинга с невалидным токеном."""
        import websockets
        from uvicorn import Server, Config

        # Подавляем deprecation warnings
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        app = FastAPI()
        router = create_monitor_web_router(client._account_manager, network_map)
        app.include_router(router)

        config = Config(app=app, host="127.0.0.1", port=8892, log_level="error")
        server = Server(config)

        server_thread = threading.Thread(target=server.run)
        server_thread.daemon = True
        server_thread.start()

        await asyncio.sleep(0.5)

        try:
            uri = "ws://127.0.0.1:8892/api/web/ws/monitor?token=invalid_token"

            # Невалидный токен должен вызвать ошибку подключения
            with pytest.raises(Exception):
                async with websockets.connect(uri, close_timeout=2) as websocket:
                    await asyncio.wait_for(websocket.recv(), timeout=1.0)

        finally:
            server.should_exit = True
            server_thread.join(timeout=2)
