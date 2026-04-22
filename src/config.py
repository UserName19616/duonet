# src/config.py
"""
Глобальные конфигурационные константы DuoNet
Все лимиты и настройки в одном месте
"""

import os
from enum import Enum
from pathlib import Path

# =============================================================================
# РЕЖИМЫ ЗАПУСКА
# =============================================================================

class DuoNetMode(Enum):
    """Режимы работы DuoNet."""
    SERVER = "server"      # только серверная логика (маршрутизация, прокси, gossip)
    CLIENT = "client"      # только клиентская логика (TUI, сообщения)
    FULL = "full"          # всё вместе (как сейчас, для разработки)
    WEB = "web"            # веб-демонстрация (требует оба компонента)

# Текущий режим из переменной окружения
DUONET_MODE = os.environ.get("DUONET_MODE", "full").lower()

# Нормализуем значение
if DUONET_MODE == "server":
    CURRENT_MODE = DuoNetMode.SERVER
elif DUONET_MODE == "client":
    CURRENT_MODE = DuoNetMode.CLIENT
elif DUONET_MODE == "web":
    CURRENT_MODE = DuoNetMode.WEB
else:
    CURRENT_MODE = DuoNetMode.FULL

# =============================================================================
# ПУТИ К БАЗАМ ДАННЫХ
# =============================================================================

BASE_DIR = Path(__file__).parent.parent

# Клиентская БД (аккаунты, контакты, сообщения, диалоги, rotation_state)
if CURRENT_MODE == DuoNetMode.SERVER:
    CLIENT_DB_PATH = None  # серверный режим не использует клиентскую БД
elif CURRENT_MODE == DuoNetMode.CLIENT:
    CLIENT_DB_PATH = str(BASE_DIR / "duonet_client.db")
else:  # FULL или WEB
    CLIENT_DB_PATH = str(BASE_DIR / "duonet.db")

# Серверная БД (серверы, клиенты, пиры, приглашения, карта сети)
if CURRENT_MODE == DuoNetMode.CLIENT:
    SERVER_DB_PATH = None  # клиентский режим не использует серверную БД
else:
    SERVER_DB_PATH = str(BASE_DIR / "duonet_server.db")

# =============================================================================
# ЛИМИТЫ СООБЩЕНИЙ
# =============================================================================

MAX_TEXT_LENGTH = 4096
MAX_FILE_SIZE_MB = 12
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
PACKET_SIZE = 65536
MAX_PACKETS = MAX_FILE_SIZE_BYTES // PACKET_SIZE + 1

# =============================================================================
# PADDING
# =============================================================================

PAD_MIN = 32
PAD_RANGE = 96
PAD_BOOST_SHORT = 32
PAD_MAX_LONG = 192
LONG_MESSAGE_THRESHOLD = 200

# =============================================================================
# СЕТЕВЫЕ ПОРТЫ
# =============================================================================

DEFAULT_API_PORT = 8443
DEFAULT_RENDEZVOUS_PORT = 9878
DEFAULT_PROXY_PORT = 9879

# =============================================================================
# КРИПТОГРАФИЯ
# =============================================================================

JWT_EXPIRATION_SECONDS = 604800
JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MIN_SEED_PHRASE_LENGTH = 1

# =============================================================================
# ЛИМИТЫ АККАУНТОВ
# =============================================================================

MAX_CLIENT_ACCOUNTS = 3
MAX_SERVER_ACCOUNTS = 1

# =============================================================================
# RATE LIMITING
# =============================================================================

RATE_LIMIT_REGISTRATION = 3
RATE_LIMIT_REGISTRATION_PERIOD = 86400

RATE_LIMIT_INVITE = 50
RATE_LIMIT_INVITE_PERIOD = 86400

RATE_LIMIT_SEND_MESSAGE = 60
RATE_LIMIT_SEND_MESSAGE_PERIOD = 60

RATE_LIMIT_CONNECT = 10
RATE_LIMIT_CONNECT_PERIOD = 60

# =============================================================================
# INVITE PROTOCOL
# =============================================================================

INVITE_TTL_SECONDS = 604800
INVITE_TIMESTAMP_MAX_AGE = 3600
MAX_INVITE_MESSAGE_LEN = 200

# =============================================================================
# GOSSIP PROTOCOL
# =============================================================================

GOSSIP_INTERVAL = 60
GOSSIP_TIMEOUT = 10
GOSSIP_MAX_PEERS = 10

# =============================================================================
# СЕТЬ И ТАЙМАУТЫ
# =============================================================================

WS_HEARTBEAT_INTERVAL = 45
WS_IDLE_TIMEOUT = 300
SERVER_TTL_SECONDS = 3600
CLEANUP_INTERVAL_SECONDS = 600
PFS_ROTATE_INTERVAL = 100
PFS_CONFIRM_TIMEOUT = 30
PFS_MAX_RETRIES = 3

# =============================================================================
# КАРТА СЕТИ (Network Map)
# =============================================================================

