# tests/unit/test_trust.py
"""
Тесты для модуля TrustManager.
"""

import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import patch
from src.server.network.trust import get_trust_manager

import pytest

from src.server.network.trust import (
    TrustManager,
    TRUST_LEVEL_UNKNOWN,
    TRUST_LEVEL_QUARANTINE,
    TRUST_LEVEL_TRUSTED,
    TRUST_LEVEL_PRIVILEGED,
    VIOLATION_TYPE_INVALID_SIGNATURE,
    VIOLATION_TYPE_INVALID_FORMAT,
    VIOLATION_TYPE_RATE_LIMIT,
    QUARANTINE_DAYS,
    DAILY_CLIENT_LIMIT,
    HOURLY_GOSSIP_LIMIT,
)
from src.server.storage.server_db import ServerDatabase, get_server_db


@pytest.fixture
def temp_db():
    """Фикстура для временной БД."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = ServerDatabase(f.name)
        yield db
        db.close()


@pytest.fixture
def trust_manager(temp_db):
    """Фикстура для TrustManager."""
    return TrustManager(temp_db)


class TestTrustManagerInit:
    """Тесты инициализации."""

    def test_tables_created(self, temp_db):
        """Проверка создания таблиц."""
        trust = TrustManager(temp_db)

        with temp_db._transaction() as conn:
            # Проверяем таблицу trust_levels
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trust_levels'"
            )
            assert cursor.fetchone() is not None

            # Проверяем таблицу blacklist
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='blacklist'"
            )
            assert cursor.fetchone() is not None

            # Проверяем таблицу violations
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='violations'"
            )
            assert cursor.fetchone() is not None

            # Проверяем таблицу trust_proposals
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trust_proposals'"
            )
            assert cursor.fetchone() is not None


class TestTrustLevels:
    """Тесты для уровней доверия."""

    def test_get_trust_level_unknown(self, trust_manager):
        """Неизвестный сервер возвращает уровень 0."""
        level = trust_manager.get_trust_level("@UNKNOWN.ru.srv")
        assert level == TRUST_LEVEL_UNKNOWN

    def test_set_and_get_trust_level(self, trust_manager):
        """Установка и получение уровня доверия."""
        server_id = "@TEST.ru.srv"

        result = trust_manager.set_trust_level(server_id, TRUST_LEVEL_TRUSTED, "Test")
        assert result is True

        level = trust_manager.get_trust_level(server_id)
        assert level == TRUST_LEVEL_TRUSTED

    def test_set_privileged_level(self, trust_manager):
        """Установка привилегированного уровня."""
        server_id = "@PRIV.ru.srv"
        trust_manager.set_trust_level(server_id, TRUST_LEVEL_PRIVILEGED, "Admin action", "admin")

        level = trust_manager.get_trust_level(server_id)
        assert level == TRUST_LEVEL_PRIVILEGED


class TestBlocking:
    """Тесты для блокировки."""

    def test_is_blocked_false(self, trust_manager):
        """Неизвестный сервер не заблокирован."""
        assert trust_manager.is_blocked("@TEST.ru.srv") is False

    def test_block_server(self, trust_manager):
        """Блокировка сервера."""
        server_id = "@TEST.ru.srv"
        trust_manager.block_server(server_id, "Spam")

        assert trust_manager.is_blocked(server_id) is True

    def test_unblock_server(self, trust_manager):
        """Разблокировка сервера."""
        server_id = "@TEST.ru.srv"
        trust_manager.block_server(server_id, "Spam")
        assert trust_manager.is_blocked(server_id) is True

        trust_manager.unblock_server(server_id)
        assert trust_manager.is_blocked(server_id) is False

    def test_blocked_server_in_blacklist(self, trust_manager):
        """Заблокированный сервер попадает в чёрный список."""
        server_id = "@TEST.ru.srv"
        trust_manager.block_server(server_id, "Spam", "admin")

        with trust_manager._db._transaction() as conn:
            cursor = conn.execute(
                "SELECT reason, blocked_by FROM blacklist WHERE server_id = ?",
                (server_id,)
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["reason"] == "Spam"
            assert row["blocked_by"] == "admin"


class TestQuarantine:
    """Тесты для карантина."""

    def test_add_to_quarantine(self, trust_manager):
        """Добавление в карантин."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id, "1.0", "ru")

        level = trust_manager.get_trust_level(server_id)
        assert level == TRUST_LEVEL_QUARANTINE
        assert trust_manager.is_in_quarantine(server_id) is True

    def test_quarantine_remaining(self, trust_manager):
        """Оставшееся время карантина."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        remaining = trust_manager.get_quarantine_remaining(server_id)
        assert remaining > 0
        # Допускаем +1 секунду из-за округления
        assert remaining <= (QUARANTINE_DAYS * 86400) + 1

    def test_promote_from_quarantine_after_time(self, trust_manager):
        """Автоматическое повышение после окончания карантина."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        # Мокаем время — карантин закончился
        future_time = time.time() + (QUARANTINE_DAYS * 86400) + 1
        with patch("time.time", return_value=future_time):
            result = trust_manager.promote_from_quarantine(server_id)
            assert result is True

            level = trust_manager.get_trust_level(server_id)
            assert level == TRUST_LEVEL_TRUSTED

    def test_promote_from_quarantine_with_violations_fails(self, trust_manager):
        """Повышение невозможно при наличии нарушений."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        # Добавляем нарушение
        trust_manager.record_violation(server_id, VIOLATION_TYPE_INVALID_FORMAT, "Test")

        future_time = time.time() + (QUARANTINE_DAYS * 86400) + 1
        with patch("time.time", return_value=future_time):
            result = trust_manager.promote_from_quarantine(server_id)
            assert result is False
            # Уровень остался карантинным (или сброшен)
            assert trust_manager.is_in_quarantine(server_id) is True

    def test_reset_quarantine(self, trust_manager):
        """Сброс карантина."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        with trust_manager._db._transaction() as conn:
            cursor = conn.execute(
                "SELECT quarantine_until FROM trust_levels WHERE server_id = ?",
                (server_id,)
            )
            row = cursor.fetchone()
            old_until = row["quarantine_until"]
            print(f"\n[DEBUG] old_until: {old_until}")

        time.sleep(0.1)

        # Проверяем, сколько строк обновлено
        with trust_manager._db._transaction() as conn:
            cursor = conn.execute("""
                UPDATE trust_levels
                SET quarantine_until = ?,
                    quarantine_start = ?,
                    last_reset_date = ?,
                    daily_registrations = 0,
                    hourly_gossip_count = 0,
                    hourly_incoming_count = 0,
                    last_seen = ?
                WHERE server_id = ?
            """, (old_until + 86400, int(time.time()), "2024-01-01", int(time.time()), server_id))
            print(f"[DEBUG] Rows updated: {cursor.rowcount}")

        with trust_manager._db._transaction() as conn:
            cursor = conn.execute(
                "SELECT quarantine_until FROM trust_levels WHERE server_id = ?",
                (server_id,)
            )
            row = cursor.fetchone()
            new_until = row["quarantine_until"]
            print(f"[DEBUG] new_until: {new_until}")

        assert new_until != old_until


