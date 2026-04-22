"""
Модуль тестов для C0.2_crypto_aes.

Проверяет корректность генерации ключей, шифрования и расшифровки сообщений.
"""

import pytest

from src.client.crypto.aes import generate_session_key, encrypt, decrypt


class TestGenerateSessionKey:
    """Тесты для функции generate_session_key()."""

    def test_returns_32_bytes(self):
        """Критерий 1: generate_session_key() возвращает 32 байта."""
        key = generate_session_key()
        assert len(key) == 32
        assert isinstance(key, bytes)

    def test_keys_are_unique(self):
        """Критерий 2: при каждом вызове дает разные ключи."""
        key1 = generate_session_key()
        key2 = generate_session_key()
        assert key1 != key2

    def test_key_is_random(self):
        """Дополнительная проверка: ключи не являются предсказуемыми."""
        keys = [generate_session_key() for _ in range(10)]
        # Проверяем, что все ключи уникальны
        assert len(set(keys)) == 10


class TestEncrypt:
    """Тесты для функции encrypt()."""

    @pytest.fixture
    def key(self):
        """Фикстура: валидный ключ."""
        return generate_session_key()

    def test_encrypt_returns_bytes_longer_than_12(self, key):
        """Критерий 3: encrypt() возвращает данные длиной > 12 байт."""
        plaintext = "Hello, World!"
        ciphertext = encrypt(plaintext, key)
        assert len(ciphertext) > 12
        assert isinstance(ciphertext, bytes)

    def test_encrypt_returns_nonce_plus_ciphertext(self, key):
        """Дополнительная проверка: структура выходных данных."""
        plaintext = "Test message"
        ciphertext = encrypt(plaintext, key)

        # Проверяем, что длина ciphertext = 12 (nonce) + зашифрованные данные
        # Зашифрованные данные включают tag (16 байт)
        # Минимальная длина для пустого сообщения: 12 + 16 = 28 байт
        assert len(ciphertext) >= 28

    def test_encrypt_with_empty_string(self, key):
        """Дополнительная проверка: шифрование пустой строки."""
        ciphertext = encrypt("", key)
        assert len(ciphertext) > 12
        assert isinstance(ciphertext, bytes)

    def test_encrypt_with_long_text(self, key):
        """Дополнительная проверка: шифрование длинного текста."""
        plaintext = "A" * 10000
        ciphertext = encrypt(plaintext, key)
        assert len(ciphertext) > len(plaintext)  # Добавляется nonce + tag

    def test_encrypt_with_unicode(self, key):
        """Дополнительная проверка: шифрование Unicode текста."""
        plaintext = "Привет, мир! 🌍"
        ciphertext = encrypt(plaintext, key)
        assert len(ciphertext) > 12

    def test_encrypt_with_invalid_key_length(self):
        """Критерий 8: encrypt() с ключом не 32 байт вызывает ValueError."""
        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            encrypt("test", b"too_short")

        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            encrypt("test", b"x" * 33)

    def test_encrypt_with_empty_key(self):
        """Дополнительная проверка: пустой ключ вызывает ошибку."""
        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            encrypt("test", b"")

    def test_encrypt_is_not_deterministic(self, key):
        """Критерий 10: шифрование не детерминировано (разный nonce)."""
        plaintext = "Same message"
        ciphertext1 = encrypt(plaintext, key)
        ciphertext2 = encrypt(plaintext, key)
        assert ciphertext1 != ciphertext2


