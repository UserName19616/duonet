# src/server/api/main.py
"""
Главный модуль API, объединяющий все эндпоинты в единое FastAPI приложение.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, List, Optional

from fastapi import FastAPI, HTTPException, Request, status, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Импорты из common
from src.common.identity.account import AccountManager
from src.common.identity.recovery import RecoveryService
from src.common.storage.sqlite import SQLiteStorage
from src.common.utils.geoip import get_region_by_ip

# Импорты из server
from src.server.network.rendezvous.rendezvous_client import RendezvousClient
from src.server.network.network_map import NetworkMapManager
from src.server.network.rendezvous.rendezvous_manager import RendezvousManager
from src.server.network.trust import get_trust_manager
from src.server.network.gossip import GossipProtocol
from src.server.network.rate_limiter import MultiRateLimiter
from src.server.storage.server_db import get_server_db
from src.server.proxy.client_crud import ClientManager

from .auth import create_auth_router
from .charter import create_charter_router
from .contacts import create_contacts_router
from .messages import create_messages_router
from .proxy import create_proxy_router
from .server_db import create_server_db_router
from .websocket import WebSocketManager, websocket_endpoint, set_ws_manager
from .peers import create_peers_router

# Импорты из web
from src.web.auth import create_auth_web_router
from src.web.chat import create_chat_web_router
from src.web.contacts import create_contacts_web_router
from src.web.crypto_log import create_crypto_log_web_router
from src.web.file_transfer import create_file_transfer_web_router
from src.web.monitor import create_monitor_web_router
from src.web.multi_client import create_multi_client_web_router

# Импорты из client (через API)
from src.client.messaging.message_router import MessageRouter
from src.client.storage.contacts import ContactsStorage
from src.client.storage.messages import MessagesStorage

logger = logging.getLogger(__name__)

VERSION = "2.0.0"

_gossip_protocol: Optional[GossipProtocol] = None
_lifespan_ws_manager: Optional[WebSocketManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _gossip_protocol, _lifespan_ws_manager

    # Запускаем cleanup task для WebSocketManager
    if _lifespan_ws_manager:
        await _lifespan_ws_manager.start_cleanup_task()
        logger.info("WebSocketManager cleanup task started")

    if _gossip_protocol:
        await _gossip_protocol.start()
        logger.info("Gossip protocol started")

    yield

    if _gossip_protocol:
        await _gossip_protocol.stop()
        logger.info("Gossip protocol stopped")

    if _lifespan_ws_manager:
        await _lifespan_ws_manager.stop_cleanup_task()
        logger.info("WebSocketManager cleanup task stopped")


def create_app(
    account_manager: AccountManager,
    recovery_service: RecoveryService,
    message_router: MessageRouter,
    client_manager: ClientManager,
    rendezvous_client: RendezvousClient,
    rate_limiter: MultiRateLimiter,
    ws_manager: WebSocketManager,
    jwt_secret: str,
    geoip_func: Callable[[str], str],
    contacts_storage: ContactsStorage,
    messages_storage: MessagesStorage,
    storage: SQLiteStorage,
    network_map: NetworkMapManager,
    rendezvous_manager: Optional[RendezvousManager] = None,
    cors_origins: Optional[List[str]] = None,
    invite_protocol: Any = None,
) -> FastAPI:
    """Создание настроенного FastAPI приложения."""
    global _lifespan_ws_manager
    _lifespan_ws_manager = ws_manager

    app = FastAPI(
        title="DuoNet API",
        description="Decentralized messenger API",
        version=VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS
    origins = cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========== СТАТИЧЕСКИЕ ФАЙЛЫ ==========
    app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

    # ========== ШАБЛОНЫ ==========
    templates = Jinja2Templates(directory="src/web/templates")
    templates.env.cache_size = 0
    if hasattr(templates.env, 'cache'):
        templates.env.cache = {}

    # Отключаем кэш шаблонов
    class NoCache:
        def get(self, key, default=None):
            return default
        def __getitem__(self, key):
            raise KeyError()
        def __setitem__(self, key, value):
            pass
        def __contains__(self, key):
            return False

    templates.env.cache = NoCache()

    # ========== КОМПОНЕНТЫ ==========
    actual_invite_protocol = invite_protocol or message_router._invite_protocol
    spam_protection = actual_invite_protocol._spam_protection

    # Роутеры API
    auth_router = create_auth_router(
        account_manager=account_manager,
        recovery_service=recovery_service,
        rate_limiter=rate_limiter,
    )

    contacts_router = create_contacts_router(
        account_manager=account_manager,
        contacts_storage=contacts_storage,
        rendezvous_client=rendezvous_client,
        invite_protocol=actual_invite_protocol,
        spam_protection=spam_protection,
        ws_manager=ws_manager,
    )

    messages_router = create_messages_router(
        account_manager=account_manager,
        message_router=message_router,
    )

    proxy_router = create_proxy_router(
        account_manager=account_manager,
        client_manager=client_manager,
    )

    charter_router = create_charter_router(
        account_manager=account_manager,
        storage=storage,
    )

    server_db = get_server_db()
    server_db_router = create_server_db_router(server_db)

    # Подключаем API роутеры
    app.include_router(auth_router)
    app.include_router(contacts_router)
    app.include_router(messages_router)
    app.include_router(proxy_router)
    app.include_router(charter_router)
    app.include_router(server_db_router)

    # Веб-роутеры
    auth_web_router = create_auth_web_router(
        account_manager=account_manager,
        recovery_service=recovery_service,
        templates=templates,
    )
    app.include_router(auth_web_router)

    peers_router = create_peers_router(account_manager)
    app.include_router(peers_router)

    # Debug роутер
    from .websocket import debug_router
    app.include_router(debug_router)

    # WebSocket эндпоинт
    @app.websocket("/ws")
    async def websocket_handler(websocket: WebSocket, token: str = None, contact: str = None):
        if token is None:
            token = websocket.query_params.get("token")
        if contact is None:
            contact = websocket.query_params.get("contact")

        logger.info(f"WebSocket request from {websocket.client.host}, token present: {bool(token)}, contact: {contact}")

        await websocket_endpoint(
            websocket=websocket,
            account_manager=account_manager,
            message_router=message_router,
            messages_storage=messages_storage,
            rendezvous_client=rendezvous_client,
            ws_manager=ws_manager,
            token=token,
            contact=contact,
        )

    # Веб-роутеры (продолжение)
    contacts_web_router = create_contacts_web_router(
        account_manager=account_manager,
        storage=storage,
        rendezvous_client=rendezvous_client,
        invite_protocol=actual_invite_protocol,
        spam_protection=spam_protection,
        message_router=message_router,
    )
    app.include_router(contacts_web_router)

    chat_web_router = create_chat_web_router(
        account_manager=account_manager,
        db_path="duonet.db",
        message_router=message_router,
    )
    app.include_router(chat_web_router)

    file_transfer_web_router = create_file_transfer_web_router(
        account_manager=account_manager,
        storage=storage,
        chat_manager=None,
    )
    app.include_router(file_transfer_web_router)

    multi_client_web_router = create_multi_client_web_router(
        account_manager=account_manager,
        storage=storage,
    )
    app.include_router(multi_client_web_router)

    monitor_web_router = create_monitor_web_router(
        account_manager=account_manager,
        network_map=network_map,
        rendezvous_manager=rendezvous_manager,
        api_port=8443,
    )
    app.include_router(monitor_web_router)

    crypto_log_web_router = create_crypto_log_web_router(
        account_manager=account_manager,
        storage=storage,
        message_router=message_router,
    )
    app.include_router(crypto_log_web_router)

    # ========== HEALTH CHECKS ==========
    @app.get("/health")
    async def health_check(request: Request) -> dict:
        return {
            "status": "healthy",
            "version": VERSION,
            "uptime": time.time() - app.state.start_time if hasattr(app.state, "start_time") else 0,
            "load": {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "active_connections": ws_manager.get_connection_count(),
                "proxy_clients": len(client_manager.get_all_clients()),
            },
        }

    @app.get("/ready")
    async def ready_check() -> dict:
        return {"ready": True, "message": None}

    # ========== ОБРАБОТЧИКИ ОШИБОК ==========
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    app.state.start_time = time.time()
    return app


def create_default_app() -> FastAPI:
    """Создание приложения с настройками по умолчанию."""
    from src.common.storage.sqlite import SQLiteStorage
    from src.server.network.rate_limiter import MultiRateLimiter
    from src.common.utils.geoip import get_region_by_ip
    from src.common.identity.account import AccountManager
    from src.common.identity.recovery import RecoveryService
    from src.client.messaging.spam_protection import SpamProtection
    from src.client.messaging.invite import InviteProtocol
    from src.client.messaging.message_router import MessageRouter
    from src.server.network.rendezvous.rendezvous_client import RendezvousClient
    from src.server.proxy.client_crud import ClientManager
    from src.client.storage.contacts import ContactsStorage
    from src.client.storage.messages import MessagesStorage
    from .websocket import WebSocketManager, set_ws_manager
    from src.server.network.network_map import NetworkMapManager
    from src.server.network.rendezvous.rendezvous_manager import RendezvousManager
    from src.common.crypto.keys import generate_keypair_from_seed

    storage = SQLiteStorage("duonet.db")
    rate_limiter = MultiRateLimiter()
    ws_manager = WebSocketManager()

    # Принудительная установка глобального WS_MANAGER
    set_ws_manager(ws_manager)
    logger.info(f"✅ Global WebSocketManager set with {ws_manager.get_connection_count()} connections")

    geoip_func = get_region_by_ip

    import os
    jwt_secret = os.environ.get("JWT_SECRET_KEY", "default_secret_key_change_in_production")

    account_manager = AccountManager(
        storage=storage,
        geoip_func=geoip_func,
        rate_limiter=rate_limiter,
        jwt_secret=jwt_secret,
        ws_manager=ws_manager,
    )

    recovery_service = RecoveryService(storage, account_manager)
    spam_protection = SpamProtection(storage)

    # Подключаем серверную БД для хранения приглашений
    server_db = SQLiteStorage("duonet_server.db")

    invite_protocol = InviteProtocol(
        spam_protection=spam_protection,
        storage=storage,
        server_db=server_db
    )

    rendezvous_url = os.environ.get("RENDEZVOUS_URL", "http://127.0.0.1:9878")
    rendezvous_client = RendezvousClient(rendezvous_url)

    client_manager = ClientManager(storage, account_manager)

    dummy_user_id = b"\x01" * 20
    contacts_storage = ContactsStorage(storage, dummy_user_id)
    messages_storage = MessagesStorage("duonet.db")

    message_router = MessageRouter(
        account_manager=account_manager,
        messages_storage=messages_storage,
        invite_protocol=invite_protocol,
        ws_manager=ws_manager,
        storage=storage,
    )

    network_map = NetworkMapManager(storage, ws_manager)

    # Rendezvous сервер ожидается запущенным отдельно
    rendezvous_manager = None
    logger.info("Rendezvous server is expected to be running externally on port 9878")

    trust_manager = get_trust_manager()
    server_db_obj = get_server_db()

    global _gossip_protocol
    _gossip_protocol = None

    cursor = storage.execute_sql(
        "SELECT server_id, seed_hash FROM accounts WHERE is_server = 1 LIMIT 1"
    )
    row = cursor.fetchone()
    if row:
        server_id = row[0]
        seed_hash = row[1]
        private_key, _ = generate_keypair_from_seed(seed_hash)

        _gossip_protocol = GossipProtocol(
            my_server_id=server_id,
            private_key=private_key,
            db=server_db_obj,
            trust_manager=trust_manager,
            http_client=None,
        )
        logger.info(f"Gossip protocol created for server {server_id}")
    else:
        logger.info("No server account found, gossip protocol not created")

    return create_app(
        account_manager=account_manager,
        recovery_service=recovery_service,
        message_router=message_router,
        client_manager=client_manager,
        rendezvous_client=rendezvous_client,
        rate_limiter=rate_limiter,
        ws_manager=ws_manager,
        jwt_secret=jwt_secret,
        geoip_func=geoip_func,
        contacts_storage=contacts_storage,
        messages_storage=messages_storage,
        storage=storage,
        network_map=network_map,
        rendezvous_manager=rendezvous_manager,
        invite_protocol=invite_protocol,
    )


# Глобальный экземпляр приложения
app = create_default_app()
