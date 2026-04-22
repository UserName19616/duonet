# src/server/storage/server_db.py
"""
Хранилище сетевых данных сервера (duonet_server.db).
"""

import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import hashlib
import hmac

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
MASTER_KEY_ENV = "DUONET_MASTER_KEY"
SALT_SIZE = 16
NONCE_SIZE = 12
HMAC_SIZE = 32


class KeyManager:
    _instance = None
    _master_key: Optional[bytes] = None
    _enc_key: Optional[bytes] = None
    _hmac_key: Optional[bytes] = None
    _sign_key: Optional[bytes] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._master_key is None:
            self._master_key = self._load_or_create_master_key()
            self._enc_key, self._hmac_key, self._sign_key = self._derive_keys(self._master_key)

    def _load_or_create_master_key(self) -> bytes:
        key_hex = os.environ.get(MASTER_KEY_ENV)
        if key_hex:
            try:
                return bytes.fromhex(key_hex)
            except ValueError:
                logger.warning("Invalid master key in env, generating new")

        master_key = secrets.token_bytes(32)
        key_hex = master_key.hex()
        try:
            with open(".env", "a") as f:
                f.write(f"\n{MASTER_KEY_ENV}={key_hex}\n")
            os.chmod(".env", 0o600)
            logger.info(f"Generated new master key and saved to .env")
        except Exception as e:
            logger.warning(f"Failed to save master key to .env: {e}")
        return master_key

    def _derive_keys(self, master_key: bytes) -> Tuple[bytes, bytes, bytes]:
        enc_key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"duonet_enc_salt", iterations=100000).derive(master_key)
        hmac_key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"duonet_hmac_salt", iterations=100000).derive(master_key)
        sign_key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"duonet_sign_salt", iterations=100000).derive(master_key)
        return enc_key, hmac_key, sign_key

    def get_enc_key(self) -> bytes:
        return self._enc_key

    def get_hmac_key(self) -> bytes:
        return self._hmac_key

    def get_sign_key(self) -> bytes:
        return self._sign_key


_key_manager = KeyManager()


def encrypt_data(data: str) -> bytes:
    if not data:
        return b""
    key = _key_manager.get_enc_key()
    salt = secrets.token_bytes(SALT_SIZE)
    nonce = secrets.token_bytes(NONCE_SIZE)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=10000)
    derived_key = kdf.derive(key)
    aesgcm = AESGCM(derived_key)
    ciphertext = aesgcm.encrypt(nonce, data.encode(), None)
    return salt + nonce + ciphertext


def decrypt_data(encrypted: bytes) -> str:
    if not encrypted or len(encrypted) < SALT_SIZE + NONCE_SIZE:
        return ""
    key = _key_manager.get_enc_key()
    salt = encrypted[:SALT_SIZE]
    nonce = encrypted[SALT_SIZE:SALT_SIZE + NONCE_SIZE]
    ciphertext = encrypted[SALT_SIZE + NONCE_SIZE:]
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=10000)
    derived_key = kdf.derive(key)
    try:
        aesgcm = AESGCM(derived_key)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode()
    except Exception:
        logger.error("Decryption failed")
        return ""


def hmac_server_id(server_id: str) -> str:
    key = _key_manager.get_hmac_key()
    return hmac.new(key, server_id.encode(), hashlib.sha256).hexdigest()[:HMAC_SIZE]


def sign_server_record(server_id: str, region: str, ws_url: str, timestamp: int) -> str:
    key = _key_manager.get_sign_key()
    data = f"{server_id}:{region}:{ws_url}:{timestamp}".encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def verify_signature(server_id: str, region: str, ws_url: str, timestamp: int, signature: str) -> bool:
    expected = sign_server_record(server_id, region, ws_url, timestamp)
    return hmac.compare_digest(signature, expected)


