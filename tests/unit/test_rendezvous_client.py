# tests/unit/test_rendezvous_client.py
"""
Тесты для модуля RendezvousClient.
"""

import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest

from src.common.identity.public_id import generate_public_id, is_server_id, is_valid_format
from src.server.network.rendezvous.rendezvous_client import RendezvousClient


@pytest.fixture
def rendezvous_url():
    return "http://localhost:9878"


@pytest.fixture
def client(rendezvous_url):
    return RendezvousClient(rendezvous_url)


@pytest.fixture
def valid_server_id():
    """Генерация валидного серверного ID для тестов."""
    seed_hash = hashlib.sha256(b"test_server_123").digest()
    return generate_public_id(seed_hash, "ru", is_server=True)


class TestRendezvousClient:
    """Тесты для RendezvousClient."""

    def test_find_server_by_id_success(self, client, valid_server_id):
        """Поиск существующего сервера."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "server": {
                "public_id": valid_server_id,
                "type": "nat",
                "region": "ru",
                "ws_url": "wss://test.local:9877",
                "capacity": 100,
                "load": 0,
            }
        }

        with patch.object(client._session, "get", return_value=mock_response) as mock_get:
            result = client.find_server_by_id(valid_server_id)
            assert result is not None
            assert result["public_id"] == valid_server_id
            assert result["type"] == "nat"
            mock_get.assert_called_once()

    def test_find_server_by_id_not_found(self, client, valid_server_id):
        """Поиск несуществующего сервера."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"server": None}

        with patch.object(client._session, "get", return_value=mock_response):
            result = client.find_server_by_id(valid_server_id)
            assert result is None

    def test_find_server_by_id_invalid_format(self, client):
        """Поиск с неверным форматом ID."""
        result = client.find_server_by_id("invalid")
        assert result is None

        result = client.find_server_by_id("@CLIENT.ru")
        assert result is None

    def test_find_servers_by_region(self, client):
        """Поиск серверов по региону."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                {"public_id": "server1", "type": "nat", "region": "ru"},
                {"public_id": "server2", "type": "validator", "region": "ru"},
            ]
        }

        with patch.object(client._session, "get", return_value=mock_response):
            servers = client.find_servers_by_region("ru")
            assert len(servers) == 2

    def test_find_servers_by_region_with_type(self, client):
        """Поиск серверов по региону с фильтром по типу."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                {"public_id": "server1", "type": "nat", "region": "ru"},
                {"public_id": "server2", "type": "validator", "region": "ru"},
            ]
        }

        with patch.object(client._session, "get", return_value=mock_response):
            validators = client.find_validators_by_region("ru")
            assert len(validators) == 1
            assert validators[0]["type"] == "validator"

            nat_servers = client.find_nat_servers_by_region("ru")
            assert len(nat_servers) == 1
            assert nat_servers[0]["type"] == "nat"

    def test_find_servers_by_region_invalid(self, client):
        """Поиск с неверным регионом."""
        servers = client.find_servers_by_region("rus")
        assert servers == []

        servers = client.find_servers_by_region("r1")
        assert servers == []

    def test_resolve_contact_by_id(self, client, valid_server_id):
        """Поиск контакта по Public ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "server": {"public_id": valid_server_id, "type": "nat"}
        }

        with patch.object(client._session, "get", return_value=mock_response):
            result = client.resolve_contact(valid_server_id)
            assert result is not None
            assert result["public_id"] == valid_server_id

    def test_resolve_contact_region_mask_client(self, client):
        """Поиск по маске @*.ru."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [{"public_id": "server1", "type": "nat"}]
        }

        with patch.object(client._session, "get", return_value=mock_response):
            result = client.resolve_contact("@*.ru")
            assert result is not None
            assert result["type"] == "list"
            assert len(result["items"]) == 1

    def test_resolve_contact_region_mask_server(self, client):
        """Поиск по маске @*.ru.srv."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [{"public_id": "server1", "type": "nat"}]
        }

        with patch.object(client._session, "get", return_value=mock_response):
            result = client.resolve_contact("@*.ru.srv")
            assert result is not None
            assert result["type"] == "list"

    def test_resolve_contact_invalid(self, client):
        """Поиск с неверным идентификатором."""
        result = client.resolve_contact("")
        assert result is None

        result = client.resolve_contact("invalid")
        assert result is None

    def test_register_server_success(self, client, valid_server_id):
        """Успешная регистрация сервера."""
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch.object(client._session, "post", return_value=mock_response) as mock_post:
            result = client.register_server(
                public_id=valid_server_id,
                server_type="nat",
                region="ru",
                ws_url="wss://test.local:9877",
                capacity=100,
            )
            assert result is True
            mock_post.assert_called_once()

    def test_register_server_failure(self, client):
        """Ошибка регистрации сервера."""
        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch.object(client._session, "post", return_value=mock_response):
            result = client.register_server(
                public_id="invalid",
                server_type="nat",
                region="ru",
                ws_url="wss://test.local:9877",
            )
            assert result is False

    def test_send_heartbeat_success(self, client, valid_server_id):
        """Успешная отправка heartbeat."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(client._session, "post", return_value=mock_response) as mock_post:
            result = client.send_heartbeat(valid_server_id, load=50)
            assert result is True
            mock_post.assert_called_once()

    def test_send_heartbeat_failure(self, client):
        """Ошибка отправки heartbeat."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client._session, "post", return_value=mock_response):
            result = client.send_heartbeat("invalid")
            assert result is False

    def test_cache(self, client, valid_server_id):
        """Проверка кэширования."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"server": {"public_id": valid_server_id}}

        with patch.object(client._session, "get", return_value=mock_response) as mock_get:
            # Первый запрос
            client.find_server_by_id(valid_server_id)
            # Второй запрос должен использовать кэш
            client.find_server_by_id(valid_server_id)

            assert mock_get.call_count == 1

    def test_invalidate_cache_key(self, client, valid_server_id):
        """Инвалидация конкретного ключа."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"server": {"public_id": valid_server_id}}

        with patch.object(client._session, "get", return_value=mock_response) as mock_get:
            client.find_server_by_id(valid_server_id)
            client.invalidate_cache(f"server:{valid_server_id}")
            client.find_server_by_id(valid_server_id)

            assert mock_get.call_count == 2

    def test_invalidate_cache_all(self, client):
        """Очистка всего кэша."""
        client._cache["key1"] = ("value1", time.time())
        client._cache["key2"] = ("value2", time.time())

        client.invalidate_cache()

        assert len(client._cache) == 0

    def test_context_manager(self):
        """Проверка контекстного менеджера."""
        with RendezvousClient("http://localhost:9878") as c:
            assert c._session is not None
        # После выхода из контекста сессия закрыта

    def test_get_servers_by_region_with_load(self, client):
        """Получение серверов с нагрузкой."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                {"public_id": "server1", "ws_url": "wss://s1.local:9877", "load": 45},
                {"public_id": "server2", "ws_url": "wss://s2.local:9877", "load": 25},
            ]
        }

        with patch.object(client._session, "get", return_value=mock_response):
            servers = client.get_servers_by_region_with_load("ru")
            assert len(servers) == 2

    def test_get_servers_by_region_with_load_invalid(self, client):
        """Получение серверов с неверным регионом."""
        servers = client.get_servers_by_region_with_load("rus")
        assert servers == []
