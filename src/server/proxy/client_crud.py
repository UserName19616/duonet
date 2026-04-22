# src/server/proxy/client_crud.py
"""
Управление прокси-клиентами: CRUD операции.
"""

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from src.common.identity.account import AccountManager
from src.common.storage.sqlite import SQLiteStorage
from src.config import PROXY_MAX_CLIENTS, PROXY_DAILY_LIMIT_BASIC_MB, PROXY_DAILY_LIMIT_STANDARD_MB

logger = logging.getLogger(__name__)

MAX_CLIENTS_DEFAULT = PROXY_MAX_CLIENTS
DAILY_LIMIT_BASIC_DEFAULT_MB = PROXY_DAILY_LIMIT_BASIC_MB
DAILY_LIMIT_STANDARD_DEFAULT_MB = PROXY_DAILY_LIMIT_STANDARD_MB


@dataclass
class ClientInfo:
    client_id: str
    public_id: str
    name: str
    group: str
    connected: bool
    last_seen: float
    traffic_today: int
    traffic_total: int
    daily_limit: Optional[int]
    expires_at: Optional[float]
    created_at: float
    updated_at: float


GROUPS = {
    "basic": {"daily_limit_mb": PROXY_DAILY_LIMIT_BASIC_MB, "ttl": 86400, "description": "New clients, 24h access"},
    "standard": {"daily_limit_mb": PROXY_DAILY_LIMIT_STANDARD_MB, "ttl": None, "description": "Regular users, monthly access"},
    "privileged": {"daily_limit_mb": None, "ttl": None, "description": "Own devices, unlimited"},
}


