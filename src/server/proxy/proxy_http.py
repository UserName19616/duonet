# src/proxy/proxy_http.py
"""
HTTP/HTTPS прокси-сервер для мобильных клиентов.

Позволяет направлять веб-трафик через домашний компьютер (NAT-сервер),
скрывая реальный IP клиента и обеспечивая доступ к интернету.
"""

import asyncio
import base64
import logging
import time
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import ClientTimeout, web

from .client_crud import ClientManager  # ИСПРАВЛЕНО: client_crud вместо proxy_manager

logger = logging.getLogger(__name__)

# Константы
PROXY_REQUEST_TIMEOUT_SECONDS = 30
PROXY_MAX_RESPONSE_SIZE_MB = 50


class ProxyServer:
    """
    HTTP/HTTPS прокси-сервер.

    Асинхронно обрабатывает запросы от клиентов, проверяет права доступа,
    ограничения трафика и проксирует запросы к целевым серверам.
    """

    def __init__(self, client_manager: ClientManager, port: int = 9879):
        """
        Инициализация прокси-сервера.

        Args:
            client_manager: Менеджер клиентов (для проверки разрешений).
            port: Порт для прослушивания (по умолчанию 9879).
        """
        self._client_manager = client_manager
        self._port = port
        self._app = None
        self._runner = None
        self._running = False
        self._client_session: Optional[aiohttp.ClientSession] = None

    def _get_client_id(self, request: web.Request) -> Optional[str]:
        """
        Извлечение client_id из заголовка.

        Формат: Authorization: Bearer {client_id}
        """
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return None

    async def _forward_request(
        self,
        client_id: str,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Проксирование запроса к целевому серверу.

        Args:
            client_id: ID клиента.
            method: HTTP метод.
            url: Целевой URL.
            headers: Заголовки запроса.
            body: Тело запроса.

        Returns:
            Словарь с ответом.
        """
        # Удаляем заголовки, которые не должны передаваться
        forward_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in ["host", "authorization", "proxy-connection"]
        }

        # Добавляем User-Agent если отсутствует
        if "user-agent" not in {k.lower() for k in forward_headers}:
            forward_headers["User-Agent"] = "DuoNet-Proxy/1.0"

        timeout = ClientTimeout(total=PROXY_REQUEST_TIMEOUT_SECONDS)

        try:
            async with self._client_session.request(
                method=method,
                url=url,
                headers=forward_headers,
                data=body,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                # Читаем тело ответа с ограничением по размеру
                content = await response.read()
                max_bytes = PROXY_MAX_RESPONSE_SIZE_MB * 1024 * 1024
                if len(content) > max_bytes:
                    logger.warning(f"Response too large: {len(content)} bytes")
                    return {
                        "id": "error",
                        "status": 502,
                        "headers": {"content-type": "text/plain"},
                        "body": base64.b64encode(b"Response too large").decode(),
                    }

                # Логируем трафик
                self._client_manager.add_traffic(client_id, len(content))

                return {
                    "id": "response",
                    "status": response.status,
                    "headers": dict(response.headers),
                    "body": base64.b64encode(content).decode(),
                }

        except asyncio.TimeoutError:
            logger.warning(f"Request timeout: {url}")
            return {
                "id": "error",
                "status": 504,
                "headers": {"content-type": "text/plain"},
                "body": base64.b64encode(b"Gateway Timeout").decode(),
            }
        except aiohttp.ClientError as e:
            logger.error(f"Client error: {e}")
            return {
                "id": "error",
                "status": 502,
                "headers": {"content-type": "text/plain"},
                "body": base64.b64encode(f"Proxy error: {str(e)}".encode()).decode(),
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {
                "id": "error",
                "status": 500,
                "headers": {"content-type": "text/plain"},
                "body": base64.b64encode(b"Internal Server Error").decode(),
            }

    async def handle_proxy_request(self, request: web.Request) -> web.Response:
        """
        Обработка прокси-запроса.

        Ожидает JSON с полями:
        {
            "id": str,
            "method": str,
            "url": str,
            "headers": dict,
            "body": Optional[str] (base64)
        }

        Returns:
            JSON ответа.
        """
        client_id = self._get_client_id(request)
        if not client_id:
            return web.json_response(
                {"success": False, "error": "unauthorized", "message": "Missing client ID"},
                status=401,
            )

        # Проверяем права
        if not self._client_manager.has_permission(client_id, "proxy"):
            return web.json_response(
                {"success": False, "error": "forbidden", "message": "Proxy access denied"},
                status=403,
            )

        # Парсим запрос
        try:
            data = await request.json()
        except Exception as e:
            return web.json_response(
                {"success": False, "error": "invalid_request", "message": str(e)},
                status=400,
            )

        req_id = data.get("id")
        method = data.get("method")
        url = data.get("url")
        headers = data.get("headers", {})
        body_b64 = data.get("body")

        if not method or not url:
            return web.json_response(
                {"success": False, "error": "invalid_request", "message": "Missing method or url"},
                status=400,
            )

        # Декодируем тело
        body = None
        if body_b64:
            try:
                body = base64.b64decode(body_b64)
            except Exception:
                return web.json_response(
                    {"success": False, "error": "invalid_body", "message": "Invalid base64 body"},
                    status=400,
                )

        # Проверяем лимит трафика
        if not self._client_manager.check_traffic_limit(client_id, len(body or b"")):
            return web.json_response(
                {"success": False, "error": "rate_limited", "message": "Traffic limit exceeded"},
                status=429,
            )

        # Логируем входящий трафик
        self._client_manager.add_traffic(client_id, len(body or b""))

        # Проксируем запрос
        result = await self._forward_request(
            client_id=client_id,
            method=method,
            url=url,
            headers=headers,
            body=body,
        )

        return web.json_response(result)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Эндпоинт для проверки состояния прокси."""
        return web.json_response({"status": "ok", "running": self._running})

    async def start(self, host: str = "0.0.0.0", port: Optional[int] = None) -> None:
        """
        Запуск прокси-сервера.

        Args:
            host: Хост для прослушивания.
            port: Порт (если не указан, используется port из конструктора).
        """
        if self._running:
            logger.warning("Proxy server already running")
            return

        self._app = web.Application()
        self._app.router.add_post("/proxy", self.handle_proxy_request)
        self._app.router.add_get("/health", self.handle_health)

        # Создаем клиентскую сессию
        self._client_session = aiohttp.ClientSession()

        port = port or self._port
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()

        # Сохраняем реальный порт, если использовали порт 0
        if port == 0:
            sockets = self._runner.addresses
            if sockets:
                self._port = sockets[0][1]

        self._running = True
        logger.info(f"Proxy server started on {host}:{self._port}")

    async def stop(self) -> None:
        """Остановка прокси-сервера."""
        if not self._running:
            return

        if self._runner:
            await self._runner.cleanup()

        if self._client_session:
            await self._client_session.close()

        self._running = False
        logger.info("Proxy server stopped")

    async def __aenter__(self):
        """Поддержка async with."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие при выходе."""
        await self.stop()
