# src/client/screens/welcome.py
"""
Приветственный экран. Точка входа в приложение.
"""

from textual.containers import Vertical
from textual.widgets import Button, Static

from .base import BaseScreen


class WelcomeScreen(BaseScreen):
    """Приветственный экран."""

    def compose(self):
        yield Vertical(
            Static("# DuoNet Messenger", id="title"),
            Static("Decentralized Secure Communication", id="subtitle"),
            Static("Выберите язык / Select language:", id="lang-label"),
            Vertical(
                Button("🇷🇺 Русский", id="lang-ru", variant="primary"),
                Button("🇬🇧 English", id="lang-en", variant="default"),
                id="lang-buttons",
            ),
            Button("Выйти", id="quit", variant="error"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lang-ru":
            self.app.push_screen("CharterScreen", lang="ru", for_client=False)
        elif event.button.id == "lang-en":
            self.app.push_screen("CharterScreen", lang="en", for_client=False)
        elif event.button.id == "quit":
            self.app.exit()
