# tests/unit/test_web_multi_client.py
"""
Тесты для модуля мульти-клиента.
"""

import hashlib
import tempfile
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.identity.account import AccountManager
from src.common.identity.public_id import generate_public_id
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage
from src.web.multi_client import (
    create_multi_client_web_router,
    MAX_CLIENTS,
    set_test_mode,
    reset_client_manager,
)
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


def make_valid_public_id() -> str:
    seed_hash = hashlib.sha256(b"test_user_seed").digest()
    return generate_public_id(seed_hash, "ru", is_server=False)


@pytest.fixture(autouse=True)
def setup_test_mode():
    """Включаем тестовый режим и сбрасываем состояние перед каждым тестом."""
    set_test_mode(True)
    reset_client_manager()  # Сбрасываем состояние менеджера перед каждым тестом
    yield
    set_test_mode(False)


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
def router(account_manager, storage):
    return create_multi_client_web_router(account_manager, storage)


@pytest.fixture
def client(router, account_manager, test_user):
    app = FastAPI()
    app.include_router(router)

    login = account_manager.login(test_user["seed_phrase"], test_user["password"])
    assert login is not None
    token = login["token"]

    client = TestClient(app)
    client.cookies.set("token", token)
    return client


class TestWebMultiClient:
    """Тесты для мульти-клиента."""

    def test_create_client_success(self, client):
        """Успешное создание клиента."""
        response = client.post("/api/web/clients/create")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "client_id" in data
        assert "port" in data
        assert "url" in data
        assert data["port"] >= 8001
        assert data["port"] <= 8000 + MAX_CLIENTS

    def test_create_multiple_clients(self, client):
        """Создание нескольких клиентов."""
        ports = set()
        for i in range(MAX_CLIENTS):
            response = client.post("/api/web/clients/create")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            ports.add(data["port"])

        assert len(ports) == MAX_CLIENTS

    def test_max_clients_limit(self, client):
        """Проверка лимита клиентов."""
        # Создаём максимальное количество
        for i in range(MAX_CLIENTS):
            response = client.post("/api/web/clients/create")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

        # Пытаемся создать ещё одного
        response = client.post("/api/web/clients/create")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "max_clients_reached"

    def test_get_client_url(self, client):
        """Получение URL клиента."""
        # Создаём клиента
        create_response = client.post("/api/web/clients/create")
        assert create_response.status_code == 200
        data = create_response.json()
        assert data["success"] is True
        client_id = data["client_id"]

        # Даем время на запуск в тестовом режиме не нужно, но оставим для совместимости
        time.sleep(0.05)

        # Получаем URL
        response = client.get(f"/api/web/clients/{client_id}/url")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "url" in data["data"]
        assert "http://127.0.0.1:" in data["data"]["url"]

    def test_get_client_status(self, client):
        """Получение статуса клиента."""
        # Создаём клиента
        create_response = client.post("/api/web/clients/create")
        assert create_response.status_code == 200
        data = create_response.json()
        assert data["success"] is True
        client_id = data["client_id"]

        # Даем время на запуск
        time.sleep(0.05)

        # Получаем статус
        response = client.get(f"/api/web/clients/{client_id}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # В тестовом режиме статус сразу становится "running"
        assert data["data"]["status"] in ["starting", "running", "stopped"]
        assert "port" in data["data"]
        assert "created_at" in data["data"]
        assert "last_heartbeat" in data["data"]

    def test_get_client_not_found(self, client):
        """Получение несуществующего клиента."""
        response = client.get("/api/web/clients/nonexistent/url")
        assert response.status_code == 404

    def test_stop_client(self, client):
        """Остановка клиента."""
        # Создаём клиента
        create_response = client.post("/api/web/clients/create")
        assert create_response.status_code == 200
        data = create_response.json()
        assert data["success"] is True
        client_id = data["client_id"]

        # Даем время на запуск
        time.sleep(0.05)

        # Останавливаем
        response = client.post(f"/api/web/clients/{client_id}/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем статус после остановки
        status_response = client.get(f"/api/web/clients/{client_id}/status")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["data"]["status"] == "stopped"

    def test_delete_client(self, client):
        """Удаление клиента."""
        # Создаём клиента
        create_response = client.post("/api/web/clients/create")
        assert create_response.status_code == 200
        data = create_response.json()
        assert data["success"] is True
        client_id = data["client_id"]

        # Удаляем
        response = client.delete(f"/api/web/clients/{client_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем что клиент удален
        get_response = client.get(f"/api/web/clients/{client_id}/status")
        assert get_response.status_code == 404

    def test_list_clients(self, client):
        """Список всех клиентов."""
        # Создаём несколько клиентов
        created_clients = []
        for i in range(3):
            response = client.post("/api/web/clients/create")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            created_clients.append(data["client_id"])

        response = client.get("/api/web/clients")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["clients"]) == 3
        assert data["data"]["max_clients"] == MAX_CLIENTS
        assert data["data"]["total_clients"] == 3

    def test_client_heartbeat(self, client):
        """Heartbeat от клиента."""
        # Создаём клиента
        create_response = client.post("/api/web/clients/create")
        assert create_response.status_code == 200
        data = create_response.json()
        assert data["success"] is True
        client_id = data["client_id"]

        # Даем время на запуск
        time.sleep(0.05)

        # Получаем начальный heartbeat
        status_response = client.get(f"/api/web/clients/{client_id}/status")
        assert status_response.status_code == 200
        initial_heartbeat = status_response.json()["data"]["last_heartbeat"]

        # Ждем немного
        time.sleep(0.1)

        # Отправляем heartbeat
        response = client.post(f"/api/web/clients/heartbeat/{client_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем что heartbeat обновился
        status_response = client.get(f"/api/web/clients/{client_id}/status")
        assert status_response.status_code == 200
        updated_heartbeat = status_response.json()["data"]["last_heartbeat"]
        assert updated_heartbeat > initial_heartbeat

    def test_heartbeat_nonexistent_client(self, client):
        """Heartbeat для несуществующего клиента."""
        response = client.post("/api/web/clients/heartbeat/nonexistent")
        assert response.status_code == 404

    def test_unauthorized_access(self, router):
        """Неавторизованный доступ."""
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.post("/api/web/clients/create")
        assert response.status_code == 401

    def test_stop_nonexistent_client(self, client):
        """Остановка несуществующего клиента."""
        response = client.post("/api/web/clients/nonexistent/stop")
        assert response.status_code == 404

    def test_delete_nonexistent_client(self, client):
        """Удаление несуществующего клиента."""
        response = client.delete("/api/web/clients/nonexistent")
        assert response.status_code == 404
