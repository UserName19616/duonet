# tests/unit/test_charter_signer.py
"""
Тесты для подписания Устава.
"""

import tempfile
from pathlib import Path
import pytest

from src.common.charter.loader import CharterLoader, get_charter_text
from src.common.charter.signer import (
    init_charter_table,
    sign_charter,
    verify_charter_signature,
    check_charter_accepted,
    get_charter_signature,
)
from src.common.crypto.keys import generate_keypair, generate_keypair_from_seed
from src.common.identity.account import AccountManager
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage


def mock_geoip(ip):
    return "ru"


@pytest.fixture(scope="function")
def temp_charter_dir():
    """Создание временной директории с тестовым Уставом."""
    with tempfile.TemporaryDirectory() as tmpdir:
        templates_dir = Path(tmpdir)
        # Создаём тестовый Устав с явными отличиями
        ru_file = templates_dir / "charter_ru.txt"
        ru_file.write_text(
            "Тестовый Устав DuoNet\n"
            "Статья 1: Тест на русском языке\n"
            "Это уникальный русский текст для проверки подписи",
            encoding="utf-8"
        )
        en_file = templates_dir / "charter_en.txt"
        en_file.write_text(
            "Test DuoNet Charter\n"
            "Article 1: Test in English\n"
            "This is unique English text for signature verification",
            encoding="utf-8"
        )

        # Сохраняем оригинальный путь
        import src.common.charter.loader as charter_loader
        original_dir = charter_loader.CHARTER_TEMPLATES_DIR
        original_loader = charter_loader._charter_loader

        # Устанавливаем временный
        charter_loader.CHARTER_TEMPLATES_DIR = templates_dir
        charter_loader._charter_loader = CharterLoader(templates_dir)

        yield templates_dir

        # Восстанавливаем
        charter_loader.CHARTER_TEMPLATES_DIR = original_dir
        charter_loader._charter_loader = original_loader


