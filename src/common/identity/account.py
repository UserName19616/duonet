# src/common/identity/account.py
"""
Модуль управления аккаунтами пользователей.

Обеспечивает регистрацию, аутентификацию, смену пароля,
генерацию и верификацию JWT токенов.
"""

import hashlib
import secrets
import time
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from jose import JWTError, jwt

from ..crypto.hash import hash_password, verify_password
from ..crypto.keys import generate_keypair_from_seed, hash_sha256
from ..identity.public_id import generate_public_id
from ..storage.sqlite import SQLiteStorage
from ...config import (
    JWT_EXPIRATION_SECONDS,
    JWT_ALGORITHM,
    MIN_PASSWORD_LENGTH,
    MAX_CLIENT_ACCOUNTS,
    MAX_SERVER_ACCOUNTS,
)

logger = logging.getLogger(__name__)


@dataclass
class AccountInfo:
    """Информация об аккаунте (без приватного ключа)."""

    account_id: bytes  # 20 байт
    seed_hash: bytes  # 32-байтовый хеш сид-фразы 1
    password_hash: bytes  # bcrypt хеш пароля
    public_id: Optional[str]  # клиентский Public ID
    server_id: Optional[str]  # серверный Public ID
    region: str  # двухбуквенный код региона
    is_server: bool  # является ли аккаунт серверным
    created_at: int  # timestamp создания
    public_key: bytes  # 32-байтовый публичный ключ
    recovery_email_hash: Optional[str] = None  # хеш email для восстановления
    last_login_at: Optional[int] = None  # timestamp последнего входа


