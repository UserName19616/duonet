# tests/unit/test_api_charter.py
"""
Тесты для API эндпоинтов Устава.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api.charter import create_charter_router
from src.common.charter.loader import CharterLoader
from src.common.crypto.keys import generate_keypair, generate_keypair_from_seed, hash_sha256
from src.common.identity.account import AccountManager
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage


def mock_geoip(ip):
    return "ru"


@pytest.fixture(scope="function")
def temp_charter_dir():
    """Создание временной директории с тестовым Уставом."""
    with tempfile.TemporaryDirectory() as tmpdir:
        templates_dir = Path(tmpdir)
        ru_file = templates_dir / "charter_ru.txt"
        ru_file.write_text(
            "Тестовый Устав DuoNet\n"
            "Статья 1: Тест на русском языке\n"
            "Уникальный русский текст для проверки",
            encoding="utf-8"
        )
        en_file = templates_dir / "charter_en.txt"
        en_file.write_text(
            "Test DuoNet Charter\n"
            "Article 1: Test in English\n"
            "Unique English text for verification",
            encoding="utf-8"
        )

        import src.common.charter.loader as charter_loader
        original_dir = charter_loader.CHARTER_TEMPLATES_DIR
        original_loader = charter_loader._charter_loader

        charter_loader.CHARTER_TEMPLATES_DIR = templates_dir
        charter_loader._charter_loader = CharterLoader(templates_dir)

        yield templates_dir

        charter_loader.CHARTER_TEMPLATES_DIR = original_dir
        charter_loader._charter_loader = original_loader


@pytest.fixture
def storage(temp_charter_dir):
    """Фикстура для SQLiteStorage."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def rate_limiter():
    return MultiRateLimiter()


@pytest.fixture
def account_manager(storage, rate_limiter):
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret_key",
    )


@pytest.fixture
def router(account_manager, storage, temp_charter_dir):
    """Роутер с уже настроенным временным Уставом."""
    return create_charter_router(account_manager, storage)


