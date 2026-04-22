# src/proxy/proxy_settings.py
"""
Настройки прокси-сервиса.
Управление лимитами, группами клиентов и параметрами по умолчанию.
"""

import logging
from typing import Any, Dict

from ..storage.sqlite import SQLiteStorage
from ..config import (
    PROXY_MAX_CLIENTS,
    PROXY_DAILY_LIMIT_BASIC_MB,
    PROXY_DAILY_LIMIT_STANDARD_MB,
    PROXY_INVITE_TTL_DEFAULT,
)

logger = logging.getLogger(__name__)

# Константы (импортированы из config)
MAX_CLIENTS_DEFAULT = PROXY_MAX_CLIENTS
DAILY_LIMIT_BASIC_DEFAULT_MB = PROXY_DAILY_LIMIT_BASIC_MB
DAILY_LIMIT_STANDARD_DEFAULT_MB = PROXY_DAILY_LIMIT_STANDARD_MB
INVITE_TTL_DEFAULT = PROXY_INVITE_TTL_DEFAULT


class ProxySettingsManager:
    """
    Менеджер настроек прокси-сервиса.
    """

    def __init__(self, storage: SQLiteStorage):
        """
        Инициализация менеджера настроек.

        Args:
            storage: Экземпляр SQLiteStorage.
        """
        self._storage = storage

    def _init_settings_table(self) -> None:
        """Инициализация таблицы настроек."""
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS proxy_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Инициализация настроек по умолчанию
        self._init_default_settings()

    def _init_default_settings(self) -> None:
        """Инициализация настроек по умолчанию."""
        default_settings = {
            "max_clients": str(MAX_CLIENTS_DEFAULT),
            "default_daily_limit_mb": str(DAILY_LIMIT_BASIC_DEFAULT_MB),
            "default_group": "basic",
            "proxy_enabled": "true",
        }

        for key, value in default_settings.items():
            cursor = self._storage.execute_sql(
                "SELECT 1 FROM proxy_settings WHERE key = ?", (key,)
            )
            if not cursor.fetchone():
                self._storage.execute_sql(
                    "INSERT INTO proxy_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

    def _get_setting(self, key: str, default: str = "") -> str:
        """Получение настройки."""
        cursor = self._storage.execute_sql(
            "SELECT value FROM proxy_settings WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else default

    def _set_setting(self, key: str, value: str) -> None:
        """Установка настройки."""
        self._storage.execute_sql(
            "INSERT OR REPLACE INTO proxy_settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    def get_settings(self) -> Dict[str, Any]:
        """
        Получение текущих настроек.

        Returns:
            Словарь с настройками.
        """
        return {
            "max_clients": int(self._get_setting("max_clients", str(MAX_CLIENTS_DEFAULT))),
            "default_daily_limit_mb": int(self._get_setting("default_daily_limit_mb", str(DAILY_LIMIT_BASIC_DEFAULT_MB))),
            "default_group": self._get_setting("default_group", "basic"),
            "proxy_enabled": self._get_setting("proxy_enabled", "true").lower() == "true",
        }

    def get_max_clients(self) -> int:
        """Получение максимального количества клиентов."""
        return int(self._get_setting("max_clients", str(MAX_CLIENTS_DEFAULT)))

    def get_default_daily_limit_mb(self) -> int:
        """Получение лимита трафика по умолчанию (в МБ)."""
        return int(self._get_setting("default_daily_limit_mb", str(DAILY_LIMIT_BASIC_DEFAULT_MB)))

    def get_default_group(self) -> str:
        """Получение группы по умолчанию."""
        return self._get_setting("default_group", "basic")

    def is_proxy_enabled(self) -> bool:
        """Проверка, включён ли прокси-сервис."""
        return self._get_setting("proxy_enabled", "true").lower() == "true"

    def update_settings(self, **kwargs) -> bool:
        """
        Обновление настроек.

        Args:
            **kwargs: Параметры для обновления:
                - max_clients: int
                - default_daily_limit_mb: int
                - default_group: str ("basic", "standard", "privileged")
                - proxy_enabled: bool

        Returns:
            True если обновление успешно.
        """
        if "max_clients" in kwargs:
            max_clients = kwargs["max_clients"]
            if max_clients < 0:
                return False
            self._set_setting("max_clients", str(max_clients))

        if "default_daily_limit_mb" in kwargs:
            limit = kwargs["default_daily_limit_mb"]
            if limit < 0:
                return False
            self._set_setting("default_daily_limit_mb", str(limit))

        if "default_group" in kwargs:
            group = kwargs["default_group"]
            if group not in ("basic", "standard", "privileged"):
                return False
            self._set_setting("default_group", group)

        if "proxy_enabled" in kwargs:
            enabled = "true" if kwargs["proxy_enabled"] else "false"
            self._set_setting("proxy_enabled", enabled)

        return True
