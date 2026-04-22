# tests/unit/test_api_contacts.py
"""
Тесты для API контактов.
"""

import hashlib
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api.contacts import create_contacts_router
from src.common.identity.account import AccountManager
from src.common.identity.public_id import generate_public_id
from src.client.messaging.invite import InviteProtocol
from src.client.messaging.spam_protection import SpamProtection
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.client.storage.contacts import ContactsStorage
from src.common.storage.sqlite import SQLiteStorage

# Импортируем заглушку WebSocketManager
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
def spam_protection(storage):
    return SpamProtection(storage)


@pytest.fixture
def invite_protocol(spam_protection):
    return InviteProtocol(spam_protection)


@pytest.fixture
def rendezvous_client():
    mock = MagicMock(spec=RendezvousClient)
    mock.resolve_contact.return_value = None
    mock.find_server_by_id.return_value = None
    return mock


@pytest.fixture
def contacts_storage(storage, account_manager):
    # Создаем хранилище для тестового пользователя
    user_id = b"\x01" * 20
    return ContactsStorage(storage, user_id)


@pytest.fixture
def test_user(account_manager):
    # Регистрируем тестового пользователя с seed фразой
    seed_phrase = "test_seed_phrase_for_testing_purposes_only"
    password = "password123"

    result = account_manager.register(
        seed_phrase, password, False, "127.0.0.1"
    )
    assert result["success"], f"Registration failed: {result}"
    return {
        "public_id": result["public_id"],
        "account_id": result["account_id"],
        "seed_phrase": seed_phrase,
        "password": password,
    }


@pytest.fixture
def router(account_manager, contacts_storage, rendezvous_client, invite_protocol, spam_protection):
    return create_contacts_router(
        account_manager=account_manager,
        contacts_storage=contacts_storage,
        rendezvous_client=rendezvous_client,
        invite_protocol=invite_protocol,
        spam_protection=spam_protection,
    )


@pytest.fixture
def client(router, account_manager, test_user):
    """Создание тестового клиента с авторизацией."""
    app = FastAPI()
    app.include_router(router)

    # Логинимся
    login_result = account_manager.login(test_user["seed_phrase"], test_user["password"])
    assert login_result is not None, "Login failed"
    token = login_result["token"]

    client = TestClient(app)
    client.headers = {"Authorization": f"Bearer {token}"}
    client._token = token
    client._public_id = test_user["public_id"]
    return client


