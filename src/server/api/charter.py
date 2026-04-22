# src/server/api/charter.py
"""
API-эндпоинты для работы с Уставом.
Поддерживает подписание Устава как серверными, так и клиентскими аккаунтами.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

# Исправляем импорт: charter из common, а не из server
from src.common.charter import (
    get_charter_text,
    get_charter_title,
    get_charter_version,
    get_charter_hash,
    sign_charter,
    check_charter_accepted,
    get_charter_signature,
    init_charter_table,
)
from src.common.crypto.keys import generate_keypair_from_seed, hash_sha256
from src.common.identity.account import AccountManager
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic модели
# =============================================================================

class CharterTextResponse(BaseModel):
    """Ответ с текстом Устава."""
    success: bool
    version: str
    title: str
    text: str
    lang: str


class CharterAcceptRequest(BaseModel):
    """Запрос на принятие Устава."""
    seed_phrase: str = Field(..., min_length=1)
    lang: str = Field("ru", min_length=2, max_length=2)
    account_type: str = Field("server", pattern="^(server|client)$")  # какой аккаунт подписывает


class CharterAcceptResponse(BaseModel):
    """Ответ на принятие Устава."""
    success: bool
    signature: Optional[str] = None
    account_id: Optional[str] = None
    account_type: Optional[str] = None
    error: Optional[str] = None


class CharterStatusResponse(BaseModel):
    """Статус принятия Устава."""
    success: bool
    accepted: bool
    version: Optional[str] = None
    signature: Optional[str] = None
    account_type: Optional[str] = None


# =============================================================================
# Создание роутера
# =============================================================================

def create_charter_router(
    account_manager: AccountManager,
    storage: SQLiteStorage,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов Устава.
    """
    # Инициализируем таблицу charter_acceptances
    init_charter_table(storage)

    router = APIRouter(prefix="/api/charter", tags=["charter"])

    @router.get("/text", response_model=CharterTextResponse)
    async def get_charter(lang: str = "ru") -> CharterTextResponse:
        """
        Получение текста Устава.
        """
        return CharterTextResponse(
            success=True,
            version=get_charter_version(),
            title=get_charter_title(lang),
            text=get_charter_text(lang),
            lang=lang,
        )

    @router.post("/accept", response_model=CharterAcceptResponse)
    async def accept_charter(data: CharterAcceptRequest) -> CharterAcceptResponse:
        """
        Принятие Устава — подписание приватным ключом аккаунта.

        Поддерживает:
        - account_type="server" — подпись серверным аккаунтом (.srv)
        - account_type="client" — подпись клиентским аккаунтом
        """
        # Получаем хеш сид-фразы
        seed_hash = hash_sha256(data.seed_phrase.encode())

        # Ищем аккаунт по seed_hash и типу
        is_server = (data.account_type == "server")

        cursor = account_manager._storage.execute_sql(
            "SELECT account_id FROM accounts WHERE seed_hash = ? AND is_server = ?",
            (seed_hash, 1 if is_server else 0)
        )
        row = cursor.fetchone()

        if not row:
            return CharterAcceptResponse(
                success=False,
                error="account_not_found",
                account_type=data.account_type,
            )

        account_id = row[0]

        # Получаем полную информацию об аккаунте
        account = account_manager.get_account(account_id)
        if not account:
            return CharterAcceptResponse(
                success=False,
                error="account_not_found",
                account_type=data.account_type,
            )

        # Проверяем соответствие типа
        if is_server and not account.is_server:
            return CharterAcceptResponse(
                success=False,
                error="not_server_account",
                account_type=data.account_type,
            )
        if not is_server and account.is_server:
            return CharterAcceptResponse(
                success=False,
                error="not_client_account",
                account_type=data.account_type,
            )

        # Проверяем, не принимал ли уже Устав на этом языке
        if check_charter_accepted(storage, account_id, data.lang):
            signature = get_charter_signature(storage, account_id, data.lang)
            return CharterAcceptResponse(
                success=True,
                signature=signature,
                account_id=account_id.hex(),
                account_type=data.account_type,
            )

        # Генерируем приватный ключ из seed_hash
        private_key, _ = generate_keypair_from_seed(seed_hash)

        # Подписываем Устав
        success = sign_charter(
            storage=storage,
            account_id=account_id,
            private_key=private_key,
            lang=data.lang,
        )

        if not success:
            return CharterAcceptResponse(
                success=False,
                error="signature_failed",
                account_type=data.account_type,
            )

        signature = get_charter_signature(storage, account_id, data.lang)

        logger.info(f"Charter accepted by {data.account_type} account {account_id.hex()}")

        return CharterAcceptResponse(
            success=True,
            signature=signature,
            account_id=account_id.hex(),
            account_type=data.account_type,
        )

    @router.get("/status", response_model=CharterStatusResponse)
    async def get_charter_status(
        seed_phrase: str,
        lang: str = "ru",
        account_type: str = "server",
    ) -> CharterStatusResponse:
        """
        Проверка, принимал ли аккаунт Устав.

        Args:
            seed_phrase: Сид-фраза
            lang: Язык Устава
            account_type: "server" или "client"
        """
        # Получаем хеш сид-фразы
        seed_hash = hash_sha256(seed_phrase.encode())

        # Ищем аккаунт по seed_hash и типу
        is_server = (account_type == "server")

        cursor = account_manager._storage.execute_sql(
            "SELECT account_id FROM accounts WHERE seed_hash = ? AND is_server = ?",
            (seed_hash, 1 if is_server else 0)
        )
        row = cursor.fetchone()

        if not row:
            return CharterStatusResponse(
                success=False,
                accepted=False,
                account_type=account_type,
            )

        account_id = row[0]

        # Получаем полную информацию об аккаунте
        account = account_manager.get_account(account_id)
        if not account:
            return CharterStatusResponse(
                success=False,
                accepted=False,
                account_type=account_type,
            )

        # Проверяем соответствие типа
        if is_server and not account.is_server:
            return CharterStatusResponse(
                success=False,
                accepted=False,
                account_type=account_type,
            )
        if not is_server and account.is_server:
            return CharterStatusResponse(
                success=False,
                accepted=False,
                account_type=account_type,
            )

        accepted = check_charter_accepted(storage, account_id, lang)
        signature = get_charter_signature(storage, account_id, lang) if accepted else None

        return CharterStatusResponse(
            success=True,
            accepted=accepted,
            version=get_charter_version() if accepted else None,
            signature=signature,
            account_type=account_type,
        )

    @router.get("/by-account/{account_id}")
    async def get_charter_by_account_id(
        account_id: str,
        lang: str = "ru",
    ) -> dict:
        """
        Получение статуса Устава по ID аккаунта (для внутреннего использования).
        """
        try:
            account_id_bytes = bytes.fromhex(account_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_account_id",
            )

        accepted = check_charter_accepted(storage, account_id_bytes, lang)
        signature = get_charter_signature(storage, account_id_bytes, lang) if accepted else None

        return {
            "success": True,
            "accepted": accepted,
            "signature": signature,
            "account_id": account_id,
            "lang": lang,
        }

    return router
