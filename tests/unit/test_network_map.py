# tests/unit/test_network_map.py
"""
Тесты для модуля NetworkMap.
"""

import asyncio
import json
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.network.network_map import NetworkMapManager, NetworkNode, NODE_TTL_SECONDS
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def ws_manager():
    """Создаёт мок WebSocketManager с асинхронным broadcast_to_all."""
    mock = MagicMock()
    # Используем AsyncMock для асинхронного метода
    mock.broadcast_to_all = AsyncMock(return_value=1)
    return mock


@pytest.fixture
def network_map(storage, ws_manager):
    manager = NetworkMapManager(storage, ws_manager)
    return manager


class TestNetworkNode:
    """Тесты для NetworkNode."""

    def test_node_creation(self):
        """Создание узла."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        assert node.node_id == "test.local"
        assert node.node_type == "rendezvous"
        assert node.address == "192.168.1.100"
        assert node.port == 9878

    def test_is_active(self):
        """Проверка активности узла."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
            expires_at=time.time() + 100,
        )
        assert node.is_active() is True

        node.expires_at = time.time() - 1
        assert node.is_active() is False

    def test_update_heartbeat(self):
        """Обновление heartbeat."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        old_expires = node.expires_at
        time.sleep(0.01)
        node.update_heartbeat()
        assert node.expires_at > old_expires

    def test_to_dict(self):
        """Преобразование в словарь."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
            metadata={"version": "1.0"},
        )
        d = node.to_dict()
        assert d["node_id"] == "test.local"
        assert d["node_type"] == "rendezvous"
        assert d["address"] == "192.168.1.100"
        assert d["port"] == 9878
        assert d["metadata"]["version"] == "1.0"

    def test_from_dict(self):
        """Создание из словаря."""
        data = {
            "node_id": "test.local",
            "node_type": "rendezvous",
            "address": "192.168.1.100",
            "port": 9878,
            "metadata": {"version": "1.0"},
        }
        node = NetworkNode.from_dict(data)
        assert node.node_id == "test.local"
        assert node.node_type == "rendezvous"
        assert node.address == "192.168.1.100"
        assert node.port == 9878
        assert node.metadata["version"] == "1.0"


