# src/common/crypto/padding.py
"""
Адаптивный паддинг для защиты от анализа трафика.
Реализует "пинг-понг" алгоритм с синхронизацией через счётчик сообщений.

Принцип работы:
1. Размер паддинга зависит от:
   - направленного ключа (уникального для пары участников)
   - счётчика сообщений (порядковый номер)
   - размера предыдущего паддинга (пинг-понг)
   - длины исходного текста

2. Короткие сообщения (<20 байт) получают дополнительный паддинг (boost)

3. Длинные сообщения (>200 байт) не паддимся (экономия трафика)

4. Синхронизация через message_id (содержит счётчик)
"""

import secrets
from typing import Optional

# Исправленный импорт: config теперь на уровень выше
from src.config import (
    PAD_MIN, PAD_RANGE, PAD_BOOST_SHORT,
    PAD_MAX_LONG, LONG_MESSAGE_THRESHOLD
)
from .common import get_directional_key


def calculate_padding_size(
    session_key: bytes,
    from_id: str,
    to_id: str,
    message_counter: int,
    plaintext_len: int,
    prev_padding: int = 0
) -> int:
    """
    Вычисляет размер паддинга для сообщения.

    Args:
        session_key: 32-байтовый сессионный ключ
        from_id: Public ID отправителя
        to_id: Public ID получателя
        message_counter: порядковый номер сообщения в диалоге (0, 1, 2...)
        plaintext_len: длина исходного текста в байтах
        prev_padding: размер паддинга предыдущего сообщения (0 для первого)

    Returns:
        размер паддинга в байтах (0 если паддинг не нужен)
    """
    # Длинные сообщения не паддим
    if plaintext_len > LONG_MESSAGE_THRESHOLD:
        return 0

    # Получаем направленный ключ
    directional_key = get_directional_key(session_key, from_id, to_id)

    # Берём байт ключа на основе счётчика (циклически)
    key_byte = directional_key[message_counter % 32]

    # Дополнительный паддинг для очень коротких сообщений (<20 байт)
    boost = PAD_BOOST_SHORT if plaintext_len < 20 else 0

    if prev_padding == 0:
        # Первое сообщение в диалоге (или после длинного)
        padding = PAD_MIN + (key_byte % PAD_RANGE) + boost
    else:
        # Пинг-понг: новый паддинг зависит от предыдущего
        padding = (prev_padding + key_byte) % PAD_RANGE + PAD_MIN + boost

    return min(padding, PAD_MAX_LONG)


def add_padding(data: bytes, target_size: int) -> bytes:
    """
    Добавляет случайный паддинг до target_size.

    Args:
        data: исходные данные
        target_size: целевой размер после добавления паддинга

    Returns:
        данные с добавленным случайным паддингом
    """
    if len(data) >= target_size:
        return data
    padding_length = target_size - len(data)
    padding = secrets.token_bytes(padding_length)
    return data + padding


def remove_padding(data: bytes, original_size: int) -> bytes:
    """
    Удаляет паддинг, возвращая данные исходного размера.

    Args:
        data: данные с паддингом
        original_size: исходный размер до добавления паддинга

    Returns:
        данные без паддинга
    """
    return data[:original_size]


def extract_counter_from_message_id(message_id: str) -> int:
    """
    Извлекает счётчик из message_id.

    Формат: msg_{counter:04x}_{random}
    Пример: msg_0001_a8f3e1b7c9d2 → counter = 1

    Args:
        message_id: ID сообщения

    Returns:
        счётчик (0 если не удалось извлечь)
    """
    try:
        # Формат: msg_XXXX_...
        parts = message_id.split('_')
        if len(parts) >= 2:
            # Вторая часть после msg_ — это счётчик в hex
            return int(parts[1], 16)
    except (ValueError, IndexError):
        pass
    return 0


def generate_message_id_with_counter(counter: int) -> str:
    """
    Генерирует message_id со встроенным счётчиком.

    Формат: msg_{counter:04x}_{random}
    Пример: msg_0001_a8f3e1b7c9d2

    Args:
        counter: счётчик сообщения (0-65535)

    Returns:
        message_id
    """
    random_part = secrets.token_hex(6)  # 12 hex-символов
    return f"msg_{counter:04x}_{random_part}"
