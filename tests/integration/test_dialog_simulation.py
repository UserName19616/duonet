# tests/integration/test_dialog_simulation.py
"""
Интеграционный тест для имитации диалога между двумя пользователями.
Использует существующие аккаунты из БД.
Запуск: pytest tests/integration/test_dialog_simulation.py -v -s
"""

import os
import sys
import time
import asyncio
import pytest
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.identity.account import AccountManager
from src.messaging.message_router import MessageRouter
from src.messaging.invite import InviteProtocol
from src.messaging.spam_protection import SpamProtection
from src.network.rate_limiter import MultiRateLimiter
from src.network.geoip import get_region_by_ip
from src.storage.sqlite import SQLiteStorage
from src.storage.messages import MessagesStorage
from src.client.crypto import ClientCrypto
from tests.unit.mock_ws_manager import MockWebSocketManager


# =============================================================================
# Конфигурация пользователей (ЗАМЕНИТЕ НА СВОИ ДАННЫЕ!)
# =============================================================================

USER_A = {
    "public_id": "@EQSW-MBWC-CFM8.ru",  # Замените на реальный Public ID
    "seed_phrase": "prohoziy@bk.ru",  # Замените
    "password": "12345678",  # Замените
}

USER_B = {
    "public_id": "@K7MC-57UH-URW7.ru",  # Замените на реальный Public ID
    "seed_phrase": "lehanik@inbox.ru",  # Замените
    "password": "12345678",  # Замените
}

# Дополнительная фраза для защиты
SECRET_PHRASE = "123"

# Путь к файлу с диалогом
DIALOG_FILE = Path(__file__).parent.parent / "data" / "test_dialog.txt"


def mock_geoip(ip):
    return "ru"


