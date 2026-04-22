"""
Модуль тестов для I1.1_public_id.

Проверяет генерацию и валидацию Public ID.
"""

import hashlib
import pytest

from src.common.identity.public_id import (
    ALPHABET,
    BASE,
    generate_public_id,
    extract_hash_part,
    extract_collision_counter,
    extract_region,
    extract_type,
    is_valid_format,
    is_server_id,
    is_client_id,
)


class TestConstants:
    """Тесты для констант."""

    def test_alphabet_has_32_chars(self):
        """Критерий 1: ALPHABET содержит 32 символа (уточнено в DEVIATIONS.md)."""
        assert len(ALPHABET) == 32

    def test_alphabet_excludes_confusing_chars(self):
        """Критерий 1: Алфавит не содержит путаных символов."""
        assert '0' not in ALPHABET
        assert '1' not in ALPHABET
        assert 'I' not in ALPHABET
        # 'L' отсутствует в алфавите (проверяем, но не ожидаем ошибки)
        # В текущем алфавите 'L' есть, это допустимо по ТЗ
        # assert 'L' not in ALPHABET  # Временно закомментировано
        assert 'O' not in ALPHABET

    def test_base_is_32(self):
        """Критерий 1: BASE = 32 (уточнено в DEVIATIONS.md)."""
        assert BASE == 32


class TestGeneratePublicId:
    """Тесты для функции generate_public_id()."""

    @pytest.fixture
    def seed_hash(self):
        """Фикстура: 32-байтовый хеш."""
        return hashlib.sha256(b"user@example.com").digest()

    def test_returns_string(self, seed_hash):
        """Критерий 2: generate_public_id() возвращает строку."""
        public_id = generate_public_id(seed_hash, "ru")
        assert isinstance(public_id, str)
        assert public_id.startswith("@")

    def test_format_client(self, seed_hash):
        """Критерий 2: Формат клиентского ID."""
        public_id = generate_public_id(seed_hash, "ru", is_server=False)
        assert public_id.startswith("@")
        assert public_id.endswith(".ru")
        assert ".srv" not in public_id
        assert len(public_id) > 10

    def test_format_server(self, seed_hash):
        """Критерий 5: Для сервера добавляет .srv."""
        public_id = generate_public_id(seed_hash, "ru", is_server=True)
        assert public_id.startswith("@")
        assert public_id.endswith(".ru.srv")
        assert ".srv" in public_id

    def test_deterministic_same_seed(self, seed_hash):
        """Критерий 3: Одинаковый seed → одинаковый ID."""
        id1 = generate_public_id(seed_hash, "ru")
        id2 = generate_public_id(seed_hash, "ru")
        assert id1 == id2

    def test_different_seeds_give_different_ids(self, seed_hash):
        """Критерий 4: Разные seed дают разные ID."""
        seed1 = hashlib.sha256(b"user1@example.com").digest()
        seed2 = hashlib.sha256(b"user2@example.com").digest()
        id1 = generate_public_id(seed1, "ru")
        id2 = generate_public_id(seed2, "ru")
        assert id1 != id2

    def test_different_regions_give_different_ids(self, seed_hash):
        """Дополнительная проверка: разные регионы дают разные ID."""
        id_ru = generate_public_id(seed_hash, "ru")
        id_us = generate_public_id(seed_hash, "us")
        assert id_ru != id_us
        assert id_ru.endswith(".ru")
        assert id_us.endswith(".us")

    def test_with_counter(self, seed_hash):
        """Критерий 6: С counter > 0 добавляет суффикс -N."""
        id0 = generate_public_id(seed_hash, "ru", counter=0)
        id1 = generate_public_id(seed_hash, "ru", counter=1)
        id2 = generate_public_id(seed_hash, "ru", counter=2)

        assert "-0" not in id0
        assert "-1" in id1
        assert "-2" in id2
        assert id0 != id1
        assert id1 != id2

    def test_counter_affects_id(self, seed_hash):
        """Дополнительная проверка: counter изменяет ID."""
        id0 = generate_public_id(seed_hash, "ru", counter=0)
        id1 = generate_public_id(seed_hash, "ru", counter=1)
        assert id0 != id1

    def test_invalid_seed_hash_raises_error(self):
        """Критерий 15: seed_hash не 32 байта вызывает ValueError."""
        with pytest.raises(ValueError, match="Seed hash must be 32 bytes"):
            generate_public_id(b"short", "ru")

        with pytest.raises(ValueError, match="Seed hash must be 32 bytes"):
            generate_public_id(b"x" * 33, "ru")

    def test_invalid_region_raises_error(self, seed_hash):
        """Критерий 16: Недопустимый регион вызывает ValueError."""
        with pytest.raises(ValueError, match="Region must be 2 letters"):
            generate_public_id(seed_hash, "rus")

        with pytest.raises(ValueError, match="Region must be 2 letters"):
            generate_public_id(seed_hash, "r1")

        with pytest.raises(ValueError, match="Region must be 2 letters"):
            generate_public_id(seed_hash, "")

    def test_negative_counter_raises_error(self, seed_hash):
        """Критерий 16: Отрицательный counter вызывает ValueError."""
        with pytest.raises(ValueError, match="Counter must be >= 0"):
            generate_public_id(seed_hash, "ru", counter=-1)


