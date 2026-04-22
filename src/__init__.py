# src/__init__.py
"""
DuoNet - Децентрализованная сеть приватного общения
Версия: 2.0.0
"""

from .config import (
    DuoNetMode,
    CURRENT_MODE,
    CLIENT_DB_PATH,
    SERVER_DB_PATH,
    is_server_mode,
    is_client_mode,
)

__version__ = "2.0.0"
__all__ = [
    "DuoNetMode",
    "CURRENT_MODE",
    "CLIENT_DB_PATH",
    "SERVER_DB_PATH",
    "is_server_mode",
    "is_client_mode",
]
