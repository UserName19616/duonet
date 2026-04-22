"""
Модуль тестов для C0.1_crypto_keys.

Проверяет корректность генерации ключей, подписи, верификации и хеширования.
"""

import pytest

from src.common.crypto.keys import (
    generate_keypair,
    generate_keypair_from_seed,
    sign,
    verify,
    hash_sha256,
)


class TestGenerateKeypair:
    """Тесты для функции generate_keypair()."""

    def test_returns_bytes_tuple(self):
        """Критерий 1: generate_keypair() возвращает два значения типа bytes."""
        priv, pub = generate_keypair()
        assert isinstance(priv, bytes)
        assert isinstance(pub, bytes)

    def test_private_key_length(self):
        """Критерий 2: Приватный ключ имеет длину 32 байта."""
        priv, _ = generate_keypair()
        assert len(priv) == 32

    def test_public_key_length(self):
        """Критерий 3: Публичный ключ имеет длину 32 байта."""
        _, pub = generate_keypair()
        assert len(pub) == 32

    def test_keys_are_unique(self):
        """Критерий 4: Каждый вызов generate_keypair() генерирует разные ключи."""
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2

    def test_keys_are_not_empty(self):
        """Дополнительная проверка: ключи не пустые."""
        priv, pub = generate_keypair()
        assert priv != b''
        assert pub != b''


class TestGenerateKeypairFromSeed:
    """Тесты для функции generate_keypair_from_seed()."""

    def test_valid_seed_length(self):
        """Критерий 5, 6: Генерация ключей из валидного seed."""
        seed = b'\x00' * 32
        priv, pub = generate_keypair_from_seed(seed)
        assert len(priv) == 32
        assert len(pub) == 32

    def test_deterministic_same_seed(self):
        """Критерий 5: Для одного seed дает одинаковые ключи при каждом вызове."""
        seed = b'\x00' * 32
        priv1, pub1 = generate_keypair_from_seed(seed)
        priv2, pub2 = generate_keypair_from_seed(seed)
        assert priv1 == priv2
        assert pub1 == pub2

    def test_different_seeds_give_different_keys(self):
        """Критерий 6: С разными seed дает разные ключи."""
        seed1 = b'\x00' * 32
        seed2 = b'\x01' * 32
        priv1, pub1 = generate_keypair_from_seed(seed1)
        priv2, pub2 = generate_keypair_from_seed(seed2)
        assert priv1 != priv2
        assert pub1 != pub2

    def test_invalid_seed_length_raises_value_error(self):
        """Критерий (исключение): Неверная длина seed вызывает ValueError."""
        with pytest.raises(ValueError, match="Seed must be 32 bytes"):
            generate_keypair_from_seed(b'too_short')

        with pytest.raises(ValueError, match="Seed must be 32 bytes"):
            generate_keypair_from_seed(b'x' * 33)

    def test_seed_with_random_bytes(self):
        """Дополнительная проверка: работа с любыми случайными байтами."""
        seed = bytes([i % 256 for i in range(32)])
        priv, pub = generate_keypair_from_seed(seed)
        assert len(priv) == 32
        assert len(pub) == 32


class TestSignAndVerify:
    """Тесты для функций sign() и verify()."""

    @pytest.fixture
    def keypair(self):
        """Фикстура: создает тестовую ключевую пару."""
        return generate_keypair()

    @pytest.fixture
    def message(self):
        """Фикстура: тестовое сообщение."""
        return b"test message for signing"

    def test_signature_length(self, keypair, message):
        """Критерий 7: sign() возвращает подпись длиной 64 байта."""
        priv, _ = keypair
        signature = sign(priv, message)
        assert len(signature) == 64

    def test_verify_valid_signature(self, keypair, message):
        """Критерий 8: verify() возвращает True для корректной подписи."""
        priv, pub = keypair
        signature = sign(priv, message)
        assert verify(pub, signature, message) is True

    def test_verify_invalid_signature(self, keypair, message):
        """Критерий 9: verify() возвращает False для неверной подписи."""
        priv, pub = keypair
        # Подпись от другого сообщения
        signature = sign(priv, b"different message")
        assert verify(pub, signature, message) is False

    def test_verify_wrong_key(self, keypair, message):
        """Критерий 10: verify() возвращает False для подписи от другого ключа."""
        priv1, _ = generate_keypair()
        _, pub2 = generate_keypair()
        signature = sign(priv1, message)
        assert verify(pub2, signature, message) is False

    def test_verify_tampered_signature(self, keypair, message):
        """Дополнительная проверка: поврежденная подпись."""
        priv, pub = keypair
        signature = sign(priv, message)
        # Изменяем последний байт подписи
        tampered = signature[:-1] + bytes([signature[-1] ^ 0x01])
        assert verify(pub, tampered, message) is False

    def test_verify_tampered_message(self, keypair, message):
        """Дополнительная проверка: поврежденное сообщение."""
        priv, pub = keypair
        signature = sign(priv, message)
        tampered_message = message + b'tampered'
        assert verify(pub, signature, tampered_message) is False

    def test_sign_with_different_private_keys(self, message):
        """Дополнительная проверка: разные ключи дают разные подписи."""
        priv1, _ = generate_keypair()
        priv2, _ = generate_keypair()
        sig1 = sign(priv1, message)
        sig2 = sign(priv2, message)
        assert sig1 != sig2

    def test_sign_with_same_key_deterministic(self, keypair, message):
        """
        Дополнительная проверка: подпись для одного сообщения одним ключом
        всегда одинакова (Ed25519 детерминирована).
        """
        priv, _ = keypair
        sig1 = sign(priv, message)
        sig2 = sign(priv, message)
        assert sig1 == sig2

    def test_sign_with_empty_message(self, keypair):
        """Дополнительная проверка: подпись пустого сообщения."""
        priv, pub = keypair
        signature = sign(priv, b"")
        assert len(signature) == 64
        assert verify(pub, signature, b"") is True


