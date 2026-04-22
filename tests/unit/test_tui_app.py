# tests/unit/test_tui_app.py
"""
Тесты для TUI приложения (только критическая функциональность,
без запуска реального TUI).
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.client.app import DuoNetApp


class TestDuoNetApp:
    """Тесты для DuoNetApp (без запуска TUI)."""

    def test_app_initialization(self):
        """Инициализация приложения."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        assert app is not None
        assert app.api_client.base_url == "http://test-server:8000"
        assert app._debug is True

    def test_app_initialization_defaults(self):
        """Инициализация с параметрами по умолчанию."""
        app = DuoNetApp()
        assert app.api_client.base_url == "https://localhost:8443"
        assert app._debug is False
        assert app._auto_login_account is None
        assert app._auto_login_password is None

    @pytest.mark.asyncio
    async def test_api_client_register_success(self):
        """API клиент: успешная регистрация."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True, "token": "tok", "public_id": "@TEST.ru"}
            result = await app.api_client.register("seed", "pass123456")
            assert result["success"] is True
            assert result["token"] == "tok"

    @pytest.mark.asyncio
    async def test_api_client_register_server(self):
        """API клиент: регистрация серверного аккаунта."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "token": "tok",
                "public_id": "@TEST.ru",
                "server_id": "@TEST.ru.srv"
            }
            result = await app.api_client.register("seed", "pass123456", is_server=True)
            assert result["success"] is True
            assert result["server_id"] is not None
            assert result["server_id"].endswith(".srv")

    @pytest.mark.asyncio
    async def test_api_client_login_success(self):
        """API клиент: успешный вход."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True, "token": "tok", "public_id": "@TEST.ru"}
            result = await app.api_client.login("seed", "pass123456")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_api_client_login_by_id_success(self):
        """API клиент: успешный вход по public_id."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True, "token": "tok", "public_id": "@TEST.ru"}
            result = await app.api_client.login_by_id("@TEST.ru", "pass123456")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_api_client_get_accounts(self):
        """API клиент: получение списка аккаунтов."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = [
                {"public_id": "@ALICE.ru", "server_id": None, "is_server": False},
                {"public_id": "@SERVER.ru.srv", "server_id": "@SERVER.ru.srv", "is_server": True},
            ]
            result = await app.api_client.get_accounts()
            assert len(result) == 2
            assert result[0]["public_id"] == "@ALICE.ru"
            assert result[1]["is_server"] is True

    @pytest.mark.asyncio
    async def test_api_client_get_contacts(self):
        """API клиент: получение контактов."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"contacts": [{"public_id": "@BOB.ru", "name": "Bob"}]}
            }
            result = await app.api_client.get_contacts()
            assert result["success"] is True
            assert len(result["data"]["contacts"]) == 1

    @pytest.mark.asyncio
    async def test_api_client_get_dialogs(self):
        """API клиент: получение диалогов."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"dialogs": [{"public_id": "@BOB.ru", "online": True}]}
            }
            result = await app.api_client.get_dialogs()
            assert len(result) == 1
            assert result[0]["public_id"] == "@BOB.ru"

    @pytest.mark.asyncio
    async def test_api_client_get_messages(self):
        """API клиент: получение сообщений."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "messages": [{"id": "msg1", "from_id": "@A.ru", "to_id": "@B.ru"}]
            }
            result = await app.api_client.get_messages("@B.ru")
            assert len(result) == 1
            assert result[0]["id"] == "msg1"

    @pytest.mark.asyncio
    async def test_api_client_get_session_key(self):
        """API клиент: получение session_key."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {"session_key": "a" * 64}
            }
            result = await app.api_client.get_session_key("@B.ru")
            assert result == "a" * 64

    @pytest.mark.asyncio
    async def test_api_client_send_message(self):
        """API клиент: отправка сообщения."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True, "message_id": "msg123"}
            result = await app.api_client.send_message("@B.ru", "encrypted", "key123")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_api_client_mark_read(self):
        """API клиент: отметка прочитанного."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True}
            result = await app.api_client.mark_message_read("msg123")
            assert result is True

    @pytest.mark.asyncio
    async def test_api_client_delete_conversation(self):
        """API клиент: удаление переписки."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True, "count": 5}
            result = await app.api_client.delete_conversation("@B.ru")
            assert result == 5

    def test_phrase_cache(self):
        """Кэш дополнительных фраз."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        app.save_phrase("@ALICE.ru", "secret_phrase")
        assert app.get_phrase("@ALICE.ru") == "secret_phrase"
        app.forget_phrase("@ALICE.ru")
        assert app.get_phrase("@ALICE.ru") is None

    def test_phrase_cache_multiple_contacts(self):
        """Кэш фраз для нескольких контактов."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        app.save_phrase("@ALICE.ru", "alice_secret")
        app.save_phrase("@BOB.ru", "bob_secret")
        assert app.get_phrase("@ALICE.ru") == "alice_secret"
        assert app.get_phrase("@BOB.ru") == "bob_secret"
        app.forget_phrase("@ALICE.ru")
        assert app.get_phrase("@ALICE.ru") is None
        assert app.get_phrase("@BOB.ru") == "bob_secret"

    @pytest.mark.skip(reason="Requires event loop")
    def test_set_language(self):
        """Установка языка."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        app.set_language("en")
        assert app.state.selected_lang == "en"
        app.set_language("ru")
        assert app.state.selected_lang == "ru"

        """Принятие Устава в клиентском режиме."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        app._creating_client = True
        app.charter_accepted(for_client=True)
        assert app.state.charter_accepted is True

    @pytest.mark.asyncio
    async def test_register_with_client_limit_error(self):
        """Ошибка при превышении лимита клиентских аккаунтов."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, 'register', new_callable=AsyncMock) as mock_register:
            mock_register.return_value = {
                "success": False,
                "error": "max_clients_reached",
                "message": "Maximum 5 client accounts allowed",
                "data": {"client_count": 5, "max_clients": 5}
            }
            result = await app.api_client.register("seed", "pass123456", is_server=False)
            assert result["success"] is False
            assert result["error"] == "max_clients_reached"

    @pytest.mark.asyncio
    async def test_register_with_server_limit_error(self):
        """Ошибка при превышении лимита серверных аккаунтов."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        with patch.object(app.api_client, 'register', new_callable=AsyncMock) as mock_register:
            mock_register.return_value = {
                "success": False,
                "error": "max_servers_reached",
                "message": "Maximum 1 server account allowed",
                "data": {"server_count": 1, "max_servers": 1}
            }
            result = await app.api_client.register("seed", "pass123456", is_server=True)
            assert result["success"] is False
            assert result["error"] == "max_servers_reached"

    @pytest.mark.asyncio
    async def test_api_client_close(self):
        """Закрытие API клиента."""
        app = DuoNetApp(api_url="http://test-server:8000", debug=True)
        await app.api_client.close()
        assert app.api_client._client.is_closed

    def test_state_manager_initialization(self):
        """Инициализация StateManager."""
        app = DuoNetApp()
        assert app.state.token is None
        assert app.state.public_id is None
        assert app.state.is_server is False
        assert app.state.is_authenticated() is False

    def test_state_manager_set_auth(self):
        """Установка аутентификации в StateManager."""
        app = DuoNetApp()
        app.state.token = "test_token"
        app.state.public_id = "@TEST.ru"
        app.state.is_server = False
        assert app.state.is_authenticated() is True
        assert app.state.token == "test_token"
        assert app.state.public_id == "@TEST.ru"

    def test_state_manager_clear_auth(self):
        """Очистка аутентификации в StateManager."""
        app = DuoNetApp()
        app.state.token = "test_token"
        app.state.public_id = "@TEST.ru"
        app.state.clear_auth()
        assert app.state.token is None
        assert app.state.public_id is None
        assert app.state.is_authenticated() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

    pass