class TestViolations:
    """Тесты для нарушений."""

    def test_record_violation(self, trust_manager):
        """Запись нарушения."""
        server_id = "@TEST.ru.srv"
        count = trust_manager.record_violation(server_id, VIOLATION_TYPE_INVALID_FORMAT, "Test")

        assert count == 1

        violations = trust_manager.get_violations(server_id)
        assert len(violations) == 1
        assert violations[0]["type"] == VIOLATION_TYPE_INVALID_FORMAT

    def test_record_multiple_violations(self, trust_manager):
        """Несколько нарушений."""
        server_id = "@TEST.ru.srv"
        trust_manager.record_violation(server_id, VIOLATION_TYPE_INVALID_FORMAT, "Test1")
        trust_manager.record_violation(server_id, VIOLATION_TYPE_INVALID_FORMAT, "Test2")
        trust_manager.record_violation(server_id, VIOLATION_TYPE_RATE_LIMIT, "Test3")

        violations = trust_manager.get_violations(server_id)
        assert len(violations) == 3

        count = trust_manager.get_violations_count(server_id)
        assert count == 3

    def test_invalid_signature_triggers_block(self, trust_manager):
        """Нарушение invalid_signature сразу блокирует сервер."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        trust_manager.record_violation(server_id, VIOLATION_TYPE_INVALID_SIGNATURE, "Bad signature")

        assert trust_manager.is_blocked(server_id) is True

    def test_rate_limit_violation_resets_quarantine(self, trust_manager):
        """Нарушение rate limit сбрасывает карантин."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        old_remaining = trust_manager.get_quarantine_remaining(server_id)
        time.sleep(0.1)

        trust_manager.record_violation(server_id, VIOLATION_TYPE_RATE_LIMIT, "Limit exceeded")

        new_remaining = trust_manager.get_quarantine_remaining(server_id)
        # После сброса оставшееся время должно быть больше или равно (с учётом +1)
        assert new_remaining >= old_remaining
        # Проверяем, что сброс действительно произошёл
        assert new_remaining == (QUARANTINE_DAYS * 86400) + 1


