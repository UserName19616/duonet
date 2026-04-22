# src/client/crypto/directional.py
"""
Направленное шифрование для диалогов.

Ключ шифрования зависит от направления сообщения:
- A → B: key = session_key ⊕ hash(A+B)
- B → A: key = session_key ⊕ hash(B+A)

Это обеспечивает дополнительную защиту от replay-атак и подмены отправителя.
"""

from typing import Optional, Tuple

from .aes import encrypt as aes_encrypt, decrypt as aes_decrypt
from .phrase import encrypt_with_phrase, decrypt_with_phrase
from src.common.crypto.padding import calculate_padding_size, add_padding, remove_padding
from .common import get_directional_key


def encrypt_directional(
    plaintext: str,
    session_key: bytes,
    from_id: str,
    to_id: str,
    phrase: Optional[str] = None,
) -> bytes:
    """
    Шифрование сообщения с учётом направления.

    Args:
        plaintext: Текст сообщения
        session_key: 32-байтовый сессионный ключ
        from_id: Public ID отправителя
        to_id: Public ID получателя
        phrase: Дополнительная фраза (опционально)

    Returns:
        Зашифрованные данные
    """
    directional_key = get_directional_key(session_key, from_id, to_id)

    if phrase:
        return encrypt_with_phrase(plaintext, directional_key, phrase)
    else:
        return aes_encrypt(plaintext, directional_key)


def decrypt_directional(
    ciphertext: bytes,
    session_key: bytes,
    from_id: str,
    to_id: str,
    phrase: Optional[str] = None,
) -> Optional[str]:
    """
    Расшифровка сообщения с учётом направления.

    Args:
        ciphertext: Зашифрованные данные
        session_key: 32-байтовый сессионный ключ
        from_id: Public ID отправителя
        to_id: Public ID получателя
        phrase: Дополнительная фраза (опционально)

    Returns:
        Расшифрованный текст или None
    """
    directional_key = get_directional_key(session_key, from_id, to_id)

    if phrase:
        return decrypt_with_phrase(ciphertext, directional_key, phrase)
    else:
        return aes_decrypt(ciphertext, directional_key)


def encrypt_directional_with_padding(
    plaintext: str,
    session_key: bytes,
    from_id: str,
    to_id: str,
    message_counter: int,
    prev_padding: int = 0,
    phrase: Optional[str] = None,
) -> Tuple[bytes, int]:
    """
    Шифрование сообщения с учётом направления и адаптивным паддингом.

    Args:
        plaintext: Текст сообщения
        session_key: 32-байтовый сессионный ключ
        from_id: Public ID отправителя
        to_id: Public ID получателя
        message_counter: Порядковый номер сообщения в диалоге
        prev_padding: Размер паддинга предыдущего сообщения
        phrase: Дополнительная фраза (опционально)

    Returns:
        Tuple[bytes, int]: (Зашифрованные данные с паддингом, размер паддинга)
    """
    plaintext_bytes = plaintext.encode('utf-8')

    # Вычисляем размер паддинга
    padding_size = calculate_padding_size(
        session_key=session_key,
        from_id=from_id,
        to_id=to_id,
        message_counter=message_counter,
        plaintext_len=len(plaintext_bytes),
        prev_padding=prev_padding,
    )

    # Шифруем
    encrypted = encrypt_directional(plaintext, session_key, from_id, to_id, phrase)

    # Добавляем паддинг
    if padding_size > 0:
        encrypted = add_padding(encrypted, len(encrypted) + padding_size)

    return encrypted, padding_size


def decrypt_directional_with_padding(
    ciphertext: bytes,
    session_key: bytes,
    from_id: str,
    to_id: str,
    original_size: int,
    phrase: Optional[str] = None,
) -> Optional[str]:
    """
    Расшифровка сообщения с учётом направления и удалением паддинга.

    Args:
        ciphertext: Зашифрованные данные (могут содержать паддинг)
        session_key: 32-байтовый сессионный ключ
        from_id: Public ID отправителя
        to_id: Public ID получателя
        original_size: Исходный размер зашифрованных данных без паддинга
        phrase: Дополнительная фраза (опционально)

    Returns:
        Расшифрованный текст или None
    """
    # Удаляем паддинг
    if len(ciphertext) > original_size:
        ciphertext = remove_padding(ciphertext, original_size)

    return decrypt_directional(ciphertext, session_key, from_id, to_id, phrase)
