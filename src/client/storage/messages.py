# src/client/storage/messages.py
"""
Управление хранением сообщений пользователя.
"""

import sqlite3
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MessageInfo:
    id: str
    from_id: str
    to_id: str
    session_key: str
    encrypted: str
    timestamp: int
    has_phrase: bool = False
    delivered: bool = False
    read: bool = False
    direction: str = "outgoing"
    pfs_key: Optional[str] = None
    is_system: int = 0
    system_type: Optional[str] = None
    system_data: Optional[str] = None


class MessagesStorage:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    from_id TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    pfs_key TEXT,
                    encrypted TEXT NOT NULL,
                    has_phrase INTEGER DEFAULT 0,
                    timestamp INTEGER NOT NULL,
                    delivered INTEGER DEFAULT 0,
                    read INTEGER DEFAULT 0,
                    direction TEXT DEFAULT 'outgoing',
                    is_system INTEGER DEFAULT 0,
                    system_type TEXT,
                    system_data TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_dialog ON messages(from_id, to_id, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_participant ON messages(from_id, to_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(to_id, read)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_system ON messages(is_system)")
            conn.commit()

    def save(self, message: MessageInfo) -> bool:
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT 1 FROM messages WHERE id = ?", (message.id,))
                if cursor.fetchone():
                    return False
                conn.execute("""
                    INSERT INTO messages (id, from_id, to_id, session_key, pfs_key, encrypted,
                        has_phrase, timestamp, delivered, read, direction, is_system, system_type, system_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (message.id, message.from_id, message.to_id, message.session_key, message.pfs_key,
                      message.encrypted, 1 if message.has_phrase else 0, message.timestamp,
                      1 if message.delivered else 0, 1 if message.read else 0, message.direction,
                      message.is_system, message.system_type, message.system_data))
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"Duplicate message: {message.id}")
            return False

    def get(self, message_id: str) -> Optional[MessageInfo]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, from_id, to_id, session_key, encrypted, timestamp, has_phrase, delivered, read, direction, pfs_key "
                "FROM messages WHERE id = ?",
                (message_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return MessageInfo(
                id=row["id"],
                from_id=row["from_id"],
                to_id=row["to_id"],
                session_key=row["session_key"],
                encrypted=row["encrypted"],
                timestamp=row["timestamp"],
                has_phrase=bool(row["has_phrase"]),
                delivered=bool(row["delivered"]),
                read=bool(row["read"]),
                direction=row["direction"],
                pfs_key=row["pfs_key"]
            )

    def get_dialog(self, user_id: str, contact_id: str, limit: int = 50, offset: int = 0) -> List[MessageInfo]:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT id, from_id, to_id, session_key, encrypted, timestamp, has_phrase,
                       delivered, read, direction, pfs_key
                FROM messages
                WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)
                ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """, (user_id, contact_id, contact_id, user_id, limit, offset))
            messages = []
            for row in cursor.fetchall():
                messages.append(MessageInfo(
                    id=row["id"],
                    from_id=row["from_id"],
                    to_id=row["to_id"],
                    session_key=row["session_key"],
                    encrypted=row["encrypted"],
                    timestamp=row["timestamp"],
                    has_phrase=bool(row["has_phrase"]),
                    delivered=bool(row["delivered"]),
                    read=bool(row["read"]),
                    direction=row["direction"],
                    pfs_key=row["pfs_key"]
                ))
            return messages

    def get_unread(self, user_id: str, contact_id: Optional[str] = None) -> List[MessageInfo]:
        with self._get_conn() as conn:
            if contact_id:
                cursor = conn.execute("SELECT * FROM messages WHERE to_id = ? AND from_id = ? AND read = 0 ORDER BY timestamp ASC",
                                     (user_id, contact_id))
            else:
                cursor = conn.execute("SELECT * FROM messages WHERE to_id = ? AND read = 0 ORDER BY timestamp ASC", (user_id,))
            messages = []
            for row in cursor.fetchall():
                messages.append(MessageInfo(id=row["id"], from_id=row["from_id"], to_id=row["to_id"],
                                            session_key=row["session_key"], encrypted=row["encrypted"],
                                            timestamp=row["timestamp"], has_phrase=bool(row["has_phrase"]),
                                            delivered=bool(row["delivered"]), read=bool(row["read"]),
                                            direction=row["direction"], pfs_key=row["pfs_key"]))
            return messages

    def mark_delivered(self, message_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("UPDATE messages SET delivered = 1 WHERE id = ? AND delivered = 0", (message_id,))
            return cursor.rowcount > 0

    def mark_read(self, message_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("UPDATE messages SET read = 1 WHERE id = ? AND read = 0", (message_id,))
            return cursor.rowcount > 0

    def mark_all_read(self, user_id: str, contact_id: str) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute("UPDATE messages SET read = 1 WHERE to_id = ? AND from_id = ? AND read = 0",
                                 (user_id, contact_id))
            return cursor.rowcount

    def delete(self, message_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            return cursor.rowcount > 0

    def delete_dialog(self, user_id: str, contact_id: str) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
                                 (user_id, contact_id, contact_id, user_id))
            return cursor.rowcount

    def get_session_key(self, message_id: str) -> Optional[str]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT session_key FROM messages WHERE id = ?", (message_id,))
            row = cursor.fetchone()
            return row["session_key"] if row else None

    def get_unread_count(self, user_id: str, contact_id: Optional[str] = None) -> int:
        with self._get_conn() as conn:
            if contact_id:
                cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE to_id = ? AND from_id = ? AND read = 0",
                                     (user_id, contact_id))
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE to_id = ? AND read = 0", (user_id,))
            return cursor.fetchone()[0]

    def cleanup_older_than(self, days: int) -> int:
        cutoff = int(time.time()) - (days * 86400)
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
            return cursor.rowcount

    def get_all_dialogs(self, user_id: str) -> List[tuple]:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT CASE WHEN from_id = ? THEN to_id ELSE from_id END as contact_id,
                       MAX(timestamp) as last_activity
                FROM messages WHERE from_id = ? OR to_id = ?
                GROUP BY contact_id ORDER BY last_activity DESC
            """, (user_id, user_id, user_id))
            return [(row["contact_id"], row["last_activity"]) for row in cursor.fetchall()]

    def close(self) -> None:
        pass
