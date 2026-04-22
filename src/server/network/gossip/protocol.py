# src/server/network/gossip/protocol.py
"""
Gossip Protocol для обмена данными между серверами.
"""

import asyncio
import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

from src.common.crypto.keys import sign, verify
from src.server.storage.server_db import ServerDatabase, get_server_db
from src.server.network.trust import TrustManager, get_trust_manager, TRUST_LEVEL_QUARANTINE
from .message import GossipMessage
from .handlers import GossipHandlers
from .sync import GossipSync

logger = logging.getLogger(__name__)

GOSSIP_INTERVAL = 60
GOSSIP_TIMEOUT = 10


class GossipProtocol:
    def __init__(
        self,
        my_server_id: str,
        private_key: bytes,
        db: Optional[ServerDatabase] = None,
        trust_manager: Optional[TrustManager] = None,
        http_client=None,
    ):
        self.my_server_id = my_server_id
        self._private_key = private_key
        self._db = db or get_server_db()
        self._trust_manager = trust_manager or get_trust_manager()
        self._http_client = http_client
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._used_nonces: Dict[str, float] = {}

        self._handlers = GossipHandlers(self._db, self._trust_manager, my_server_id)
        self._sync = GossipSync(self._db, self._trust_manager, my_server_id, http_client)

    def _get_public_key(self, server_id: str) -> Optional[bytes]:
        return None

    def _sign_message(self, payload: Dict[str, Any]) -> GossipMessage:
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        data = f"{self.my_server_id}:{timestamp}:{nonce}:{json.dumps(payload, sort_keys=True)}"
        signature = sign(self._private_key, data.encode()).hex()

        return GossipMessage(
            sender_id=self.my_server_id,
            timestamp=timestamp,
            nonce=nonce,
            payload=payload,
            signature=signature,
        )

    def _verify_message(self, message: GossipMessage) -> bool:
        if message.nonce in self._used_nonces:
            logger.warning(f"Duplicate nonce detected: {message.nonce}")
            return False
        self._used_nonces[message.nonce] = time.time()

        if time.time() - message.timestamp > 300:
            logger.warning(f"Message too old: {message.timestamp}")
            return False

        public_key = self._get_public_key(message.sender_id)
        if not public_key:
            logger.warning(f"Unknown server: {message.sender_id}")
            return False

        data = f"{message.sender_id}:{message.timestamp}:{message.nonce}:{json.dumps(message.payload, sort_keys=True)}"
        try:
            return verify(public_key, bytes.fromhex(message.signature), data.encode())
        except Exception:
            return False

    async def _send_to_server(self, server_id: str, ws_url: str, message: GossipMessage) -> None:
        try:
            level = self._trust_manager.get_trust_level(server_id)
            if level == TRUST_LEVEL_QUARANTINE:
                if not self._trust_manager.check_and_increment(server_id, "gossip_out"):
                    return
            logger.debug(f"Sending gossip to {server_id}")
        except Exception as e:
            logger.error(f"Failed to send gossip to {server_id}: {e}")

    async def handle_gossip_message(self, message: GossipMessage) -> Dict[str, Any]:
        if not self._verify_message(message):
            return {"error": "Invalid message"}

        level = self._trust_manager.get_trust_level(message.sender_id)
        if level == TRUST_LEVEL_QUARANTINE:
            if not self._trust_manager.check_and_increment(message.sender_id, "gossip_in"):
                return {"error": "Rate limit exceeded"}

        self._trust_manager.update_last_seen(message.sender_id)

        msg_type = message.payload.get("type")
        handler = self._handlers.get_handler(msg_type)

        return await handler(message)

    async def broadcast_change(self, change_type: str, data: Dict[str, Any]) -> None:
        trusted_servers = self._trust_manager.get_all_trusted_servers(min_level=TRUST_LEVEL_QUARANTINE)

        servers_info = []
        for server_id in trusted_servers:
            if server_id == self.my_server_id:
                continue
            server = self._db.get_server(server_id)
            if server and server["ws_url"]:
                servers_info.append((server_id, server["ws_url"]))

        payload = {"type": change_type, "data": data, "timestamp": int(time.time())}
        message = self._sign_message(payload)

        for server_id, ws_url in servers_info:
            asyncio.create_task(self._send_to_server(server_id, ws_url, message))

    async def _periodic_sync(self) -> None:
        await self._sync.periodic_sync(lambda: self._running)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._periodic_sync())
        logger.info("Gossip protocol started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Gossip protocol stopped")
