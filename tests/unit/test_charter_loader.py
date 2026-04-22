# tests/unit/test_charter_loader.py
"""
Тесты для загрузчика Устава.
"""

import tempfile
from pathlib import Path

import pytest

from src.common.charter.loader import (
    CharterLoader,
    get_charter_text,
    get_charter_title,
    get_charter_version,
    get_charter_hash,
)


@pytest.fixture
def temp_templates_dir():
    """Создание временной директории с тестовыми файлами Устава."""
    with tempfile.TemporaryDirectory() as tmpdir:
        templates_dir = Path(tmpdir)
        # Создаём русский файл
        ru_file = templates_dir / "charter_ru.txt"
        ru_file.write_text("Тестовый Устав на русском языке\nСтатья 1", encoding="utf-8")
        # Создаём английский файл
        en_file = templates_dir / "charter_en.txt"
        en_file.write_text("Test Charter in English\nArticle 1", encoding="utf-8")
        yield templates_dir


class TestCharterLoader:
    """Тесты для CharterLoader."""

    def test_loader_init_default(self):
        """Инициализация с путём по умолчанию."""
        loader = CharterLoader()
        assert loader.templates_dir is not None

    def test_loader_init_custom(self, temp_templates_dir):
        """Инициализация с пользовательским путём."""
        loader = CharterLoader(temp_templates_dir)
        assert loader.templates_dir == temp_templates_dir

    def test_get_charter_text_ru(self, temp_templates_dir):
        """Получение текста Устава на русском."""
        loader = CharterLoader(temp_templates_dir)
        text = loader.get_charter_text("ru")
        assert "Тестовый Устав на русском языке" in text
        assert "Статья 1" in text

    def test_get_charter_text_en(self, temp_templates_dir):
        """Получение текста Устава на английском."""
        loader = CharterLoader(temp_templates_dir)
        text = loader.get_charter_text("en")
        assert "Test Charter in English" in text
        assert "Article 1" in text

    def test_get_charter_text_default_lang(self, temp_templates_dir):
        """Получение текста Устава с языком по умолчанию (ru)."""
        loader = CharterLoader(temp_templates_dir)
        text = loader.get_charter_text("fr")  # не существует
        # Должен вернуть русский (fallback)
        assert "Тестовый Устав на русском языке" in text

    def test_get_charter_text_file_not_found(self):
        """Ошибка при отсутствии файлов."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = CharterLoader(Path(tmpdir))
            with pytest.raises(FileNotFoundError):
                loader.get_charter_text("ru")

    def test_get_charter_title_ru(self):
        """Заголовок Устава на русском."""
        title = get_charter_title("ru")
        assert title == "Устав сообщества DuoNet"

    def test_get_charter_title_en(self):
        """Заголовок Устава на английском."""
        title = get_charter_title("en")
        assert title == "DuoNet Community Charter"

    def test_get_charter_title_default(self):
        """Заголовок Устава для неизвестного языка."""
        title = get_charter_title("fr")
        assert title == "Устав сообщества DuoNet"  # fallback

    def test_get_charter_version(self):
        """Получение версии Устава."""
        version = get_charter_version()
        assert version == "1.0"
        assert isinstance(version, str)

    def test_get_charter_hash(self, temp_templates_dir):
        """Получение хеша Устава."""
        loader = CharterLoader(temp_templates_dir)
        hash_ru = loader.get_charter_hash("ru")
        hash_en = loader.get_charter_hash("en")

        assert len(hash_ru) == 64  # SHA256 hex
        assert len(hash_en) == 64
        assert hash_ru != hash_en

    def test_charter_hash_consistency(self, temp_templates_dir):
        """Хеш одинакового текста должен быть одинаковым."""
        loader = CharterLoader(temp_templates_dir)
        hash1 = loader.get_charter_hash("ru")
        hash2 = loader.get_charter_hash("ru")
        assert hash1 == hash2


class TestCharterLoaderGlobal:
    """Тесты для глобальных функций."""

    def test_global_get_charter_text(self):
        """Глобальная функция get_charter_text."""
        text = get_charter_text("ru")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_global_get_charter_title(self):
        """Глобальная функция get_charter_title."""
        title = get_charter_title("ru")
        assert title == "Устав сообщества DuoNet"

    def test_global_get_charter_version(self):
        """Глобальная функция get_charter_version."""
        version = get_charter_version()
        assert version == "1.0"

    def test_global_get_charter_hash(self):
        """Глобальная функция get_charter_hash."""
        hash_val = get_charter_hash("ru")
        assert len(hash_val) == 64
