# src/messaging/crypto_logger.py
"""
Логирование событий шифрования для визуализации.
Вынесено в отдельный модуль для избежания циркулярных импортов.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Глобальное хранилище логов (in-memory)
_crypto_logs: Dict[str, List[Dict[str, Any]]] = {}  # user_id -> list of logs
_crypto_log_ws_connections: Dict[str, Dict[str, Any]] = {}  # user_id -> {contact_id -> websocket}
_max_log_size = 100


async def log_crypto_event(
    user_id: str,
    contact_id: str,
    message_id: str,
    direction: str,
    encrypted_data: bytes,
    file_info: Optional[dict] = None,
) -> None:
    """
    Логирование события шифрования.

    Args:
        user_id: ID пользователя
        contact_id: ID контакта
        message_id: ID сообщения
        direction: "outgoing" или "incoming"
        encrypted_data: Зашифрованные данные
        file_info: Информация о файле (если есть)
    """
    # Разбиваем на пакеты (если данные большие)
    packet_size = 65536
    data_bytes = encrypted_data if isinstance(encrypted_data, bytes) else encrypted_data.encode()
    total_packets = (len(data_bytes) + packet_size - 1) // packet_size

    packets = []
    for i in range(total_packets):
        start = i * packet_size
        end = min(start + packet_size, len(data_bytes))
        packet_data = data_bytes[start:end]
        packets.append({
            "seq": i + 1,
            "total": total_packets,
            "encrypted_preview": packet_data[:12].hex() + "..." if len(packet_data) > 12 else packet_data.hex(),
            "size": len(packet_data),
        })

    log_entry = {
        "message_id": message_id,
        "contact_id": contact_id,
        "direction": direction,
        "packets": packets,
        "file_info": file_info,
        "timestamp": int(time.time()),
    }

    # Сохраняем в буфер
    if user_id not in _crypto_logs:
        _crypto_logs[user_id] = []
    _crypto_logs[user_id].insert(0, log_entry)
    if len(_crypto_logs[user_id]) > _max_log_size:
        _crypto_logs[user_id].pop()

    # Отправляем через WebSocket если есть подключение
    if user_id in _crypto_log_ws_connections and contact_id in _crypto_log_ws_connections[user_id]:
        try:
            ws = _crypto_log_ws_connections[user_id][contact_id]
            await ws.send_json({
                "type": "crypto_log",
                "data": log_entry,
            })
        except Exception as e:
            logger.error(f"Failed to send crypto log via WS: {e}")


def get_crypto_logs(user_id: str, contact_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """Получение логов пользователя."""
    logs = _crypto_logs.get(user_id, [])
    if contact_id:
        logs = [log for log in logs if log.get("contact_id") == contact_id]
    return logs[:limit]


def clear_crypto_logs(user_id: str) -> None:
    """Очистка логов пользователя."""
    if user_id in _crypto_logs:
        _crypto_logs[user_id].clear()


def register_crypto_log_ws(user_id: str, contact_id: str, websocket) -> None:
    """Регистрация WebSocket соединения для логов."""
    if user_id not in _crypto_log_ws_connections:
        _crypto_log_ws_connections[user_id] = {}
    _crypto_log_ws_connections[user_id][contact_id] = websocket


def unregister_crypto_log_ws(user_id: str, contact_id: str) -> None:
    """Удаление WebSocket соединения."""
    if user_id in _crypto_log_ws_connections:
        _crypto_log_ws_connections[user_id].pop(contact_id, None)
        if not _crypto_log_ws_connections[user_id]:
            del _crypto_log_ws_connections[user_id]