class TestNetworkMapManager:
    """Тесты для NetworkMapManager."""

    @pytest.mark.asyncio
    async def test_add_node(self, network_map):
        """Добавление узла."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        result = await network_map.add_node(node)
        assert result is True

        retrieved = await network_map.get_node("test.local")
        assert retrieved is not None
        assert retrieved.address == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_add_node_update(self, network_map):
        """Обновление существующего узла."""
        node1 = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await network_map.add_node(node1)

        node2 = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.101",
            port=9879,
        )
        await network_map.add_node(node2)

        retrieved = await network_map.get_node("test.local")
        assert retrieved.address == "192.168.1.101"
        assert retrieved.port == 9879

    @pytest.mark.asyncio
    async def test_remove_node(self, network_map):
        """Удаление узла."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await network_map.add_node(node)

        result = await network_map.remove_node("test.local")
        assert result is True

        retrieved = await network_map.get_node("test.local")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_remove_node_not_found(self, network_map):
        """Удаление несуществующего узла."""
        result = await network_map.remove_node("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_nodes_by_type(self, network_map):
        """Получение узлов по типу."""
        node1 = NetworkNode(
            node_id="test1.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        node2 = NetworkNode(
            node_id="test2.local",
            node_type="client",
            address="192.168.1.101",
            port=8000,
            public_id="@TEST.ru",
        )
        await network_map.add_node(node1)
        await network_map.add_node(node2)

        rendezvous = await network_map.get_nodes_by_type("rendezvous")
        assert len(rendezvous) == 1
        assert rendezvous[0].node_id == "test1.local"

        clients = await network_map.get_nodes_by_type("client")
        assert len(clients) == 1
        assert clients[0].node_id == "test2.local"

    @pytest.mark.asyncio
    async def test_get_all_nodes(self, network_map):
        """Получение всех активных узлов."""
        node1 = NetworkNode(
            node_id="test1.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        node2 = NetworkNode(
            node_id="test2.local",
            node_type="client",
            address="192.168.1.101",
            port=8000,
        )
        await network_map.add_node(node1)
        await network_map.add_node(node2)

        nodes = await network_map.get_all_nodes()
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_get_best_rendezvous(self, network_map):
        """Получение лучшего Rendezvous сервера."""
        node1 = NetworkNode(
            node_id="test1.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        node2 = NetworkNode(
            node_id="test2.local",
            node_type="rendezvous",
            address="192.168.1.101",
            port=9879,
        )
        await network_map.add_node(node1)
        await network_map.add_node(node2)

        best = await network_map.get_best_rendezvous()
        assert best is not None
        # В прототипе возвращается первый
        assert best.node_id in ["test1.local", "test2.local"]

    @pytest.mark.asyncio
    async def test_update_heartbeat(self, network_map):
        """Обновление heartbeat."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await network_map.add_node(node)

        old_expires = node.expires_at
        await asyncio.sleep(0.1)
        result = await network_map.update_heartbeat("test.local")
        assert result is True

        updated = await network_map.get_node("test.local")
        assert updated.expires_at > old_expires

    @pytest.mark.asyncio
    async def test_update_heartbeat_not_found(self, network_map):
        """Обновление heartbeat несуществующего узла."""
        result = await network_map.update_heartbeat("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_with_client(self, network_map):
        """Синхронизация с клиентом."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await network_map.add_node(node)

        nodes = await network_map.sync_with_client("@CLIENT.ru")
        assert len(nodes) == 1
        assert nodes[0].node_id == "test.local"

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, network_map):
        """Очистка истекших узлов."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
            expires_at=time.time() - 100,  # уже истек
        )
        await network_map.add_node(node)

        count = await network_map.cleanup_expired()
        assert count == 1

        retrieved = await network_map.get_node("test.local")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_persistence(self, storage):
        """Персистентность данных."""
        # Создаём первый менеджер и добавляем узел
        manager1 = NetworkMapManager(storage, None)
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await manager1.add_node(node)
        await manager1.stop_monitor()

        # Создаём второй менеджер и проверяем загрузку
        manager2 = NetworkMapManager(storage, None)
        await manager2.start_monitor()

        nodes = await manager2.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "test.local"

        await manager2.stop_monitor()

    @pytest.mark.asyncio
    async def test_broadcast_on_add(self, network_map, ws_manager):
        """Рассылка при добавлении узла."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await network_map.add_node(node)

        ws_manager.broadcast_to_all.assert_called_once()
        call_args = ws_manager.broadcast_to_all.call_args[0][0]
        assert call_args["type"] == "network_update"
        assert call_args["data"]["action"] == "add"

    @pytest.mark.asyncio
    async def test_broadcast_on_remove(self, network_map, ws_manager):
        """Рассылка при удалении узла."""
        node = NetworkNode(
            node_id="test.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        await network_map.add_node(node)

        ws_manager.broadcast_to_all.reset_mock()
        await network_map.remove_node("test.local")

        ws_manager.broadcast_to_all.assert_called_once()
        call_args = ws_manager.broadcast_to_all.call_args[0][0]
        assert call_args["type"] == "network_update"
        assert call_args["data"]["action"] == "remove"

    @pytest.mark.asyncio
    async def test_get_stats(self, network_map):
        """Получение статистики сети."""
        node1 = NetworkNode(
            node_id="test1.local",
            node_type="rendezvous",
            address="192.168.1.100",
            port=9878,
        )
        node2 = NetworkNode(
            node_id="test2.local",
            node_type="client",
            address="192.168.1.101",
            port=8000,
            public_id="@CLIENT.ru",
        )
        await network_map.add_node(node1)
        await network_map.add_node(node2)

        stats = await network_map.get_stats()
        assert stats["total_nodes"] == 2
        assert stats["by_type"]["rendezvous"] == 1
        assert stats["by_type"]["client"] == 1
        assert stats["active_rendezvous"] == 1
        assert stats["active_clients"] == 1

    @pytest.mark.asyncio
    async def test_start_stop_monitor(self, network_map):
        """Запуск и остановка мониторинга."""
        await network_map.start_monitor()
        assert network_map._running is True
        assert network_map._monitor_task is not None

        await network_map.stop_monitor()
        assert network_map._running is False