class AccountManager:
    """
    Менеджер аккаунтов.

    Управляет регистрацией, аутентификацией, сменой пароля
    и JWT токенами.
    """

    def __init__(
        self,
        storage: SQLiteStorage,
        geoip_func: Callable[[str], str],
        rate_limiter: Any,  # MultiRateLimiter из server.network
        jwt_secret: str,
        ws_manager: Any = None,
    ):
        """
        Инициализация менеджера аккаунтов.

        Args:
            storage: Экземпляр хранилища SQLite.
            geoip_func: Функция определения региона по IP.
            rate_limiter: Ограничитель запросов (из server.network).
            jwt_secret: Секретный ключ для JWT.
            ws_manager: Менеджер WebSocket-соединений (опционально).
        """
        self._storage = storage
        self._geoip_func = geoip_func
        self._rate_limiter = rate_limiter
        self._jwt_secret = jwt_secret
        self._ws_manager = ws_manager
        self._session_private_keys: Dict[str, bytes] = {}  # public_id -> private_key

        # Создаем таблицу accounts если не существует
        self._init_db()

    def _init_db(self) -> None:
        """Инициализация таблицы accounts."""
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id BLOB PRIMARY KEY,
                seed_hash BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                public_id TEXT,
                server_id TEXT UNIQUE,
                region TEXT NOT NULL,
                is_server INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                public_key BLOB NOT NULL,
                recovery_email_hash TEXT,
                last_login_at INTEGER
            )
        """)

        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_accounts_public_id
            ON accounts(public_id)
        """)

        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_accounts_server_id
            ON accounts(server_id)
        """)

        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_accounts_seed_hash
            ON accounts(seed_hash)
        """)

    # =========================================================================
    # Сессионные ключи (для PFS и подписей)
    # =========================================================================

    def set_session_private_key(self, public_id: str, private_key: bytes) -> None:
        """Сохранить приватный ключ в сессии после логина."""
        self._session_private_keys[public_id] = private_key
        logger.debug(f"Session private key stored for {public_id}")

    def get_session_private_key(self, public_id: str) -> Optional[bytes]:
        """Получить приватный ключ из сессии."""
        return self._session_private_keys.get(public_id)

    def clear_session_private_key(self, public_id: str) -> None:
        """Удалить приватный ключ при выходе."""
        self._session_private_keys.pop(public_id, None)
        logger.debug(f"Session private key cleared for {public_id}")

    def clear_all_session_keys(self) -> None:
        """Очистить все сессионные ключи."""
        self._session_private_keys.clear()
        logger.debug("All session private keys cleared")

    # =========================================================================
    # Основные методы
    # =========================================================================

    def count_client_accounts(self) -> int:
        """Подсчёт количества клиентских аккаунтов (не серверных)."""
        cursor = self._storage.execute_sql(
            "SELECT COUNT(*) FROM accounts WHERE is_server = 0"
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def count_server_accounts(self) -> int:
        """Подсчёт количества серверных аккаунтов (с .srv)."""
        cursor = self._storage.execute_sql(
            "SELECT COUNT(*) FROM accounts WHERE is_server = 1"
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_client_accounts(self) -> List[Dict[str, Any]]:
        """Получение списка всех клиентских аккаунтов."""
        cursor = self._storage.execute_sql(
            "SELECT public_id, server_id, created_at FROM accounts WHERE is_server = 0 ORDER BY created_at"
        )
        accounts = []
        for row in cursor.fetchall():
            accounts.append({
                "public_id": row[0],
                "server_id": row[1],
                "created_at": row[2],
            })
        return accounts

    def _compute_seed_hash(self, seed_phrase: str) -> bytes:
        """Вычисление хеша сид-фразы."""
        return hash_sha256(seed_phrase.encode("utf-8"))

    def _generate_account_id(self, seed_hash: bytes, is_server: bool, collision_counter: int = 0) -> bytes:
        """
        Генерация уникального account_id из seed_hash и типа аккаунта.

        Args:
            seed_hash: 32-байтовый хеш сид-фразы.
            is_server: True для серверного аккаунта, False для клиентского.
            collision_counter: Счётчик коллизий (при повторной попытке).

        Returns:
            20-байтовый account_id.
        """
        # Используем seed_hash как основу, модифицируем последний байт
        account_id = bytearray(seed_hash[:20])
        if is_server:
            account_id[-1] = account_id[-1] ^ 0x01
        else:
            account_id[-1] = account_id[-1] ^ 0x00

        # Добавляем счётчик коллизий в последние 2 байта если нужно
        if collision_counter > 0:
            account_id[-2] = (account_id[-2] + collision_counter) & 0xFF
            account_id[-1] = (account_id[-1] + (collision_counter >> 8)) & 0xFF

        return bytes(account_id)

    def _account_id_from_seed_hash(self, seed_hash: bytes) -> bytes:
        """Получение account_id из seed_hash (устаревший метод)."""
        return seed_hash[:20]

    def _validate_password(self, password: str) -> bool:
        """Проверка пароля на минимальную длину."""
        return len(password) >= MIN_PASSWORD_LENGTH

    def _generate_jwt_token(
        self, public_id: str, account_id: bytes, is_server: bool
    ) -> Tuple[str, int]:
        """Генерация JWT токена."""
        now = int(time.time())
        expires_at = now + JWT_EXPIRATION_SECONDS

        subject = public_id if public_id else account_id.hex()

        payload = {
            "sub": subject,
            "account_id": account_id.hex(),
            "is_server": is_server,
            "iat": now,
            "exp": expires_at,
            "jti": str(uuid4()),
        }

        token = jwt.encode(payload, self._jwt_secret, algorithm=JWT_ALGORITHM)
        return token, expires_at

    def _account_exists(self, account_id: bytes) -> bool:
        """Проверка существования аккаунта."""
        cursor = self._storage.execute_sql(
            "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
        )
        return cursor.fetchone() is not None

    def _generate_unique_account_id(self, seed_hash: bytes, is_server: bool) -> bytes:
        """Генерация уникального account_id с обработкой коллизий."""
        collision_counter = 0
        max_attempts = 10

        while collision_counter < max_attempts:
            account_id = self._generate_account_id(seed_hash, is_server, collision_counter)
            if not self._account_exists(account_id):
                return account_id
            collision_counter += 1

        raise RuntimeError(f"Failed to generate unique account_id after {max_attempts} attempts")

    def register(
        self,
        seed_phrase: str,
        password: str,
        is_server: bool = False,
        client_ip: str = "0.0.0.0",
        region_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Регистрация нового аккаунта.

        Если is_server=True:
            Создаёт серверный аккаунт (.srv) и, если есть место, клиентский аккаунт.
        Если is_server=False:
            Создаёт только клиентский аккаунт с проверкой лимита.
        """
        if not seed_phrase or not seed_phrase.strip():
            return {
                "success": False,
                "error": "empty_seed",
                "message": "Seed phrase cannot be empty",
            }

        if not self._validate_password(password):
            return {
                "success": False,
                "error": "weak_password",
                "message": f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            }

        # Вычисляем хеш сид-фразы
        seed_hash = self._compute_seed_hash(seed_phrase.strip())

        # Проверяем, не существует ли уже аккаунт с таким seed_hash
        cursor = self._storage.execute_sql(
            "SELECT account_id FROM accounts WHERE seed_hash = ?",
            (seed_hash,)
        )
        if cursor.fetchone():
            return {
                "success": False,
                "error": "account_exists",
                "message": "Account with this seed phrase already exists",
            }

        if not self._rate_limiter.check("registration", client_ip):
            return {
                "success": False,
                "error": "rate_limit_exceeded",
                "message": "Too many registration attempts from this IP",
            }

        if region_override:
            region = region_override.lower()
            if len(region) != 2 or not region.isalpha():
                return {
                    "success": False,
                    "error": "invalid_region",
                    "message": "Region must be 2 letters",
                }
        else:
            region = self._geoip_func(client_ip)
            if region == "local":
                region = "ru"

        private_key, public_key = generate_keypair_from_seed(seed_hash)
        password_hash = hash_password(password)
        now = int(time.time())

        if is_server:
            server_count = self.count_server_accounts()
            if server_count >= MAX_SERVER_ACCOUNTS:
                return {
                    "success": False,
                    "error": "max_servers_reached",
                    "message": f"Maximum {MAX_SERVER_ACCOUNTS} server account allowed",
                    "server_count": server_count,
                    "max_servers": MAX_SERVER_ACCOUNTS,
                }

            server_account_id = self._generate_unique_account_id(seed_hash, is_server=True)

            if self._account_exists(server_account_id):
                return {
                    "success": False,
                    "error": "account_exists",
                    "message": "Server account already exists",
                }

            server_id = generate_public_id(seed_hash, region, is_server=True)

            self._storage.execute_sql(
                """
                INSERT INTO accounts (
                    account_id, seed_hash, password_hash, public_id, server_id,
                    region, is_server, created_at, public_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server_account_id,
                    seed_hash,
                    password_hash,
                    None,
                    server_id,
                    region,
                    1,
                    now,
                    public_key,
                ),
            )

            client_count = self.count_client_accounts()
            client_account_id = None
            public_id = None

            if client_count < MAX_CLIENT_ACCOUNTS:
                client_account_id = self._generate_unique_account_id(seed_hash, is_server=False)
                public_id = generate_public_id(seed_hash, region, is_server=False)

                if not self._account_exists(client_account_id):
                    self._storage.execute_sql(
                        """
                        INSERT INTO accounts (
                            account_id, seed_hash, password_hash, public_id, server_id,
                            region, is_server, created_at, public_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            client_account_id,
                            seed_hash,
                            password_hash,
                            public_id,
                            None,
                            region,
                            0,
                            now,
                            public_key,
                        ),
                    )

            self._rate_limiter.increment("registration", client_ip)

            return {
                "success": True,
                "account_id": server_account_id,
                "client_account_id": client_account_id,
                "server_account_id": server_account_id,
                "public_id": public_id,
                "server_id": server_id,
                "region": region,
            }
        else:
            client_count = self.count_client_accounts()
            if client_count >= MAX_CLIENT_ACCOUNTS:
                return {
                    "success": False,
                    "error": "max_clients_reached",
                    "message": f"Maximum {MAX_CLIENT_ACCOUNTS} client accounts allowed",
                    "client_count": client_count,
                    "max_clients": MAX_CLIENT_ACCOUNTS,
                }

            client_account_id = self._generate_unique_account_id(seed_hash, is_server=False)
            public_id = generate_public_id(seed_hash, region, is_server=False)

            if self._account_exists(client_account_id):
                return {
                    "success": False,
                    "error": "account_exists",
                    "message": "Account already exists",
                }

            self._storage.execute_sql(
                """
                INSERT INTO accounts (
                    account_id, seed_hash, password_hash, public_id, server_id,
                    region, is_server, created_at, public_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_account_id,
                    seed_hash,
                    password_hash,
                    public_id,
                    None,
                    region,
                    0,
                    now,
                    public_key,
                ),
            )

            self._rate_limiter.increment("registration", client_ip)

            return {
                "success": True,
                "account_id": client_account_id,
                "public_id": public_id,
                "server_id": None,
                "region": region,
            }

    def login(self, seed_phrase: str, password: str) -> Optional[Dict[str, Any]]:
        """Аутентификация пользователя по сид-фразе."""
        seed_hash = self._compute_seed_hash(seed_phrase.strip())
        client_account_id = self._generate_account_id(seed_hash, is_server=False, collision_counter=0)

        cursor = self._storage.execute_sql(
            """
            SELECT account_id, password_hash, public_id, server_id, is_server, public_key
            FROM accounts WHERE account_id = ? AND is_server = 0
            """,
            (client_account_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        stored_hash = row[1]
        if not verify_password(password, stored_hash):
            return None

        now = int(time.time())
        self._storage.execute_sql(
            "UPDATE accounts SET last_login_at = ? WHERE account_id = ? AND is_server = 0",
            (now, client_account_id),
        )

        token, expires_at = self._generate_jwt_token(row[2], row[0], bool(row[4]))

        return {
            "account_id": row[0],
            "public_id": row[2],
            "server_id": row[3],
            "is_server": bool(row[4]),
            "token": token,
            "expires_at": expires_at,
        }

    def login_by_server_id(self, server_id: str, password: str) -> Optional[Dict[str, Any]]:
        """Аутентификация по серверному ID и паролю."""
        cursor = self._storage.execute_sql(
            """
            SELECT account_id, password_hash, public_id, server_id, is_server, public_key
            FROM accounts WHERE server_id = ?
            """,
            (server_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        stored_hash = row[1]
        if not verify_password(password, stored_hash):
            return None

        now = int(time.time())
        self._storage.execute_sql(
            "UPDATE accounts SET last_login_at = ? WHERE server_id = ?",
            (now, server_id),
        )

        token, expires_at = self._generate_jwt_token(row[3], row[0], bool(row[4]))

        return {
            "account_id": row[0],
            "public_id": row[2],
            "server_id": row[3],
            "is_server": bool(row[4]),
            "token": token,
            "expires_at": expires_at,
        }

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Проверка JWT токена."""
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGORITHM])
            return payload
        except JWTError:
            return None

    def change_password(
        self, account_id: bytes, old_password: str, new_password: str
    ) -> bool:
        """Смена пароля для аккаунта."""
        if not self._validate_password(new_password):
            return False

        cursor = self._storage.execute_sql(
            "SELECT password_hash FROM accounts WHERE account_id = ?",
            (account_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False

        if not verify_password(old_password, row[0]):
            return False

        new_hash = hash_password(new_password)

        self._storage.execute_sql(
            "UPDATE accounts SET password_hash = ? WHERE account_id = ?",
            (new_hash, account_id),
        )
        return True

    def get_account(self, account_id: bytes) -> Optional[AccountInfo]:
        """Получение информации об аккаунте по account_id."""
        cursor = self._storage.execute_sql(
            """
            SELECT account_id, seed_hash, password_hash, public_id, server_id,
                   region, is_server, created_at, public_key, recovery_email_hash,
                   last_login_at
            FROM accounts WHERE account_id = ?
            """,
            (account_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return AccountInfo(
            account_id=row[0],
            seed_hash=row[1],
            password_hash=row[2],
            public_id=row[3],
            server_id=row[4],
            region=row[5],
            is_server=bool(row[6]),
            created_at=row[7],
            public_key=row[8],
            recovery_email_hash=row[9],
            last_login_at=row[10],
        )

    def get_private_key(
        self, account_id: bytes, seed_phrase: str
    ) -> Optional[bytes]:
        """Получение приватного ключа (генерируется из seed_hash на лету)."""
        seed_hash = self._compute_seed_hash(seed_phrase.strip())

        expected_client_id = self._generate_account_id(seed_hash, is_server=False, collision_counter=0)
        expected_server_id = self._generate_account_id(seed_hash, is_server=True, collision_counter=0)

        if account_id not in (expected_client_id, expected_server_id):
            return None

        if not self._account_exists(account_id):
            return None

        private_key, _ = generate_keypair_from_seed(seed_hash)
        return private_key

    def get_public_key(self, account_id: bytes) -> Optional[bytes]:
        """Получение публичного ключа."""
        cursor = self._storage.execute_sql(
            "SELECT public_key FROM accounts WHERE account_id = ?",
            (account_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_public_key_by_id(self, public_id: str) -> Optional[bytes]:
        """Получение публичного ключа по Public ID."""
        cursor = self._storage.execute_sql(
            "SELECT public_key FROM accounts WHERE public_id = ? OR server_id = ?",
            (public_id, public_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def public_id_to_account_id(self, public_id: str) -> Optional[bytes]:
        """Конвертация Public ID в account_id."""
        cursor = self._storage.execute_sql(
            "SELECT account_id FROM accounts WHERE public_id = ? OR server_id = ?",
            (public_id, public_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def account_id_to_public_id(self, account_id: bytes) -> Optional[str]:
        """Конвертация account_id в Public ID."""
        cursor = self._storage.execute_sql(
            "SELECT public_id FROM accounts WHERE account_id = ?",
            (account_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_connected_clients(self) -> List[Dict[str, Any]]:
        """Получение списка подключённых клиентов (для балансировки)."""
        if self._ws_manager is None:
            return []
        return self._ws_manager.get_all_connections()

    def get_ws_manager(self) -> Any:
        """Получение экземпляра менеджера WebSocket."""
        return self._ws_manager

    def is_online(self, public_id: str) -> bool:
        """Проверка, находится ли клиент онлайн."""
        if self._ws_manager is None:
            return False
        return self._ws_manager.get_connection(public_id) is not None

    def get_private_key_by_id(
        self, public_id: str, seed_phrase: str
    ) -> Optional[bytes]:
        """Получение приватного ключа по Public ID."""
        account_id = self.public_id_to_account_id(public_id)
        if account_id is None:
            return None
        return self.get_private_key(account_id, seed_phrase)

    def get_active_connection_count(self) -> int:
        """Получение количества активных WebSocket-соединений."""
        if self._ws_manager is None:
            return 0
        return self._ws_manager.get_connection_count()

    def update_last_login(self, account_id: bytes) -> None:
        """Обновление timestamp последнего входа."""
        now = int(time.time())
        self._storage.execute_sql(
            "UPDATE accounts SET last_login_at = ? WHERE account_id = ?",
            (now, account_id),
        )

    def close_connection(self, public_id: str) -> bool:
        """Закрытие WebSocket-соединения клиента."""
        if self._ws_manager is None:
            return False
        return self._ws_manager.remove_connection(public_id)
