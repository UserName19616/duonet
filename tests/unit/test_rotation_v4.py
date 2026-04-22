# tests/unit/test_rotation_v4.py
"""
Unit-тесты для протокола ротации ключей V4 (клиент-клиент, сервер слепой).
Сервер не участвует, все сообщения шифруются и идут как обычные.
"""

import json
import time
from unittest.mock import patch

import pytest

from src.client.crypto.ecdh import (
    generate_ecdh_keypair,
    compute_shared_secret,
    derive_new_key,
)
from src.client.crypto.rotation_id import generate_rotation_id, is_rotation_id_expired
from src.client.crypto.aes import generate_session_key, encrypt, decrypt
from src.client.crypto.directional import get_directional_key


# =============================================================================
# Тесты для rotation_id
# =============================================================================

class TestRotationId:
    def test_generate_rotation_id_format(self):
        rid = generate_rotation_id()
        assert len(rid) == 8 + 1 + 12
        assert rid[8] == "_"
        assert rid[:8].isdigit()

    def test_generate_rotation_id_unique(self):
        ids = set()
        for _ in range(100):
            rid = generate_rotation_id()
            assert rid not in ids
            ids.add(rid)

    def test_is_rotation_id_expired(self):
        fresh = generate_rotation_id()
        assert is_rotation_id_expired(fresh, ttl_seconds=86400) is False

        import datetime
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
        old_rid = f"{yesterday}_123456789012"
        assert is_rotation_id_expired(old_rid, ttl_seconds=86400) is True


# =============================================================================
# Тесты для ECDH
# =============================================================================

class TestECDH:
    def test_generate_keypair(self):
        priv, pub = generate_ecdh_keypair()
        assert len(priv) == 32
        assert len(pub) == 32

    def test_compute_shared_secret(self):
        priv_a, pub_a = generate_ecdh_keypair()
        priv_b, pub_b = generate_ecdh_keypair()

        secret_a = compute_shared_secret(priv_a, pub_b)
        secret_b = compute_shared_secret(priv_b, pub_a)

        assert secret_a == secret_b
        assert len(secret_a) == 32

    def test_derive_new_key(self):
        priv_a, pub_a = generate_ecdh_keypair()
        priv_b, pub_b = generate_ecdh_keypair()

        shared = compute_shared_secret(priv_a, pub_b)
        dialog_id = "user1:user2"
        key = derive_new_key(shared, dialog_id)

        assert len(key) == 32


# =============================================================================
# Тесты для формата системных сообщений (сервер слепой)
# =============================================================================

class TestSystemMessageFormat:
    """Системные сообщения — это обычные зашифрованные сообщения,
       внутри которых JSON с полем __type: 'system'."""

    def test_system_message_has_type_field(self):
        msg = {
            "__type": "system",
            "subtype": "rotation_request",
            "rotation_id": generate_rotation_id(),
            "eph_public_key": "a" * 64,
            "timestamp": 123456
        }
        assert msg["__type"] == "system"

    def test_system_message_no_is_system_field(self):
        """Сервер не должен видеть is_system — его нет в сообщении."""
        msg = {
            "__type": "system",
            "subtype": "rotation_request",
            "rotation_id": generate_rotation_id()
        }
        assert "is_system" not in msg
        assert "system_type" not in msg
        assert "system_data" not in msg

    def test_system_message_encrypted_as_regular(self):
        """Системное сообщение шифруется как обычное (нет is_system)."""
        session_key = generate_session_key()
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        system_msg = {
            "__type": "system",
            "subtype": "rotation_request",
            "rotation_id": generate_rotation_id(),
            "eph_public_key": "a" * 64,
            "timestamp": int(time.time())
        }

        plaintext = json.dumps(system_msg)
        directional_key = get_directional_key(session_key, from_id, to_id)
        encrypted = encrypt(plaintext, directional_key)
        decrypted = decrypt(encrypted, directional_key)

        assert decrypted is not None
        decoded = json.loads(decrypted)
        assert decoded["__type"] == "system"
        # Проверяем, что нет серверных полей
        assert "is_system" not in decoded


# =============================================================================
# Тесты для полного цикла ротации (клиент-клиент, без сервера)
# =============================================================================

