# src/client/screens/charter.py
"""
Экран с Уставом сообщества.
"""

from textual.containers import Vertical, ScrollableContainer
from textual.widgets import Button, Label, Static

from ...common.charter.loader import get_charter_text, get_charter_title
from .base import BaseScreen


class CharterScreen(BaseScreen):
    """Экран с Уставом сообщества."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, lang: str = "ru", for_client: bool = False):
        super().__init__()
        self.lang = lang.lower()[:2]
        if self.lang not in ("ru", "en"):
            self.lang = "ru"
        self.for_client = for_client

    def compose(self):
        try:
            charter_text = get_charter_text(self.lang)
            title = get_charter_title(self.lang)
        except FileNotFoundError:
            charter_text = "Error: Charter file not found"
            title = "Error"

        formatted_text = charter_text.replace("•", "  •").replace("—", "—")

        yield Vertical(
            Label(f"[bold cyan]{title}[/bold cyan]", id="charter-title"),
            ScrollableContainer(
                Static(formatted_text, id="charter-content", markup=False),
                id="charter-scroll",
            ),
            Vertical(
                Button(
                    "✓ Принимаю Устав" if self.lang == "ru" else "✓ I Accept the Charter",
                    id="accept",
                    variant="success",
                ),
                Button(
                    "✗ Не принимаю" if self.lang == "ru" else "✗ I Do Not Accept",
                    id="decline",
                    variant="error",
                ),
                id="charter-buttons",
            ),
            id="charter-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept":
            self.app.charter_accepted(for_client=self.for_client)
        elif event.button.id == "decline":
            self.app.exit()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
