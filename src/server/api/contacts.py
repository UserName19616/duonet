# src/server/api/contacts.py
"""
API-эндпоинты для управления контактами пользователя.

Обеспечивает поиск, добавление, удаление и обновление локальных имен контактов.
"""

import hashlib
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

# Исправляем импорты: identity из common, а не из server
from src.common.identity.account import AccountManager
from src.common.identity.public_id import is_client_id, is_server_id, is_valid_format
from src.client.messaging.invite import InviteProtocol
from src.client.messaging.spam_protection import SpamProtection
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.client.storage.contacts import ContactInfo, ContactsStorage
from src.server.api.websocket import get_ws_manager

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic модели
# =============================================================================

class ContactResponse(BaseModel):
    """Ответ с информацией о контакте."""
    public_id: str
    name: str
    added_at: int
    last_message: Optional[str] = None
    last_message_time: Optional[int] = None
    unread: int = 0
    online: bool = False
    phrase_known: bool = False


class ContactsListResponse(BaseModel):
    """Ответ со списком контактов."""
    success: bool
    contacts: List[ContactResponse]


class SearchResult(BaseModel):
    """Результат поиска."""
    public_id: str
    type: str  # "client" или "server"
    online: bool
    trust_score: Optional[float] = None
    region: Optional[str] = None
    load: Optional[int] = None  # для серверов


class SearchResponse(BaseModel):
    """Ответ на поиск."""
    success: bool
    results: List[SearchResult]


class AddContactRequest(BaseModel):
    """Запрос на добавление контакта."""
    public_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=64)


class UpdateContactRequest(BaseModel):
    """Запрос на обновление контакта."""
    name: Optional[str] = Field(None, min_length=1, max_length=64)


class SetPhraseRequest(BaseModel):
    """Запрос на установку дополнительной фразы."""
    phrase: str = Field(..., min_length=1, max_length=200)


class SimpleResponse(BaseModel):
    """Простой ответ."""
    success: bool
    name: Optional[str] = None
    phrase_known: Optional[bool] = None
    count: Optional[int] = None


# =============================================================================
# Создание роутера
# =============================================================================

