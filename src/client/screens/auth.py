# src/client/screens/auth.py
"""
Экраны аутентификации: ввод сид-фразы, пароля, восстановление.
"""

from typing import Optional

from textual.containers import Vertical
from textual.widgets import Button, Input, Static, TextArea

from .base import BaseScreen


class SeedInputScreen(BaseScreen):
    """Экран ввода сид-фразы."""

    def __init__(self, is_restore: bool = False, is_client: bool = False):
        super().__init__()
        self.is_restore = is_restore
        self.is_client = is_client
        self._checking = False

    def compose(self):
        mode_text = "клиентского" if self.is_client else "серверного"
        title = f"Введите сид-фразу для {mode_text} аккаунта:" if not self.is_restore else "Введите сид-фразу для восстановления:"
        yield Vertical(
            Static(title, id="label"),
            TextArea(id="seed-input"),
            Static("", id="email-hint"),
            Static("", id="warning"),
            Button("Назад", id="back", variant="default"),
            Button("Продолжить" if not self.is_restore else "Восстановить", id="next", variant="primary"),
        )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        text = event.text_area.text
        if "@" in text and "." in text:
            self.query_one("#email-hint", Static).update("✅ Email обнаружен (восстановление возможно)")
        else:
            self.query_one("#email-hint", Static).update("")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "next":
            if self._checking:
                return
            self._checking = True

            seed = self.query_one("#seed-input", TextArea).text
            if not seed.strip():
                self.app.show_warning("Сид-фраза не может быть пустой")
                self._checking = False
                return

            result = await self.app.api_client.check_account_exists(seed.strip())

            if result.get("exists"):
                self.app.show_warning(
                    f"Аккаунт с такой сид-фразой уже существует.\n"
                    f"Пожалуйста, используйте другую сид-фразу."
                )
                self._checking = False
                return

            if self.is_client:
                accounts = await self.app.api_client.get_accounts()
                client_accounts = [acc for acc in accounts if not acc.get("is_server", False)]
                client_count = len(client_accounts)
                MAX_CLIENTS = 3

                if client_count >= MAX_CLIENTS:
                    self.app.show_warning(
                        f"Достигнут лимит клиентских аккаунтов ({MAX_CLIENTS}).\n"
                        "Невозможно создать новый клиентский аккаунт."
                    )
                    self._checking = False
                    while len(self.app.screen_stack) > 1:
                        self.app.pop_screen()
                    fresh_accounts = await self.app.api_client.get_accounts()
                    fresh_client_count = len([acc for acc in fresh_accounts if not acc.get("is_server", False)])
                    if fresh_client_count >= MAX_CLIENTS:
                        self.app.push_screen("AccountFullScreen", accounts=fresh_accounts)
                    else:
                        self.app.push_screen("AccountSelectionScreen", accounts=fresh_accounts)
                    return

            self.app.seed_phrase = seed
            if self.is_restore:
                self.app.push_screen("PasswordRestoreScreen", public_id="", seed=seed)
            else:
                self.app.push_screen(
                    "PasswordInputScreen",
                    seed=seed,
                    selected_region=self.app.selected_region,
                    is_client=self.is_client
                )
            self._checking = False


class PasswordInputScreen(BaseScreen):
    """Экран ввода пароля при регистрации."""

    def __init__(self, seed: str, selected_region: str, is_client: bool = False):
        super().__init__()
        self.seed = seed
        self.region_code = selected_region
        self.is_client = is_client

    def compose(self):
        mode_text = "клиентского" if self.is_client else "серверного"
        yield Vertical(
            Static(f"Регистрация {mode_text} аккаунта", id="mode-info"),
            Static(f"Регион: {self.region_code.upper()}", id="region-info"),
            Static("Придумайте пароль (мин. 8 символов):", id="label"),
            Input(placeholder="Пароль", password=True, id="password-input"),
            Input(placeholder="Подтверждение", password=True, id="confirm-input"),
            Button("Назад", id="back", variant="default"),
            Button("Продолжить", id="next", variant="primary"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "next":
            p1 = self.query_one("#password-input", Input).value
            p2 = self.query_one("#confirm-input", Input).value
            if len(p1) < 8:
                self.app.show_warning("Пароль должен быть не менее 8 символов")
                return
            if p1 != p2:
                self.app.show_warning("Пароли не совпадают")
                return
            self.app.push_screen(
                "RegistrationScreen",
                seed=self.seed,
                password=p1,
                region_code=self.region_code,
                is_client=self.is_client
            )


class PasswordRestoreScreen(BaseScreen):
    """Экран ввода пароля при входе в существующий аккаунт."""

    def __init__(self, public_id: str, seed: str = ""):
        super().__init__()
        self.public_id = public_id
        self.seed = seed

    def compose(self):
        if self.public_id:
            title = f"Вход в аккаунт: {self.public_id}"
        else:
            title = "Восстановление аккаунта"
        yield Vertical(
            Static(title, id="label"),
            Input(placeholder="Пароль", password=True, id="password-input"),
            Button("Назад", id="back", variant="default"),
            Button("Войти", id="login", variant="primary"),
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "login":
            password = self.query_one("#password-input", Input).value
            if not password:
                self.app.show_warning("Введите пароль")
                return

            if self.public_id:
                result = await self.app.api_client.login_by_id(self.public_id, password)
                if result.get("success"):
                    self.app.login_by_id_success(
                        result["token"],
                        result["public_id"],
                        result.get("is_server", False)
                    )
                else:
                    self.app.show_warning(f"Ошибка входа: {result.get('error', 'Unknown')}")
            elif self.seed:
                result = await self.app.api_client.login(self.seed, password)
                if result.get("success"):
                    self.app.login_success(
                        result["token"],
                        result["public_id"],
                        result.get("is_server", False)
                    )
                else:
                    self.app.show_warning(f"Ошибка входа: {result.get('error', 'Unknown')}")
            else:
                self.app.show_warning("Не указан аккаунт для входа")
