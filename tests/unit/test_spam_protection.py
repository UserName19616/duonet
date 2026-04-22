# tests/unit/test_spam_protection.py
"""
Тесты для модуля защиты от спама.
"""

import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.client.messaging.spam_protection import MAX_REJECTIONS_PER_DAY, SpamProtection
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def spam(storage):
    return SpamProtection(storage)


class TestSpamProtection:
    """Тесты для SpamProtection."""

    def test_record_rejection_first(self, spam):
        """Первый отказ."""
        result = spam.record_rejection("user@test.ru")

        assert result["rejections_today"] == 1
        assert result["rejections_total"] == 1
        assert result["blocked"] is False
        assert result["block_level"] == 0

    def test_record_rejection_reaches_limit(self, spam):
        """Достижение лимита отказов."""
        user = "user@test.ru"

        # 50 отказов (лимит)
        for i in range(MAX_REJECTIONS_PER_DAY):
            spam.record_rejection(user)
            # После 50 отказов блокировка должна сработать
            if i == MAX_REJECTIONS_PER_DAY - 1:
                result = spam.record_rejection(user)
                assert result["block_level"] == 1
                assert result["blocked"] is True
                break

    def test_record_rejection_second_block(self, spam):
        """Вторая блокировка."""
        user = "user@test.ru"

        # Первая блокировка (достигаем лимита)
        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        # Проверяем первую блокировку
        assert spam.get_block_level(user) == 1

        # Имитация прошедшего времени (истечение блокировки)
        stats = spam._load_stats(user)
        stats.block_until = time.time() - 1  # истекла
        stats.block_level = 0  # разблокирован
        spam._save_stats(stats)

        # Вторая блокировка
        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        result = spam.record_rejection(user)
        assert result["block_level"] == 2
        assert result["blocked"] is True

    def test_record_rejection_third_block(self, spam):
        """Третья блокировка (бессрочный бан)."""
        user = "user@test.ru"

        # Первая блокировка (достигаем лимита)
        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)
        assert spam.get_block_level(user) == 1

        # Снимаем блокировку (имитация прошедшего времени)
        stats = spam._load_stats(user)
        stats.block_until = time.time() - 1
        stats.block_level = 0
        spam._save_stats(stats)

        # Вторая блокировка
        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)
        assert spam.get_block_level(user) == 2

        # Снимаем блокировку
        stats = spam._load_stats(user)
        stats.block_until = time.time() - 1
        stats.block_level = 0
        spam._save_stats(stats)

        # Третья блокировка (должна быть бессрочной)
        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        result = spam.record_rejection(user)
        assert result["block_level"] == 3
        assert result["blocked"] is True
        assert result["block_until"] is None

    def test_is_blocked(self, spam):
        """Проверка блокировки."""
        user = "user@test.ru"

        assert spam.is_blocked(user) is False

        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        assert spam.is_blocked(user) is True

    def test_get_block_level(self, spam):
        """Получение уровня блокировки."""
        user = "user@test.ru"

        assert spam.get_block_level(user) == 0

        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        assert spam.get_block_level(user) == 1

    def test_get_remaining_invites(self, spam):
        """Получение оставшихся приглашений."""
        user = "user@test.ru"

        assert spam.get_remaining_invites(user) == MAX_REJECTIONS_PER_DAY

        for i in range(30):
            spam.record_rejection(user)

        assert spam.get_remaining_invites(user) == MAX_REJECTIONS_PER_DAY - 30

    def test_record_accept_resets_counter(self, spam):
        """Принятие сбрасывает счетчик отказов."""
        user = "user@test.ru"

        for i in range(10):
            spam.record_rejection(user)

        assert spam.get_remaining_invites(user) == MAX_REJECTIONS_PER_DAY - 10

        result = spam.record_accept(user)

        assert result["rejections_today"] == 0
        assert result["accepts_today"] == 1
        assert spam.get_remaining_invites(user) == MAX_REJECTIONS_PER_DAY

    def test_accept_increases_accepts_today(self, spam):
        """Принятие увеличивает счетчик принятий."""
        user = "user@test.ru"

        result1 = spam.record_accept(user)
        assert result1["accepts_today"] == 1

        result2 = spam.record_accept(user)
        assert result2["accepts_today"] == 2

    def test_daily_reset(self, spam):
        """Сброс счетчиков в новый день."""
        user = "user@test.ru"

        # Набираем 10 отказов
        for i in range(10):
            spam.record_rejection(user)

        # Меняем дату (имитация нового дня)
        with patch("src.client.messaging.spam_protection.datetime") as mock_datetime:
            # Создаем дату вчерашнего дня
            yesterday = datetime(2024, 1, 1, tzinfo=timezone.utc)
            mock_datetime.now.return_value = yesterday

            stats = spam._load_stats(user)
            stats.last_reset_date = "2024-01-01"
            spam._save_stats(stats)

        # Следующий вызов должен сбросить счетчик
        result = spam.record_rejection(user)

        assert result["rejections_today"] == 1  # новый день, новый счетчик
        assert result["rejections_total"] == 11  # общий счетчик увеличился

    def test_get_stats(self, spam):
        """Получение полной статистики."""
        user = "user@test.ru"

        spam.record_rejection(user)
        spam.record_rejection(user)
        spam.record_accept(user)

        stats = spam.get_stats(user)
        assert stats is not None
        assert stats["user_id"] == user
        assert stats["rejections_today"] == 0  # сброшен после accept
        assert stats["accepts_today"] == 1
        assert stats["rejections_total"] == 2
        assert stats["remaining_invites"] == MAX_REJECTIONS_PER_DAY

    def test_reset_user(self, spam):
        """Сброс статистики пользователя."""
        user = "user@test.ru"

        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        assert spam.get_block_level(user) == 1

        spam.reset_user(user)

        assert spam.get_block_level(user) == 0
        assert spam.is_blocked(user) is False
        assert spam.get_remaining_invites(user) == MAX_REJECTIONS_PER_DAY

    def test_persistence(self, spam, storage):
        """Персистентность данных."""
        user = "user@test.ru"

        spam.record_rejection(user)
        spam.record_rejection(user)

        # Создаем новый экземпляр с тем же storage
        spam2 = SpamProtection(storage)

        stats = spam2.get_stats(user)
        assert stats is not None
        assert stats["rejections_today"] == 2

    def test_block_expiration(self, spam):
        """Истечение блокировки."""
        user = "user@test.ru"

        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        assert spam.is_blocked(user) is True

        # Принудительно меняем block_until
        stats = spam._load_stats(user)
        stats.block_until = time.time() - 1  # уже истекло
        spam._save_stats(stats)

        assert spam.is_blocked(user) is False

    def test_accept_unblocks_after_expiration(self, spam):
        """Принятие разблокирует после истечения блокировки."""
        user = "user@test.ru"

        # Создаем блокировку
        for i in range(MAX_REJECTIONS_PER_DAY + 1):
            spam.record_rejection(user)

        # Истекаем
        stats = spam._load_stats(user)
        stats.block_until = time.time() - 1
        spam._save_stats(stats)

        # Принятие должно разблокировать
        result = spam.record_accept(user)
        assert result["blocked"] is False
        assert result["block_level"] == 0

    def test_corrupted_data_handling(self, spam, storage):
        """Обработка поврежденных данных."""
        user = "user@test.ru"

        spam.record_rejection(user)

        # Повреждаем данные
        key = spam._make_key(user)
        storage.put(key, b"invalid json{")

        # Должен вернуть новые данные
        stats = spam._load_stats(user)
        assert stats.rejections_today == 0
        assert stats.block_level == 0
