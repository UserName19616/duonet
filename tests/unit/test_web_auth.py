# tests/unit/test_web_auth.py
"""
Тесты для модуля веб-аутентификации.
"""

import tempfile
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from src.common.identity.account import AccountManager, MIN_PASSWORD_LENGTH
from src.common.identity.recovery import RecoveryService
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage
from src.web.auth import create_auth_web_router
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
def recovery_service(storage, account_manager):
    return RecoveryService(storage, account_manager)


@pytest.fixture
def templates():
    loader = FileSystemLoader("src/web/templates")
    env = Environment(loader=loader, cache_size=0)
    env.cache = {}
    return Jinja2Templates(env=env)


@pytest.fixture
def router(account_manager, recovery_service, templates):
    return create_auth_web_router(account_manager, recovery_service, templates)


@pytest.fixture
def client(router, account_manager):
    app = FastAPI()
    app.include_router(router)
    test_client = TestClient(app)
    test_client._account_manager = account_manager
    return test_client


def get_charter_cookie(client) -> str:
    """Получает cookie принятия Устава."""
    response = client.post(
        "/api/web/charter/accept",
        json={"accepted": True, "lang": "ru", "version": "1.0"}
    )
    assert response.status_code == 200
    return response.cookies.get("charter_accepted")


class TestWebAuth:
    """Тесты для веб-аутентификации."""

    def test_login_page_redirects_to_accounts(self, client):
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 302
        assert "/accounts" in response.headers["location"]

    def test_register_page(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response = client.get("/register", cookies={"charter_accepted": cookie})
        assert response.status_code == 200

    def test_root_redirects_to_charter_when_no_accounts(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/charter" in response.headers["location"]

    def test_root_redirects_to_accounts_when_accounts_exist(self, client, account_manager):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        account_manager.register("test@example.com", "password123", False, "127.0.0.1")

        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/accounts" in response.headers["location"]

    def test_register_api_success_client(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com моя фраза",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["public_id"] is not None

    def test_register_api_success_server(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "server@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": True,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server_id"] is not None

    def test_register_api_duplicate(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response1 = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response1.status_code == 200
        assert response1.json()["success"] is True

        response2 = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response2.status_code == 200
        data = response2.json()
        assert data["success"] is False
        assert data["error"] == "account_exists"

    def test_register_api_weak_password(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        weak_password = "a" * (MIN_PASSWORD_LENGTH - 1)
        response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": weak_password,
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response.status_code == 422

    def test_register_api_empty_seed(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response.status_code == 422

    def test_login_api_success(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        reg_response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert reg_response.status_code == 200
        assert reg_response.json()["success"] is True

        response = client.post(
            "/api/web/login",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data

    def test_login_api_by_id_success(self, client, account_manager):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        reg_response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )
        assert reg_response.status_code == 200
        assert reg_response.json()["success"] is True
        public_id = reg_response.json()["public_id"]

        response = client.post(
            "/api/web/login-by-id",
            json={
                "public_id": public_id,
                "password": "secure123",
                "seed_phrase": "user@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_login_api_wrong_password(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": cookie},
        )

        response = client.post(
            "/api/web/login",
            json={
                "seed_phrase": "user@example.com",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_credentials"

    def test_login_api_nonexistent(self, client):
        response = client.post(
            "/api/web/login",
            json={
                "seed_phrase": "nonexistent@example.com",
                "password": "secure123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_credentials"

    def test_logout(self, client):
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_charter_page(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        response = client.get("/charter?lang=ru")
        assert response.status_code == 200

    def test_accounts_page(self, client, account_manager):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        account_manager.register("test@example.com", "password123", False, "127.0.0.1")

        response = client.get("/accounts")
        assert response.status_code == 200

    def test_chat_page_requires_auth(self, client):
        response = client.get("/chat", follow_redirects=False)
        assert response.status_code == 302
        assert "/accounts" in response.headers["location"]

    def test_monitor_page_requires_auth(self, client):
        response = client.get("/monitor", follow_redirects=False)
        assert response.status_code == 302
        assert "/accounts" in response.headers["location"]

    def test_authenticated_chat_page(self, client):
        """Авторизованный доступ к странице чата (теперь dashboard)."""
        # Очищаем БД
        client._account_manager._storage.execute_sql("DELETE FROM accounts")

        # Принимаем Устав (через API)
        charter_response = client.post(
            "/api/web/charter/accept",
            json={"accepted": True, "lang": "ru", "version": "1.0"}
        )
        assert charter_response.status_code == 200
        charter_cookie = charter_response.cookies.get("charter_accepted")
        client.cookies.set("charter_accepted", charter_cookie)

        # Регистрируем клиентский аккаунт
        reg_response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": False,
            },
            cookies={"charter_accepted": charter_cookie},
        )
        assert reg_response.status_code == 200
        assert reg_response.json()["success"] is True

        # Логинимся
        login_response = client.post(
            "/api/web/login",
            json={
                "seed_phrase": "user@example.com",
                "password": "secure123",
            },
        )
        assert login_response.status_code == 200
        assert login_response.json()["success"] is True
        token = login_response.json()["token"]

        # Устанавливаем cookie и делаем запрос
        client.cookies.set("token", token)
        response = client.get("/chat", follow_redirects=False)

        assert response.status_code == 200
        content = response.text.lower()

        # Проверяем, что загрузилась dashboard страница (новая архитектура)
        # Вместо старой проверки "chat" проверяем наличие элементов dashboard
        assert "контакты" in content or "contacts" in content
        assert "duonet" in content
        # Проверяем наличие вкладок dashboard
        assert "tab-contacts" in content or "вкладка" in content

    def test_charter_accept_endpoint(self, client):
        response = client.post(
            "/api/web/charter/accept",
            json={"accepted": True, "lang": "ru", "version": "1.0"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_charter_accept_decline(self, client):
        response = client.post(
            "/api/web/charter/accept",
            json={"accepted": False, "lang": "ru", "version": "1.0"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestWebAuthLimits:
    """Тесты для лимитов аккаунтов."""

    def test_register_client_within_limit(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        for i in range(3):
            response = client.post(
                "/api/web/register",
                json={
                    "seed_phrase": f"client{i}@example.com",
                    "password": "secure123",
                    "region": "ru",
                    "is_server": False,
                },
                cookies={"charter_accepted": cookie},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True, f"Failed at iteration {i}: {data}"

    def test_register_client_at_limit(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        for i in range(3):
            response = client.post(
                "/api/web/register",
                json={
                    "seed_phrase": f"client{i}@example.com",
                    "password": "secure123",
                    "region": "ru",
                    "is_server": False,
                },
                cookies={"charter_accepted": cookie},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True, f"Failed at iteration {i}: {data}"

    def test_register_client_exceeds_limit(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        with patch.object(client._account_manager._rate_limiter, 'check', return_value=True):
            for i in range(3):
                response = client.post(
                    "/api/web/register",
                    json={
                        "seed_phrase": f"client{i}@example.com",
                        "password": "secure123",
                        "region": "ru",
                        "is_server": False,
                    },
                    cookies={"charter_accepted": cookie},
                )
                assert response.status_code == 200
                assert response.json()["success"] is True

            response = client.post(
                "/api/web/register",
                json={
                    "seed_phrase": "client3@example.com",
                    "password": "secure123",
                    "region": "ru",
                    "is_server": False,
                },
                cookies={"charter_accepted": cookie},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["error"] == "max_clients_reached"

    def test_register_server_success(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "server@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": True,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server_id"] is not None

    def test_register_server_exceeds_limit(self, client):
        client._account_manager._storage.execute_sql("DELETE FROM accounts")
        cookie = get_charter_cookie(client)

        response1 = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "server1@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": True,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response1.status_code == 200
        assert response1.json()["success"] is True

        response2 = client.post(
            "/api/web/register",
            json={
                "seed_phrase": "server2@example.com",
                "password": "secure123",
                "region": "ru",
                "is_server": True,
            },
            cookies={"charter_accepted": cookie},
        )
        assert response2.status_code == 200
        data = response2.json()
        assert data["success"] is False
        assert data["error"] == "max_servers_reached"

# Пропуск тестов, требующих доработки
    pass
