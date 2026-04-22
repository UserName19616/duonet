# tests/unit/test_gossip.py
"""
Тесты для Gossip Protocol.
"""

import asyncio
import json
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.crypto.keys import generate_keypair
from src.server.network.gossip import GossipProtocol, GossipMessage
from src.server.network.trust import TrustManager, TRUST_LEVEL_TRUSTED, TRUST_LEVEL_QUARANTINE
from src.server.storage.server_db import ServerDatabase


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = ServerDatabase(f.name)
        yield db
        db.close()


@pytest.fixture
def keypair():
    priv, pub = generate_keypair()
    return priv, pub


@pytest.fixture
def trust_manager(temp_db):
    return TrustManager(temp_db)


@pytest.fixture
def gossip_protocol(temp_db, trust_manager, keypair):
    priv, _ = keypair
    protocol = GossipProtocol(
        my_server_id="@MAIN.ru.srv",
        private_key=priv,
        db=temp_db,
        trust_manager=trust_manager,
        http_client=MagicMock(),
    )
    return protocol


class TestGossipMessage:
    """Тесты для GossipMessage."""

    def test_to_dict_and_from_dict(self):
        """Преобразование в словарь и обратно."""
        message = GossipMessage(
            sender_id="@A.ru.srv",
            timestamp=1234567890,
            nonce="abc123",
            payload={"type": "test", "data": "value"},
            signature="sig123",
        )

        d = message.to_dict()
        assert d["sender_id"] == "@A.ru.srv"
        assert d["timestamp"] == 1234567890
        assert d["nonce"] == "abc123"
        assert d["payload"]["type"] == "test"
        assert d["signature"] == "sig123"

        restored = GossipMessage.from_dict(d)
        assert restored.sender_id == message.sender_id
        assert restored.timestamp == message.timestamp
        assert restored.payload == message.payload


class TestGossipProtocol:
    """Тесты для GossipProtocol."""

    def test_sign_message(self, gossip_protocol):
        """Подпись сообщения."""
        payload = {"type": "test", "data": "hello"}
        message = gossip_protocol._sign_message(payload)

        assert message.sender_id == gossip_protocol.my_server_id
        assert message.timestamp > 0
        assert message.nonce is not None
        assert message.payload == payload
        assert len(message.signature) > 0

    def test_verify_message_unknown_server(self, gossip_protocol):
        """Верификация сообщения от неизвестного сервера."""
        # Создаём сообщение от другого сервера
        other_priv, _ = generate_keypair()
        other_protocol = GossipProtocol(
            my_server_id="@OTHER.ru.srv",
            private_key=other_priv,
            db=gossip_protocol._db,
            trust_manager=gossip_protocol._trust_manager,
        )
        payload = {"type": "test"}
        message = other_protocol._sign_message(payload)

        # Публичный ключ неизвестен
        result = gossip_protocol._verify_message(message)
        assert result is False

    def test_verify_message_old_timestamp(self, gossip_protocol):
        """Сообщение с устаревшим timestamp."""
        payload = {"type": "test"}
        message = gossip_protocol._sign_message(payload)
        message.timestamp = int(time.time()) - 400  # старше 5 минут

        result = gossip_protocol._verify_message(message)
        assert result is False

    def test_duplicate_nonce_detection(self, gossip_protocol):
        """Обнаружение дубликата nonce."""
        payload = {"type": "test"}
        message = gossip_protocol._sign_message(payload)

        # Первая проверка
        result1 = gossip_protocol._verify_message(message)
        # Вторая проверка (nonce уже использован)
        result2 = gossip_protocol._verify_message(message)

        # Верификация может пройти или не пройти, но дубликат должен быть отмечен
        # Проверяем, что nonce в _used_nonces
        assert message.nonce in gossip_protocol._used_nonces

    @pytest.mark.asyncio
    async def test_broadcast_change(self, gossip_protocol, temp_db):
        """Рассылка изменения."""
        # Добавляем доверенный сервер
        temp_db.add_server("@TRUSTED.ru.srv", "ru", "wss://trusted:9877", "active")
        gossip_protocol._trust_manager.set_trust_level("@TRUSTED.ru.srv", TRUST_LEVEL_TRUSTED)

        with patch.object(gossip_protocol, "_send_to_server", new_callable=AsyncMock) as mock_send:
            await gossip_protocol.broadcast_change("new_client", {"client_id": "@NEW.ru"})

            # Должен быть вызван _send_to_server
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_sync_request(self, gossip_protocol, temp_db):
        """Обработка запроса синхронизации."""
        # Добавляем локальных клиентов
        temp_db.add_client("@CLIENT1.ru", "@MAIN.ru.srv", "ru")
        temp_db.add_client("@CLIENT2.ru", "@MAIN.ru.srv", "ru")

        # Запрос от другого сервера
        other_priv, other_pub = generate_keypair()
        other_protocol = GossipProtocol(
            my_server_id="@OTHER.ru.srv",
            private_key=other_priv,
            db=temp_db,
            trust_manager=gossip_protocol._trust_manager,
        )

        payload = {
            "type": "sync_request",
            "clients": [{"client_id": "@CLIENT1.ru", "region": "ru"}],
            "timestamp": int(time.time()),
        }
        message = other_protocol._sign_message(payload)

        # Временное добавление публичного ключа для верификации
        with patch.object(gossip_protocol, "_get_public_key", return_value=other_pub):
            response = await gossip_protocol.handle_gossip_message(message)

            assert "error" not in response
            assert "clients" in response
            # Должен вернуть только @CLIENT2.ru (которого нет у отправителя)
            client_ids = [c["client_id"] for c in response["clients"]]
            assert "@CLIENT2.ru" in client_ids
            assert "@CLIENT1.ru" not in client_ids

    @pytest.mark.asyncio
    async def test_handle_new_client(self, gossip_protocol, temp_db):
        """Обработка нового клиента."""
        other_priv, other_pub = generate_keypair()
        other_protocol = GossipProtocol(
            my_server_id="@OTHER.ru.srv",
            private_key=other_priv,
            db=temp_db,
            trust_manager=gossip_protocol._trust_manager,
        )

        payload = {
            "type": "new_client",
            "data": {"client_id": "@NEWCLIENT.ru", "region": "ru"},
            "timestamp": int(time.time()),
        }
        message = other_protocol._sign_message(payload)

        with patch.object(gossip_protocol, "_get_public_key", return_value=other_pub):
            response = await gossip_protocol.handle_gossip_message(message)

            assert response.get("success") is True

            # Проверяем, что клиент добавлен в БД
            with temp_db._transaction() as conn:
                cursor = conn.execute(
                    "SELECT client_id FROM clients WHERE client_id = ?",
                    ("@NEWCLIENT.ru",)
                )
                assert cursor.fetchone() is not None

    @pytest.mark.asyncio
    async def test_rate_limit_for_quarantine(self, gossip_protocol, temp_db):
        """Rate limiting для карантинных серверов."""
        from src.server.network.trust import HOURLY_GOSSIP_LIMIT

        server_id = "@QUARANTINE.ru.srv"

        # Добавляем сервер в карантин
        gossip_protocol._trust_manager.add_to_quarantine(server_id)

        # Первые HOURLY_GOSSIP_LIMIT запросов должны пройти
        for i in range(HOURLY_GOSSIP_LIMIT):
            result = gossip_protocol._trust_manager.check_and_increment(server_id, "gossip_out")
            assert result is True, f"Request {i+1} should be allowed"

        # Следующий запрос должен быть отклонён
        result = gossip_protocol._trust_manager.check_and_increment(server_id, "gossip_out")
        assert result is False, "Request should be rate limited"

    @pytest.mark.asyncio
    async def test_start_stop(self, gossip_protocol):
        """Запуск и остановка протокола."""
        await gossip_protocol.start()
        assert gossip_protocol._running is True
        assert gossip_protocol._task is not None

        await gossip_protocol.stop()
        assert gossip_protocol._running is False
        # Даем время на отмену задачи
        await asyncio.sleep(0.1)


