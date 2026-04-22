# src/network/rate_limiter.py
"""
Модуль ограничения частоты запросов (Rate Limiting).

Защита от DDoS-атак и злоупотреблений.
"""

import threading
import time
from typing import Dict, Optional


class RateLimiter:
    """
    Ограничитель для одного типа операций.

    Реализует алгоритм скользящего окна с очисткой устаревших записей.
    """

    def __init__(self, limit: int, period: int, cleanup_interval: int = 300):
        """
        Инициализация ограничителя.

        Args:
            limit: Максимальное количество операций за период.
            period: Период времени в секундах.
            cleanup_interval: Интервал очистки устаревших записей (сек).
        """
        self.limit = limit
        self.period = period
        self.cleanup_interval = cleanup_interval

        self._counters: Dict[str, list] = {}  # key -> list of timestamps
        self._lock = threading.RLock()
        self._last_cleanup = time.time()

    def _cleanup(self) -> None:
        """Очистка устаревших записей."""
        now = time.time()
        cutoff = now - self.period

        with self._lock:
            for key in list(self._counters.keys()):
                timestamps = self._counters[key]
                # Удаляем устаревшие метки времени
                while timestamps and timestamps[0] < cutoff:
                    timestamps.pop(0)
                # Если список пуст, удаляем ключ
                if not timestamps:
                    del self._counters[key]

            self._last_cleanup = now

    def _check_cleanup(self) -> None:
        """Проверка необходимости очистки."""
        now = time.time()
        if now - self._last_cleanup >= self.cleanup_interval:
            self._cleanup()

    def check(self, key: str) -> bool:
        """
        Проверка, не превышен ли лимит для ключа.

        Args:
            key: Идентификатор (IP, user_id и т.д.).

        Returns:
            True если лимит не превышен.
        """
        self._check_cleanup()

        with self._lock:
            timestamps = self._counters.get(key, [])
            cutoff = time.time() - self.period

            # Считаем количество операций в текущем окне
            count = sum(1 for ts in timestamps if ts >= cutoff)
            return count < self.limit

    def increment(self, key: str) -> int:
        """
        Увеличить счётчик для ключа.

        Args:
            key: Идентификатор.

        Returns:
            Текущее количество операций.
        """
        self._check_cleanup()

        now = time.time()
        cutoff = now - self.period

        with self._lock:
            if key not in self._counters:
                self._counters[key] = []

            timestamps = self._counters[key]

            # Удаляем устаревшие
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)

            # Добавляем новую метку
            timestamps.append(now)

            return len(timestamps)

    def reset(self, key: str) -> None:
        """
        Сбросить счётчик для ключа.

        Args:
            key: Идентификатор.
        """
        with self._lock:
            if key in self._counters:
                del self._counters[key]

    def get_count(self, key: str) -> int:
        """
        Получить текущее количество операций для ключа.

        Args:
            key: Идентификатор.

        Returns:
            Количество операций в текущем окне.
        """
        self._check_cleanup()

        with self._lock:
            timestamps = self._counters.get(key, [])
            cutoff = time.time() - self.period
            return sum(1 for ts in timestamps if ts >= cutoff)

    def get_remaining(self, key: str) -> int:
        """
        Получить количество оставшихся операций.

        Args:
            key: Идентификатор.

        Returns:
            Оставшееся количество операций.
        """
        count = self.get_count(key)
        return max(0, self.limit - count)

    def get_reset_time(self, key: str) -> Optional[float]:
        """
        Получить время сброса счётчика.

        Args:
            key: Идентификатор.

        Returns:
            Timestamp сброса или None если счётчик пуст.
        """
        with self._lock:
            timestamps = self._counters.get(key, [])
            if not timestamps:
                return None
            oldest = min(timestamps)
            return oldest + self.period


class MultiRateLimiter:
    """
    Менеджер нескольких лимитеров для разных операций.

    Предопределённые лимиты для прототипа.
    """

    # Константы из C0.5_config
    REGISTRATION_LIMIT = 3
    REGISTRATION_PERIOD = 86400  # 24 часа
    INVITE_LIMIT = 50
    INVITE_PERIOD = 86400  # 24 часа
    DHT_LOOKUP_LIMIT = 100
    DHT_LOOKUP_PERIOD = 60  # 1 минута
    SEND_MESSAGE_LIMIT = 60
    SEND_MESSAGE_PERIOD = 60  # 1 минута
    CONNECT_LIMIT = 10
    CONNECT_PERIOD = 60  # 1 минута

    def __init__(self):
        """Инициализация мульти-лимитера."""
        self._limiters: Dict[str, RateLimiter] = {
            "registration": RateLimiter(
                self.REGISTRATION_LIMIT, self.REGISTRATION_PERIOD
            ),
            "invite": RateLimiter(self.INVITE_LIMIT, self.INVITE_PERIOD),
            "dht_lookup": RateLimiter(
                self.DHT_LOOKUP_LIMIT, self.DHT_LOOKUP_PERIOD
            ),
            "send_message": RateLimiter(
                self.SEND_MESSAGE_LIMIT, self.SEND_MESSAGE_PERIOD
            ),
            "connect": RateLimiter(self.CONNECT_LIMIT, self.CONNECT_PERIOD),
        }

    def check(self, operation: str, key: str) -> bool:
        """
        Проверка лимита для операции.

        Args:
            operation: Тип операции.
            key: Идентификатор.

        Returns:
            True если лимит не превышен.
        """
        limiter = self._limiters.get(operation)
        if limiter is None:
            return True  # Неизвестная операция — разрешаем
        return limiter.check(key)

    def increment(self, operation: str, key: str) -> int:
        """
        Увеличить счётчик для операции.

        Args:
            operation: Тип операции.
            key: Идентификатор.

        Returns:
            Текущее количество операций.
        """
        limiter = self._limiters.get(operation)
        if limiter is None:
            return 0
        return limiter.increment(key)

    def reset(self, operation: str, key: str) -> None:
        """
        Сбросить счётчик для операции.

        Args:
            operation: Тип операции.
            key: Идентификатор.
        """
        limiter = self._limiters.get(operation)
        if limiter is not None:
            limiter.reset(key)

    def get_remaining(self, operation: str, key: str) -> int:
        """
        Получить количество оставшихся операций.

        Args:
            operation: Тип операции.
            key: Идентификатор.

        Returns:
            Оставшееся количество операций.
        """
        limiter = self._limiters.get(operation)
        if limiter is None:
            return 0
        return limiter.get_remaining(key)
