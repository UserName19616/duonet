# src/api/auth.py
"""
API-эндпоинты для аутентификации и управления аккаунтом.

Обеспечивает регистрацию, вход, смену пароля и восстановление доступа.
"""

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

# Исправляем импорт: config на уровень src, а не src.server
from src.config import MAX_CLIENT_ACCOUNTS, MAX_SERVER_ACCOUNTS, RATE_LIMIT_REGISTRATION
from src.common.crypto.hash import verify_password
from src.common.identity.account import AccountManager
from src.common.identity.recovery import RecoveryService
from src.server.network.rate_limiter import MultiRateLimiter

# Константы (локальные для обратной совместимости, но импортированы из config)
MAX_CLIENT_ACCOUNTS = MAX_CLIENT_ACCOUNTS
MAX_SERVER_ACCOUNTS = MAX_SERVER_ACCOUNTS
RATE_LIMIT_REGISTRATION = RATE_LIMIT_REGISTRATION


# =============================================================================
# Pydantic модели
# =============================================================================

class RegisterRequest(BaseModel):
    """Запрос на регистрацию."""
    seed_phrase: str = Field(..., min_length=1, max_length=500)
    password: str = Field(..., min_length=8, max_length=128)
    region: str = Field(..., min_length=2, max_length=2, pattern="^[a-z]{2}$")
    is_server: bool = False


class RegisterResponse(BaseModel):
    """Ответ на регистрацию."""
    success: bool
    public_id: Optional[str] = None
    server_id: Optional[str] = None
    account_id: Optional[str] = None
    region: Optional[str] = None
    recovery_email: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[int] = None
    error: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class LoginRequest(BaseModel):
    """Запрос на вход по сид-фразе."""
    seed_phrase: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginByIdRequest(BaseModel):
    """Запрос на вход по public_id и паролю."""
    public_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Ответ на вход."""
    success: bool
    token: Optional[str] = None
    expires_at: Optional[int] = None
    public_id: Optional[str] = None
    server_id: Optional[str] = None
    is_server: Optional[bool] = None
    error: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    """Запрос на смену пароля."""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class RecoveryRequest(BaseModel):
    """Запрос на восстановление пароля."""
    seed_phrase: str = Field(..., min_length=1)


class RecoveryResetRequest(BaseModel):
    """Запрос на сброс пароля."""
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class VerifyResponse(BaseModel):
    """Ответ на проверку токена."""
    success: bool
    valid: bool
    expires_at: Optional[int] = None
    public_id: Optional[str] = None


class AccountInfoResponse(BaseModel):
    """Информация об аккаунте."""
    public_id: str
    server_id: Optional[str] = None
    region: str
    is_server: bool
    created_at: int
    has_recovery: bool


class AccountResponse(BaseModel):
    """Ответ с информацией об аккаунте."""
    success: bool
    data: Optional[AccountInfoResponse] = None
    error: Optional[str] = None


class ClientLimitResponse(BaseModel):
    """Ответ с информацией о лимите клиентских аккаунтов."""
    success: bool
    client_count: int
    max_clients: int
    remaining: int
    can_create: bool


class ServerLimitResponse(BaseModel):
    """Ответ с информацией о лимите серверных аккаунтов."""
    success: bool
    server_count: int
    max_servers: int
    can_create: bool


class CheckAccountRequest(BaseModel):
    """Запрос на проверку существования аккаунта."""
    seed_phrase: str = Field(..., min_length=1)


class CheckAccountResponse(BaseModel):
    """Ответ на проверку существования аккаунта."""
    exists: bool
    error: Optional[str] = None


# =============================================================================
# Роутер и зависимости
# =============================================================================

def get_client_ip(request: Request) -> str:
    """Извлечение IP клиента из заголовков."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


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


