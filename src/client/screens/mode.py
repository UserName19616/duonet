# src/client/screens/mode.py
"""
Экран выбора режима работы (Клиент / Сервер).
"""

from textual.containers import Vertical
from textual.widgets import Button, Static

from .base import BaseScreen


class ModeSelectionScreen(BaseScreen):
    """Экран выбора режима работы."""

    def compose(self):
        yield Vertical(
            Static("Выберите режим работы:", id="label"),
            Button("💬 Клиент — общение в чате", id="client", variant="primary"),
            Button("🔧 Сервер — управление прокси", id="server", variant="default"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "client":
            self.app.push_screen("ChatListScreen")
        elif event.button.id == "server":
            self.app.show_warning("Панель управления прокси будет доступна в следующей версии")