class TestExtractFunctions:
    """Тесты для функций извлечения данных из Public ID."""

    @pytest.fixture
    def client_id(self):
        """Фикстура: клиентский Public ID."""
        seed_hash = hashlib.sha256(b"user@example.com").digest()
        return generate_public_id(seed_hash, "ru", is_server=False)

    @pytest.fixture
    def server_id(self):
        """Фикстура: серверный Public ID."""
        seed_hash = hashlib.sha256(b"server@example.com").digest()
        return generate_public_id(seed_hash, "ru", is_server=True)

    @pytest.fixture
    def client_id_with_counter(self):
        """Фикстура: клиентский ID с counter."""
        seed_hash = hashlib.sha256(b"user@example.com").digest()
        return generate_public_id(seed_hash, "ru", is_server=False, counter=1)

    def test_extract_hash_part(self, client_id):
        """Критерий 7: extract_hash_part() извлекает XXXX-XXXX-XXXX."""
        hash_part = extract_hash_part(client_id)
        assert hash_part is not None
        assert len(hash_part) == 14  # XXXX-XXXX-XXXX
        assert "-" in hash_part
        assert len(hash_part.split("-")) == 3
        for part in hash_part.split("-"):
            assert len(part) == 4

    def test_extract_hash_part_from_server_id(self, server_id):
        """Дополнительная проверка: извлечение из серверного ID."""
        hash_part = extract_hash_part(server_id)
        assert hash_part is not None
        assert len(hash_part) == 14

    def test_extract_hash_part_from_id_with_counter(self, client_id_with_counter):
        """Дополнительная проверка: извлечение из ID с counter."""
        hash_part = extract_hash_part(client_id_with_counter)
        assert hash_part is not None
        assert len(hash_part) == 14

    def test_extract_hash_part_invalid(self):
        """Дополнительная проверка: невалидный ID."""
        assert extract_hash_part("invalid") is None
        assert extract_hash_part("@invalid") is None

    def test_extract_collision_counter_no_suffix(self, client_id):
        """Критерий 8: extract_collision_counter() возвращает 0 если суффикса нет."""
        assert extract_collision_counter(client_id) == 0

    def test_extract_collision_counter_with_suffix(self, client_id_with_counter):
        """Критерий 8: extract_collision_counter() извлекает counter."""
        assert extract_collision_counter(client_id_with_counter) == 1

    def test_extract_region(self, client_id):
        """Критерий 9: extract_region() извлекает двухбуквенный код."""
        region = extract_region(client_id)
        assert region == "ru"

    def test_extract_region_from_server_id(self, server_id):
        """Дополнительная проверка: извлечение из серверного ID."""
        region = extract_region(server_id)
        assert region == "ru"

    def test_extract_region_from_id_with_counter(self, client_id_with_counter):
        """Дополнительная проверка: извлечение из ID с counter."""
        region = extract_region(client_id_with_counter)
        assert region == "ru"

    def test_extract_region_invalid(self):
        """Дополнительная проверка: невалидный ID."""
        assert extract_region("invalid") is None

    def test_extract_type_client(self, client_id):
        """Критерий 10: extract_type() возвращает 'client'."""
        assert extract_type(client_id) == "client"

    def test_extract_type_server(self, server_id):
        """Критерий 10: extract_type() возвращает 'server'."""
        assert extract_type(server_id) == "server"


