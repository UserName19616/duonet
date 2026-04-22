# src/common/identity/recovery.py
"""
Модуль восстановления пароля.

Позволяет пользователю сбросить пароль, если в сид-фразе 1 указан email.
Email НЕ хранится в системе, только хеш.
"""

import secrets
import smtplib
import time
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any, Dict, Optional, Tuple

from ..crypto.keys import hash_sha256
from ..storage.sqlite import SQLiteStorage

# Константы
RECOVERY_TOKEN_TTL_SECONDS = 900  # 15 минут
RECOVERY_RATE_LIMIT = 3  # попыток в час
RECOVERY_RATE_PERIOD_SECONDS = 3600  # 1 час


class EmailSender(ABC):
    """Абстрактный класс для отправки email."""

    @abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> bool:
        """
        Отправка email.

        Args:
            to_email: Email получателя.
            subject: Тема письма.
            body: Текст письма.

        Returns:
            True если отправка успешна.
        """
        pass


class ConsoleEmailSender(EmailSender):
    """Реализация EmailSender для разработки (логирование в консоль)."""

    def send(self, to_email: str, subject: str, body: str) -> bool:
        """Вывод письма в консоль."""
        print(f"\n[EMAIL] To: {to_email}")
        print(f"[EMAIL] Subject: {subject}")
        print(f"[EMAIL] Body:\n{body}\n")
        return True


class SmtpEmailSender(EmailSender):
    """Реализация EmailSender через SMTP."""

    def __init__(self, config: Dict[str, Any]):
        """
        Инициализация SMTP отправителя.

        Args:
            config: Словарь с настройками SMTP:
                - server: SMTP сервер
                - port: порт (обычно 587)
                - username: имя пользователя
                - password: пароль
                - from_email: email отправителя
                - use_tls: использовать TLS (по умолчанию True)
        """
        self.config = config

    def send(self, to_email: str, subject: str, body: str) -> bool:
        """Отправка через SMTP."""
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg["Subject"] = subject
            msg["From"] = self.config["from_email"]
            msg["To"] = to_email

            with smtplib.SMTP(
                self.config["server"], self.config["port"]
            ) as server:
                if self.config.get("use_tls", True):
                    server.starttls()
                server.login(
                    self.config["username"], self.config["password"]
                )
                server.send_message(msg)
            return True
        except Exception:
            return False


class NullEmailSender(EmailSender):
    """Реализация EmailSender, которая ничего не делает."""

    def send(self, to_email: str, subject: str, body: str) -> bool:
        """Ничего не отправляет."""
        return True


