# src/client/messaging/invite.py
"""
Протокол приглашений с поддержкой БД и автоматическим добавлением контактов.
"""

import secrets
import time
import hashlib
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from src.common.crypto.keys import sign, verify
from src.common.identity.public_id import is_client_id
from src.config import INVITE_TTL_SECONDS, INVITE_TIMESTAMP_MAX_AGE, MAX_INVITE_MESSAGE_LEN
# Исправляем импорт SQLiteStorage
from src.common.storage.sqlite import SQLiteStorage

MAX_INVITE_MESSAGE_LEN = MAX_INVITE_MESSAGE_LEN
INVITE_TTL_SECONDS = INVITE_TTL_SECONDS
INVITE_TIMESTAMP_MAX_AGE = INVITE_TIMESTAMP_MAX_AGE


@dataclass
class InviteRequest:
    from_id: str
    to_id: str
    message: str
    timestamp: int
    nonce: str
    signature: str
    session_key_encrypted: Optional[str] = None
    directional: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"from_id": self.from_id, "to_id": self.to_id, "message": self.message,
                "timestamp": self.timestamp, "nonce": self.nonce, "signature": self.signature,
                "session_key_encrypted": self.session_key_encrypted, "directional": self.directional}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InviteRequest":
        return cls(from_id=data["from_id"], to_id=data["to_id"], message=data["message"],
                   timestamp=data["timestamp"], nonce=data["nonce"], signature=data["signature"],
                   session_key_encrypted=data.get("session_key_encrypted"), directional=data.get("directional", True))


@dataclass
class PendingInvite:
    invite_id: str
    request: InviteRequest
    status: str
    created_at: int
    expires_at: int

    def to_dict(self) -> Dict[str, Any]:
        return {"invite_id": self.invite_id, "from_id": self.request.from_id, "to_id": self.request.to_id,
                "message": self.request.message, "status": self.status, "created_at": self.created_at,
                "expires_at": self.expires_at}


@dataclass
class AcceptedInvite:
    invite_id: str
    from_id: str
    to_id: str
    message: str
    accepted_at: int
    created_at: int

    def to_dict(self) -> Dict[str, Any]:
        return {"invite_id": self.invite_id, "from_id": self.from_id, "to_id": self.to_id,
                "message": self.message, "accepted_at": self.accepted_at, "created_at": self.created_at}


