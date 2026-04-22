# src/server/network/network_map.py
"""
Хранение и синхронизация карты локальной сети.

Обеспечивает:
- Сохранение информации об обнаруженных узлах (Rendezvous серверы, клиенты)
- Передачу карты сети новым клиентам при подключении
- Автоматическое переключение на альтернативные узлы при обрыве связи
- Мониторинг доступности узлов через heartbeat
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Исправляем импорт: SQLiteStorage из common.storage, а не из server.storage
from src.common.storage.sqlite import SQLiteStorage
from src.config import (
    NODE_TTL_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
    SYNC_INTERVAL_SECONDS,
    MAX_NODES,
)

logger = logging.getLogger(__name__)

# Константы (импортированы из config)
NODE_TTL_SECONDS = NODE_TTL_SECONDS
CLEANUP_INTERVAL_SECONDS = CLEANUP_INTERVAL_SECONDS
SYNC_INTERVAL_SECONDS = SYNC_INTERVAL_SECONDS
MAX_NODES = MAX_NODES


@dataclass
class NetworkNode:
    """Модель узла сети."""

    node_id: str  # уникальный ID узла (public_id или hostname)
    node_type: str  # "rendezvous" | "client" | "server"
    address: str  # IP-адрес
    port: int  # порт
    ws_url: Optional[str] = None  # WebSocket URL (для клиентов)
    public_id: Optional[str] = None  # Public ID (для клиентов)
    last_seen: float = field(default_factory=time.time)  # timestamp последнего heartbeat
    expires_at: float = field(default_factory=lambda: time.time() + NODE_TTL_SECONDS)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Проверка, активен ли узел."""
        return time.time() < self.expires_at

    def update_heartbeat(self) -> None:
        """Обновление heartbeat узла."""
        self.last_seen = time.time()
        self.expires_at = time.time() + NODE_TTL_SECONDS

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "address": self.address,
            "port": self.port,
            "ws_url": self.ws_url,
            "public_id": self.public_id,
            "last_seen": self.last_seen,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkNode":
        """Создание из словаря."""
        return cls(
            node_id=data["node_id"],
            node_type=data["node_type"],
            address=data["address"],
            port=data["port"],
            ws_url=data.get("ws_url"),
            public_id=data.get("public_id"),
            last_seen=data.get("last_seen", time.time()),
            expires_at=data.get("expires_at", time.time() + NODE_TTL_SECONDS),
            metadata=data.get("metadata", {}),
        )


