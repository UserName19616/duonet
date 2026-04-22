"""
Модуль C0.3: Дополнительная фраза (Double Key).

Обеспечивает второй уровень защиты для отдельных чатов через дополнительную фразу.
Включает получение ключа из фразы (PBKDF2), комбинирование ключей (XOR),
шифрование и расшифровку с дополнительной фразой.
"""

import secrets
from typing import Optional

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .aes import encrypt as aes_encrypt, decrypt as aes_decrypt


def derive_phrase_key(phrase: str, salt: bytes) -> bytes:
    """
    Получение 32-байтового ключа из дополнительной фразы с использованием PBKDF2.

    Args:
        phrase: Дополнительная фраза.
        salt: Соль (16 байт).

    Returns:
        bytes: 32-байтовый ключ.

    Example:
        >>> salt = secrets.token_bytes(16)
        >>> key = derive_phrase_key("зеленый дом", salt)
        >>> len(key)
        32
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(phrase.encode('utf-8'))


def xor_keys(key1: bytes, key2: bytes) -> bytes:
    """
    Побайтовый XOR двух ключей одинаковой длины.

    Args:
        key1: Первый ключ.
        key2: Второй ключ.

    Returns:
        bytes: Результат XOR.

    Raises:
        ValueError: Если длины ключей не совпадают.

    Example:
        >>> key1 = b'\\x01' * 32
        >>> key2 = b'\\x02' * 32
        >>> result = xor_keys(key1, key2)
        >>> result == b'\\x03' * 32
        True
    """
    if len(key1) != len(key2):
        raise ValueError(f"Key lengths must match: {len(key1)} != {len(key2)}")
    return bytes(a ^ b for a, b in zip(key1, key2))


def encrypt_with_phrase(plaintext: str, session_key: bytes, phrase: str) -> bytes:
    """
    Шифрование сообщения с дополнительной фразой.

    Формат выходных данных:
        salt (16 байт) + nonce (12 байт) + ciphertext (включает tag 16 байт)

    Args:
        plaintext: Текст сообщения.
        session_key: 32-байтовый сессионный ключ.
        phrase: Дополнительная фраза.

    Returns:
        bytes: Зашифрованные данные (salt + nonce + ciphertext).

    Raises:
        ValueError: Если длина session_key не равна 32 байтам.

    Example:
        >>> session_key = generate_session_key()
        >>> ciphertext = encrypt_with_phrase("Secret", session_key, "мой секрет")
        >>> len(ciphertext) > 28
        True
    """
    if len(session_key) != 32:
        raise ValueError(f"Session key must be 32 bytes, got {len(session_key)}")

    # Генерируем случайную соль (16 байт)
    salt = secrets.token_bytes(16)

    # Получаем ключ из фразы
    phrase_key = derive_phrase_key(phrase, salt)

    # Комбинируем ключи
    combined_key = xor_keys(session_key, phrase_key)

    # Шифруем с комбинированным ключом
    # Используем AES-GCM с nonce 12 байт
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(combined_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

    # Возвращаем salt + nonce + ciphertext
    return salt + nonce + ciphertext


def decrypt_with_phrase(ciphertext: bytes, session_key: bytes, phrase: str) -> Optional[str]:
    """
    Расшифровка сообщения, зашифрованного с дополнительной фразой.

    Args:
        ciphertext: Зашифрованные данные (salt 16 байт + nonce 12 байт + ciphertext).
        session_key: 32-байтовый сессионный ключ.
        phrase: Дополнительная фраза.

    Returns:
        Optional[str]: Расшифрованный текст или None при ошибке.

    Raises:
        ValueError: Если длина session_key не равна 32 байтам.

    Example:
        >>> session_key = generate_session_key()
        >>> ciphertext = encrypt_with_phrase("Secret", session_key, "мой секрет")
        >>> decrypted = decrypt_with_phrase(ciphertext, session_key, "мой секрет")
        >>> decrypted == "Secret"
        True
    """
    if len(session_key) != 32:
        raise ValueError(f"Session key must be 32 bytes, got {len(session_key)}")

    # Проверяем минимальную длину (salt 16 + nonce 12 = 28 байт)
    if len(ciphertext) < 28:
        return None

    # Извлекаем salt (первые 16 байт)
    salt = ciphertext[:16]
    nonce = ciphertext[16:28]
    encrypted_data = ciphertext[28:]

    try:
        # Получаем ключ из фразы
        phrase_key = derive_phrase_key(phrase, salt)

        # Комбинируем ключи
        combined_key = xor_keys(session_key, phrase_key)

        # Расшифровываем
        aesgcm = AESGCM(combined_key)
        decrypted = aesgcm.decrypt(nonce, encrypted_data, None)
        return decrypted.decode('utf-8')
    except Exception:
        # Любая ошибка расшифровки (неверная фраза, поврежденные данные)
        return None