def create_auth_router(
    account_manager: AccountManager,
    recovery_service: RecoveryService,
    rate_limiter: MultiRateLimiter,
) -> APIRouter:
    """
    Создание роутера для эндпоинтов аутентификации.

    Args:
        account_manager: Менеджер аккаунтов.
        recovery_service: Сервис восстановления пароля.
        rate_limiter: Ограничитель запросов.

    Returns:
        Настроенный APIRouter.
    """
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/register", response_model=RegisterResponse)
    async def register(
        request: Request,
        data: RegisterRequest,
    ) -> RegisterResponse:
        """
        Регистрация нового аккаунта.

        Ограничения:
        - 3 регистрации с одного IP за 24 часа
        - Пароль минимум 8 символов
        - Регион — двухбуквенный код
        - Не более 3 клиентских аккаунтов
        - Не более 1 серверного аккаунта
        """
        client_ip = get_client_ip(request)

        # Rate limiting
        if not rate_limiter.check("registration", client_ip):
            return RegisterResponse(
                success=False,
                error="rate_limit_exceeded",
                message="Too many registration attempts from this IP",
            )

        # Регистрация с переданным регионом
        result = account_manager.register(
            seed_phrase=data.seed_phrase,
            password=data.password,
            is_server=data.is_server,
            client_ip=client_ip,
            region_override=data.region,
        )

        if not result["success"]:
            # Если ошибка из-за лимита клиентов
            if result["error"] == "max_clients_reached":
                return RegisterResponse(
                    success=False,
                    error=result["error"],
                    message=result["message"],
                    data={
                        "client_count": result.get("client_count", 0),
                        "max_clients": result.get("max_clients", MAX_CLIENT_ACCOUNTS),
                    },
                )
            # Если ошибка из-за лимита серверов
            if result["error"] == "max_servers_reached":
                return RegisterResponse(
                    success=False,
                    error=result["error"],
                    message=result["message"],
                    data={
                        "server_count": result.get("server_count", 0),
                        "max_servers": result.get("max_servers", MAX_SERVER_ACCOUNTS),
                    },
                )
            return RegisterResponse(
                success=False,
                error=result["error"],
                message=result.get("message"),
            )

        # Настройка восстановления пароля
        email = None
        if recovery_service:
            success, email = recovery_service.setup_recovery(
                data.seed_phrase, result["account_id"]
            )

        # Генерация токена для автоматического входа
        login_result = account_manager.login(data.seed_phrase, data.password)
        token = None
        expires_at = None
        if login_result:
            token = login_result["token"]
            expires_at = login_result["expires_at"]

        return RegisterResponse(
            success=True,
            public_id=result["public_id"],
            server_id=result["server_id"],
            account_id=result["account_id"].hex(),
            region=result["region"],
            recovery_email=email,
            token=token,
            expires_at=expires_at,
        )

    @router.post("/login", response_model=LoginResponse)
    async def login(
        data: LoginRequest,
    ) -> LoginResponse:
        """
        Аутентификация по сид-фразе и паролю.
        """
        result = account_manager.login(data.seed_phrase, data.password)

        if not result:
            return LoginResponse(
                success=False,
                error="invalid_credentials",
            )

        return LoginResponse(
            success=True,
            token=result["token"],
            expires_at=result["expires_at"],
            public_id=result["public_id"],
            server_id=result["server_id"],
            is_server=result["is_server"],
        )

    @router.post("/login-by-id", response_model=LoginResponse)
    async def login_by_id(
        data: LoginByIdRequest,
    ) -> LoginResponse:
        """
        Аутентификация по public_id и паролю (для удобства входа).

        Позволяет входить в аккаунт, зная только public_id и пароль,
        без необходимости вводить сид-фразу.
        """
        # Ищем аккаунт по public_id или server_id
        cursor = account_manager._storage.execute_sql(
            "SELECT account_id, seed_hash, password_hash, public_id, server_id, is_server "
            "FROM accounts WHERE public_id = ? OR server_id = ?",
            (data.public_id, data.public_id)
        )
        row = cursor.fetchone()
        if not row:
            return LoginResponse(
                success=False,
                error="invalid_credentials",
            )

        account_id, seed_hash, password_hash, public_id, server_id, is_server = row

        # Проверяем пароль
        if not verify_password(data.password, password_hash):
            return LoginResponse(
                success=False,
                error="invalid_credentials",
            )

        # Обновляем время последнего входа
        now = int(time.time())
        account_manager._storage.execute_sql(
            "UPDATE accounts SET last_login_at = ? WHERE account_id = ?",
            (now, account_id)
        )

        # Генерируем токен
        token, expires_at = account_manager._generate_jwt_token(
            public_id, account_id, bool(is_server)
        )

        return LoginResponse(
            success=True,
            token=token,
            expires_at=expires_at,
            public_id=public_id,
            server_id=server_id,
            is_server=bool(is_server),
        )

    @router.post("/logout")
    async def logout(
        token: str = Depends(get_auth_token),
    ) -> Dict[str, bool]:
        """
        Выход из системы (отзыв токена).

        В прототипе просто возвращает успех.
        В полной версии здесь будет добавление токена в черный список.
        """
        return {"success": True}

    @router.get("/verify", response_model=VerifyResponse)
    async def verify(
        token: str = Depends(get_auth_token),
    ) -> VerifyResponse:
        """
        Проверка валидности токена.
        """
        payload = account_manager.verify_token(token)

        if not payload:
            return VerifyResponse(
                success=True,
                valid=False,
            )

        return VerifyResponse(
            success=True,
            valid=True,
            expires_at=payload.get("exp"),
            public_id=payload.get("sub"),
        )

    @router.post("/change-password")
    async def change_password(
        data: ChangePasswordRequest,
        token: str = Depends(get_auth_token),
    ) -> Dict[str, bool]:
        """
        Смена пароля.
        """
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        account_id = bytes.fromhex(payload["account_id"])

        success = account_manager.change_password(
            account_id,
            data.old_password,
            data.new_password,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid old password or weak new password",
            )

        return {"success": True}

    @router.post("/recovery/request")
    async def recovery_request(
        data: RecoveryRequest,
    ) -> Dict[str, Any]:
        """
        Запрос восстановления пароля.

        Всегда возвращает success=True для безопасности.
        """
        email = recovery_service.extract_email_from_seed(data.seed_phrase)

        if email:
            recovery_service.request_recovery(email)

        return {"success": True, "message": "If email is associated with an account, recovery link will be sent"}

    @router.post("/recovery/reset")
    async def recovery_reset(
        data: RecoveryResetRequest,
    ) -> Dict[str, bool]:
        """
        Сброс пароля по токену.
        """
        success = recovery_service.reset_password(data.token, data.new_password)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired token",
            )

        return {"success": True}

    @router.get("/account", response_model=AccountResponse)
    async def get_account(
        token: str = Depends(get_auth_token),
    ) -> AccountResponse:
        """
        Получение информации об аккаунте.
        """
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        account_id = bytes.fromhex(payload["account_id"])
        account = account_manager.get_account(account_id)

        if not account:
            return AccountResponse(
                success=False,
                error="Account not found",
            )

        has_recovery = recovery_service.is_recovery_configured(account_id)

        return AccountResponse(
            success=True,
            data=AccountInfoResponse(
                public_id=account.public_id,
                server_id=account.server_id,
                region=account.region,
                is_server=account.is_server,
                created_at=account.created_at,
                has_recovery=has_recovery,
            ),
        )

    @router.get("/accounts")
    async def get_accounts(
        request: Request,
    ) -> List[Dict[str, Any]]:
        """
        Получение списка всех аккаунтов (без авторизации, только для TUI/Web).
        """
        cursor = account_manager._storage.execute_sql(
            "SELECT public_id, server_id, is_server FROM accounts ORDER BY created_at"
        )
        accounts = []
        for row in cursor.fetchall():
            public_id, server_id, is_server = row
            accounts.append({
                "public_id": public_id,
                "server_id": server_id,
                "is_server": bool(is_server),
            })

        return accounts

    @router.get("/client-limit", response_model=ClientLimitResponse)
    async def get_client_limit(
        token: str = Depends(get_auth_token),
    ) -> ClientLimitResponse:
        """
        Получение информации о лимите клиентских аккаунтов.
        """
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        client_count = account_manager.count_client_accounts()

        return ClientLimitResponse(
            success=True,
            client_count=client_count,
            max_clients=MAX_CLIENT_ACCOUNTS,
            remaining=max(0, MAX_CLIENT_ACCOUNTS - client_count),
            can_create=client_count < MAX_CLIENT_ACCOUNTS,
        )

    @router.get("/server-limit", response_model=ServerLimitResponse)
    async def get_server_limit(
        token: str = Depends(get_auth_token),
    ) -> ServerLimitResponse:
        """
        Получение информации о лимите серверных аккаунтов.
        """
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        server_count = account_manager.count_server_accounts()

        return ServerLimitResponse(
            success=True,
            server_count=server_count,
            max_servers=MAX_SERVER_ACCOUNTS,
            can_create=server_count < MAX_SERVER_ACCOUNTS,
        )

    @router.post("/check-account", response_model=CheckAccountResponse)
    async def check_account_exists(
        data: CheckAccountRequest,
    ) -> CheckAccountResponse:
        """
        Проверка существования аккаунта по сид-фразе (без авторизации).
        """
        seed_phrase = data.seed_phrase.strip()
        if not seed_phrase:
            return CheckAccountResponse(exists=False, error="empty_seed")

        seed_hash = account_manager._compute_seed_hash(seed_phrase)
        account_id = account_manager._account_id_from_seed_hash(seed_hash)

        cursor = account_manager._storage.execute_sql(
            "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
        )
        exists = cursor.fetchone() is not None

        return CheckAccountResponse(exists=exists)

    return router