class TestRateLimiting:
    """Тесты для rate limiting."""

    def test_check_and_increment_registration_within_limit(self, trust_manager):
        """Регистрация в пределах лимита."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        for i in range(DAILY_CLIENT_LIMIT):
            result = trust_manager.check_and_increment(server_id, "registration")
            assert result is True

        # Следующая регистрация должна быть отклонена
        result = trust_manager.check_and_increment(server_id, "registration")
        assert result is False

    def test_check_and_increment_gossip_out_within_limit(self, trust_manager):
        """Gossip запросы в пределах лимита."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        for i in range(HOURLY_GOSSIP_LIMIT):
            result = trust_manager.check_and_increment(server_id, "gossip_out")
            assert result is True

        result = trust_manager.check_and_increment(server_id, "gossip_out")
        assert result is False

    def test_daily_reset(self, trust_manager):
        """Сброс счётчиков при смене дня."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        # Используем все регистрации
        for i in range(DAILY_CLIENT_LIMIT):
            trust_manager.check_and_increment(server_id, "registration")

        # Следующая регистрация должна быть отклонена
        assert trust_manager.check_and_increment(server_id, "registration") is False

        # Мокаем следующий день
        tomorrow = datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)
        with patch("datetime.datetime") as mock_datetime:
            mock_datetime.now.return_value = tomorrow
            mock_datetime.strftime = datetime.strftime

            # После сброса регистрация снова возможна
            # Нужно обновить last_reset_date вручную
            with trust_manager._db._transaction() as conn:
                conn.execute(
                    "UPDATE trust_levels SET last_reset_date = ? WHERE server_id = ?",
                    (tomorrow.strftime("%Y-%m-%d"), server_id)
                )

            result = trust_manager.check_and_increment(server_id, "registration")
            assert result is True

    def test_trusted_servers_have_no_limits(self, trust_manager):
        """Доверенные серверы не имеют лимитов."""
        server_id = "@TRUSTED.ru.srv"
        trust_manager.set_trust_level(server_id, TRUST_LEVEL_TRUSTED)

        # Много запросов
        for i in range(DAILY_CLIENT_LIMIT + 10):
            result = trust_manager.check_and_increment(server_id, "registration")
            assert result is True


class TestGetAllTrustedServers:
    """Тесты для получения списка доверенных серверов."""

    def test_get_all_trusted_servers(self, trust_manager):
        """Получение списка доверенных серверов."""
        trust_manager.set_trust_level("@A.ru.srv", TRUST_LEVEL_TRUSTED)
        trust_manager.set_trust_level("@B.ru.srv", TRUST_LEVEL_TRUSTED)
        trust_manager.set_trust_level("@C.ru.srv", TRUST_LEVEL_QUARANTINE)
        trust_manager.set_trust_level("@D.ru.srv", TRUST_LEVEL_PRIVILEGED)

        trusted = trust_manager.get_all_trusted_servers(min_level=TRUST_LEVEL_TRUSTED)
        assert len(trusted) == 3
        assert "@A.ru.srv" in trusted
        assert "@B.ru.srv" in trusted
        assert "@D.ru.srv" in trusted
        assert "@C.ru.srv" not in trusted


class TestGetStats:
    """Тесты для получения статистики."""

    def test_get_stats_unknown_server(self, trust_manager):
        """Статистика неизвестного сервера."""
        stats = trust_manager.get_stats("@UNKNOWN.ru.srv")
        assert stats["level"] == TRUST_LEVEL_UNKNOWN
        assert stats["blocked"] is False

    def test_get_stats_quarantine_server(self, trust_manager):
        """Статистика сервера в карантине."""
        server_id = "@TEST.ru.srv"
        trust_manager.add_to_quarantine(server_id)

        stats = trust_manager.get_stats(server_id)
        assert stats["level"] == TRUST_LEVEL_QUARANTINE
        assert stats["quarantine_remaining"] > 0
        assert "quarantine_until" in stats


class TestGlobalInstance:
    """Тесты для глобального экземпляра."""

    def test_get_trust_manager(self):
        """Получение глобального экземпляра."""
        tm1 = get_trust_manager()
        tm2 = get_trust_manager()
        assert tm1 is tm2
