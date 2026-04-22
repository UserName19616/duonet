# tests/unit/test_rendezvous_server.py
"""
Тесты для модуля RendezvousServer.
"""

import asyncio
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiohttp import ClientSession

from src.server.network.rendezvous.rendezvous_server import RendezvousServer, ServerInfo


# Счётчик для генерации уникальных ID
_counter = 0

def make_valid_public_id(base: str, region: str, is_server: bool = True) -> str:
    """
    Генерирует валидный Public ID для тестирования.
    Использует только символы из разрешённого алфавита.
    Разрешённые символы: ABCDEFGHJKLMNPQRSTUVWXYZ23456789
    """
    global _counter
    _counter += 1

    # Разрешённые символы (без I, L, O, 0, 1)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    # Генерируем 12 символов для хеша
    # Используем счётчик и base для создания уникального, но валидного хеша
    import hashlib

    # Создаём строку для хеширования
    seed = f"{base}_{_counter}_{time.time()}"
    # Берём хеш и преобразуем в символы из алфавита
    hash_bytes = hashlib.sha256(seed.encode()).digest()

    # Преобразуем байты в символы из алфавита
    hash_chars = []
    for i in range(12):
        # Берём байт и преобразуем в индекс алфавита
        idx = hash_bytes[i] % len(alphabet)
        hash_chars.append(alphabet[idx])

    # Форматируем: XXXX-XXXX-XXXX
    hash_part = f"{''.join(hash_chars[:4])}-{''.join(hash_chars[4:8])}-{''.join(hash_chars[8:12])}"

    public_id = f"@{hash_part}.{region}"
    if is_server:
        public_id += ".srv"

    return public_id


@pytest_asyncio.fixture
async def server():
    """Создание сервера знакомств."""
    srv = RendezvousServer()
    await srv.start(host="127.0.0.1", port=0)
    yield srv
    await srv.stop()


@pytest_asyncio.fixture
async def client(server):
    """Создание тестового клиента."""
    # Получаем реальный порт
    port = server._runner.addresses[0][1]
    base_url = f"http://127.0.0.1:{port}"

    async with ClientSession() as session:
        class TestClientProxy:
            def __init__(self, session, base_url):
                self.session = session
                self.base_url = base_url

            async def post(self, path, **kwargs):
                return await self.session.post(f"{self.base_url}{path}", **kwargs)

            async def get(self, path, **kwargs):
                return await self.session.get(f"{self.base_url}{path}", **kwargs)

        yield TestClientProxy(session, base_url)


