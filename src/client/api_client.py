# src/client/api_client.py
"""
HTTP-клиент для взаимодействия с API сервером DuoNet.
"""

import json
import logging
import ssl
import certifi
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, base_url: str = "https://localhost:8443", debug: bool = False):
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = None
        self._debug = debug
        self._ws = None
        self._ws_task = None
        self._ws_contact = None

        if self.base_url.startswith("https"):
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0, verify=ssl_context)
        else:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0, verify=False)

        if debug:
            logging.basicConfig(level=logging.DEBUG)

    def set_token(self, token: str) -> None:
        self._token = token
        self._client.headers["Authorization"] = f"Bearer {token}"

    def clear_token(self) -> None:
        self._token = None
        if "Authorization" in self._client.headers:
            del self._client.headers["Authorization"]

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        try:
            if self._debug:
                logger.debug(f"Request: {method.upper()} {path}")
            if self._token and "cookies" not in kwargs:
                kwargs["cookies"] = {"token": self._token}
            response = await getattr(self._client, method)(path, **kwargs)
            try:
                return response.json()
            except Exception:
                return {"success": False, "error": "Invalid JSON response"}
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return {"success": False, "error": str(e)}

    async def register(self, seed_phrase: str, password: str, region: str = "ru", is_server: bool = False) -> Dict[str, Any]:
        return await self._request("post", "/api/auth/register", json={
            "seed_phrase": seed_phrase, "password": password, "region": region, "is_server": is_server})

    async def login(self, seed_phrase: str, password: str) -> Dict[str, Any]:
        return await self._request("post", "/api/auth/login", json={"seed_phrase": seed_phrase, "password": password})

    async def login_by_id(self, public_id: str, password: str) -> Dict[str, Any]:
        return await self._request("post", "/api/auth/login-by-id", json={"public_id": public_id, "password": password})

    async def accept_charter(self, seed_phrase: str, lang: str = "ru") -> Dict[str, Any]:
        return await self._request("post", "/api/charter/accept", json={"seed_phrase": seed_phrase, "lang": lang})

    async def accept_charter_client(self, seed_phrase: str, lang: str = "ru") -> Dict[str, Any]:
        return await self._request("post", "/api/charter/accept", json={"seed_phrase": seed_phrase, "lang": lang, "account_type": "client"})

    async def get_accounts(self) -> List[Dict[str, Any]]:
        result = await self._request("get", "/api/auth/accounts")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "accounts" in result:
            return result["accounts"]
        return []

    async def get_client_limit(self) -> Dict[str, Any]:
        return await self._request("get", "/api/auth/client-limit")

    async def get_server_limit(self) -> Dict[str, Any]:
        return await self._request("get", "/api/auth/server-limit")

    async def check_account_exists(self, seed_phrase: str) -> Dict[str, Any]:
        return await self._request("post", "/api/auth/check-account", json={"seed_phrase": seed_phrase})

    async def get_contacts(self) -> Dict[str, Any]:
        return await self._request("get", "/api/web/contacts")

    async def get_dialogs(self) -> List[Dict[str, Any]]:
        result = await self._request("get", "/api/web/dialogs")
        if result.get("success"):
            return result.get("data", {}).get("dialogs", [])
        return []

    async def get_dialogs_with_messages(self) -> List[Dict[str, Any]]:
        result = await self._request("get", "/api/web/contacts")
        if result.get("success"):
            return result.get("data", {}).get("contacts", [])
        return []

    async def get_messages(self, contact_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        result = await self._request("get", f"/api/messages/history/{contact_id}?limit={limit}&offset={offset}")
        if result.get("success"):
            return result.get("messages", [])
        return []

    async def get_session_key(self, contact_id: str) -> Optional[str]:
        result = await self._request("get", f"/api/web/dialog/{contact_id}/session-key")
        if result.get("success"):
            return result.get("data", {}).get("session_key")
        return None

    async def send_message(self, to: str, encrypted: str, session_key: str, has_phrase: bool = False,
                           plaintext_len: Optional[int] = None, prev_padding: Optional[int] = None,
                           message_counter: Optional[int] = None) -> Dict[str, Any]:
        payload = {"to": to, "encrypted": encrypted, "session_key": session_key, "has_phrase": has_phrase}
        if plaintext_len is not None:
            payload["plaintext_len"] = plaintext_len
        if prev_padding is not None:
            payload["prev_padding"] = prev_padding
        if message_counter is not None:
            payload["message_counter"] = message_counter
        return await self._request("post", "/api/messages/send", json=payload)

    async def mark_message_read(self, message_id: str) -> bool:
        result = await self._request("post", "/api/messages/read", json={"message_id": message_id})
        return result.get("success", False)

    async def mark_all_read(self, contact_id: str) -> int:
        result = await self._request("post", f"/api/messages/read-all/{contact_id}")
        if result.get("success"):
            return result.get("count", 0)
        return 0

    async def delete_message(self, message_id: str) -> bool:
        result = await self._request("delete", f"/api/messages/{message_id}")
        return result.get("success", False)

    async def delete_conversation(self, contact_id: str) -> int:
        result = await self._request("delete", f"/api/messages/conversation/{contact_id}")
        if result.get("success"):
            return result.get("count", 0)
        return 0

    async def get_public_key(self, public_id: str) -> Optional[str]:
        result = await self._request("get", f"/api/web/public-key/{public_id}")
        if result.get("success"):
            return result.get("data", {}).get("public_key")
        return None

    async def get_my_public_key(self) -> Optional[str]:
        result = await self._request("get", "/api/web/public-key")
        if result.get("success"):
            return result.get("data", {}).get("public_key")
        return None

    async def initiate_key_rotation(self, contact_id: str) -> Dict[str, Any]:
        return await self._request("post", "/api/messages/rotate-key", json={"contact_id": contact_id})

    async def get_rotation_status(self, contact_id: str) -> Dict[str, Any]:
        return await self._request("get", f"/api/messages/rotation-status/{contact_id}")

    async def confirm_key_rotation(self, contact_id: str, request_id: str) -> Dict[str, Any]:
        return await self._request("post", "/api/messages/rotate-key/confirm", json={"contact_id": contact_id, "request_id": request_id})

    async def reject_key_rotation(self, contact_id: str, request_id: str) -> Dict[str, Any]:
        return await self._request("post", "/api/messages/rotate-key/reject", json={"contact_id": contact_id, "request_id": request_id})

    async def connect_chat_ws(self, token: str) -> None:
        import websockets
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        api_host = self.base_url.replace("https://", "").replace("http://", "")
        ws_url = f"wss://{api_host}/ws?token={token}"
        try:
            self._ws = await websockets.connect(ws_url, ssl=ssl_context, close_timeout=5)
            logger.info(f"WebSocket connected for {token[:20]}...")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._ws = None

    async def disconnect_chat_ws(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except Exception:
                pass
        if self._ws:
            await self._ws.close()
        self._ws = None
        self._ws_task = None

    async def close(self) -> None:
        await self._client.aclose()