class InviteProtocol:
    def __init__(self, spam_protection: Optional[Any] = None, rendezvous_client: Optional[Any] = None,
                 storage: Optional[SQLiteStorage] = None, server_db: Optional[SQLiteStorage] = None):
        self._spam_protection = spam_protection
        self._rendezvous_client = rendezvous_client
        self._storage = storage
        self._server_db = server_db
        self._pending_invites: Dict[str, PendingInvite] = {}
        self._used_nonces: Dict[str, float] = {}

        if self._server_db:
            self._init_invites_table()
        self._load_active_invites()

    def _init_invites_table(self):
        if not self._server_db:
            return
        try:
            self._server_db.execute_sql("""
                CREATE TABLE IF NOT EXISTS invites (
                    invite_id TEXT PRIMARY KEY,
                    from_public_id TEXT NOT NULL,
                    to_public_id TEXT NOT NULL,
                    message TEXT,
                    session_key_encrypted TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    accepted_at INTEGER
                )
            """)
            self._server_db.execute_sql("CREATE INDEX IF NOT EXISTS idx_invites_from_public_id ON invites(from_public_id)")
            self._server_db.execute_sql("CREATE INDEX IF NOT EXISTS idx_invites_to_public_id ON invites(to_public_id)")
            self._server_db.execute_sql("CREATE INDEX IF NOT EXISTS idx_invites_status ON invites(status)")
            self._server_db.execute_sql("CREATE INDEX IF NOT EXISTS idx_invites_expires_at ON invites(expires_at)")
        except Exception as e:
            print(f"Failed to create invites table: {e}")

    def _load_active_invites(self):
        if not self._server_db:
            return
        try:
            cursor = self._server_db.execute_sql("""
                SELECT invite_id, from_public_id, to_public_id, message, session_key_encrypted,
                       status, created_at, expires_at FROM invites
                WHERE status = 'pending' AND expires_at > ?
            """, (int(time.time()),))
            for row in cursor.fetchall():
                request = InviteRequest(from_id=row[1], to_id=row[2], message=row[3] or "",
                                        timestamp=row[6], nonce="", signature="", session_key_encrypted=row[4])
                invite = PendingInvite(invite_id=row[0], request=request, status=row[5],
                                       created_at=row[6], expires_at=row[7])
                self._pending_invites[row[0]] = invite
        except Exception as e:
            print(f"Failed to load invites from DB: {e}")

    def _generate_invite_id(self, from_id: str, to_id: str, nonce: str) -> str:
        data = f"{from_id}:{to_id}:{nonce}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def _get_account_id_by_public_id(self, public_id: str) -> Optional[bytes]:
        if not self._storage:
            return None
        cursor = self._storage.execute_sql("SELECT account_id FROM accounts WHERE public_id = ? OR server_id = ?",
                                           (public_id, public_id))
        row = cursor.fetchone()
        return row[0] if row else None

    def _add_contact_to_storage(self, storage, user_public_id: str, contact_public_id: str) -> bool:
        if not storage:
            return False
        cursor = storage.execute_sql("SELECT account_id FROM accounts WHERE public_id = ? OR server_id = ?",
                                     (user_public_id, user_public_id))
        row = cursor.fetchone()
        if not row:
            return False
        account_id = row[0]
        from src.client.storage.contacts import ContactsStorage
        contacts = ContactsStorage(storage, account_id)
        if contacts.get(contact_public_id):
            return True
        default_name = contact_public_id.split('@')[1][:10] if '@' in contact_public_id else contact_public_id[:10]
        return contacts.add(contact_public_id, default_name)

    def send_invite(self, from_id: str, to_id: str, message: str, private_key: bytes,
                    session_key: Optional[bytes] = None, get_public_key_func: Optional[Callable] = None,
                    directional: bool = True) -> Dict[str, Any]:
        if not is_client_id(from_id) or not is_client_id(to_id):
            return {"success": False, "error": "invalid_id", "message": "Both IDs must be client IDs"}
        if from_id == to_id:
            return {"success": False, "error": "cannot_invite_self", "message": "Cannot invite yourself"}
        if len(message) > MAX_INVITE_MESSAGE_LEN:
            return {"success": False, "error": "message_too_long", "message": f"Message too long (max {MAX_INVITE_MESSAGE_LEN})"}

        if self._spam_protection:
            if hasattr(self._spam_protection, 'is_blocked') and self._spam_protection.is_blocked(from_id):
                return {"success": False, "error": "sender_blocked", "message": "You are blocked from sending invites"}
            if hasattr(self._spam_protection, 'get_remaining_invites'):
                remaining = self._spam_protection.get_remaining_invites(from_id)
                if remaining <= 0:
                    return {"success": False, "error": "invite_limit_reached", "message": "Daily invite limit reached"}

        if self._server_db:
            cursor = self._server_db.execute_sql("""
                SELECT invite_id, status FROM invites WHERE from_public_id = ? AND to_public_id = ?
                AND status IN ('pending', 'accepted')
            """, (from_id, to_id))
            if cursor.fetchone():
                return {"success": False, "error": "invite_already_exists", "message": "Invite already exists"}

        if session_key is None:
            session_key = secrets.token_bytes(32)

        session_key_encrypted = None
        if get_public_key_func:
            recipient_pubkey = get_public_key_func(to_id)
            if recipient_pubkey:
                session_key_encrypted = session_key.hex()

        nonce = secrets.token_urlsafe(16)
        timestamp = int(time.time())
        sign_data = f"{from_id}:{to_id}:{message}:{timestamp}:{nonce}".encode()
        signature = sign(private_key, sign_data).hex()

        request = InviteRequest(from_id=from_id, to_id=to_id, message=message, timestamp=timestamp,
                                nonce=nonce, signature=signature, session_key_encrypted=session_key_encrypted,
                                directional=directional)
        invite_id = self._generate_invite_id(from_id, to_id, nonce)

        if self._server_db:
            try:
                self._server_db.execute_sql("""
                    INSERT OR REPLACE INTO invites
                    (invite_id, from_public_id, to_public_id, message, session_key_encrypted,
                     status, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """, (invite_id, from_id, to_id, message, session_key_encrypted, timestamp, timestamp + INVITE_TTL_SECONDS))
            except Exception as e:
                return {"success": False, "error": "db_error", "message": str(e)}

        self._pending_invites[invite_id] = PendingInvite(invite_id=invite_id, request=request, status="pending",
                                                         created_at=timestamp, expires_at=timestamp + INVITE_TTL_SECONDS)
        return {"success": True, "invite_id": invite_id, "session_key": session_key, "request": request.to_dict()}

    def verify_invite_signature(self, request: InviteRequest, get_public_key_func: Callable[[str], Optional[bytes]]) -> bool:
        sign_data = f"{request.from_id}:{request.to_id}:{request.message}:{request.timestamp}:{request.nonce}".encode()
        signature_bytes = bytes.fromhex(request.signature)
        public_key = get_public_key_func(request.from_id)
        if not public_key:
            return False
        return verify(public_key, signature_bytes, sign_data)

    def is_invite_expired(self, request: InviteRequest) -> bool:
        now = int(time.time())
        return now - request.timestamp > INVITE_TIMESTAMP_MAX_AGE

    def is_nonce_used(self, nonce: str) -> bool:
        if nonce in self._used_nonces:
            return True
        self._used_nonces[nonce] = time.time()
        now = time.time()
        expired = [n for n, ts in self._used_nonces.items() if now - ts > 3600]
        for n in expired:
            del self._used_nonces[n]
        return False

    def process_invite(self, request_dict: Dict[str, Any],
                       get_public_key_func: Callable[[str], Optional[bytes]]) -> Dict[str, Any]:
        request = InviteRequest.from_dict(request_dict)
        if not self.verify_invite_signature(request, get_public_key_func):
            return {"success": False, "error": "invalid_signature", "message": "Invalid signature"}
        if self.is_invite_expired(request):
            return {"success": False, "error": "invite_expired", "message": "Invite expired"}
        if self.is_nonce_used(request.nonce):
            return {"success": False, "error": "duplicate_nonce", "message": "Duplicate invite detected"}

        invite_id = self._generate_invite_id(request.from_id, request.to_id, request.nonce)
        if invite_id in self._pending_invites:
            existing = self._pending_invites[invite_id]
            return {"success": True, "invite_id": invite_id, "from_id": existing.request.from_id,
                    "message": existing.request.message}

        now = int(time.time())
        if self._server_db:
            try:
                cursor = self._server_db.execute_sql("SELECT 1 FROM invites WHERE invite_id = ?", (invite_id,))
                if cursor.fetchone():
                    cursor = self._server_db.execute_sql("SELECT from_public_id, message FROM invites WHERE invite_id = ?", (invite_id,))
                    row = cursor.fetchone()
                    if row:
                        return {"success": True, "invite_id": invite_id, "from_id": row[0], "message": row[1]}
                self._server_db.execute_sql("""
                    INSERT OR IGNORE INTO invites
                    (invite_id, from_public_id, to_public_id, message, session_key_encrypted,
                     status, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """, (invite_id, request.from_id, request.to_id, request.message,
                      request.session_key_encrypted, now, now + INVITE_TTL_SECONDS))
            except Exception as e:
                return {"success": False, "error": "db_error", "message": str(e)}

        invite = PendingInvite(invite_id=invite_id, request=request, status="pending",
                               created_at=now, expires_at=now + INVITE_TTL_SECONDS)
        self._pending_invites[invite_id] = invite
        return {"success": True, "invite_id": invite_id, "from_id": request.from_id, "message": request.message}

    def get_pending_invites(self, for_id: str) -> List[Dict[str, Any]]:
        invites = []
        now = int(time.time())
        if self._server_db:
            try:
                cursor = self._server_db.execute_sql("""
                    SELECT invite_id, from_public_id, to_public_id, message, status, created_at, expires_at
                    FROM invites WHERE to_public_id = ? AND status = 'pending' AND expires_at > ?
                    ORDER BY created_at DESC
                """, (for_id, now))
                for row in cursor.fetchall():
                    invites.append({"invite_id": row[0], "from_id": row[1], "to_id": row[2], "message": row[3],
                                    "status": row[4], "created_at": row[5], "expires_at": row[6]})
            except Exception as e:
                print(f"Failed to get invites from DB: {e}")
        return invites

    def get_sent_invites(self, from_id: str) -> List[Dict[str, Any]]:
        invites = []
        if self._server_db:
            try:
                cursor = self._server_db.execute_sql("""
                    SELECT invite_id, to_public_id, message, status, created_at, expires_at
                    FROM invites WHERE from_public_id = ? ORDER BY created_at DESC
                """, (from_id,))
                for row in cursor.fetchall():
                    invites.append({"invite_id": row[0], "to_id": row[1], "message": row[2],
                                    "status": row[3], "created_at": row[4], "expires_at": row[5]})
            except Exception as e:
                print(f"Failed to get sent invites from DB: {e}")
        return invites

    def revoke_invite(self, invite_id: str, from_id: str) -> Dict[str, Any]:
        if self._server_db:
            cursor = self._server_db.execute_sql("SELECT from_public_id, status FROM invites WHERE invite_id = ?", (invite_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "invite_not_found"}
            if row[0] != from_id:
                return {"success": False, "error": "not_your_invite"}
            if row[1] != 'pending':
                return {"success": False, "error": f"invite_already_{row[1]}"}
            self._server_db.execute_sql("UPDATE invites SET status = 'revoked' WHERE invite_id = ?", (invite_id,))
            if invite_id in self._pending_invites:
                del self._pending_invites[invite_id]
            return {"success": True}
        return {"success": False, "error": "db_error"}

    def get_accepted_invites(self, user_id: str) -> List[Dict[str, Any]]:
        accepted = []
        if self._server_db:
            try:
                cursor = self._server_db.execute_sql("""
                    SELECT invite_id, from_public_id, to_public_id, message, created_at, accepted_at
                    FROM invites WHERE (from_public_id = ? OR to_public_id = ?) AND status = 'accepted'
                    ORDER BY accepted_at DESC
                """, (user_id, user_id))
                for row in cursor.fetchall():
                    accepted.append({"invite_id": row[0], "from_id": row[1], "to_id": row[2], "message": row[3],
                                     "created_at": row[4], "accepted_at": row[5]})
            except Exception as e:
                print(f"Failed to get accepted invites from DB: {e}")
        return accepted

    def get_contacts(self, user_id: str) -> List[str]:
        accepted = self.get_accepted_invites(user_id)
        contacts = set()
        for invite in accepted:
            if invite["from_id"] == user_id:
                contacts.add(invite["to_id"])
            else:
                contacts.add(invite["from_id"])
        return list(contacts)

    def accept_invite(self, invite_id: str, accepter_id: str, private_key: bytes) -> Dict[str, Any]:
        invite = self._pending_invites.get(invite_id)
        if not invite and self._server_db:
            try:
                cursor = self._server_db.execute_sql("""
                    SELECT from_public_id, to_public_id, message, session_key_encrypted
                    FROM invites WHERE invite_id = ? AND status = 'pending'
                """, (invite_id,))
                row = cursor.fetchone()
                if row:
                    request = InviteRequest(from_id=row[0], to_id=row[1], message=row[2] or "",
                                            timestamp=0, nonce="", signature="", session_key_encrypted=row[3])
                    invite = PendingInvite(invite_id=invite_id, request=request, status="pending", created_at=0, expires_at=0)
            except Exception as e:
                return {"success": False, "error": "db_error", "message": str(e)}

        if not invite:
            return {"success": False, "error": "invite_not_found", "message": "Invite not found"}
        if invite.request.to_id != accepter_id:
            return {"success": False, "error": "not_for_you", "message": "This invite is not for you"}

        session_key = None
        if invite.request.session_key_encrypted:
            try:
                session_key = bytes.fromhex(invite.request.session_key_encrypted)
            except:
                pass
        if not session_key:
            session_key = secrets.token_bytes(32)

        if self._server_db:
            try:
                self._server_db.execute_sql("UPDATE invites SET status = 'accepted', accepted_at = ? WHERE invite_id = ?",
                                           (int(time.time()), invite_id))
            except Exception as e:
                print(f"Failed to update invite status: {e}")

        invite.status = "accepted"
        session_key_hex = session_key.hex()
        now = int(time.time())

        storage_for_dialogs = self._storage if self._storage else self._server_db
        if storage_for_dialogs:
            try:
                storage_for_dialogs.save_dialog(accepter_id, invite.request.from_id, session_key_hex)
                storage_for_dialogs.save_dialog(invite.request.from_id, accepter_id, session_key_hex)
            except Exception as e:
                print(f"[ERROR] Failed to save dialog: {e}")

        if storage_for_dialogs:
            self._add_contact_to_storage(storage_for_dialogs, accepter_id, invite.request.from_id)
            self._add_contact_to_storage(storage_for_dialogs, invite.request.from_id, accepter_id)

        return {"success": True, "dialog_id": f"dialog_{invite_id[:16]}",
                "peer_id": invite.request.from_id, "session_key": session_key_hex}

    def reject_invite(self, invite_id: str, rejecter_id: str) -> Dict[str, Any]:
        from_id = None
        if invite_id in self._pending_invites:
            from_id = self._pending_invites[invite_id].request.from_id
        elif self._server_db:
            cursor = self._server_db.execute_sql("SELECT from_public_id FROM invites WHERE invite_id = ?", (invite_id,))
            row = cursor.fetchone()
            if row:
                from_id = row[0]

        if self._server_db:
            try:
                self._server_db.execute_sql("UPDATE invites SET status = 'rejected' WHERE invite_id = ? AND to_public_id = ?",
                                           (invite_id, rejecter_id))
            except Exception as e:
                return {"success": False, "error": "db_error", "message": str(e)}

        if invite_id in self._pending_invites:
            del self._pending_invites[invite_id]

        if from_id and self._spam_protection:
            self._spam_protection.record_rejection(from_id)

        return {"success": True}

    def cleanup_expired(self) -> int:
        now = int(time.time())
        expired = [invite_id for invite_id, invite in self._pending_invites.items() if invite.expires_at < now]
        for invite_id in expired:
            del self._pending_invites[invite_id]
        if self._server_db:
            try:
                cursor = self._server_db.execute_sql("DELETE FROM invites WHERE expires_at < ? AND status = 'pending'", (now,))
                return cursor.rowcount
            except Exception as e:
                print(f"Failed to cleanup expired invites: {e}")
        return len(expired)