class TestHashSha256:
    """Тесты для функции hash_sha256()."""

    def test_hash_length(self):
        """Критерий 11: hash_sha256() возвращает 32-байтовый хеш."""
        h = hash_sha256(b"hello")
        assert len(h) == 32

    def test_deterministic_same_input(self):
        """Критерий 12: одинаковые данные → одинаковый хеш."""
        data = b"hello world"
        h1 = hash_sha256(data)
        h2 = hash_sha256(data)
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        """Критерий 13: для разных данных дает разные хеши."""
        h1 = hash_sha256(b"hello")
        h2 = hash_sha256(b"world")
        assert h1 != h2

    def test_hash_empty_data(self):
        """Дополнительная проверка: хеш пустых данных."""
        h = hash_sha256(b"")
        assert len(h) == 32
        # SHA256 пустой строки известен
        expected = bytes.fromhex(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert h == expected

    def test_hash_large_data(self):
        """Дополнительная проверка: хеш больших данных."""
        large_data = b"x" * 1000000
        h = hash_sha256(large_data)
        assert len(h) == 32

    def test_hash_binary_data(self):
        """Дополнительная проверка: хеш бинарных данных."""
        binary_data = bytes([i % 256 for i in range(256)])
        h = hash_sha256(binary_data)
        assert len(h) == 32


class TestIntegration:
    """Интеграционные тесты для проверки взаимодействия функций."""

    def test_full_cycle(self):
        """
        Полный цикл: генерация ключей из seed → подпись → верификация.
        Проверяет детерминированность всей цепочки.
        """
        seed = b'\x42' * 32
        priv, pub = generate_keypair_from_seed(seed)
        message = b"Important message for the network"

        signature = sign(priv, message)
        assert verify(pub, signature, message) is True

        # Повторяем с теми же параметрами
        priv2, pub2 = generate_keypair_from_seed(seed)
        assert priv == priv2
        assert pub == pub2

        signature2 = sign(priv2, message)
        assert signature == signature2
        assert verify(pub2, signature2, message) is True

    def test_keypair_and_verify_consistency(self):
        """
        Проверка, что публичный ключ из пары действительно верифицирует
        подписи, сделанные приватным ключом из той же пары.
        """
        priv, pub = generate_keypair()
        test_messages = [
            b"",
            b"single word",
            b"A" * 1024,
            b"\x00\x01\x02\x03\x04\x05",
        ]

        for msg in test_messages:
            sig = sign(priv, msg)
            assert verify(pub, sig, msg) is True

    def test_cross_verification_fails(self):
        """
        Проверка, что ключи из разных пар не могут верифицировать
        подписи друг друга.
        """
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        message = b"cross verification test"

        sig_from_1 = sign(priv1, message)
        sig_from_2 = sign(priv2, message)

        assert verify(pub2, sig_from_1, message) is False
        assert verify(pub1, sig_from_2, message) is False


class TestEdgeCases:
    """Тесты граничных случаев."""

    @pytest.fixture
    def keypair(self):
        """Фикстура: создает тестовую ключевую пару."""
        return generate_keypair()

    def test_sign_with_all_zeros_key(self):
        """Проверка подписи ключом из нулевых байтов."""
        priv = b'\x00' * 32
        message = b"test"
        # PyNaCl должен принять любой 32-байтовый ключ
        signature = sign(priv, message)
        assert len(signature) == 64

    def test_sign_with_all_ones_key(self):
        """Проверка подписи ключом из единичных байтов."""
        priv = b'\xff' * 32
        message = b"test"
        signature = sign(priv, message)
        assert len(signature) == 64

    def test_verify_with_wrong_signature_length(self, keypair):
        """Проверка верификации с подписью неверной длины."""
        _, pub = keypair
        wrong_sig = b"too_short"
        assert verify(pub, wrong_sig, b"test") is False

    def test_verify_with_empty_signature(self, keypair):
        """Проверка верификации с пустой подписью."""
        _, pub = keypair
        assert verify(pub, b"", b"test") is False

    def test_hash_sha256_with_unicode_bytes(self):
        """Проверка хеширования UTF-8 строк."""
        text = "Привет, мир! 🌍"
        data = text.encode('utf-8')
        h = hash_sha256(data)
        assert len(h) == 32


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