class TestRendezvousServer:
    """Тесты для RendezvousServer."""

    @pytest.mark.asyncio
    async def test_register_success(self, client, server):
        """Успешная регистрация сервера."""
        public_id = make_valid_public_id("TEST", "ru", is_server=True)
        response = await client.post(
            "/api/register",
            json={
                "public_id": public_id,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
                "capacity": 100,
            },
        )

        assert response.status == 201
        data = await response.json()
        assert data["public_id"] == public_id
        assert data["type"] == "nat"
        assert data["region"] == "ru"
        assert data["load"] == 0
        assert "expires_at" in data

    @pytest.mark.asyncio
    async def test_register_invalid_public_id(self, client):
        """Регистрация с неверным Public ID."""
        response = await client.post(
            "/api/register",
            json={
                "public_id": "@INVALID",
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
            },
        )
        assert response.status == 400
        data = await response.json()
        assert "Invalid Public ID format" in data["error"]

    @pytest.mark.asyncio
    async def test_register_not_server_id(self, client):
        """Регистрация с ID не сервера."""
        public_id = make_valid_public_id("CLIENT", "ru", is_server=False)
        response = await client.post(
            "/api/register",
            json={
                "public_id": public_id,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
            },
        )
        assert response.status == 400
        data = await response.json()
        assert "must be a server ID" in data["error"]

    @pytest.mark.asyncio
    async def test_register_invalid_region(self, client):
        """Регистрация с неверным регионом."""
        public_id = make_valid_public_id("TEST", "ru", is_server=True)
        response = await client.post(
            "/api/register",
            json={
                "public_id": public_id,
                "type": "nat",
                "region": "rus",
                "ws_url": "wss://test.local:9877",
            },
        )
        assert response.status == 400
        data = await response.json()
        assert "2-letter code" in data["error"]

    @pytest.mark.asyncio
    async def test_register_region_mismatch(self, client):
        """Несоответствие региона в ID и в запросе."""
        public_id = make_valid_public_id("TEST", "ru", is_server=True)
        response = await client.post(
            "/api/register",
            json={
                "public_id": public_id,
                "type": "nat",
                "region": "us",
                "ws_url": "wss://test.local:9877",
            },
        )
        assert response.status == 400
        data = await response.json()
        assert "Region mismatch" in data["error"]

    @pytest.mark.asyncio
    async def test_heartbeat_success(self, client, server):
        """Успешный heartbeat."""
        public_id = make_valid_public_id("TEST", "ru", is_server=True)

        # Сначала регистрируем сервер
        register_response = await client.post(
            "/api/register",
            json={
                "public_id": public_id,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
            },
        )
        assert register_response.status == 201, f"Registration failed: {await register_response.text()}"

        # Отправляем heartbeat
        response = await client.post(
            f"/api/heartbeat?public_id={public_id}&load=75"
        )
        assert response.status == 200
        data = await response.json()
        assert data["public_id"] == public_id
        assert data["load"] == 75
        assert "expires_at" in data

    @pytest.mark.asyncio
    async def test_heartbeat_not_found(self, client):
        """Heartbeat для несуществующего сервера."""
        response = await client.post(
            "/api/heartbeat?public_id=@NONEXISTENT.ru.srv"
        )
        assert response.status == 404
        data = await response.json()
        assert "Server not found" in data["error"]

    @pytest.mark.asyncio
    async def test_lookup_success(self, client, server):
        """Поиск существующего сервера."""
        public_id = make_valid_public_id("TEST", "ru", is_server=True)

        register_response = await client.post(
            "/api/register",
            json={
                "public_id": public_id,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
            },
        )
        assert register_response.status == 201, f"Registration failed: {await register_response.text()}"

        response = await client.get(f"/api/lookup/{public_id}")
        assert response.status == 200
        data = await response.json()
        assert data["server"] is not None
        assert data["server"]["public_id"] == public_id

    @pytest.mark.asyncio
    async def test_lookup_not_found(self, client):
        """Поиск несуществующего сервера."""
        response = await client.get("/api/lookup/@NONEXISTENT.ru.srv")
        assert response.status == 200
        data = await response.json()
        assert data["server"] is None

    @pytest.mark.asyncio
    async def test_region_servers(self, client, server):
        """Получение списка серверов в регионе."""
        # Регистрируем несколько серверов
        public_id_1 = make_valid_public_id("S1", "ru", is_server=True)
        public_id_2 = make_valid_public_id("S2", "ru", is_server=True)
        public_id_3 = make_valid_public_id("S3", "us", is_server=True)

        print(f"\nPublic IDs: {public_id_1}, {public_id_2}, {public_id_3}")

        resp1 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_1,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://s1.local:9877",
            },
        )
        assert resp1.status == 201, f"Registration 1 failed: {await resp1.text()}"

        resp2 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_2,
                "type": "validator",
                "region": "ru",
                "ws_url": "wss://s2.local:9877",
            },
        )
        assert resp2.status == 201, f"Registration 2 failed: {await resp2.text()}"

        resp3 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_3,
                "type": "nat",
                "region": "us",
                "ws_url": "wss://s3.local:9877",
            },
        )
        assert resp3.status == 201, f"Registration 3 failed: {await resp3.text()}"

        response = await client.get("/api/region/ru")
        assert response.status == 200
        data = await response.json()
        servers = data["servers"]
        assert len(servers) == 2, f"Expected 2 servers in ru region, got {len(servers)}: {servers}"
        assert all(s["region"] == "ru" for s in servers)

    @pytest.mark.asyncio
    async def test_region_invalid(self, client):
        """Запрос с неверным регионом."""
        response = await client.get("/api/region/rus")
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_region_with_load(self, client, server):
        """Получение серверов с нагрузкой, отсортированных."""
        public_id_1 = make_valid_public_id("S1", "ru", is_server=True)
        public_id_2 = make_valid_public_id("S2", "ru", is_server=True)
        public_id_3 = make_valid_public_id("S3", "ru", is_server=True)

        print(f"\nPublic IDs: {public_id_1}, {public_id_2}, {public_id_3}")

        # Регистрируем серверы с разной нагрузкой
        resp1 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_1,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://s1.local:9877",
            },
        )
        assert resp1.status == 201, f"Registration 1 failed: {await resp1.text()}"

        heartbeat1 = await client.post(
            f"/api/heartbeat?public_id={public_id_1}&load=45"
        )
        assert heartbeat1.status == 200, f"Heartbeat 1 failed: {await heartbeat1.text()}"

        resp2 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_2,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://s2.local:9877",
            },
        )
        assert resp2.status == 201, f"Registration 2 failed: {await resp2.text()}"

        heartbeat2 = await client.post(
            f"/api/heartbeat?public_id={public_id_2}&load=25"
        )
        assert heartbeat2.status == 200, f"Heartbeat 2 failed: {await heartbeat2.text()}"

        resp3 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_3,
                "type": "validator",
                "region": "ru",
                "ws_url": "wss://s3.local:9877",
            },
        )
        assert resp3.status == 201, f"Registration 3 failed: {await resp3.text()}"

        heartbeat3 = await client.post(
            f"/api/heartbeat?public_id={public_id_3}&load=95"
        )
        assert heartbeat3.status == 200, f"Heartbeat 3 failed: {await heartbeat3.text()}"

        response = await client.get("/api/region/ru/with-load")
        assert response.status == 200
        data = await response.json()
        servers = data["servers"]
        assert len(servers) == 2, f"Expected 2 servers (excluding 95% load), got {len(servers)}: {servers}"

        if len(servers) == 2:
            # Сортируем по нагрузке (возрастание) - ожидаем S2 (25), затем S1 (45)
            # Сервер с нагрузкой 95% исключен
            # Проверяем нагрузку, а не ID, так как ID могут быть в любом порядке
            loads = [s["load"] for s in servers]
            assert loads == [25, 45], f"Expected loads [25, 45], got {loads}"

    @pytest.mark.asyncio
    async def test_health(self, client):
        """Проверка эндпоинта /health."""
        response = await client.get("/api/health")
        assert response.status == 200
        data = await response.json()
        assert data["status"] == "healthy"
        assert "servers" in data
        assert "uptime" in data

    @pytest.mark.asyncio
    async def test_stats(self, client, server):
        """Получение статистики."""
        public_id_1 = make_valid_public_id("S1", "ru", is_server=True)
        public_id_2 = make_valid_public_id("S2", "us", is_server=True)

        resp1 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_1,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://s1.local:9877",
            },
        )
        assert resp1.status == 201, f"Registration 1 failed: {await resp1.text()}"

        resp2 = await client.post(
            "/api/register",
            json={
                "public_id": public_id_2,
                "type": "validator",
                "region": "us",
                "ws_url": "wss://s2.local:9877",
            },
        )
        assert resp2.status == 201, f"Registration 2 failed: {await resp2.text()}"

        response = await client.get("/api/stats")
        assert response.status == 200
        data = await response.json()
        assert data["total_servers"] == 2
        assert data["by_region"]["ru"] == 1
        assert data["by_region"]["us"] == 1

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, server):
        """Проверка истечения TTL."""
        # Регистрируем сервер с коротким TTL через мок
        with patch("src.server.network.rendezvous.rendezvous_server.SERVER_TTL_SECONDS", 1):
            # Создаем новый сервер для этого теста
            test_server = RendezvousServer()
            await test_server.start(host="127.0.0.1", port=0)

            try:
                # Получаем порт
                port = test_server._runner.addresses[0][1]
                public_id = make_valid_public_id("TEST", "ru", is_server=True)

                async with ClientSession() as session:
                    # Регистрируем сервер
                    resp = await session.post(
                        f"http://127.0.0.1:{port}/api/register",
                        json={
                            "public_id": public_id,
                            "type": "nat",
                            "region": "ru",
                            "ws_url": "wss://test.local:9877",
                        },
                    )
                    assert resp.status == 201, f"Registration failed: {await resp.text()}"

                    # Проверяем, что сервер существует
                    resp = await session.get(
                        f"http://127.0.0.1:{port}/api/lookup/{public_id}"
                    )
                    data = await resp.json()
                    assert data["server"] is not None

                    # Ждем истечения TTL
                    await asyncio.sleep(1.5)

                    # Запускаем очистку
                    await test_server._store.cleanup()

                    # Проверяем, что сервер удален
                    resp = await session.get(
                        f"http://127.0.0.1:{port}/api/lookup/{public_id}"
                    )
                    data = await resp.json()
                    assert data["server"] is None

            finally:
                await test_server.stop()

    @pytest.mark.asyncio
    async def test_server_info_dataclass(self):
        """Тест dataclass ServerInfo."""
        now = time.time()
        server = ServerInfo(
            public_id="@ABCD-2345-6789.ru.srv",
            type="nat",
            region="ru",
            ws_url="wss://test.local:9877",
            capacity=100,
            load=50,
            last_seen=now,
            expires_at=now + 3600,
        )

        assert server.public_id == "@ABCD-2345-6789.ru.srv"
        assert server.type == "nat"
        assert server.region == "ru"
        assert server.ws_url == "wss://test.local:9877"
        assert server.capacity == 100
        assert server.load == 50
        assert server.last_seen == now
        assert server.expires_at == now + 3600
        assert server.is_active() is True
