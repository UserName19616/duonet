"""
Модуль ECDH (X25519) для безопасного обмена ключами.
Используется в протоколе ротации ключей V2.
"""

import secrets
from typing import Tuple, Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def generate_ecdh_keypair() -> Tuple[bytes, bytes]:
    """
    Генерация эфемерной ключевой пары X25519.

    Returns:
        Tuple[bytes, bytes]: (private_key, public_key) по 32 байта каждый
    """
    private_key = X25519PrivateKey.generate()
    private_bytes = private_key.private_bytes_raw()
    public_bytes = private_key.public_key().public_bytes_raw()
    return private_bytes, public_bytes


def private_key_from_bytes(private_bytes: bytes) -> X25519PrivateKey:
    """
    Восстановление приватного ключа из байт.

    Args:
        private_bytes: 32 байта приватного ключа

    Returns:
        X25519PrivateKey
    """
    return X25519PrivateKey.from_private_bytes(private_bytes)


def public_key_from_bytes(public_bytes: bytes) -> X25519PublicKey:
    """
    Восстановление публичного ключа из байт.

    Args:
        public_bytes: 32 байта публичного ключа

    Returns:
        X25519PublicKey
    """
    return X25519PublicKey.from_public_bytes(public_bytes)


def compute_shared_secret(private_bytes: bytes, public_bytes: bytes) -> bytes:
    """
    Вычисление общего секрета по схеме ECDH.

    Args:
        private_bytes: 32 байта приватного ключа (своя сторона)
        public_bytes: 32 байта публичного ключа (собеседника)

    Returns:
        32-байтовый общий секрет
    """
    private_key = private_key_from_bytes(private_bytes)
    public_key = public_key_from_bytes(public_bytes)
    return private_key.exchange(public_key)


def derive_new_key(
    shared_secret: bytes,
    dialog_id: str,
    salt: Optional[bytes] = None,
) -> bytes:
    """
    Получение 32-байтового ключа шифрования из общего секрета ECDH.

    Используется HKDF (RFC 5869) для детерминированного получения ключа.

    Args:
        shared_secret: 32-байтовый общий секрет от ECDH
        dialog_id: ID диалога (используется как info)
        salt: Соль (опционально, по умолчанию dialog_id)

    Returns:
        32-байтовый ключ для AES-256-GCM
    """
    if salt is None:
        salt = dialog_id.encode()

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=f"duonet_rotation_v2:{dialog_id}".encode(),
    )
    return hkdf.derive(shared_secret)


def generate_request_id() -> str:
    """
    Генерация уникального ID для запроса ротации.

    Returns:
        Строка вида "req_{16_hex_chars}"
    """
    return f"req_{secrets.token_hex(8)}"
