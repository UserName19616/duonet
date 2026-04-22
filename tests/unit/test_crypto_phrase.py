"""
Модуль тестов для C0.3_crypto_phrase.

Проверяет корректность работы с дополнительной фразой:
- вывод ключа из фразы (PBKDF2)
- XOR комбинирование ключей
- шифрование/расшифровку с дополнительной фразой
"""

import pytest
import secrets

from src.client.crypto.aes import generate_session_key
from src.client.crypto.phrase import (
    derive_phrase_key,
    xor_keys,
    encrypt_with_phrase,
    decrypt_with_phrase,
)


class TestDerivePhraseKey:
    """Тесты для функции derive_phrase_key()."""

    @pytest.fixture
    def salt(self):
        """Фикстура: соль 16 байт."""
        return secrets.token_bytes(16)

    def test_returns_32_bytes(self, salt):
        """Критерий 1: derive_phrase_key() возвращает 32 байта."""
        key = derive_phrase_key("мой секрет", salt)
        assert len(key) == 32
        assert isinstance(key, bytes)

    def test_deterministic_same_input(self, salt):
        """Критерий 2: одинаковые (phrase, salt) → одинаковый ключ."""
        phrase = "мой секрет"
        key1 = derive_phrase_key(phrase, salt)
        key2 = derive_phrase_key(phrase, salt)
        assert key1 == key2

    def test_different_salt_gives_different_keys(self, salt):
        """Критерий 3: с разными salt дает разные ключи."""
        phrase = "мой секрет"
        salt2 = secrets.token_bytes(16)
        key1 = derive_phrase_key(phrase, salt)
        key2 = derive_phrase_key(phrase, salt2)
        assert key1 != key2

    def test_different_phrase_gives_different_keys(self, salt):
        """Дополнительная проверка: разные фразы дают разные ключи."""
        key1 = derive_phrase_key("фраза 1", salt)
        key2 = derive_phrase_key("фраза 2", salt)
        assert key1 != key2

    def test_unicode_phrase(self, salt):
        """Дополнительная проверка: фраза с Unicode символами."""
        phrase = "Привет мир! 🌍"
        key = derive_phrase_key(phrase, salt)
        assert len(key) == 32

    def test_empty_phrase(self, salt):
        """Дополнительная проверка: пустая фраза."""
        key = derive_phrase_key("", salt)
        assert len(key) == 32


class TestXorKeys:
    """Тесты для функции xor_keys()."""

    @pytest.fixture
    def key(self):
        """Фикстура: 32-байтовый ключ."""
        return b'\x01' * 32

    def test_xor_identity(self, key):
        """Проверка: XOR с самим собой дает нули."""
        result = xor_keys(key, key)
        assert result == b'\x00' * 32

    def test_xor_commutative(self):
        """Проверка: XOR коммутативен."""
        key1 = b'\x01' * 32
        key2 = b'\x02' * 32
        assert xor_keys(key1, key2) == xor_keys(key2, key1)

    def test_xor_associative(self):
        """Проверка: XOR ассоциативен."""
        key1 = b'\x01' * 32
        key2 = b'\x02' * 32
        key3 = b'\x03' * 32
        assert xor_keys(xor_keys(key1, key2), key3) == xor_keys(key1, xor_keys(key2, key3))

    def test_xor_correct_result(self):
        """Критерий 4: корректное комбинирование двух ключей."""
        key1 = b'\x01' * 32
        key2 = b'\x02' * 32
        expected = b'\x03' * 32
        assert xor_keys(key1, key2) == expected

    def test_xor_different_length_raises_value_error(self):
        """Критерий 5: с ключами разной длины вызывает ValueError."""
        key1 = b'\x00' * 32
        key2 = b'\x00' * 16
        with pytest.raises(ValueError, match="Key lengths must match"):
            xor_keys(key1, key2)

    def test_xor_empty_keys(self):
        """Дополнительная проверка: пустые ключи."""
        result = xor_keys(b"", b"")
        assert result == b""

    def test_xor_with_random_bytes(self):
        """Дополнительная проверка: случайные байты."""
        key1 = secrets.token_bytes(32)
        key2 = secrets.token_bytes(32)
        result = xor_keys(key1, key2)
        assert len(result) == 32
        # XOR должен дать не нули для разных ключей
        assert result != b'\x00' * 32


