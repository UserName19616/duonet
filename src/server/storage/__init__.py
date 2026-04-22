"""Серверное хранилище."""
from .server_db import ServerDatabase, get_server_db, set_server_db

__all__ = ["ServerDatabase", "get_server_db", "set_server_db"]
