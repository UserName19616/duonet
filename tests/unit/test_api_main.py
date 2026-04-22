# tests/unit/test_api_main.py
"""
Тесты для главного модуля API.
"""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.server.api.main import create_app
from src.common.identity.account import AccountManager
from src.common.identity.recovery import RecoveryService
from src.client.messaging.message_router import MessageRouter
from src.client.messaging.spam_protection import SpamProtection
from src.client.messaging.invite import InviteProtocol
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.server.network.network_map import NetworkMapManager
from src.server.proxy.client_crud import ClientManager
from src.client.storage.contacts import ContactsStorage
from src.client.storage.messages import MessagesStorage
from src.common.storage.sqlite import SQLiteStorage
from src.server.api.websocket import WebSocketManager


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
    ws_manager = WebSocketManager()
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
        ws_manager=ws_manager,
    )


@pytest.fixture
def recovery_service(storage, account_manager):
    return RecoveryService(storage, account_manager)


@pytest.fixture
def rate_limiter():
    return MultiRateLimiter()


@pytest.fixture
def ws_manager():
    return WebSocketManager()


@pytest.fixture
def spam_protection(storage):
    return SpamProtection(storage)


@pytest.fixture
def invite_protocol(spam_protection):
    return InviteProtocol(spam_protection)


@pytest.fixture
def rendezvous_client():
    return MagicMock(spec=RendezvousClient)


@pytest.fixture
def client_manager(storage, account_manager):
    return ClientManager(storage, account_manager)


@pytest.fixture
def contacts_storage(storage, account_manager):
    user_id = b"\x01" * 20
    return ContactsStorage(storage, user_id)


@pytest.fixture
def messages_storage(storage, account_manager):
    user_id = b"\x01" * 20
    return MessagesStorage("duonet.db")


@pytest.fixture
def message_router(account_manager, messages_storage, invite_protocol, ws_manager):
    return MessageRouter(
        account_manager=account_manager,
        messages_storage=messages_storage,
        invite_protocol=invite_protocol,
        ws_manager=ws_manager,
    )


@pytest.fixture
def network_map(storage, ws_manager):
    return NetworkMapManager(storage, ws_manager)


@pytest.fixture
def app(
    account_manager,
    recovery_service,
    message_router,
    client_manager,
    rendezvous_client,
    rate_limiter,
    ws_manager,
    contacts_storage,
    messages_storage,
    storage,
    network_map,
):
    return create_app(
        account_manager=account_manager,
        recovery_service=recovery_service,
        message_router=message_router,
        client_manager=client_manager,
        rendezvous_client=rendezvous_client,
        rate_limiter=rate_limiter,
        ws_manager=ws_manager,
        jwt_secret="test_secret",
        geoip_func=mock_geoip,
        contacts_storage=contacts_storage,
        messages_storage=messages_storage,
        storage=storage,
        network_map=network_map,
        rendezvous_manager=None,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


class TestApiMain:
    """Тесты для главного модуля API."""

    def test_health_endpoint(self, client):
        """Проверка эндпоинта /health."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "uptime" in data
        assert "load" in data

    def test_ready_endpoint(self, client):
        """Проверка эндпоинта /ready."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert "ready" in data

    def test_docs_available(self, client):
        """Проверка доступности Swagger документации."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_available(self, client):
        """Проверка доступности ReDoc документации."""
        response = client.get("/redoc")
        assert response.status_code == 200

    def test_openapi_json(self, client):
        """Проверка доступности OpenAPI JSON."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "DuoNet API"
        assert data["info"]["version"] == "2.0.0"

    def test_auth_routes_registered(self, client):
        """Проверка, что роутер auth зарегистрирован."""
        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "test",
                "password": "test123456",
            },
        )
        # Не проверяем успех, только что эндпоинт существует
        assert response.status_code != 404

    def test_contacts_routes_registered(self, client):
        """Проверка, что роутер contacts зарегистрирован."""
        response = client.get("/api/contacts")
        assert response.status_code == 401  # требует авторизации, но эндпоинт существует

    def test_messages_routes_registered(self, client):
        """Проверка, что роутер messages зарегистрирован."""
        response = client.post(
            "/api/messages/send",
            json={
                "to": "@TEST.ru",
                "encrypted": "test",
                "has_phrase": False,
            },
        )
        assert response.status_code == 401  # требует авторизации

    def test_proxy_routes_registered(self, client):
        """Проверка, что роутер proxy зарегистрирован."""
        response = client.get("/api/proxy/clients")
        assert response.status_code == 401  # требует авторизации

    def test_404_handler(self, client):
        """Проверка обработчика 404."""
        response = client.get("/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_cors_configuration(self, app):
        """Проверка, что CORS middleware добавлен."""
        from fastapi.middleware.cors import CORSMiddleware

        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls == CORSMiddleware:
                cors_middleware = middleware
                break
        assert cors_middleware is not None

    def test_websocket_route_registered(self, app):
        """Проверка, что WebSocket эндпоинт зарегистрирован."""
        routes = [route for route in app.routes if route.path == "/ws"]
        assert len(routes) == 1

    def test_validation_exception_handler(self, client):
        """Проверка обработчика ошибок валидации."""
        response = client.post(
            "/api/auth/register",
            json={
                "seed_phrase": "test",
                # password отсутствует
            },
        )
        assert response.status_code == 400
