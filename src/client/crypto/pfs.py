# src/crypto/pfs.py
"""
Forward Secrecy через KDF-ротацию с подтверждением.
"""

import hmac
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Tuple

# Константы
ROTATE_INTERVAL = 100
CONFIRM_TIMEOUT = 30  # секунд
MAX_RETRIES = 3

# Флаги в сообщении (1 байт)
FLAG_ROTATE = 0x01
FLAG_RESYNC_REQUEST = 0x02
FLAG_RESYNC_RESPONSE = 0x04


@dataclass
class DialogState:
    """Состояние диалога для PFS."""
    contact_id: str
    session_key: bytes           # исходный ключ (не меняется)
    current_key: bytes           # текущий ключ для шифрования
    outgoing_counter: int = 0    # отправлено сообщений
    incoming_counter: int = 0    # получено сообщений
    pending_rotate: bool = False # ожидает подтверждения ротации
    retry_count: int = 0         # количество повторов
    last_message_id: Optional[str] = None  # последнее отправленное сообщение


def rotate_key(current_key: bytes) -> bytes:
    """
    KDF для получения нового ключа.

    Args:
        current_key: текущий 32-байтовый ключ

    Returns:
        32-байтовый новый ключ
    """
    return hmac.new(
        current_key,
        b"duonet_rotate_v1",
        hashlib.sha256
    ).digest()


def attach_flags(ciphertext: bytes, flags: int) -> bytes:
    """
    Добавляет флаги в начало ciphertext.

    Args:
        ciphertext: зашифрованные данные
        flags: 1 байт флагов

    Returns:
        flags + ciphertext
    """
    return bytes([flags]) + ciphertext


def extract_flags(data: bytes) -> Tuple[int, bytes]:
    """
    Извлекает флаги из начала данных.

    Args:
        data: данные с флагами в начале

    Returns:
        (flags, остальные_данные)
    """
    if len(data) < 1:
        return 0, data
    return data[0], data[1:]


def should_rotate(state: DialogState) -> bool:
    """Проверяет, нужно ли выполнить ротацию."""
    return (state.outgoing_counter > 0 and
            state.outgoing_counter % ROTATE_INTERVAL == 0 and
            not state.pending_rotate)


def send_rotate_confirmation(contact_id: str, counter: int) -> dict:
    """
    Формирует сообщение подтверждения ротации.

    Returns:
        dict для WebSocket отправки
    """
    return {
        "type": "rotate_confirm",
        "data": {
            "contact_id": contact_id,
            "counter": counter
        }
    }


def request_resync(contact_id: str, expected_counter: int) -> dict:
    """
    Формирует запрос ресинхронизации.

    Returns:
        dict для WebSocket отправки
    """
    return {
        "type": "resync_request",
        "data": {
            "contact_id": contact_id,
            "expected_counter": expected_counter
        }
    }


def resync_response(contact_id: str, messages: list) -> dict:
    """
    Формирует ответ на ресинхронизацию.

    Args:
        contact_id: ID контакта
        messages: список потерянных сообщений

    Returns:
        dict для WebSocket отправки
    """
    return {
        "type": "resync_response",
        "data": {
            "contact_id": contact_id,
            "messages": messages
        }
    }
