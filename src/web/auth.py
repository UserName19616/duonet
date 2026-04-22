# src/web/auth.py
"""
Веб-интерфейс для регистрации и входа в систему.
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.common.crypto.hash import verify_password
from src.common.crypto.keys import generate_keypair_from_seed
from src.common.identity.account import AccountManager
from src.common.identity.recovery import RecoveryService
from src.common.charter.signer import sign_charter

logger = logging.getLogger(__name__)


class RegisterWebRequest(BaseModel):
    seed_phrase: str = Field(..., min_length=1, max_length=500)
    password: str = Field(..., min_length=8, max_length=128)
    region: str = Field(..., min_length=2, max_length=2)
    is_server: bool = Field(False)


class LoginWebRequest(BaseModel):
    seed_phrase: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginByIdRequest(BaseModel):
    public_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    seed_phrase: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    expires_at: Optional[int] = None
    public_id: Optional[str] = None
    server_id: Optional[str] = None
    is_server: Optional[bool] = None
    error: Optional[str] = None


def get_current_user(request: Request, account_manager: AccountManager) -> Optional[dict]:
    token = request.cookies.get("token")
    if not token:
        return None
    payload = account_manager.verify_token(token)
    if not payload:
        return None
    return {"public_id": payload["sub"], "account_id": bytes.fromhex(payload.get("account_id", "")),
            "is_server": payload.get("is_server", False)}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def render_template_safe(templates: Jinja2Templates, name: str, context: dict) -> HTMLResponse:
    from jinja2 import Environment, FileSystemLoader
    import os
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), auto_reload=True, cache_size=0)
    env.cache = {}
    template = env.get_template(name)
    content = template.render(**context)
    return HTMLResponse(content=content)


def sign_charter_for_account(account_manager: AccountManager, account_id: bytes, seed_phrase: str, lang: str = "ru") -> bool:
    try:
        private_key = account_manager.get_private_key(account_id, seed_phrase)
        if private_key is None:
            logger.error(f"Failed to get private key for account {account_id.hex()}")
            return False
        success = sign_charter(storage=account_manager._storage, account_id=account_id,
                               private_key=private_key, lang=lang)
        if success:
            logger.info(f"Charter signed for account {account_id.hex()}")
        else:
            logger.error(f"Failed to sign charter for account {account_id.hex()}")
        return success
    except Exception as e:
        logger.error(f"Error signing charter: {e}")
        return False


def create_auth_web_router(account_manager: AccountManager, recovery_service: RecoveryService,
                           templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="", tags=["web"])

    @router.get("/")
    async def root(request: Request):
        user = get_current_user(request, account_manager)
        if user:
            return RedirectResponse(url="/accounts", status_code=302)
        cursor = account_manager._storage.execute_sql("SELECT COUNT(*) FROM accounts")
        count = cursor.fetchone()[0]
        if count > 0:
            return RedirectResponse(url="/accounts", status_code=302)
        return RedirectResponse(url="/charter", status_code=302)

    @router.get("/login")
    async def login_page(request: Request):
        user = get_current_user(request, account_manager)
        if user:
            return RedirectResponse(url="/accounts", status_code=302)
        return RedirectResponse(url="/accounts", status_code=302)

    @router.get("/register")
    async def register_page(request: Request):
        user = get_current_user(request, account_manager)
        if user:
            return RedirectResponse(url="/accounts", status_code=302)
        charter_accepted = request.cookies.get("charter_accepted")
        if not charter_accepted:
            return RedirectResponse(url="/charter", status_code=302)
        return render_template_safe(templates, "register.html", {"request": request, "hide_nav": True})

    @router.get("/logout")
    async def logout(request: Request, response: Response):
        token = request.cookies.get("token")
        if token:
            payload = account_manager.verify_token(token)
            if payload:
                account_manager.clear_session_private_key(payload["sub"])
        response = RedirectResponse(url="/", status_code=302)
        response.delete_cookie("token")
        response.delete_cookie("charter_accepted")
        return response

    @router.get("/chat")
    async def chat_list_page(request: Request):
        user = get_current_user(request, account_manager)
        if not user:
            return RedirectResponse(url="/accounts", status_code=302)
        token = request.cookies.get("token", "")
        # Теперь загружаем dashboard.html вместо contacts_list.html
        return render_template_safe(templates, "dashboard.html", {
            "request": request,
            "user": user,
            "token": token
        })

    @router.get("/dialogs")
    async def dialogs_page(request: Request):
        """Страница со списком диалогов."""
        user = get_current_user(request, account_manager)
        if not user:
            return RedirectResponse(url="/accounts", status_code=302)

        token = request.cookies.get("token", "")
        return render_template_safe(templates, "dialogs.html", {
            "request": request,
            "user": user,
            "token": token
        })

    @router.get("/invites")
    async def invites_page(request: Request):
        user = get_current_user(request, account_manager)
        if not user:
            return RedirectResponse(url="/accounts", status_code=302)
        token = request.cookies.get("token", "")
        return render_template_safe(templates, "invites.html", {"request": request, "user": user, "token": token})

    @router.get("/charter")
    async def charter_page(request: Request, lang: str = "ru"):
        user = get_current_user(request, account_manager)
        if user:
            return RedirectResponse(url="/accounts", status_code=302)
        return render_template_safe(templates, "charter.html", {"request": request, "lang": lang, "hide_nav": True})

    @router.get("/accounts")
    async def accounts_page(request: Request):
        user = get_current_user(request, account_manager)
        if user:
            return RedirectResponse(url="/chat", status_code=302)
        cursor = account_manager._storage.execute_sql("SELECT public_id, server_id, is_server FROM accounts ORDER BY created_at")
        accounts = []
        client_count = 0
        for row in cursor.fetchall():
            public_id, server_id, is_server = row
            accounts.append({"public_id": public_id, "server_id": server_id, "is_server": bool(is_server)})
            if not is_server:
                client_count += 1
        if not accounts:
            return RedirectResponse(url="/charter", status_code=302)
        MAX_CLIENTS = 3
        return render_template_safe(templates, "account_selection.html",
                                   {"request": request, "accounts": accounts, "hide_nav": True,
                                    "client_count": client_count, "max_clients": MAX_CLIENTS,
                                    "can_create_client": client_count < MAX_CLIENTS})

    @router.get("/monitor")
    async def monitor_page(request: Request):
        user = get_current_user(request, account_manager)
        if not user:
            return RedirectResponse(url="/accounts", status_code=302)
        if not user.get("is_server", False):
            return RedirectResponse(url="/chat", status_code=302)
        cursor = account_manager._storage.execute_sql("SELECT server_id FROM accounts WHERE account_id = ?", (user["account_id"],))
        row = cursor.fetchone()
        server_id = row[0] if row else user.get("public_id")
        token = request.cookies.get("token", "")
        return render_template_safe(templates, "monitor.html",
                                   {"request": request, "user": {"public_id": server_id, "is_server": True},
                                    "token": token, "hide_nav": False})

    @router.post("/api/web/charter/accept")
    async def charter_accept(data: dict, request: Request, response: Response):
        accepted = data.get("accepted", False)
        lang = data.get("lang", "ru")
        version = data.get("version", "1.0")
        if not accepted:
            return {"success": False, "error": "Charter not accepted"}
        response.set_cookie(key="charter_accepted", value=f"{lang}:{version}", max_age=3600, path="/")
        return {"success": True, "message": "Charter accepted"}

    @router.post("/api/web/register", response_model=AuthResponse)
    async def register_api(data: RegisterWebRequest, request: Request, response: Response):
        charter_accepted = request.cookies.get("charter_accepted")
        if not charter_accepted:
            return AuthResponse(success=False, error="charter_not_accepted")
        charter_lang = charter_accepted.split(":")[0] if ":" in charter_accepted else "ru"
        result = account_manager.register(seed_phrase=data.seed_phrase, password=data.password,
                                          is_server=data.is_server, client_ip=get_client_ip(request),
                                          region_override=data.region)
        if not result["success"]:
            return AuthResponse(success=False, error=result["error"])

        if data.is_server:
            if result.get("server_account_id"):
                sign_charter_for_account(account_manager, result["server_account_id"], data.seed_phrase, charter_lang)
            if result.get("client_account_id"):
                sign_charter_for_account(account_manager, result["client_account_id"], data.seed_phrase, charter_lang)
            elif result.get("account_id"):
                sign_charter_for_account(account_manager, result["account_id"], data.seed_phrase, charter_lang)
        else:
            if result.get("account_id"):
                sign_charter_for_account(account_manager, result["account_id"], data.seed_phrase, charter_lang)

        if recovery_service:
            recovery_service.setup_recovery(data.seed_phrase, result["account_id"])

        response.delete_cookie("charter_accepted")
        response.delete_cookie("token")
        return AuthResponse(success=True, public_id=result.get("public_id"),
                           server_id=result.get("server_id"), is_server=data.is_server)

    @router.post("/api/web/login", response_model=AuthResponse)
    async def login_api(data: LoginWebRequest, response: Response):
        result = account_manager.login(data.seed_phrase, data.password)
        if not result:
            return AuthResponse(success=False, error="invalid_credentials")
        seed_hash = account_manager._compute_seed_hash(data.seed_phrase.strip())
        private_key, _ = generate_keypair_from_seed(seed_hash)
        account_manager.set_session_private_key(result["public_id"], private_key)
        response.set_cookie(
            key="token",
            value=result["token"],
            httponly=False,
            max_age=result["expires_at"] - int(time.time()),
            path="/",
            samesite="lax",
            secure=True
        )
        return AuthResponse(success=True, token=result["token"], expires_at=result["expires_at"],
                           public_id=result["public_id"], server_id=result["server_id"],
                           is_server=result["is_server"])

    @router.post("/api/web/login-by-id", response_model=AuthResponse)
    async def login_by_id_api(data: LoginByIdRequest, response: Response):
        public_id = data.public_id
        password = data.password
        seed_phrase = data.seed_phrase
        if not public_id or not password or not seed_phrase:
            return AuthResponse(success=False, error="missing_fields")
        cursor = account_manager._storage.execute_sql(
            "SELECT account_id, password_hash, public_id, server_id, is_server, seed_hash "
            "FROM accounts WHERE public_id = ? OR server_id = ?", (public_id, public_id))
        row = cursor.fetchone()
        if not row:
            return AuthResponse(success=False, error="invalid_credentials")
        account_id, password_hash, public_id, server_id, is_server, stored_seed_hash = row
        if not verify_password(password, password_hash):
            return AuthResponse(success=False, error="invalid_credentials")
        computed_seed_hash = account_manager._compute_seed_hash(seed_phrase.strip())
        if computed_seed_hash != stored_seed_hash:
            return AuthResponse(success=False, error="invalid_seed_phrase")
        now = int(time.time())
        account_manager._storage.execute_sql("UPDATE accounts SET last_login_at = ? WHERE account_id = ?", (now, account_id))
        token, expires_at = account_manager._generate_jwt_token(public_id, account_id, bool(is_server))
        private_key, _ = generate_keypair_from_seed(computed_seed_hash)
        account_manager.set_session_private_key(public_id, private_key)
        response.set_cookie(
            key="token",
            value=token,
            httponly=False,  # ← JavaScript должен читать cookie
            max_age=expires_at - now,
            path="/",
            samesite="lax",
            secure=True      # ← для HTTPS
        )
        return AuthResponse(success=True, token=token, expires_at=expires_at,
                           public_id=public_id, server_id=server_id, is_server=bool(is_server))

    return router