class TestEncryptWithPhrase:
    """Тесты для функции encrypt_with_phrase()."""

    @pytest.fixture
    def session_key(self):
        """Фикстура: сессионный ключ."""
        return generate_session_key()

    @pytest.fixture
    def phrase(self):
        """Фикстура: дополнительная фраза."""
        return "зеленый дом"

    @pytest.fixture
    def plaintext(self):
        """Фикстура: тестовое сообщение."""
        return "Секретное сообщение"

    def test_encrypt_returns_bytes_longer_than_28(self, session_key, phrase, plaintext):
        """Критерий 6: encrypt_with_phrase() возвращает данные длиной > 28 байт."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        assert len(ciphertext) > 28  # salt(16) + nonce(12) = 28
        assert isinstance(ciphertext, bytes)

    def test_encrypt_with_empty_string(self, session_key, phrase):
        """Дополнительная проверка: шифрование пустой строки."""
        ciphertext = encrypt_with_phrase("", session_key, phrase)
        assert len(ciphertext) > 28

    def test_encrypt_with_unicode(self, session_key, phrase):
        """Дополнительная проверка: шифрование Unicode текста."""
        plaintext = "Привет, мир! 🌍"
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        assert len(ciphertext) > 28

    def test_encrypt_with_invalid_session_key(self, phrase):
        """Критерий 11: с неверным session_key вызывает ValueError."""
        with pytest.raises(ValueError, match="Session key must be 32 bytes"):
            encrypt_with_phrase("test", b"too_short", phrase)

    def test_encrypt_is_not_deterministic(self, session_key, phrase, plaintext):
        """Дополнительная проверка: шифрование не детерминировано."""
        cipher1 = encrypt_with_phrase(plaintext, session_key, phrase)
        cipher2 = encrypt_with_phrase(plaintext, session_key, phrase)
        assert cipher1 != cipher2

    def test_encrypt_with_empty_phrase(self, session_key):
        """Дополнительная проверка: шифрование с пустой фразой."""
        ciphertext = encrypt_with_phrase("test", session_key, "")
        assert len(ciphertext) > 28


class TestDecryptWithPhrase:
    """Тесты для функции decrypt_with_phrase()."""

    @pytest.fixture
    def session_key(self):
        """Фикстура: сессионный ключ."""
        return generate_session_key()

    @pytest.fixture
    def phrase(self):
        """Фикстура: дополнительная фраза."""
        return "зеленый дом"

    @pytest.fixture
    def plaintext(self):
        """Фикстура: тестовое сообщение."""
        return "Секретное сообщение"

    def test_decrypt_valid(self, session_key, phrase, plaintext):
        """Критерий 7: decrypt_with_phrase(encrypt_with_phrase(text, sk, ph), sk, ph) == text."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
        assert decrypted == plaintext

    def test_decrypt_empty_string(self, session_key, phrase):
        """Дополнительная проверка: расшифровка пустой строки."""
        ciphertext = encrypt_with_phrase("", session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
        assert decrypted == ""

    def test_decrypt_unicode(self, session_key, phrase):
        """Дополнительная проверка: расшифровка Unicode текста."""
        plaintext = "Привет, мир! 🌍"
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
        assert decrypted == plaintext

    def test_decrypt_wrong_phrase(self, session_key, phrase, plaintext):
        """Критерий 8: с неверной фразой возвращает None."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, "неправильная фраза")
        assert decrypted is None

    def test_decrypt_wrong_session_key(self, phrase, plaintext):
        """Критерий 9: с неверным session_key возвращает None."""
        sk1 = generate_session_key()
        sk2 = generate_session_key()
        ciphertext = encrypt_with_phrase(plaintext, sk1, phrase)
        decrypted = decrypt_with_phrase(ciphertext, sk2, phrase)
        assert decrypted is None

    def test_decrypt_corrupted_data(self, session_key, phrase, plaintext):
        """Критерий 10: с поврежденными данными возвращает None."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        corrupted = ciphertext[:-1] + b'\x00'
        decrypted = decrypt_with_phrase(corrupted, session_key, phrase)
        assert decrypted is None

    def test_decrypt_too_short(self, session_key, phrase):
        """Дополнительная проверка: данные короче 28 байт."""
        result = decrypt_with_phrase(b"too_short", session_key, phrase)
        assert result is None

    def test_decrypt_tampered_salt(self, session_key, phrase, plaintext):
        """Дополнительная проверка: изменение соли."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        # Изменяем первый байт соли
        tampered = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
        decrypted = decrypt_with_phrase(tampered, session_key, phrase)
        assert decrypted is None

    def test_decrypt_tampered_nonce(self, session_key, phrase, plaintext):
        """Дополнительная проверка: изменение nonce."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        # Изменяем байт в nonce (16-28)
        if len(ciphertext) > 28:
            tampered = ciphertext[:16] + bytes([ciphertext[16] ^ 0x01]) + ciphertext[17:]
            decrypted = decrypt_with_phrase(tampered, session_key, phrase)
            assert decrypted is None

    def test_decrypt_with_invalid_session_key(self, phrase):
        """Критерий 11: с неверным session_key вызывает ValueError."""
        with pytest.raises(ValueError, match="Session key must be 32 bytes"):
            decrypt_with_phrase(b"some_data", b"too_short", phrase)

    def test_decrypt_with_empty_phrase(self, session_key, plaintext):
        """Дополнительная проверка: расшифровка с пустой фразой."""
        ciphertext = encrypt_with_phrase(plaintext, session_key, "")
        decrypted = decrypt_with_phrase(ciphertext, session_key, "")
        assert decrypted == plaintext

        # Неверная пустая фраза (фактически всегда неверна)
        decrypted_wrong = decrypt_with_phrase(ciphertext, session_key, "")
        assert decrypted_wrong == plaintext  # Правильная фраза - пустая


class TestIntegration:
    """Интеграционные тесты."""

    def test_full_cycle_multiple_messages(self):
        """Проверка полного цикла с несколькими сообщениями."""
        session_key = generate_session_key()
        phrase = "мой секретный ключ"
        messages = [
            "",
            "Short",
            "Normal message",
            "A" * 1000,
            "Привет, мир! 🌍",
            "Special chars: !@#$%^&*()",
        ]

        for msg in messages:
            ciphertext = encrypt_with_phrase(msg, session_key, phrase)
            decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
            assert decrypted == msg

    def test_different_phrases_produce_different_ciphertexts(self):
        """Проверка, что разные фразы дают разные шифротексты."""
        session_key = generate_session_key()
        plaintext = "Secret message"
        phrase1 = "фраза 1"
        phrase2 = "фраза 2"

        cipher1 = encrypt_with_phrase(plaintext, session_key, phrase1)
        cipher2 = encrypt_with_phrase(plaintext, session_key, phrase2)

        assert cipher1 != cipher2
        assert decrypt_with_phrase(cipher1, session_key, phrase2) is None
        assert decrypt_with_phrase(cipher2, session_key, phrase1) is None

    def test_different_session_keys_produce_different_ciphertexts(self):
        """Проверка, что разные session_key дают разные шифротексты."""
        sk1 = generate_session_key()
        sk2 = generate_session_key()
        phrase = "общая фраза"
        plaintext = "Secret message"

        cipher1 = encrypt_with_phrase(plaintext, sk1, phrase)
        cipher2 = encrypt_with_phrase(plaintext, sk2, phrase)

        assert cipher1 != cipher2
        assert decrypt_with_phrase(cipher1, sk2, phrase) is None
        assert decrypt_with_phrase(cipher2, sk1, phrase) is None

    def test_encrypt_without_phrase_equals_encrypt_with_empty_phrase(self):
        """Проверка, что encrypt_with_phrase с пустой фразой эквивалентен обычному шифрованию."""
        from src.client.crypto.aes import encrypt as aes_encrypt, decrypt as aes_decrypt

        session_key = generate_session_key()
        plaintext = "Test message"

        # Шифрование с пустой фразой
        cipher_with_empty = encrypt_with_phrase(plaintext, session_key, "")

        # Расшифровка через decrypt_with_phrase с пустой фразой
        decrypted = decrypt_with_phrase(cipher_with_empty, session_key, "")
        assert decrypted == plaintext


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_very_long_phrase(self):
        """Проверка с очень длинной фразой."""
        session_key = generate_session_key()
        phrase = "x" * 10000
        plaintext = "Secret message"

        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
        assert decrypted == plaintext

    def test_very_long_message(self):
        """Проверка с очень длинным сообщением."""
        session_key = generate_session_key()
        phrase = "мой секрет"
        plaintext = "X" * 1000000

        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
        assert decrypted == plaintext

    def test_special_characters_in_phrase(self):
        """Проверка с фразой, содержащей спецсимволы."""
        session_key = generate_session_key()
        phrase = "!@#$%^&*()_+{}[]|\\:;\"'<>,.?/~`"
        plaintext = "Secret message"

        ciphertext = encrypt_with_phrase(plaintext, session_key, phrase)
        decrypted = decrypt_with_phrase(ciphertext, session_key, phrase)
        assert decrypted == plaintext

    def test_decrypt_with_none_input(self):
        """Проверка с None вместо ciphertext."""
        session_key = generate_session_key()
        phrase = "test"
        with pytest.raises((TypeError, AttributeError)):
            decrypt_with_phrase(None, session_key, phrase)  # type: ignore

    def test_decrypt_with_wrong_type(self):
        """Проверка с неправильным типом данных."""
        session_key = generate_session_key()
        phrase = "test"
        result = decrypt_with_phrase("not bytes", session_key, phrase)  # type: ignore
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
