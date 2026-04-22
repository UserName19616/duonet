# src/web/crypto_log.py
"""
Визуализация процесса шифрования для демонстрации безопасности обмена сообщениями.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from src.common.identity.account import AccountManager
from src.client.messaging.crypto_logger import get_crypto_logs, clear_crypto_logs, register_crypto_log_ws, unregister_crypto_log_ws
from src.client.messaging.message_router import MessageRouter
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


class SimpleResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class DecryptRequest(BaseModel):
    session_key: str = Field(..., min_length=64, max_length=64)
    phrase: Optional[str] = Field(None, max_length=200)


class SetPhraseRequest(BaseModel):
    phrase: str = Field(..., max_length=200)


def get_current_user(request: Request, account_manager: AccountManager) -> Optional[dict]:
    token = request.cookies.get("token")
    if not token:
        return None
    payload = account_manager.verify_token(token)
    if not payload:
        return None
    return {"public_id": payload["sub"], "account_id": bytes.fromhex(payload.get("account_id", "")),
            "is_server": payload.get("is_server", False)}


async def websocket_crypto_log_handler(websocket: WebSocket, token: str, contact: str,
                                        account_manager: AccountManager, message_router: MessageRouter) -> None:
    payload = account_manager.verify_token(token)
    if not payload:
        await websocket.close(code=1008, reason="Invalid token")
        return
    user_id = payload["sub"]
    contact_id = contact
    await websocket.accept()
    register_crypto_log_ws(user_id, contact_id, websocket)
    logger.info(f"WebSocket crypto log connected: {user_id} <-> {contact_id}")
    existing_logs = get_crypto_logs(user_id, contact_id)
    for log_entry in existing_logs:
        try:
            await websocket.send_json({"type": "crypto_log", "data": log_entry})
        except Exception as e:
            logger.error(f"Failed to send existing log: {e}")
    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            try:
                msg = json.loads(data)
                if msg.get("type") == "clear":
                    clear_crypto_logs(user_id)
                    await websocket.send_json({"type": "clear_response", "data": {"success": True}})
            except json.JSONDecodeError:
                pass
    except asyncio.TimeoutError:
        pass
    except WebSocketDisconnect:
        logger.info(f"WebSocket crypto log disconnected: {user_id} <-> {contact_id}")
    except Exception as e:
        logger.error(f"WebSocket crypto log error: {e}")
    finally:
        unregister_crypto_log_ws(user_id, contact_id)


def create_crypto_log_web_router(account_manager: AccountManager, storage: SQLiteStorage,
                                  message_router: Optional[MessageRouter] = None) -> APIRouter:
    router = APIRouter(prefix="/api/web", tags=["web_crypto_log"])

    def get_current_user_dep(request: Request) -> dict:
        user = get_current_user(request, account_manager)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user

    @router.get("/crypto-log/{contact_id}", response_model=SimpleResponse)
    async def get_crypto_logs_endpoint(contact_id: str, limit: int = 100, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        logs = get_crypto_logs(user["public_id"], contact_id, limit)
        return SimpleResponse(success=True, data={"logs": logs})

    @router.get("/crypto-log/message/{message_id}", response_model=SimpleResponse)
    async def get_crypto_log_by_message_id(message_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        logs = get_crypto_logs(user["public_id"])
        for log in logs:
            if log["message_id"] == message_id:
                return SimpleResponse(success=True, data={"log": log})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="log_not_found")

    @router.get("/messages/{contact_id}/packets/{message_id}", response_model=SimpleResponse)
    async def get_message_packets(contact_id: str, message_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        if not message_router:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="message_router not configured")
        packets = message_router.get_message_packets(message_id)
        if not packets:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message_not_found")
        return SimpleResponse(success=True, data=packets)

    @router.post("/messages/{message_id}/decrypt", response_model=SimpleResponse)
    async def decrypt_message(message_id: str, data: DecryptRequest, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        if not message_router:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="message_router not configured")
        try:
            session_key = bytes.fromhex(data.session_key)
            if len(session_key) != 32:
                raise ValueError("Session key must be 32 bytes")
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid session_key: {e}")
        decrypted = message_router.decrypt_message(message_id=message_id, session_key=session_key, phrase=data.phrase)
        if decrypted is None:
            return SimpleResponse(success=False, error="decryption_failed", data={"decrypted": None})
        return SimpleResponse(success=True, data={"decrypted": decrypted})

    @router.post("/crypto-log/clear", response_model=SimpleResponse)
    async def clear_crypto_logs_endpoint(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        clear_crypto_logs(user["public_id"])
        return SimpleResponse(success=True)

    @router.get("/crypto-log/export", response_model=SimpleResponse)
    async def export_crypto_logs(contact_id: Optional[str] = None, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        logs = get_crypto_logs(user["public_id"], contact_id)
        return SimpleResponse(success=True, data={"logs": logs})

    @router.post("/chat/{contact_id}/phrase", response_model=SimpleResponse)
    async def set_contact_phrase(contact_id: str, data: SetPhraseRequest, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        logger.info(f"Phrase set for contact {contact_id} by user {user['public_id']}")
        return SimpleResponse(success=True, data={"phrase_known": True})

    @router.get("/chat/{contact_id}/phrase", response_model=SimpleResponse)
    async def get_contact_phrase(contact_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        return SimpleResponse(success=True, data={"phrase": None})

    @router.websocket("/ws/crypto_log")
    async def websocket_crypto_log(websocket: WebSocket, token: str, contact: str) -> None:
        await websocket_crypto_log_handler(websocket, token, contact, account_manager, message_router)

    return router
