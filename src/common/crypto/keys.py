"""
Модуль C0.1: Базовые криптографические операции.

Обеспечивает генерацию ключевых пар Ed25519, подпись и верификацию сообщений,
а также вычисление SHA256 хешей. Является фундаментом для всех криптографических
операций в прототипе.
"""

import hashlib
import secrets
from typing import Tuple

from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError


def generate_keypair() -> Tuple[bytes, bytes]:
    """
    Генерирует новую случайную ключевую пару Ed25519.

    Returns:
        Tuple[bytes, bytes]: Кортеж из двух элементов:
            - private_key: 32-байтовый приватный ключ.
            - public_key: 32-байтовый публичный ключ.

    Example:
        >>> priv, pub = generate_keypair()
        >>> len(priv)
        32
        >>> len(pub)
        32
    """
    signing_key = SigningKey.generate()
    private_key = bytes(signing_key)
    public_key = bytes(signing_key.verify_key)
    return private_key, public_key


def generate_keypair_from_seed(seed: bytes) -> Tuple[bytes, bytes]:
    """
    Детерминированно генерирует ключевую пару Ed25519 из 32-байтового seed.

    Args:
        seed: 32-байтовый seed (например, хеш сид-фразы).

    Returns:
        Tuple[bytes, bytes]: Кортеж (private_key, public_key), где каждый ключ - 32 байта.

    Raises:
        ValueError: Если длина seed не равна 32 байтам.
    """
    if len(seed) != 32:
        raise ValueError(f"Seed must be 32 bytes, got {len(seed)}")
    signing_key = SigningKey(seed)
    private_key = bytes(signing_key)
    public_key = bytes(signing_key.verify_key)
    return private_key, public_key


def sign(private_key: bytes, message: bytes) -> bytes:
    """
    Создает подпись для сообщения с использованием приватного ключа.

    Args:
        private_key: 32-байтовый приватный ключ.
        message: Сообщение для подписи.

    Returns:
        bytes: 64-байтовая подпись.

    Raises:
        ValueError: Если private_key не является 32-байтовым (косвенная проверка через PyNaCl).
    """
    signing_key = SigningKey(private_key)
    signed = signing_key.sign(message)
    # signed.signature содержит 64-байтовую подпись
    return bytes(signed.signature)


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """
    Проверяет подпись сообщения с использованием публичного ключа.

    Args:
        public_key: 32-байтовый публичный ключ.
        signature: 64-байтовая подпись.
        message: Исходное сообщение.

    Returns:
        bool: True, если подпись верна, False в противном случае.

    Raises:
        ValueError: Если public_key не является 32-байтовым (косвенная проверка через PyNaCl).
    """
    try:
        # Проверяем длину подписи перед вызовом verify
        if len(signature) != 64:
            return False

        verify_key = VerifyKey(public_key)
        verify_key.verify(message, signature)
        return True
    except (BadSignatureError, ValueError):
        # ValueError может возникнуть при неверной длине подписи
        return False


def hash_sha256(data: bytes) -> bytes:
    """
    Вычисляет SHA256 хеш от данных.

    Args:
        data: Произвольные байтовые данные.

    Returns:
        bytes: 32-байтовый хеш.
    """
    return hashlib.sha256(data).digest()