class NetworkMapManager:
    """
    Менеджер карты сети.

    Управляет хранением и синхронизацией узлов сети.
    """

    def __init__(self, storage: SQLiteStorage, ws_manager=None):
        """
        Инициализация менеджера карты сети.

        Args:
            storage: Хранилище SQLite
            ws_manager: Менеджер WebSocket для рассылки обновлений
        """
        self._storage = storage
        self._ws_manager = ws_manager
        self._nodes: Dict[str, NetworkNode] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._sync_task: Optional[asyncio.Task] = None

        # Инициализация таблицы
        self._init_db()

    def _init_db(self) -> None:
        """Инициализация таблицы network_nodes."""
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS network_nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                address TEXT NOT NULL,
                port INTEGER NOT NULL,
                ws_url TEXT,
                public_id TEXT,
                last_seen REAL NOT NULL,
                expires_at REAL NOT NULL,
                metadata TEXT
            )
        """)
        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_network_nodes_type
            ON network_nodes(node_type)
        """)
        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_network_nodes_expires_at
            ON network_nodes(expires_at)
        """)

    def _save_node(self, node: NetworkNode) -> None:
        """Сохранение узла в БД."""
        metadata_json = json.dumps(node.metadata) if node.metadata else "{}"
        self._storage.execute_sql(
            """
            INSERT OR REPLACE INTO network_nodes
            (node_id, node_type, address, port, ws_url, public_id, last_seen, expires_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.node_id,
                node.node_type,
                node.address,
                node.port,
                node.ws_url,
                node.public_id,
                node.last_seen,
                node.expires_at,
                metadata_json,
            ),
        )

    def _load_nodes(self) -> Dict[str, NetworkNode]:
        """Загрузка узлов из БД."""
        cursor = self._storage.execute_sql(
            "SELECT node_id, node_type, address, port, ws_url, public_id, last_seen, expires_at, metadata "
            "FROM network_nodes"
        )
        nodes = {}
        for row in cursor.fetchall():
            try:
                metadata = json.loads(row[8]) if row[8] else {}
            except json.JSONDecodeError:
                metadata = {}

            node = NetworkNode(
                node_id=row[0],
                node_type=row[1],
                address=row[2],
                port=row[3],
                ws_url=row[4],
                public_id=row[5],
                last_seen=row[6],
                expires_at=row[7],
                metadata=metadata,
            )
            nodes[node.node_id] = node
        return nodes

    async def add_node(self, node: NetworkNode) -> bool:
        """
        Добавление или обновление узла в карте.

        Args:
            node: Информация об узле

        Returns:
            True если узел добавлен/обновлён
        """
        async with self._lock:
            # Проверяем лимит узлов
            if len(self._nodes) >= MAX_NODES and node.node_id not in self._nodes:
                logger.warning(f"Node limit reached ({MAX_NODES}), cannot add {node.node_id}")
                return False

            existing = self._nodes.get(node.node_id)
            if existing:
                node.last_seen = existing.last_seen
                node.expires_at = existing.expires_at

            self._nodes[node.node_id] = node
            self._save_node(node)

            logger.info(f"Node added/updated: {node.node_id} ({node.node_type}) at {node.address}:{node.port}")

            # Рассылаем обновление
            await self._broadcast_update(node, "add" if not existing else "update")

            return True

    async def remove_node(self, node_id: str) -> bool:
        """
        Удаление узла из карты.

        Args:
            node_id: ID узла

        Returns:
            True если узел удалён
        """
        async with self._lock:
            if node_id not in self._nodes:
                return False

            node = self._nodes.pop(node_id)
            self._storage.execute_sql(
                "DELETE FROM network_nodes WHERE node_id = ?", (node_id,)
            )

            logger.info(f"Node removed: {node_id}")

            # Рассылаем обновление
            await self._broadcast_update(node, "remove")

            return True

    async def get_node(self, node_id: str) -> Optional[NetworkNode]:
        """
        Получение информации об узле.

        Args:
            node_id: ID узла

        Returns:
            NetworkNode или None
        """
        async with self._lock:
            return self._nodes.get(node_id)

    async def get_nodes_by_type(self, node_type: str) -> List[NetworkNode]:
        """
        Получение всех узлов определённого типа.

        Args:
            node_type: Тип узла ("rendezvous" | "client" | "server")

        Returns:
            Список узлов
        """
        async with self._lock:
            return [n for n in self._nodes.values() if n.node_type == node_type and n.is_active()]

    async def get_all_nodes(self) -> List[NetworkNode]:
        """
        Получение всех активных узлов.

        Returns:
            Список всех узлов с expires_at > now
        """
        async with self._lock:
            return [n for n in self._nodes.values() if n.is_active()]

    async def get_best_rendezvous(self) -> Optional[NetworkNode]:
        """
        Получение лучшего Rendezvous сервера.

        Выбирается сервер с наименьшей задержкой (по времени ответа).
        В прототипе возвращает первый активный rendezvous.

        Returns:
            NetworkNode или None
        """
        nodes = await self.get_nodes_by_type("rendezvous")
        if not nodes:
            return None
        # В прототипе возвращаем первый
        # В реальной версии нужно измерять задержку
        return nodes[0]

    async def update_heartbeat(self, node_id: str) -> bool:
        """
        Обновление heartbeat узла.

        Args:
            node_id: ID узла

        Returns:
            True если обновлено
        """
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return False

            node.update_heartbeat()
            self._save_node(node)
            logger.debug(f"Heartbeat updated for {node_id}")
            return True

    async def sync_with_client(self, client_public_id: str) -> List[NetworkNode]:
        """
        Синхронизация карты сети с клиентом.

        Args:
            client_public_id: Public ID клиента

        Returns:
            Список узлов для отправки клиенту
        """
        return await self.get_all_nodes()

    async def _broadcast_update(self, node: NetworkNode, action: str) -> int:
        """
        Рассылка обновления карты всем подключённым клиентам.

        Args:
            node: Изменённый узел
            action: "add" | "update" | "remove"

        Returns:
            Количество клиентов, получивших обновление
        """
        if not self._ws_manager:
            return 0

        message = {
            "type": "network_update",
            "data": {
                "action": action,
                "node": node.to_dict(),
            },
        }

        # Рассылаем всем клиентам
        count = await self._ws_manager.broadcast_to_all(message)
        logger.debug(f"Broadcasted network update to {count} clients")
        return count

    async def cleanup_expired(self) -> int:
        """
        Очистка истекших узлов (expires_at < now).

        Returns:
            Количество удалённых узлов
        """
        async with self._lock:
            now = time.time()
            expired = [node_id for node_id, node in self._nodes.items() if not node.is_active()]

            for node_id in expired:
                del self._nodes[node_id]
                self._storage.execute_sql(
                    "DELETE FROM network_nodes WHERE node_id = ?", (node_id,)
                )

            if expired:
                logger.info(f"Cleaned up {len(expired)} expired nodes")

            return len(expired)

    async def _monitor_loop(self) -> None:
        """Фоновый цикл мониторинга узлов."""
        while self._running:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            await self.cleanup_expired()

    async def start_monitor(self) -> None:
        """Запуск фонового мониторинга узлов."""
        if self._running:
            return

        # Загружаем сохранённые узлы из БД
        self._nodes = self._load_nodes()
        logger.info(f"Loaded {len(self._nodes)} nodes from database")

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Network map monitor started")

    async def stop_monitor(self) -> None:
        """Остановка фонового мониторинга."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Network map monitor stopped")

    async def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики сети.

        Returns:
            Словарь со статистикой
        """
        nodes = await self.get_all_nodes()
        by_type = {}
        for node in nodes:
            by_type[node.node_type] = by_type.get(node.node_type, 0) + 1

        return {
            "total_nodes": len(nodes),
            "by_type": by_type,
            "active_rendezvous": len(await self.get_nodes_by_type("rendezvous")),
            "active_clients": len(await self.get_nodes_by_type("client")),
            "active_servers": len(await self.get_nodes_by_type("server")),
        }