class RecoveryService:
    """
    Сервис восстановления пароля.

    Управляет сбросом пароля через email.
    """

    def __init__(
        self,
        storage: SQLiteStorage,
        account_manager: Any,
        email_sender: Optional[EmailSender] = None,
    ):
        """
        Инициализация сервиса восстановления.

        Args:
            storage: Экземпляр хранилища SQLite.
            account_manager: Менеджер аккаунтов.
            email_sender: Отправитель email (если None, используется ConsoleEmailSender).
        """
        self._storage = storage
        self._account_manager = account_manager
        self._email_sender = email_sender or ConsoleEmailSender()

        # Счетчики rate limiting (in-memory)
        self._recovery_attempts: Dict[str, list] = {}  # email -> list of timestamps

        # Инициализация таблицы
        self._init_db()

    def _init_db(self) -> None:
        """Инициализация таблицы recovery_tokens."""
        self._storage.execute_sql("""
            CREATE TABLE IF NOT EXISTS recovery_tokens (
                token TEXT PRIMARY KEY,
                account_id BLOB NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_recovery_tokens_account_id
            ON recovery_tokens(account_id)
        """)
        self._storage.execute_sql("""
            CREATE INDEX IF NOT EXISTS idx_recovery_tokens_expires_at
            ON recovery_tokens(expires_at)
        """)

    @staticmethod
    def extract_email_from_seed(seed_phrase: str) -> Optional[str]:
        """
        Извлечение email из сид-фразы 1.

        Правила:
          - Email должен быть в начале строки (с пробелом после)
          - ИЛИ в конце строки (с пробелом перед)
          - ИЛИ являться всей строкой

        Args:
            seed_phrase: Сид-фраза 1.

        Returns:
            Извлеченный email или None.
        """
        import re

        # Простое регулярное выражение для email
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

        # Проверяем, что вся строка — email
        if re.fullmatch(email_pattern, seed_phrase.strip()):
            return seed_phrase.strip()

        # Проверяем начало строки (email + пробел + текст)
        match = re.match(rf"^{email_pattern}\s+", seed_phrase)
        if match:
            return match.group(0).strip()

        # Проверяем конец строки (текст + пробел + email)
        match = re.search(rf"\s+({email_pattern})$", seed_phrase)
        if match:
            return match.group(1)

        return None

    def setup_recovery(
        self, seed_phrase: str, account_id: bytes
    ) -> Tuple[bool, Optional[str]]:
        """
        Настройка восстановления для аккаунта.

        Args:
            seed_phrase: Сид-фраза 1.
            account_id: ID аккаунта.

        Returns:
            (успех, извлеченный_email или None)
        """
        email = self.extract_email_from_seed(seed_phrase)
        if not email:
            return False, None

        # Сохраняем хеш email
        email_hash = hash_sha256(email.encode("utf-8")).hex()
        self._storage.execute_sql(
            "UPDATE accounts SET recovery_email_hash = ? WHERE account_id = ?",
            (email_hash, account_id),
        )
        return True, email

    def _check_rate_limit(self, email: str) -> bool:
        """
        Проверка rate limiting для восстановления.

        Args:
            email: Email для проверки.

        Returns:
            True если лимит не превышен.
        """
        now = time.time()
        cutoff = now - RECOVERY_RATE_PERIOD_SECONDS

        attempts = self._recovery_attempts.get(email, [])
        # Удаляем устаревшие
        attempts = [ts for ts in attempts if ts >= cutoff]
        self._recovery_attempts[email] = attempts

        return len(attempts) < RECOVERY_RATE_LIMIT

    def _record_attempt(self, email: str) -> None:
        """Запись попытки восстановления."""
        now = time.time()
        if email not in self._recovery_attempts:
            self._recovery_attempts[email] = []
        self._recovery_attempts[email].append(now)

    def request_recovery(self, email: str) -> bool:
        """
        Запрос на восстановление пароля.

        Всегда возвращает True для безопасности.

        Args:
            email: Email для восстановления.

        Returns:
            True всегда (для безопасности).
        """
        # Rate limiting
        if not self._check_rate_limit(email):
            return True

        self._record_attempt(email)

        # Ищем аккаунт по хешу email
        email_hash = hash_sha256(email.encode("utf-8")).hex()
        cursor = self._storage.execute_sql(
            "SELECT account_id FROM accounts WHERE recovery_email_hash = ?",
            (email_hash,),
        )
        row = cursor.fetchone()
        if not row:
            return True  # Для безопасности

        account_id = row[0]

        # Генерируем токен
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + RECOVERY_TOKEN_TTL_SECONDS

        # Сохраняем токен
        self._storage.execute_sql(
            """
            INSERT OR REPLACE INTO recovery_tokens (token, account_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, account_id, expires_at, now),
        )

        # Отправляем email
        api_base_url = "http://localhost:8000"  # из конфига
        body = (
            f"Для восстановления пароля перейдите по ссылке:\n\n"
            f"{api_base_url}/api/auth/recovery/reset?token={token}\n\n"
            f"Ссылка действительна {RECOVERY_TOKEN_TTL_SECONDS // 60} минут."
        )

        self._email_sender.send(
            to_email=email,
            subject="DuoNet — восстановление пароля",
            body=body,
        )

        return True

    def verify_token(self, token: str) -> Optional[bytes]:
        """
        Проверка токена восстановления.

        Args:
            token: Токен из ссылки.

        Returns:
            account_id или None.
        """
        now = int(time.time())
        cursor = self._storage.execute_sql(
            """
            SELECT account_id, expires_at FROM recovery_tokens
            WHERE token = ? AND expires_at > ?
            """,
            (token, now),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return row[0]

    def reset_password(self, token: str, new_password: str) -> bool:
        """
        Сброс пароля по токену.

        Args:
            token: Токен восстановления.
            new_password: Новый пароль (минимум 8 символов).

        Returns:
            True если пароль изменен.
        """
        account_id = self.verify_token(token)
        if not account_id:
            return False

        # Меняем пароль
        # Используем пустой старый пароль, так как это сброс
        success = self._account_manager.change_password(
            account_id, "", new_password
        )
        if not success:
            return False

        # Удаляем использованный токен
        self._storage.execute_sql(
            "DELETE FROM recovery_tokens WHERE token = ?", (token,)
        )
        return True

    def get_recovery_email_hash(self, account_id: bytes) -> Optional[str]:
        """
        Получение хеша email для аккаунта.

        Args:
            account_id: ID аккаунта.

        Returns:
            Хеш email или None.
        """
        cursor = self._storage.execute_sql(
            "SELECT recovery_email_hash FROM accounts WHERE account_id = ?",
            (account_id,),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None

    def is_recovery_configured(self, account_id: bytes) -> bool:
        """
        Проверка, настроено ли восстановление.

        Args:
            account_id: ID аккаунта.

        Returns:
            True если восстановление настроено.
        """
        return self.get_recovery_email_hash(account_id) is not None

    def cleanup_expired_tokens(self) -> int:
        """
        Очистка истекших токенов.

        Returns:
            Количество удаленных токенов.
        """
        now = int(time.time())
        cursor = self._storage.execute_sql(
            "DELETE FROM recovery_tokens WHERE expires_at <= ?", (now,)
        )
        return cursor.rowcount
