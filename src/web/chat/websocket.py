# src/web/chat/websocket.py
"""
WebSocket обработчик для веб-чата.
"""

import asyncio
import json
import logging
import secrets
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from src.common.identity.account import AccountManager
from src.client.storage.messages import MessagesStorage, MessageInfo
from src.config import MAX_TEXT_LENGTH, MAX_FILE_SIZE_BYTES
from src.server.api.websocket import get_ws_manager
from .manager import get_chat_manager
from .utils import generate_message_id, generate_system_message_id

logger = logging.getLogger(__name__)


async def websocket_chat_handler(
    websocket: WebSocket,
    token: str,
    contact: str,
    account_manager: AccountManager,
    db_path: str,
    message_router=None,
) -> None:
    payload = account_manager.verify_token(token)
    if not payload:
        await websocket.close(code=1008, reason="Invalid token")
        return

    user_id = payload["sub"]
    contact_id = contact
    account_id_hex = payload.get("account_id", "")
    if not account_id_hex:
        await websocket.close(code=1008, reason="Invalid account_id")
        return

    await websocket.accept()

    chat_manager = get_chat_manager()
    ws_manager = get_ws_manager()

    await chat_manager.register_with_global_manager(
        user_id=user_id,
        websocket=websocket,
        client_ip=websocket.client.host or "unknown"
    )

    await chat_manager.connect(user_id, contact_id, websocket)

    messages_storage = MessagesStorage(db_path)

    if message_router:
        message_router.load_dialogs_from_db(user_id)

    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=55.0)

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": {"code": "invalid_json", "message": "Invalid JSON"},
                })
                continue

            msg_type = msg.get("type")
            msg_data = msg.get("data", {})

            if msg_type == "status":
                if ws_manager:
                    await ws_manager.update_heartbeat(user_id)
                    conn = ws_manager.get_connection(user_id)
                    if conn:
                        conn.last_heartbeat = time.time()

                await websocket.send_json({
                    "type": "status_response",
                    "data": {
                        "online": True,
                        "timestamp": int(time.time()),
                        "server_load": 0.1,
                        "server_overloaded": False,
                        "recommend_servers": []
                    }
                })
                logger.debug(f"Status received from {user_id}")
                continue

            if msg_type == "ping" or (isinstance(msg, str) and msg == "ping"):
                if ws_manager:
                    await ws_manager.update_heartbeat(user_id)
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "pong":
                if ws_manager:
                    await ws_manager.update_heartbeat(user_id)
                continue

            if msg_type == "message":
                message_id = msg_data.get("message_id", generate_message_id())
                encrypted_hex = msg_data.get("encrypted", "")
                session_key_hex = msg_data.get("session_key", "")
                has_phrase = msg_data.get("has_phrase", False)
                plaintext = msg_data.get("plaintext", "")
                is_file = msg_data.get("is_file", False)
                file_size = msg_data.get("file_size", None)
                is_system = msg_data.get("is_system", 0)
                system_type = msg_data.get("system_type")
                system_data = msg_data.get("system_data")

                if is_system == 1 and system_type and message_router:
                    logger.info(f"Processing system message: {system_type} from {user_id} to {contact_id}")
                    parsed_system_data = system_data
                    if isinstance(system_data, str):
                        try:
                            parsed_system_data = json.loads(system_data)
                        except:
                            parsed_system_data = {}
                    result = message_router.handle_system_message(
                        from_id=user_id,
                        to_id=contact_id,
                        system_type=system_type,
                        system_data=parsed_system_data,
                        timestamp=int(time.time())
                    )
                    logger.info(f"System message {system_type} processed: {result}")

                    if system_type == "rotation_request" and result.get("action") == "auto_confirmed":
                        if message_router._ws_manager and message_router._account_manager.is_online(user_id):
                            await message_router._ws_manager.send_to_client(user_id, {
                                "type": "message",
                                "data": {
                                    "message_id": generate_system_message_id("ack"),
                                    "from": contact_id,
                                    "is_system": 1,
                                    "system_type": "rotation_ack",
                                    "system_data": json.dumps({"request_id": parsed_system_data.get("request_id")}),
                                    "timestamp": int(time.time())
                                }
                            })
                            logger.info(f"WebSocket rotation_ack sent to {user_id}")

                    timestamp = int(time.time())
                    sys_msg = MessageInfo(
                        id=message_id or generate_system_message_id(system_type),
                        from_id=user_id,
                        to_id=contact_id,
                        session_key="",
                        encrypted="",
                        timestamp=timestamp,
                        delivered=True,
                        read=True,
                        has_phrase=False,
                        direction="system",
                        is_system=1,
                        system_type=system_type,
                        system_data=json.dumps(parsed_system_data) if parsed_system_data else None,
                    )
                    messages_storage.save(sys_msg)

                    await chat_manager.send_to_user(contact_id, user_id, {
                        "type": "message",
                        "data": {
                            "message_id": sys_msg.id,
                            "from": user_id,
                            "encrypted": "",
                            "session_key": "",
                            "timestamp": timestamp,
                            "has_phrase": False,
                            "is_own": False,
                            "is_system": 1,
                            "system_type": system_type,
                            "system_data": json.dumps(parsed_system_data) if parsed_system_data else None,
                        },
                    })

                    await websocket.send_json({
                        "type": "message",
                        "data": {
                            "message_id": sys_msg.id,
                            "from": user_id,
                            "encrypted": "",
                            "session_key": "",
                            "timestamp": timestamp,
                            "has_phrase": False,
                            "is_own": True,
                            "is_system": 1,
                            "system_type": system_type,
                            "system_data": json.dumps(parsed_system_data) if parsed_system_data else None,
                        },
                    })
                    continue

                if not is_file and plaintext:
                    if len(plaintext) > MAX_TEXT_LENGTH:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"code": "message_too_long", "message": f"Text message too long (max {MAX_TEXT_LENGTH} chars)"}
                        })
                        continue

                if is_file and file_size and file_size > MAX_FILE_SIZE_BYTES:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": "file_too_large", "message": f"File too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)} MB)"}
                    })
                    continue

                if not encrypted_hex:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": "missing_encrypted", "message": "No encrypted data"}
                    })
                    continue

                if not session_key_hex:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"code": "missing_session_key", "message": "No session key"}
                    })
                    continue

                timestamp = int(time.time())
                outgoing_msg = MessageInfo(
                    id=message_id,
                    from_id=user_id,
                    to_id=contact_id,
                    session_key=session_key_hex,
                    encrypted=encrypted_hex,
                    timestamp=timestamp,
                    delivered=False,
                    read=False,
                    has_phrase=has_phrase,
                    direction="outgoing",
                )
                messages_storage.save(outgoing_msg)

                success = await chat_manager.send_to_user(contact_id, user_id, {
                    "type": "message",
                    "data": {
                        "message_id": message_id,
                        "from": user_id,
                        "encrypted": encrypted_hex,
                        "session_key": session_key_hex,
                        "timestamp": timestamp,
                        "has_phrase": has_phrase,
                        "is_own": False,
                        "is_file": is_file,
                        "file_size": file_size,
                    },
                })

                if success and ws_manager:
                    await ws_manager.send_to_client(user_id, {
                        "type": "message_delivered",
                        "data": {"message_id": message_id}
                    })

                await websocket.send_json({
                    "type": "message",
                    "data": {
                        "message_id": message_id,
                        "from": user_id,
                        "encrypted": encrypted_hex,
                        "session_key": session_key_hex,
                        "timestamp": timestamp,
                        "has_phrase": has_phrase,
                        "is_own": True,
                        "is_file": is_file,
                        "file_size": file_size,
                        "plaintext": plaintext,
                    },
                })

            elif msg_type == "typing":
                is_typing = msg_data.get("is_typing", False)
                if is_typing:
                    await chat_manager.set_typing(user_id, contact_id)
                else:
                    await chat_manager.broadcast_typing(user_id, contact_id, False)

            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"code": "unknown_type", "message": f"Unknown type: {msg_type}"}
                })

    except asyncio.TimeoutError:
        logger.debug(f"WebSocket timeout for {user_id}")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {user_id}: {e}")
    finally:
        await chat_manager.disconnect(user_id, contact_id)
        if ws_manager:
            await ws_manager.remove_connection(user_id)
        logger.info(f"WebSocket cleanup completed for {user_id}")
