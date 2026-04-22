# src/network/gossip/handlers.py
"""
Обработчики gossip-сообщений.
"""

import logging
import time
from typing import Dict, Any, Optional

from ...storage.server_db import ServerDatabase
from ..trust import TrustManager, TRUST_LEVEL_QUARANTINE
from .message import GossipMessage

logger = logging.getLogger(__name__)


class GossipHandlers:
    """
    Обработчики входящих gossip-сообщений.
    """

    def __init__(
        self,
        db: ServerDatabase,
        trust_manager: TrustManager,
        my_server_id: str,
    ):
        """
        Инициализация обработчиков.

        Args:
            db: Экземпляр ServerDatabase
            trust_manager: Экземпляр TrustManager
            my_server_id: Public ID текущего сервера
        """
        self._db = db
        self._trust_manager = trust_manager
        self._my_server_id = my_server_id

    async def handle_sync_request(self, message: GossipMessage) -> Dict[str, Any]:
        """
        Обработка запроса синхронизации.

        Args:
            message: Полученное сообщение

        Returns:
            Ответное сообщение (payload)
        """
        payload = message.payload
        remote_clients = payload.get("clients", [])

        # Получаем локальных клиентов
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT client_id, region, last_seen FROM clients")
            local_clients = [
                {"client_id": row["client_id"], "region": row["region"], "last_seen": row["last_seen"]}
                for row in cursor.fetchall()
            ]

        # Находим новых клиентов (которых нет у отправителя)
        remote_ids = {c["client_id"] for c in remote_clients}
        new_clients = [c for c in local_clients if c["client_id"] not in remote_ids]

        # Формируем ответ
        return {
            "type": "sync_response",
            "clients": new_clients,
            "timestamp": int(time.time()),
        }

    async def handle_new_client(self, message: GossipMessage) -> Dict[str, Any]:
        """
        Обработка нового клиента.

        Args:
            message: Полученное сообщение

        Returns:
            Ответное сообщение (payload)
        """
        payload = message.payload
        client_data = payload.get("data", {})

        client_id = client_data.get("client_id")
        region = client_data.get("region", "ru")

        if client_id:
            with self._db._transaction() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO clients (client_id, server_id_hash, region, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (client_id, message.sender_id, region, int(time.time()), int(time.time())))

            logger.info(f"Added client {client_id} from gossip from {message.sender_id}")

        return {"success": True}

    async def handle_update_client(self, message: GossipMessage) -> Dict[str, Any]:
        """
        Обработка обновления клиента.

        Args:
            message: Полученное сообщение

        Returns:
            Ответное сообщение (payload)
        """
        payload = message.payload
        client_data = payload.get("data", {})

        client_id = client_data.get("client_id")
        if client_id:
            with self._db._transaction() as conn:
                conn.execute("""
                    UPDATE clients SET last_seen = ? WHERE client_id = ?
                """, (int(time.time()), client_id))

        return {"success": True}

    async def handle_unknown(self, message: GossipMessage) -> Dict[str, Any]:
        """
        Обработка неизвестного типа сообщения.

        Args:
            message: Полученное сообщение

        Returns:
            Ответное сообщение (payload)
        """
        logger.warning(f"Unknown gossip message type: {message.payload.get('type')}")
        return {"error": f"unknown_type_{message.payload.get('type')}"}

    def get_handler(self, msg_type: str):
        """
        Получение обработчика для типа сообщения.

        Args:
            msg_type: Тип сообщения

        Returns:
            Функция-обработчик или None
        """
        handlers = {
            "sync_request": self.handle_sync_request,
            "new_client": self.handle_new_client,
            "update_client": self.handle_update_client,
        }
        return handlers.get(msg_type, self.handle_unknown)
