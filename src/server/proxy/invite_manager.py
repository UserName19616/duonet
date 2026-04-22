# src/proxy/invite_manager.py
"""
Управление приглашениями для прокси-клиентов.
Генерация токенов, QR-кодов, хранение приглашений.
"""

import base64
import logging
import secrets
import time
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Any, Dict, Optional

import qrcode

from ..storage.sqlite import SQLiteStorage
from .proxy_settings import ProxySettingsManager
from ..config import PROXY_DAILY_LIMIT_BASIC_MB, PROXY_DAILY_LIMIT_STANDARD_MB

logger = logging.getLogger(__name__)

# Константы (импортированы из config)
DAILY_LIMIT_BASIC_DEFAULT_MB = PROXY_DAILY_LIMIT_BASIC_MB
DAILY_LIMIT_STANDARD_DEFAULT_MB = PROXY_DAILY_LIMIT_STANDARD_MB

# Группы клиентов (константы)
GROUPS = {
    "basic": {
        "daily_limit_mb": DAILY_LIMIT_BASIC_DEFAULT_MB,
        "ttl": 86400,  # 24 часа
        "description": "New clients, 24h access",
    },
    "standard": {
        "daily_limit_mb": DAILY_LIMIT_STANDARD_DEFAULT_MB,
        "ttl": None,  # до конца месяца
        "description": "Regular users, monthly access",
    },
    "privileged": {
        "daily_limit_mb": None,  # без лимита
        "ttl": None,  # бессрочно
        "description": "Own devices, unlimited",
    },
}


class InviteManager:
    """
    Менеджер приглашений прокси-клиентов.
    """

    def __init__(self, storage: SQLiteStorage, settings_manager: ProxySettingsManager):
        """
        Инициализация менеджера приглашений.

        Args:
            storage: Экземпляр SQLiteStorage.
            settings_manager: Менеджер настроек.
        """
        self._storage = storage
        self._settings = settings_manager

    def generate_invite(
        self,
        client_name: str,
        expires_in: int = 86400,
        group: str = "basic",
        daily_limit_mb: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Генерация приглашения для нового клиента.

        Args:
            client_name: Локальное имя клиента.
            expires_in: Срок действия в секундах (1 час - 30 дней).
            group: Группа клиента.
            daily_limit_mb: Переопределение лимита (опционально).

        Returns:
            Словарь с результатом.
        """
        # Валидация
        if not client_name or len(client_name) > 64:
            return {
                "success": False,
                "error": "invalid_name",
                "message": "Name must be 1-64 characters",
            }

        if expires_in < 3600 or expires_in > 2592000:
            return {
                "success": False,
                "error": "invalid_expiry",
                "message": "Expiry must be between 1 hour and 30 days",
            }

        if group not in GROUPS:
            return {
                "success": False,
                "error": "invalid_group",
                "message": f"Group must be one of {list(GROUPS.keys())}",
            }

        # Генерация токена и QR-кода
        token = secrets.token_urlsafe(32)
        invite_url = f"duonet://invite?token={token}"

        qr_code = self._generate_qr_code(invite_url)

        # Вычисляем expires_at
        if group == "privileged":
            expires_at = None
        elif group == "standard":
            expires_at = None  # При активации будет пересчитан
        else:
            expires_at = time.time() + expires_in

        # Определяем daily_limit
        if daily_limit_mb is None:
            daily_limit_mb = GROUPS[group].get("daily_limit_mb")

        # Сохраняем приглашение
        now = time.time()
        self._storage.execute_sql(
            """
            INSERT INTO proxy_invites
            (token, client_name, group_name, daily_limit_mb, expires_at, used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                client_name,
                group,
                daily_limit_mb,
                expires_at if expires_at is not None else 0,
                0,
                now,
            ),
        )

        return {
            "success": True,
            "token": token,
            "invite_url": invite_url,
            "qr_code": qr_code,
            "expires_at": expires_at,
        }

    def _generate_qr_code(self, invite_url: str) -> str:
        """
        Генерация QR-кода для приглашения.

        Args:
            invite_url: URL приглашения.

        Returns:
            QR-код в формате base64 PNG.
        """
        try:
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(invite_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            logger.warning(f"QR generation failed: {e}, using placeholder")
            # Fallback: создаем пустой QR-код (1x1 пиксель PNG)
            return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    def get_invite(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Получение информации о приглашении по токену.

        Args:
            token: Токен приглашения.

        Returns:
            Информация о приглашении или None.
        """
        cursor = self._storage.execute_sql(
            """
            SELECT client_name, group_name, daily_limit_mb, expires_at, used
            FROM proxy_invites WHERE token = ?
            """,
            (token,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "client_name": row[0],
            "group": row[1],
            "daily_limit_mb": row[2],
            "expires_at": row[3] if row[3] != 0 else None,
            "used": bool(row[4]),
        }

    def mark_used(self, token: str) -> None:
        """Отметка приглашения как использованного."""
        self._storage.execute_sql(
            "UPDATE proxy_invites SET used = 1 WHERE token = ?", (token,)
        )

    def cleanup_expired(self) -> int:
        """Очистка истекших неиспользованных токенов."""
        now = time.time()
        cursor = self._storage.execute_sql(
            "DELETE FROM proxy_invites WHERE expires_at IS NOT NULL AND expires_at < ? AND used = 0",
            (now,),
        )
        return cursor.rowcount

    def _calculate_standard_expiry(self, activation_timestamp: int) -> int:
        """
        Вычисление expires_at для группы "standard".

        Args:
            activation_timestamp: Timestamp активации клиента.

        Returns:
            Timestamp истечения (23:59:59 последнего дня месяца).
        """
        dt = datetime.fromtimestamp(activation_timestamp, tz=timezone.utc)
        # Переходим на первый день следующего месяца
        if dt.month == 12:
            next_month = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
        # Последний день текущего месяца
        last_day = next_month - timedelta(days=1)
        # Устанавливаем время 23:59:59
        last_day = last_day.replace(hour=23, minute=59, second=59)
        return int(last_day.timestamp())