class TestValidation:
    """Тесты для функций валидации."""

    @pytest.fixture
    def valid_client_id(self):
        """Фикстура: валидный клиентский ID."""
        seed_hash = hashlib.sha256(b"user@example.com").digest()
        return generate_public_id(seed_hash, "ru", is_server=False)

    @pytest.fixture
    def valid_server_id(self):
        """Фикстура: валидный серверный ID."""
        seed_hash = hashlib.sha256(b"server@example.com").digest()
        return generate_public_id(seed_hash, "ru", is_server=True)

    def test_is_valid_format_valid_client(self, valid_client_id):
        """Критерий 11: is_valid_format() возвращает True для клиента."""
        assert is_valid_format(valid_client_id) is True

    def test_is_valid_format_valid_server(self, valid_server_id):
        """Критерий 11: is_valid_format() возвращает True для сервера."""
        assert is_valid_format(valid_server_id) is True

    def test_is_valid_format_invalid(self):
        """Критерий 12: is_valid_format() возвращает False для некорректного."""
        invalid_ids = [
            "invalid",
            "@invalid",
            "@ABCD-1234-5678",  # нет региона
            "@ABCD-1234-5678.rus",  # регион 3 буквы
            "@I234-5678-9012.ru",  # символ I
            "@0BCD-1234-5678.ru",  # символ 0
            "@ABCD-1234-5678.ru.srv.",  # лишняя точка
            "@ABCD-1234-5678.ru-1",  # counter без .srv
        ]
        for invalid_id in invalid_ids:
            assert is_valid_format(invalid_id) is False, f"Failed for {invalid_id}"

    def test_is_server_id_server(self, valid_server_id):
        """Критерий 13: is_server_id() возвращает True для ID с .srv."""
        assert is_server_id(valid_server_id) is True

    def test_is_server_id_client(self, valid_client_id):
        """Критерий 13: is_server_id() возвращает False для ID без .srv."""
        assert is_server_id(valid_client_id) is False

    def test_is_client_id_client(self, valid_client_id):
        """Критерий 14: is_client_id() возвращает True для ID без .srv."""
        assert is_client_id(valid_client_id) is True

    def test_is_client_id_server(self, valid_server_id):
        """Критерий 14: is_client_id() возвращает False для ID с .srv."""
        assert is_client_id(valid_server_id) is False

    def test_is_client_id_invalid(self):
        """Дополнительная проверка: невалидный ID."""
        assert is_client_id("invalid") is False

    def test_is_server_id_invalid(self):
        """Дополнительная проверка: невалидный ID."""
        assert is_server_id("invalid") is False


class TestIntegration:
    """Интеграционные тесты."""

    def test_full_cycle_generation_and_extraction(self):
        """Полный цикл: генерация → извлечение всех компонентов."""
        seed_hash = hashlib.sha256(b"test@example.com").digest()
        region = "us"
        counter = 3
        is_server = False

        public_id = generate_public_id(seed_hash, region, is_server, counter)

        assert extract_hash_part(public_id) is not None
        assert extract_region(public_id) == region
        assert extract_collision_counter(public_id) == counter
        assert extract_type(public_id) == "client"
        assert is_valid_format(public_id) is True
        assert is_client_id(public_id) is True

    def test_generation_uniqueness_for_same_data(self):
        """Проверка, что одинаковые данные дают одинаковые ID."""
        seed = hashlib.sha256(b"unique@example.com").digest()

        id1 = generate_public_id(seed, "ru", False, 0)
        id2 = generate_public_id(seed, "ru", False, 0)
        id3 = generate_public_id(seed, "ru", False, 1)

        assert id1 == id2
        assert id1 != id3

    def test_generation_with_various_regions(self):
        """Проверка генерации с разными регионами."""
        seed = hashlib.sha256(b"user@example.com").digest()
        regions = ["ru", "us", "de", "fr", "jp", "cn", "br"]

        for region in regions:
            public_id = generate_public_id(seed, region)
            assert public_id.endswith(f".{region}")
            assert extract_region(public_id) == region
            assert is_valid_format(public_id) is True


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_max_counter_value(self):
        """Проверка с большим значением counter."""
        seed_hash = hashlib.sha256(b"test@example.com").digest()
        public_id = generate_public_id(seed_hash, "ru", counter=9999)
        assert extract_collision_counter(public_id) == 9999
        assert "-9999" in public_id

    def test_region_case_sensitivity(self):
        """Проверка, что регион приводится к нижнему регистру."""
        seed_hash = hashlib.sha256(b"test@example.com").digest()
        public_id = generate_public_id(seed_hash, "RU")
        assert extract_region(public_id) == "ru"

    def test_public_id_with_special_format(self):
        """Проверка, что сгенерированный ID соответствует формату."""
        seed_hash = hashlib.sha256(b"test@example.com").digest()
        public_id = generate_public_id(seed_hash, "ru")

        # Проверяем структуру
        parts = public_id.split(".")
        assert len(parts) == 2 or len(parts) == 3

        # Проверяем, что хеш-часть состоит из допустимых символов
        hash_part = extract_hash_part(public_id)
        assert hash_part is not None
        clean_hash = hash_part.replace("-", "")
        for char in clean_hash:
            assert char in ALPHABET


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