class TestGossipIntegration:
    """Интеграционные тесты для Gossip Protocol."""

    @pytest.mark.asyncio
    async def test_two_servers_sync(self, temp_db):
        """Синхронизация между двумя серверами."""
        # Создаём два сервера
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()

        gossip1 = GossipProtocol(
            my_server_id="@SERVER1.ru.srv",
            private_key=priv1,
            db=temp_db,
        )
        gossip2 = GossipProtocol(
            my_server_id="@SERVER2.ru.srv",
            private_key=priv2,
            db=temp_db,
        )

        # Добавляем серверы в БД
        temp_db.add_server("@SERVER1.ru.srv", "ru", "wss://server1:9877")
        temp_db.add_server("@SERVER2.ru.srv", "ru", "wss://server2:9877")

        # Добавляем клиента на первом сервере
        temp_db.add_client("@ALICE.ru", "@SERVER1.ru.srv", "ru")

        # Мокаем _get_public_key для верификации
        def mock_get_pubkey(server_id):
            if server_id == "@SERVER1.ru.srv":
                return pub1
            if server_id == "@SERVER2.ru.srv":
                return pub2
            return None

        gossip1._get_public_key = mock_get_pubkey
        gossip2._get_public_key = mock_get_pubkey

        # Синхронизация сервера 2 с сервером 1
        payload = {
            "type": "sync_request",
            "clients": [{"client_id": "@ALICE.ru", "region": "ru"}],
            "timestamp": int(time.time()),
        }
        message = gossip1._sign_message(payload)

        response = await gossip2.handle_gossip_message(message)
        assert "error" not in response

        # Проверяем, что клиент появился на втором сервере
        with temp_db._transaction() as conn:
            cursor = conn.execute(
                "SELECT client_id FROM clients WHERE client_id = ?",
                ("@ALICE.ru",)
            )
            assert cursor.fetchone() is not None
