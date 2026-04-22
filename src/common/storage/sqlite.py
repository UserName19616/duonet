# src/common/storage/sqlite.py
"""
Низкоуровневое key-value хранилище на базе SQLite.
Поддерживает системные сообщения для протокола ротации ключей V3.
"""

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple


class SQLiteStorage:
    """
    Key-value хранилище на SQLite.

    Использует WAL режим для лучшей производительности.
    Потокобезопасен за счет threading.RLock.
    Поддерживает системные сообщения для протокола ротации ключей V3.
    """

    def __init__(self, path: str):
        """
        Инициализация хранилища.

        Args:
            path: Путь к файлу базы данных.

        Raises:
            RuntimeError: При ошибке открытия базы данных.
        """
        self._path = path
        self._lock = threading.RLock()
        self._closed = False

        try:
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._create_tables()
            self._migrate_tables()
        except Exception as e:
            raise RuntimeError(f"Failed to open database: {e}")

    def _create_tables(self) -> None:
        """Инициализация таблиц storage, dialogs, messages и rotation_state."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS storage (
                key BLOB PRIMARY KEY,
                value BLOB NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_key ON storage(key)")

        # Таблица диалогов
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS dialogs (
                user_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_activity INTEGER NOT NULL,
                PRIMARY KEY (user_id, contact_id)
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_dialogs_user ON dialogs(user_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_dialogs_contact ON dialogs(contact_id)")

        # Таблица сообщений (с поддержкой системных сообщений)
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_system ON messages(is_system)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_system_type ON messages(system_type)")

        # Таблица состояния ротации ключей V3 (заменяет старую rotation_state)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS rotation_state (
                dialog_id TEXT PRIMARY KEY,
                active_key TEXT NOT NULL,
                pending_rotation_id TEXT,
                pending_status TEXT,
                pending_expires_at INTEGER DEFAULT 0,
                pending_eph_public_key TEXT,
                last_rotation_by_me TEXT,
                last_rotation_by_peer TEXT,
                updated_at INTEGER
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_rotation_state_pending ON rotation_state(pending_rotation_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_rotation_state_updated ON rotation_state(updated_at)")

        self._conn.commit()

    def _migrate_tables(self) -> None:
        """Миграция существующих таблиц (добавление новых колонок и индексов)."""
        # Добавляем колонки в messages если их нет
        cursor = self._conn.execute("PRAGMA table_info(messages)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'is_system' not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN is_system INTEGER DEFAULT 0")
            print("Added column is_system to messages table")

        if 'system_type' not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN system_type TEXT")
            print("Added column system_type to messages table")

        if 'system_data' not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN system_data TEXT")
            print("Added column system_data to messages table")

        if 'session_key' not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN session_key TEXT")
            print("Added column session_key to messages table")

        if 'pfs_key' not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN pfs_key TEXT")
            print("Added column pfs_key to messages table")

        if 'direction' not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN direction TEXT DEFAULT 'outgoing'")
            print("Added column direction to messages table")

        # Создаём индексы для messages
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_system ON messages(is_system)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_system_type ON messages(system_type)")

        # Проверяем структуру rotation_state и мигрируем если нужно
        cursor = self._conn.execute("PRAGMA table_info(rotation_state)")
        rot_columns = [row[1] for row in cursor.fetchall()]

        # Добавляем новые колонки для V3
        if 'pending_status' not in rot_columns:
            self._conn.execute("ALTER TABLE rotation_state ADD COLUMN pending_status TEXT")
            print("Added column pending_status to rotation_state")

        if 'pending_eph_public_key' not in rot_columns:
            self._conn.execute("ALTER TABLE rotation_state ADD COLUMN pending_eph_public_key TEXT")
            print("Added column pending_eph_public_key to rotation_state")

        # Переименовываем старые колонки если нужно (pending_request_id -> pending_rotation_id)
        if 'pending_request_id' in rot_columns and 'pending_rotation_id' not in rot_columns:
            self._conn.execute("ALTER TABLE rotation_state RENAME COLUMN pending_request_id TO pending_rotation_id")
            print("Renamed column pending_request_id to pending_rotation_id")

        # Удаляем старые LRP-колонки если есть
        lrp_columns = ['pool_version', 'used_indices', 'key_history', 'mode', 'rotation_deadline']
        for col in lrp_columns:
            if col in rot_columns:
                try:
                    self._conn.execute(f"ALTER TABLE rotation_state DROP COLUMN {col}")
                    print(f"Dropped legacy column {col} from rotation_state")
                except sqlite3.OperationalError:
                    pass  # колонка уже удалена

        self._conn.commit()

    # =========================================================================
    # МЕТОДЫ ДЛЯ СИСТЕМНЫХ СООБЩЕНИЙ (ротация ключей V3)
    # =========================================================================

    def save_system_message(
        self,
        msg_id: str,
        from_id: str,
        to_id: str,
        timestamp: int,
        system_type: str,
        system_data: Optional[str] = None,
    ) -> bool:
        """
        Сохранение системного сообщения (для ротации ключей и т.д.).

        Args:
            msg_id: Уникальный ID сообщения
            from_id: Отправитель
            to_id: Получатель
            timestamp: Время создания
            system_type: Тип системного сообщения
            system_data: JSON данные сообщения

        Returns:
            True если сохранено, False при ошибке
        """
        try:
            self._conn.execute("""
                INSERT OR REPLACE INTO messages
                (id, from_id, to_id, session_key, encrypted, has_phrase,
                 timestamp, delivered, read, direction, is_system,
                 system_type, system_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg_id, from_id, to_id, "", "", 0,
                timestamp, 1, 1, "system", 1,
                system_type, system_data
            ))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Failed to save system message: {e}")
            return False

    def get_system_messages(
        self,
        user_id: str,
        contact_id: str,
        system_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Получение системных сообщений для диалога.

        Args:
            user_id: ID пользователя
            contact_id: ID контакта
            system_type: Фильтр по типу (опционально)
            limit: Максимальное количество сообщений

        Returns:
            Список системных сообщений
        """
        self._conn.row_factory = sqlite3.Row
        if system_type:
            cursor = self._conn.execute("""
                SELECT id, from_id, to_id, timestamp, system_type, system_data
                FROM messages
                WHERE ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                  AND is_system = 1
                  AND system_type = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, contact_id, contact_id, user_id, system_type, limit))
        else:
            cursor = self._conn.execute("""
                SELECT id, from_id, to_id, timestamp, system_type, system_data
                FROM messages
                WHERE ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                  AND is_system = 1
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, contact_id, contact_id, user_id, limit))

        messages = []
        for row in cursor.fetchall():
            messages.append({
                "id": row["id"],
                "from_id": row["from_id"],
                "to_id": row["to_id"],
                "timestamp": row["timestamp"],
                "system_type": row["system_type"],
                "system_data": json.loads(row["system_data"]) if row["system_data"] else {},
            })
        return messages

    def get_rotation_history(
        self,
        user_id: str,
        contact_id: str,
        initiated_by_me: Optional[bool] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Получение истории ротаций ключей.

        Args:
            user_id: ID пользователя
            contact_id: ID контакта
            initiated_by_me: True — только где я инициатор, False — только собеседник, None — все
            limit: Максимальное количество записей

        Returns:
            Список записей о ротациях
        """
        self._conn.row_factory = sqlite3.Row
        if initiated_by_me is True:
            cursor = self._conn.execute("""
                SELECT id, from_id, to_id, timestamp, system_data
                FROM messages
                WHERE ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                  AND is_system = 1
                  AND system_type = 'rotation_complete'
                  AND json_extract(system_data, '$.initiator') = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, contact_id, contact_id, user_id, user_id, limit))
        elif initiated_by_me is False:
            cursor = self._conn.execute("""
                SELECT id, from_id, to_id, timestamp, system_data
                FROM messages
                WHERE ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                  AND is_system = 1
                  AND system_type = 'rotation_complete'
                  AND json_extract(system_data, '$.initiator') = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, contact_id, contact_id, user_id, contact_id, limit))
        else:
            cursor = self._conn.execute("""
                SELECT id, from_id, to_id, timestamp, system_data
                FROM messages
                WHERE ((from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?))
                  AND is_system = 1
                  AND system_type = 'rotation_complete'
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, contact_id, contact_id, user_id, limit))

        history = []
        for row in cursor.fetchall():
            history.append({
                "id": row["id"],
                "from_id": row["from_id"],
                "to_id": row["to_id"],
                "timestamp": row["timestamp"],
                "system_data": json.loads(row["system_data"]) if row["system_data"] else {},
            })
        return history

    # =========================================================================
    # МЕТОДЫ ДЛЯ СОСТОЯНИЯ РОТАЦИИ (rotation_state V3)
    # =========================================================================

    def save_rotation_state(self, dialog_id: str, state: dict) -> None:
        """Сохранение состояния ротации для диалога."""
        now = int(time.time())

        self._conn.execute("""
            INSERT OR REPLACE INTO rotation_state
            (dialog_id, active_key, pending_rotation_id, pending_status, pending_expires_at,
             pending_eph_public_key, last_rotation_by_me, last_rotation_by_peer, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dialog_id,
            state.get("active_key", ""),
            state.get("pending_rotation_id"),
            state.get("pending_status"),
            state.get("pending_expires_at", 0),
            state.get("pending_eph_public_key"),
            state.get("last_rotation_by_me", ""),
            state.get("last_rotation_by_peer", ""),
            now
        ))
        self._conn.commit()

    def load_rotation_state(self, dialog_id: str) -> Optional[dict]:
        """Загрузка состояния ротации для диалога."""
        self._conn.row_factory = sqlite3.Row
        cursor = self._conn.execute("""
            SELECT dialog_id, active_key, pending_rotation_id, pending_status, pending_expires_at,
                   pending_eph_public_key, last_rotation_by_me, last_rotation_by_peer, updated_at
            FROM rotation_state
            WHERE dialog_id = ?
        """, (dialog_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return {
            "dialog_id": row["dialog_id"],
            "active_key": row["active_key"],
            "pending_rotation_id": row["pending_rotation_id"],
            "pending_status": row["pending_status"],
            "pending_expires_at": row["pending_expires_at"],
            "pending_eph_public_key": row["pending_eph_public_key"],
            "last_rotation_by_me": row["last_rotation_by_me"],
            "last_rotation_by_peer": row["last_rotation_by_peer"],
            "updated_at": row["updated_at"]
        }

    def delete_rotation_state(self, dialog_id: str) -> bool:
        """Удаление состояния ротации для диалога."""
        cursor = self._conn.execute(
            "DELETE FROM rotation_state WHERE dialog_id = ?",
            (dialog_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_all_rotation_states(self) -> List[dict]:
        """Получение всех состояний ротации."""
        self._conn.row_factory = sqlite3.Row
        cursor = self._conn.execute("""
            SELECT dialog_id, active_key, pending_rotation_id, pending_status, pending_expires_at,
                   pending_eph_public_key, last_rotation_by_me, last_rotation_by_peer, updated_at
            FROM rotation_state
            ORDER BY updated_at DESC
        """)

        states = []
        for row in cursor.fetchall():
            states.append({
                "dialog_id": row["dialog_id"],
                "active_key": row["active_key"],
                "pending_rotation_id": row["pending_rotation_id"],
                "pending_status": row["pending_status"],
                "pending_expires_at": row["pending_expires_at"],
                "pending_eph_public_key": row["pending_eph_public_key"],
                "last_rotation_by_me": row["last_rotation_by_me"],
                "last_rotation_by_peer": row["last_rotation_by_peer"],
                "updated_at": row["updated_at"]
            })

        return states

    def cleanup_expired_rotation_states(self, older_than_seconds: int = 86400) -> int:
        """Очистка устаревших состояний ротации (без pending)."""
        cutoff = int(time.time()) - older_than_seconds
        cursor = self._conn.execute(
            "DELETE FROM rotation_state WHERE updated_at < ? AND pending_rotation_id IS NULL",
            (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount

    # =========================================================================
    # МЕТОДЫ ДЛЯ ДИАЛОГОВ
    # =========================================================================

    def get_dialog(self, user_id: str, contact_id: str) -> Optional[str]:
        """Получение session_key для диалога."""
        self._conn.row_factory = sqlite3.Row
        cursor = self._conn.execute(
            "SELECT session_key FROM dialogs WHERE user_id = ? AND contact_id = ?",
            (user_id, contact_id)
        )
        row = cursor.fetchone()
        return row["session_key"] if row else None

    def save_dialog(self, user_id: str, contact_id: str, session_key: str) -> None:
        """Сохранение session_key для диалога."""
        now = int(time.time())
        self._conn.execute("""
            INSERT OR REPLACE INTO dialogs
            (user_id, contact_id, session_key, created_at, last_activity)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, contact_id, session_key, now, now))
        self._conn.commit()

    def get_all_dialogs(self, user_id: str) -> List[Tuple[str, str]]:
        """
        Получение всех диалогов пользователя.

        Returns:
            List[Tuple[str, str]]: Список (contact_id, session_key)
        """
        self._conn.row_factory = sqlite3.Row
        cursor = self._conn.execute(
            "SELECT contact_id, session_key FROM dialogs WHERE user_id = ?",
            (user_id,)
        )
        return [(row["contact_id"], row["session_key"]) for row in cursor.fetchall()]

    def update_dialog_activity(self, user_id: str, contact_id: str) -> None:
        """Обновление времени последней активности в диалоге."""
        now = int(time.time())
        self._conn.execute("""
            UPDATE dialogs SET last_activity = ?
            WHERE user_id = ? AND contact_id = ?
        """, (now, user_id, contact_id))
        self._conn.commit()

    def delete_dialog(self, user_id: str, contact_id: str) -> bool:
        """Удаление диалога."""
        cursor = self._conn.execute(
            "DELETE FROM dialogs WHERE user_id = ? AND contact_id = ?",
            (user_id, contact_id)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # =========================================================================
    # МЕТОДЫ ДЛЯ СООБЩЕНИЙ (с поддержкой метаданных)
    # =========================================================================

    def save_message_with_metadata(
        self,
        msg_id: str,
        from_id: str,
        to_id: str,
        session_key: str,
        encrypted: str,
        timestamp: int,
        has_phrase: bool = False,
        direction: str = "outgoing",
        is_system: int = 0,
        system_type: str = None,
        system_data: str = None
    ) -> bool:
        """Сохранение сообщения с метаданными."""
        try:
            self._conn.execute("""
                INSERT OR REPLACE INTO messages (
                    id, from_id, to_id, session_key, pfs_key, encrypted,
                    has_phrase, timestamp, delivered, read, direction,
                    is_system, system_type, system_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg_id, from_id, to_id, session_key, None, encrypted,
                1 if has_phrase else 0, timestamp, 0, 0, direction,
                is_system, system_type, system_data
            ))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # =========================================================================
    # СУЩЕСТВУЮЩИЕ МЕТОДЫ (key-value storage)
    # =========================================================================

    def _check_closed(self) -> None:
        """Проверка, закрыта ли база данных."""
        if self._closed:
            raise RuntimeError("Database is closed")

    @contextmanager
    def _transaction(self):
        """Контекстный менеджер для транзакций."""
        self._check_closed()
        with self._lock:
            try:
                yield
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def put(self, key: bytes, value: bytes) -> None:
        """Запись значения по ключу."""
        if not isinstance(key, bytes):
            raise ValueError(f"Key must be bytes, got {type(key)}")
        if not isinstance(value, bytes):
            raise ValueError(f"Value must be bytes, got {type(value)}")

        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO storage (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get(self, key: bytes) -> Optional[bytes]:
        """Чтение значения по ключу."""
        if not isinstance(key, bytes):
            raise ValueError(f"Key must be bytes, got {type(key)}")

        self._check_closed()
        with self._lock:
            cursor = self._conn.execute(
                "SELECT value FROM storage WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def exists(self, key: bytes) -> bool:
        """Проверка существования ключа."""
        if not isinstance(key, bytes):
            raise ValueError(f"Key must be bytes, got {type(key)}")

        self._check_closed()
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM storage WHERE key = ? LIMIT 1", (key,)
            )
            return cursor.fetchone() is not None

    def delete(self, key: bytes) -> None:
        """Удаление значения по ключу."""
        if not isinstance(key, bytes):
            raise ValueError(f"Key must be bytes, got {type(key)}")

        with self._transaction():
            self._conn.execute("DELETE FROM storage WHERE key = ?", (key,))

    def iter_keys(self, prefix: bytes = b"") -> Generator[bytes, None, None]:
        """Итерация по ключам с заданным префиксом."""
        if not isinstance(prefix, bytes):
            raise ValueError(f"Prefix must be bytes, got {type(prefix)}")

        self._check_closed()
        with self._lock:
            if prefix:
                pattern = prefix.hex() + "%"
                cursor = self._conn.execute(
                    "SELECT key FROM storage WHERE hex(key) LIKE ?",
                    (pattern,),
                )
            else:
                cursor = self._conn.execute("SELECT key FROM storage")

            for row in cursor:
                yield row[0]

    def iter_keys_list(self, prefix: bytes = b"") -> List[bytes]:
        """Получение списка ключей с заданным префиксом."""
        return list(self.iter_keys(prefix))

    def iter_items(
        self, prefix: bytes = b""
    ) -> Generator[Tuple[bytes, bytes], None, None]:
        """Итерация по парам ключ-значение с заданным префиксом."""
        if not isinstance(prefix, bytes):
            raise ValueError(f"Prefix must be bytes, got {type(prefix)}")

        self._check_closed()
        with self._lock:
            if prefix:
                pattern = prefix.hex() + "%"
                cursor = self._conn.execute(
                    "SELECT key, value FROM storage WHERE hex(key) LIKE ?",
                    (pattern,),
                )
            else:
                cursor = self._conn.execute("SELECT key, value FROM storage")

            for row in cursor:
                yield row[0], row[1]

    def iter_items_list(self, prefix: bytes = b"") -> List[Tuple[bytes, bytes]]:
        """Получение списка пар ключ-значение с заданным префиксом."""
        return list(self.iter_items(prefix))

    def batch_write(self, operations: List[Tuple[str, bytes, bytes]]) -> None:
        """Пакетная запись нескольких операций."""
        with self._transaction():
            for op, key, value in operations:
                if not isinstance(key, bytes):
                    raise ValueError(f"Key must be bytes, got {type(key)}")

                if op == "put":
                    if not isinstance(value, bytes):
                        raise ValueError(
                            f"Value must be bytes, got {type(value)}"
                        )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO storage (key, value) VALUES (?, ?)",
                        (key, value),
                    )
                elif op == "delete":
                    self._conn.execute(
                        "DELETE FROM storage WHERE key = ?", (key,)
                    )
                else:
                    raise ValueError(f"Unknown operation: {op}")

    def execute_sql(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Выполнение произвольного SQL-запроса."""
        self._check_closed()
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def close(self) -> None:
        """Закрытие базы данных."""
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