NODE_TTL_SECONDS = 300
NETWORK_CLEANUP_INTERVAL_SECONDS = 60
NETWORK_SYNC_INTERVAL_SECONDS = 60
MAX_NODES = 100

# Алиасы для обратной совместимости с network_map.py
SYNC_INTERVAL_SECONDS = NETWORK_SYNC_INTERVAL_SECONDS

# =============================================================================
# РОТАЦИЯ КЛЮЧЕЙ (V2 с ECDH)
# =============================================================================

# Таймаут запроса на ротацию (24 часа)
ROTATION_TIMEOUT = 86400

# Cooldown между ротациями (24 часа)
ROTATION_COOLDOWN = 86400

# Алиасы для обратной совместимости с LRP (удалено, но оставляем для плавного перехода)
LRP_ROTATION_COOLDOWN = ROTATION_COOLDOWN
LRP_ROTATION_TIMEOUT = ROTATION_TIMEOUT
LRP_ACTIVE_POOL_SIZE = 8
LRP_PENDING_POOL_SIZE = 8
LRP_TOTAL_POOL_SIZE = 16
LRP_KEY_HISTORY_SIZE = 5
LRP_MAX_REJECTS_BEFORE_BLOCK = 3
LRP_REJECT_BLOCK_DURATION = 86400

# =============================================================================
# ПРОКСИ
# =============================================================================

PROXY_MAX_CLIENTS = 10
PROXY_DAILY_LIMIT_BASIC_MB = 1024
PROXY_DAILY_LIMIT_STANDARD_MB = 5120
PROXY_DEFAULT_GROUP = "basic"
PROXY_INVITE_TTL_DEFAULT = 86400
PROXY_REQUEST_TIMEOUT_SECONDS = 30
PROXY_MAX_RESPONSE_SIZE_MB = 50

# =============================================================================
# БАЛАНСИРОВЩИК НАГРУЗКИ
# =============================================================================

LOAD_WARNING_THRESHOLD = 0.80
LOAD_CRITICAL_THRESHOLD = 0.90
LOAD_CHECK_INTERVAL = 60
METRICS_HISTORY_SIZE = 10
CLIENT_RECONNECT_DELAY_MS = 3000

# =============================================================================
# TRUST SYSTEM
# =============================================================================

TRUST_LEVEL_UNKNOWN = 0
TRUST_LEVEL_QUARANTINE = 1
TRUST_LEVEL_TRUSTED = 2
TRUST_LEVEL_PRIVILEGED = 3

QUARANTINE_DAYS = 7
DAILY_CLIENT_LIMIT = 50
HOURLY_GOSSIP_LIMIT = 10
HOURLY_INCOMING_LIMIT = 100

VIOLATION_TYPE_INVALID_SIGNATURE = "invalid_signature"
VIOLATION_TYPE_INVALID_FORMAT = "invalid_format"
VIOLATION_TYPE_RATE_LIMIT = "rate_limit"
VIOLATION_TYPE_SPAM = "spam"

# =============================================================================
# СПАМ-ПРОТЕКЦИЯ
# =============================================================================

MAX_REJECTIONS_PER_DAY = 50
BLOCK_LEVELS = {
    0: {"duration": 0, "message": "Normal behavior"},
    1: {"duration": 86400, "message": "Exceeded invite limit (24h block)"},
    2: {"duration": 604800, "message": "Repeated violation (7d block)"},
    3: {"duration": None, "message": "Permanent ban"},
}

# =============================================================================
# ВОССТАНОВЛЕНИЕ ПАРОЛЯ
# =============================================================================

RECOVERY_TOKEN_TTL_SECONDS = 900
RECOVERY_RATE_LIMIT = 3
RECOVERY_RATE_PERIOD_SECONDS = 3600

# =============================================================================
# ЛОГИРОВАНИЕ
# =============================================================================

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_MAX_SIZE_MB = 100
LOG_MAX_FILES = 5
LOG_RETENTION_DAYS = 30

# =============================================================================
# MISC
# =============================================================================

REGISTRATION_LIMIT = 3
REGISTRATION_PERIOD = 86400

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def ensure_directories() -> None:
    """Создаёт все необходимые директории."""
    DATA_DIR = BASE_DIR / "data"
    LOGS_DIR = BASE_DIR / "logs"
    SSL_DIR = DATA_DIR / "ssl"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SSL_DIR.mkdir(parents=True, exist_ok=True)


def get_version() -> str:
    """Возвращает версию DuoNet."""
    return "2.0.0"


def is_development() -> bool:
    """Проверка, запущен ли прототип в режиме разработки."""
    return os.environ.get("DUONET_ENV", "development") == "development"


def is_server_mode() -> bool:
    """Проверка, запущен ли серверный режим."""
    return CURRENT_MODE in (DuoNetMode.SERVER, DuoNetMode.FULL, DuoNetMode.WEB)


def is_client_mode() -> bool:
    """Проверка, запущен ли клиентский режим."""
    return CURRENT_MODE in (DuoNetMode.CLIENT, DuoNetMode.FULL, DuoNetMode.WEB)
