# src/web/contacts/routes.py
"""
REST эндпоинты для веб-контактов.
"""

import logging
import sqlite3
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.common.identity.account import AccountManager
from src.common.identity.public_id import is_server_id, is_valid_format
from src.client.messaging.invite import InviteProtocol
from src.client.messaging.spam_protection import SpamProtection
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.client.storage.contacts import ContactsStorage
from src.common.storage.sqlite import SQLiteStorage
from src.server.api.websocket import get_ws_manager
from .utils import get_current_user, get_user_contacts_storage
from .invite_handlers import send_invite, accept_invite, reject_invite, revoke_invite

logger = logging.getLogger(__name__)


def get_current_user_dep(request: Request, account_manager: AccountManager) -> dict:
    user = get_current_user(request, account_manager)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def validate_public_id(public_id: str) -> bool:
    return is_valid_format(public_id)


def create_contacts_web_router(
    account_manager: AccountManager,
    storage: SQLiteStorage,
    rendezvous_client: RendezvousClient,
    invite_protocol: InviteProtocol,
    spam_protection: SpamProtection,
    message_router,
) -> APIRouter:
    router = APIRouter(prefix="/api/web", tags=["web_contacts"])

    def _get_current_user(request: Request) -> dict:
        return get_current_user_dep(request, account_manager)

    @router.get("/contacts")
    async def get_contacts(
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        conn = sqlite3.connect("duonet.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT DISTINCT
                CASE
                    WHEN user_id = ? THEN contact_id
                    ELSE user_id
                END as contact_id,
                MAX(last_activity) as last_activity
            FROM dialogs
            WHERE user_id = ? OR contact_id = ?
            GROUP BY contact_id
            ORDER BY last_activity DESC
        """, (user["public_id"], user["public_id"], user["public_id"]))

        contacts_storage = get_user_contacts_storage(user["account_id"], storage)
        contacts_map = {}
        for contact in contacts_storage.get_all():
            contacts_map[contact.public_id] = contact

        ws_manager = get_ws_manager()

        results = []
        for row in cursor.fetchall():
            contact_id = row["contact_id"]
            last_activity = row["last_activity"]

            if contact_id == user["public_id"]:
                continue

            online = False
            if ws_manager:
                online = ws_manager.get_connection(contact_id) is not None

            contact_info = contacts_map.get(contact_id)
            if contact_info:
                name = contact_info.name
                phrase_known = contact_info.phrase_hash is not None
                added_at = contact_info.added_at
            else:
                name = contact_id
                phrase_known = False
                added_at = last_activity or 0

            results.append({
                "public_id": contact_id,
                "name": name,
                "added_at": added_at,
                "online": online,
                "phrase_known": phrase_known,
                "last_message": None,
                "last_message_time": None,
                "unread": 0
            })

        conn.close()
        return {"success": True, "data": {"contacts": results}}

    @router.get("/dialogs")
    async def dialogs_redirect(request: Request):
        """Редирект на страницу контактов."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/contacts", status_code=302)

    @router.patch("/contacts/{contact_id}/name")
    async def update_contact_name(
        contact_id: str,
        data: dict,
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        if not validate_public_id(contact_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_public_id",
            )

        new_name = data.get("name", "")
        if not new_name or len(new_name) > 64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_name",
            )

        contacts_storage = get_user_contacts_storage(user["account_id"], storage)
        success = contacts_storage.update_name(contact_id, new_name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="contact_not_found",
            )

        logger.info(f"Updated contact name for {contact_id} to '{new_name}' by user {user['public_id']}")
        return {"success": True, "data": {"name": new_name}}

    @router.post("/contacts/search")
    async def search_contacts(
        data: dict,
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        query = data.get("query", "").strip()
        results = []

        if query.startswith("@*."):
            result = rendezvous_client.resolve_contact(query)
            if result and result.get("type") == "list":
                items = result.get("items", [])
                for item in items:
                    results.append({
                        "public_id": item.get("public_id", ""),
                        "type": item.get("type", "server"),
                        "online": False,
                        "region": item.get("region"),
                        "load": item.get("load"),
                    })
                return {"success": True, "data": {"results": results}}

        if validate_public_id(query):
            if is_server_id(query):
                server = rendezvous_client.find_server_by_id(query)
                if server:
                    results.append({
                        "public_id": server["public_id"],
                        "type": server["type"],
                        "online": False,
                        "region": server.get("region"),
                        "load": server.get("load"),
                    })
            else:
                results.append({
                    "public_id": query,
                    "type": "client",
                    "online": False,
                    "region": None,
                    "load": None,
                })
        else:
            if len(query) == 2 and query.isalpha():
                servers = rendezvous_client.find_servers_by_region(query)
                for server in servers:
                    results.append({
                        "public_id": server.get("public_id", ""),
                        "type": server.get("type", "server"),
                        "online": False,
                        "region": server.get("region", query),
                        "load": server.get("load"),
                    })

        return {"success": True, "data": {"results": results}}

    @router.get("/invites")
    async def get_invites_endpoint(
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        try:
            invites = invite_protocol.get_pending_invites(user["public_id"])
        except Exception as e:
            logger.error(f"Error in get_pending_invites: {e}")
            return {"success": False, "error": str(e)}

        result = []
        for invite in invites:
            result.append({
                "invite_id": invite["invite_id"],
                "from_id": invite["from_id"],
                "message": invite["message"],
                "timestamp": invite["created_at"],
                "expires_at": invite["expires_at"],
                "status": invite["status"],
            })

        return {"success": True, "data": {"invites": result}}

    @router.get("/invites/sent")
    async def get_sent_invites_endpoint(
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        try:
            invites = invite_protocol.get_sent_invites(user["public_id"])
        except Exception as e:
            logger.error(f"Error in get_sent_invites: {e}")
            return {"success": False, "error": str(e)}

        result = []
        for invite in invites:
            result.append({
                "invite_id": invite["invite_id"],
                "to_id": invite["to_id"],
                "message": invite["message"],
                "timestamp": invite["created_at"],
                "expires_at": invite["expires_at"],
                "status": invite["status"],
            })

        return {"success": True, "data": {"invites": result}}

    @router.post("/invites/{invite_id}/revoke")
    async def revoke_invite_endpoint(
        invite_id: str,
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        result = await revoke_invite(invite_id, user["public_id"], invite_protocol)
        return {"success": True, "data": result}

    @router.post("/invites/send")
    async def send_invite_endpoint(
        data: dict,
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        result = await send_invite(
            from_id=user["public_id"],
            to_id=data.get("public_id", ""),
            message=data.get("message", ""),
            account_manager=account_manager,
            invite_protocol=invite_protocol,
            spam_protection=spam_protection,
            rendezvous_client=rendezvous_client,
        )
        return {"success": True, "data": result}

    @router.post("/invites/{invite_id}/accept")
    async def accept_invite_endpoint(
        invite_id: str,
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        result = await accept_invite(
            invite_id=invite_id,
            accepter_id=user["public_id"],
            account_manager=account_manager,
            invite_protocol=invite_protocol,
        )
        return {"success": True, "data": result}

    @router.post("/invites/{invite_id}/reject")
    async def reject_invite_endpoint(
        invite_id: str,
        user: dict = Depends(_get_current_user),
    ) -> Dict[str, Any]:
        result = await reject_invite(invite_id, user["public_id"], invite_protocol)
        return {"success": True, "data": result}

    @router.get("/dialogs-with-last-messages")
    def get_dialogs_with_last_messages(request: Request):
        """Получение диалогов с последними сообщениями."""
        import sqlite3
        from src.server.api.websocket import get_ws_manager
        from .utils import get_current_user, get_user_contacts_storage
        from src.common.storage.sqlite import SQLiteStorage

        # Получаем пользователя из cookies
        user = get_current_user(request, account_manager)
        if not user:
            return {"success": False, "error": "unauthorized", "data": {"dialogs": []}}

        local_storage = SQLiteStorage("duonet.db")

        conn = sqlite3.connect("duonet.db")
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.execute("""
                SELECT DISTINCT
                    CASE
                        WHEN user_id = ? THEN contact_id
                        ELSE user_id
                    END as contact_id
                FROM dialogs
                WHERE user_id = ? OR contact_id = ?
            """, (user["public_id"], user["public_id"], user["public_id"]))

            dialogs = []
            ws_manager = get_ws_manager()
            contacts_storage = get_user_contacts_storage(user["account_id"], local_storage)

            for row in cursor.fetchall():
                contact_id = row["contact_id"]

                if contact_id == user["public_id"]:
                    continue

                msg_cursor = conn.execute("""
                    SELECT from_id, encrypted, timestamp, read, is_system, system_type
                    FROM messages
                    WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)
                    ORDER BY timestamp DESC LIMIT 1
                """, (contact_id, user["public_id"], user["public_id"], contact_id))

                last_msg = msg_cursor.fetchone()

                last_message_preview = None
                if last_msg:
                    if last_msg["is_system"] == 1:
                        sys_types = {
                            'rotation_request': '🔄 Запрос смены ключа',
                            'rotation_accept': '✅ Подтверждение смены ключа',
                            'rotation_confirm': '🔐 Ключ обновлён',
                            'rotation_complete': '✅ Смена ключа завершена',
                            'rotation_reject': '❌ Смена ключа отклонена',
                            'rotation_timeout': '⏰ Запрос истёк'
                        }
                        last_message_preview = sys_types.get(last_msg["system_type"], '📢 Системное сообщение')
                    else:
                        encrypted_preview = last_msg["encrypted"][:30] + "..." if len(last_msg["encrypted"]) > 30 else last_msg["encrypted"]
                        last_message_preview = f'🔒 [Зашифровано] {encrypted_preview}'

                unread_cursor = conn.execute("""
                    SELECT COUNT(*) FROM messages
                    WHERE from_id = ? AND to_id = ? AND read = 0 AND is_system = 0
                """, (contact_id, user["public_id"]))

                unread_count = unread_cursor.fetchone()[0]

                contact_info = contacts_storage.get(contact_id)
                contact_name = contact_info.name if contact_info else contact_id.split('@')[1][:15] if '@' in contact_id else contact_id[:15]

                online = False
                if ws_manager:
                    online = ws_manager.get_connection(contact_id) is not None

                dialogs.append({
                    "contact_id": contact_id,
                    "contact_name": contact_name,
                    "last_message": last_message_preview,
                    "last_message_time": last_msg["timestamp"] if last_msg else None,
                    "unread_count": unread_count,
                    "online": online,
                })

            dialogs.sort(key=lambda x: x["last_message_time"] or 0, reverse=True)

            return {"success": True, "data": {"dialogs": dialogs}}

        except Exception as e:
            import logging
            logging.error(f"Error in dialogs-with-last-messages: {e}")
            return {"success": False, "error": str(e), "data": {"dialogs": []}}
        finally:
            conn.close()

    return router
