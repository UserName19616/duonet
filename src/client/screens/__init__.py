# src/client/screens/__init__.py
"""
Модуль экранов TUI клиента.
"""

from .base import BaseScreen
from .welcome import WelcomeScreen
from .charter import CharterScreen
from .region import RegionSelectionScreen
from .auth import SeedInputScreen, PasswordInputScreen, PasswordRestoreScreen
from .registration import RegistrationScreen, IdDisplayScreen
from .account import (
    AccountSelectionScreen,
    AccountFullScreen,
    ServerPasswordScreen,
    ServerManagementScreen,
)
from .chat_list import ChatListScreen
from .search import SearchScreen
from .invites import InvitesScreen, InviteActionScreen
from .warning import WarningScreen
from .mode import ModeSelectionScreen

# Примечание: ChatScreen был удалён при рефакторинге.
# Вместо него используется ChatListScreen + веб-интерфейс для чата.
# Если нужен TUI чат, необходимо реализовать ChatScreen заново.

__all__ = [
    "BaseScreen",
    "WelcomeScreen",
    "CharterScreen",
    "RegionSelectionScreen",
    "SeedInputScreen",
    "PasswordInputScreen",
    "PasswordRestoreScreen",
    "RegistrationScreen",
    "IdDisplayScreen",
    "AccountSelectionScreen",
    "AccountFullScreen",
    "ServerPasswordScreen",
    "ServerManagementScreen",
    "ChatListScreen",
    "SearchScreen",
    "InvitesScreen",
    "InviteActionScreen",
    "WarningScreen",
    "ModeSelectionScreen",
]