class ServerDatabase:
    def __init__(self, path: str = "duonet_server.db"):
        self._path = path
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _transaction(self):
        with self._lock:
            conn = self._get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)")
            cursor = conn.execute("SELECT MAX(version) as ver FROM schema_version")
            row = cursor.fetchone()
            current_version = row["ver"] if row and row["ver"] else 0

            if current_version == 0:
                conn.execute("""
                    CREATE TABLE servers (
                        server_id TEXT PRIMARY KEY,
                        region TEXT NOT NULL,
                        ws_url_encrypted BLOB NOT NULL,
                        status TEXT DEFAULT 'active',
                        signature TEXT,
                        last_seen INTEGER,
                        created_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.execute("CREATE INDEX idx_servers_region ON servers(region)")
                conn.execute("CREATE INDEX idx_servers_status ON servers(status)")
                conn.execute("""
                    CREATE TABLE clients (
                        client_id TEXT NOT NULL,
                        server_id_hash TEXT NOT NULL,
                        region TEXT,
                        first_seen INTEGER,
                        last_seen INTEGER,
                        PRIMARY KEY (client_id, server_id_hash)
                    )
                """)
                conn.execute("CREATE INDEX idx_clients_region ON clients(region)")
                conn.execute("CREATE INDEX idx_clients_server ON clients(server_id_hash)")
                conn.execute("""
                    CREATE TABLE network_map (
                        node_id TEXT PRIMARY KEY,
                        address_encrypted BLOB,
                        port INTEGER,
                        node_type TEXT,
                        connections_encrypted BLOB,
                        latency_ms INTEGER,
                        last_updated INTEGER
                    )
                """)
                conn.execute("CREATE INDEX idx_network_type ON network_map(node_type)")
                conn.execute("""
                    CREATE TABLE sync_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_server_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        data TEXT,
                        status TEXT DEFAULT 'pending',
                        retry_count INTEGER DEFAULT 0,
                        created_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.execute("CREATE INDEX idx_sync_status ON sync_queue(status)")
                conn.execute("CREATE INDEX idx_sync_target ON sync_queue(target_server_id)")
                conn.execute("""
                    CREATE TABLE settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        encrypted INTEGER DEFAULT 0,
                        updated_at INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE peers (
                        peer_id TEXT PRIMARY KEY,
                        ws_url TEXT NOT NULL,
                        region TEXT,
                        status TEXT DEFAULT 'disconnected',
                        last_connected INTEGER,
                        added_by TEXT DEFAULT 'manual',
                        added_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.execute("CREATE INDEX idx_peers_status ON peers(status)")
                conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (2, int(time.time())))
                logger.info(f"Server database initialized with version 2")
            elif current_version == 1:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS peers (
                        peer_id TEXT PRIMARY KEY,
                        ws_url TEXT NOT NULL,
                        region TEXT,
                        status TEXT DEFAULT 'disconnected',
                        last_connected INTEGER,
                        added_by TEXT DEFAULT 'manual',
                        added_at INTEGER,
                        updated_at INTEGER
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_peers_status ON peers(status)")
                conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (2, int(time.time())))
                logger.info(f"Server database migrated to version 2")

    def add_server(self, server_id: str, region: str, ws_url: str, status: str = "active") -> bool:
        now = int(time.time())
        ws_url_encrypted = encrypt_data(ws_url)
        signature = sign_server_record(server_id, region, ws_url, now)
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO servers
                (server_id, region, ws_url_encrypted, status, signature, last_seen, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM servers WHERE server_id = ?), ?), ?)
            """, (server_id, region, ws_url_encrypted, status, signature, now, server_id, now, now))
        logger.info(f"Server {server_id} added/updated")
        return True

    def get_server(self, server_id: str) -> Optional[Dict[str, Any]]:
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT server_id, region, ws_url_encrypted, status, signature, last_seen, created_at, updated_at "
                "FROM servers WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {"server_id": row["server_id"], "region": row["region"], "ws_url": decrypt_data(row["ws_url_encrypted"]),
                    "status": row["status"], "signature": row["signature"], "last_seen": row["last_seen"],
                    "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_servers_by_region(self, region: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT server_id, region, ws_url_encrypted, status, last_seen FROM servers WHERE region = ? AND status = 'active' ORDER BY last_seen DESC LIMIT ?",
                (region, limit))
            return [{"server_id": row["server_id"], "region": row["region"], "ws_url": decrypt_data(row["ws_url_encrypted"]),
                     "status": row["status"], "last_seen": row["last_seen"]} for row in cursor.fetchall()]

    def update_server_status(self, server_id: str, status: str) -> bool:
        now = int(time.time())
        with self._transaction() as conn:
            cursor = conn.execute("UPDATE servers SET status = ?, updated_at = ? WHERE server_id = ?", (status, now, server_id))
            return cursor.rowcount > 0

    def update_last_seen(self, server_id: str) -> bool:
        now = int(time.time())
        with self._transaction() as conn:
            cursor = conn.execute("UPDATE servers SET last_seen = ?, updated_at = ? WHERE server_id = ?", (now, now, server_id))
            return cursor.rowcount > 0

    def add_client(self, client_id: str, server_id: str, region: str) -> bool:
        now = int(time.time())
        server_hash = hmac_server_id(server_id)
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO clients (client_id, server_id_hash, region, first_seen, last_seen)
                VALUES (?, ?, ?, COALESCE((SELECT first_seen FROM clients WHERE client_id = ? AND server_id_hash = ?), ?), ?)
            """, (client_id, server_hash, region, client_id, server_hash, now, now))
        logger.debug(f"Client {client_id} added to server {server_id}")
        return True

    def get_client_server(self, client_id: str) -> Optional[str]:
        with self._transaction() as conn:
            cursor = conn.execute("SELECT server_id_hash FROM clients WHERE client_id = ?", (client_id,))
            row = cursor.fetchone()
            return row["server_id_hash"] if row else None

    def update_client_last_seen(self, client_id: str) -> bool:
        now = int(time.time())
        with self._transaction() as conn:
            cursor = conn.execute("UPDATE clients SET last_seen = ? WHERE client_id = ?", (now, client_id))
            return cursor.rowcount > 0

    def update_network_node(self, node_id: str, address: str, port: int, node_type: str, connections: List[str], latency_ms: int = 0) -> bool:
        now = int(time.time())
        address_encrypted = encrypt_data(address)
        connections_encrypted = encrypt_data(json.dumps(connections))
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO network_map (node_id, address_encrypted, port, node_type, connections_encrypted, latency_ms, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (node_id, address_encrypted, port, node_type, connections_encrypted, latency_ms, now))
        return True

    def get_network_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT node_id, address_encrypted, port, node_type, connections_encrypted, latency_ms, last_updated FROM network_map WHERE node_id = ?",
                (node_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {"node_id": row["node_id"], "address": decrypt_data(row["address_encrypted"]), "port": row["port"],
                    "node_type": row["node_type"], "connections": json.loads(decrypt_data(row["connections_encrypted"])),
                    "latency_ms": row["latency_ms"], "last_updated": row["last_updated"]}

    def add_to_sync_queue(self, target_server_id: str, operation: str, data: dict) -> int:
        now = int(time.time())
        with self._transaction() as conn:
            cursor = conn.execute("""
                INSERT INTO sync_queue (target_server_id, operation, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (target_server_id, operation, json.dumps(data), now, now))
            return cursor.lastrowid

    def get_pending_sync(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._transaction() as conn:
            cursor = conn.execute("""
                SELECT id, target_server_id, operation, data, retry_count, created_at
                FROM sync_queue WHERE status = 'pending' AND retry_count < 5 ORDER BY created_at ASC LIMIT ?
            """, (limit,))
            return [{"id": row["id"], "target_server_id": row["target_server_id"], "operation": row["operation"],
                     "data": json.loads(row["data"]) if row["data"] else {}, "retry_count": row["retry_count"],
                     "created_at": row["created_at"]} for row in cursor.fetchall()]

    def mark_sync_done(self, sync_id: int, success: bool) -> None:
        now = int(time.time())
        with self._transaction() as conn:
            if success:
                conn.execute("UPDATE sync_queue SET status = 'synced', updated_at = ? WHERE id = ?", (now, sync_id))
            else:
                conn.execute("UPDATE sync_queue SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?", (now, sync_id))
                cursor = conn.execute("SELECT retry_count FROM sync_queue WHERE id = ?", (sync_id,))
                row = cursor.fetchone()
                if row and row["retry_count"] >= 5:
                    conn.execute("UPDATE sync_queue SET status = 'failed' WHERE id = ?", (sync_id,))
                else:
                    conn.execute("UPDATE sync_queue SET status = 'pending' WHERE id = ?", (sync_id,))

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._transaction() as conn:
            cursor = conn.execute("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if not row:
                return default
            value = row["value"]
            if row["encrypted"]:
                value = decrypt_data(bytes.fromhex(value))
            return value

    def set_setting(self, key: str, value: Any, encrypted: bool = False) -> None:
        now = int(time.time())
        if encrypted:
            value = encrypt_data(str(value)).hex()
        else:
            value = str(value)
        with self._transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value, encrypted, updated_at) VALUES (?, ?, ?, ?)",
                        (key, value, 1 if encrypted else 0, now))

    def get_stats(self) -> Dict[str, Any]:
        with self._transaction() as conn:
            servers = conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
            clients = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
            nodes = conn.execute("SELECT COUNT(*) FROM network_map").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status = 'pending'").fetchone()[0]
            return {"total_servers": servers, "total_clients": clients, "network_nodes": nodes, "pending_sync": pending, "db_path": self._path}

    def close(self) -> None:
        pass


_server_db: Optional[ServerDatabase] = None


def get_server_db() -> ServerDatabase:
    global _server_db
    if _server_db is None:
        _server_db = ServerDatabase()
    return _server_db


def set_server_db(db: ServerDatabase) -> None:
    global _server_db
    _server_db = db
