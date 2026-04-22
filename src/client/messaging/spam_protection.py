# src/client/messaging/spam_protection.py (исправленный)
"""
Защита от спама в Invite-запросах.

Отслеживает количество отклонённых приглашений и применяет блокировки.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Исправляем импорт: config на уровне src
from src.config import MAX_REJECTIONS_PER_DAY, BLOCK_LEVELS
from src.common.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

# Константы (импортированы из config)
MAX_REJECTIONS_PER_DAY = MAX_REJECTIONS_PER_DAY
DAILY_RESET_HOUR = 0  # UTC

# Уровни блокировок (импортированы из config)
BLOCK_LEVELS = BLOCK_LEVELS


@dataclass
class SpamStats:
    """Статистика спама для пользователя."""

    user_id: str  # Public ID пользователя
    rejections_today: int  # количество отказов сегодня
    rejections_total: int  # общее количество отказов
    accepts_today: int  # количество принятий сегодня
    last_rejection_time: float  # время последнего отказа
    last_accept_time: float  # время последнего принятия
    block_level: int  # текущий уровень блокировки (0-3)
    block_until: Optional[float]  # время окончания блокировки
    last_reset_date: str  # дата последнего сброса (YYYY-MM-DD)
    created_at: float  # время создания записи
    updated_at: float  # время последнего обновления
    block_history: List[int] = field(default_factory=list)  # история уровней блокировок


class SpamProtection:
    """
    Защита от спама в Invite-запросах.

    Отслеживает количество отклонённых приглашений и применяет блокировки.
    """

    def __init__(self, storage: SQLiteStorage):
        """
        Инициализация защиты от спама.

        Args:
            storage: Экземпляр SQLiteStorage.
        """
        self._storage = storage
        self._prefix = "spam_stats:"
        self._init_db()

    def _init_db(self) -> None:
        """Инициализация таблицы spam_stats."""
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS spam_stats (
                user_id TEXT PRIMARY KEY,
                stats TEXT NOT NULL
            )
        """)

    def _make_key(self, user_id: str) -> bytes:
        """Формирование ключа для статистики."""
        return f"{self._prefix}{user_id}".encode()

    def _get_today_date(self) -> str:
        """Получение текущей даты в формате YYYY-MM-DD."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _serialize(self, stats: SpamStats) -> bytes:
        """Сериализация статистики в JSON."""
        data = {
            "user_id": stats.user_id,
            "rejections_today": stats.rejections_today,
            "rejections_total": stats.rejections_total,
            "accepts_today": stats.accepts_today,
            "last_rejection_time": stats.last_rejection_time,
            "last_accept_time": stats.last_accept_time,
            "block_level": stats.block_level,
            "block_until": stats.block_until,
            "last_reset_date": stats.last_reset_date,
            "created_at": stats.created_at,
            "updated_at": stats.updated_at,
            "block_history": stats.block_history,
        }
        return json.dumps(data).encode()

    def _deserialize(self, data: bytes) -> Optional[SpamStats]:
        """Десериализация статистики из JSON."""
        try:
            obj = json.loads(data)
            return SpamStats(
                user_id=obj["user_id"],
                rejections_today=obj["rejections_today"],
                rejections_total=obj["rejections_total"],
                accepts_today=obj["accepts_today"],
                last_rejection_time=obj["last_rejection_time"],
                last_accept_time=obj["last_accept_time"],
                block_level=obj["block_level"],
                block_until=obj["block_until"],
                last_reset_date=obj["last_reset_date"],
                created_at=obj["created_at"],
                updated_at=obj["updated_at"],
                block_history=obj.get("block_history", []),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to deserialize spam stats: {e}")
            return None

    def _check_daily_reset(self, stats: SpamStats) -> bool:
        """
        Проверка необходимости сброса дневных счетчиков.

        Returns:
            True если был сброс.
        """
        today = self._get_today_date()
        if stats.last_reset_date != today:
            stats.rejections_today = 0
            stats.accepts_today = 0
            stats.last_reset_date = today
            return True
        return False

    def _update_block_level(self, stats: SpamStats) -> None:
        """
        Обновление уровня блокировки на основе количества отказов и истории.

        Алгоритм:
        - При 50+ отказах за день:
          - Если история блокировок пуста или последняя была level 1 и истекла → level 1
          - Если последняя блокировка была level 1 и еще активна → не блокируем повторно
          - Если была level 2 и истекла → level 2
          - Если была level 2 и активна → level 3
        """
        if stats.rejections_today >= MAX_REJECTIONS_PER_DAY:
            # Проверяем, не заблокирован ли уже
            if stats.block_level > 0 and stats.block_until and stats.block_until > time.time():
                # Уже заблокирован, не меняем уровень
                return

            # Подсчитываем количество предыдущих блокировок из истории
            previous_blocks = len(stats.block_history)

            if previous_blocks == 0:
                # Первая блокировка
                stats.block_level = 1
                stats.block_until = time.time() + BLOCK_LEVELS[1]["duration"]
                stats.block_history.append(1)
                logger.info(f"User {stats.user_id} blocked (level 1) until {stats.block_until}")
            elif previous_blocks == 1:
                # Вторая блокировка
                stats.block_level = 2
                stats.block_until = time.time() + BLOCK_LEVELS[2]["duration"]
                stats.block_history.append(2)
                logger.info(f"User {stats.user_id} blocked (level 2) until {stats.block_until}")
            elif previous_blocks >= 2:
                # Третья и последующие блокировки
                stats.block_level = 3
                stats.block_until = None
                if 3 not in stats.block_history:
                    stats.block_history.append(3)
                logger.info(f"User {stats.user_id} permanently banned (level 3)")

    def _load_stats(self, user_id: str) -> SpamStats:
        """Загрузка статистики пользователя."""
        key = self._make_key(user_id)
        raw = self._storage.get(key)

        if raw is None:
            now = time.time()
            today = self._get_today_date()
            return SpamStats(
                user_id=user_id,
                rejections_today=0,
                rejections_total=0,
                accepts_today=0,
                last_rejection_time=0,
                last_accept_time=0,
                block_level=0,
                block_until=None,
                last_reset_date=today,
                created_at=now,
                updated_at=now,
                block_history=[],
            )

        stats = self._deserialize(raw)
        if stats is None:
            # Если данные повреждены, создаем новые
            now = time.time()
            today = self._get_today_date()
            return SpamStats(
                user_id=user_id,
                rejections_today=0,
                rejections_total=0,
                accepts_today=0,
                last_rejection_time=0,
                last_accept_time=0,
                block_level=0,
                block_until=None,
                last_reset_date=today,
                created_at=now,
                updated_at=now,
                block_history=[],
            )

        return stats

    def _save_stats(self, stats: SpamStats) -> None:
        """Сохранение статистики пользователя."""
        stats.updated_at = time.time()
        key = self._make_key(stats.user_id)
        self._storage.put(key, self._serialize(stats))

    def record_rejection(self, user_id: str) -> Dict:
        """
        Фиксация отказа на приглашение.

        Args:
            user_id: Public ID отправителя.

        Returns:
            Словарь с информацией о результате.
        """
        stats = self._load_stats(user_id)

        # Проверяем дневной сброс
        self._check_daily_reset(stats)

        # Увеличиваем счетчики
        stats.rejections_today += 1
        stats.rejections_total += 1
        stats.last_rejection_time = time.time()

        # Проверяем блокировку
        self._update_block_level(stats)

        # Сохраняем
        self._save_stats(stats)

        return {
            "rejections_today": stats.rejections_today,
            "rejections_total": stats.rejections_total,
            "block_level": stats.block_level,
            "blocked": self.is_blocked(user_id),
            "block_until": stats.block_until,
            "message": BLOCK_LEVELS[stats.block_level]["message"],
        }

    def record_accept(self, user_id: str) -> Dict:
        """
        Фиксация принятия приглашения (сбрасывает счётчик отказов).

        Args:
            user_id: Public ID отправителя.

        Returns:
            Словарь с информацией о результате.
        """
        stats = self._load_stats(user_id)

        # Проверяем дневной сброс
        self._check_daily_reset(stats)

        # Увеличиваем счетчик принятий
        stats.accepts_today += 1
        stats.last_accept_time = time.time()

        # Сбрасываем счетчик отказов
        stats.rejections_today = 0

        # Если был заблокирован, но блокировка истекла — разблокируем
        if stats.block_level > 0 and stats.block_until and stats.block_until <= time.time():
            stats.block_level = 0
            stats.block_until = None
            logger.info(f"User {stats.user_id} unblocked after acceptance")

        self._save_stats(stats)

        return {
            "accepts_today": stats.accepts_today,
            "rejections_today": stats.rejections_today,
            "block_level": stats.block_level,
            "blocked": self.is_blocked(user_id),
        }

    def is_blocked(self, user_id: str) -> bool:
        """
        Проверка, заблокирован ли пользователь.

        Args:
            user_id: Public ID пользователя.

        Returns:
            True если заблокирован.
        """
        stats = self._load_stats(user_id)

        if stats.block_level == 0:
            return False

        if stats.block_level == 3:
            return True

        if stats.block_until and stats.block_until > time.time():
            return True

        return False

    def get_block_level(self, user_id: str) -> int:
        """
        Получение уровня блокировки.

        Args:
            user_id: Public ID пользователя.

        Returns:
            Уровень блокировки (0-3).
        """
        stats = self._load_stats(user_id)
        return stats.block_level

    def get_remaining_invites(self, user_id: str) -> int:
        """
        Получение количества оставшихся приглашений на сегодня.

        Args:
            user_id: Public ID пользователя.

        Returns:
            Оставшееся количество (0-50).
        """
        stats = self._load_stats(user_id)
        self._check_daily_reset(stats)

        remaining = MAX_REJECTIONS_PER_DAY - stats.rejections_today
        return max(0, remaining)

    def get_stats(self, user_id: str) -> Optional[Dict]:
        """
        Получение полной статистики пользователя.

        Args:
            user_id: Public ID пользователя.

        Returns:
            Словарь со статистикой или None.
        """
        stats = self._load_stats(user_id)
        self._check_daily_reset(stats)

        return {
            "user_id": stats.user_id,
            "rejections_today": stats.rejections_today,
            "rejections_total": stats.rejections_total,
            "accepts_today": stats.accepts_today,
            "last_rejection_time": stats.last_rejection_time,
            "last_accept_time": stats.last_accept_time,
            "block_level": stats.block_level,
            "block_until": stats.block_until,
            "block_history": stats.block_history,
            "remaining_invites": MAX_REJECTIONS_PER_DAY - stats.rejections_today,
            "created_at": stats.created_at,
            "updated_at": stats.updated_at,
        }

    def reset_user(self, user_id: str) -> None:
        """
        Сброс статистики пользователя (для администраторов).

        Сбрасывает только текущие счетчики, но сохраняет историю блокировок.

        Args:
            user_id: Public ID пользователя.
        """
        stats = self._load_stats(user_id)

        # Сбрасываем текущие счетчики
        stats.rejections_today = 0
        stats.accepts_today = 0
        stats.block_level = 0
        stats.block_until = None
        stats.last_reset_date = self._get_today_date()
        stats.last_rejection_time = 0
        stats.last_accept_time = 0
        # История блокировок сохраняется!

        self._save_stats(stats)
        logger.info(f"User {user_id} stats reset by admin (block history preserved)")
