# src/api/messages/models.py
"""
Pydantic модели для API сообщений.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from src.config import MAX_TEXT_LENGTH, MAX_FILE_SIZE_BYTES


# =============================================================================
# Базовые модели
# =============================================================================

class SendMessageRequest(BaseModel):
    """Запрос на отправку сообщения."""
    to: str = Field(..., min_length=1, max_length=100)
    encrypted: str = Field(..., min_length=1)  # hex
    session_key: str = Field(..., min_length=64, max_length=64)  # hex
    has_phrase: bool = False
    text_length: Optional[int] = Field(None, ge=0, le=MAX_TEXT_LENGTH)
    file_size: Optional[int] = Field(None, ge=0, le=MAX_FILE_SIZE_BYTES)
    is_file: bool = False
    plaintext_len: Optional[int] = Field(None, ge=0)
    prev_padding: Optional[int] = Field(None, ge=0)
    message_counter: Optional[int] = Field(None, ge=0)


class SendMessageResponse(BaseModel):
    """Ответ на отправку сообщения."""
    success: bool
    message_id: Optional[str] = None
    timestamp: Optional[int] = None
    error: Optional[str] = None
    padding_size: Optional[int] = None
    key_index: Optional[int] = None


class MessageResponse(BaseModel):
    """Ответ с информацией о сообщении."""
    id: str
    from_id: str
    encrypted: str  # hex
    session_key: str  # hex
    timestamp: int
    has_phrase: bool
    delivered: bool
    read: bool
    padding_size: Optional[int] = None
    key_index: Optional[int] = None
    flags: Optional[int] = None
    is_system: Optional[int] = 0
    system_type: Optional[str] = None
    system_data: Optional[str] = None


class PollResponse(BaseModel):
    """Ответ на polling."""
    success: bool
    messages: List[MessageResponse]


class MarkRequest(BaseModel):
    """Запрос на отметку сообщения."""
    message_id: str


class ReadAllResponse(BaseModel):
    """Ответ на отметку всех сообщений."""
    success: bool
    count: int


class UnreadResponse(BaseModel):
    """Ответ с количеством непрочитанных."""
    success: bool
    count: int


# =============================================================================
# LRP модели
# =============================================================================

class RotateKeyRequest(BaseModel):
    """Запрос на смену ключа."""
    contact_id: str = Field(..., min_length=1)


class RotateKeyResponse(BaseModel):
    """Ответ на смену ключа."""
    success: bool
    request_id: Optional[str] = None
    new_key: Optional[str] = None
    new_key_hash: Optional[str] = None
    message_id: Optional[str] = None
    timestamp: Optional[int] = None
    deadline: Optional[int] = None
    cooldown_remaining: Optional[int] = None
    error: Optional[str] = None


class ConfirmKeyRequest(BaseModel):
    """Запрос на подтверждение смены ключа."""
    contact_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)


class ConfirmKeyResponse(BaseModel):
    """Ответ на подтверждение смены ключа."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    my_new_key_hash: Optional[str] = None


class RejectKeyRequest(BaseModel):
    """Запрос на отклонение смены ключа."""
    contact_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)


class RejectKeyResponse(BaseModel):
    """Ответ на отклонение смены ключа."""
    success: bool
    message_id: Optional[str] = None
    reject_count: Optional[int] = None
    blocked_until: Optional[int] = None
    error: Optional[str] = None


class RotationStatusResponse(BaseModel):
    """Ответ со статусом ротации."""
    success: bool
    mode: str
    can_rotate_by_me: bool
    can_rotate_by_peer: bool
    my_cooldown_remaining: int
    peer_cooldown_remaining: int
    unused_keys: int
    need_rotation: bool
    deadline: Optional[int] = None
    deadline_remaining: Optional[int] = None
    pending_request_id: Optional[str] = None
    pending_request: Optional[dict] = None
    reject_counter: Optional[int] = None
    reject_blocked_until: Optional[int] = None


class SystemMessageRequest(BaseModel):
    """Запрос на сохранение системного сообщения."""
    id: str
    from_id: str
    to_id: str
    timestamp: int
    is_system: int = 1
    system_type: str
    system_data: Optional[str] = None
