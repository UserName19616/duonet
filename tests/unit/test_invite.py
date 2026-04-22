# tests/unit/test_invite.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
import hashlib
import tempfile
import time
from unittest.mock import MagicMock
import pytest
from src.common.crypto.keys import generate_keypair, verify, sign
from src.common.identity.account import AccountManager
from src.common.identity.public_id import generate_public_id
from src.client.messaging.invite import (
    MAX_INVITE_MESSAGE_LEN,
    InviteProtocol,
    PendingInvite,
    AcceptedInvite,
    InviteRequest,
)
from src.client.messaging.spam_protection import SpamProtection
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def server_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def ws_manager():
    return MockWebSocketManager()


@pytest.fixture
def account_manager(storage, ws_manager):
    rate_limiter = MultiRateLimiter()
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
        ws_manager=ws_manager,
    )


@pytest.fixture
def spam_protection():
    """Мок для защиты от спама."""
    mock = MagicMock(spec=SpamProtection)
    mock.is_blocked.return_value = False
    mock.get_remaining_invites.return_value = 50
    mock.record_rejection = MagicMock()
    return mock


@pytest.fixture
def alice_protocol(spam_protection, storage, server_db):
    return InviteProtocol(spam_protection, storage=storage, server_db=server_db)


@pytest.fixture
def bob_protocol(spam_protection, storage, server_db):
    return InviteProtocol(spam_protection, storage=storage, server_db=server_db)


@pytest.fixture
def test_users(account_manager):
    """Создаёт двух пользователей через account_manager."""
    alice = account_manager.register("alice_test_seed", "pass123456", False, "127.0.0.1")
    bob = account_manager.register("bob_test_seed", "pass123456", False, "127.0.0.1")
    assert alice["success"]
    assert bob["success"]
    return {
        "alice": {
            "id": alice["public_id"],
            "account_id": alice["account_id"],
            "seed_phrase": "alice_test_seed",
            "private_key": account_manager.get_private_key(alice["account_id"], "alice_test_seed"),
            "public_key": account_manager.get_public_key(alice["account_id"]),
        },
        "bob": {
            "id": bob["public_id"],
            "account_id": bob["account_id"],
            "seed_phrase": "bob_test_seed",
            "private_key": account_manager.get_private_key(bob["account_id"], "bob_test_seed"),
            "public_key": account_manager.get_public_key(bob["account_id"]),
        },
    }


