# src/crypto/hash.py
"""
Хеширование паролей с использованием bcrypt для безопасного хранения.
Обеспечивает надежное хранение паролей пользователей с солью и адаптивной
сложностью.
"""

import bcrypt


def hash_password(password: str) -> bytes:
    """
    Хеширование пароля с автоматической генерацией соли.

    Args:
        password: Пароль (не может быть пустым).

    Returns:
        bytes — bcrypt хеш (60 байт).

    Raises:
        ValueError: если password пустой.
    """
    if not password:
        raise ValueError("Password cannot be empty")

    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt)


def verify_password(password: str, password_hash: bytes) -> bool:
    """
    Проверка пароля.

    Args:
        password: Пароль для проверки (не может быть пустым).
        password_hash: Сохраненный хеш (не может быть None или пустым).

    Returns:
        bool — True если пароль верен, False иначе.

    Raises:
        ValueError: если password пустой или hash некорректный.
    """
    if not password:
        raise ValueError("Password cannot be empty")

    if not password_hash:
        raise ValueError("Invalid password hash")

    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash)
    except ValueError as e:
        # bcrypt выбрасывает ValueError для некорректного хеша
        raise ValueError("Invalid password hash") from e
