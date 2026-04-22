# src/proxy/traffic_manager.py
"""
Управление трафиком прокси-клиентов.
Учёт, лимиты, статистика, сброс счётчиков.
"""

import logging
import time
from typing import Any, Dict, Optional

from ..storage.sqlite import SQLiteStorage
from ..config import PROXY_DAILY_LIMIT_BASIC_MB, PROXY_DAILY_LIMIT_STANDARD_MB

logger = logging.getLogger(__name__)

# Константы (импортированы из config)
DAILY_LIMIT_BASIC_DEFAULT_MB = PROXY_DAILY_LIMIT_BASIC_MB
DAILY_LIMIT_STANDARD_DEFAULT_MB = PROXY_DAILY_LIMIT_STANDARD_MB


class TrafficManager:
    """
    Менеджер учёта трафика прокси-клиентов.
    """

    def __init__(self, storage: SQLiteStorage):
        """
        Инициализация менеджера трафика.

        Args:
            storage: Экземпляр SQLiteStorage.
        """
        self._storage = storage

    def add_traffic(self, client_id: str, bytes_added: int) -> None:
        """
        Добавление использованного трафика.

        Args:
            client_id: ID клиента.
            bytes_added: Количество добавленных байт.
        """
        # Получаем текущие значения
        cursor = self._storage.execute_sql(
            "SELECT traffic_today, traffic_total FROM proxy_clients WHERE client_id = ?",
            (client_id,),
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(f"Client {client_id} not found for traffic update")
            return

        new_traffic_today = row[0] + bytes_added
        new_traffic_total = row[1] + bytes_added

        self._storage.execute_sql(
            """
            UPDATE proxy_clients
            SET traffic_today = ?, traffic_total = ?, updated_at = ?
            WHERE client_id = ?
            """,
            (new_traffic_today, new_traffic_total, time.time(), client_id),
        )

    def check_traffic_limit(self, client_id: str, bytes_to_add: int) -> bool:
        """
        Проверка, не превышен ли лимит трафика.

        Args:
            client_id: ID клиента.
            bytes_to_add: Количество байт, которое планируется добавить.

        Returns:
            True если лимит не превышен.
        """
        cursor = self._storage.execute_sql(
            "SELECT daily_limit, traffic_today FROM proxy_clients WHERE client_id = ?",
            (client_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False

        daily_limit = row[0]
        traffic_today = row[1]

        if daily_limit is None:
            return True

        return traffic_today + bytes_to_add <= daily_limit

    def get_traffic_stats(self, client_id: str) -> Dict[str, Any]:
        """
        Получение статистики трафика клиента.

        Args:
            client_id: ID клиента.

        Returns:
            Словарь со статистикой.
        """
        cursor = self._storage.execute_sql(
            "SELECT traffic_today, traffic_total, daily_limit FROM proxy_clients WHERE client_id = ?",
            (client_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {}

        traffic_today = row[0]
        traffic_total = row[1]
        daily_limit = row[2]

        used_mb = traffic_today / (1024 * 1024)
        limit_mb = daily_limit / (1024 * 1024) if daily_limit is not None else None

        result = {
            "used_today_mb": round(used_mb, 2),
            "total_mb": round(traffic_total / (1024 * 1024), 2),
        }

        if limit_mb is not None:
            result["daily_limit_mb"] = round(limit_mb, 2)
            result["remaining_mb"] = round(limit_mb - used_mb, 2)
        else:
            result["daily_limit_mb"] = None
            result["remaining_mb"] = None

        return result

    def get_aggregated_stats(self) -> Dict[str, Any]:
        """
        Получение агрегированной статистики по всем клиентам.

        Returns:
            Словарь с агрегированной статистикой.
        """
        cursor = self._storage.execute_sql("""
            SELECT
                COALESCE(SUM(traffic_today), 0) as total_today,
                COALESCE(SUM(traffic_total), 0) as total_all,
                COUNT(*) as total_clients,
                COALESCE(SUM(CASE WHEN connected = 1 THEN 1 ELSE 0 END), 0) as active_clients,
                COALESCE(SUM(CASE WHEN group_name = 'basic' THEN 1 ELSE 0 END), 0) as basic_count,
                COALESCE(SUM(CASE WHEN group_name = 'standard' THEN 1 ELSE 0 END), 0) as standard_count,
                COALESCE(SUM(CASE WHEN group_name = 'privileged' THEN 1 ELSE 0 END), 0) as privileged_count
            FROM proxy_clients
        """)
        row = cursor.fetchone()

        active_clients = row[3] if row[3] is not None else 0
        total_clients = row[2] if row[2] is not None else 0
        total_today = row[0] if row[0] is not None else 0
        total_all = row[1] if row[1] is not None else 0
        basic_count = row[4] if row[4] is not None else 0
        standard_count = row[5] if row[5] is not None else 0
        privileged_count = row[6] if row[6] is not None else 0

        return {
            "total_today_mb": round(total_today / (1024 * 1024), 2),
            "total_all_mb": round(total_all / (1024 * 1024), 2),
            "total_clients": total_clients,
            "active_clients": active_clients,
            "by_group": {
                "basic": basic_count,
                "standard": standard_count,
                "privileged": privileged_count,
            },
        }

    def reset_daily_traffic(self) -> int:
        """
        Сброс ежедневных счетчиков трафика для всех клиентов.

        Returns:
            Количество обновлённых клиентов.
        """
        self._storage.execute_sql(
            "UPDATE proxy_clients SET traffic_today = 0, updated_at = ?",
            (time.time(),),
        )
        # Получаем количество обновленных строк через отдельный запрос
        cursor = self._storage.execute_sql("SELECT changes()")
        return cursor.fetchone()[0]
