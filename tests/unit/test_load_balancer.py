# tests/unit/test_load_balancer.py
"""
Тесты для модуля LoadBalancer.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.server.network.load_balancer import LoadBalancer, LoadMetrics


@pytest.fixture
def message_router():
    """Мок маршрутизатора сообщений."""
    mock = MagicMock()
    mock.get_connected_clients.return_value = [
        {"public_id": "client1", "is_proxy": False},
        {"public_id": "client2", "is_proxy": True, "proxy_group": "basic"},
        {"public_id": "client3", "is_proxy": True, "proxy_group": "standard"},
        {"public_id": "client4", "is_proxy": True, "proxy_group": "privileged"},
    ]
    mock.send_to_client.return_value = True
    mock.close_connection.return_value = True
    mock.get_active_connection_count.return_value = 10
    return mock


@pytest.fixture
def rendezvous_client():
    """Мок клиента сервера знакомств."""
    mock = MagicMock()
    mock.get_servers_by_region_with_load.return_value = [
        {"public_id": "@S1.ru.srv", "ws_url": "wss://s1.duonet.net:9877", "load": 35},
        {"public_id": "@S2.ru.srv", "ws_url": "wss://s2.duonet.net:9877", "load": 45},
        {"public_id": "@S3.ru.srv", "ws_url": "wss://s3.duonet.net:9877", "load": 85},
    ]
    return mock


@pytest.fixture
def load_balancer(message_router, rendezvous_client):
    """Создание балансировщика."""
    return LoadBalancer(
        message_router=message_router,
        rendezvous_client=rendezvous_client,
        server_public_id="@LOCAL-1234-5678.ru.srv",
    )


class TestLoadBalancer:
    """Тесты для LoadBalancer."""

    def test_extract_region(self, load_balancer):
        """Извлечение региона из Public ID."""
        region = load_balancer._extract_region("@TEST-1234-5678.ru.srv")
        assert region == "ru"

        region = load_balancer._extract_region("@TEST-1234-5678.us.srv")
        assert region == "us"

    def test_get_current_metrics(self, load_balancer):
        """Получение текущих метрик."""
        with patch("psutil.cpu_percent", return_value=45.0):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value.percent = 60.0
                metrics = load_balancer.get_current_metrics()

                assert metrics.cpu_percent == 45.0
                assert metrics.memory_percent == 60.0
                assert metrics.active_messaging_sessions == 10
                assert metrics.timestamp > 0

    def test_is_warning(self, load_balancer):
        """Проверка порога предупреждения."""
        with patch.object(load_balancer, "get_load_percent", return_value=0.75):
            assert load_balancer.is_warning() is False

        with patch.object(load_balancer, "get_load_percent", return_value=0.85):
            assert load_balancer.is_warning() is True

    def test_is_critical(self, load_balancer):
        """Проверка критического порога."""
        with patch.object(load_balancer, "get_load_percent", return_value=0.85):
            assert load_balancer.is_critical() is False

        with patch.object(load_balancer, "get_load_percent", return_value=0.95):
            assert load_balancer.is_critical() is True

    def test_get_recommended_servers(self, load_balancer, rendezvous_client):
        """Получение рекомендуемых серверов."""
        servers = load_balancer.get_recommended_servers(limit=2)

        assert len(servers) == 2
        assert servers[0]["public_id"] == "@S1.ru.srv"
        assert servers[1]["public_id"] == "@S2.ru.srv"
        # Сервер с нагрузкой 85% не включен
        assert "@S3.ru.srv" not in [s["public_id"] for s in servers]

    def test_get_recommended_servers_excludes_self(self, load_balancer, rendezvous_client):
        """Рекомендуемые серверы исключают текущий."""
        rendezvous_client.get_servers_by_region_with_load.return_value.append(
            {"public_id": "@LOCAL-1234-5678.ru.srv", "ws_url": "wss://local:9877", "load": 30}
        )

        servers = load_balancer.get_recommended_servers()
        assert not any(s["public_id"] == "@LOCAL-1234-5678.ru.srv" for s in servers)

    def test_get_priority_clients(self, load_balancer, message_router):
        """Сортировка клиентов по приоритету."""
        clients = load_balancer.get_priority_clients()

        # Проверяем порядок: чужие → basic → standard → privileged
        client_ids = [c["public_id"] for c in clients]
        assert client_ids[0] == "client1"   # чужой
        assert client_ids[1] == "client2"   # basic
        assert client_ids[2] == "client3"   # standard
        assert client_ids[3] == "client4"   # privileged

    def test_suggest_reconnect_success(self, load_balancer, message_router):
        """Успешная отправка рекомендации."""
        result = load_balancer.suggest_reconnect("client1")
        assert result is True
        message_router.send_to_client.assert_called_once()

        call_args = message_router.send_to_client.call_args[0]
        assert call_args[0] == "client1"
        assert call_args[1]["type"] == "switch_server"
        assert "target_servers" in call_args[1]["data"]

    def test_suggest_reconnect_no_servers(self, load_balancer, rendezvous_client):
        """Нет серверов для переключения."""
        rendezvous_client.get_servers_by_region_with_load.return_value = []
        result = load_balancer.suggest_reconnect("client1")
        assert result is False

    def test_balance(self, load_balancer, message_router):
        """Запуск балансировки."""
        # Значения нагрузки:
        # 1. is_critical() в начале: 0.92 -> True
        # 2. is_critical() для client1: 0.92 -> True (отправляем рекомендацию)
        # 3. is_critical() для client2: 0.92 -> True (отправляем рекомендацию)
        # 4. is_critical() для client3: 0.85 -> False (останавливаемся)
        load_values = [0.92, 0.92, 0.92, 0.85, 0.78]

        with patch.object(load_balancer, "get_load_percent", side_effect=load_values):
            with patch.object(load_balancer, "get_priority_clients", return_value=[
                {"public_id": "client1"},
                {"public_id": "client2"},
                {"public_id": "client3"},
                {"public_id": "client4"},
            ]):
                with patch.object(load_balancer, "get_recommended_servers", return_value=[
                    {"ws_url": "wss://s1.duonet.net:9877", "load": 35}
                ]):
                    count = load_balancer.balance()

                    assert count == 2
                    assert message_router.send_to_client.call_count == 2

    def test_balance_stops_when_load_normal(self, load_balancer, message_router):
        """Балансировка останавливается при нормальной нагрузке."""
        # Значения нагрузки:
        # 1. is_critical() в начале: 0.92 -> True
        # 2. is_critical() для client1: 0.92 -> True (отправляем рекомендацию)
        # 3. is_critical() для client2: 0.72 -> False (останавливаемся, client2 не получает рекомендацию)
        # Таким образом, должна быть отправлена только 1 рекомендация
        load_values = [0.92, 0.92, 0.72, 0.72]

        with patch.object(load_balancer, "get_load_percent", side_effect=load_values):
            with patch.object(load_balancer, "get_priority_clients", return_value=[
                {"public_id": "client1"},
                {"public_id": "client2"},
                {"public_id": "client3"},
                {"public_id": "client4"},
            ]):
                with patch.object(load_balancer, "get_recommended_servers", return_value=[
                    {"ws_url": "wss://s1.duonet.net:9877", "load": 35}
                ]):
                    count = load_balancer.balance()

                    # После первого переключения нагрузка стала 72% — останавливаемся
                    assert count == 1
                    assert message_router.send_to_client.call_count == 1

    def test_start_stop_monitoring(self, load_balancer):
        """Запуск и остановка мониторинга."""
        with patch("threading.Thread") as mock_thread:
            load_balancer.start()
            assert load_balancer._running is True
            mock_thread.assert_called_once()

            load_balancer.stop()
            assert load_balancer._running is False

    def test_handle_client_reconnect(self, load_balancer, message_router):
        """Обработка подтверждения переключения."""
        result = load_balancer.handle_client_reconnect("client1", "wss://s1.duonet.net:9877")
        assert result is True
        message_router.close_connection.assert_called_with("client1")

    def test_load_metrics_dataclass(self):
        """Тест dataclass LoadMetrics."""
        metrics = LoadMetrics(
            cpu_percent=45.0,
            memory_percent=60.0,
            active_messaging_sessions=10,
            messages_per_second=5.5,
            bytes_per_second=1024.0,
            timestamp=1234567890.0,
        )
        assert metrics.cpu_percent == 45.0
        assert metrics.memory_percent == 60.0
        assert metrics.active_messaging_sessions == 10
        assert metrics.messages_per_second == 5.5
        assert metrics.bytes_per_second == 1024.0
        assert metrics.timestamp == 1234567890.0
