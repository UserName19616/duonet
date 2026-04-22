# src/web/chat/routes.py
"""
REST эндпоинты для веб-чата.
"""

import json
import logging
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.common.identity.account import AccountManager
from src.client.storage.messages import MessagesStorage, MessageInfo
from src.server.api.websocket import get_ws_manager
from src.config import MAX_TEXT_LENGTH, MAX_FILE_SIZE_BYTES
from .manager import get_chat_manager
from .utils import get_current_user, render_template_safe

logger = logging.getLogger(__name__)


class PhraseRequest(BaseModel):
    phrase: str = Field(..., min_length=1, max_length=200)


class SimpleResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


def create_chat_web_router(account_manager: AccountManager, db_path: str, message_router=None) -> APIRouter:
    router = APIRouter(prefix="/api/web", tags=["web_chat"])
    templates = Jinja2Templates(directory="src/web/templates")
    chat_manager = get_chat_manager()

    def get_current_user_dep(request: Request) -> dict:
        user = get_current_user(request, account_manager)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user

    @router.get("/dialog/{contact_id}/session-key", response_model=SimpleResponse)
    async def get_session_key(contact_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        current_user_id = user["public_id"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT session_key FROM dialogs WHERE (user_id = ? AND contact_id = ?) OR (user_id = ? AND contact_id = ?)",
            (current_user_id, contact_id, contact_id, current_user_id))
        row = cursor.fetchone()
        conn.close()
        if row:
            return SimpleResponse(success=True, data={"session_key": row["session_key"]})
        logger.warning(f"Dialog not found for {current_user_id} <-> {contact_id}")
        return SimpleResponse(success=False, error="dialog_not_found")

    @router.get("/public-key", response_model=SimpleResponse)
    async def get_my_public_key(user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        public_key = account_manager.get_public_key_by_id(user["public_id"])
        if not public_key:
            return SimpleResponse(success=False, error="public_key_not_found")
        return SimpleResponse(success=True, data={"public_key": public_key.hex()})

    @router.get("/public-key/{public_id}", response_model=SimpleResponse)
    async def get_user_public_key(public_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        public_key = account_manager.get_public_key_by_id(public_id)
        if not public_key:
            return SimpleResponse(success=False, error="public_key_not_found")
        return SimpleResponse(success=True, data={"public_key": public_key.hex()})

    @router.get("/messages/{contact_id}", response_model=SimpleResponse)
    async def get_messages(contact_id: str, limit: int = 50, offset: int = 0,
                           user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        messages_storage = MessagesStorage(db_path)
        messages = messages_storage.get_dialog(user["public_id"], contact_id, limit, offset)
        result = [{
            "id": msg.id,
            "from_id": msg.from_id,
            "to_id": msg.to_id,
            "encrypted": msg.encrypted,
            "session_key": msg.session_key,
            "timestamp": msg.timestamp,
            "has_phrase": msg.has_phrase,
            "delivered": msg.delivered,
            "read": msg.read
        } for msg in messages]
        return SimpleResponse(success=True, data={"messages": result})

    @router.get("/message/{message_id}", response_model=SimpleResponse)
    async def get_message_by_id(message_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        messages_storage = MessagesStorage(db_path)
        msg = messages_storage.get(message_id)
        if not msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message_not_found")
        return SimpleResponse(success=True, data={
            "id": msg.id,
            "from_id": msg.from_id,
            "to_id": msg.to_id,
            "encrypted": msg.encrypted,
            "session_key": msg.session_key,
            "timestamp": msg.timestamp,
            "has_phrase": msg.has_phrase,
            "delivered": msg.delivered,
            "read": msg.read
        })

    @router.post("/chat/{contact_id}/phrase", response_model=SimpleResponse)
    async def save_phrase(contact_id: str, data: PhraseRequest, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        chat_manager.set_phrase(user["public_id"], contact_id, data.phrase)
        logger.info(f"Phrase saved for contact {contact_id} by user {user['public_id']}")
        return SimpleResponse(success=True, data={"phrase_known": True})

    @router.delete("/chat/{contact_id}/phrase", response_model=SimpleResponse)
    async def delete_phrase(contact_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        chat_manager.clear_phrase(user["public_id"], contact_id)
        logger.info(f"Phrase cleared for contact {contact_id} by user {user['public_id']}")
        return SimpleResponse(success=True, data={"phrase_known": False})

    @router.get("/chat/{contact_id}/phrase", response_model=SimpleResponse)
    async def get_phrase_status(contact_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        phrase = chat_manager.get_phrase(user["public_id"], contact_id)
        return SimpleResponse(success=True, data={"phrase_known": phrase is not None})

    @router.get("/chat/{contact_id}/page", response_class=HTMLResponse)
    async def chat_page(request: Request, contact_id: str, user: dict = Depends(get_current_user_dep)) -> HTMLResponse:
        token = request.cookies.get("token", "")
        # Удаляем этот вызов - он не нужен для V4
        # if message_router:
        #     message_router.load_dialogs_from_db(user["public_id"])
        return render_template_safe(templates, "chat_full.html",
                                   {"request": request, "user": user, "contact_id": contact_id, "token": token})

    @router.get("/debug/dialogs")
    async def debug_dialogs(user: dict = Depends(get_current_user_dep)) -> dict:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT user_id, contact_id, session_key FROM dialogs")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return {"dialogs": rows, "current_user": user["public_id"]}

    return router
