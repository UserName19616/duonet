# src/client/screens/registration.py
"""
Экраны регистрации и отображения ID.
"""

from typing import Optional

from textual.containers import Vertical
from textual.widgets import Button, Static

from .base import BaseScreen


class RegistrationScreen(BaseScreen):
    """Экран регистрации (показывает процесс)."""

    def __init__(self, seed: str, password: str, region_code: str, is_client: bool = False):
        super().__init__()
        self.seed = seed
        self.password = password
        self.user_region = region_code
        self.is_client = is_client
        self._registered = False

    def compose(self):
        mode_text = "клиентского" if self.is_client else "серверного"
        yield Vertical(
            Static(f"⏳ Регистрация {mode_text} аккаунта в регионе {self.user_region.upper()}...", id="status"),
            Static("Пожалуйста, подождите", id="message"),
        )

    async def on_mount(self) -> None:
        await self._do_register()

    async def _do_register(self) -> None:
        if self._registered:
            return
        self._registered = True

        result = await self.app.api_client.register(
            self.seed, self.password, region=self.user_region, is_server=not self.is_client
        )

        if not result.get("success"):
            error_msg = result.get('error', 'Unknown')
            if error_msg == "max_clients_reached":
                self.app.show_warning(f"Достигнут лимит клиентских аккаунтов (3).")
            elif error_msg == "max_servers_reached":
                self.app.show_warning(f"Серверный аккаунт уже создан (только один).")
            elif error_msg == "account_exists":
                self.app.show_warning(f"Аккаунт с такой сид-фразой уже существует.")
            else:
                self.app.show_warning(f"Ошибка регистрации: {error_msg}")
            self.app.pop_screen()
            return

        # Подписываем Устав
        if self.is_client:
            await self.app.api_client.accept_charter_client(self.seed, "ru")
        else:
            await self.app.api_client.accept_charter(self.seed, "ru")

        # Заменяем текущий экран на экран с ID
        self.app.switch_screen(
            "IdDisplayScreen",
            public_id=result.get("public_id"),
            server_id=result.get("server_id"),
        )


class IdDisplayScreen(BaseScreen):
    """Экран отображения ID после регистрации."""

    def __init__(self, public_id: str, server_id: Optional[str] = None):
        super().__init__()
        self.public_id = public_id
        self.server_id = server_id

    def compose(self):
        content = [
            "✅ Регистрация успешна!",
            "",
            f"📱 Клиент: {self.public_id}",
        ]
        if self.server_id:
            content.append(f"🖥️ Сервер: {self.server_id}")
        content.extend([
            "",
            "⚠️ Сохраните эти данные!",
        ])
        yield Vertical(
            Static("\n".join(content), id="info"),
            Button("Продолжить", id="continue", variant="primary"),
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self.app.pop_screen()
            await self._return_to_account_selection()

    async def _return_to_account_selection(self) -> None:
        import asyncio
        await asyncio.sleep(0.5)
        accounts = await self.app.api_client.get_accounts()
        client_accounts = [acc for acc in accounts if not acc.get("is_server", False)]
        client_count = len(client_accounts)
        MAX_CLIENTS = 3

        while len(self.app.screen_stack) > 1:
            self.app.pop_screen()

        if client_count >= MAX_CLIENTS:
            self.app.push_screen("AccountFullScreen", accounts=accounts)
        else:
            self.app.push_screen("AccountSelectionScreen", accounts=accounts)
