# tests/unit/test_storage_messages_new.py
"""
Тесты для MessagesStorage с поддержкой session_key и LRP.
"""

import tempfile
import time
import os
import pytest

from src.client.storage.messages import MessageInfo, MessagesStorage


@pytest.fixture
def messages_storage():
    """Создаёт временную БД для каждого теста."""
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
    session_key: str = "a" * 64,
    has_phrase: bool = False,
) -> MessageInfo:
    """Создание тестового сообщения."""
    return MessageInfo(
        id=msg_id,
        from_id=from_id,
        to_id=to_id,
        session_key=session_key,
        encrypted="test_encrypted_data",
        timestamp=int(time.time()),
        delivered=False,
        read=False,
        has_phrase=has_phrase,
        direction="outgoing",
    )


class TestMessagesStorageWithSessionKey:
    """Тесты для MessagesStorage с session_key."""

    def test_save_message_with_session_key(self, messages_storage):
        msg = create_test_message("msg_001", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", "a" * 64)
        result = messages_storage.save(msg)
        assert result is True

        retrieved = messages_storage.get("msg_001")
        assert retrieved is not None
        assert retrieved.session_key == "a" * 64
        assert retrieved.id == "msg_001"

    def test_get_session_key_for_message(self, messages_storage):
        msg = create_test_message("msg_002", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", "b" * 64)
        messages_storage.save(msg)

        session_key = messages_storage.get_session_key("msg_002")
        assert session_key == "b" * 64

    def test_message_has_phrase_flag(self, messages_storage):
        msg = create_test_message("msg_003", "@ALICE-1234-5678.ru", "@BOB-1234-5678.ru", "c" * 64, has_phrase=True)
        messages_storage.save(msg)

        retrieved = messages_storage.get("msg_003")
        assert retrieved.has_phrase is True

    def test_get_dialog_returns_session_key(self, messages_storage):
        msg1 = create_test_message("msg_001", "@ALICE.ru", "@BOB.ru", "key1" + "0" * 60)
        msg2 = create_test_message("msg_002", "@BOB.ru", "@ALICE.ru", "key2" + "0" * 60)
        messages_storage.save(msg1)
        messages_storage.save(msg2)

        messages = messages_storage.get_dialog("@ALICE.ru", "@BOB.ru")
        assert len(messages) == 2
        # Порядок может быть разный, проверяем что оба ключа присутствуют
        keys = [m.session_key for m in messages]
        assert "key1" + "0" * 60 in keys
        assert "key2" + "0" * 60 in keys

    def test_get_unread_returns_session_key(self, messages_storage):
        msg = create_test_message("msg_001", "@ALICE.ru", "@BOB.ru", "key123")
        messages_storage.save(msg)

        unread = messages_storage.get_unread("@BOB.ru")
        assert len(unread) == 1
        assert unread[0].session_key == "key123"


class TestMessageInfoWithSessionKey:
    """Тесты для MessageInfo dataclass."""

    def test_message_info_creation(self):
        msg = MessageInfo(
            id="test_id",
            from_id="@A.ru",
            to_id="@B.ru",
            encrypted="data",
            session_key="a" * 64,
            timestamp=123456,
            delivered=False,
            read=False,
            has_phrase=False,
        )
        assert msg.session_key == "a" * 64
        assert len(msg.session_key) == 64

    def test_message_info_with_pfs_key(self):
        msg = MessageInfo(
            id="test_id",
            from_id="@A.ru",
            to_id="@B.ru",
            encrypted="data",
            session_key="a" * 64,
            timestamp=123456,
            delivered=False,
            read=False,
            has_phrase=True,
            pfs_key="b" * 64,
        )
        assert msg.pfs_key == "b" * 64
        assert msg.has_phrase is True

    def test_message_info_with_system_fields(self):
        msg = MessageInfo(
            id="test_id",
            from_id="@A.ru",
            to_id="@B.ru",
            encrypted="data",
            session_key="a" * 64,
            timestamp=123456,
            delivered=True,
            read=True,
            has_phrase=False,
            is_system=1,
            system_type="rotation_request",
            system_data='{"request_id": "123"}',
        )
        assert msg.is_system == 1
        assert msg.system_type == "rotation_request"
        assert msg.system_data == '{"request_id": "123"}'
