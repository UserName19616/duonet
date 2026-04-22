# tests/unit/test_api_server_db.py
"""
Тесты для API эндпоинтов серверной БД.
"""

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api.server_db import create_server_db_router
from src.server.storage.server_db import ServerDatabase


@pytest.fixture
def temp_db():
    """Фикстура для временной БД."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = ServerDatabase(f.name)
        yield db
        db.close()


@pytest.fixture
def client(temp_db):
    """Тестовый клиент."""
    app = FastAPI()
    router = create_server_db_router(temp_db)
    app.include_router(router)
    return TestClient(app)


class TestApiServerDB:
    """Тесты для API серверной БД."""

    def test_health_check(self, client):
        """Проверка health эндпоинта."""
        response = client.get("/api/server-db/health")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Server DB healthy" in data["message"]

    def test_get_servers_empty(self, client):
        """Получение пустого списка серверов."""
        response = client.get("/api/server-db/servers")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["servers"] == []
        assert data["total"] == 0

    def test_add_server(self, client):
        """Добавление сервера."""
        response = client.post(
            "/api/server-db/servers",
            json={
                "server_id": "@TEST-1234-5678.ru.srv",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
                "status": "active",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "added/updated" in data["message"]

    def test_get_server_by_id(self, client, temp_db):
        """Получение сервера по ID."""
        # Добавляем сервер напрямую
        temp_db.add_server(
            server_id="@TEST.ru.srv",
            region="ru",
            ws_url="wss://test.local:9877",
        )

        response = client.get("/api/server-db/servers/@TEST.ru.srv")
        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == "@TEST.ru.srv"
        assert data["region"] == "ru"
        assert data["ws_url"] == "wss://test.local:9877"
        assert data["status"] == "active"

    def test_get_server_not_found(self, client):
        """Получение несуществующего сервера."""
        response = client.get("/api/server-db/servers/@NONEXISTENT.ru.srv")
        assert response.status_code == 404

    def test_get_servers_by_region(self, client, temp_db):
        """Получение серверов по региону."""
        temp_db.add_server("@A.ru.srv", "ru", "wss://a:9877")
        temp_db.add_server("@B.ru.srv", "ru", "wss://b:9877")
        temp_db.add_server("@C.us.srv", "us", "wss://c:9877")

        response = client.get("/api/server-db/servers?region=ru")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["servers"]) == 2

    def test_server_heartbeat(self, client, temp_db):
        """Обновление heartbeat сервера."""
        temp_db.add_server("@TEST.ru.srv", "ru", "wss://test:9877")

        response = client.post("/api/server-db/servers/@TEST.ru.srv/heartbeat")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_server_heartbeat_not_found(self, client):
        """Heartbeat для несуществующего сервера."""
        response = client.post("/api/server-db/servers/@NONEXISTENT.ru.srv/heartbeat")
        assert response.status_code == 404

    def test_get_clients_empty(self, client):
        """Получение пустого списка клиентов."""
        response = client.get("/api/server-db/clients")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["clients"] == []
        assert data["total"] == 0

    def test_add_client(self, client, temp_db):
        """Добавление клиента."""
        # Сначала добавляем сервер
        temp_db.add_server("@SERVER.ru.srv", "ru", "wss://server:9877")

        response = client.post(
            "/api/server-db/clients",
            json={
                "client_id": "@CLIENT.ru",
                "server_id": "@SERVER.ru.srv",
                "region": "ru",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "added" in data["message"]

    def test_get_clients_with_data(self, client, temp_db):
        """Получение списка клиентов с данными."""
        temp_db.add_server("@SERVER.ru.srv", "ru", "wss://server:9877")
        temp_db.add_client("@CLIENT1.ru", "@SERVER.ru.srv", "ru")
        temp_db.add_client("@CLIENT2.ru", "@SERVER.ru.srv", "ru")

        response = client.get("/api/server-db/clients")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["clients"]) == 2

    def test_get_clients_by_region(self, client, temp_db):
        """Получение клиентов по региону."""
        temp_db.add_server("@SERVER.ru.srv", "ru", "wss://server:9877")
        temp_db.add_client("@CLIENT1.ru", "@SERVER.ru.srv", "ru")
        temp_db.add_client("@CLIENT2.ru", "@SERVER.ru.srv", "ru")

        response = client.get("/api/server-db/clients?region=ru")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    def test_get_stats(self, client, temp_db):
        """Получение статистики."""
        # Добавляем данные
        temp_db.add_server("@S1.ru.srv", "ru", "wss://s1:9877")
        temp_db.add_server("@S2.ru.srv", "ru", "wss://s2:9877")
        temp_db.add_client("@C1.ru", "@S1.ru.srv", "ru")
        temp_db.add_client("@C2.ru", "@S2.ru.srv", "ru")
        temp_db.update_network_node("node1", "127.0.0.1", 9877, "nat", [])

        response = client.get("/api/server-db/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_servers"] == 2
        assert data["total_clients"] == 2
        assert data["network_nodes"] == 1
        assert data["pending_sync"] == 0

    def test_sync_request(self, client):
        """Добавление задачи синхронизации."""
        response = client.post(
            "/api/server-db/sync",
            json={
                "target_server_id": "@OTHER.ru.srv",
                "data": {"test": "data"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Sync task added" in data["message"]

    def test_get_pending_sync(self, client, temp_db):
        """Получение задач синхронизации."""
        # Добавляем задачу
        temp_db.add_to_sync_queue("@OTHER.ru.srv", "test", {"data": "value"})

        response = client.get("/api/server-db/sync/pending")
        assert response.status_code == 200
        data = response.json()
        print(f"DEBUG: {data}")  # Добавить эту строку
        assert data["success"] is True
        assert data["data"]["count"] == 1
        assert len(data["data"]["pending"]) == 1

    def test_add_server_invalid_region(self, client):
        """Добавление сервера с неверным регионом."""
        response = client.post(
            "/api/server-db/servers",
            json={
                "server_id": "@TEST.ru.srv",
                "region": "rus",  # 3 буквы, должно быть 2
                "ws_url": "wss://test:9877",
            },
        )
        assert response.status_code == 422  # Pydantic validation error

    def test_add_server_missing_fields(self, client):
        """Добавление сервера с отсутствующими полями."""
        response = client.post(
            "/api/server-db/servers",
            json={
                "server_id": "@TEST.ru.srv",
                # region отсутствует
            },
        )
        assert response.status_code == 422


class TestApiServerDBAuth:
    """Тесты для API серверной БД (без авторизации)."""

    def test_all_endpoints_accessible_without_auth(self, temp_db):
        """Все эндпоинты доступны без авторизации (для прототипа)."""
        app = FastAPI()
        router = create_server_db_router(temp_db)
        app.include_router(router)
        client = TestClient(app)

        # Проверяем несколько эндпоинтов
        response = client.get("/api/server-db/health")
        assert response.status_code == 200

        response = client.get("/api/server-db/servers")
        assert response.status_code == 200

        response = client.get("/api/server-db/stats")
        assert response.status_code == 200


class TestApiServerDBIntegration:
    """Интеграционные тесты."""

    def test_full_flow(self, client, temp_db):
        """Полный сценарий: сервер → клиент → статистика."""
        # 1. Добавляем сервер
        response = client.post(
            "/api/server-db/servers",
            json={
                "server_id": "@MAIN.ru.srv",
                "region": "ru",
                "ws_url": "wss://main.local:9877",
            },
        )
        assert response.status_code == 200

        # 2. Добавляем клиента
        response = client.post(
            "/api/server-db/clients",
            json={
                "client_id": "@ALICE.ru",
                "server_id": "@MAIN.ru.srv",
                "region": "ru",
            },
        )
        assert response.status_code == 200

        # 3. Проверяем статистику
        response = client.get("/api/server-db/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_servers"] == 1
        assert data["total_clients"] == 1

        # 4. Получаем список серверов
        response = client.get("/api/server-db/servers")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["servers"][0]["server_id"] == "@MAIN.ru.srv"

        # 5. Получаем список клиентов
        response = client.get("/api/server-db/clients")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["clients"][0]["client_id"] == "@ALICE.ru"
