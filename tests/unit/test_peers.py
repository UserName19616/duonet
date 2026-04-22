# tests/unit/test_peers.py
"""
Тесты для API эндпоинтов управления пирами (peers).
"""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api.peers import create_peers_router
from src.common.identity.account import AccountManager
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage
from src.server.storage.server_db import ServerDatabase, get_server_db
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


@pytest.fixture
def storage():
    """Фикстура для пользовательской БД."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def server_db():
    """Фикстура для серверной БД (очищается перед каждым тестом)."""
    with tempfile.NamedTemporaryFile(suffix="_server.db") as f:
        db = ServerDatabase(f.name)
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
def test_server_account(account_manager):
    """Создание тестового серверного аккаунта."""
    result = account_manager.register(
        seed_phrase="server@example.com test",
        password="password123",
        is_server=True,
        client_ip="127.0.0.1",
        region_override="ru",
    )
    assert result["success"]
    return {
        "account_id": result["account_id"],
        "server_id": result["server_id"],
        "seed_phrase": "server@example.com test",
        "password": "password123",
    }


@pytest.fixture
def router(account_manager, server_db):
    """Роутер для пиров с чистой БД."""
    # Подменяем глобальную БД для теста
    import src.server.storage.server_db as server_db_module
    original_db = server_db_module._server_db
    server_db_module._server_db = server_db

    router = create_peers_router(account_manager)

    yield router

    # Восстанавливаем
    server_db_module._server_db = original_db


@pytest.fixture
def client(router, account_manager, test_server_account, server_db):
    """Тестовый клиент с авторизацией и чистой БД."""
    app = FastAPI()
    app.include_router(router)

    # Получаем токен для серверного аккаунта
    login = account_manager.login_by_server_id(
        test_server_account["server_id"],
        test_server_account["password"]
    )
    assert login is not None
    token = login["token"]

    test_client = TestClient(app)
    test_client.cookies.set("token", token)
    test_client._token = token
    test_client._server_id = test_server_account["server_id"]
    test_client._server_db = server_db
    return test_client


class TestPeersAPI:
    """Тесты для API пиров."""

    def test_add_peer_success(self, client):
        """Успешное добавление пира."""
        response = client.post(
            "/api/peers/add",
            json={
                "peer_id": "@PEER-1234-5678.ru.srv",
                "ws_url": "wss://192.168.1.100:8443/ws",
                "region": "ru",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Peer" in data["message"]

    def test_add_peer_missing_fields(self, client):
        """Добавление пира с отсутствующими полями."""
        response = client.post(
            "/api/peers/add",
            json={"peer_id": "@TEST.ru.srv"}
        )
        assert response.status_code == 422  # Validation error

    def test_list_peers_empty(self, client):
        """Получение пустого списка пиров."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        response = client.get("/api/peers/list")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["peers"] == []
        assert data["total"] == 0

    def test_list_peers_with_data(self, client):
        """Получение списка пиров после добавления."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        # Добавляем двух пиров
        client.post("/api/peers/add", json={
            "peer_id": "@PEER1.ru.srv",
            "ws_url": "wss://192.168.1.100:8443/ws",
            "region": "ru",
        })
        client.post("/api/peers/add", json={
            "peer_id": "@PEER2.ru.srv",
            "ws_url": "wss://192.168.1.200:8443/ws",
            "region": "us",
        })

        response = client.get("/api/peers/list")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["peers"]) == 2
        assert data["total"] == 2

    def test_connect_to_peer(self, client):
        """Подключение к пиру."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        # Добавляем пира
        client.post("/api/peers/add", json={
            "peer_id": "@PEER.ru.srv",
            "ws_url": "wss://192.168.1.100:8443/ws",
            "region": "ru",
        })

        # Подключаемся
        response = client.post("/api/peers/@PEER.ru.srv/connect")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Connected" in data["message"]

        # Проверяем статус
        list_response = client.get("/api/peers/list")
        peers = list_response.json()["peers"]
        peer = next(p for p in peers if p["peer_id"] == "@PEER.ru.srv")
        assert peer["status"] == "connected"

    def test_connect_to_nonexistent_peer(self, client):
        """Подключение к несуществующему пиру."""
        response = client.post("/api/peers/@NONEXISTENT.ru.srv/connect")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Peer not found" in data["error"]

    def test_disconnect_from_peer(self, client):
        """Отключение от пира."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        # Добавляем и подключаем пира
        client.post("/api/peers/add", json={
            "peer_id": "@PEER.ru.srv",
            "ws_url": "wss://192.168.1.100:8443/ws",
            "region": "ru",
        })
        client.post("/api/peers/@PEER.ru.srv/connect")

        # Отключаемся
        response = client.post("/api/peers/@PEER.ru.srv/disconnect")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Disconnected" in data["message"]

        # Проверяем статус
        list_response = client.get("/api/peers/list")
        peers = list_response.json()["peers"]
        peer = next(p for p in peers if p["peer_id"] == "@PEER.ru.srv")
        assert peer["status"] == "disconnected"

    def test_delete_peer(self, client):
        """Удаление пира."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        # Добавляем пира
        client.post("/api/peers/add", json={
            "peer_id": "@PEER.ru.srv",
            "ws_url": "wss://192.168.1.100:8443/ws",
            "region": "ru",
        })

        # Удаляем
        response = client.delete("/api/peers/@PEER.ru.srv")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "deleted" in data["message"]

        # Проверяем, что пир удалён
        list_response = client.get("/api/peers/list")
        assert len(list_response.json()["peers"]) == 0

    def test_delete_nonexistent_peer(self, client):
        """Удаление несуществующего пира."""
        response = client.delete("/api/peers/@NONEXISTENT.ru.srv")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "deleted" in data["message"]

    def test_reconnect_all(self, client):
        """Переподключение ко всем пирам."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        # Добавляем двух пиров
        client.post("/api/peers/add", json={
            "peer_id": "@PEER1.ru.srv",
            "ws_url": "wss://192.168.1.100:8443/ws",
            "region": "ru",
        })
        client.post("/api/peers/add", json={
            "peer_id": "@PEER2.ru.srv",
            "ws_url": "wss://192.168.1.200:8443/ws",
            "region": "us",
        })

        response = client.post("/api/peers/reconnect-all")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Reconnected" in data["message"]

    def test_get_server_info(self, client, test_server_account):
        """Получение информации о сервере."""
        response = client.get("/api/peers/server-info")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert "local_ips" in data["data"]
        assert "ws_url" in data["data"]
        assert "is_public" in data["data"]

    def test_peer_persistence(self, client):
        """Проверка сохранения пиров в БД."""
        # Очищаем БД перед тестом
        with client._server_db._transaction() as conn:
            conn.execute("DELETE FROM peers")

        # Добавляем пира
        client.post("/api/peers/add", json={
            "peer_id": "@PERSISTENT.ru.srv",
            "ws_url": "wss://192.168.1.100:8443/ws",
            "region": "ru",
        })

        # Проверяем, что пир сохранился (данные в БД)
        response = client.get("/api/peers/list")
        assert response.status_code == 200
        data = response.json()
        assert len(data["peers"]) == 1
        assert data["peers"][0]["peer_id"] == "@PERSISTENT.ru.srv"


class TestPeersWithoutAuth:
    """Тесты для API пиров без авторизации."""

    def test_list_peers_unauthorized(self, router):
        """Доступ без авторизации."""
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.get("/api/peers/list")
        assert response.status_code == 200

    def test_add_peer_unauthorized(self, router):
        """Добавление пира без авторизации."""
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.post(
            "/api/peers/add",
            json={
                "peer_id": "@TEST.ru.srv",
                "ws_url": "wss://test:8443/ws",
            }
        )
        assert response.status_code == 200
