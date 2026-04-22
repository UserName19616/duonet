# src/charter/loader.py
"""
Загрузчик текста Устава сообщества DuoNet.
Обеспечивает единую точку доступа к тексту Устава для TUI и Web.
"""
import hashlib
from pathlib import Path
from typing import Optional

# Путь к директории с шаблонами Устава
CHARTER_TEMPLATES_DIR = Path(__file__).parent / "templates"
CHARTER_VERSION = "1.0"  # Текущая версия Устава


class CharterLoader:
    """Загрузчик текста Устава."""

    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or CHARTER_TEMPLATES_DIR

    def get_charter_text(self, lang: str = "ru") -> str:
        """Получение полного текста Устава."""
        lang = lang.lower()[:2]
        if lang not in ("ru", "en"):
            lang = "ru"

        charter_file = self.templates_dir / f"charter_{lang}.txt"

        if not charter_file.exists():
            charter_file = self.templates_dir / "charter_ru.txt"
            if not charter_file.exists():
                raise FileNotFoundError(f"Charter file not found: {charter_file}")

        with open(charter_file, "r", encoding="utf-8") as f:
            return f.read()

    def get_charter_title(self, lang: str = "ru") -> str:
        """Получение заголовка Устава."""
        titles = {
            "ru": "Устав сообщества DuoNet",
            "en": "DuoNet Community Charter",
        }
        return titles.get(lang[:2].lower(), titles["ru"])

    def get_charter_version(self) -> str:
        """Получение версии Устава."""
        return CHARTER_VERSION

    def get_charter_hash(self, lang: str = "ru") -> str:
        """Получение хеша текста Устава."""
        text = self.get_charter_text(lang)
        return hashlib.sha256(text.encode()).hexdigest()


# Глобальный экземпляр
_charter_loader = CharterLoader()


def get_charter_text(lang: str = "ru") -> str:
    return _charter_loader.get_charter_text(lang)


def get_charter_title(lang: str = "ru") -> str:
    return _charter_loader.get_charter_title(lang)


def get_charter_version() -> str:
    return _charter_loader.get_charter_version()


def get_charter_hash(lang: str = "ru") -> str:
    return _charter_loader.get_charter_hash(lang)
