# tests/unit/test_proxy_manager.py
"""
Тесты для модуля ClientManager.
"""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.common.identity.account import AccountManager
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.utils.geoip import get_region_by_ip
from src.server.proxy.client_crud import ClientManager, GROUPS
from src.common.storage.sqlite import SQLiteStorage
from tests.unit.mock_ws_manager import MockWebSocketManager


def mock_geoip(ip):
    return "ru"


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def account_manager(storage):
    rate_limiter = MultiRateLimiter()
    ws_manager = MockWebSocketManager()
    return AccountManager(
        storage=storage,
        geoip_func=mock_geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret",
        ws_manager=ws_manager,
    )


@pytest.fixture
def client_manager(storage, account_manager):
    return ClientManager(storage, account_manager)


@pytest.fixture
def test_user(account_manager):
    result = account_manager.register(
        "user@example.com", "password123", False, "127.0.0.1"
    )
    assert result["success"]
    return result["public_id"]


@pytest.fixture
def test_user2(account_manager):
    result = account_manager.register(
        "user2@example.com", "password123", False, "127.0.0.1"
    )
    assert result["success"]
    return result["public_id"]


@pytest.fixture
def test_user3(account_manager):
    result = account_manager.register(
        "user3@example.com", "password123", False, "127.0.0.1"
    )
    assert result["success"]
    return result["public_id"]


