# tests/unit/test_directional.py
"""
Тесты для направленного шифрования.
"""

import pytest

from src.client.crypto.aes import generate_session_key
from src.client.crypto.directional import (
    get_directional_key,
    encrypt_directional,
    decrypt_directional,
)


class TestDirectionalKey:
    """Тесты для функции get_directional_key."""

    def test_keys_for_different_directions_are_different(self):
        """Ключи для разных направлений должны отличаться."""
        session_key = generate_session_key()
        key_ab = get_directional_key(session_key, "@A.ru", "@B.ru")
        key_ba = get_directional_key(session_key, "@B.ru", "@A.ru")
        assert key_ab != key_ba

    def test_keys_for_same_direction_are_same(self):
        """Ключи для одинакового направления должны совпадать."""
        session_key = generate_session_key()
        key1 = get_directional_key(session_key, "@A.ru", "@B.ru")
        key2 = get_directional_key(session_key, "@A.ru", "@B.ru")
        assert key1 == key2

    def test_key_length(self):
        """Длина ключа должна быть 32 байта."""
        session_key = generate_session_key()
        key = get_directional_key(session_key, "@A.ru", "@B.ru")
        assert len(key) == 32

    def test_different_session_keys_produce_different_directional_keys(self):
        """Разные session_key дают разные направленные ключи."""
        sk1 = generate_session_key()
        sk2 = generate_session_key()
        key1 = get_directional_key(sk1, "@A.ru", "@B.ru")
        key2 = get_directional_key(sk2, "@A.ru", "@B.ru")
        assert key1 != key2

    def test_directional_key_with_long_ids(self):
        """Длинные Public ID корректно обрабатываются."""
        long_id = "@" + "X" * 50 + ".ru"
        session_key = generate_session_key()
        key = get_directional_key(session_key, long_id, "@B.ru")
        assert len(key) == 32


class TestDirectionalEncryption:
    """Тесты для encrypt_directional и decrypt_directional."""

    def test_encrypt_decrypt_same_direction(self):
        """Шифрование и расшифровка в одном направлении."""
        session_key = generate_session_key()
        plaintext = "Secret message"
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        encrypted = encrypt_directional(plaintext, session_key, from_id, to_id)
        decrypted = decrypt_directional(encrypted, session_key, from_id, to_id)

        assert decrypted == plaintext

    def test_wrong_direction_fails(self):
        """Расшифровка с неправильным направлением должна возвращать None."""
        session_key = generate_session_key()
        plaintext = "Secret message"

        # Алиса → Боб
        encrypted = encrypt_directional(plaintext, session_key, "@ALICE.ru", "@BOB.ru")

        # Боб пытается расшифровать с направлением Боб → Алиса (неправильно)
        decrypted = decrypt_directional(encrypted, session_key, "@BOB.ru", "@ALICE.ru")

        assert decrypted is None

    def test_wrong_session_key_fails(self):
        """Расшифровка с неправильным session_key должна возвращать None."""
        sk1 = generate_session_key()
        sk2 = generate_session_key()
        plaintext = "Secret message"

        encrypted = encrypt_directional(plaintext, sk1, "@ALICE.ru", "@BOB.ru")
        decrypted = decrypt_directional(encrypted, sk2, "@ALICE.ru", "@BOB.ru")

        assert decrypted is None

    def test_empty_message(self):
        """Пустое сообщение."""
        session_key = generate_session_key()
        encrypted = encrypt_directional("", session_key, "@A.ru", "@B.ru")
        decrypted = decrypt_directional(encrypted, session_key, "@A.ru", "@B.ru")
        assert decrypted == ""

    def test_long_message(self):
        """Длинное сообщение."""
        session_key = generate_session_key()
        plaintext = "X" * 10000
        encrypted = encrypt_directional(plaintext, session_key, "@A.ru", "@B.ru")
        decrypted = decrypt_directional(encrypted, session_key, "@A.ru", "@B.ru")
        assert decrypted == plaintext

    def test_unicode_message(self):
        """Сообщение с Unicode символами."""
        session_key = generate_session_key()
        plaintext = "Привет, мир! 🌍"
        encrypted = encrypt_directional(plaintext, session_key, "@A.ru", "@B.ru")
        decrypted = decrypt_directional(encrypted, session_key, "@A.ru", "@B.ru")
        assert decrypted == plaintext


