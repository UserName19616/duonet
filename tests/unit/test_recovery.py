# tests/unit/test_recovery.py
"""
Тесты для модуля восстановления пароля.
"""

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from src.common.identity.account import AccountManager
from src.common.identity.recovery import (
    ConsoleEmailSender,
    NullEmailSender,
    RecoveryService,
    SmtpEmailSender,
)
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def account_manager(storage):
    geoip = get_region_by_ip
    rate_limiter = MultiRateLimiter()
    return AccountManager(
        storage=storage,
        geoip_func=geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
    )


@pytest.fixture
def recovery_service(storage, account_manager):
    return RecoveryService(storage, account_manager)


class TestExtractEmailFromSeed:
    """Тесты для extract_email_from_seed."""

    def test_extract_from_start(self):
        """Email в начале строки."""
        email = RecoveryService.extract_email_from_seed("user@example.com моя фраза")
        assert email == "user@example.com"

    def test_extract_from_end(self):
        """Email в конце строки."""
        email = RecoveryService.extract_email_from_seed("моя фраза user@example.com")
        assert email == "user@example.com"

    def test_extract_only_email(self):
        """Только email."""
        email = RecoveryService.extract_email_from_seed("user@example.com")
        assert email == "user@example.com"

    def test_extract_middle(self):
        """Email в середине строки."""
        email = RecoveryService.extract_email_from_seed("фраза user@example.com текст")
        assert email is None

    def test_extract_invalid(self):
        """Некорректный email."""
        email = RecoveryService.extract_email_from_seed("user12@example.com12 моя фраза")
        assert email is None

    def test_extract_complex_email(self):
        """Сложный email."""
        email = RecoveryService.extract_email_from_seed(
            "user.name+tag@sub.domain.co.uk моя фраза"
        )
        assert email == "user.name+tag@sub.domain.co.uk"


# ... остальные тесты без изменений ...
