# tests/unit/test_mdns.py
"""
Тесты для модуля MDNS.
"""

import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.server.network.mdns import MDNSService, MDNSServiceManager, RendezvousService


class TestMDNSService:
    """Тесты для MDNSService."""

    def test_service_creation(self):
        """Создание сервиса."""
        service = MDNSService()
        assert service is not None

    @patch("src.server.network.mdns.zeroconf.Zeroconf")
    @patch("src.server.network.mdns.zeroconf.ServiceInfo")
    def test_publish_rendezvous(self, mock_service_info, mock_zeroconf):
        """Публикация сервиса."""
        # Настройка моков
        mock_zeroconf_instance = MagicMock()
        mock_zeroconf.return_value = mock_zeroconf_instance

        mock_service_info_instance = MagicMock()
        mock_service_info.return_value = mock_service_info_instance

        service = MDNSService()
        service.publish_rendezvous(port=9878)

        # Проверяем вызовы
        mock_zeroconf.assert_called_once()
        mock_service_info.assert_called_once()
        mock_zeroconf_instance.register_service.assert_called_once_with(mock_service_info_instance)
        assert service._service_info is not None

    @patch("src.server.network.mdns.zeroconf.Zeroconf")
    @patch("src.server.network.mdns.zeroconf.ServiceInfo")
    def test_stop_publish(self, mock_service_info, mock_zeroconf):
        """Остановка публикации."""
        # Настройка моков
        mock_zeroconf_instance = MagicMock()
        mock_zeroconf.return_value = mock_zeroconf_instance

        mock_service_info_instance = MagicMock()
        mock_service_info.return_value = mock_service_info_instance

        service = MDNSService()
        service.publish_rendezvous(port=9878)
        service.stop()

        # Проверяем, что сервис был отменен
        mock_zeroconf_instance.unregister_service.assert_called_once_with(mock_service_info_instance)
        assert service._service_info is None
        assert service._zeroconf is None

    @patch("src.server.network.mdns.zeroconf.Zeroconf")
    @patch("src.server.network.mdns.zeroconf.ServiceBrowser")
    def test_discover_rendezvous_timeout(self, mock_service_browser, mock_zeroconf):
        """Поиск сервисов с таймаутом."""
        # Настройка моков
        mock_zeroconf_instance = MagicMock()
        mock_zeroconf.return_value = mock_zeroconf_instance

        mock_browser_instance = MagicMock()
        mock_service_browser.return_value = mock_browser_instance

        service = MDNSService()
        services = service.discover_rendezvous(timeout=0.1)

        # Проверяем, что браузер был создан и отменен
        mock_service_browser.assert_called_once()
        mock_browser_instance.cancel.assert_called_once()
        mock_zeroconf_instance.close.assert_called_once()

        # Должен вернуть пустой список при отсутствии сервисов
        assert isinstance(services, list)
        assert len(services) == 0

    def test_get_first_rendezvous_no_services(self):
        """Получение первого сервиса при отсутствии."""
        service = MDNSService()
        result = service.get_first_rendezvous(timeout=0.1)
        assert result is None

    def test_rendezvous_service_dataclass(self):
        """Тест dataclass RendezvousService."""
        service = RendezvousService(
            name="test.local",
            address="192.168.1.100",
            port=9878,
            properties={"version": "1.0"},
        )

        assert service.name == "test.local"
        assert service.address == "192.168.1.100"
        assert service.port == 9878
        assert service.properties["version"] == "1.0"

    def test_rendezvous_service_to_dict(self):
        """Преобразование в словарь."""
        service = RendezvousService(
            name="test.local",
            address="192.168.1.100",
            port=9878,
        )

        d = service.to_dict()
        assert d["name"] == "test.local"
        assert d["address"] == "192.168.1.100"
        assert d["port"] == 9878
        assert d["type"] == "rendezvous"

    @patch("src.server.network.mdns.zeroconf.Zeroconf")
    def test_publish_rendezvous_already_published(self, mock_zeroconf):
        """Публикация уже опубликованного сервиса."""
        mock_zeroconf_instance = MagicMock()
        mock_zeroconf.return_value = mock_zeroconf_instance

        service = MDNSService()
        service._zeroconf = MagicMock()  # Имитируем уже запущенный сервис

        # Пытаемся опубликовать снова
        service.publish_rendezvous(port=9878)

        # Проверяем, что новый Zeroconf не создавался
        mock_zeroconf.assert_not_called()


class TestMDNSServiceManager:
    """Тесты для MDNSServiceManager."""

    def test_manager_start_stop(self):
        """Запуск и остановка менеджера."""
        manager = MDNSServiceManager()
        manager.start()
        assert manager._running is True

        manager.stop()
        assert manager._running is False

    @patch("src.server.network.mdns.MDNSService")
    def test_publish(self, mock_service_class):
        """Публикация через менеджер."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        manager = MDNSServiceManager()
        manager._service = mock_service
        manager.publish(port=9878, name="test")

        mock_service.publish_rendezvous.assert_called_once_with(9878, "test")

    @patch("src.server.network.mdns.MDNSService")
    def test_discover(self, mock_service_class):
        """Поиск через менеджер."""
        mock_service = MagicMock()
        mock_service.discover_rendezvous.return_value = []
        mock_service_class.return_value = mock_service

        manager = MDNSServiceManager()
        manager._service = mock_service
        result = manager.discover(timeout=0.5)

        mock_service.discover_rendezvous.assert_called_once_with(0.5)
        assert result == []

    @patch("src.server.network.mdns.MDNSService")
    def test_get_first(self, mock_service_class):
        """Получение первого сервиса через менеджер."""
        mock_service = MagicMock()
        mock_service.get_first_rendezvous.return_value = None
        mock_service_class.return_value = mock_service

        manager = MDNSServiceManager()
        manager._service = mock_service
        result = manager.get_first(timeout=0.5)

        mock_service.get_first_rendezvous.assert_called_once_with(0.5)
        assert result is None

    def test_set_on_discovery_callback(self):
        """Установка callback."""
        manager = MDNSServiceManager()

        def callback(service):
            pass

        manager.set_on_discovery_callback(callback)
        assert manager._on_discovery_callback == callback

    @patch("src.server.network.mdns.MDNSService")
    def test_manager_stop_calls_service_stop(self, mock_service_class):
        """Проверка вызова stop у сервиса при остановке менеджера."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        manager = MDNSServiceManager()
        manager._service = mock_service
        manager.start()
        manager.stop()

        mock_service.stop.assert_called_once()