class TestDirectionalWithPhrase:
    """Тесты для направленного шифрования с дополнительной фразой."""

    def test_encrypt_decrypt_with_phrase(self):
        """Шифрование и расшифровка с дополнительной фразой."""
        session_key = generate_session_key()
        phrase = "зеленый дом"
        plaintext = "Secret message with phrase"

        encrypted = encrypt_directional(
            plaintext, session_key, "@ALICE.ru", "@BOB.ru", phrase=phrase
        )
        decrypted = decrypt_directional(
            encrypted, session_key, "@ALICE.ru", "@BOB.ru", phrase=phrase
        )

        assert decrypted == plaintext

    def test_wrong_phrase_fails(self):
        """Расшифровка с неверной фразой должна возвращать None."""
        session_key = generate_session_key()
        phrase_correct = "зеленый дом"
        phrase_wrong = "красный дом"
        plaintext = "Secret message"

        encrypted = encrypt_directional(
            plaintext, session_key, "@ALICE.ru", "@BOB.ru", phrase=phrase_correct
        )
        decrypted = decrypt_directional(
            encrypted, session_key, "@ALICE.ru", "@BOB.ru", phrase=phrase_wrong
        )

        assert decrypted is None

    def test_encrypt_with_phrase_decrypt_without_phrase_fails(self):
        """Шифрование с фразой, расшифровка без фразы → None."""
        session_key = generate_session_key()
        phrase = "зеленый дом"
        plaintext = "Secret message"

        encrypted = encrypt_directional(
            plaintext, session_key, "@ALICE.ru", "@BOB.ru", phrase=phrase
        )
        decrypted = decrypt_directional(
            encrypted, session_key, "@ALICE.ru", "@BOB.ru", phrase=None
        )

        assert decrypted is None

    def test_encrypt_without_phrase_decrypt_with_phrase_fails(self):
        """Шифрование без фразы, расшифровка с фразой → None."""
        session_key = generate_session_key()
        phrase = "зеленый дом"
        plaintext = "Secret message"

        encrypted = encrypt_directional(
            plaintext, session_key, "@ALICE.ru", "@BOB.ru", phrase=None
        )
        decrypted = decrypt_directional(
            encrypted, session_key, "@ALICE.ru", "@BOB.ru", phrase=phrase
        )

        assert decrypted is None


class TestDirectionalIntegration:
    """Интеграционные тесты."""

    def test_full_duplex_communication(self):
        """
        Полнодуплексная коммуникация: Алиса → Боб и Боб → Алиса.
        Каждое направление использует свой ключ.
        """
        session_key = generate_session_key()
        alice = "@ALICE.ru"
        bob = "@BOB.ru"

        # Алиса → Боб
        msg_ab = "Hello from Alice"
        encrypted_ab = encrypt_directional(msg_ab, session_key, alice, bob)
        decrypted_ab = decrypt_directional(encrypted_ab, session_key, alice, bob)
        assert decrypted_ab == msg_ab

        # Боб → Алиса
        msg_ba = "Hello from Bob"
        encrypted_ba = encrypt_directional(msg_ba, session_key, bob, alice)
        decrypted_ba = decrypt_directional(encrypted_ba, session_key, bob, alice)
        assert decrypted_ba == msg_ba

        # Проверяем, что ключи разные
        key_ab = get_directional_key(session_key, alice, bob)
        key_ba = get_directional_key(session_key, bob, alice)
        assert key_ab != key_ba

    def test_cannot_decrypt_with_opposite_direction(self):
        """
        Сообщение от Алисы к Бобу нельзя расшифровать ключом Боб → Алиса.
        """
        session_key = generate_session_key()
        alice = "@ALICE.ru"
        bob = "@BOB.ru"
        plaintext = "Secret"

        encrypted = encrypt_directional(plaintext, session_key, alice, bob)

        # Пытаемся расшифровать с противоположным направлением
        decrypted = decrypt_directional(encrypted, session_key, bob, alice)
        assert decrypted is None