@pytest.fixture
def storage(temp_charter_dir):
    """Фикстура для SQLiteStorage."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        # Инициализируем таблицу charter_acceptances
        init_charter_table(db)
        yield db
        db.close()


@pytest.fixture
def account_manager(storage):
    """Фикстура для AccountManager."""
    rate_limiter = MultiRateLimiter()
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
    )


@pytest.fixture
def keypair():
    """Фикстура: ключевая пара."""
    priv, pub = generate_keypair()
    return priv, pub


@pytest.fixture
def test_server(account_manager):
    """Создание тестового серверного аккаунта."""
    seed_phrase = "test_server_seed_phrase_for_charter"
    password = "test_password_123"

    result = account_manager.register(
        seed_phrase=seed_phrase,
        password=password,
        is_server=True,
        client_ip="127.0.0.1",
    )
    assert result["success"]

    return {
        "account_id": result["account_id"],
        "public_id": result["public_id"],
        "seed_phrase": seed_phrase,
        "password": password,
    }


class TestCharterSigner:
    """Тесты для функций подписания Устава."""

    def test_init_charter_table(self, storage):
        """Инициализация таблицы charter_acceptances."""
        cursor = storage.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='charter_acceptances'"
        )
        assert cursor.fetchone() is not None

    def test_sign_charter_success(self, storage, account_manager, test_server):
        """Успешное подписание Устава."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)

        result = sign_charter(storage, account_id, priv, "ru")
        assert result is True

        cursor = storage.execute_sql(
            "SELECT server_account_id, version, signature FROM charter_acceptances WHERE lang = 'ru'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == account_id
        assert row[1] == "1.0"
        assert len(row[2]) == 128

    def test_verify_charter_signature_valid(self, storage, account_manager, test_server):
        """Проверка валидной подписи."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)
        pub = account_manager.get_public_key(account_id)

        sign_charter(storage, account_id, priv, "ru")
        result = verify_charter_signature(storage, pub, "ru")
        assert result is True

    def test_verify_charter_signature_no_signature(self, storage, account_manager, test_server):
        """Проверка подписи, когда её нет."""
        pub = account_manager.get_public_key(test_server["account_id"])
        result = verify_charter_signature(storage, pub, "ru")
        assert result is False

    def test_verify_charter_signature_wrong_key(self, storage, account_manager, test_server):
        """Проверка подписи с неверным ключом."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)
        wrong_priv, wrong_pub = generate_keypair()

        sign_charter(storage, account_id, priv, "ru")
        result = verify_charter_signature(storage, wrong_pub, "ru")
        assert result is False

    def test_verify_charter_signature_tampered_text(self, storage, account_manager, test_server, temp_charter_dir):
        """Проверка подписи после изменения текста Устава."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)
        pub = account_manager.get_public_key(account_id)

        sign_charter(storage, account_id, priv, "ru")

        # Изменяем текст Устава
        ru_file = temp_charter_dir / "charter_ru.txt"
        ru_file.write_text("Изменённый текст Устава", encoding="utf-8")

        import src.common.charter.loader as charter_loader
        charter_loader._charter_loader = CharterLoader(temp_charter_dir)

        result = verify_charter_signature(storage, pub, "ru")
        assert result is False

    def test_check_charter_accepted_true(self, storage, account_manager, test_server):
        """Проверка, что Устав принят."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)

        sign_charter(storage, account_id, priv, "ru")
        accepted = check_charter_accepted(storage, account_id, "ru")
        assert accepted is True

    def test_check_charter_accepted_false(self, storage, test_server):
        """Проверка, что Устав не принят."""
        account_id = test_server["account_id"]
        accepted = check_charter_accepted(storage, account_id, "ru")
        assert accepted is False

    def test_get_charter_signature_exists(self, storage, account_manager, test_server):
        """Получение подписи, если она существует."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)

        sign_charter(storage, account_id, priv, "ru")
        signature = get_charter_signature(storage, account_id, "ru")
        assert signature is not None
        assert len(signature) == 128

    def test_get_charter_signature_not_exists(self, storage, test_server):
        """Получение подписи, когда её нет."""
        account_id = test_server["account_id"]
        signature = get_charter_signature(storage, account_id, "ru")
        assert signature is None

    def test_multiple_accounts_with_different_seeds(self, storage, account_manager):
        """Несколько аккаунтов с разными подписями (только первый серверный успешен)."""
        # Первый аккаунт - успешная регистрация
        result1 = account_manager.register(
            seed_phrase="test1@example.com",
            password="password123",
            is_server=True,
            client_ip="127.0.0.1",
        )
        assert result1["success"]
        acc_id1 = result1["account_id"]
        priv1 = account_manager.get_private_key(acc_id1, "test1@example.com")

        # Второй аккаунт - должен быть отклонён из-за лимита серверных аккаунтов
        result2 = account_manager.register(
            seed_phrase="test2@example.com",
            password="password123",
            is_server=True,
            client_ip="127.0.0.1",
        )
        assert result2["success"] is False
        assert result2["error"] == "max_servers_reached"

        # Подписываем только первый аккаунт
        sign_charter(storage, acc_id1, priv1, "ru")

        sig1 = get_charter_signature(storage, acc_id1, "ru")
        assert sig1 is not None
        assert len(sig1) == 128

    def test_different_languages(self, storage, account_manager, test_server):
        """Подписание Устава на разных языках."""
        account_id = test_server["account_id"]
        seed_phrase = test_server["seed_phrase"]

        priv = account_manager.get_private_key(account_id, seed_phrase)
        pub = account_manager.get_public_key(account_id)

        # Проверяем, что тексты действительно разные
        text_ru = get_charter_text("ru")
        text_en = get_charter_text("en")
        assert text_ru != text_en, "Texts should be different"

        # Подписываем русский
        sign_charter(storage, account_id, priv, "ru")
        sig_ru = get_charter_signature(storage, account_id, "ru")

        # Подписываем английский
        sign_charter(storage, account_id, priv, "en")
        sig_en = get_charter_signature(storage, account_id, "en")

        # Подписи должны быть разными
        assert sig_ru != sig_en, "Signatures for different languages should be different"

        # Проверяем верификацию
        assert verify_charter_signature(storage, pub, "ru") is True
        assert verify_charter_signature(storage, pub, "en") is True
