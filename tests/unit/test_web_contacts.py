# tests/unit/test_web_contacts.py
"""
Тесты для модуля веб-контактов (только Invite Protocol).
"""

import hashlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.identity.account import AccountManager
from src.common.identity.public_id import generate_public_id
from src.client.messaging.invite import InviteProtocol
from src.client.messaging.spam_protection import SpamProtection
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.client.storage.contacts import ContactsStorage
from src.common.storage.sqlite import SQLiteStorage
from src.web.contacts import create_contacts_web_router
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


def make_valid_public_id() -> str:
    seed_hash = hashlib.sha256(b"test_contact_seed").digest()
    return generate_public_id(seed_hash, "ru", is_server=False)


def make_valid_server_id() -> str:
    seed_hash = hashlib.sha256(b"test_server_seed").digest()
    return generate_public_id(seed_hash, "ru", is_server=True)


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
def spam_protection(storage):
    return SpamProtection(storage)


@pytest.fixture
def invite_protocol(spam_protection, storage):
    return InviteProtocol(spam_protection, storage=storage)


@pytest.fixture
def rendezvous_client():
    mock = MagicMock(spec=RendezvousClient)
    mock.resolve_contact.return_value = None
    mock.find_server_by_id.return_value = None
    return mock


@pytest.fixture
def test_user(account_manager):
    result = account_manager.register(
        "user@example.com", "password123", False, "127.0.0.1"
    )
    assert result["success"]
    return {
        "public_id": result["public_id"],
        "account_id": result["account_id"],
        "seed_phrase": "user@example.com",
        "password": "password123",
    }


@pytest.fixture
def mock_message_router():
    mock = MagicMock()
    mock._get_dialog_state = MagicMock()
    return mock


@pytest.fixture
def router(account_manager, storage, rendezvous_client, invite_protocol, spam_protection, mock_message_router):
    return create_contacts_web_router(
        account_manager=account_manager,
        storage=storage,
        rendezvous_client=rendezvous_client,
        invite_protocol=invite_protocol,
        spam_protection=spam_protection,
        message_router=mock_message_router,
    )


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
    client._test_user = test_user
    return client


class TestWebContacts:
    """Тесты для веб-контактов (Invite Protocol)."""

    def test_get_contacts_empty(self, client):
        """Пустой список контактов."""
        response = client.get("/api/web/contacts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["contacts"]) == 0

    def test_get_invites_empty(self, client):
        """Получение пустого списка приглашений."""
        response = client.get("/api/web/invites")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["invites"]) == 0

    def test_search_by_public_id(self, client, rendezvous_client):
        """Поиск по Public ID."""
        public_id = make_valid_public_id()
        response = client.post(
            "/api/web/contacts/search",
            json={"query": public_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["results"]) == 1
        assert data["data"]["results"][0]["public_id"] == public_id
        assert data["data"]["results"][0]["type"] == "client"

    def test_search_by_server_id(self, client, rendezvous_client):
        """Поиск по серверному ID."""
        server_id = make_valid_server_id()
        rendezvous_client.find_server_by_id.return_value = {
            "public_id": server_id,
            "type": "nat",
            "region": "ru",
            "load": 45,
        }

        response = client.post(
            "/api/web/contacts/search",
            json={"query": server_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["results"]) == 1
        assert data["data"]["results"][0]["type"] == "nat"

    def test_search_by_region_mask(self, client, rendezvous_client):
        """Поиск по маске региона."""
        rendezvous_client.resolve_contact.return_value = {
            "type": "list",
            "items": [
                {"public_id": make_valid_server_id(), "type": "nat", "load": 45},
                {"public_id": make_valid_server_id(), "type": "nat", "load": 25},
            ],
        }

        response = client.post(
            "/api/web/contacts/search",
            json={"query": "@*.ru.srv"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["results"]) == 2

    def test_unauthorized_access(self, router):
        """Неавторизованный доступ."""
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.get("/api/web/contacts")
        assert response.status_code == 401
