# src/client/__init__.py
"""DuoNet Client Module - обмен сообщениями, TUI."""

# Экспортируем ClientCrypto для удобства
from .client_crypto import ClientCrypto

__all__ = ["ClientCrypto"]