def parse_dialog_file(file_path: Path) -> list:
    """
    Парсит файл с диалогом.

    Returns:
        list of dict: [{"sender": "A" or "B", "text": "...", "has_phrase": bool}]
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Dialog file not found: {file_path}")

    messages = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Формат: [P] A: Текст сообщения
            # или [N] B: Текст сообщения
            if line.startswith("[P]") or line.startswith("[N]"):
                flag = line[1]  # P или N
                rest = line[4:]  # пропускаем "[P] " или "[N] "

                # Извлекаем отправителя
                if rest.startswith("A:"):
                    sender = "A"
                    text = rest[2:].strip()
                elif rest.startswith("B:"):
                    sender = "B"
                    text = rest[2:].strip()
                else:
                    continue

                messages.append({
                    "sender": sender,
                    "text": text,
                    "has_phrase": (flag == "P"),
                })

    return messages


class DialogSimulator:
    """Симулятор диалога между двумя пользователями."""

    def __init__(self, user_a: dict, user_b: dict, secret_phrase: str = None):
        self.user_a = user_a
        self.user_b = user_b
        self.secret_phrase = secret_phrase

        # Инициализация хранилища
        self.storage = SQLiteStorage("duonet.db")

        # Rate limiter
        self.rate_limiter = MultiRateLimiter()

        # WebSocket manager (mock)
        self.ws_manager = MockWebSocketManager()

        # Account manager
        self.account_manager = AccountManager(
            storage=self.storage,
            geoip_func=mock_geoip,
            rate_limiter=self.rate_limiter,
            jwt_secret="test_secret",
            ws_manager=self.ws_manager,
        )

        # Spam protection
        self.spam_protection = SpamProtection(self.storage)

        # Invite protocol
        self.invite_protocol = InviteProtocol(
            self.spam_protection,
            storage=self.storage,
            server_db=None,
        )

        # Messages storage
        self.messages_storage = MessagesStorage("duonet.db")

        # Message routers для каждого пользователя
        self.router_a = MessageRouter(
            account_manager=self.account_manager,
            messages_storage=self.messages_storage,
            invite_protocol=self.invite_protocol,
            ws_manager=self.ws_manager,
            storage=self.storage,
        )

        self.router_b = MessageRouter(
            account_manager=self.account_manager,
            messages_storage=self.messages_storage,
            invite_protocol=self.invite_protocol,
            ws_manager=self.ws_manager,
            storage=self.storage,
        )

        # Состояние диалога
        self.session_key = None
        self._counter_a = 0
        self._counter_b = 0
        self._last_padding_a = 0
        self._last_padding_b = 0

    def _get_session_key(self) -> bytes:
        """Получение session_key из БД."""
        import sqlite3
        conn = sqlite3.connect("duonet.db")
        cursor = conn.execute(
            "SELECT session_key FROM dialogs WHERE user_id = ? AND contact_id = ?",
            (self.user_a["public_id"], self.user_b["public_id"])
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return bytes.fromhex(row[0])
        return None

    def send_message(self, from_user: dict, to_user: dict, text: str, has_phrase: bool = False) -> dict:
        """Отправка сообщения от одного пользователя другому."""

        # Получаем session_key если ещё нет
        if self.session_key is None:
            self.session_key = self._get_session_key()
            if self.session_key is None:
                return {"success": False, "error": "No session key found"}

        # Определяем направление
        if from_user["public_id"] == self.user_a["public_id"]:
            from_id = self.user_a["public_id"]
            to_id = self.user_b["public_id"]
            counter = self._counter_a
            prev_padding = self._last_padding_a
        else:
            from_id = self.user_b["public_id"]
            to_id = self.user_a["public_id"]
            counter = self._counter_b
            prev_padding = self._last_padding_b

        phrase = self.secret_phrase if has_phrase else None

        # Шифруем сообщение
        try:
            encrypted, padding_size = ClientCrypto.encrypt_message_with_padding(
                plaintext=text,
                session_key=self.session_key,
                from_id=from_id,
                to_id=to_id,
                message_counter=counter,
                prev_padding=prev_padding,
                phrase=phrase,
            )
        except Exception as e:
            return {"success": False, "error": f"Encryption failed: {e}"}

        # Сохраняем состояние
        if from_user["public_id"] == self.user_a["public_id"]:
            self._last_padding_a = padding_size
            self._counter_a += 1
        else:
            self._last_padding_b = padding_size
            self._counter_b += 1

        # Отправляем через роутер
        result = self.router_a.send_encrypted_message(
            from_id=from_id,
            to_id=to_id,
            encrypted_hex=encrypted.hex(),
            session_key=self.session_key,
            has_phrase=has_phrase,
            phrase=phrase,
            plaintext_len=len(text),
            prev_padding=prev_padding,
            message_counter=counter,
        )

        return result

    def simulate_dialog(self, messages: list) -> dict:
        """Симуляция всего диалога."""
        results = {
            "total": len(messages),
            "sent": 0,
            "failed": 0,
            "errors": [],
        }

        print(f"\n{'='*60}")
        print(f"Начинаем симуляцию диалога ({len(messages)} сообщений)")
        print(f"{'='*60}\n")

        for i, msg in enumerate(messages, 1):
            sender = msg["sender"]
            text = msg["text"]
            has_phrase = msg["has_phrase"]

            # Выбираем пользователя
            if sender == "A":
                from_user = self.user_a
                to_user = self.user_b
                sender_name = "A"
            else:
                from_user = self.user_b
                to_user = self.user_a
                sender_name = "B"

            # Отправляем
            result = self.send_message(from_user, to_user, text, has_phrase)

            if result.get("success"):
                results["sent"] += 1
                phrase_mark = "[P]" if has_phrase else "[N]"
                print(f"  {i:3d}. {phrase_mark} {sender_name}: {text[:50]}{'...' if len(text) > 50 else ''}")
            else:
                results["failed"] += 1
                results["errors"].append({
                    "index": i,
                    "sender": sender_name,
                    "text": text[:50],
                    "error": result.get("error"),
                })
                print(f"  {i:3d}. ❌ Ошибка: {result.get('error')}")

            # Небольшая задержка между сообщениями
            time.sleep(0.1)

        print(f"\n{'='*60}")
        print(f"Результаты: отправлено {results['sent']}/{results['total']}")
        if results["failed"] > 0:
            print(f"Ошибок: {results['failed']}")
            for err in results["errors"]:
                print(f"  - Сообщение {err['index']}: {err['error']}")
        print(f"{'='*60}\n")

        return results


@pytest.mark.integration
class TestDialogSimulation:
    """Тест симуляции диалога."""

    def test_simulate_dialog(self):
        """Основной тест: симуляция диалога из файла."""

        # Проверяем, что файл с диалогом существует
        assert DIALOG_FILE.exists(), f"Dialog file not found: {DIALOG_FILE}"

        # Парсим диалог
        messages = parse_dialog_file(DIALOG_FILE)
        assert len(messages) > 0, "No messages in dialog file"

        print(f"\nЗагружено {len(messages)} сообщений из файла")

        # Создаём симулятор
        simulator = DialogSimulator(USER_A, USER_B, SECRET_PHRASE)

        # Симулируем диалог
        results = simulator.simulate_dialog(messages)

        # Проверяем результат
        assert results["failed"] == 0, f"Failed to send {results['failed']} messages"
        assert results["sent"] == results["total"], "Not all messages were sent"

        print("\n✅ Диалог успешно отправлен!")
        print("Теперь вы можете зайти в браузер и проверить:")
        print("  1. Все сообщения отобразились")
        print("  2. Сообщения с флагом [P] защищены фразой '123'")
        print("  3. При вводе фразы '123' сообщения расшифровываются")


if __name__ == "__main__":
    # Запуск без pytest
    test = TestDialogSimulation()
    test.test_simulate_dialog()
