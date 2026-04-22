# tests/unit/test_web_file_transfer.py
"""
Тесты для модуля передачи файлов.
"""

import asyncio
import base64
import hashlib
import json
import socket
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.client.crypto.aes import encrypt, generate_session_key, decrypt
from src.common.identity.account import AccountManager
from src.common.identity.public_id import generate_public_id
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage
from src.web.file_transfer import create_file_transfer_web_router, get_file_storage
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


def make_valid_public_id() -> str:
    seed_hash = hashlib.sha256(b"test_user_seed").digest()
    return generate_public_id(seed_hash, "ru", is_server=False)


def make_valid_public_id2() -> str:
    seed_hash = hashlib.sha256(b"test_user_seed_2").digest()
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
    return create_file_transfer_web_router(account_manager, storage, chat_manager=None)


@pytest.fixture
def client(router, account_manager, test_user):
    # Очищаем хранилище перед каждым тестом
    file_storage = get_file_storage()
    file_storage._files.clear()
    file_storage._metadata.clear()
    file_storage._pending_packets.clear()
    file_storage._packet_metadata.clear()

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


class TestWebFileTransfer:
    """Тесты для передачи файлов."""

    def test_upload_file(self, client):
        """Загрузка файла."""
        files = {"file": ("test.txt", b"Hello, World!", "text/plain")}
        response = client.post("/api/web/files/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "file_id" in data["data"]
        assert "message_id" in data["data"]
        assert data["data"]["name"] == "test.txt"
        assert data["data"]["size"] == 13

    def test_upload_file_too_large(self, client):
        """Загрузка слишком большого файла."""
        from src.config import MAX_FILE_SIZE_BYTES
        large_data = b"x" * (MAX_FILE_SIZE_BYTES + 1)  # ← используем правильную константу
        files = {"file": ("large.bin", large_data, "application/octet-stream")}
        response = client.post("/api/web/files/upload", files=files)
        assert response.status_code == 413

    def test_get_file_metadata(self, client):
        """Получение метаданных файла."""
        # Загружаем файл
        files = {"file": ("test.txt", b"Hello, World!", "text/plain")}
        upload_response = client.post("/api/web/files/upload", files=files)
        assert upload_response.status_code == 200
        file_id = upload_response.json()["data"]["file_id"]

        # Получаем метаданные
        response = client.get(f"/api/web/files/{file_id}/metadata")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == file_id
        assert data["data"]["name"] == "test.txt"
        assert data["data"]["size"] == 13

    def test_get_file_metadata_not_found(self, client):
        """Получение метаданных несуществующего файла."""
        response = client.get("/api/web/files/nonexistent/metadata")
        assert response.status_code == 404

    def test_delete_file(self, client):
        """Удаление файла."""
        # Загружаем файл
        files = {"file": ("test.txt", b"Hello, World!", "text/plain")}
        upload_response = client.post("/api/web/files/upload", files=files)
        assert upload_response.status_code == 200
        file_id = upload_response.json()["data"]["file_id"]

        # Удаляем файл
        response = client.delete(f"/api/web/files/{file_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем, что файл удалён
        response = client.get(f"/api/web/files/{file_id}/metadata")
        assert response.status_code == 404

    def test_get_conversation_files_empty(self, client, test_user):
        """Пустой список файлов в переписке."""
        response = client.get(f"/api/web/files/conversation/{test_user['public_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # После очистки хранилища список должен быть пустым
        assert data["data"]["files"] == []

    def test_get_packet_info(self, client):
        """Получение информации о пакетах."""
        response = client.get("/api/web/files/packets/test_message_id")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["message_id"] == "test_message_id"

    def test_unauthorized_access(self, router):
        """Неавторизованный доступ."""
        app = FastAPI()
        app.include_router(router)
        unauth_client = TestClient(app)

        response = unauth_client.get("/api/web/files/conversation/@TEST.ru")
        assert response.status_code == 401

    def test_download_file(self, client):
        """Скачивание файла."""
        # Загружаем файл
        files = {"file": ("test.txt", b"Hello, World!", "text/plain")}
        upload_response = client.post("/api/web/files/upload", files=files)
        assert upload_response.status_code == 200
        file_id = upload_response.json()["data"]["file_id"]

        # Скачиваем файл
        response = client.get(f"/api/web/files/{file_id}/download")
        assert response.status_code == 200
        # Проверяем, что содержимое соответствует ожидаемому
        assert response.content == b"Hello, World!"
        # Проверяем content-type (может быть с charset или без)
        assert response.headers["content-type"].startswith("text/plain")
        assert "attachment; filename=test.txt" in response.headers["content-disposition"]
