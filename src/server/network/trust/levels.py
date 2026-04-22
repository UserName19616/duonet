# src/server/network/trust/levels.py
"""
Константы уровней доверия и лимитов для карантинных серверов.

Импортирует все константы из централизованного config.py
"""

# Исправляем импорт: config на уровень src, а не src.server
from src.config import (
    TRUST_LEVEL_UNKNOWN,
    TRUST_LEVEL_QUARANTINE,
    TRUST_LEVEL_TRUSTED,
    TRUST_LEVEL_PRIVILEGED,
    QUARANTINE_DAYS,
    DAILY_CLIENT_LIMIT,
    HOURLY_GOSSIP_LIMIT,
    HOURLY_INCOMING_LIMIT,
)

__all__ = [
    "TRUST_LEVEL_UNKNOWN",
    "TRUST_LEVEL_QUARANTINE",
    "TRUST_LEVEL_TRUSTED",
    "TRUST_LEVEL_PRIVILEGED",
    "QUARANTINE_DAYS",
    "DAILY_CLIENT_LIMIT",
    "HOURLY_GOSSIP_LIMIT",
    "HOURLY_INCOMING_LIMIT",
]
