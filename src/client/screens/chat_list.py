# src/client/screens/chat_list.py
"""
Экран списка диалогов.
"""

from textual.containers import Vertical
from textual.widgets import Button, ListItem, ListView, Static

from .base import BaseScreen


class ChatListScreen(BaseScreen):
    """Экран списка диалогов."""

    def compose(self):
        yield Vertical(
            Static(f"Ваши диалоги (аккаунт: {self.app.public_id})", id="label"),
            Vertical(
                Static("🚧 РАЗДЕЛ В РАЗРАБОТКЕ 🚧", id="dev-message"),
                Static("Функционал списка диалогов временно недоступен.", id="dev-info"),
                Static("Пожалуйста, используйте веб-интерфейс для обмена сообщениями.", id="dev-hint"),
                id="dev-container",
            ),
            Button("🔍 Поиск", id="search", variant="default"),
            Button("📨 Приглашения", id="invites", variant="primary"),
            Button("Выход", id="quit", variant="error"),
        )

    def on_mount(self) -> None:
        pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.logout()
        elif event.button.id == "search":
            self.app.push_screen("SearchScreen")
        elif event.button.id == "invites":
            self.app.push_screen("InvitesScreen")

    async def load_dialogs(self) -> None:
        """Загрузка списка диалогов (заглушка, будет реализовано позже)."""
        pass
