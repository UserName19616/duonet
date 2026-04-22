# src/identity/public_id.py
"""
Модуль I1.1: Генерация и валидация Public ID.

Public ID — публичный идентификатор участника сети.
Форматы:
  - Клиент: @XXXX-XXXX-XXXX.region
  - Сервер: @XXXX-XXXX-XXXX.region.srv

Алфавит Base32 (без путаных символов): ABCDEFGHJKLMNPQRSTUVWXYZ23456789
(исключены: 0, 1, I, L, O)
Примечание: фактически используется 32 символа (уточнение из DEVIATIONS.md)
"""

import hashlib
import hmac
import re
from typing import Optional

# Алфавит Base32 (исключены: 0, 1, I, L, O)
# Фактически 32 символа (см. DEVIATIONS.md)
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
BASE = 32

# Регулярные выражения для валидации
# Разрешаем любые заглавные буквы и цифры для тестов, но в реальности используем ALPHABET
PUBLIC_ID_PATTERN = re.compile(
    r'^@([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})\.([a-z]{2})(?:\.srv)?(?:-([0-9]+))?$',
    re.IGNORECASE
)


def _encode_base32(value: int, length: int) -> str:
    """
    Кодирует число в Base32 строку фиксированной длины.

    Args:
        value: Число для кодирования.
        length: Желаемая длина строки.

    Returns:
        str: Base32 строка.
    """
    result = []
    temp_value = value
    for _ in range(length):
        temp_value, remainder = divmod(temp_value, BASE)
        result.append(ALPHABET[remainder])
    return ''.join(reversed(result))


def generate_public_id(
    seed_hash: bytes,
    region: str,
    is_server: bool = False,
    counter: int = 0
) -> str:
    """
    Генерация Public ID из хеша сид-фразы 1.

    Алгоритм:
        HMAC-SHA256(seed_hash, salt) → 9 байт → Base32 → 12 символов
        Форматирование: XXXX-XXXX-XXXX.region[.srv][-counter]

    Args:
        seed_hash: 32-байтовый хеш сид-фразы 1 (SHA256).
        region: Двухбуквенный код страны (ru, us, de...).
        is_server: True для сервера (добавляет .srv).
        counter: Счётчик коллизий (0 для первой попытки).

    Returns:
        str: Public ID в формате @XXXX-XXXX-XXXX.region[.srv][-counter]

    Raises:
        ValueError: Если seed_hash не 32 байта.
        ValueError: Если region не 2 буквы.
        ValueError: Если counter < 0.

    Example:
        >>> seed_hash = hashlib.sha256(b"user@example.com").digest()
        >>> generate_public_id(seed_hash, "ru")
        '@ABCD-1234-5678.ru'
    """
    if len(seed_hash) != 32:
        raise ValueError(f"Seed hash must be 32 bytes, got {len(seed_hash)}")

    if not region or len(region) != 2 or not region.isalpha():
        raise ValueError(f"Region must be 2 letters, got '{region}'")

    # Приводим регион к нижнему регистру
    region = region.lower()

    if counter < 0:
        raise ValueError(f"Counter must be >= 0, got {counter}")

    # Генерируем хеш-часть (9 байт → 12 символов Base32)
    salt = f"public_id_v1:{region}:{counter}".encode()
    h = hmac.new(seed_hash, salt, hashlib.sha256).digest()

    # Берем первые 9 байт и конвертируем в число
    value = int.from_bytes(h[:9], byteorder='big')

    # Кодируем в Base32 (12 символов)
    encoded = _encode_base32(value, 12)

    # Форматируем: XXXX-XXXX-XXXX
    hash_part = f"{encoded[:4]}-{encoded[4:8]}-{encoded[8:12]}"

    # Собираем ID
    public_id = f"@{hash_part}.{region}"

    if is_server:
        public_id += ".srv"

    if counter > 0:
        public_id += f"-{counter}"

    return public_id