class ClientManager:
    def __init__(self, storage: SQLiteStorage, account_manager: AccountManager):
        self._storage = storage
        self._account_manager = account_manager
        self.proxy_port = 9879
        self._init_db()

    def _init_db(self) -> None:
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS proxy_clients (
                client_id TEXT PRIMARY KEY,
                public_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                group_name TEXT NOT NULL,
                connected INTEGER DEFAULT 0,
                last_seen REAL DEFAULT 0,
                traffic_today INTEGER DEFAULT 0,
                traffic_total INTEGER DEFAULT 0,
                daily_limit INTEGER,
                expires_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS proxy_invites (
                token TEXT PRIMARY KEY,
                client_name TEXT NOT NULL,
                group_name TEXT NOT NULL,
                daily_limit_mb INTEGER,
                expires_at REAL NOT NULL,
                used INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS proxy_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._init_default_settings()

    def _init_default_settings(self) -> None:
        default_settings = {
            "max_clients": str(MAX_CLIENTS_DEFAULT),
            "default_daily_limit_mb": str(DAILY_LIMIT_BASIC_DEFAULT_MB),
            "default_group": "basic",
            "proxy_enabled": "true",
        }
        for key, value in default_settings.items():
            cursor = self._storage.execute_sql("SELECT 1 FROM proxy_settings WHERE key = ?", (key,))
            if not cursor.fetchone():
                self._storage.execute_sql("INSERT INTO proxy_settings (key, value) VALUES (?, ?)", (key, value))

    def _get_setting(self, key: str, default: str = "") -> str:
        cursor = self._storage.execute_sql("SELECT value FROM proxy_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

    def _set_setting(self, key: str, value: str) -> None:
        self._storage.execute_sql("INSERT OR REPLACE INTO proxy_settings (key, value) VALUES (?, ?)", (key, value))

    def _generate_client_id(self) -> str:
        return secrets.token_urlsafe(16)

    def _generate_token(self) -> str:
        return secrets.token_urlsafe(32)

    def _generate_qr_code(self, invite_url: str) -> str:
        try:
            import qrcode
            from io import BytesIO
            import base64
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(invite_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            logger.warning(f"QR generation failed: {e}, using placeholder")
            return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    def _calculate_standard_expiry(self, activation_timestamp: int) -> int:
        dt = datetime.fromtimestamp(activation_timestamp, tz=timezone.utc)
        if dt.month == 12:
            next_month = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
        last_day = next_month - timedelta(days=1)
        last_day = last_day.replace(hour=23, minute=59, second=59)
        return int(last_day.timestamp())

    def generate_invite(self, client_name: str, expires_in: int = 86400, group: str = "basic", daily_limit_mb: Optional[int] = None) -> Dict[str, Any]:
        if not client_name or len(client_name) > 64:
            return {"success": False, "error": "invalid_name", "message": "Name must be 1-64 characters"}
        if expires_in < 3600 or expires_in > 2592000:
            return {"success": False, "error": "invalid_expiry", "message": "Expiry must be between 1 hour and 30 days"}
        if group not in GROUPS:
            return {"success": False, "error": "invalid_group", "message": f"Group must be one of {list(GROUPS.keys())}"}

        token = self._generate_token()
        invite_url = f"duonet://invite?token={token}"
        qr_code = self._generate_qr_code(invite_url)

        if group == "privileged":
            expires_at = None
        elif group == "standard":
            expires_at = None
        else:
            expires_at = time.time() + expires_in

        if daily_limit_mb is None:
            daily_limit_mb = GROUPS[group].get("daily_limit_mb")

        now = time.time()
        self._storage.execute_sql("""
            INSERT INTO proxy_invites (token, client_name, group_name, daily_limit_mb, expires_at, used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (token, client_name, group, daily_limit_mb, expires_at if expires_at is not None else 0, 0, now))

        return {"success": True, "token": token, "invite_url": invite_url, "qr_code": qr_code, "expires_at": expires_at}

    def get_invite(self, token: str) -> Optional[Dict[str, Any]]:
        cursor = self._storage.execute_sql("SELECT client_name, group_name, daily_limit_mb, expires_at, used FROM proxy_invites WHERE token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            return None
        return {"client_name": row[0], "group": row[1], "daily_limit_mb": row[2], "expires_at": row[3] if row[3] != 0 else None, "used": bool(row[4])}

    def mark_invite_used(self, token: str) -> None:
        self._storage.execute_sql("UPDATE proxy_invites SET used = 1 WHERE token = ?", (token,))

    def cleanup_expired_invites(self) -> int:
        now = time.time()
        cursor = self._storage.execute_sql("DELETE FROM proxy_invites WHERE expires_at IS NOT NULL AND expires_at < ? AND used = 0", (now,))
        return cursor.rowcount

    def add_client(self, token: str, public_id: str) -> bool:
        if self._account_manager.public_id_to_account_id(public_id) is None:
            return False

        invite = self.get_invite(token)
        if not invite or invite["used"]:
            return False
        if invite["expires_at"] and invite["expires_at"] < time.time():
            return False

        max_clients = int(self._get_setting("max_clients", str(MAX_CLIENTS_DEFAULT)))
        cursor = self._storage.execute_sql("SELECT COUNT(*) FROM proxy_clients")
        if cursor.fetchone()[0] >= max_clients:
            return False

        now = int(time.time())
        if invite["group"] == "privileged":
            expires_at = None
        elif invite["group"] == "standard":
            expires_at = self._calculate_standard_expiry(now)
        else:
            expires_at = invite["expires_at"]

        daily_limit = None
        if invite["daily_limit_mb"] is not None:
            daily_limit = invite["daily_limit_mb"] * 1024 * 1024

        client_id = self._generate_client_id()
        self._storage.execute_sql("""
            INSERT INTO proxy_clients (client_id, public_id, name, group_name, connected, last_seen,
                                       traffic_today, traffic_total, daily_limit, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (client_id, public_id, invite["client_name"], invite["group"], 0, 0.0, 0, 0, daily_limit, expires_at, float(now), float(now)))

        self.mark_invite_used(token)
        return True

    def get_client(self, client_id: str) -> Optional[ClientInfo]:
        cursor = self._storage.execute_sql("""
            SELECT client_id, public_id, name, group_name, connected, last_seen,
                   traffic_today, traffic_total, daily_limit, expires_at, created_at, updated_at
            FROM proxy_clients WHERE client_id = ?
        """, (client_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return ClientInfo(client_id=row[0], public_id=row[1], name=row[2], group=row[3], connected=bool(row[4]),
                         last_seen=row[5], traffic_today=row[6], traffic_total=row[7], daily_limit=row[8],
                         expires_at=row[9], created_at=row[10], updated_at=row[11])

    def get_client_by_public_id(self, public_id: str) -> Optional[ClientInfo]:
        cursor = self._storage.execute_sql("""
            SELECT client_id, public_id, name, group_name, connected, last_seen,
                   traffic_today, traffic_total, daily_limit, expires_at, created_at, updated_at
            FROM proxy_clients WHERE public_id = ?
        """, (public_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return ClientInfo(client_id=row[0], public_id=row[1], name=row[2], group=row[3], connected=bool(row[4]),
                         last_seen=row[5], traffic_today=row[6], traffic_total=row[7], daily_limit=row[8],
                         expires_at=row[9], created_at=row[10], updated_at=row[11])

    def get_all_clients(self) -> List[ClientInfo]:
        cursor = self._storage.execute_sql("""
            SELECT client_id, public_id, name, group_name, connected, last_seen,
                   traffic_today, traffic_total, daily_limit, expires_at, created_at, updated_at
            FROM proxy_clients ORDER BY created_at
        """)
        result = []
        for row in cursor.fetchall():
            result.append(ClientInfo(client_id=row[0], public_id=row[1], name=row[2], group=row[3], connected=bool(row[4]),
                                    last_seen=row[5], traffic_today=row[6], traffic_total=row[7], daily_limit=row[8],
                                    expires_at=row[9], created_at=row[10], updated_at=row[11]))
        return result

    def update_client(self, client_id: str, **kwargs) -> bool:
        client = self.get_client(client_id)
        if not client:
            return False

        updates = []
        params = []

        if "name" in kwargs:
            updates.append("name = ?")
            params.append(kwargs["name"])
        if "group" in kwargs:
            new_group = kwargs["group"]
            if new_group not in ("basic", "standard", "privileged"):
                return False
            updates.append("group_name = ?")
            params.append(new_group)
            if new_group == "privileged":
                updates.append("daily_limit = ?")
                params.append(None)
                updates.append("expires_at = ?")
                params.append(None)
            elif new_group == "standard":
                updates.append("daily_limit = ?")
                params.append(DAILY_LIMIT_STANDARD_DEFAULT_MB * 1024 * 1024)
                now = int(time.time())
                updates.append("expires_at = ?")
                params.append(self._calculate_standard_expiry(now))
        if "daily_limit_mb" in kwargs:
            limit_mb = kwargs["daily_limit_mb"]
            if limit_mb is None:
                updates.append("daily_limit = ?")
                params.append(None)
            elif limit_mb >= 0:
                updates.append("daily_limit = ?")
                params.append(limit_mb * 1024 * 1024)
        if "expires_at" in kwargs:
            updates.append("expires_at = ?")
            params.append(kwargs["expires_at"])

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(client_id)

        self._storage.execute_sql(f"UPDATE proxy_clients SET {', '.join(updates)} WHERE client_id = ?", params)
        return True

    def revoke_access(self, client_id: str) -> bool:
        client = self.get_client(client_id)
        if not client:
            return False
        self._storage.execute_sql("DELETE FROM proxy_clients WHERE client_id = ?", (client_id,))
        return True

    def cleanup_expired_clients(self) -> int:
        now = time.time()
        cursor = self._storage.execute_sql("SELECT client_id, public_id FROM proxy_clients WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
        expired_clients = cursor.fetchall()
        for client_id, public_id in expired_clients:
            self._account_manager.close_connection(public_id)
            self._storage.execute_sql("DELETE FROM proxy_clients WHERE client_id = ?", (client_id,))
        expired_invites = self.cleanup_expired_invites()
        return len(expired_clients) + expired_invites

    def add_traffic(self, client_id: str, bytes_added: int) -> None:
        cursor = self._storage.execute_sql("SELECT traffic_today, traffic_total FROM proxy_clients WHERE client_id = ?", (client_id,))
        row = cursor.fetchone()
        if not row:
            logger.warning(f"Client {client_id} not found for traffic update")
            return
        new_traffic_today = row[0] + bytes_added
        new_traffic_total = row[1] + bytes_added
        self._storage.execute_sql("UPDATE proxy_clients SET traffic_today = ?, traffic_total = ?, updated_at = ? WHERE client_id = ?",
                                  (new_traffic_today, new_traffic_total, time.time(), client_id))

    def check_traffic_limit(self, client_id: str, bytes_to_add: int) -> bool:
        cursor = self._storage.execute_sql("SELECT daily_limit, traffic_today FROM proxy_clients WHERE client_id = ?", (client_id,))
        row = cursor.fetchone()
        if not row:
            return False
        daily_limit = row[0]
        traffic_today = row[1]
        if daily_limit is None:
            return True
        return traffic_today + bytes_to_add <= daily_limit

    def get_traffic_stats(self, client_id: str) -> Dict[str, Any]:
        cursor = self._storage.execute_sql("SELECT traffic_today, traffic_total, daily_limit FROM proxy_clients WHERE client_id = ?", (client_id,))
        row = cursor.fetchone()
        if not row:
            return {}
        traffic_today = row[0]
        traffic_total = row[1]
        daily_limit = row[2]
        used_mb = traffic_today / (1024 * 1024)
        limit_mb = daily_limit / (1024 * 1024) if daily_limit is not None else None
        result = {"used_today_mb": round(used_mb, 2), "total_mb": round(traffic_total / (1024 * 1024), 2)}
        if limit_mb is not None:
            result["daily_limit_mb"] = round(limit_mb, 2)
            result["remaining_mb"] = round(limit_mb - used_mb, 2)
        else:
            result["daily_limit_mb"] = None
            result["remaining_mb"] = None
        return result

    def get_aggregated_stats(self) -> Dict[str, Any]:
        cursor = self._storage.execute_sql("""
            SELECT COALESCE(SUM(traffic_today), 0) as total_today, COALESCE(SUM(traffic_total), 0) as total_all,
                   COUNT(*) as total_clients,
                   COALESCE(SUM(CASE WHEN connected = 1 THEN 1 ELSE 0 END), 0) as active_clients,
                   COALESCE(SUM(CASE WHEN group_name = 'basic' THEN 1 ELSE 0 END), 0) as basic_count,
                   COALESCE(SUM(CASE WHEN group_name = 'standard' THEN 1 ELSE 0 END), 0) as standard_count,
                   COALESCE(SUM(CASE WHEN group_name = 'privileged' THEN 1 ELSE 0 END), 0) as privileged_count
            FROM proxy_clients
        """)
        row = cursor.fetchone()
        total_today = row[0] if row[0] is not None else 0
        total_all = row[1] if row[1] is not None else 0
        return {
            "total_today_mb": round(total_today / (1024 * 1024), 2),
            "total_all_mb": round(total_all / (1024 * 1024), 2),
            "total_clients": row[2] if row[2] is not None else 0,
            "active_clients": row[3] if row[3] is not None else 0,
            "by_group": {"basic": row[4] if row[4] is not None else 0,
                         "standard": row[5] if row[5] is not None else 0,
                         "privileged": row[6] if row[6] is not None else 0},
        }

    def reset_daily_traffic(self) -> int:
        self._storage.execute_sql("UPDATE proxy_clients SET traffic_today = 0, updated_at = ?", (time.time(),))
        cursor = self._storage.execute_sql("SELECT changes()")
        return cursor.fetchone()[0]

    def get_settings(self) -> Dict[str, Any]:
        return {
            "max_clients": int(self._get_setting("max_clients", str(MAX_CLIENTS_DEFAULT))),
            "default_daily_limit_mb": int(self._get_setting("default_daily_limit_mb", str(DAILY_LIMIT_BASIC_DEFAULT_MB))),
            "default_group": self._get_setting("default_group", "basic"),
            "proxy_enabled": self._get_setting("proxy_enabled", "true").lower() == "true",
        }

    def update_settings(self, **kwargs) -> bool:
        # Проверяем default_group ПЕРВОЙ (если передан)
        if "default_group" in kwargs:
            if kwargs["default_group"] not in ("basic", "standard", "privileged"):
                return False  # ← Неверная группа → возвращаем False
            self._set_setting("default_group", kwargs["default_group"])

        if "max_clients" in kwargs and kwargs["max_clients"] >= 0:
            self._set_setting("max_clients", str(kwargs["max_clients"]))

        if "default_daily_limit_mb" in kwargs and kwargs["default_daily_limit_mb"] >= 0:
            self._set_setting("default_daily_limit_mb", str(kwargs["default_daily_limit_mb"]))

        if "proxy_enabled" in kwargs:
            self._set_setting("proxy_enabled", "true" if kwargs["proxy_enabled"] else "false")

        return True

    def has_permission(self, client_id: str, permission: str) -> bool:
        client = self.get_client(client_id)
        if not client:
            return False
        if permission == "proxy":
            if client.expires_at is not None and client.expires_at < time.time():
                return False
            if client.daily_limit is not None and client.traffic_today >= client.daily_limit:
                return False
            return True
        if permission == "chat":
            return True
        return False

    def cleanup_expired(self) -> int:
        return self.cleanup_expired_clients()
