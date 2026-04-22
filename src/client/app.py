# src/client/app.py
"""
Главное приложение DuoNet TUI (Textual).
"""

import asyncio
import json
import logging
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from .api_client import APIClient
from .state_manager import StateManager
from .screens import (
    WelcomeScreen, CharterScreen, RegionSelectionScreen, SeedInputScreen,
    PasswordInputScreen, PasswordRestoreScreen, RegistrationScreen,
    IdDisplayScreen, ModeSelectionScreen, ChatListScreen, WarningScreen,
    SearchScreen, AccountSelectionScreen, AccountFullScreen,
    ServerPasswordScreen, ServerManagementScreen, InvitesScreen, InviteActionScreen,
)

logger = logging.getLogger(__name__)


class DuoNetApp(App):
    CSS = """
    Screen { align: center middle; }
    #charter-container { width: 90%; height: 90%; background: $surface; border: solid $primary; padding: 1 2; }
    #charter-title { text-align: center; text-style: bold; padding: 1; }
    #charter-scroll { height: 1fr; border: solid $secondary; padding: 1; }
    #charter-content { width: 100%; }
    #charter-buttons { height: auto; align: center middle; padding: 1; }
    #charter-buttons Button { width: 40%; margin: 0 1; }
    #region-container { width: 60%; height: auto; background: $surface; border: solid $primary; padding: 1 2; }
    #region-container Button { margin: 1 0; }
    """

    TITLE = "DuoNet Messenger"
    SUB_TITLE = "Decentralized Secure Communication"

    def __init__(self, api_url: str = "https://localhost:8443", debug: bool = False,
                 auto_account: Optional[str] = None, auto_password: Optional[str] = None):
        super().__init__()
        self.api_client = APIClient(api_url, debug=debug)
        self.state = StateManager()
        self._auto_login_account = auto_account
        self._auto_login_password = auto_password
        self.token = None
        self.public_id = None
        self.phrase_cache = {}
        self._creating_client = False
        self._selected_lang = "ru"
        self._debug = debug

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        if self._auto_login_account:
            self.run_worker(self._auto_login(), exclusive=True)
        else:
            self.run_worker(self._check_startup_state(), exclusive=True)

    async def _auto_login(self) -> None:
        password = self._auto_login_password
        if not password:
            self.push_screen(PasswordRestoreScreen(public_id=self._auto_login_account))
            return
        result = await self.api_client.login_by_id(self._auto_login_account, password)
        if result.get("success"):
            self.login_by_id_success(result["token"], result["public_id"], result.get("is_server", False))
        else:
            self.show_warning(f"Login failed: {result.get('error', 'Unknown error')}")
            self.exit()

    async def _check_startup_state(self) -> None:
        try:
            accounts = await self.api_client.get_accounts()
            if not accounts:
                self.push_screen(WelcomeScreen())
                return
            client_accounts = [acc for acc in accounts if not acc.get("is_server", False)]
            client_count = len(client_accounts)
            MAX_CLIENTS = 3
            if client_count >= MAX_CLIENTS:
                self.push_screen(AccountFullScreen(accounts=accounts))
            else:
                screen = AccountSelectionScreen(accounts=accounts)
                screen.client_count = client_count
                screen.max_clients = MAX_CLIENTS
                self.push_screen(screen)
        except Exception as e:
            logger.error(f"Failed to check startup state: {e}")
            self.push_screen(WelcomeScreen())

    async def action_quit(self) -> None:
        await self.api_client.close()
        self.exit()

    def login_success(self, token: str, public_id: str, is_server: bool) -> None:
        self.state.token = token
        self.state.public_id = public_id
        self.state.is_server = is_server
        self.api_client.set_token(token)
        screen = ChatListScreen()
        self.push_screen(screen)
        asyncio.create_task(screen.load_dialogs())

    def login_by_id_success(self, token: str, public_id: str, is_server: bool) -> None:
        self.state.token = token
        self.state.public_id = public_id
        self.state.is_server = is_server
        self.api_client.set_token(token)
        self.push_screen(ChatListScreen())

    def logout(self) -> None:
        self.state.clear_auth()
        self.api_client.clear_token()
        self.pop_screen()
        asyncio.create_task(self._return_to_account_selection())

    async def _return_to_account_selection(self) -> None:
        accounts = await self.api_client.get_accounts()
        client_accounts = [acc for acc in accounts if not acc.get("is_server", False)]
        client_count = len(client_accounts)
        MAX_CLIENTS = 3
        if client_count >= MAX_CLIENTS:
            self.push_screen(AccountFullScreen(accounts=accounts))
        else:
            screen = AccountSelectionScreen(accounts=accounts)
            screen.client_count = client_count
            screen.max_clients = MAX_CLIENTS
            self.push_screen(screen)

    def show_warning(self, message: str, title: str = "⚠️ ПРЕДУПРЕЖДЕНИЕ") -> None:
        self.push_screen(WarningScreen(message=message, title=title))

    def show_notification(self, message: str, title: str = "DuoNet") -> None:
        from textual import log
        log(f"[{title}] {message}")
        current_screen = self.screen
        if hasattr(current_screen, "show_toast"):
            current_screen.show_toast(message)

    def save_phrase(self, contact_id: str, phrase: str) -> None:
        self.state.save_phrase(contact_id, phrase)

    def forget_phrase(self, contact_id: str) -> None:
        self.state.forget_phrase(contact_id)

    def get_phrase(self, contact_id: str) -> Optional[str]:
        return self.state.get_phrase(contact_id)

    def charter_accepted(self, for_client: bool = False) -> None:
        self.state.charter_accepted = True
        if for_client:
            self.push_screen(SeedInputScreen(is_restore=False, is_client=True))
            self.state.creating_client = False
        else:
            detected_region = "ru"
            self.push_screen(RegionSelectionScreen(detected_region=detected_region))

    def set_language(self, lang: str) -> None:
        self.state.selected_lang = lang

    async def connect_chat_ws(self, contact_id: str) -> None:
        if not self.state.token:
            return
        await self.api_client.connect_chat_ws(self.state.token)

    async def disconnect_chat_ws(self) -> None:
        await self.api_client.disconnect_chat_ws()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DuoNet TUI Client")
    parser.add_argument("--api-url", default="https://localhost:8443", help="API server URL")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--http", action="store_true", help="Use HTTP instead of HTTPS")
    parser.add_argument("--account", help="Public ID of account to login with")
    parser.add_argument("--password", help="Password for the account (optional, will prompt if not provided)")
    args = parser.parse_args()
    api_url = args.api_url
    if args.http:
        api_url = api_url.replace("https://", "http://")
    app = DuoNetApp(api_url=api_url, debug=args.debug, auto_account=args.account, auto_password=args.password)
    app.run()
