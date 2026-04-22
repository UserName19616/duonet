# src/network/mdns.py
"""
Автообнаружение Rendezvous сервера в локальной сети через mDNS (Bonjour/Avahi).
Позволяет клиентам автоматически находить Rendezvous сервер без ручной настройки IP.
"""

import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import zeroconf

logger = logging.getLogger(__name__)

# Константы
SERVICE_TYPE = "_duonet-rendezvous._tcp.local."
DEFAULT_PORT = 9878
DEFAULT_TIMEOUT = 5.0


@dataclass
class RendezvousService:
    """Информация об обнаруженном сервере."""

    name: str
    address: str
    port: int = DEFAULT_PORT
    server_type: str = "rendezvous"
    properties: Dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь."""
        return {
            "name": self.name,
            "address": self.address,
            "port": self.port,
            "type": self.server_type,
            "properties": self.properties,
            "last_seen": self.last_seen,
        }


class MDNSService:
    """
    Класс для публикации и поиска mDNS сервисов.
    """

    def __init__(self):
        self._zeroconf: Optional[zeroconf.Zeroconf] = None
        self._service_info: Optional[zeroconf.ServiceInfo] = None
        self._browser: Optional[zeroconf.ServiceBrowser] = None
        self._services: Dict[str, RendezvousService] = {}
        self._lock = asyncio.Lock()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_hostname(self) -> str:
        """Получение имени хоста для публикации."""
        return socket.gethostname().split(".")[0]

    def _get_ip_addresses(self) -> List[str]:
        """Получение IP-адресов для публикации."""
        ips = []
        hostname = socket.gethostname()
        try:
            for addr in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ips.append(addr[4][0])
        except socket.gaierror:
            pass

        if not ips:
            ips.append("127.0.0.1")
        return ips

    def publish_rendezvous(self, port: int = DEFAULT_PORT, name: Optional[str] = None) -> None:
        """
        Публикация Rendezvous сервера в локальной сети.

        Args:
            port: порт сервера (по умолчанию 9878)
            name: имя сервера (если None, генерируется из hostname)
        """
        if self._zeroconf is not None:
            logger.warning("Service already published")
            return

        self._zeroconf = zeroconf.Zeroconf(ip_version=zeroconf.IPVersion.V4Only)

        service_name = name or f"{self._get_hostname()}.{SERVICE_TYPE}"

        # Получаем IP-адреса
        addresses = self._get_ip_addresses()
        address_bytes = [socket.inet_aton(addr) for addr in addresses]

        # Создаём сервис (без параметра ttl для совместимости с zeroconf 0.148.0)
        self._service_info = zeroconf.ServiceInfo(
            SERVICE_TYPE,
            service_name,
            addresses=address_bytes,
            port=port,
            properties={
                b"version": b"1.0",
                b"hostname": self._get_hostname().encode(),
                b"protocol": b"duonet",
            },
        )

        self._zeroconf.register_service(self._service_info)
        logger.info(f"Published rendezvous service: {service_name} on port {port}")

    def _on_service_state_change(
        self,
        zeroconf_obj: zeroconf.Zeroconf,
        service_type: str,
        name: str,
        state_change: zeroconf.ServiceStateChange,
    ) -> None:
        """Обработчик изменения состояния сервиса."""
        if state_change is zeroconf.ServiceStateChange.Added:
            asyncio.create_task(self._add_service(zeroconf_obj, service_type, name))
        elif state_change is zeroconf.ServiceStateChange.Removed:
            asyncio.create_task(self._remove_service(name))

    async def _add_service(self, zeroconf_obj: zeroconf.Zeroconf, service_type: str, name: str) -> None:
        """Добавление обнаруженного сервиса."""
        try:
            info = zeroconf_obj.get_service_info(service_type, name, timeout=2000)  # timeout в миллисекундах
            if info is None:
                return

            # Извлекаем адрес
            address = None
            if info.addresses:
                address = socket.inet_ntoa(info.addresses[0])
            else:
                return

            port = info.port

            # Извлекаем свойства
            properties = {}
            if info.properties:
                for key, value in info.properties.items():
                    if isinstance(key, bytes):
                        key = key.decode()
                    if isinstance(value, bytes):
                        value = value.decode()
                    properties[key] = value

            service = RendezvousService(
                name=name,
                address=address,
                port=port,
                properties=properties,
            )

            async with self._lock:
                self._services[name] = service

            logger.debug(f"Discovered rendezvous service: {name} at {address}:{port}")

        except Exception as e:
            logger.error(f"Error adding service {name}: {e}")

    async def _remove_service(self, name: str) -> None:
        """Удаление обнаруженного сервиса."""
        async with self._lock:
            if name in self._services:
                del self._services[name]
                logger.debug(f"Removed rendezvous service: {name}")

    def discover_rendezvous(self, timeout: float = DEFAULT_TIMEOUT) -> List[RendezvousService]:
        """
        Поиск Rendezvous серверов в локальной сети.

        Args:
            timeout: время ожидания ответа (секунд)

        Returns:
            список обнаруженных серверов
        """
        if self._zeroconf is not None:
            logger.warning("Discovery already running")
            return []

        self._zeroconf = zeroconf.Zeroconf(ip_version=zeroconf.IPVersion.V4Only)

        # Запускаем поиск
        self._browser = zeroconf.ServiceBrowser(
            self._zeroconf,
            SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )

        # Ждём обнаружения
        time.sleep(timeout)

        # Останавливаем поиск
        if self._browser:
            self._browser.cancel()
            self._browser = None

        # Получаем список сервисов перед закрытием
        services = list(self._services.values())

        if self._zeroconf:
            self._zeroconf.close()
            self._zeroconf = None

        return services

    def get_first_rendezvous(self, timeout: float = DEFAULT_TIMEOUT) -> Optional[RendezvousService]:
        """
        Получение первого обнаруженного Rendezvous сервера.

        Args:
            timeout: время ожидания ответа (секунд)

        Returns:
            первый сервер или None
        """
        services = self.discover_rendezvous(timeout)
        return services[0] if services else None

    def stop(self) -> None:
        """Остановка публикации или поиска."""
        if self._service_info and self._zeroconf:
            self._zeroconf.unregister_service(self._service_info)
            self._service_info = None

        if self._browser:
            self._browser.cancel()
            self._browser = None

        if self._zeroconf:
            self._zeroconf.close()
            self._zeroconf = None

        self._services.clear()


class MDNSServiceManager:
    """
    Менеджер для управления публикацией и поиском mDNS сервисов.
    """

    def __init__(self):
        self._service = MDNSService()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._on_discovery_callback: Optional[callable] = None

    def start(self) -> None:
        """Запуск фонового мониторинга mDNS."""
        if self._running:
            return

        self._running = True
        logger.info("MDNS service manager started")

    def stop(self) -> None:
        """Остановка фонового мониторинга."""
        self._running = False
        self._service.stop()
        if self._monitor_task:
            self._monitor_task.cancel()
        logger.info("MDNS service manager stopped")

    def publish(self, port: int = DEFAULT_PORT, name: Optional[str] = None) -> None:
        """
        Публикация сервиса.

        Args:
            port: порт сервера
            name: имя сервера
        """
        self._service.publish_rendezvous(port, name)

    def discover(self, timeout: float = DEFAULT_TIMEOUT) -> List[RendezvousService]:
        """
        Поиск сервисов.

        Args:
            timeout: время ожидания

        Returns:
            список обнаруженных сервисов
        """
        return self._service.discover_rendezvous(timeout)

    def get_first(self, timeout: float = DEFAULT_TIMEOUT) -> Optional[RendezvousService]:
        """
        Получение первого сервиса.

        Args:
            timeout: время ожидания

        Returns:
            первый сервис или None
        """
        return self._service.get_first_rendezvous(timeout)

    def set_on_discovery_callback(self, callback: callable) -> None:
        """
        Установка callback при обнаружении сервиса.

        Args:
            callback: функция, вызываемая при обнаружении сервиса
        """
        self._on_discovery_callback = callback
