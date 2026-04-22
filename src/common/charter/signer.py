# src/charter/signer.py
"""
Подписание и проверка Устава.
"""
import time
from typing import Optional

from ..crypto.keys import sign, verify, hash_sha256
from ..storage.sqlite import SQLiteStorage
from .loader import get_charter_text, get_charter_version, get_charter_hash


def init_charter_table(storage: SQLiteStorage) -> None:
    storage.execute_sql("""
        CREATE TABLE IF NOT EXISTS charter_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_account_id BLOB NOT NULL,
            version TEXT NOT NULL,
            signature TEXT NOT NULL,
            charter_hash TEXT NOT NULL,
            lang TEXT NOT NULL DEFAULT 'ru',
            accepted_at INTEGER NOT NULL,
            UNIQUE(server_account_id, lang)
        )
    """)


def sign_charter(
    storage: SQLiteStorage,
    account_id: bytes,
    private_key: bytes,
    lang: str = "ru"
) -> bool:
    """
    Подписание Устава приватным ключом серверного аккаунта.

    Args:
        storage: Хранилище SQLite
        account_id: ID серверного аккаунта
        private_key: Приватный ключ (32 байта)
        lang: Язык Устава

    Returns:
        True если подпись сохранена
    """
    # Инициализируем таблицу
    init_charter_table(storage)

    # Получаем текст Устава и хеш
    charter_text = get_charter_text(lang)
    charter_version = get_charter_version()
    charter_hash = get_charter_hash(lang)

    # Подписываем текст
    signature = sign(private_key, charter_text.encode())
    signature_hex = signature.hex()

    # Сохраняем
    now = int(time.time())
    storage.execute_sql(
        """
        INSERT OR REPLACE INTO charter_acceptances
        (server_account_id, version, signature, charter_hash, lang, accepted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (account_id, charter_version, signature_hex, charter_hash, lang, now)
    )

    return True


def verify_charter_signature(
    storage: SQLiteStorage,
    public_key: bytes,
    lang: str = "ru"
) -> bool:
    """
    Проверка подписи Устава для серверного аккаунта.

    Args:
        storage: Хранилище SQLite
        public_key: Публичный ключ серверного аккаунта
        lang: Язык Устава

    Returns:
        True если подпись верна
    """
    # Получаем запись о принятии для указанного языка
    cursor = storage.execute_sql(
        """
        SELECT signature, charter_hash FROM charter_acceptances
        WHERE server_account_id = (SELECT account_id FROM accounts WHERE public_key = ?)
        AND lang = ?
        ORDER BY accepted_at DESC LIMIT 1
        """,
        (public_key, lang)
    )
    row = cursor.fetchone()
    if not row:
        return False

    signature_hex, stored_hash = row
    signature = bytes.fromhex(signature_hex)

    # Получаем текущий текст Устава
    charter_text = get_charter_text(lang)
    current_hash = get_charter_hash(lang)

    # Проверяем, что версия Устава не изменилась
    if stored_hash != current_hash:
        return False

    # Проверяем подпись
    return verify(public_key, signature, charter_text.encode())


def save_charter_acceptance(
    storage: SQLiteStorage,
    account_id: bytes,
    private_key: bytes,
    lang: str = "ru"
) -> bool:
    """
    Сохранение принятия Устава (обёртка для sign_charter).

    Args:
        storage: Хранилище SQLite
        account_id: ID серверного аккаунта
        private_key: Приватный ключ
        lang: Язык Устава

    Returns:
        True если сохранено
    """
    return sign_charter(storage, account_id, private_key, lang)


def check_charter_accepted(
    storage: SQLiteStorage,
    account_id: bytes,
    lang: str = "ru"
) -> bool:
    """
    Проверка, принимал ли серверный аккаунт Устав на указанном языке.

    Args:
        storage: Хранилище SQLite
        account_id: ID серверного аккаунта
        lang: Язык Устава

    Returns:
        True если Устав принят
    """
    cursor = storage.execute_sql(
        "SELECT 1 FROM charter_acceptances WHERE server_account_id = ? AND lang = ?",
        (account_id, lang)
    )
    return cursor.fetchone() is not None


def get_charter_signature(
    storage: SQLiteStorage,
    account_id: bytes,
    lang: str = "ru"
) -> Optional[str]:
    """
    Получение подписи Устава для серверного аккаунта.

    Args:
        storage: Хранилище SQLite
        account_id: ID серверного аккаунта
        lang: Язык Устава

    Returns:
        Подпись в hex или None
    """
    cursor = storage.execute_sql(
        "SELECT signature FROM charter_acceptances WHERE server_account_id = ? AND lang = ?",
        (account_id, lang)
    )
    row = cursor.fetchone()
    return row[0] if row else None
