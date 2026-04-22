# src/client/screens/base.py
"""
Базовые классы для экранов TUI.
"""

from textual.screen import Screen
from textual.widgets import Footer, Header


class BaseScreen(Screen):
    """
    Базовый экран с общими настройками.
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def compose(self):
        yield Header()
        yield Footer()

    def action_quit(self) -> None:
        """Выход из приложения."""
        self.app.exit()

    def action_back(self) -> None:
        """Возврат на предыдущий экран."""
        self.app.pop_screen()
