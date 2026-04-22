# src/client/screens/account.py
"""
Экраны выбора и управления аккаунтами.
"""

from typing import Any, Dict, List, Optional

from textual.containers import Vertical
from textual.widgets import Button, Input, ListItem, ListView, Static

from .base import BaseScreen


class AccountSelectionScreen(BaseScreen):
    """Экран выбора аккаунта при входе."""

    def __init__(self, accounts: List[Dict[str, Any]] = None):
        super().__init__()
        self.accounts = accounts or []
        self.client_count = 0
        self.max_clients = 3
        self.server_id = None
        self._loading = False

    def compose(self):
        yield Vertical(
            Static("Выберите аккаунт:", id="label"),
            ListView(id="accounts-list"),
            Static("", id="client-limit-info"),
            Button("🔧 Управление сервером", id="server-manage", variant="default"),
            Button("📱 Создать клиентский аккаунт", id="new-client", variant="primary"),
            Button("Выйти", id="quit", variant="error"),
        )

    async def on_mount(self) -> None:
        await self.load_data()

    async def load_data(self) -> None:
        if self._loading:
            return
        self._loading = True

        try:
            if self.client_count >= self.max_clients:
                self.app.pop_screen()
                self.app.push_screen("AccountFullScreen", accounts=self.accounts)
                return

            client_limit_text = f"📊 Клиентские аккаунты: {self.client_count}/{self.max_clients}"
            self.query_one("#client-limit-info", Static).update(client_limit_text)

            create_client_button = self.query_one("#new-client", Button)
            create_client_button.disabled = False
            create_client_button.variant = "primary"

            await self.display_accounts()

            server_exists = any(acc.get("is_server", False) for acc in self.accounts)
            server_manage_button = self.query_one("#server-manage", Button)
            if not server_exists:
                server_manage_button.disabled = True
                server_manage_button.variant = "default"
                server_manage_button.tooltip = "Серверный аккаунт не создан"
            else:
                server_manage_button.disabled = False
                server_manage_button.variant = "primary"

        finally:
            self._loading = False

    async def display_accounts(self) -> None:
        list_view = self.query_one("#accounts-list", ListView)
        list_view.clear()

        server_accounts = []
        client_accounts = []

        for account in self.accounts:
            is_server = account.get("is_server", False)
            if is_server:
                display_id = account.get("server_id", account.get("public_id", "Unknown"))
                if not self.server_id:
                    self.server_id = display_id
            else:
                display_id = account.get("public_id", "Unknown")

            type_icon = "🖥️" if is_server else "📱"
            item = ListItem(Static(f"{type_icon} {display_id}"))
            item.account_data = account

            if is_server:
                server_accounts.append(item)
            else:
                client_accounts.append(item)

        for item in server_accounts:
            list_view.append(item)

        if server_accounts and client_accounts:
            separator = ListItem(Static("─" * 40))
            list_view.append(separator)

        for item in client_accounts:
            list_view.append(item)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-client":
            accounts = await self.app.api_client.get_accounts()
            client_count = len([acc for acc in accounts if not acc.get("is_server", False)])

            if client_count >= self.max_clients:
                self.app.show_warning(
                    f"Достигнут лимит клиентских аккаунтов ({self.max_clients}).\n"
                    "Невозможно создать новый клиентский аккаунт."
                )
                self.client_count = client_count
                client_limit_text = f"📊 Клиентские аккаунты: {self.client_count}/{self.max_clients}"
                self.query_one("#client-limit-info", Static).update(client_limit_text)
                return

            self.app._creating_client = True
            self.app.push_screen("CharterScreen", lang="ru", for_client=True)

        elif event.button.id == "server-manage":
            if not self.server_id:
                self.app.show_warning("Серверный аккаунт не найден.")
                return
            self.app.push_screen("ServerPasswordScreen", server_id=self.server_id)
        elif event.button.id == "quit":
            self.app.exit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        contact = getattr(event.item, 'contact_data', None)
        if contact:
            self.app.push_screen("ChatScreen", contact=contact)


