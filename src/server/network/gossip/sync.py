# src/network/gossip/sync.py
"""
Синхронизация данных между серверами через gossip протокол.
"""

import asyncio
import logging
from typing import Optional

from ...storage.server_db import ServerDatabase
from ..trust import TrustManager, TRUST_LEVEL_QUARANTINE
from .message import GossipMessage

logger = logging.getLogger(__name__)

# Константы
GOSSIP_INTERVAL = 60  # 60 секунд между синхронизациями
GOSSIP_MAX_PEERS = 10  # максимальное количество пиров для синхронизации


class GossipSync:
    """
    Синхронизация данных между серверами.
    """

    def __init__(
        self,
        db: ServerDatabase,
        trust_manager: TrustManager,
        my_server_id: str,
        http_client=None,
    ):
        """
        Инициализация синхронизатора.

        Args:
            db: Экземпляр ServerDatabase
            trust_manager: Экземпляр TrustManager
            my_server_id: Public ID текущего сервера
            http_client: HTTP клиент для запросов
        """
        self._db = db
        self._trust_manager = trust_manager
        self._my_server_id = my_server_id
        self._http_client = http_client

    async def sync_with_server(self, server_id: str, ws_url: str) -> bool:
        """
        Синхронизация с удалённым сервером.

        Args:
            server_id: ID сервера
            ws_url: WebSocket URL сервера

        Returns:
            True если синхронизация успешна
        """
        # Проверяем уровень доверия
        level = self._trust_manager.get_trust_level(server_id)
        if level < TRUST_LEVEL_QUARANTINE:
            logger.debug(f"Server {server_id} has insufficient trust level {level}")
            return False

        # Проверяем лимиты для карантинных серверов
        if level == TRUST_LEVEL_QUARANTINE:
            if not self._trust_manager.check_and_increment(server_id, "gossip_out"):
                logger.warning(f"Gossip rate limit exceeded for {server_id}")
                return False

        # Формируем запрос
        # Получаем список клиентов для синхронизации
        with self._db._transaction() as conn:
            cursor = conn.execute(
                "SELECT client_id, region, last_seen FROM clients LIMIT 100"
            )
            clients = [
                {"client_id": row["client_id"], "region": row["region"], "last_seen": row["last_seen"]}
                for row in cursor.fetchall()
            ]

        # В реальной реализации здесь будет HTTP запрос к /api/gossip/sync
        # Пока возвращаем True как заглушку
        logger.info(f"Syncing with server {server_id}")
        return True

    async def periodic_sync(self, running_flag: callable) -> None:
        """
        Фоновый процесс периодической синхронизации.

        Args:
            running_flag: Функция, возвращающая True если сервер запущен
        """
        while running_flag():
            try:
                await asyncio.sleep(GOSSIP_INTERVAL)

                # Получаем список серверов для синхронизации
                with self._db._transaction() as conn:
                    cursor = conn.execute("""
                        SELECT server_id, ws_url_encrypted FROM servers
                        WHERE server_id != ? AND status = 'active'
                        LIMIT ?
                    """, (self._my_server_id, GOSSIP_MAX_PEERS))
                    servers = cursor.fetchall()

                for row in servers:
                    server_id = row["server_id"]
                    ws_url_encrypted = row["ws_url_encrypted"]
                    if ws_url_encrypted:
                        from ...storage.server_db import decrypt_data
                        ws_url = decrypt_data(ws_url_encrypted)
                        await self.sync_with_server(server_id, ws_url)

            except Exception as e:
                logger.error(f"Error in periodic sync: {e}")