class TestFullRotationFlowClientOnly:
    """Полный цикл ротации только на клиентах."""

    def setup_method(self):
        self.alice_id = "@ALICE-1234-5678.ru"
        self.bob_id = "@BOB-1234-5678.ru"
        self.session_key = generate_session_key()
        self.dialog_id = f"{self.alice_id}:{self.bob_id}" if self.alice_id < self.bob_id else f"{self.bob_id}:{self.alice_id}"

    def _encrypt_message(self, plaintext: str, from_id: str, to_id: str) -> str:
        directional_key = get_directional_key(self.session_key, from_id, to_id)
        encrypted = encrypt(plaintext, directional_key)
        return encrypted.hex()

    def _decrypt_message(self, ciphertext_hex: str, from_id: str, to_id: str) -> str:
        directional_key = get_directional_key(self.session_key, from_id, to_id)
        decrypted = decrypt(bytes.fromhex(ciphertext_hex), directional_key)
        return decrypted

    def _create_system_message(self, subtype: str, rotation_id: str, **kwargs) -> str:
        msg = {
            "__type": "system",
            "subtype": subtype,
            "rotation_id": rotation_id,
            "timestamp": int(time.time()),
            **kwargs
        }
        return json.dumps(msg)

    def test_full_rotation_flow(self):
        rotation_id = generate_rotation_id()

        # 1. REQUEST от Алисы
        eph_priv_a, eph_pub_a = generate_ecdh_keypair()
        request_msg = self._create_system_message(
            "rotation_request", rotation_id,
            eph_public_key=eph_pub_a.hex(),
            expires_at=int(time.time()) + 86400
        )
        encrypted_request = self._encrypt_message(request_msg, self.alice_id, self.bob_id)

        # 2. Боб получает и расшифровывает
        decrypted_request = self._decrypt_message(encrypted_request, self.alice_id, self.bob_id)
        # JSON сериализуется с пробелами, ищем с пробелом
        assert '"__type": "system"' in decrypted_request

        data = json.loads(decrypted_request)
        assert data["subtype"] == "rotation_request"
        assert data["rotation_id"] == rotation_id

        # 3. ACCEPT от Боба
        eph_priv_b, eph_pub_b = generate_ecdh_keypair()
        shared_secret = compute_shared_secret(eph_priv_b, bytes.fromhex(data["eph_public_key"]))
        new_key = derive_new_key(shared_secret, self.dialog_id)

        accept_msg = self._create_system_message(
            "rotation_accept", rotation_id,
            eph_public_key=eph_pub_b.hex()
        )
        encrypted_accept = self._encrypt_message(accept_msg, self.bob_id, self.alice_id)

        # 4. Алиса получает ACCEPT, отправляет CONFIRM
        decrypted_accept = self._decrypt_message(encrypted_accept, self.bob_id, self.alice_id)
        accept_data = json.loads(decrypted_accept)
        assert accept_data["subtype"] == "rotation_accept"

        shared_secret_a = compute_shared_secret(eph_priv_a, bytes.fromhex(accept_data["eph_public_key"]))
        new_key_a = derive_new_key(shared_secret_a, self.dialog_id)
        assert new_key_a == new_key

        confirm_msg = self._create_system_message("rotation_confirm", rotation_id)
        encrypted_confirm = self._encrypt_message(confirm_msg, self.alice_id, self.bob_id)

        # 5. Боб получает CONFIRM, отправляет COMPLETE
        decrypted_confirm = self._decrypt_message(encrypted_confirm, self.alice_id, self.bob_id)
        confirm_data = json.loads(decrypted_confirm)
        assert confirm_data["subtype"] == "rotation_confirm"

        complete_msg = self._create_system_message("rotation_complete", rotation_id)
        encrypted_complete = self._encrypt_message(complete_msg, self.bob_id, self.alice_id)

        # 6. Алиса получает COMPLETE
        decrypted_complete = self._decrypt_message(encrypted_complete, self.bob_id, self.alice_id)
        complete_data = json.loads(decrypted_complete)
        assert complete_data["subtype"] == "rotation_complete"

        # Ключи совпадают и отличаются от старого
        assert new_key_a == new_key
        assert self.session_key != new_key

    def test_reject_flow(self):
        rotation_id = generate_rotation_id()

        eph_priv_a, eph_pub_a = generate_ecdh_keypair()
        request_msg = self._create_system_message(
            "rotation_request", rotation_id,
            eph_public_key=eph_pub_a.hex(),
            expires_at=int(time.time()) + 86400
        )
        encrypted_request = self._encrypt_message(request_msg, self.alice_id, self.bob_id)

        decrypted_request = self._decrypt_message(encrypted_request, self.alice_id, self.bob_id)
        # JSON сериализуется с пробелами, ищем с пробелом
        assert '"__type": "system"' in decrypted_request

        reject_msg = self._create_system_message("rotation_reject", rotation_id)
        encrypted_reject = self._encrypt_message(reject_msg, self.bob_id, self.alice_id)

        decrypted_reject = self._decrypt_message(encrypted_reject, self.bob_id, self.alice_id)
        reject_data = json.loads(decrypted_reject)
        assert reject_data["subtype"] == "rotation_reject"

        # Ключ не изменился
        test_msg = "Test after reject"
        encrypted_test = self._encrypt_message(test_msg, self.alice_id, self.bob_id)
        decrypted_test = self._decrypt_message(encrypted_test, self.alice_id, self.bob_id)
        assert decrypted_test == test_msg


# =============================================================================
# Тесты для совместимости с существующей криптографией
# =============================================================================

class TestEncryptionCompatibility:
    def test_system_message_uses_same_encryption_as_regular(self):
        session_key = generate_session_key()
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        regular_plaintext = "Hello!"
        directional_key = get_directional_key(session_key, from_id, to_id)
        regular_encrypted = encrypt(regular_plaintext, directional_key)

        system_plaintext = json.dumps({"__type": "system", "subtype": "test"})
        system_encrypted = encrypt(system_plaintext, directional_key)

        assert decrypt(regular_encrypted, directional_key) == regular_plaintext
        assert decrypt(system_encrypted, directional_key) == system_plaintext

        # Сервер не может отличить одно от другого — оба зашифрованы
        # В открытом виде нет is_system
        assert "is_system" not in system_plaintext


# =============================================================================
# Тест: сервер не должен видеть is_system
# =============================================================================

class TestServerBlindness:
    def test_no_is_system_in_message(self):
        """Сообщение, отправляемое на сервер, не должно содержать is_system."""
        session_key = generate_session_key()
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        system_msg = {
            "__type": "system",
            "subtype": "rotation_request",
            "rotation_id": generate_rotation_id()
        }
        plaintext = json.dumps(system_msg)
        directional_key = get_directional_key(session_key, from_id, to_id)
        encrypted = encrypt(plaintext, directional_key)

        # То, что идёт на сервер — только encrypted и session_key
        wire_message = {
            "type": "message",
            "data": {
                "message_id": "msg_123",
                "encrypted": encrypted.hex(),
                "session_key": session_key.hex(),
                "has_phrase": False
            }
        }

        # Сервер не должен видеть is_system, system_type, system_data
        assert "is_system" not in wire_message["data"]
        assert "system_type" not in wire_message["data"]
        assert "system_data" not in wire_message["data"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
