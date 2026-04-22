"""
Модуль C0.2: AES-256-GCM шифрование.

Обеспечивает генерацию сессионных ключей, шифрование и расшифровку сообщений
с использованием AES-256-GCM. Используется для защиты содержимого сообщений.
"""

import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_session_key() -> bytes:
    """
    Генерирует случайный сессионный ключ для AES-256-GCM.

    Returns:
        bytes: 32-байтовый ключ (AES-256).

    Example:
        >>> key = generate_session_key()
        >>> len(key)
        32
    """
    return secrets.token_bytes(32)


def encrypt(plaintext: str, key: bytes) -> bytes:
    """
    Шифрует сообщение с использованием AES-256-GCM.

    Формат выходных данных:
        nonce (12 байт) + ciphertext (включает tag 16 байт)

    Args:
        plaintext: Текст сообщения (строка).
        key: 32-байтовый ключ шифрования.

    Returns:
        bytes: Зашифрованные данные (nonce + ciphertext).

    Raises:
        ValueError: Если длина key не равна 32 байтам.

    Example:
        >>> key = generate_session_key()
        >>> ciphertext = encrypt("Hello, World!", key)
        >>> len(ciphertext) > 12
        True
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")

    # Генерируем случайный nonce (12 байт - стандарт для AES-GCM)
    nonce = secrets.token_bytes(12)

    # Создаем экземпляр AESGCM
    aesgcm = AESGCM(key)

    # Шифруем данные (AESGCM автоматически добавляет tag)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

    # Возвращаем nonce + ciphertext
    return nonce + ciphertext


def decrypt(ciphertext: bytes, key: bytes) -> Optional[str]:
    """
    Расшифровывает сообщение, зашифрованное функцией encrypt().

    Args:
        ciphertext: Зашифрованные данные (nonce 12 байт + ciphertext).
        key: 32-байтовый ключ шифрования.

    Returns:
        Optional[str]: Расшифрованный текст или None при ошибке.

    Raises:
        ValueError: Если длина key не равна 32 байтам.

    Example:
        >>> key = generate_session_key()
        >>> ciphertext = encrypt("Secret", key)
        >>> decrypted = decrypt(ciphertext, key)
        >>> decrypted == "Secret"
        True
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")

    # Проверяем минимальную длину (nonce 12 байт)
    if len(ciphertext) < 12:
        return None

    # Извлекаем nonce (первые 12 байт)
    nonce = ciphertext[:12]
    encrypted_data = ciphertext[12:]

    try:
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, encrypted_data, None)
        return decrypted.decode('utf-8')
    except Exception:
        # Любая ошибка расшифровки (неверный ключ, поврежденные данные)
        return None
