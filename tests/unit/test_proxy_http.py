# tests/unit/test_proxy_http.py
"""
Тесты для модуля ProxyServer.
"""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import aiohttp

from src.server.proxy.proxy_http import ProxyServer
from src.server.proxy.client_crud import ClientManager, GROUPS


class AsyncContextManagerMock:
    """Мок для асинхронного контекстного менеджера."""

    def __init__(self, response_mock):
        self.response_mock = response_mock

    async def __aenter__(self):
        return self.response_mock

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def client_manager():
    """Мок ClientManager."""
    mock = MagicMock(spec=ClientManager)
    mock.has_permission.return_value = True
    mock.check_traffic_limit.return_value = True
    return mock


@pytest_asyncio.fixture
async def proxy_server(client_manager):
    """Создание прокси-сервера."""
    # Используем порт 0 для автоматического выбора свободного порта
    server = ProxyServer(client_manager, port=0)
    await server.start(host="127.0.0.1")
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def aiohttp_client(proxy_server):
    """Создание тестового клиента aiohttp."""
    async with aiohttp.ClientSession() as session:
        yield session


class TestProxyServer:
    """Тесты для ProxyServer."""

    @pytest.mark.asyncio
    async def test_start_stop(self, proxy_server):
        """Запуск и остановка сервера."""
        assert proxy_server._running is True
        await proxy_server.stop()
        assert proxy_server._running is False

    @pytest.mark.asyncio
    async def test_handle_health(self, proxy_server, aiohttp_client):
        """Проверка эндпоинта /health."""
        async with aiohttp_client.get(f"http://127.0.0.1:{proxy_server._port}/health") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["running"] is True

    @pytest.mark.asyncio
    async def test_handle_proxy_request_no_auth(self, proxy_server, aiohttp_client):
        """Запрос без авторизации."""
        async with aiohttp_client.post(
            f"http://127.0.0.1:{proxy_server._port}/proxy",
            json={}
        ) as resp:
            assert resp.status == 401
            data = await resp.json()
            assert data["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_handle_proxy_request_forbidden(self, proxy_server, client_manager, aiohttp_client):
        """Запрос без прав доступа."""
        client_manager.has_permission.return_value = False
        async with aiohttp_client.post(
            f"http://127.0.0.1:{proxy_server._port}/proxy",
            headers={"Authorization": "Bearer client123"},
            json={},
        ) as resp:
            assert resp.status == 403
            data = await resp.json()
            assert data["error"] == "forbidden"

    @pytest.mark.asyncio
    async def test_handle_proxy_request_rate_limited(self, proxy_server, client_manager, aiohttp_client):
        """Превышение лимита трафика."""
        client_manager.check_traffic_limit.return_value = False
        async with aiohttp_client.post(
            f"http://127.0.0.1:{proxy_server._port}/proxy",
            headers={"Authorization": "Bearer client123"},
            json={
                "id": "req1",
                "method": "GET",
                "url": "https://httpbin.org/get",
            },
        ) as resp:
            assert resp.status == 429
            data = await resp.json()
            assert data["error"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_handle_proxy_request_invalid_json(self, proxy_server, aiohttp_client):
        """Неверный JSON в запросе."""
        async with aiohttp_client.post(
            f"http://127.0.0.1:{proxy_server._port}/proxy",
            headers={"Authorization": "Bearer client123"},
            data="invalid json",
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
            assert data["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_handle_proxy_request_missing_fields(self, proxy_server, aiohttp_client):
        """Отсутствие обязательных полей."""
        async with aiohttp_client.post(
            f"http://127.0.0.1:{proxy_server._port}/proxy",
            headers={"Authorization": "Bearer client123"},
            json={"id": "req1"},
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
            assert data["error"] == "invalid_request"
            assert "Missing method or url" in data["message"]

    @pytest.mark.asyncio
    async def test_handle_proxy_request_invalid_body(self, proxy_server, aiohttp_client):
        """Неверный base64 в теле запроса."""
        async with aiohttp_client.post(
            f"http://127.0.0.1:{proxy_server._port}/proxy",
            headers={"Authorization": "Bearer client123"},
            json={
                "id": "req1",
                "method": "POST",
                "url": "https://httpbin.org/post",
                "body": "invalid-base64!!!",
            },
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
            assert data["error"] == "invalid_body"

    @pytest.mark.asyncio
    async def test_forward_request_success(self, proxy_server, client_manager):
        """Успешное проксирование GET запроса."""
        # Создаем мок ответа
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.read = AsyncMock(return_value=b'{"test": "ok"}')

        # Создаем мок для request, который возвращает контекстный менеджер
        def request_mock(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)

        # Создаем мок сессии
        mock_session = MagicMock()
        mock_session.request = request_mock

        with patch.object(proxy_server, "_client_session", mock_session):
            result = await proxy_server._forward_request(
                client_id="client123",
                method="GET",
                url="https://httpbin.org/get",
                headers={},
            )

            assert result["status"] == 200
            assert result["headers"]["content-type"] == "application/json"

            # Проверяем декодирование body
            body = base64.b64decode(result["body"])
            assert body == b'{"test": "ok"}'

    @pytest.mark.asyncio
    async def test_forward_request_timeout(self, proxy_server, client_manager):
        """Таймаут при проксировании."""
        # Создаем мок для request, который выбрасывает исключение
        def request_mock(*args, **kwargs):
            raise asyncio.TimeoutError()

        # Создаем мок сессии
        mock_session = MagicMock()
        mock_session.request = request_mock

        with patch.object(proxy_server, "_client_session", mock_session):
            result = await proxy_server._forward_request(
                client_id="client123",
                method="GET",
                url="https://httpbin.org/get",
                headers={},
            )

            # Проверяем, что возвращается 504
            assert result["status"] == 504
            body = base64.b64decode(result["body"])
            assert b"Gateway Timeout" in body

    @pytest.mark.asyncio
    async def test_forward_request_client_error(self, proxy_server, client_manager):
        """Ошибка клиента при проксировании."""
        # Создаем мок для request, который выбрасывает исключение
        def request_mock(*args, **kwargs):
            raise aiohttp.ClientError("Connection failed")

        # Создаем мок сессии
        mock_session = MagicMock()
        mock_session.request = request_mock

        with patch.object(proxy_server, "_client_session", mock_session):
            result = await proxy_server._forward_request(
                client_id="client123",
                method="GET",
                url="https://httpbin.org/get",
                headers={},
            )

            assert result["status"] == 502
            body = base64.b64decode(result["body"])
            assert b"Proxy error" in body

    @pytest.mark.asyncio
    async def test_forward_request_response_too_large(self, proxy_server, client_manager):
        """Слишком большой ответ."""
        # Создаем ответ больше лимита (51 МБ)
        large_response = b"x" * (51 * 1024 * 1024)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=large_response)

        # Создаем мок для request, который возвращает контекстный менеджер
        def request_mock(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)

        # Создаем мок сессии
        mock_session = MagicMock()
        mock_session.request = request_mock

        with patch.object(proxy_server, "_client_session", mock_session):
            result = await proxy_server._forward_request(
                client_id="client123",
                method="GET",
                url="https://httpbin.org/get",
                headers={},
            )

            assert result["status"] == 502
            body = base64.b64decode(result["body"])
            assert b"Response too large" in body

    @pytest.mark.asyncio
    async def test_traffic_logging(self, proxy_server, client_manager):
        """Проверка логирования трафика."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.read = AsyncMock(return_value=b"response data")

        # Создаем мок для request, который возвращает контекстный менеджер
        def request_mock(*args, **kwargs):
            return AsyncContextManagerMock(mock_response)

        # Создаем мок сессии
        mock_session = MagicMock()
        mock_session.request = request_mock

        with patch.object(proxy_server, "_client_session", mock_session):
            await proxy_server._forward_request(
                client_id="client123",
                method="GET",
                url="https://httpbin.org/get",
                headers={},
                body=b"request body",
            )

            # Проверяем, что add_traffic был вызван для ответа (response)
            # В _forward_request add_traffic вызывается после чтения ответа
            client_manager.add_traffic.assert_called_once()

            # Проверяем, что первый аргумент - client_id
            call_args = client_manager.add_traffic.call_args[0]
            assert call_args[0] == "client123"
            # Проверяем, что второй аргумент - положительное число (размер ответа)
            assert call_args[1] > 0

    @pytest.mark.asyncio
    async def test_get_client_id(self, proxy_server):
        """Извлечение client_id из заголовка."""
        # Создаем мок запроса
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer client123"}

        client_id = proxy_server._get_client_id(mock_request)
        assert client_id == "client123"

    @pytest.mark.asyncio
    async def test_get_client_id_no_auth(self, proxy_server):
        """Отсутствие заголовка Authorization."""
        mock_request = MagicMock()
        mock_request.headers = {}

        client_id = proxy_server._get_client_id(mock_request)
        assert client_id is None

    @pytest.mark.asyncio
    async def test_get_client_id_wrong_format(self, proxy_server):
        """Неверный формат заголовка."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Basic client123"}

        client_id = proxy_server._get_client_id(mock_request)
        assert client_id is None

    @pytest.mark.asyncio
    async def test_context_manager(self, client_manager):
        """Проверка async context manager."""
        # Используем порт 0 для автоматического выбора
        async with ProxyServer(client_manager, port=0) as server:
            assert server._running is True
        assert server._running is False

    @pytest.mark.asyncio
    async def test_headers_filtering(self, proxy_server):
        """Проверка фильтрации заголовков."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.read = AsyncMock(return_value=b"ok")

        # Создаем мок для контекстного менеджера
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        # Создаем мок сессии
        mock_session = MagicMock()
        mock_session.request.return_value = mock_cm

        with patch.object(proxy_server, "_client_session", mock_session):
            # Заголовки, которые должны быть удалены
            headers = {
                "Host": "example.com",
                "Authorization": "Bearer token",
                "Proxy-Connection": "keep-alive",
                "X-Custom": "test",
            }

            await proxy_server._forward_request(
                client_id="client123",
                method="GET",
                url="https://httpbin.org/get",
                headers=headers,
            )

            # Проверяем, что запрос был сделан с отфильтрованными заголовками
            call_args = mock_session.request.call_args
            forwarded_headers = call_args[1]["headers"]
            assert "Host" not in forwarded_headers
            assert "Authorization" not in forwarded_headers
            assert "Proxy-Connection" not in forwarded_headers
            assert forwarded_headers["X-Custom"] == "test"
