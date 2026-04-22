# src/server/network/trust/violations.py
"""
Константы типов нарушений.

Импортирует все константы из централизованного config.py
"""

# Исправляем импорт: config на уровень src, а не src.server
from src.config import (
    VIOLATION_TYPE_INVALID_SIGNATURE,
    VIOLATION_TYPE_INVALID_FORMAT,
    VIOLATION_TYPE_RATE_LIMIT,
    VIOLATION_TYPE_SPAM,
)

__all__ = [
    "VIOLATION_TYPE_INVALID_SIGNATURE",
    "VIOLATION_TYPE_INVALID_FORMAT",
    "VIOLATION_TYPE_RATE_LIMIT",
    "VIOLATION_TYPE_SPAM",
]