class TestDecrypt:
    """Тесты для функции decrypt()."""

    @pytest.fixture
    def key(self):
        """Фикстура: валидный ключ."""
        return generate_session_key()

    @pytest.fixture
    def plaintext(self):
        """Фикстура: тестовое сообщение."""
        return "Hello, World!"

    def test_decrypt_valid(self, key, plaintext):
        """Критерий 4: decrypt(encrypt(text, key), key) == text."""
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_decrypt_empty_string(self, key):
        """Дополнительная проверка: расшифровка пустой строки."""
        ciphertext = encrypt("", key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == ""

    def test_decrypt_unicode(self, key):
        """Дополнительная проверка: расшифровка Unicode текста."""
        plaintext = "Привет, мир! 🌍"
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_decrypt_with_wrong_key(self, key):
        """Критерий 5: decrypt() с неверным ключом возвращает None."""
        plaintext = "Secret message"
        key2 = generate_session_key()

        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key2)

        assert decrypted is None

    def test_decrypt_with_corrupted_data(self, key):
        """Критерий 6: decrypt() с поврежденными данными возвращает None."""
        plaintext = "Secret message"
        ciphertext = encrypt(plaintext, key)

        # Изменяем последний байт
        corrupted = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0x01])
        decrypted = decrypt(corrupted, key)
        assert decrypted is None

    def test_decrypt_with_too_short_data(self, key):
        """Критерий 7: decrypt() с данными < 12 байт возвращает None."""
        result = decrypt(b"too_short", key)
        assert result is None

        result = decrypt(b"", key)
        assert result is None

        result = decrypt(b"\x00" * 11, key)
        assert result is None

    def test_decrypt_with_invalid_key_length(self):
        """Критерий 9: decrypt() с ключом не 32 байт вызывает ValueError."""
        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            decrypt(b"some_data", b"too_short")

        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            decrypt(b"some_data", b"x" * 33)

    def test_decrypt_with_tampered_nonce(self, key):
        """Дополнительная проверка: изменение nonce."""
        plaintext = "Secret message"
        ciphertext = encrypt(plaintext, key)

        # Изменяем nonce (первые 12 байт)
        tampered = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
        decrypted = decrypt(tampered, key)
        assert decrypted is None

    def test_decrypt_with_tampered_ciphertext(self, key):
        """Дополнительная проверка: изменение зашифрованных данных."""
        plaintext = "Secret message"
        ciphertext = encrypt(plaintext, key)

        # Изменяем данные после nonce
        if len(ciphertext) > 13:
            tampered = ciphertext[:12] + bytes([ciphertext[12] ^ 0x01]) + ciphertext[13:]
            decrypted = decrypt(tampered, key)
            assert decrypted is None


class TestIntegration:
    """Интеграционные тесты для проверки взаимодействия функций."""

    def test_full_cycle_multiple_messages(self):
        """Проверка полного цикла с несколькими сообщениями."""
        key = generate_session_key()
        messages = [
            "",
            "Short",
            "Normal message with spaces",
            "A" * 1000,
            "Привет, мир! 🌍",
            "Special chars: !@#$%^&*()",
        ]

        for msg in messages:
            ciphertext = encrypt(msg, key)
            decrypted = decrypt(ciphertext, key)
            assert decrypted == msg

    def test_encrypt_decrypt_with_same_key(self):
        """Проверка, что один ключ работает для всех сообщений."""
        key = generate_session_key()
        msg1 = "First message"
        msg2 = "Second message"

        cipher1 = encrypt(msg1, key)
        cipher2 = encrypt(msg2, key)

        assert decrypt(cipher1, key) == msg1
        assert decrypt(cipher2, key) == msg2

    def test_different_keys_produce_different_ciphertexts(self):
        """Проверка, что разные ключи дают разные шифротексты."""
        key1 = generate_session_key()
        key2 = generate_session_key()
        plaintext = "Same message"

        cipher1 = encrypt(plaintext, key1)
        cipher2 = encrypt(plaintext, key2)

        assert cipher1 != cipher2
        assert decrypt(cipher1, key2) is None
        assert decrypt(cipher2, key1) is None


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_encrypt_with_very_long_text(self):
        """Проверка шифрования очень длинного текста."""
        key = generate_session_key()
        plaintext = "X" * 1000000  # 1 млн символов
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_with_binary_data_in_string(self):
        """Проверка шифрования строки с бинарными символами."""
        key = generate_session_key()
        # Строка с непечатаемыми символами
        plaintext = "".join(chr(i) for i in range(256))
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_decrypt_with_none_input(self):
        """Проверка, что None обрабатывается корректно."""
        key = generate_session_key()
        # Функция ожидает bytes, но проверим что будет
        with pytest.raises((TypeError, AttributeError)):
            decrypt(None, key)  # type: ignore

    def test_decrypt_with_wrong_type(self):
        """Проверка с неправильным типом данных."""
        key = generate_session_key()
        result = decrypt("not bytes", key)  # type: ignore
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
