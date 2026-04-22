# tests/conftest.py
import pytest
import tempfile
import os
import time
import sqlite3

from src.client.storage.messages import MessagesStorage
from src.common.storage.sqlite import SQLiteStorage
from src.server.storage.server_db import ServerDatabase


@pytest.fixture(autouse=True)
def clean_test_messages():
    """Очистка тестовых сообщений после каждого теста (для глобальной БД)."""
    yield
    try:
        conn = sqlite3.connect("duonet.db")
        conn.execute("DELETE FROM messages WHERE id LIKE 'sys_%' AND is_system=1")
        conn.execute("DELETE FROM messages WHERE id LIKE 'msg_%' AND timestamp < ?", (int(time.time()) - 3600,))
        conn.commit()
        conn.close()
    except:
        pass


@pytest.fixture
def messages_storage():
    """Создаёт временную БД для сообщений для каждого теста."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    msgs = MessagesStorage(db_path)
    yield msgs

    msgs.close()

    # Закрываем все возможные соединения перед удалением
    try:
        os.unlink(db_path)
    except PermissionError:
        time.sleep(0.1)
        try:
            os.unlink(db_path)
        except:
            pass


@pytest.fixture
def storage():
    """Создаёт временную SQLiteStorage для каждого теста."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = SQLiteStorage(db_path)
    yield db

    db.close()
    try:
        os.unlink(db_path)
    except PermissionError:
        time.sleep(0.1)
        try:
            os.unlink(db_path)
        except:
            pass


@pytest.fixture
def server_db():
    """Создаёт временную ServerDatabase для каждого теста."""
    with tempfile.NamedTemporaryFile(suffix="_server.db", delete=False) as f:
        db_path = f.name

    db = ServerDatabase(db_path)
    yield db

    db.close()
    try:
        os.unlink(db_path)
    except PermissionError:
        time.sleep(0.1)
        try:
            os.unlink(db_path)
        except:
            pass
