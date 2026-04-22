# tests/unit/test_crypto_hash.py
"""
Модуль тестов для C0.4_crypto_hash.

Проверяет корректность хеширования и верификации паролей с использованием bcrypt.
"""

import pytest

from src.common.crypto.hash import hash_password, verify_password


class TestHashPassword:
    """Тесты для функции hash_password()."""

    def test_returns_60_bytes(self):
        """Критерий 1: hash_password() возвращает 60-байтовый хеш."""
        password_hash = hash_password("secure_password_123")
        assert len(password_hash) == 60
        assert isinstance(password_hash, bytes)

    def test_hash_format(self):
        """Дополнительная проверка: формат bcrypt хеша."""
        password_hash = hash_password("test_password")
        # Формат: $2b$12$[22 символа соли][31 символ хеша]
        assert password_hash.startswith(b'$2b$12$')
        assert len(password_hash) == 60

    def test_different_hashes_for_same_password(self):
        """Критерий 2: одинаковые пароли дают разные хеши (разная соль)."""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2

    def test_hash_with_strong_password(self):
        """Дополнительная проверка: сложный пароль."""
        password = "MyStr0ng!P@ssw0rd#2024"
        password_hash = hash_password(password)
        assert len(password_hash) == 60

    def test_hash_with_simple_password(self):
        """Дополнительная проверка: простой пароль."""
        password = "12345678"
        password_hash = hash_password(password)
        assert len(password_hash) == 60

    def test_hash_with_unicode_password(self):
        """Дополнительная проверка: пароль с Unicode символами."""
        password = "пароль_с_русскими_символами"
        password_hash = hash_password(password)
        assert len(password_hash) == 60

    def test_hash_with_special_characters(self):
        """Дополнительная проверка: пароль со спецсимволами."""
        password = "!@#$%^&*()_+{}[]|\\:;\"'<>,.?/~`"
        password_hash = hash_password(password)
        assert len(password_hash) == 60

    def test_hash_with_very_long_password(self):
        """Дополнительная проверка: очень длинный пароль (обрезаем до 72 байт)."""
        # bcrypt имеет лимит 72 байта
        password = "x" * 100
        # Обрезаем до 72 байт для bcrypt
        password = password[:72]
        password_hash = hash_password(password)
        assert len(password_hash) == 60

    def test_hash_with_empty_password_raises_error(self):
        """Критерий 6: hash_password() с пустым паролем вызывает ValueError."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            hash_password("")

    def test_hash_with_whitespace_only(self):
        """Дополнительная проверка: пароль из пробелов."""
        password = "   "
        password_hash = hash_password(password)
        assert len(password_hash) == 60
        assert verify_password(password, password_hash) is True


class TestVerifyPassword:
    """Тесты для функции verify_password()."""

    @pytest.fixture
    def password(self):
        """Фикстура: тестовый пароль."""
        return "secure_password_123"

    @pytest.fixture
    def password_hash(self, password):
        """Фикстура: хеш тестового пароля."""
        return hash_password(password)

    def test_verify_correct_password(self, password, password_hash):
        """Критерий 3: verify_password() возвращает True для корректного пароля."""
        assert verify_password(password, password_hash) is True

    def test_verify_incorrect_password(self, password, password_hash):
        """Критерий 4: verify_password() возвращает False для неверного пароля."""
        wrong_password = "wrong_password"
        assert verify_password(wrong_password, password_hash) is False

    def test_verify_empty_password(self, password_hash):
        """Критерий 5: verify_password() для пустого пароля вызывает ValueError."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            verify_password("", password_hash)

    def test_verify_with_none_hash(self, password):
        """Дополнительная проверка: None вместо хеша."""
        with pytest.raises(ValueError, match="Invalid password hash"):
            verify_password(password, None)  # type: ignore

    def test_verify_with_empty_hash(self, password):
        """Дополнительная проверка: пустой хеш."""
        with pytest.raises(ValueError, match="Invalid password hash"):
            verify_password(password, b"")

    def test_verify_with_invalid_hash_format(self, password):
        """Критерий 8: verify_password() с некорректным хешем вызывает ValueError."""
        invalid_hash = b"not_a_valid_bcrypt_hash"
        with pytest.raises(ValueError, match="Invalid password hash"):
            verify_password(password, invalid_hash)

    def test_verify_with_wrong_bcrypt_version(self, password):
        """Дополнительная проверка: хеш с другой версией bcrypt."""
        import bcrypt
        salt = bcrypt.gensalt(rounds=12, prefix=b'2a')
        wrong_version_hash = bcrypt.hashpw(password.encode('utf-8'), salt)

        assert verify_password(password, wrong_version_hash) is True

    def test_verify_with_different_rounds(self, password):
        """Дополнительная проверка: хеш с другим количеством раундов."""
        import bcrypt
        salt = bcrypt.gensalt(rounds=10)
        different_rounds_hash = bcrypt.hashpw(password.encode('utf-8'), salt)

        assert verify_password(password, different_rounds_hash) is True

    def test_verify_with_tampered_hash(self, password):
        """Дополнительная проверка: поврежденный хеш."""
        original_hash = hash_password(password)
        # Изменяем последний байт
        tampered = original_hash[:-1] + bytes([original_hash[-1] ^ 0x01])

        result = verify_password(password, tampered)
        assert result is False

    def test_verify_with_unicode_password(self):
        """Дополнительная проверка: Unicode пароль."""
        password = "пароль_с_русскими_символами"
        password_hash = hash_password(password)
        assert verify_password(password, password_hash) is True

        wrong_password = "неправильный_пароль"
        assert verify_password(wrong_password, password_hash) is False


