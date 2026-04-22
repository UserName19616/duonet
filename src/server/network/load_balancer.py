# src/network/load_balancer.py
"""
Управление распределением нагрузки для мессенджера.

Обеспечивает мониторинг состояния сервера и автоматическое
переключение клиентов при перегрузке.
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import psutil

from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.config import (
    LOAD_WARNING_THRESHOLD,
    LOAD_CRITICAL_THRESHOLD,
    LOAD_CHECK_INTERVAL,
    METRICS_HISTORY_SIZE,
    CLIENT_RECONNECT_DELAY_MS,
)

logger = logging.getLogger(__name__)

# Константы (импортированы из config)
LOAD_WARNING_THRESHOLD = LOAD_WARNING_THRESHOLD
LOAD_CRITICAL_THRESHOLD = LOAD_CRITICAL_THRESHOLD
LOAD_CHECK_INTERVAL = LOAD_CHECK_INTERVAL
METRICS_HISTORY_SIZE = METRICS_HISTORY_SIZE
CLIENT_RECONNECT_DELAY_MS = CLIENT_RECONNECT_DELAY_MS


@dataclass
class LoadMetrics:
    """Структура метрик нагрузки."""

    cpu_percent: float
    memory_percent: float
    active_messaging_sessions: int
    messages_per_second: float
    bytes_per_second: float
    timestamp: float


class LoadBalancer:
    """
    Балансировщик нагрузки.

    Мониторит состояние сервера и рекомендует клиентам
    переключение при перегрузке.
    """

    def __init__(
        self,
        message_router: Any,
        rendezvous_client: RendezvousClient,
        server_public_id: str,
    ):
        """
        Инициализация балансировщика.

        Args:
            message_router: Маршрутизатор сообщений (доступ к клиентам).
            rendezvous_client: Клиент сервера знакомств.
            server_public_id: Public ID текущего сервера.
        """
        self._message_router = message_router
        self._rendezvous_client = rendezvous_client
        self._server_public_id = server_public_id
        self._region = self._extract_region(server_public_id)

        # Состояние
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._metrics_history: List[LoadMetrics] = []
        self._last_msg_count = 0
        self._last_bytes = 0
        self._last_metrics_time = time.time()

        # Для тестирования: возможность подмены get_load_percent
        self._test_load_values = None
        self._test_load_index = 0

    def _extract_region(self, public_id: str) -> str:
        """Извлечение региона из Public ID."""
        parts = public_id.split(".")
        if len(parts) >= 2:
            return parts[1]  # @XXXX-XXXX-XXXX.ru -> ru
        return "ru"

    def _collect_metrics(self) -> LoadMetrics:
        """Сбор текущих метрик нагрузки."""
        now = time.time()
        delta = now - self._last_metrics_time

        # Системные метрики
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory().percent

        # Активные соединения
        active = self._message_router.get_active_connection_count() if hasattr(self._message_router, "get_active_connection_count") else 0

        # Сообщения в секунду и трафик
        # В прототипе используем заглушки
        msg_per_sec = 0.0
        bytes_per_sec = 0.0

        if delta > 0:
            # Здесь должна быть реальная статистика
            pass

        self._last_metrics_time = now

        return LoadMetrics(
            cpu_percent=cpu,
            memory_percent=memory,
            active_messaging_sessions=active,
            messages_per_second=msg_per_sec,
            bytes_per_second=bytes_per_sec,
            timestamp=now,
        )

    def get_current_metrics(self) -> LoadMetrics:
        """Получение текущих метрик нагрузки."""
        return self._collect_metrics()

    def get_load_percent(self) -> float:
        """
        Получение агрегированной нагрузки (0-1).

        Формула: max(cpu/100, memory/100, messages_per_second/500)
        """
        # Для тестирования: если установлены тестовые значения, возвращаем их
        if self._test_load_values is not None:
            if self._test_load_index < len(self._test_load_values):
                value = self._test_load_values[self._test_load_index]
                self._test_load_index += 1
                return value
            else:
                # Если список закончился, возвращаем последнее значение
                return self._test_load_values[-1] if self._test_load_values else 0.0

        metrics = self._collect_metrics()
        # Добавляем в историю для сглаживания
        self._metrics_history.append(metrics)
        if len(self._metrics_history) > METRICS_HISTORY_SIZE:
            self._metrics_history.pop(0)

        # Сглаживаем метрики
        avg_cpu = sum(m.cpu_percent for m in self._metrics_history) / len(self._metrics_history) / 100
        avg_mem = sum(m.memory_percent for m in self._metrics_history) / len(self._metrics_history) / 100
        avg_msg = sum(m.messages_per_second for m in self._metrics_history) / len(self._metrics_history) / 500

        return max(avg_cpu, avg_mem, avg_msg)

    def is_warning(self) -> bool:
        """Проверка, достигнут ли порог предупреждения (≥80%)."""
        return self.get_load_percent() >= LOAD_WARNING_THRESHOLD

    def is_critical(self) -> bool:
        """Проверка, достигнут ли критический порог (≥90%)."""
        return self.get_load_percent() >= LOAD_CRITICAL_THRESHOLD

    def get_recommended_servers(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получение списка рекомендуемых серверов для переключения.

        Returns:
            Список серверов в регионе с нагрузкой < 70%.
        """
        servers = self._rendezvous_client.get_servers_by_region_with_load(self._region)

        # Фильтруем текущий сервер и серверы с нагрузкой >= 70%
        filtered = [
            s for s in servers
            if s["public_id"] != self._server_public_id
            and s.get("load", 100) < 70
        ]

        # Сортируем по нагрузке
        filtered.sort(key=lambda s: s.get("load", 100))

        return filtered[:limit]

    def get_priority_clients(self) -> List[Dict[str, Any]]:
        """
        Получение списка клиентов, отсортированных по приоритету для переключения.

        Приоритет (от низшего к высшему):
          1. Клиенты, не являющиеся прокси-клиентами (чужие)
          2. Прокси-клиенты группы basic
          3. Прокси-клиенты группы standard
          4. Прокси-клиенты группы privileged (свои)
        """
        clients = self._message_router.get_connected_clients() if hasattr(self._message_router, "get_connected_clients") else []

        # Функция приоритета (чем выше приоритет, тем раньше переключаем)
        def priority(client):
            is_proxy = client.get("is_proxy", False)
            proxy_group = client.get("proxy_group", "none")

            if not is_proxy:
                return 0  # чужие клиенты — самые низкоприоритетные
            if proxy_group == "basic":
                return 1
            if proxy_group == "standard":
                return 2
            if proxy_group == "privileged":
                return 3
            return 0

        clients.sort(key=priority)
        return clients

    def suggest_reconnect(self, client_id: str) -> bool:
        """
        Отправить клиенту рекомендацию переключиться.

        Args:
            client_id: Public ID клиента.

        Returns:
            True если отправлено.
        """
        servers = self.get_recommended_servers(limit=3)
        if not servers:
            logger.warning(f"No recommended servers for client {client_id}")
            return False

        message = {
            "type": "switch_server",
            "data": {
                "reason": "overload",
                "target_servers": servers,
                "delay_ms": CLIENT_RECONNECT_DELAY_MS,
            },
        }

        return self._message_router.send_to_client(client_id, message)

    def balance(self) -> int:
        """
        Запуск балансировки (вызывается при критической нагрузке).

        Returns:
            Количество клиентов, которым отправлена рекомендация.
        """
        # Проверяем нагрузку перед началом балансировки
        if not self.is_critical():
            return 0

        clients = self.get_priority_clients()
        recommended_count = 0

        for client in clients:
            # Проверяем нагрузку перед обработкой каждого клиента
            if not self.is_critical():
                break

            client_id = client.get("public_id") or client.get("client_id")
            if not client_id:
                continue

            if self.suggest_reconnect(client_id):
                recommended_count += 1
                logger.info(f"Recommended reconnect for client {client_id}")

                # Небольшая пауза, чтобы нагрузка успела измениться
                time.sleep(0.1)

        return recommended_count

    def _monitor_loop(self) -> None:
        """Фоновый цикл мониторинга нагрузки."""
        while self._running:
            try:
                if self.is_critical():
                    logger.warning(f"Critical load detected ({self.get_load_percent():.2f}), balancing...")
                    count = self.balance()
                    if count > 0:
                        logger.info(f"Sent reconnect recommendations to {count} clients")
                elif self.is_warning():
                    logger.info(f"Warning load detected ({self.get_load_percent():.2f})")

                time.sleep(LOAD_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(LOAD_CHECK_INTERVAL)

    def start(self) -> None:
        """Запуск фонового мониторинга нагрузки."""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Load balancer started")

    def stop(self) -> None:
        """Остановка фонового мониторинга."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Load balancer stopped")

    def handle_client_reconnect(self, client_id: str, target_server: str) -> bool:
        """
        Обработка подтверждения переключения от клиента.

        Args:
            client_id: Public ID клиента.
            target_server: URL целевого сервера.

        Returns:
            True если соединение закрыто.
        """
        logger.info(f"Client {client_id} reconnecting to {target_server}")
        return self._message_router.close_connection(client_id)
