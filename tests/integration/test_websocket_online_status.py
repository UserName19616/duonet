#!/usr/bin/env python3
"""
Интеграционный тест для проверки WebSocket и online статуса.
Использует ОДНУ пару пользователей для всех тестов.
"""

import asyncio
import json
import time
import uuid
import os

import pytest
import websockets
import requests

import ssl
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

API_URL = "https://localhost:8443"
WS_URL = "wss://localhost:8443/ws"


def wait_for_server(timeout: int = 30) -> bool:
    """Ожидание готовности сервера."""
    for i in range(timeout):
        try:
            response = requests.get(f"{API_URL}/health", verify=False, timeout=2)
            if response.status_code == 200:
                print("✅ Server is ready")
                return True
        except:
            pass
        time.sleep(1)
    return False


def cleanup_database():
    """Очистка базы данных."""
    db_path = "duonet.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print(f"✅ Removed database: {db_path}")
            return True
        except Exception as e:
            print(f"❌ Failed to remove database: {e}")
    return False


class TestClient:
    """Тестовый клиент для WebSocket."""

    def __init__(self, name: str, seed_phrase: str = None):
        self.name = name
        self.seed_phrase = seed_phrase or f"{name.lower()}_test_user"
        self.password = "test123456"
        self.public_id = None
        self.token = None
        self.ws = None
        self.received_messages = []
        self._listener_task = None

    async def register(self):
        """Регистрация."""
        response = requests.post(
            f"{API_URL}/api/auth/register",
            json={
                "seed_phrase": self.seed_phrase,
                "password": self.password,
                "region": "ru",
                "is_server": False
            },
            verify=False
        )
        data = response.json()
        if data.get("success"):
            self.public_id = data.get("public_id")
            print(f"✅ {self.name} registered: {self.public_id}")
            return True
        else:
            print(f"❌ {self.name} registration failed: {data}")
            return False

    async def login(self):
        """Вход."""
        response = requests.post(
            f"{API_URL}/api/auth/login",
            json={
                "seed_phrase": self.seed_phrase,
                "password": self.password
            },
            verify=False
        )
        data = response.json()
        if data.get("success"):
            self.token = data.get("token")
            print(f"✅ {self.name} logged in")
            return True
        else:
            print(f"❌ {self.name} login failed: {data}")
            return False

    async def connect_websocket(self):
        """Подключение WebSocket."""
        if not self.token:
            print(f"❌ {self.name}: no token")
            return False

        ws_url = f"{WS_URL}?token={self.token}"

        try:
            self.ws = await websockets.connect(
                ws_url,
                ssl=SSL_CONTEXT,
                close_timeout=5
            )
            print(f"✅ {self.name} WebSocket connected")

            self._listener_task = asyncio.create_task(self._listen())
            await asyncio.sleep(1)
            await self.send_status()

            return True
        except Exception as e:
            print(f"❌ {self.name} WebSocket connection failed: {e}")
            return False

    async def _listen(self):
        """Слушатель WebSocket сообщений."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    self.received_messages.append(data)
                    print(f"📨 {self.name} received: {data.get('type')}")
                except:
                    pass
        except:
            pass

    async def send_typing(self, to_id: str, is_typing: bool = True):
        """Отправка статуса печатает."""
        if not self.ws:
            return False
        message = {"type": "typing", "data": {"to": to_id, "is_typing": is_typing}}
        await self.ws.send(json.dumps(message))
        print(f"📤 {self.name} sent typing to {to_id}")
        return True

    async def send_status(self):
        """Отправка статуса."""
        if not self.ws:
            return False
        message = {"type": "status", "data": {"online": True, "load": 0.1}}
        await self.ws.send(json.dumps(message))
        print(f"📤 {self.name} sent status")
        return True

    async def disconnect(self):
        """Отключение WebSocket."""
        if self._listener_task:
            self._listener_task.cancel()
        if self.ws:
            await self.ws.close()
        print(f"🔌 {self.name} disconnected")

    def get_online_status(self, contact_id: str) -> bool:
        """Проверка online статуса через API."""
        try:
            response = requests.get(
                f"{API_URL}/api/contacts",
                headers={"Authorization": f"Bearer {self.token}"},
                verify=False
            )
            data = response.json()
            if data.get("success"):
                for contact in data.get("contacts", []):
                    if contact.get("public_id") == contact_id:
                        return contact.get("online", False)
        except:
            pass
        return False

    async def send_rotation_request(self, to_id: str, request_id: str):
        """Отправка запроса на ротацию ключа."""
        if not self.ws:
            return False
        message = {"type": "rotation_request", "data": {"to": to_id, "request_id": request_id, "timestamp": int(time.time())}}
        await self.ws.send(json.dumps(message))
        return True

    async def send_rotation_ack(self, to_id: str, request_id: str):
        """Отправка подтверждения ротации."""
        if not self.ws:
            return False
        message = {"type": "rotation_ack", "data": {"to": to_id, "request_id": request_id}}
        await self.ws.send(json.dumps(message))
        return True


# =============================================================================
# Тесты - используем ОДНУ пару пользователей для всех тестов
# =============================================================================

@pytest.mark.asyncio(loop_scope="function")
class TestWebSocketOnlineStatus:
    """Интеграционные тесты WebSocket и online статуса."""

    @classmethod
    def setup_class(cls):
        """Очистка перед всеми тестами."""
        print("\n🧹 Setting up test environment...")
        cleanup_database()
        wait_for_server()

    async def test_1_register_users(self):
        """Тест 1: Регистрация пользователей (один раз)."""
        global alice, bob

        alice = TestClient("Alice", "alice_permanent")
        bob = TestClient("Bob", "bob_permanent")

        assert await alice.register() is True
        assert await alice.login() is True
        assert await bob.register() is True
        assert await bob.login() is True

        # Добавляем в контакты
        requests.post(
            f"{API_URL}/api/contacts/add",
            headers={"Authorization": f"Bearer {alice.token}"},
            json={"public_id": bob.public_id},
            verify=False
        )
        requests.post(
            f"{API_URL}/api/contacts/add",
            headers={"Authorization": f"Bearer {bob.token}"},
            json={"public_id": alice.public_id},
            verify=False
        )

        print("✅ Users registered and added as contacts")

    async def test_2_websocket_connection(self):
        """Тест 2: WebSocket подключение."""
        assert await alice.connect_websocket() is True
        assert alice.ws is not None
        assert not alice.ws.closed

        assert await bob.connect_websocket() is True
        assert bob.ws is not None
        assert not bob.ws.closed

        print("✅ WebSocket connection test passed")

    async def test_3_online_status(self):
        """Тест 3: online статус."""
        await asyncio.sleep(2)

        status = alice.get_online_status(bob.public_id)
        print(f"Bob online status from Alice: {status}")
        assert status is True, f"Expected online=True, got {status}"

        print("✅ Online status test passed")

    async def test_4_typing_notification(self):
        """Тест 4: уведомление о печатает."""
        alice.received_messages.clear()
        bob.received_messages.clear()

        await alice.send_typing(bob.public_id, is_typing=True)
        await asyncio.sleep(2)

        typing_received = any(msg.get("type") == "typing" for msg in bob.received_messages)
        assert typing_received is True

        print("✅ Typing notification test passed")

    async def test_5_rotation_request(self):
        """Тест 5: запрос на ротацию ключа."""
        alice.received_messages.clear()
        bob.received_messages.clear()

        request_id = "test_" + str(uuid.uuid4())[:8]
        await alice.send_rotation_request(bob.public_id, request_id)
        await asyncio.sleep(2)

        rotation_received = any(msg.get("type") == "rotation_request" for msg in bob.received_messages)
        assert rotation_received is True

        if rotation_received:
            await bob.send_rotation_ack(alice.public_id, request_id)

        print("✅ Rotation request test passed")

    @classmethod
    def teardown_class(cls):
        """Очистка после тестов."""
        async def cleanup():
            if 'alice' in globals():
                await alice.disconnect()
            if 'bob' in globals():
                await bob.disconnect()

        asyncio.run(cleanup())
        print("\n🧹 Test cleanup completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