class TestIntegration:
    """Интеграционные тесты."""

    def test_multiple_passwords(self):
        """Проверка работы с несколькими паролями."""
        passwords = [
            "pass1",
            "pass2",
            "very_strong_password_123!@#",
            "пароль_на_русском",
            "1234567890",
            "a" * 70,  # Максимум 72 байта, используем 70
        ]

        hashes = []
        for pwd in passwords:
            pwd_hash = hash_password(pwd)
            hashes.append(pwd_hash)
            assert verify_password(pwd, pwd_hash) is True

        # Проверяем, что все хеши уникальны
        assert len(set(hashes)) == len(passwords)

        # Проверяем перекрестную верификацию
        for i, pwd in enumerate(passwords):
            for j, other_hash in enumerate(hashes):
                if i == j:
                    assert verify_password(pwd, other_hash) is True
                else:
                    assert verify_password(pwd, other_hash) is False

    def test_hash_and_verify_cycle(self):
        """Проверка полного цикла хеширования и верификации."""
        for _ in range(10):
            password = f"test_password_{_}"
            pwd_hash = hash_password(password)
            assert verify_password(password, pwd_hash) is True

    def test_same_password_different_hashes_all_verify(self):
        """Проверка, что все хеши одного пароля верифицируются."""
        password = "common_password"
        hashes = [hash_password(password) for _ in range(5)]

        for pwd_hash in hashes:
            assert verify_password(password, pwd_hash) is True


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_password_with_newline(self):
        """Пароль с символом новой строки."""
        password = "password\nwith_newline"
        pwd_hash = hash_password(password)
        assert verify_password(password, pwd_hash) is True

    def test_password_with_tab(self):
        """Пароль с символом табуляции."""
        password = "password\twith_tab"
        pwd_hash = hash_password(password)
        assert verify_password(password, pwd_hash) is True

    def test_password_with_null_byte(self):
        """Пароль с нулевым байтом."""
        password = "password\x00with_null"
        pwd_hash = hash_password(password)
        assert verify_password(password, pwd_hash) is True

    def test_very_short_password(self):
        """Минимальный пароль (1 символ)."""
        password = "a"
        pwd_hash = hash_password(password)
        assert len(pwd_hash) == 60
        assert verify_password(password, pwd_hash) is True

    def test_verify_with_bytes_hash(self):
        """Проверка, что хеш может быть bytes."""
        password = "test"
        pwd_hash = hash_password(password)
        assert isinstance(pwd_hash, bytes)
        assert verify_password(password, pwd_hash) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
