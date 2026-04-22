# tests/unit/test_storage_messages.py
"""
Тесты для модуля хранения сообщений.
"""

import tempfile
import time
import os

import pytest

from src.client.storage.messages import MessageInfo, MessagesStorage
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def messages():
    """Создаёт временную БД с правильной схемой для каждого теста."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    msgs = MessagesStorage(db_path)

    # Принудительно добавляем колонки, если их нет (миграция)
    conn = msgs._get_conn()
    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'is_system' not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN is_system INTEGER DEFAULT 0")
    if 'system_type' not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN system_type TEXT")
    if 'system_data' not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN system_data TEXT")
    conn.commit()
    conn.close()

    yield msgs

    msgs.close()
    os.unlink(db_path)


def create_test_message(
    msg_id: str,
    from_id: str,
    to_id: str,
    timestamp: int,
    delivered: bool = False,
    read: bool = False,
) -> MessageInfo:
    """Создание тестового сообщения."""
    return MessageInfo(
        id=msg_id,
        from_id=from_id,
        to_id=to_id,
        session_key="a" * 64,
        encrypted="test_encrypted_data",
        timestamp=timestamp,
        delivered=delivered,
        read=read,
        has_phrase=False,
    )


class TestMessagesStorage:
    """Тесты для MessagesStorage."""

    def test_save_and_get(self, messages):
        """Сохранение и получение сообщения."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now
        )

        result = messages.save(msg)
        assert result is True

        retrieved = messages.get("msg_001")
        assert retrieved is not None
        assert retrieved.id == "msg_001"
        assert retrieved.from_id == "@ALICE-1234-5678.ru"

    def test_save_duplicate(self, messages):
        """Сохранение дубликата."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now
        )

        messages.save(msg)
        result = messages.save(msg)
        assert result is False

    def test_get_nonexistent(self, messages):
        """Получение несуществующего сообщения."""
        retrieved = messages.get("nonexistent")
        assert retrieved is None

    def test_get_dialog(self, messages):
        """Получение сообщений диалога."""
        now = int(time.time())
        msg1 = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now
        )
        msg2 = create_test_message(
            "msg_002", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now + 100
        )

        messages.save(msg1)
        messages.save(msg2)

        dialog_msgs = messages.get_dialog("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru")
        assert len(dialog_msgs) == 2

    def test_get_dialog_with_limit(self, messages):
        """Получение сообщений диалога с лимитом."""
        now = int(time.time())
        for i in range(5):
            msg = create_test_message(
                f"msg_{i:03d}",
                "@ALICE-1234-5678.ru",
                "@BOB-1234-5678.ru",
                now + i * 10,
            )
            messages.save(msg)

        msgs = messages.get_dialog("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", limit=3)
        assert len(msgs) == 3

    def test_get_dialog_with_offset(self, messages):
        """Получение сообщений диалога со смещением."""
        now = int(time.time())
        for i in range(5):
            msg = create_test_message(
                f"msg_{i:03d}",
                "@ALICE-1234-5678.ru",
                "@BOB-1234-5678.ru",
                now + i * 10,
            )
            messages.save(msg)

        msgs = messages.get_dialog("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", limit=2, offset=2)
        assert len(msgs) == 2

    def test_get_unread_all(self, messages):
        """Получение всех непрочитанных сообщений."""
        now = int(time.time())
        msg1 = create_test_message(
            "msg_001", "@BOB-1234-5678.ru", "@ALICE-1234-5678.ru", now, read=False
        )
        msg2 = create_test_message(
            "msg_002", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now + 10, read=True
        )
        msg3 = create_test_message(
            "msg_003", "@BOB-1234-5678.ru", "@ALICE-1234-5678.ru", now + 20, read=False
        )

        messages.save(msg1)
        messages.save(msg2)
        messages.save(msg3)

        unread = messages.get_unread("@ALICE-1234-5678.ru")
        assert len(unread) == 2

    def test_get_unread_by_contact(self, messages):
        """Получение непрочитанных сообщений по контакту."""
        now = int(time.time())
        msg1 = create_test_message(
            "msg_001", "@BOB-1234-5678.ru", "@ALICE-1234-5678.ru", now, read=False
        )
        msg2 = create_test_message(
            "msg_002", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now + 10, read=False
        )
        msg3 = create_test_message(
            "msg_003", "@BOB-1234-5678.ru", "@ALICE-1234-5678.ru", now + 20, read=False
        )

        messages.save(msg1)
        messages.save(msg2)
        messages.save(msg3)

        unread = messages.get_unread("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru")
        assert len(unread) == 2

    def test_mark_delivered(self, messages):
        """Отметка сообщения как доставленного."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now, delivered=False
        )
        messages.save(msg)

        result = messages.mark_delivered("msg_001")
        assert result is True

        retrieved = messages.get("msg_001")
        assert retrieved.delivered is True

    def test_mark_delivered_already(self, messages):
        """Отметка уже доставленного сообщения."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now, delivered=True
        )
        messages.save(msg)

        result = messages.mark_delivered("msg_001")
        assert result is False

    def test_mark_read(self, messages):
        """Отметка сообщения как прочитанного."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now, read=False
        )
        messages.save(msg)

        result = messages.mark_read("msg_001")
        assert result is True

        retrieved = messages.get("msg_001")
        assert retrieved.read is True

    def test_mark_all_read(self, messages):
        """Отметка всех сообщений от контакта как прочитанных."""
        now = int(time.time())
        for i in range(3):
            msg = create_test_message(
                f"msg_00{i}",
                "@BOB-1234-5678.ru",
                "@ALICE-1234-5678.ru",
                now + i * 10,
                read=False,
            )
            messages.save(msg)

        count = messages.mark_all_read("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru")
        assert count == 3

        unread = messages.get_unread("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru")
        assert len(unread) == 0

    def test_delete(self, messages):
        """Удаление сообщения."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now
        )
        messages.save(msg)

        result = messages.delete("msg_001")
        assert result is True
        assert messages.get("msg_001") is None

    def test_delete_dialog(self, messages):
        """Удаление всех сообщений диалога."""
        now = int(time.time())
        for i in range(3):
            msg = create_test_message(
                f"msg_00{i}",
                "@ALICE-1234-5678.ru",
                "@BOB-1234-5678.ru",
                now + i * 10,
            )
            messages.save(msg)

        count = messages.delete_dialog("@ALICE-1234-5678.ru", "@BOB-1234-5678.ru")
        assert count == 3

    def test_get_unread_count(self, messages):
        """Количество непрочитанных сообщений."""
        now = int(time.time())
        for i in range(5):
            msg = create_test_message(
                f"msg_00{i}",
                "@BOB-1234-5678.ru",
                "@ALICE-1234-5678.ru",
                now + i * 10,
                read=(i % 2 == 0),
            )
            messages.save(msg)

        count = messages.get_unread_count("@ALICE-1234-5678.ru")
        assert count == 2

    def test_cleanup_older_than(self, messages):
        """Удаление старых сообщений."""
        old_time = int(time.time()) - (31 * 86400)
        new_time = int(time.time())

        old_msg = create_test_message(
            "msg_old", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", old_time
        )
        new_msg = create_test_message(
            "msg_new", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", new_time
        )

        messages.save(old_msg)
        messages.save(new_msg)

        deleted = messages.cleanup_older_than(30)
        assert deleted == 1
        assert messages.get("msg_old") is None
        assert messages.get("msg_new") is not None

    def test_cleanup_older_than_zero_days(self, messages):
        """cleanup_older_than(0) удаляет сообщения старше 0 дней."""
        now = int(time.time())
        msg = create_test_message(
            "msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", now
        )
        messages.save(msg)

        deleted = messages.cleanup_older_than(0)
        assert deleted == 0

        old_time = now - 2
        msg_old = create_test_message(
            "msg_old", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", old_time
        )
        messages.save(msg_old)

        deleted2 = messages.cleanup_older_than(0)
        assert deleted2 == 1

        assert messages.get("msg_001") is not None
        assert messages.get("msg_old") is None

    def test_encrypted_hex_format(self, messages):
        """Проверка hex формата encrypted."""
        now = int(time.time())
        msg = MessageInfo(
            id="msg_001",
            from_id="@ALICE-1234-5678.ru",
            to_id="@BOB-1234-5678.ru",
            session_key="a" * 64,
            encrypted="01020304",
            timestamp=now,
            delivered=False,
            read=False,
            has_phrase=False,
        )
        messages.save(msg)

        retrieved = messages.get("msg_001")
        assert retrieved.encrypted == "01020304"

    def test_message_info_dataclass(self, messages):
        """Тест dataclass MessageInfo."""
        now = int(time.time())
        msg = MessageInfo(
            id="msg_001",
            from_id="@ALICE.ru",
            to_id="@BOB.ru",
            session_key="a" * 64,
            encrypted="test",
            timestamp=now,
            delivered=True,
            read=True,
            has_phrase=True,
        )
        messages.save(msg)

        retrieved = messages.get("msg_001")
        assert retrieved.id == "msg_001"
        assert retrieved.from_id == "@ALICE.ru"
        assert retrieved.to_id == "@BOB.ru"
        assert retrieved.timestamp == now
        assert retrieved.delivered is True
        assert retrieved.read is True
        assert retrieved.has_phrase is True

    def test_mark_delivered_nonexistent(self, messages):
        """Отметка доставки несуществующего сообщения."""
        result = messages.mark_delivered("nonexistent")
        assert result is False

    def test_mark_read_nonexistent(self, messages):
        """Отметка прочтения несуществующего сообщения."""
        result = messages.mark_read("nonexistent")
        assert result is False