@pytest.fixture
def client(router, temp_charter_dir):
    """Создаём клиент."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def test_server_account(account_manager):
    """Создание тестового серверного аккаунта."""
    result = account_manager.register(
        seed_phrase="server@example.com test phrase",
        password="password123",
        is_server=True,
        client_ip="127.0.0.1",
        region_override="ru",
    )
    print(f"\n[DEBUG] register result: {result}")
    print(f"[DEBUG] account_id: {result['account_id'].hex()}")

    # Проверяем, что в БД есть серверная запись
    cursor = account_manager._storage.execute_sql(
        "SELECT account_id, is_server, server_id FROM accounts WHERE account_id = ? AND is_server = 1",
        (result['account_id'],)
    )
    row = cursor.fetchone()
    print(f"[DEBUG] Server account in DB: {row}")

    assert result["success"], f"Registration failed: {result}"
    return {
        "account_id": result["account_id"],
        "public_id": result["public_id"],
        "server_id": result["server_id"],
        "seed_phrase": "server@example.com test phrase",
        "password": "password123",
    }


@pytest.fixture
def test_client_account(account_manager):
    """Создание тестового клиентского аккаунта."""
    result = account_manager.register(
        seed_phrase="client@example.com test phrase",
        password="password123",
        is_server=False,
        client_ip="127.0.0.1",
        region_override="ru",
    )
    assert result["success"], f"Registration failed: {result}"
    return {
        "account_id": result["account_id"],
        "public_id": result["public_id"],
        "seed_phrase": "client@example.com test phrase",
        "password": "password123",
    }


class TestApiCharter:
    """Тесты для API эндпоинтов Устава."""

    def test_get_charter_text_ru(self, client):
        """Получение текста Устава на русском."""
        response = client.get("/api/charter/text?lang=ru")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Тестовый Устав" in data["text"]
        assert "русском" in data["text"]

    def test_get_charter_text_en(self, client):
        """Получение текста Устава на английском."""
        response = client.get("/api/charter/text?lang=en")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Test DuoNet Charter" in data["text"]
        assert "English" in data["text"]

    def test_get_charter_text_default_lang(self, client):
        """Получение текста Устава с языком по умолчанию."""
        response = client.get("/api/charter/text")
        assert response.status_code == 200
        data = response.json()
        assert data["lang"] == "ru"

    def test_accept_charter_success(self, client, test_server_account):
        """Успешное принятие Устава."""
        print(f"\n[DEBUG] test_server_account: {test_server_account}")
        print(f"[DEBUG] seed_phrase: {test_server_account['seed_phrase']}")

        response = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "ru",
            },
        )
        print(f"[DEBUG] response status: {response.status_code}")
        print(f"[DEBUG] response body: {response.json()}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_accept_charter_already_accepted(self, client, test_server_account):
        """Повторное принятие Устава (возвращает существующую подпись)."""
        response1 = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "ru",
            },
        )
        assert response1.status_code == 200
        sig1 = response1.json()["signature"]

        response2 = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "ru",
            },
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["success"] is True
        assert data2["signature"] == sig1

    def test_accept_charter_account_not_found(self, client):
        """Принятие Устава с несуществующим аккаунтом."""
        response = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": "nonexistent@example.com",
                "lang": "ru",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "account_not_found"

    def test_accept_charter_not_server_account(self, client, test_client_account):
        """Принятие Устава клиентским аккаунтом (должно быть ошибкой)."""
        response = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_client_account["seed_phrase"],
                "lang": "ru",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        # Клиентский аккаунт не имеет серверной записи, поэтому ошибка account_not_found
        assert data["error"] in ["account_not_found", "not_server_account"]

    def test_get_charter_status_accepted(self, client, test_server_account):
        """Проверка статуса Устава после принятия."""
        client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "ru",
            },
        )

        response = client.get(
            f"/api/charter/status?seed_phrase={test_server_account['seed_phrase']}&lang=ru"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["accepted"] is True
        assert data["version"] == "1.0"
        assert data["signature"] is not None

    def test_get_charter_status_not_accepted(self, client, test_server_account):
        """Проверка статуса Устава до принятия."""
        response = client.get(
            f"/api/charter/status?seed_phrase={test_server_account['seed_phrase']}&lang=ru"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["accepted"] is False
        assert data["version"] is None
        assert data["signature"] is None

    def test_get_charter_status_account_not_found(self, client):
        """Проверка статуса с несуществующим аккаунтом."""
        response = client.get("/api/charter/status?seed_phrase=nonexistent@example.com")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["accepted"] is False

    def test_get_charter_status_client_account(self, client, test_client_account):
        """Проверка статуса клиентским аккаунтом (всегда false)."""
        response = client.get(
            f"/api/charter/status?seed_phrase={test_client_account['seed_phrase']}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["accepted"] is False

    def test_accept_charter_with_different_lang(self, client, test_server_account):
        """Принятие Устава на разных языках."""
        # Принимаем на русском
        response_ru = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "ru",
            },
        )
        assert response_ru.status_code == 200
        sig_ru = response_ru.json()["signature"]

        # Проверяем статус для русского
        status_ru = client.get(
            f"/api/charter/status?seed_phrase={test_server_account['seed_phrase']}&lang=ru"
        )
        assert status_ru.json()["accepted"] is True

        # Принимаем на английском
        response_en = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "en",
            },
        )
        assert response_en.status_code == 200
        sig_en = response_en.json()["signature"]

        # Проверяем статус для английского
        status_en = client.get(
            f"/api/charter/status?seed_phrase={test_server_account['seed_phrase']}&lang=en"
        )
        assert status_en.json()["accepted"] is True

        # Подписи должны быть разными
        assert sig_ru != sig_en, f"Signatures should be different. RU: {sig_ru[:32]}..., EN: {sig_en[:32]}..."

    def test_accept_charter_missing_seed(self, client):
        """Принятие Устава без seed_phrase."""
        response = client.post(
            "/api/charter/accept",
            json={"lang": "ru"},
        )
        assert response.status_code == 422

    def test_accept_charter_invalid_lang(self, client, test_server_account):
        """Принятие Устава с неверным языком."""
        response = client.post(
            "/api/charter/accept",
            json={
                "seed_phrase": test_server_account["seed_phrase"],
                "lang": "invalid",
            },
        )
        assert response.status_code == 422
