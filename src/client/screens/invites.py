# src/client/screens/invites.py
"""
Экраны приглашений.
"""

import time

from textual.containers import Vertical, Horizontal
from textual.widgets import Button, ListItem, ListView, Static

from .base import BaseScreen


class InvitesScreen(BaseScreen):
    """Экран входящих приглашений."""

    def compose(self):
        yield Vertical(
            Static("📨 Входящие приглашения", id="title"),
            ListView(id="invites-list"),
            Button("Обновить", id="refresh", variant="primary"),
            Button("Назад", id="back", variant="default"),
        )

    async def on_mount(self) -> None:
        await self.load_invites()

    async def load_invites(self) -> None:
        """Загрузка входящих приглашений."""
        result = await self.app.api_client._request("get", "/api/web/invites")
        list_view = self.query_one("#invites-list", ListView)
        list_view.clear()

        if result.get("success"):
            invites = result.get("data", {}).get("invites", [])
            for invite in invites:
                item = ListItem(Static(
                    f"📩 От: {invite['from_id']}\n"
                    f"   Сообщение: {invite['message'][:50]}\n"
                    f"   Истекает: {time.strftime('%Y-%m-%d %H:%M', time.localtime(invite['expires_at']))}"
                ))
                item.invite_data = invite
                list_view.append(item)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        invite = getattr(event.item, 'invite_data', None)
        if invite:
            self.app.push_screen("InviteActionScreen", invite=invite)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            await self.load_invites()
        elif event.button.id == "back":
            self.app.pop_screen()


class InviteActionScreen(BaseScreen):
    """Экран для принятия/отклонения приглашения."""

    def __init__(self, invite: dict):
        super().__init__()
        self.invite = invite

    def compose(self):
        yield Vertical(
            Static(f"Приглашение от {self.invite['from_id']}", id="title"),
            Static(f"Сообщение: {self.invite['message']}", id="message"),
            Static(f"Истекает: {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.invite['expires_at']))}", id="expires"),
            Horizontal(
                Button("✅ Принять", id="accept", variant="success"),
                Button("❌ Отклонить", id="reject", variant="error"),
                Button("Назад", id="back", variant="default"),
            ),
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept":
            result = await self.app.api_client._request(
                "post",
                f"/api/web/invites/{self.invite['invite_id']}/accept"
            )
            if result.get("success"):
                self.app.show_warning("✅ Контакт добавлен!")
                self.app.pop_screen()
                self.app.pop_screen()
            else:
                self.app.show_warning(f"Ошибка: {result.get('error')}")
        elif event.button.id == "reject":
            await self.app.api_client._request(
                "post",
                f"/api/web/invites/{self.invite['invite_id']}/reject"
            )
            self.app.show_warning("❌ Приглашение отклонено")
            self.app.pop_screen()
        elif event.button.id == "back":
            self.app.pop_screen()
