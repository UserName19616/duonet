# src/network/trust/blacklist.py
"""
Управление чёрным списком (блокировки).
"""

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BlacklistManager:
    """
    Менеджер чёрного списка.
    Отвечает за блокировку и разблокировку серверов.
    """

    def __init__(self, db):
        """
        Args:
            db: Экземпляр ServerDatabase
        """
        self._db = db

    def is_blocked(self, server_id: str) -> bool:
        """
        Проверка, заблокирован ли сервер.

        Args:
            server_id: Public ID сервера

        Returns:
            True если заблокирован
        """
        with self._db._transaction() as conn:
            cursor = conn.execute(
                "SELECT blocked FROM trust_levels WHERE server_id = ?",
                (server_id,)
            )
            row = cursor.fetchone()
            if row:
                return bool(row["blocked"])

            # Проверяем чёрный список
            cursor = conn.execute(
                "SELECT 1 FROM blacklist WHERE server_id = ?",
                (server_id,)
            )
            return cursor.fetchone() is not None

    def block(self, server_id: str, reason: str, blocked_by: str = "auto") -> bool:
        """
        Блокировка сервера.

        Args:
            server_id: Public ID сервера
            reason: Причина блокировки
            blocked_by: Кто заблокировал

        Returns:
            True если успешно
        """
        now = int(time.time())

        with self._db._transaction() as conn:
            # Обновляем trust_levels
            conn.execute("""
                UPDATE trust_levels
                SET blocked = 1, blocked_reason = ?, last_seen = ?
                WHERE server_id = ?
            """, (reason, now, server_id))

            # Добавляем в чёрный список
            conn.execute("""
                INSERT OR REPLACE INTO blacklist (server_id, reason, blocked_at, blocked_by)
                VALUES (?, ?, ?, ?)
            """, (server_id, reason, now, blocked_by))

        logger.warning(f"Server {server_id} blocked: {reason}")
        return True

    def unblock(self, server_id: str) -> bool:
        """
        Разблокировка сервера.

        Args:
            server_id: Public ID сервера

        Returns:
            True если успешно
        """
        with self._db._transaction() as conn:
            conn.execute("""
                UPDATE trust_levels
                SET blocked = 0, blocked_reason = NULL
                WHERE server_id = ?
            """, (server_id,))

            conn.execute(
                "DELETE FROM blacklist WHERE server_id = ?",
                (server_id,)
            )

        logger.info(f"Server {server_id} unblocked")
        return True

    def get_block_reason(self, server_id: str) -> Optional[str]:
        """
        Получение причины блокировки.

        Args:
            server_id: Public ID сервера

        Returns:
            Причина блокировки или None
        """
        with self._db._transaction() as conn:
            cursor = conn.execute(
                "SELECT reason FROM blacklist WHERE server_id = ?",
                (server_id,)
            )
            row = cursor.fetchone()
            return row["reason"] if row else None
