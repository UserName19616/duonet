# src/client/screens/search.py
"""
Экран поиска контактов.
"""

from textual.containers import Vertical
from textual.widgets import Button, Input, Static

from .base import BaseScreen


class SearchScreen(BaseScreen):
    """Экран поиска контактов."""

    def compose(self):
        yield Vertical(
            Static("Поиск контакта:", id="label"),
            Input(placeholder="@Public-ID", id="search-input"),
            Button("Найти", id="search", variant="primary"),
            Button("Назад", id="back", variant="default"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "search":
            self.app.show_warning("Поиск пока не реализован в прототипе")