class TestClientManager:
    """Тесты для ClientManager."""

    def test_generate_invite_basic(self, client_manager):
        """Генерация приглашения для группы basic."""
        result = client_manager.generate_invite(
            client_name="Телефон Маши",
            expires_in=86400,
            group="basic",
            daily_limit_mb=1024,
        )

        assert result["success"] is True
        assert "token" in result
        assert "qr_code" in result
        assert result["expires_at"] > time.time()
        assert result["expires_at"] < time.time() + 86400 + 10

    def test_generate_invite_privileged(self, client_manager):
        """Генерация приглашения для группы privileged."""
        result = client_manager.generate_invite(
            client_name="Мой телефон",
            group="privileged",
        )

        assert result["success"] is True
        assert result["expires_at"] is None

    def test_generate_invite_invalid_name(self, client_manager):
        """Генерация с неверным именем."""
        result = client_manager.generate_invite(
            client_name="",
            group="basic",
        )
        assert result["success"] is False
        assert result["error"] == "invalid_name"

        result = client_manager.generate_invite(
            client_name="x" * 65,
            group="basic",
        )
        assert result["success"] is False
        assert result["error"] == "invalid_name"

    def test_generate_invite_invalid_expiry(self, client_manager):
        """Генерация с неверным сроком."""
        result = client_manager.generate_invite(
            client_name="Тест",
            expires_in=100,  # меньше часа
            group="basic",
        )
        assert result["success"] is False
        assert result["error"] == "invalid_expiry"

        result = client_manager.generate_invite(
            client_name="Тест",
            expires_in=3600 * 24 * 31,  # больше 30 дней
            group="basic",
        )
        assert result["success"] is False
        assert result["error"] == "invalid_expiry"

    def test_generate_invite_invalid_group(self, client_manager):
        """Генерация с неверной группой."""
        result = client_manager.generate_invite(
            client_name="Тест",
            group="invalid_group",
        )
        assert result["success"] is False
        assert result["error"] == "invalid_group"

    def test_qr_generation_success(self, client_manager):
        """Успешная генерация QR-кода."""
        result = client_manager.generate_invite(
            client_name="Телефон",
            group="basic",
        )
        assert result["success"] is True
        assert result["qr_code"] is not None
        import base64
        try:
            base64.b64decode(result["qr_code"])
        except Exception:
            pytest.fail("QR code is not valid base64")

    def test_qr_generation_failure(self, client_manager):
        """Ошибка генерации QR-кода (используется fallback)."""
        with patch("qrcode.QRCode.make", side_effect=Exception("QR failed")):
            result = client_manager.generate_invite(
                client_name="Телефон",
                group="basic",
            )
            assert result["success"] is True
            assert result["qr_code"] is not None

    def test_add_client_success(self, client_manager, test_user):
        """Успешное добавление клиента."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        token = invite["token"]

        result = client_manager.add_client(token, test_user)
        assert result is True

        clients = client_manager.get_all_clients()
        assert len(clients) == 1
        assert clients[0].name == "Телефон"
        assert clients[0].group == "basic"

    def test_add_client_standard_end_of_month(self, client_manager, test_user):
        """Добавление клиента группы standard с расчетом expires_at."""
        invite = client_manager.generate_invite("Клиент", group="standard")
        assert invite["success"] is True
        token = invite["token"]

        activation_time = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        with patch("time.time", return_value=activation_time):
            result = client_manager.add_client(token, test_user)
            assert result is True

        clients = client_manager.get_all_clients()
        client = clients[0]

        expected = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert client.expires_at == expected

    def test_add_client_standard_february(self, client_manager, test_user):
        """Добавление клиента в феврале."""
        invite = client_manager.generate_invite("Клиент", group="standard")
        assert invite["success"] is True
        token = invite["token"]

        activation_time = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        with patch("time.time", return_value=activation_time):
            result = client_manager.add_client(token, test_user)
            assert result is True

        clients = client_manager.get_all_clients()
        client = clients[0]

        expected = datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert client.expires_at == expected

    def test_add_client_max_clients(self, client_manager, test_user, test_user2):
        """Превышение лимита клиентов."""
        client_manager.update_settings(max_clients=1)

        invite1 = client_manager.generate_invite("Клиент 1", group="basic")
        invite2 = client_manager.generate_invite("Клиент 2", group="basic")
        assert invite1["success"] is True
        assert invite2["success"] is True

        assert client_manager.add_client(invite1["token"], test_user) is True
        result = client_manager.add_client(invite2["token"], test_user2)
        assert result is False

    def test_add_client_invalid_token(self, client_manager, test_user):
        """Добавление с неверным токеном."""
        result = client_manager.add_client("invalid_token", test_user)
        assert result is False

    def test_add_client_used_token(self, client_manager, test_user, test_user2):
        """Добавление с уже использованным токеном."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        token = invite["token"]

        client_manager.add_client(token, test_user)
        result = client_manager.add_client(token, test_user2)
        assert result is False

    def test_add_client_expired_token(self, client_manager, test_user):
        """Добавление с истекшим токеном."""
        invite = client_manager.generate_invite("Телефон", group="basic", expires_in=3600)
        assert invite["success"] is True
        token = invite["token"]

        expired_time = time.time() - 1
        client_manager._storage.execute_sql(
            "UPDATE proxy_invites SET expires_at = ? WHERE token = ?",
            (expired_time, token)
        )

        result = client_manager.add_client(token, test_user)
        assert result is False

    def test_get_client(self, client_manager, test_user):
        """Получение информации о клиенте."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        client = client_manager.get_client(client_id)
        assert client is not None
        assert client.public_id == test_user
        assert client.name == "Телефон"

    def test_get_all_clients(self, client_manager, test_user, test_user2):
        """Получение списка всех клиентов."""
        invite1 = client_manager.generate_invite("Клиент 1", group="basic")
        invite2 = client_manager.generate_invite("Клиент 2", group="standard")
        assert invite1["success"] is True
        assert invite2["success"] is True

        client_manager.add_client(invite1["token"], test_user)
        client_manager.add_client(invite2["token"], test_user2)

        clients = client_manager.get_all_clients()
        assert len(clients) == 2

    def test_update_client_group(self, client_manager, test_user):
        """Обновление группы клиента."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        result = client_manager.update_client(client_id, group="standard")
        assert result is True

        client = client_manager.get_client(client_id)
        assert client.group == "standard"

    def test_update_client_privileged(self, client_manager, test_user):
        """Обновление до privileged."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        result = client_manager.update_client(client_id, group="privileged", daily_limit_mb=None)
        assert result is True

        client = client_manager.get_client(client_id)
        assert client.group == "privileged"
        assert client.daily_limit is None
        assert client.expires_at is None

    def test_update_client_name(self, client_manager, test_user):
        """Обновление имени клиента."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        result = client_manager.update_client(client_id, name="Новое имя")
        assert result is True

        client = client_manager.get_client(client_id)
        assert client.name == "Новое имя"

    def test_revoke_access(self, client_manager, test_user):
        """Отзыв доступа клиента."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        result = client_manager.revoke_access(client_id)
        assert result is True

        assert len(client_manager.get_all_clients()) == 0

    def test_has_permission_proxy_active(self, client_manager, test_user):
        """Проверка разрешения proxy для активного клиента."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        assert client_manager.has_permission(client_id, "proxy") is True
        assert client_manager.has_permission(client_id, "chat") is True

    def test_has_permission_proxy_expired(self, client_manager, test_user):
        """Проверка разрешения proxy для истекшего клиента."""
        invite = client_manager.generate_invite("Телефон", group="basic", expires_in=3600)
        assert invite["success"] is True
        token = invite["token"]

        result = client_manager.add_client(token, test_user)
        assert result is True

        expired_time = time.time() - 1
        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id
        client_manager._storage.execute_sql(
            "UPDATE proxy_clients SET expires_at = ? WHERE client_id = ?",
            (expired_time, client_id)
        )

        assert client_manager.has_permission(client_id, "proxy") is False
        assert client_manager.has_permission(client_id, "chat") is True

    def test_add_traffic(self, client_manager, test_user):
        """Добавление трафика."""
        invite = client_manager.generate_invite("Телефон", group="basic", daily_limit_mb=1)
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        client_manager.add_traffic(client_id, 512 * 1024)

        client = client_manager.get_client(client_id)
        assert client.traffic_today == 512 * 1024
        assert client.traffic_total == 512 * 1024

    def test_check_traffic_limit_within_limit(self, client_manager, test_user):
        """Проверка лимита трафика в пределах."""
        invite = client_manager.generate_invite("Телефон", group="basic", daily_limit_mb=1)
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        client_manager.add_traffic(client_id, 512 * 1024)
        assert client_manager.check_traffic_limit(client_id, 512 * 1024) is True

    def test_check_traffic_limit_exceeded(self, client_manager, test_user):
        """Проверка лимита трафика при превышении."""
        invite = client_manager.generate_invite("Телефон", group="basic", daily_limit_mb=1)
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        client_manager.add_traffic(client_id, 1024 * 1024)
        assert client_manager.check_traffic_limit(client_id, 1) is False

    def test_check_traffic_limit_unlimited(self, client_manager, test_user):
        """Проверка лимита для безлимитного клиента."""
        invite = client_manager.generate_invite("Телефон", group="privileged")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        assert client_manager.check_traffic_limit(client_id, 10 * 1024 * 1024) is True

    def test_get_traffic_stats(self, client_manager, test_user):
        """Получение статистики трафика."""
        invite = client_manager.generate_invite("Телефон", group="basic", daily_limit_mb=10)
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        client_manager.add_traffic(client_id, 2 * 1024 * 1024)

        stats = client_manager.get_traffic_stats(client_id)
        assert stats["used_today_mb"] == 2.0
        assert stats["daily_limit_mb"] == 10.0
        assert stats["remaining_mb"] == 8.0

    def test_get_aggregated_stats(self, client_manager, test_user, test_user2, test_user3):
        """Получение агрегированной статистики."""
        invite1 = client_manager.generate_invite("Basic", group="basic")
        invite2 = client_manager.generate_invite("Standard", group="standard")
        invite3 = client_manager.generate_invite("Privileged", group="privileged")
        assert invite1["success"] is True
        assert invite2["success"] is True
        assert invite3["success"] is True

        client_manager.add_client(invite1["token"], test_user)
        client_manager.add_client(invite2["token"], test_user2)
        client_manager.add_client(invite3["token"], test_user3)

        clients = client_manager.get_all_clients()
        for client in clients:
            client_manager.add_traffic(client.client_id, 1024 * 1024)

        stats = client_manager.get_aggregated_stats()
        assert stats["total_today_mb"] == 3.0
        assert stats["total_clients"] == 3
        assert stats["by_group"]["basic"] == 1
        assert stats["by_group"]["standard"] == 1
        assert stats["by_group"]["privileged"] == 1

    def test_reset_daily_traffic(self, client_manager, test_user):
        """Сброс дневного трафика."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id

        client_manager.add_traffic(client_id, 1024 * 1024)

        count = client_manager.reset_daily_traffic()
        assert count == 1

        client = client_manager.get_client(client_id)
        assert client.traffic_today == 0
        assert client.traffic_total == 1024 * 1024

    def test_cleanup_expired(self, client_manager, test_user, test_user2):
        """Очистка истекших клиентов."""
        invite = client_manager.generate_invite("Временный", group="basic", expires_in=3600)
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id
        expired_time = time.time() - 1
        client_manager._storage.execute_sql(
            "UPDATE proxy_clients SET expires_at = ? WHERE client_id = ?",
            (expired_time, client_id)
        )

        invite2 = client_manager.generate_invite("Постоянный", group="privileged")
        assert invite2["success"] is True
        client_manager.add_client(invite2["token"], test_user2)

        count = client_manager.cleanup_expired()
        assert count == 1

        clients = client_manager.get_all_clients()
        assert len(clients) == 1
        assert clients[0].name == "Постоянный"

    def test_cleanup_expired_closes_websocket(self, client_manager, account_manager, test_user):
        """Очистка закрывает WebSocket соединение."""
        invite = client_manager.generate_invite("Временный", group="basic", expires_in=3600)
        assert invite["success"] is True
        client_manager.add_client(invite["token"], test_user)

        clients = client_manager.get_all_clients()
        client_id = clients[0].client_id
        expired_time = time.time() - 1
        client_manager._storage.execute_sql(
            "UPDATE proxy_clients SET expires_at = ? WHERE client_id = ?",
            (expired_time, client_id)
        )

        with patch.object(account_manager, "close_connection") as mock_close:
            client_manager.cleanup_expired()
            mock_close.assert_called_with(test_user)

    def test_get_settings_default(self, client_manager):
        """Получение настроек по умолчанию."""
        settings = client_manager.get_settings()
        assert settings["max_clients"] == 10
        assert settings["default_daily_limit_mb"] == 1024
        assert settings["default_group"] == "basic"
        assert settings["proxy_enabled"] is True

    def test_update_settings(self, client_manager):
        """Обновление настроек."""
        result = client_manager.update_settings(
            max_clients=20,
            default_daily_limit_mb=2048,
            default_group="standard",
            proxy_enabled=False,
        )
        assert result is True

        settings = client_manager.get_settings()
        assert settings["max_clients"] == 20
        assert settings["default_daily_limit_mb"] == 2048
        assert settings["default_group"] == "standard"
        assert settings["proxy_enabled"] is False

    def test_update_settings_invalid_group(self, client_manager):
        """Обновление с неверной группой должно возвращать False"""
        result = client_manager.update_settings(default_group="invalid")
        assert result is False

        # Проверяем, что настройки не изменились
        settings = client_manager.get_settings()
        assert settings["default_group"] != "invalid"

    def test_calculate_standard_expiry_january(self, client_manager):
        """Расчет expires_at для января."""
        activation = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        expiry = client_manager._calculate_standard_expiry(int(activation))

        expected = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert expiry == expected

    def test_calculate_standard_expiry_february_leap(self, client_manager):
        """Расчет expires_at для февраля високосного года."""
        activation = datetime(2024, 2, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        expiry = client_manager._calculate_standard_expiry(int(activation))

        expected = datetime(2024, 2, 29, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert expiry == expected

    def test_calculate_standard_expiry_february_non_leap(self, client_manager):
        """Расчет expires_at для февраля невисокосного года."""
        activation = datetime(2025, 2, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        expiry = client_manager._calculate_standard_expiry(int(activation))

        expected = datetime(2025, 2, 28, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert expiry == expected

    def test_proxy_port_attribute(self, client_manager):
        """Проверка атрибута proxy_port."""
        assert hasattr(client_manager, 'proxy_port')
        assert client_manager.proxy_port == 9879

        client_manager.proxy_port = 9999
        assert client_manager.proxy_port == 9999

    def test_qr_generation_fallback(self, client_manager):
        """Проверка fallback при ошибке генерации QR-кода."""
        with patch("qrcode.QRCode.make", side_effect=Exception("QR failed")):
            result = client_manager.generate_invite(
                client_name="Телефон",
                group="basic",
            )
            assert result["success"] is True
            assert result["qr_code"] is not None
            import base64
            try:
                base64.b64decode(result["qr_code"])
            except Exception:
                pytest.fail("QR code is not valid base64")

    def test_add_client_invalid_public_id(self, client_manager):
        """Добавление клиента с несуществующим public_id."""
        invite = client_manager.generate_invite("Телефон", group="basic")
        assert invite["success"] is True

        result = client_manager.add_client(invite["token"], "@NONEXISTENT-1234-5678.ru")
        assert result is False

    def test_aggregated_stats_with_no_clients(self, client_manager):
        """Агрегированная статистика при отсутствии клиентов."""
        stats = client_manager.get_aggregated_stats()
        assert stats["total_today_mb"] == 0.0
        assert stats["total_all_mb"] == 0.0
        assert stats["total_clients"] == 0
        assert stats["active_clients"] == 0
        assert stats["by_group"]["basic"] == 0
        assert stats["by_group"]["standard"] == 0
        assert stats["by_group"]["privileged"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
