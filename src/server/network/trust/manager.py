# src/server/network/trust/manager.py
"""
Менеджер доверия для серверов сети.
"""

import time
import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.server.storage.server_db import ServerDatabase, get_server_db
# Исправляем импорт config
from src.config import (
    TRUST_LEVEL_UNKNOWN, TRUST_LEVEL_QUARANTINE, TRUST_LEVEL_TRUSTED, TRUST_LEVEL_PRIVILEGED,
    QUARANTINE_DAYS, DAILY_CLIENT_LIMIT, HOURLY_GOSSIP_LIMIT, HOURLY_INCOMING_LIMIT,
    VIOLATION_TYPE_INVALID_SIGNATURE, VIOLATION_TYPE_RATE_LIMIT,
)
from .blacklist import BlacklistManager
from .voting import TrustVotingSystem

logger = logging.getLogger(__name__)


class TrustManager:
    def __init__(self, db: Optional[ServerDatabase] = None):
        self._db = db or get_server_db()
        self._blacklist = BlacklistManager(self._db)
        self._voting = TrustVotingSystem(self._db)
        self._init_tables()

    def _init_tables(self) -> None:
        with self._db._transaction() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_levels (
                    server_id TEXT PRIMARY KEY,
                    level INTEGER DEFAULT 0,
                    charter_version TEXT,
                    charter_lang TEXT,
                    charter_hash TEXT,
                    quarantine_until INTEGER,
                    quarantine_start INTEGER,
                    daily_client_limit INTEGER DEFAULT 50,
                    hourly_gossip_limit INTEGER DEFAULT 10,
                    hourly_incoming_limit INTEGER DEFAULT 100,
                    daily_registrations INTEGER DEFAULT 0,
                    hourly_gossip_count INTEGER DEFAULT 0,
                    hourly_incoming_count INTEGER DEFAULT 0,
                    last_reset_date TEXT,
                    blocked INTEGER DEFAULT 0,
                    blocked_reason TEXT,
                    verified_at INTEGER,
                    verified_by TEXT,
                    last_seen INTEGER,
                    notes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    server_id TEXT PRIMARY KEY,
                    reason TEXT,
                    blocked_at INTEGER,
                    blocked_by TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    violation_type TEXT NOT NULL,
                    details TEXT,
                    created_at INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_server_id TEXT,
                    proposed_level INTEGER,
                    proposed_by TEXT,
                    votes_for INTEGER DEFAULT 0,
                    votes_against INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at INTEGER,
                    expires_at INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trust_levels_server ON trust_levels(server_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_server ON violations(server_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_type ON violations(violation_type)")

    def get_trust_level(self, server_id: str) -> int:
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT level FROM trust_levels WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if row:
                return row["level"]
            return TRUST_LEVEL_UNKNOWN

    def set_trust_level(self, server_id: str, level: int, reason: str = "", verified_by: str = "auto") -> bool:
        now = int(time.time())
        with self._db._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trust_levels
                (server_id, level, verified_at, verified_by, notes, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (server_id, level, now, verified_by, reason, now))
        logger.info(f"Trust level for {server_id} set to {level} by {verified_by}: {reason}")
        return True

    def is_blocked(self, server_id: str) -> bool:
        return self._blacklist.is_blocked(server_id)

    def block_server(self, server_id: str, reason: str, blocked_by: str = "auto") -> bool:
        return self._blacklist.block(server_id, reason, blocked_by)

    def unblock_server(self, server_id: str) -> bool:
        return self._blacklist.unblock(server_id)

    def add_to_quarantine(self, server_id: str, charter_version: str = "", charter_lang: str = "") -> bool:
        now = int(time.time())
        quarantine_until = now + (QUARANTINE_DAYS * 86400) + 1
        today = datetime.now().strftime("%Y-%m-%d")

        with self._db._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trust_levels
                (server_id, level, charter_version, charter_lang,
                 quarantine_until, quarantine_start, last_reset_date,
                 daily_client_limit, hourly_gossip_limit, hourly_incoming_limit,
                 daily_registrations, hourly_gossip_count, hourly_incoming_count,
                 last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
            """, (server_id, TRUST_LEVEL_QUARANTINE, charter_version, charter_lang,
                  quarantine_until, now, today, DAILY_CLIENT_LIMIT, HOURLY_GOSSIP_LIMIT,
                  HOURLY_INCOMING_LIMIT, now))
        logger.info(f"Server {server_id} added to quarantine until {quarantine_until}")
        return True

    def is_in_quarantine(self, server_id: str) -> bool:
        level = self.get_trust_level(server_id)
        if level != TRUST_LEVEL_QUARANTINE:
            return False
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT quarantine_until FROM trust_levels WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if row and row["quarantine_until"]:
                return time.time() < row["quarantine_until"]
        return False

    def get_quarantine_remaining(self, server_id: str) -> int:
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT quarantine_until FROM trust_levels WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if row and row["quarantine_until"]:
                remaining = row["quarantine_until"] - int(time.time())
                return max(0, remaining)
        return 0

    def promote_from_quarantine(self, server_id: str) -> bool:
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT level, quarantine_until FROM trust_levels WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if not row or row["level"] != TRUST_LEVEL_QUARANTINE:
                return False
            quarantine_until = row["quarantine_until"]
            if not quarantine_until or time.time() < quarantine_until:
                return False

            cursor = conn.execute("SELECT COUNT(*) FROM violations WHERE server_id = ?", (server_id,))
            violations_count = cursor.fetchone()[0]
            if violations_count > 0:
                new_until = int(time.time()) + (QUARANTINE_DAYS * 86400) + 1
                conn.execute("UPDATE trust_levels SET quarantine_until = ?, quarantine_start = ? WHERE server_id = ?",
                            (new_until, int(time.time()), server_id))
                return False

            conn.execute("""
                UPDATE trust_levels
                SET level = ?, verified_at = ?, verified_by = ?, notes = ?
                WHERE server_id = ?
            """, (TRUST_LEVEL_TRUSTED, int(time.time()), "auto", "Auto-promoted after quarantine", server_id))
        logger.info(f"Server {server_id} promoted from quarantine to trusted")
        return True

    def reset_quarantine(self, server_id: str) -> bool:
        now = int(time.time())
        quarantine_until = now + (QUARANTINE_DAYS * 86400) + 1
        today = datetime.now().strftime("%Y-%m-%d")
        with self._db._transaction() as conn:
            conn.execute("""
                UPDATE trust_levels
                SET quarantine_until = ?, quarantine_start = ?, last_reset_date = ?,
                    daily_registrations = 0, hourly_gossip_count = 0, hourly_incoming_count = 0, last_seen = ?
                WHERE server_id = ?
            """, (quarantine_until, now, today, now, server_id))
        logger.warning(f"Quarantine reset for {server_id}")
        return True

    def record_violation(self, server_id: str, violation_type: str, details: str = "") -> int:
        now = int(time.time())
        with self._db._transaction() as conn:
            conn.execute("INSERT INTO violations (server_id, violation_type, details, created_at) VALUES (?, ?, ?, ?)",
                        (server_id, violation_type, details, now))
            cursor = conn.execute("SELECT COUNT(*) FROM violations WHERE server_id = ?", (server_id,))
            count = cursor.fetchone()[0]
        logger.warning(f"Violation recorded for {server_id}: {violation_type} - {details}")

        if violation_type == VIOLATION_TYPE_INVALID_SIGNATURE:
            self.block_server(server_id, f"Invalid signature: {details}")
        elif violation_type == VIOLATION_TYPE_RATE_LIMIT and self.is_in_quarantine(server_id):
            self.reset_quarantine(server_id)
        return count

    def get_violations_count(self, server_id: str, days: int = 30) -> int:
        cutoff = int(time.time()) - (days * 86400)
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM violations WHERE server_id = ? AND created_at > ?", (server_id, cutoff))
            return cursor.fetchone()[0]

    def get_violations(self, server_id: str, limit: int = 100) -> List[Dict]:
        with self._db._transaction() as conn:
            cursor = conn.execute("""
                SELECT id, violation_type, details, created_at
                FROM violations WHERE server_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (server_id, limit))
            return [{"id": row["id"], "type": row["violation_type"], "details": row["details"], "created_at": row["created_at"]}
                    for row in cursor.fetchall()]

    def check_and_increment(self, server_id: str, action: str, limit: int = None, period: str = "hour") -> bool:
        level = self.get_trust_level(server_id)
        if level >= TRUST_LEVEL_TRUSTED:
            return True
        if level != TRUST_LEVEL_QUARANTINE:
            return False

        now = time.time()
        today = datetime.now().strftime("%Y-%m-%d")

        with self._db._transaction() as conn:
            cursor = conn.execute("""
                SELECT daily_registrations, hourly_gossip_count, hourly_incoming_count, last_reset_date
                FROM trust_levels WHERE server_id = ?
            """, (server_id,))
            row = cursor.fetchone()
            if not row:
                return False

            daily_reg = row["daily_registrations"] or 0
            hourly_gossip = row["hourly_gossip_count"] or 0
            hourly_incoming = row["hourly_incoming_count"] or 0
            last_reset = row["last_reset_date"] or ""

            if last_reset != today:
                daily_reg = 0
                hourly_gossip = 0
                hourly_incoming = 0

            if action == "registration":
                if daily_reg >= (limit or DAILY_CLIENT_LIMIT):
                    self.record_violation(server_id, VIOLATION_TYPE_RATE_LIMIT, "Daily registration limit exceeded")
                    return False
                daily_reg += 1
            elif action == "gossip_out":
                if hourly_gossip >= (limit or HOURLY_GOSSIP_LIMIT):
                    self.record_violation(server_id, VIOLATION_TYPE_RATE_LIMIT, "Hourly gossip out limit exceeded")
                    return False
                hourly_gossip += 1
            elif action == "gossip_in":
                if hourly_incoming >= (limit or HOURLY_INCOMING_LIMIT):
                    self.record_violation(server_id, VIOLATION_TYPE_RATE_LIMIT, "Hourly gossip in limit exceeded")
                    return False
                hourly_incoming += 1

            conn.execute("""
                UPDATE trust_levels
                SET daily_registrations = ?, hourly_gossip_count = ?, hourly_incoming_count = ?,
                    last_reset_date = ?, last_seen = ?
                WHERE server_id = ?
            """, (daily_reg, hourly_gossip, hourly_incoming, today, int(now), server_id))

        return True

    def update_last_seen(self, server_id: str) -> None:
        with self._db._transaction() as conn:
            conn.execute("UPDATE trust_levels SET last_seen = ? WHERE server_id = ?", (int(time.time()), server_id))

    def get_stats(self, server_id: str) -> Dict:
        with self._db._transaction() as conn:
            cursor = conn.execute("""
                SELECT level, blocked, quarantine_until, quarantine_start,
                       daily_registrations, hourly_gossip_count, hourly_incoming_count,
                       verified_at, verified_by, last_seen
                FROM trust_levels WHERE server_id = ?
            """, (server_id,))
            row = cursor.fetchone()
            if not row:
                return {"level": TRUST_LEVEL_UNKNOWN, "blocked": False}
            return {
                "level": row["level"],
                "blocked": bool(row["blocked"]),
                "quarantine_until": row["quarantine_until"],
                "quarantine_start": row["quarantine_start"],
                "quarantine_remaining": max(0, (row["quarantine_until"] or 0) - int(time.time())),
                "daily_registrations": row["daily_registrations"] or 0,
                "hourly_gossip_count": row["hourly_gossip_count"] or 0,
                "hourly_incoming_count": row["hourly_incoming_count"] or 0,
                "verified_at": row["verified_at"],
                "verified_by": row["verified_by"],
                "last_seen": row["last_seen"],
            }

    def get_all_trusted_servers(self, min_level: int = TRUST_LEVEL_TRUSTED) -> List[str]:
        with self._db._transaction() as conn:
            cursor = conn.execute("SELECT server_id FROM trust_levels WHERE level >= ? AND blocked = 0", (min_level,))
            return [row["server_id"] for row in cursor.fetchall()]

    def get_voting_system(self) -> TrustVotingSystem:
        return self._voting


_trust_manager: Optional[TrustManager] = None


def get_trust_manager() -> TrustManager:
    global _trust_manager
    if _trust_manager is None:
        _trust_manager = TrustManager()
    return _trust_manager