def create_contacts_router(
    account_manager: AccountManager,
    contacts_storage: ContactsStorage,
    rendezvous_client: RendezvousClient,
    invite_protocol: InviteProtocol,
    spam_protection: SpamProtection,
    ws_manager: Any = None,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов контактов.

    Args:
        account_manager: Менеджер аккаунтов.
        contacts_storage: Хранилище контактов.
        rendezvous_client: Клиент сервера знакомств.
        invite_protocol: Протокол приглашений.
        spam_protection: Защита от спама.
        ws_manager: Менеджер WebSocket (опционально).

    Returns:
        Настроенный APIRouter.
    """
    router = APIRouter(prefix="/api", tags=["contacts"])

    # =========================================================================
    # Вспомогательные функции с замыканием на account_manager
    # =========================================================================

    def get_auth_token(authorization: Optional[str] = Header(None)) -> str:
        """Извлечение токена из заголовка Authorization."""
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization header",
            )
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format",
            )
        return authorization[7:]

    def get_current_user_id(token: str = Depends(get_auth_token)) -> bytes:
        """Получение account_id текущего пользователя из токена."""
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        account_id_hex = payload.get("account_id")
        if not account_id_hex:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing account_id",
            )
        return bytes.fromhex(account_id_hex)

    def get_current_public_id(token: str = Depends(get_auth_token)) -> str:
        """Получение public_id текущего пользователя из токена."""
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return payload["sub"]

    def get_user_contacts(user_id: bytes) -> ContactsStorage:
        """Получение хранилища контактов для пользователя."""
        return ContactsStorage(contacts_storage._storage, user_id)

    # =========================================================================
    # Эндпоинты
    # =========================================================================

    @router.get("/search", response_model=SearchResponse)
    async def search(
        q: str,
        token: str = Depends(get_auth_token),
    ) -> SearchResponse:
        """
        Поиск контактов по Public ID, email или маске региона.

        Поддерживает:
        - Public ID: @XXXX-XXXX-XXXX.ru
        - Маска региона: @*.ru, @*.ru.srv
        """
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        if not q:
            return SearchResponse(success=False, results=[])

        # Проверка на маску региона
        if q.startswith("@*."):
            result = rendezvous_client.resolve_contact(q)
            if result and result.get("type") == "list":
                items = result.get("items", [])
                results = []
                for item in items:
                    results.append(SearchResult(
                        public_id=item.get("public_id", ""),
                        type=item.get("type", "server"),
                        online=False,
                        region=item.get("region"),
                        load=item.get("load"),
                    ))
                return SearchResponse(success=True, results=results)

        # Поиск по Public ID
        if is_valid_format(q):
            if is_server_id(q):
                server = rendezvous_client.find_server_by_id(q)
                if server:
                    return SearchResponse(
                        success=True,
                        results=[SearchResult(
                            public_id=server["public_id"],
                            type=server["type"],
                            online=False,
                            region=server.get("region"),
                            load=server.get("load"),
                        )],
                    )
            else:
                # Для клиентских ID возвращаем пустой результат
                return SearchResponse(success=True, results=[])

        return SearchResponse(success=True, results=[])

    @router.get("/contacts", response_model=ContactsListResponse)
    async def get_contacts(
        current_user_id: bytes = Depends(get_current_user_id),
        current_public_id: str = Depends(get_current_public_id),
    ) -> ContactsListResponse:
        """
        Получение списка контактов пользователя.
        """
        storage = get_user_contacts(current_user_id)
        contacts = storage.get_all()

        # Получаем WebSocketManager для проверки online статуса
        ws_manager_instance = get_ws_manager()

        result = []

        for contact in contacts:
            # Проверяем онлайн статус через WebSocketManager
            online = False
            if ws_manager_instance:
                online = ws_manager_instance.get_connection(contact.public_id) is not None
            phrase_known = contact.phrase_hash is not None

            result.append(ContactResponse(
                public_id=contact.public_id,
                name=contact.name,
                added_at=contact.added_at,
                online=online,
                phrase_known=phrase_known,
            ))

        return ContactsListResponse(success=True, contacts=result)

    @router.get("/dialogs", response_model=ContactsListResponse)
    async def get_dialogs(
        current_user_id: bytes = Depends(get_current_user_id),
        current_public_id: str = Depends(get_current_public_id),
    ) -> ContactsListResponse:
        """
        Получение списка диалогов (для TUI) из таблицы dialogs.
        """
        import sqlite3

        conn = sqlite3.connect("duonet.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT DISTINCT
                CASE
                    WHEN user_id = ? THEN contact_id
                    ELSE user_id
                END as contact_id
            FROM dialogs
            WHERE user_id = ? OR contact_id = ?
        """, (current_public_id, current_public_id, current_public_id))

        ws_manager_instance = get_ws_manager()

        results = []
        for row in cursor.fetchall():
            contact_id = row["contact_id"]
            # Пропускаем самого себя
            if contact_id == current_public_id:
                continue

            # Проверяем онлайн статус через WebSocketManager
            online = False
            if ws_manager_instance:
                online = ws_manager_instance.get_connection(contact_id) is not None

            results.append(ContactResponse(
                public_id=contact_id,
                name=contact_id,  # Временно используем public_id как имя
                added_at=0,
                online=online,
                phrase_known=False,
            ))

        conn.close()
        return ContactsListResponse(success=True, contacts=results)

    @router.post("/contacts", response_model=SimpleResponse)
    async def add_contact(
        data: AddContactRequest,
        current_user_id: bytes = Depends(get_current_user_id),
        current_public_id: str = Depends(get_current_public_id),
    ) -> SimpleResponse:
        """
        Добавление контакта.
        """
        public_id = data.public_id

        # Проверка: нельзя добавить себя
        if public_id == current_public_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot_add_self",
            )

        # Проверка: нельзя добавить сервер (ID с .srv)
        if is_server_id(public_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot_add_server",
            )

        # Проверка формата
        if not is_valid_format(public_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_public_id",
            )

        storage = get_user_contacts(current_user_id)
        success = storage.add(public_id, data.name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contact_already_exists",
            )

        return SimpleResponse(success=True)

    @router.delete("/contacts/{public_id}", response_model=SimpleResponse)
    async def delete_contact(
        public_id: str,
        current_user_id: bytes = Depends(get_current_user_id),
    ) -> SimpleResponse:
        """
        Удаление контакта.
        """
        storage = get_user_contacts(current_user_id)
        success = storage.delete(public_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="contact_not_found",
            )

        return SimpleResponse(success=True)

    @router.patch("/contacts/{public_id}", response_model=SimpleResponse)
    async def update_contact(
        public_id: str,
        data: UpdateContactRequest,
        current_user_id: bytes = Depends(get_current_user_id),
    ) -> SimpleResponse:
        """
        Обновление локального имени контакта.
        """
        if data.name is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name_required",
            )

        storage = get_user_contacts(current_user_id)
        success = storage.update_name(public_id, data.name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="contact_not_found",
            )

        return SimpleResponse(success=True, name=data.name)

    @router.post("/contacts/{public_id}/phrase", response_model=SimpleResponse)
    async def set_phrase(
        public_id: str,
        data: SetPhraseRequest,
        current_user_id: bytes = Depends(get_current_user_id),
    ) -> SimpleResponse:
        """
        Установка дополнительной фразы для контакта.
        """
        # Вычисляем хеш фразы (первые 16 символов SHA256)
        phrase_hash = hashlib.sha256(data.phrase.encode()).hexdigest()[:16]

        storage = get_user_contacts(current_user_id)
        success = storage.set_phrase_hash(public_id, phrase_hash)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="contact_not_found",
            )

        return SimpleResponse(success=True, phrase_known=True)

    @router.delete("/contacts/{public_id}/phrase", response_model=SimpleResponse)
    async def delete_phrase(
        public_id: str,
        current_user_id: bytes = Depends(get_current_user_id),
    ) -> SimpleResponse:
        """
        Удаление дополнительной фразы для контакта.
        """
        storage = get_user_contacts(current_user_id)
        success = storage.set_phrase_hash(public_id, None)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="contact_not_found",
            )

        return SimpleResponse(success=True)

    return router
