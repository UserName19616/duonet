"""
Генерация уникальных ID для ротации ключей.
Формат: YYYYMMDD_{nanoid(12)}
Пример: 20260417_8xK9p2NqR4
"""

import secrets
import time
from datetime import datetime, timezone


# Алфавит для nanoid (без путаных символов)
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_ALPHABET_SIZE = len(_ALPHABET)


def _nanoid(size: int = 12) -> str:
    """Генерация криптостойкого nanoid."""
    result = []
    for _ in range(size):
        # Используем secrets.randbelow для равномерного распределения
        idx = secrets.randbelow(_ALPHABET_SIZE)
        result.append(_ALPHABET[idx])
    return "".join(result)


def generate_rotation_id() -> str:
    """
    Генерация уникального ID ротации.

    Формат: {YYYYMMDD}_{nanoid(12)}
    Пример: 20260417_8xK9p2NqR4

    Returns:
        Уникальный ID ротации
    """
    # Используем UTC дату для единообразия
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = _nanoid(12)
    return f"{date_str}_{random_part}"


def extract_date_from_rotation_id(rotation_id: str) -> str:
    """
    Извлечение даты из ID ротации.

    Args:
        rotation_id: ID ротации формата YYYYMMDD_...

    Returns:
        Строка даты (YYYYMMDD) или пустая строка при ошибке
    """
    parts = rotation_id.split("_", 1)
    if len(parts) < 1:
        return ""
    return parts[0]


def is_rotation_id_expired(rotation_id: str, ttl_seconds: int = 86400) -> bool:
    """
    Проверка, истёк ли ID ротации (по дате в ID).

    Args:
        rotation_id: ID ротации
        ttl_seconds: Время жизни в секундах (по умолчанию 24 часа)

    Returns:
        True если ID старше ttl_seconds
    """
    date_str = extract_date_from_rotation_id(rotation_id)
    if not date_str or len(date_str) != 8:
        return True

    try:
        id_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        # ID считается истекшим, если его дата старше текущей более чем на ttl_seconds
        # Упрощённо: если дата ID меньше сегодняшней минус 1 день
        age = (now - id_date).total_seconds()
        return age > ttl_seconds
    except ValueError:
        return True