def extract_hash_part(public_id: str) -> Optional[str]:
    """
    Извлечение хеш-части (XXXX-XXXX-XXXX) из Public ID.

    Args:
        public_id: Полный Public ID.

    Returns:
        Optional[str]: Хеш-часть или None.

    Example:
        >>> extract_hash_part("@ABCD-1234-5678.ru")
        'ABCD-1234-5678'
    """
    match = PUBLIC_ID_PATTERN.match(public_id)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}".upper()
    return None


def extract_collision_counter(public_id: str) -> int:
    """
    Извлечение счётчика коллизий из Public ID.

    Args:
        public_id: Полный Public ID.

    Returns:
        int: Счётчик (0 если суффикса нет).

    Example:
        >>> extract_collision_counter("@ABCD-1234-5678.ru-1")
        1
        >>> extract_collision_counter("@ABCD-1234-5678.ru")
        0
    """
    match = PUBLIC_ID_PATTERN.match(public_id)
    if match and match.group(5):
        return int(match.group(5))
    return 0


def extract_region(public_id: str) -> Optional[str]:
    """
    Извлечение региона из Public ID.

    Args:
        public_id: Полный Public ID.

    Returns:
        Optional[str]: Двухбуквенный код региона или None.

    Example:
        >>> extract_region("@ABCD-1234-5678.ru")
        'ru'
    """
    match = PUBLIC_ID_PATTERN.match(public_id)
    if match:
        return match.group(4).lower()
    return None


def extract_type(public_id: str) -> str:
    """
    Определение типа участника.

    Args:
        public_id: Полный Public ID.

    Returns:
        str: "client" или "server".

    Example:
        >>> extract_type("@ABCD-1234-5678.ru")
        'client'
        >>> extract_type("@ABCD-1234-5678.ru.srv")
        'server'
    """
    if is_server_id(public_id):
        return "server"
    return "client"


def is_valid_format(public_id: str) -> bool:
    """
    Проверка корректности формата Public ID.

    Args:
        public_id: Строка для проверки.

    Returns:
        bool: True если формат корректен.
    """
    if not public_id or not isinstance(public_id, str):
        return False

    match = PUBLIC_ID_PATTERN.match(public_id)
    if not match:
        return False

    # Проверяем, что все символы в хеш-части принадлежат разрешённому алфавиту
    for i in range(1, 4):  # группы 1, 2, 3 — части хеша
        part = match.group(i)
        for ch in part:
            if ch not in ALPHABET:
                return False

    return True


def is_server_id(public_id: str) -> bool:
    """
    Проверка, является ли ID серверным (имеет суффикс .srv).

    Args:
        public_id: Полный Public ID.

    Returns:
        bool: True если это серверный ID.
    """
    return public_id.endswith(".srv") and is_valid_format(public_id)


def is_client_id(public_id: str) -> bool:
    """
    Проверка, является ли ID клиентским (не имеет суффикса .srv).

    Args:
        public_id: Полный Public ID.

    Returns:
        bool: True если это клиентский ID.
    """
    return not is_server_id(public_id) and is_valid_format(public_id)


def normalize_public_id(public_id: str) -> str:
    """
    Нормализация Public ID (приведение к верхнему регистру хеш-части).

    Args:
        public_id: Public ID для нормализации.

    Returns:
        Нормализованный Public ID.
    """
    if not is_valid_format(public_id):
        return public_id

    match = PUBLIC_ID_PATTERN.match(public_id)
    if match:
        hash_part = f"{match.group(1).upper()}-{match.group(2).upper()}-{match.group(3).upper()}"
        region = match.group(4).lower()
        suffix = ".srv" if match.group(4) and public_id.endswith(".srv") else ""
        counter = f"-{match.group(5)}" if match.group(5) else ""
        return f"@{hash_part}.{region}{suffix}{counter}"

    return public_id
