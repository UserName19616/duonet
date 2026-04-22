# src/client/storage/__init__.py
"""Клиентское хранилище."""
from .contacts import ContactsStorage, ContactInfo
from .messages import MessagesStorage, MessageInfo

__all__ = ["ContactsStorage", "ContactInfo", "MessagesStorage", "MessageInfo"]
