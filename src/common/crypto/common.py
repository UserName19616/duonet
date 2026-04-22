# src/common/crypto/common.py
"""
Общие криптографические функции, используемые несколькими модулями.
(Вынесено отдельно для избежания циклических импортов)
"""

import hashlib


def get_directional_key(session_key: bytes, from_id: str, to_id: str) -> bytes:
    """
    Получение ключа для направления from_id → to_id.

    Args:
        session_key: 32-байтовый сессионный ключ
        from_id: Public ID отправителя
        to_id: Public ID получателя

    Returns:
        32-байтовый ключ для шифрования в данном направлении
    """
    direction_str = f"{from_id}:{to_id}"
    direction_hash = hashlib.sha256(direction_str.encode()).digest()[:32]
    return bytes(a ^ b for a, b in zip(session_key, direction_hash))