class AccountFullScreen(BaseScreen):
    """Экран выбора аккаунта при достижении лимита клиентских аккаунтов."""

    def __init__(self, accounts: List[Dict[str, Any]] = None):
        super().__init__()
        self.accounts = accounts or []
        self.server_id = None
        self._loading = False

    def compose(self):
        yield Vertical(
            Static("Выберите аккаунт:", id="label"),
            ListView(id="accounts-list"),
            Static("📊 Достигнут лимит клиентских аккаунтов (3)", id="limit-info"),
            Button("🔧 Управление сервером", id="server-manage", variant="default"),
            Button("Выйти", id="quit", variant="error"),
        )

    async def on_mount(self) -> None:
        await self.load_data()

    async def load_data(self) -> None:
        if self._loading:
            return
        self._loading = True

        try:
            if not self.accounts:
                await self.load_accounts()
            else:
                await self.display_accounts()

            server_exists = any(acc.get("is_server", False) for acc in self.accounts)
            server_manage_button = self.query_one("#server-manage", Button)
            if not server_exists:
                server_manage_button.disabled = True
                server_manage_button.variant = "default"
                server_manage_button.tooltip = "Серверный аккаунт не создан"
            else:
                server_manage_button.disabled = False
                server_manage_button.variant = "primary"

        finally:
            self._loading = False

    async def display_accounts(self) -> None:
        list_view = self.query_one("#accounts-list", ListView)
        list_view.clear()

        server_accounts = []
        client_accounts = []

        for account in self.accounts:
            is_server = account.get("is_server", False)
            if is_server:
                display_id = account.get("server_id", account.get("public_id", "Unknown"))
                if not self.server_id:
                    self.server_id = display_id
            else:
                display_id = account.get("public_id", "Unknown")

            type_icon = "🖥️" if is_server else "📱"
            item = ListItem(Static(f"{type_icon} {display_id}"))
            item.account_data = account

            if is_server:
                server_accounts.append(item)
            else:
                client_accounts.append(item)

        for item in server_accounts:
            list_view.append(item)

        if server_accounts and client_accounts:
            separator = ListItem(Static("─" * 40))
            list_view.append(separator)

        for item in client_accounts:
            list_view.append(item)

    async def load_accounts(self) -> None:
        self.accounts = await self.app.api_client.get_accounts()
        await self.display_accounts()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "server-manage":
            if not self.server_id:
                self.app.show_warning("Серверный аккаунт не найден.")
                return
            self.app.push_screen("ServerPasswordScreen", server_id=self.server_id)
        elif event.button.id == "quit":
            self.app.exit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        account = getattr(event.item, 'account_data', None)
        if account:
            if account.get("is_server", False):
                self.app.show_warning(
                    "Для управления сервером используйте кнопку 'Управление сервером' внизу экрана."
                )
                return
            public_id = account.get("public_id", "")
            self.app.push_screen("PasswordRestoreScreen", public_id=public_id)


class ServerPasswordScreen(BaseScreen):
    """Экран ввода пароля для управления сервером."""

    def __init__(self, server_id: str):
        super().__init__()
        self.server_id = server_id

    def compose(self):
        yield Vertical(
            Static(f"Управление сервером", id="title"),
            Static(f"Серверный ID: {self.server_id}", id="server-id"),
            Static("Введите пароль для доступа:", id="label"),
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

            result = await self.app.api_client.login_by_id(self.server_id, password)

            if result.get("success"):
                self.app.token = result["token"]
                self.app.public_id = self.server_id
                self.app.is_server = True
                self.app.api_client.set_token(result["token"])
                self.app.push_screen("ServerManagementScreen")
            else:
                self.app.show_warning(f"Ошибка входа: {result.get('error', 'Unknown')}")


class ServerManagementScreen(BaseScreen):
    """Экран управления сервером."""

    def compose(self):
        yield Vertical(
            Static("🖥️ Управление сервером", id="title"),
            Static("Функционал в разработке", id="message"),
            Static("Здесь будет панель управления прокси-клиентами, статистика и настройки.", id="info"),
            Button("Назад", id="back", variant="default"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.logout()
