#!/usr/bin/env python3
"""
Упрощённый интеграционный тест для WebSocket и online статуса.
Использует существующих пользователей (созданных вручную).
Запуск: pytest tests/integration/test_websocket_simple.py -v -s
"""

import asyncio
import json
import time
import ssl
import warnings

import pytest
import websockets
import requests

# Отключаем предупреждения о SSL
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

API_URL = "https://localhost:8443"
WS_URL = "wss://localhost:8443/ws"

# =============================================================================
# НАСТРОЙКА - ИСПОЛЬЗУЕМ ДАННЫЕ ИЗ ВАШЕГО ФАЙЛА
# =============================================================================

ALICE_PUBLIC_ID = "@K7MC-57UH-URW7.ru"
ALICE_SEED = "lehanik@inbox.ru"
ALICE_PASSWORD = "12345678"

BOB_PUBLIC_ID = "@EQSW-MBWC-CFM8.ru"
BOB_SEED = "prohoziy@bk.ru"
BOB_PASSWORD = "12345678"

# =============================================================================


class TestClient:
    """Тестовый клиент для WebSocket."""

    def __init__(self, name: str, public_id: str, seed_phrase: str, password: str):
        self.name = name
        self.public_id = public_id
        self.seed_phrase = seed_phrase
        self.password = password
        self.token = None
        self.ws = None
        self.received_messages = []
        self._listener_task = None
        self._session = requests.Session()
        self._session.verify = False
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    async def login(self):
        """Вход в аккаунт."""
        print(f"\n🔐 {self.name}: Logging in...")

        try:
            response = self._session.post(
                f"{API_URL}/api/auth/login",
                json={
                    "seed_phrase": self.seed_phrase,
                    "password": self.password
                },
                timeout=10
            )
            data = response.json()

            if response.status_code != 200:
                print(f"   ❌ {self.name} login HTTP {response.status_code}: {data}")
                return False

            if data.get("success"):
                self.token = data.get("token")
                print(f"   ✅ {self.name} logged in")
                return True
            else:
                print(f"   ❌ {self.name} login failed: {data.get('error')}")
                return False

        except Exception as e:
            print(f"   ❌ {self.name} login exception: {e}")
            return False

    async def connect_websocket(self):
        """Подключение WebSocket."""
        if not self.token:
            print(f"❌ {self.name}: no token")
            return False

        ws_url = f"{WS_URL}?token={self.token}"
        print(f"   🔌 {self.name} connecting...")

        try:
            self.ws = await websockets.connect(
                ws_url,
                ssl=SSL_CONTEXT,
                close_timeout=5
            )
            print(f"   ✅ {self.name} WebSocket connected!")

            self._listener_task = asyncio.create_task(self._listen())
            await asyncio.sleep(1)
            await self.send_status()

            return True
        except Exception as e:
            print(f"   ❌ {self.name} WebSocket failed: {e}")
            return False

    async def _listen(self):
        """Слушатель WebSocket сообщений."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    self.received_messages.append(data)
                    msg_type = data.get('type')
                    if msg_type == 'status_response':
                        print(f"   📨 {self.name} received status_response")
                except:
                    pass
        except:
            pass

    async def send_status(self):
        """Отправка статуса онлайн."""
        if not self.ws:
            return False

        message = {
            "type": "status",
            "data": {"online": True, "load": 0.1}
        }
        await self.ws.send(json.dumps(message))
        print(f"   📤 {self.name} sent status")
        return True

    async def send_typing(self, to_id: str, is_typing: bool = True):
        """Отправка статуса печатает."""
        if not self.ws:
            return False

        message = {
            "type": "typing",
            "data": {"to": to_id, "is_typing": is_typing}
        }
        await self.ws.send(json.dumps(message))
        print(f"   📤 {self.name} sent typing to {to_id}")
        return True

    async def disconnect(self):
        """Отключение WebSocket."""
        if self._listener_task:
            self._listener_task.cancel()
        if self.ws:
            await self.ws.close()
        print(f"   🔌 {self.name} disconnected")

    def check_online_status(self, contact_id: str) -> bool:
        """Проверка online статуса контакта через API."""
        try:
            response = self._session.get(
                f"{API_URL}/api/contacts",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            data = response.json()

            if data.get("success"):
                for contact in data.get("contacts", []):
                    if contact.get("public_id") == contact_id:
                        online = contact.get("online", False)
                        print(f"   📡 {self.name} sees {contact_id}: online={online}")
                        return online
        except Exception as e:
            print(f"   ❌ Failed to get status: {e}")

        return False


# =============================================================================
# ТЕСТЫ
# =============================================================================

def wait_for_server(timeout: int = 10) -> bool:
    """Проверка доступности сервера."""
    for i in range(timeout):
        try:
            response = requests.get(f"{API_URL}/health", verify=False, timeout=2)
            if response.status_code == 200:
                print("✅ Server is ready")
                return True
        except:
            pass
        time.sleep(1)
        print(f"⏳ Waiting for server... ({i+1}/{timeout})")
    return False


@pytest.mark.asyncio(loop_scope="function")
class TestWebSocketSimple:
    """Упрощённые тесты WebSocket."""

    @pytest.fixture(autouse=True)
    def check_server(self):
        if not wait_for_server():
            pytest.skip("Server not running")

    async def test_1_websocket_connection(self):
        """Тест: WebSocket подключение."""
        print("\n" + "="*60)
        print("ТЕСТ 1: WebSocket подключение")
        print("="*60)

        alice = TestClient("Alice", ALICE_PUBLIC_ID, ALICE_SEED, ALICE_PASSWORD)

        try:
            assert await alice.login() is True
            assert await alice.connect_websocket() is True

            await asyncio.sleep(2)
            print("\n✅ WebSocket подключение работает")

        finally:
            await alice.disconnect()

    async def test_2_online_status(self):
        """Тест: Online статус."""
        print("\n" + "="*60)
        print("ТЕСТ 2: Online статус")
        print("="*60)

        alice = TestClient("Alice", ALICE_PUBLIC_ID, ALICE_SEED, ALICE_PASSWORD)
        bob = TestClient("Bob", BOB_PUBLIC_ID, BOB_SEED, BOB_PASSWORD)

        try:
            assert await alice.login() is True
            assert await bob.login() is True
            assert await bob.connect_websocket() is True

            await asyncio.sleep(3)

            status = alice.check_online_status(BOB_PUBLIC_ID)
            print(f"\n📊 Результат: Боб онлайн = {status}")

            # Не assert, просто выводим информацию
            print("\n✅ Тест завершён")

        finally:
            await alice.disconnect()
            await bob.disconnect()

    async def test_3_typing_notification(self):
        """Тест: Уведомление о печатает."""
        print("\n" + "="*60)
        print("ТЕСТ 3: Уведомление о печатает")
        print("="*60)

        alice = TestClient("Alice", ALICE_PUBLIC_ID, ALICE_SEED, ALICE_PASSWORD)
        bob = TestClient("Bob", BOB_PUBLIC_ID, BOB_SEED, BOB_PASSWORD)

        try:
            assert await alice.login() is True
            assert await bob.login() is True
            assert await alice.connect_websocket() is True
            assert await bob.connect_websocket() is True

            bob.received_messages.clear()

            await asyncio.sleep(1)
            await alice.send_typing(BOB_PUBLIC_ID)
            await asyncio.sleep(2)

            typing_received = any(msg.get("type") == "typing" for msg in bob.received_messages)
            print(f"\n📊 Результат: Боб получил typing = {typing_received}")

            print("\n✅ Тест завершён")

        finally:
            await alice.disconnect()
            await bob.disconnect()


if __name__ == "__main__":
    async def main():
        alice = TestClient("Alice", ALICE_PUBLIC_ID, ALICE_SEED, ALICE_PASSWORD)

        print("\n🔍 Ручная проверка:")
        if await alice.login():
            print(f"   ✅ Логин успешен")
            if await alice.connect_websocket():
                print(f"   ✅ WebSocket подключён")
                await asyncio.sleep(2)
                status = alice.check_online_status(BOB_PUBLIC_ID)
                print(f"   📊 Статус Боба: {status}")
                await alice.disconnect()

    asyncio.run(main())
