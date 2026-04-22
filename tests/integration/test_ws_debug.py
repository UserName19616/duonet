# test_ws_detailed.py
#!/usr/bin/env python3
"""
Детальная диагностика WebSocket аутентификации
"""

import asyncio
import websockets
import requests
import ssl
import json

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

API_URL = "https://localhost:8443"
WS_URL = "wss://localhost:8443/ws"

async def main():
    print("=" * 60)
    print("ДИАГНОСТИКА WEBSOCKET")
    print("=" * 60)

    # 1. Регистрация
    print("\n1. Регистрация...")
    reg_response = requests.post(
        f"{API_URL}/api/auth/register",
        json={
            "seed_phrase": "ws_debug_user",
            "password": "test123456",
            "region": "ru",
            "is_server": False
        },
        verify=False
    )
    print(f"   Status: {reg_response.status_code}")
    reg_data = reg_response.json()
    print(f"   Response: {reg_data}")

    if not reg_data.get("success"):
        print("❌ Регистрация не удалась")
        return

    # 2. Логин
    print("\n2. Логин...")
    login_response = requests.post(
        f"{API_URL}/api/auth/login",
        json={
            "seed_phrase": "ws_debug_user",
            "password": "test123456"
        },
        verify=False
    )
    print(f"   Status: {login_response.status_code}")
    login_data = login_response.json()
    print(f"   Response: {login_data}")

    if not login_data.get("success"):
        print("❌ Логин не удался")
        return

    token = login_data["token"]
    public_id = login_data["public_id"]
    print(f"   Token: {token[:50]}...")
    print(f"   Public ID: {public_id}")

    # 3. Проверка токена через API
    print("\n3. Проверка токена через API...")
    verify_response = requests.get(
        f"{API_URL}/api/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
        verify=False
    )
    print(f"   Status: {verify_response.status_code}")
    print(f"   Response: {verify_response.json()}")

    # 4. WebSocket подключение с разными вариантами
    print("\n4. WebSocket подключение...")

    # Вариант 1: токен в URL
    ws_url_1 = f"{WS_URL}?token={token}"
    print(f"\n   Вариант 1 (токен в URL): {ws_url_1[:80]}...")

    try:
        async with websockets.connect(ws_url_1, ssl=SSL_CONTEXT, close_timeout=5) as ws:
            print("   ✅ WebSocket connected!")
            await ws.send(json.dumps({"type": "status", "data": {"online": True}}))
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"   📨 Received: {response}")
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"   ❌ HTTP {e.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Вариант 2: токен в заголовке (если поддерживается)
    ws_url_2 = WS_URL
    print(f"\n   Вариант 2 (токен в заголовке): {ws_url_2}")

    try:
        async with websockets.connect(
            ws_url_2,
            ssl=SSL_CONTEXT,
            close_timeout=5,
            extra_headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            print("   ✅ WebSocket connected!")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 5. Проверка, что сервер видит аккаунт
    print("\n5. Проверка существования аккаунта...")
    check_response = requests.post(
        f"{API_URL}/api/auth/check-account",
        json={"seed_phrase": "ws_debug_user"},
        verify=False
    )
    print(f"   Response: {check_response.json()}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
