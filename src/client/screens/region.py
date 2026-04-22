# src/client/screens/region.py
"""
Экран выбора региона.
"""

from typing import Optional

from textual.containers import Vertical
from textual.widgets import Button, Static

from .base import BaseScreen


class RegionSelectionScreen(BaseScreen):
    """Экран выбора региона."""

    def __init__(self, detected_region: Optional[str] = None):
        super().__init__()
        self.detected_region = detected_region

    def compose(self):
        regions = [
            ("ru", "🇷🇺 Россия"),
            ("us", "🇺🇸 США"),
            ("gb", "🇬🇧 Великобритания"),
            ("de", "🇩🇪 Германия"),
            ("fr", "🇫🇷 Франция"),
            ("jp", "🇯🇵 Япония"),
            ("cn", "🇨🇳 Китай"),
            ("br", "🇧🇷 Бразилия"),
        ]

        if self.detected_region and self.detected_region != "local":
            detected_name = dict(regions).get(self.detected_region, self.detected_region.upper())
            description = f"🌍 Определён регион: {detected_name}\n\nЕсли это не ваш регион, выберите другой:"
        else:
            description = "🌍 Выберите ваш регион для генерации Public ID:\n\nРегион влияет на первую часть вашего ID и не может быть изменён позже."

        region_buttons = []
        for code, name in regions:
            button = Button(name, id=f"region-{code}", variant="default")
            if self.detected_region == code:
                button.variant = "primary"
            region_buttons.append(button)

        yield Vertical(
            Static(description, id="description"),
            *region_buttons,
            Button("Продолжить", id="continue", variant="success", disabled=True),
            Button("Назад", id="back", variant="default"),
            id="region-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "back":
            self.app.pop_screen()
        elif button_id == "continue":
            for button in self.query(Button):
                if button.id and button.id.startswith("region-") and button.variant == "primary":
                    selected_region = button.id.replace("region-", "")
                    self.app.selected_region = selected_region
                    self.app.push_screen("SeedInputScreen", is_restore=False, is_client=False)
                    return
        elif button_id and button_id.startswith("region-"):
            for button in self.query(Button):
                if button.id and button.id.startswith("region-"):
                    button.variant = "default"
            event.button.variant = "primary"
            self.query_one("#continue", Button).disabled = False
