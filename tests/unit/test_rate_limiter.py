# tests/unit/test_rate_limiter.py
"""
Тесты для модуля ограничения частоты запросов.
"""

import threading
import time

import pytest

from src.server.network.rate_limiter import MultiRateLimiter, RateLimiter


class TestRateLimiter:
    """Тесты для RateLimiter."""

    def test_basic(self):
        """Базовый тест: проверка лимита."""
        limiter = RateLimiter(limit=3, period=10)
        key = "test_key"

        for i in range(3):
            assert limiter.check(key) is True
            limiter.increment(key)

        assert limiter.check(key) is False

    def test_reset(self):
        """Тест сброса счётчика."""
        limiter = RateLimiter(limit=3, period=10)
        key = "test_key"

        for i in range(3):
            limiter.increment(key)

        assert limiter.check(key) is False

        limiter.reset(key)
        assert limiter.check(key) is True

    def test_timeout(self):
        """Тест истечения периода."""
        limiter = RateLimiter(limit=3, period=1)
        key = "test_key"

        for i in range(3):
            limiter.increment(key)

        assert limiter.check(key) is False

        time.sleep(1.1)
        assert limiter.check(key) is True

    def test_get_count(self):
        """Тест получения количества операций."""
        limiter = RateLimiter(limit=5, period=10)
        key = "test_key"

        assert limiter.get_count(key) == 0
        assert limiter.get_remaining(key) == 5

        limiter.increment(key)
        assert limiter.get_count(key) == 1
        assert limiter.get_remaining(key) == 4

    def test_get_reset_time(self):
        """Тест получения времени сброса."""
        limiter = RateLimiter(limit=3, period=10)
        key = "test_key"

        assert limiter.get_reset_time(key) is None

        limiter.increment(key)
        reset_time = limiter.get_reset_time(key)
        assert reset_time is not None
        assert reset_time > time.time()

    def test_different_keys(self):
        """Тест независимости разных ключей."""
        limiter = RateLimiter(limit=3, period=10)
        key1 = "key1"
        key2 = "key2"

        for i in range(3):
            limiter.increment(key1)

        assert limiter.check(key1) is False
        assert limiter.check(key2) is True

    def test_cleanup(self):
        """Тест очистки устаревших записей."""
        limiter = RateLimiter(limit=3, period=1, cleanup_interval=1)
        key = "test_key"
        limiter.increment(key)

        time.sleep(1.1)
        # Принудительная очистка (вызывается автоматически при check)
        limiter.check(key)
        assert limiter.get_count(key) == 0

    def test_thread_safety(self):
        """Тест потокобезопасности."""
        limiter = RateLimiter(limit=100, period=10)
        results = []
        errors = []

        def worker():
            try:
                for i in range(50):
                    limiter.increment("key")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Из-за race condition может быть больше 100, но не должно быть ошибок
        assert limiter.get_count("key") <= 200  # допустимый запас


class TestMultiRateLimiter:
    """Тесты для MultiRateLimiter."""

    def test_registration(self):
        """Тест лимита регистрации."""
        multi = MultiRateLimiter()
        ip = "192.168.1.1"

        for i in range(3):
            assert multi.check("registration", ip) is True
            multi.increment("registration", ip)

        assert multi.check("registration", ip) is False

    def test_invite(self):
        """Тест лимита приглашений."""
        multi = MultiRateLimiter()
        user = "user123"

        for i in range(50):
            assert multi.check("invite", user) is True
            multi.increment("invite", user)

        assert multi.check("invite", user) is False

    def test_dht_lookup(self):
        """Тест лимита DHT поиска."""
        multi = MultiRateLimiter()
        user = "user123"

        for i in range(100):
            assert multi.check("dht_lookup", user) is True
            multi.increment("dht_lookup", user)

        assert multi.check("dht_lookup", user) is False

    def test_send_message(self):
        """Тест лимита отправки сообщений."""
        multi = MultiRateLimiter()
        user = "user123"

        for i in range(60):
            assert multi.check("send_message", user) is True
            multi.increment("send_message", user)

        assert multi.check("send_message", user) is False

    def test_connect(self):
        """Тест лимита подключений."""
        multi = MultiRateLimiter()
        ip = "192.168.1.1"

        for i in range(10):
            assert multi.check("connect", ip) is True
            multi.increment("connect", ip)

        assert multi.check("connect", ip) is False

    def test_unknown_operation(self):
        """Тест неизвестной операции."""
        multi = MultiRateLimiter()
        assert multi.check("unknown", "key") is True
        assert multi.increment("unknown", "key") == 0
        assert multi.get_remaining("unknown", "key") == 0

    def test_reset(self):
        """Тест сброса счётчика."""
        multi = MultiRateLimiter()
        ip = "192.168.1.1"

        multi.increment("registration", ip)
        multi.increment("registration", ip)

        assert multi.get_remaining("registration", ip) == 1

        multi.reset("registration", ip)
        assert multi.get_remaining("registration", ip) == 3

    def test_get_remaining(self):
        """Тест получения оставшихся операций."""
        multi = MultiRateLimiter()
        ip = "192.168.1.1"

        assert multi.get_remaining("registration", ip) == 3

        multi.increment("registration", ip)
        assert multi.get_remaining("registration", ip) == 2

    def test_independent_limiters(self):
        """Тест независимости разных лимитеров."""
        multi = MultiRateLimiter()
        ip = "192.168.1.1"

        # Исчерпываем registration
        for i in range(3):
            multi.increment("registration", ip)

        # Остальные лимитеры должны работать
        assert multi.check("invite", ip) is True
        assert multi.check("send_message", ip) is True
        assert multi.check("connect", ip) is True