class TestInviteProtocol:
    """Тесты для InviteProtocol."""

    def test_send_invite_success(self, alice_protocol, test_users):
        """Успешная отправка приглашения."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет! Давай пообщаемся?",
            private_key=alice["private_key"],
        )
        assert result["success"] is True
        assert "invite_id" in result
        assert "session_key" in result

    def test_send_invite_message_too_long(self, alice_protocol, test_users):
        """Слишком длинное сообщение."""
        alice = test_users["alice"]
        bob = test_users["bob"]
        long_message = "x" * (MAX_INVITE_MESSAGE_LEN + 1)

        result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message=long_message,
            private_key=alice["private_key"],
        )
        assert result["success"] is False
        assert "message_too_long" in result["error"]

    def test_send_invite_to_server(self, alice_protocol, test_users):
        """Отправка приглашения серверу."""
        alice = test_users["alice"]
        seed_hash = hashlib.sha256(b"server_seed").digest()
        server_id = generate_public_id(seed_hash, "ru", is_server=True)

        result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=server_id,
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert result["success"] is False
        assert "invalid_id" in result["error"]

    def test_send_invite_self(self, alice_protocol, test_users):
        """Отправка приглашения самому себе."""
        alice = test_users["alice"]

        result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=alice["id"],
            message="Привет себе!",
            private_key=alice["private_key"],
        )
        assert result["success"] is False
        assert "cannot_invite_self" in result["error"]

    def test_send_invite_blocked(self, alice_protocol, spam_protection, test_users):
        """Отправка приглашения заблокированным пользователем."""
        alice = test_users["alice"]
        bob = test_users["bob"]
        spam_protection.is_blocked.return_value = True

        result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert result["success"] is False
        assert result["error"] == "sender_blocked"

    def test_send_invite_limit_reached(self, alice_protocol, spam_protection, test_users):
        """Превышение лимита приглашений."""
        alice = test_users["alice"]
        bob = test_users["bob"]
        spam_protection.get_remaining_invites.return_value = 0

        result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert result["success"] is False
        assert result["error"] == "invite_limit_reached"

    def test_process_invite_success(self, alice_protocol, bob_protocol, test_users):
        """Успешная обработка входящего приглашения."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        process_result = bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        assert process_result["success"] is True
        assert process_result["invite_id"] == send_result["invite_id"]
        assert process_result["from_id"] == alice["id"]

    def test_process_invite_invalid_signature(self, alice_protocol, bob_protocol, test_users):
        """Обработка с неверной подписью."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        send_result["request"]["signature"] = "00" * 64

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        process_result = bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        assert process_result["success"] is False
        assert "invalid_signature" in process_result["error"]

    def test_process_invite_expired(self, alice_protocol, bob_protocol, test_users):
        """Обработка истекшего приглашения."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        request_dict = send_result["request"].copy()
        expired_timestamp = int(time.time()) - 4000
        request_dict["timestamp"] = expired_timestamp

        sign_data = f"{alice['id']}:{bob['id']}:Привет!:{expired_timestamp}:{request_dict['nonce']}".encode()
        new_signature = sign(alice["private_key"], sign_data).hex()
        request_dict["signature"] = new_signature

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        process_result = bob_protocol.process_invite(
            request_dict,
            get_public_key_func=get_pubkey_func,
        )
        assert process_result["success"] is False
        assert "invite_expired" in process_result["error"]

    def test_process_invite_duplicate(self, alice_protocol, bob_protocol, test_users):
        """Обработка дубликата приглашения."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        process_result1 = bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        assert process_result1["success"] is True

        bob_protocol._used_nonces.clear()

        process_result2 = bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        assert process_result2["success"] is True
        assert process_result2["invite_id"] == process_result1["invite_id"]

    def test_accept_invite_success(self, alice_protocol, bob_protocol, test_users):
        """Успешное принятие приглашения."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )

        result = bob_protocol.accept_invite(
            invite_id=send_result["invite_id"],
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )
        assert result["success"] is True
        assert result["peer_id"] == alice["id"]

    def test_reject_invite_success(self, alice_protocol, bob_protocol, test_users):
        """Успешное отклонение приглашения."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )

        result = bob_protocol.reject_invite(
            invite_id=send_result["invite_id"],
            rejecter_id=bob["id"],
        )
        assert result["success"] is True

    def test_accept_invite_not_found(self, bob_protocol, test_users):
        """Принятие несуществующего приглашения."""
        bob = test_users["bob"]

        result = bob_protocol.accept_invite(
            invite_id="nonexistent",
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )
        assert result["success"] is False
        assert "invite_not_found" in result["error"]

    def test_get_pending_invites(self, alice_protocol, bob_protocol, test_users):
        """Получение списка ожидающих приглашений."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )

        pending = bob_protocol.get_pending_invites(bob["id"])
        assert len(pending) == 1
        assert pending[0]["invite_id"] == send_result["invite_id"]
        assert pending[0]["from_id"] == alice["id"]

    def test_get_accepted_invites(self, alice_protocol, bob_protocol, test_users):
        """Получение списка принятых приглашений."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        bob_protocol.accept_invite(
            invite_id=send_result["invite_id"],
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )

        alice_accepted = alice_protocol.get_accepted_invites(alice["id"])
        assert len(alice_accepted) == 1
        assert alice_accepted[0]["invite_id"] == send_result["invite_id"]

    def test_get_contacts(self, alice_protocol, bob_protocol, test_users):
        """Получение списка контактов пользователя."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        bob_protocol.accept_invite(
            invite_id=send_result["invite_id"],
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )

        alice_contacts = alice_protocol.get_contacts(alice["id"])
        assert len(alice_contacts) == 1
        assert bob["id"] in alice_contacts

    def test_accepted_invites_persistence(self, alice_protocol, bob_protocol, test_users, storage, server_db):
        """Проверка сохранения принятых приглашений в БД."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        bob_protocol.accept_invite(
            invite_id=send_result["invite_id"],
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )

        new_alice_protocol = InviteProtocol(storage=storage, server_db=server_db)
        alice_accepted = new_alice_protocol.get_accepted_invites(alice["id"])
        assert len(alice_accepted) == 1
        assert alice_accepted[0]["invite_id"] == send_result["invite_id"]

    def test_cleanup_expired(self, alice_protocol, bob_protocol, test_users):
        """Очистка истекших приглашений."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )

        if bob_protocol._server_db:
            bob_protocol._server_db.execute_sql(
                "UPDATE invites SET expires_at = ? WHERE invite_id = ?",
                (int(time.time()) - 1, send_result["invite_id"]),
            )

        bob_protocol._load_active_invites()
        cleaned = bob_protocol.cleanup_expired()
        assert cleaned >= 1

    def test_spam_protection_calls(self, alice_protocol, bob_protocol, spam_protection, test_users):
        """Проверка вызовов спам-протектора."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True
        spam_protection.is_blocked.assert_called_with(alice["id"])
        spam_protection.get_remaining_invites.assert_called_with(alice["id"])

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        bob_protocol.reject_invite(send_result["invite_id"], bob["id"])
        spam_protection.record_rejection.assert_called_with(alice["id"])

    def test_invite_id_generation(self, alice_protocol, bob_protocol, test_users):
        """Генерация invite_id и проверка защиты от повторных приглашений."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        # Первое приглашение
        result1 = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет! Первое сообщение",
            private_key=alice["private_key"],
        )
        assert result1["success"] is True

        # Принимаем первое приглашение (устанавливаем диалог)
        def get_public_key_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        bob_protocol.process_invite(
            result1["request"],
            get_public_key_func=get_public_key_func,
        )
        bob_protocol.accept_invite(
            invite_id=result1["invite_id"],
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )

        # Второе приглашение от того же отправителя к тому же получателю
        # Должно быть отклонено (защита от повторных приглашений)
        result2 = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет! Второе сообщение",
            private_key=alice["private_key"],
        )

        # Ожидаем, что второе приглашение будет отклонено
        assert result2["success"] is False
        assert result2["error"] == "invite_already_exists"
        assert "already" in result2["message"].lower()

        # invite_id должны быть разными (если генерируются)
        if result1.get("invite_id") and result2.get("invite_id"):
            assert result1["invite_id"] != result2["invite_id"]

    def test_pending_invite_dataclass(self):
        """Тест dataclass PendingInvite."""
        request = MagicMock()
        pending = PendingInvite(
            invite_id="test_id",
            request=request,
            status="pending",
            created_at=123456,
            expires_at=654321,
        )
        assert pending.invite_id == "test_id"
        assert pending.request == request
        assert pending.status == "pending"
        assert pending.created_at == 123456
        assert pending.expires_at == 654321

    def test_accepted_invite_dataclass(self):
        """Тест dataclass AcceptedInvite."""
        accepted = AcceptedInvite(
            invite_id="test_id",
            from_id="@ALICE.ru",
            to_id="@BOB.ru",
            message="Hello!",
            accepted_at=123456,
            created_at=111111,
        )
        assert accepted.invite_id == "test_id"
        assert accepted.from_id == "@ALICE.ru"
        assert accepted.to_id == "@BOB.ru"
        assert accepted.message == "Hello!"
        assert accepted.accepted_at == 123456
        assert accepted.created_at == 111111

    def test_cross_protocol_invite_flow(self, alice_protocol, bob_protocol, test_users):
        """Сквозной тест: Алиса -> Боб -> ответ."""
        alice = test_users["alice"]
        bob = test_users["bob"]

        send_result = alice_protocol.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет, Боб!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True
        invite_id = send_result["invite_id"]

        def get_pubkey_func(public_id):
            if public_id == alice["id"]:
                return alice["public_key"]
            if public_id == bob["id"]:
                return bob["public_key"]
            return None

        process_result = bob_protocol.process_invite(
            send_result["request"],
            get_public_key_func=get_pubkey_func,
        )
        assert process_result["success"] is True

        pending = bob_protocol.get_pending_invites(bob["id"])
        assert len(pending) == 1
        assert pending[0]["message"] == "Привет, Боб!"

        accept_result = bob_protocol.accept_invite(
            invite_id=invite_id,
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )
        assert accept_result["success"] is True
        assert accept_result["peer_id"] == alice["id"]

        pending_after = bob_protocol.get_pending_invites(bob["id"])
        assert len(pending_after) == 0

        alice_accepted = alice_protocol.get_accepted_invites(alice["id"])
        assert len(alice_accepted) == 1
        bob_accepted = bob_protocol.get_accepted_invites(bob["id"])
        assert len(bob_accepted) == 1

        alice_contacts = alice_protocol.get_contacts(alice["id"])
        assert bob["id"] in alice_contacts
        bob_contacts = bob_protocol.get_contacts(bob["id"])
        assert alice["id"] in bob_contacts