class TestApiContacts:
    """Тесты для API контактов."""

    def test_get_contacts_empty(self, client):
        """Получение пустого списка контактов."""
        response = client.get("/api/contacts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["contacts"] == []

    def test_add_contact_success(self, client):
        """Успешное добавление контакта."""
        # Генерируем валидный Public ID
        seed_hash = hashlib.sha256(b"contact_seed_for_testing").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        response = client.post(
            "/api/contacts",
            json={
                "public_id": contact_id,
                "name": "Тестовый контакт",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_add_contact_self(self, client):
        """Добавление себя в контакты."""
        response = client.post(
            "/api/contacts",
            json={
                "public_id": client._public_id,
                "name": "Я",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "cannot_add_self" in data["detail"]

    def test_add_contact_server(self, client):
        """Добавление сервера в контакты."""
        seed_hash = hashlib.sha256(b"server_seed_for_testing").digest()
        server_id = generate_public_id(seed_hash, "ru", is_server=True)

        response = client.post(
            "/api/contacts",
            json={
                "public_id": server_id,
                "name": "Сервер",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "cannot_add_server" in data["detail"]

    def test_add_contact_invalid_format(self, client):
        """Добавление контакта с невалидным форматом."""
        response = client.post(
            "/api/contacts",
            json={
                "public_id": "invalid_id",
                "name": "Контакт",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "invalid_public_id" in data["detail"]

    def test_add_contact_duplicate(self, client):
        """Добавление уже существующего контакта."""
        seed_hash = hashlib.sha256(b"contact_seed_duplicate").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        # Первое добавление
        response1 = client.post(
            "/api/contacts",
            json={
                "public_id": contact_id,
                "name": "Контакт",
            },
        )
        assert response1.status_code == 200

        # Второе добавление
        response2 = client.post(
            "/api/contacts",
            json={
                "public_id": contact_id,
                "name": "Другой контакт",
            },
        )

        assert response2.status_code == 400
        data = response2.json()
        assert "contact_already_exists" in data["detail"]

    def test_get_contacts_with_data(self, client):
        """Получение списка контактов с данными."""
        seed_hash1 = hashlib.sha256(b"contact1_seed").digest()
        contact1 = generate_public_id(seed_hash1, "ru", is_server=False)
        seed_hash2 = hashlib.sha256(b"contact2_seed").digest()
        contact2 = generate_public_id(seed_hash2, "ru", is_server=False)

        client.post("/api/contacts", json={"public_id": contact1, "name": "Контакт 1"})
        client.post("/api/contacts", json={"public_id": contact2, "name": "Контакт 2"})

        response = client.get("/api/contacts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["contacts"]) == 2

        # Проверяем, что оба контакта есть
        names = [c["name"] for c in data["contacts"]]
        assert "Контакт 1" in names
        assert "Контакт 2" in names

    def test_update_contact_name(self, client):
        """Обновление имени контакта."""
        seed_hash = hashlib.sha256(b"contact_seed_update").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        client.post("/api/contacts", json={"public_id": contact_id, "name": "Старое имя"})

        response = client.patch(
            f"/api/contacts/{contact_id}",
            json={"name": "Новое имя"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["name"] == "Новое имя"

        # Проверяем, что имя обновилось
        get_response = client.get("/api/contacts")
        contacts = get_response.json()["contacts"]
        updated_contact = next(c for c in contacts if c["public_id"] == contact_id)
        assert updated_contact["name"] == "Новое имя"

    def test_update_contact_not_found(self, client):
        """Обновление несуществующего контакта."""
        response = client.patch(
            "/api/contacts/@NONEXISTENT-1234-5678.ru",
            json={"name": "Новое имя"},
        )

        assert response.status_code == 404
        data = response.json()
        assert "contact_not_found" in data["detail"]

    def test_delete_contact(self, client):
        """Удаление контакта."""
        seed_hash = hashlib.sha256(b"contact_seed_delete").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        client.post("/api/contacts", json={"public_id": contact_id, "name": "Контакт"})

        # Проверяем, что контакт добавился
        get_before = client.get("/api/contacts")
        assert len(get_before.json()["contacts"]) == 1

        # Удаляем
        response = client.delete(f"/api/contacts/{contact_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем, что контакт удален
        get_after = client.get("/api/contacts")
        assert len(get_after.json()["contacts"]) == 0

    def test_delete_contact_not_found(self, client):
        """Удаление несуществующего контакта."""
        response = client.delete("/api/contacts/@NONEXISTENT-1234-5678.ru")
        assert response.status_code == 404
        data = response.json()
        assert "contact_not_found" in data["detail"]

    def test_set_phrase(self, client):
        """Установка дополнительной фразы."""
        seed_hash = hashlib.sha256(b"contact_seed_phrase").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        client.post("/api/contacts", json={"public_id": contact_id, "name": "Контакт"})

        response = client.post(
            f"/api/contacts/{contact_id}/phrase",
            json={"phrase": "зеленый дом"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["phrase_known"] is True

    def test_delete_phrase(self, client):
        """Удаление дополнительной фразы."""
        seed_hash = hashlib.sha256(b"contact_seed_phrase_delete").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        client.post("/api/contacts", json={"public_id": contact_id, "name": "Контакт"})
        client.post(f"/api/contacts/{contact_id}/phrase", json={"phrase": "зеленый дом"})

        response = client.delete(f"/api/contacts/{contact_id}/phrase")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_search_by_public_id(self, client, rendezvous_client):
        """Поиск по Public ID."""
        seed_hash = hashlib.sha256(b"server_seed_search").digest()
        server_id = generate_public_id(seed_hash, "ru", is_server=True)

        rendezvous_client.find_server_by_id.return_value = {
            "public_id": server_id,
            "type": "nat",
            "region": "ru",
            "load": 0,
        }

        response = client.get(f"/api/search?q={server_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 1
        assert data["results"][0]["public_id"] == server_id

    def test_search_by_region_mask(self, client, rendezvous_client):
        """Поиск по маске региона."""
        rendezvous_client.resolve_contact.return_value = {
            "type": "list",
            "items": [
                {"public_id": "@S1-1234-5678.ru.srv", "type": "nat", "load": 45},
                {"public_id": "@S2-1234-5678.ru.srv", "type": "nat", "load": 25},
            ],
        }

        response = client.get("/api/search?q=@*.ru.srv")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 2

    def test_unauthorized_access(self, client, router):
        """Неавторизованный доступ."""
        # Создаем приложение без авторизации
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.get("/api/contacts")
        assert response.status_code == 401

    def test_add_contact_empty_name(self, client):
        """Добавление контакта с пустым именем."""
        seed_hash = hashlib.sha256(b"contact_seed_empty_name").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        response = client.post(
            "/api/contacts",
            json={
                "public_id": contact_id,
                "name": "",
            },
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_add_contact_name_too_long(self, client):
        """Добавление контакта со слишком длинным именем."""
        seed_hash = hashlib.sha256(b"contact_seed_long_name").digest()
        contact_id = generate_public_id(seed_hash, "ru", is_server=False)

        response = client.post(
            "/api/contacts",
            json={
                "public_id": contact_id,
                "name": "a" * 65,
            },
        )

        assert response.status_code == 422  # Pydantic validation error
