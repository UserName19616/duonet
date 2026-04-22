# src/client/screens/warning.py
"""
Экран отображения предупреждений/ошибок.
"""

from textual.containers import Vertical
from textual.widgets import Button, Static

from .base import BaseScreen


class WarningScreen(BaseScreen):
    """Экран отображения предупреждений/ошибок."""

    def __init__(self, message: str, title: str = "⚠️ ПРЕДУПРЕЖДЕНИЕ"):
        super().__init__()
        self.message = message
        self.title = title

    def compose(self):
        yield Vertical(
            Static(self.title, id="title"),
            Static(self.message, id="message"),
            Button("OK", id="ok", variant="primary"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.app.pop_screen()
