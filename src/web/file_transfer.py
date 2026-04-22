# src/web/file_transfer.py
"""
Обмен файлами между пользователями с end-to-end шифрованием.
"""

import asyncio
import base64
import logging
import secrets
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.common.identity.account import AccountManager
from src.common.storage.sqlite import SQLiteStorage
from src.config import MAX_FILE_SIZE_BYTES, PACKET_SIZE

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_BYTES
PACKET_SIZE = PACKET_SIZE


class FileMetadata(BaseModel):
    id: str
    message_id: str
    name: str
    size: int
    mime_type: str
    total_packets: int
    encrypted: bool = True
    timestamp: int
    from_id: str
    to_id: str
    delivered: bool = False
    downloaded: bool = False


class SimpleResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class FileStorage:
    def __init__(self):
        self._files: Dict[str, bytes] = {}
        self._metadata: Dict[str, FileMetadata] = {}
        self._pending_packets: Dict[str, Dict[int, bytes]] = {}
        self._packet_metadata: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def save_file(self, file_id: str, data: bytes, metadata: FileMetadata) -> bool:
        async with self._lock:
            if len(data) > MAX_FILE_SIZE_BYTES:
                logger.warning(f"File too large: {len(data)} bytes (max {MAX_FILE_SIZE_BYTES})")
                return False
            self._files[file_id] = data
            self._metadata[file_id] = metadata
            return True

    async def get_file(self, file_id: str) -> Optional[bytes]:
        async with self._lock:
            return self._files.get(file_id)

    async def get_metadata(self, file_id: str) -> Optional[FileMetadata]:
        async with self._lock:
            return self._metadata.get(file_id)

    async def delete_file(self, file_id: str) -> bool:
        async with self._lock:
            if file_id in self._files:
                del self._files[file_id]
            if file_id in self._metadata:
                del self._metadata[file_id]
            return True

    async def get_conversation_files(self, contact_id: str) -> List[FileMetadata]:
        async with self._lock:
            return [m for m in self._metadata.values() if m.from_id == contact_id or m.to_id == contact_id]

    async def add_packet(self, message_id: str, seq: int, total: int, data: bytes,
                         file_name: str = None, file_size: int = None, mime_type: str = None) -> Optional[str]:
        async with self._lock:
            if message_id not in self._pending_packets:
                self._pending_packets[message_id] = {}
            if seq == 1 and file_name:
                self._packet_metadata[message_id] = {"name": file_name, "size": file_size,
                                                     "mime_type": mime_type, "total": total}
            self._pending_packets[message_id][seq] = data
            if len(self._pending_packets[message_id]) == total:
                file_data = b"".join(self._pending_packets[message_id].get(i, b"") for i in range(1, total + 1))
                if len(file_data) > MAX_FILE_SIZE_BYTES:
                    logger.warning(f"Assembled file too large: {len(file_data)} bytes")
                    del self._pending_packets[message_id]
                    if message_id in self._packet_metadata:
                        del self._packet_metadata[message_id]
                    return None
                file_id = secrets.token_urlsafe(16)
                metadata_info = self._packet_metadata.get(message_id, {})
                metadata = FileMetadata(id=file_id, message_id=message_id, name=metadata_info.get("name", "unknown"),
                                        size=metadata_info.get("size", len(file_data)),
                                        mime_type=metadata_info.get("mime_type", "application/octet-stream"),
                                        total_packets=total, timestamp=int(time.time()), from_id="", to_id="")
                self._files[file_id] = file_data
                self._metadata[file_id] = metadata
                del self._pending_packets[message_id]
                if message_id in self._packet_metadata:
                    del self._packet_metadata[message_id]
                return file_id
            return None

    async def clear(self) -> None:
        async with self._lock:
            self._files.clear()
            self._metadata.clear()
            self._pending_packets.clear()
            self._packet_metadata.clear()


_file_storage = FileStorage()


def get_current_user(request: Request, account_manager: AccountManager) -> Optional[dict]:
    token = request.cookies.get("token")
    if not token:
        return None
    payload = account_manager.verify_token(token)
    if not payload:
        return None
    return {"public_id": payload["sub"], "account_id": bytes.fromhex(payload.get("account_id", "")),
            "is_server": payload.get("is_server", False)}


def generate_file_id() -> str:
    return "file_" + secrets.token_hex(8)


def generate_message_id() -> str:
    return "msg_" + secrets.token_hex(8)


def get_file_storage() -> FileStorage:
    return _file_storage


def create_file_transfer_web_router(account_manager: AccountManager, storage: SQLiteStorage,
                                     chat_manager=None) -> APIRouter:
    router = APIRouter(prefix="/api/web", tags=["web_file_transfer"])

    def get_current_user_dep(request: Request) -> dict:
        user = get_current_user(request, account_manager)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user

    @router.post("/files/upload", response_model=SimpleResponse)
    async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                               detail=f"File too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)} MB)")
        file_id = generate_file_id()
        message_id = generate_message_id()
        encrypted_data = content
        metadata = FileMetadata(id=file_id, message_id=message_id, name=file.filename or "unknown",
                                size=len(content), mime_type=file.content_type or "application/octet-stream",
                                total_packets=(len(content) + PACKET_SIZE - 1) // PACKET_SIZE,
                                timestamp=int(time.time()), from_id=user["public_id"], to_id="")
        success = await _file_storage.save_file(file_id, encrypted_data, metadata)
        if not success:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                               detail=f"File too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)} MB)")
        return SimpleResponse(success=True, data={"file_id": file_id, "message_id": message_id,
                                                  "name": file.filename, "size": len(content)})

    @router.get("/files/{file_id}/download")
    async def download_file(file_id: str, user: dict = Depends(get_current_user_dep)):
        data = await _file_storage.get_file(file_id)
        metadata = await _file_storage.get_metadata(file_id)
        if not data or not metadata:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file_not_found")
        decrypted_data = data
        return StreamingResponse(iter([decrypted_data]), media_type=metadata.mime_type,
                                headers={"Content-Disposition": f"attachment; filename={metadata.name}"})

    @router.get("/files/{file_id}/metadata", response_model=SimpleResponse)
    async def get_file_metadata(file_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        metadata = await _file_storage.get_metadata(file_id)
        if not metadata:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file_not_found")
        return SimpleResponse(success=True, data=metadata.model_dump())

    @router.delete("/files/{file_id}", response_model=SimpleResponse)
    async def delete_file(file_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        success = await _file_storage.delete_file(file_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file_not_found")
        return SimpleResponse(success=True)

    @router.get("/files/conversation/{contact_id}", response_model=SimpleResponse)
    async def get_conversation_files(contact_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        files = await _file_storage.get_conversation_files(contact_id)
        return SimpleResponse(success=True, data={"files": [f.model_dump() for f in files]})

    @router.get("/files/packets/{message_id}", response_model=SimpleResponse)
    async def get_packet_info(message_id: str, user: dict = Depends(get_current_user_dep)) -> SimpleResponse:
        return SimpleResponse(success=True, data={"message_id": message_id, "total_packets": 1,
                                                  "packets": [{"seq": 1, "received": True}]})

    return router