class TestInviteProtocolWithoutStorage:
    """Тесты для InviteProtocol без БД (обратная совместимость)."""

    @pytest.fixture
    def alice_protocol_no_storage(self, spam_protection):
        """Протокол без БД."""
        return InviteProtocol(spam_protection, storage=None, server_db=None)

    @pytest.fixture
    def bob_protocol_no_storage(self, spam_protection):
        """Протокол без БД."""
        return InviteProtocol(spam_protection, storage=None, server_db=None)

    @pytest.fixture
    def test_users_no_storage(self, account_manager):
        """Создаёт двух пользователей через account_manager."""
        alice = account_manager.register("alice_test_seed_nostorage", "pass123456", False, "127.0.0.1")
        bob = account_manager.register("bob_test_seed_nostorage", "pass123456", False, "127.0.0.1")
        assert alice["success"]
        assert bob["success"]
        return {
            "alice": {
                "id": alice["public_id"],
                "private_key": account_manager.get_private_key(alice["account_id"], "alice_test_seed_nostorage"),
            },
            "bob": {
                "id": bob["public_id"],
                "private_key": account_manager.get_private_key(bob["account_id"], "bob_test_seed_nostorage"),
            },
        }

    def test_without_storage_get_accepted_invites_empty(self, alice_protocol_no_storage, test_users_no_storage):
        """Без БД get_accepted_invites возвращает пустой список."""
        alice = test_users_no_storage["alice"]
        result = alice_protocol_no_storage.get_accepted_invites(alice["id"])
        assert result == []

    def test_without_storage_get_contacts_empty(self, alice_protocol_no_storage, test_users_no_storage):
        """Без БД get_contacts возвращает пустой список."""
        alice = test_users_no_storage["alice"]
        result = alice_protocol_no_storage.get_contacts(alice["id"])
        assert result == []

    def test_without_storage_accept_invite_works(self, alice_protocol_no_storage, bob_protocol_no_storage, test_users_no_storage):
        """Без БД принятие приглашения работает (in-memory)."""
        alice = test_users_no_storage["alice"]
        bob = test_users_no_storage["bob"]

        send_result = alice_protocol_no_storage.send_invite(
            from_id=alice["id"],
            to_id=bob["id"],
            message="Привет!",
            private_key=alice["private_key"],
        )
        assert send_result["success"] is True

        request = InviteRequest.from_dict(send_result["request"])

        bob_protocol_no_storage._pending_invites[send_result["invite_id"]] = PendingInvite(
            invite_id=send_result["invite_id"],
            request=request,
            status="pending",
            created_at=int(time.time()),
            expires_at=int(time.time()) + 86400,
        )

        result = bob_protocol_no_storage.accept_invite(
            invite_id=send_result["invite_id"],
            accepter_id=bob["id"],
            private_key=bob["private_key"],
        )
        assert result["success"] is True
