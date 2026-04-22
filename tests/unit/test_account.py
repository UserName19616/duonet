# tests/unit/test_account.py
"""
Тесты для модуля управления аккаунтами.
"""

import hashlib
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from src.common.crypto.hash import hash_password
from src.common.crypto.keys import generate_keypair_from_seed, hash_sha256
from src.common.identity.account import (
    MIN_PASSWORD_LENGTH,
    AccountManager,
    MAX_CLIENT_ACCOUNTS,
    MAX_SERVER_ACCOUNTS,
    generate_public_id,
)
from src.common.identity.public_id import is_valid_format
from src.server.network.rate_limiter import MultiRateLimiter
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    """Фикстура для SQLiteStorage."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def geoip():
    """Фикстура для функции GeoIP."""

    def get_region(ip):
        return "ru"

    return get_region


@pytest.fixture
def rate_limiter():
    """Фикстура для MultiRateLimiter."""
    return MultiRateLimiter()


@pytest.fixture
def account_manager(storage, geoip, rate_limiter):
    """Фикстура для AccountManager."""
    return AccountManager(
        storage=storage,
        geoip_func=geoip,
        rate_limiter=rate_limiter,
        jwt_secret="test_secret_key",
    )


def test_register_success(account_manager):
    """Тест успешной регистрации клиентского аккаунта."""
    result = account_manager.register(
        seed_phrase="user@example.com моя фраза",
        password="secure_password_123",
        is_server=False,
        client_ip="1.2.3.4",
    )

    assert result["success"] is True
    assert result["public_id"].startswith("@")
    assert result["public_id"].endswith(".ru")
    assert result["server_id"] is None
    assert result["region"] == "ru"
    assert len(result["account_id"]) == 20


def test_register_server(account_manager):
    """Тест регистрации сервера (создаётся два аккаунта)."""
    result = account_manager.register(
        seed_phrase="server@example.com",
        password="secure_password_123",
        is_server=True,
        client_ip="1.2.3.4",
    )

    assert result["success"] is True
    assert result["server_id"] is not None
    assert result["server_id"].endswith(".ru.srv")
    assert result["public_id"] is not None
    assert result["public_id"].endswith(".ru")
    assert result["public_id"] != result["server_id"]
    assert is_valid_format(result["server_id"]) is True


def test_register_duplicate(account_manager):
    """Тест регистрации дубликата."""
    account_manager.register(
        "user@example.com", "pass123456", False, client_ip="1.2.3.4"
    )

    result = account_manager.register(
        "user@example.com", "pass123456", False, client_ip="1.2.3.4"
    )
    assert result["success"] is False
    assert result["error"] == "account_exists"


def test_register_empty_seed(account_manager):
    """Тест регистрации с пустой сид-фразой."""
    result = account_manager.register("", "pass123456", False)
    assert result["success"] is False
    assert result["error"] == "empty_seed"

    result = account_manager.register("   ", "pass123456", False)
    assert result["success"] is False
    assert result["error"] == "empty_seed"


def test_register_weak_password(account_manager):
    """Тест регистрации со слабым паролем."""
    weak_password = "a" * (MIN_PASSWORD_LENGTH - 1)
    result = account_manager.register(
        "user@example.com", weak_password, False
    )
    assert result["success"] is False
    assert result["error"] == "weak_password"

    good_password = "a" * MIN_PASSWORD_LENGTH
    result = account_manager.register(
        "user@example.com", good_password, False
    )
    assert result["success"] is True


def test_register_rate_limit(account_manager):
    """Тест rate limiting для регистрации."""
    ip = "10.0.0.1"

    for i in range(3):
        result = account_manager.register(
            f"user{i}@example.com", "pass123456", False, ip
        )
        assert result["success"] is True

    result = account_manager.register(
        "user4@example.com", "pass123456", False, ip
    )
    assert result["success"] is False
    assert result["error"] == "rate_limit_exceeded"


def test_login_success(account_manager):
    """Тест успешного входа."""
    account_manager.register("user@example.com", "pass123456", False)

    result = account_manager.login("user@example.com", "pass123456")
    assert result is not None
    assert result["public_id"].startswith("@")
    assert "token" in result
    assert result["expires_at"] > time.time()
    assert "account_id" in result
    assert result["is_server"] is False


def test_login_wrong_password(account_manager):
    """Тест входа с неверным паролем."""
    account_manager.register("user@example.com", "pass123456", False)

    result = account_manager.login("user@example.com", "wrong")
    assert result is None


def test_login_nonexistent(account_manager):
    """Тест входа с несуществующей сид-фразой."""
    result = account_manager.login("nonexistent@example.com", "pass123456")
    assert result is None


def test_login_updates_last_login(account_manager):
    """Тест обновления времени последнего входа."""
    account_manager.register("user@example.com", "pass123456", False)

    before = int(time.time())
    time.sleep(0.01)

    result = account_manager.login("user@example.com", "pass123456")
    assert result is not None

    account_id = result["account_id"]
    account = account_manager.get_account(account_id)
    assert account.last_login_at is not None
    assert account.last_login_at >= before


def test_verify_token_valid(account_manager):
    """Тест верификации валидного токена."""
    account_manager.register("user@example.com", "pass123456", False)
    login_result = account_manager.login("user@example.com", "pass123456")

    payload = account_manager.verify_token(login_result["token"])
    assert payload is not None
    assert payload["sub"] == login_result["public_id"]
    assert payload["account_id"] == login_result["account_id"].hex()
    assert payload["is_server"] is False
    assert "iat" in payload
    assert "exp" in payload
    assert "jti" in payload


def test_verify_token_invalid(account_manager):
    """Тест верификации невалидного токена."""
    payload = account_manager.verify_token("invalid.token.here")
    assert payload is None


def test_verify_token_expired(account_manager):
    """Тест верификации истекшего токена."""
    account_manager.register("user@example.com", "pass123456", False)

    expired_payload = {
        "sub": "@TEST.ru",
        "account_id": "a1b2c3d4e5f6g7h8i9j0",
        "is_server": False,
        "iat": int(time.time()) - 100,
        "exp": int(time.time()) - 1,
        "jti": "test-jti",
    }

    from jose import jwt
    expired_token = jwt.encode(
        expired_payload,
        account_manager._jwt_secret,
        algorithm="HS256"
    )

    payload = account_manager.verify_token(expired_token)
    assert payload is None


def test_change_password_success(account_manager):
    """Тест успешной смены пароля."""
    reg_result = account_manager.register(
        "user@example.com", "old_pass", False
    )
    account_id = reg_result["account_id"]

    result = account_manager.change_password(account_id, "old_pass", "new_pass")
    assert result is True

    old_login = account_manager.login("user@example.com", "old_pass")
    assert old_login is None

    new_login = account_manager.login("user@example.com", "new_pass")
    assert new_login is not None


def test_change_password_wrong_old(account_manager):
    """Тест смены пароля с неверным старым паролем."""
    reg_result = account_manager.register(
        "user@example.com", "old_pass", False
    )
    account_id = reg_result["account_id"]

    result = account_manager.change_password(account_id, "wrong", "new_pass")
    assert result is False

    login = account_manager.login("user@example.com", "old_pass")
    assert login is not None


def test_change_password_weak(account_manager):
    """Тест смены пароля на слабый."""
    reg_result = account_manager.register(
        "user@example.com", "old_pass", False
    )
    account_id = reg_result["account_id"]

    weak_password = "a" * (MIN_PASSWORD_LENGTH - 1)
    result = account_manager.change_password(
        account_id, "old_pass", weak_password
    )
    assert result is False


def test_get_account(account_manager):
    """Тест получения информации об аккаунте."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    account_id = reg_result["account_id"]

    account = account_manager.get_account(account_id)
    assert account is not None
    assert account.account_id == account_id
    assert account.public_id == reg_result["public_id"]
    assert account.region == "ru"
    assert account.is_server is False
    assert account.created_at > 0
    assert len(account.public_key) == 32


def test_get_private_key(account_manager):
    """Тест получения приватного ключа."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    account_id = reg_result["account_id"]

    private_key = account_manager.get_private_key(
        account_id, "user@example.com"
    )
    assert private_key is not None
    assert len(private_key) == 32


def test_get_private_key_wrong_seed(account_manager):
    """Тест получения приватного ключа с неверной сид-фразой."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    account_id = reg_result["account_id"]

    private_key = account_manager.get_private_key(account_id, "wrong phrase")
    assert private_key is None


def test_get_public_key(account_manager):
    """Тест получения публичного ключа по account_id."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    account_id = reg_result["account_id"]

    public_key = account_manager.get_public_key(account_id)
    assert public_key is not None
    assert len(public_key) == 32


def test_get_public_key_by_id(account_manager):
    """Тест получения публичного ключа по Public ID."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    public_id = reg_result["public_id"]

    public_key = account_manager.get_public_key_by_id(public_id)
    assert public_key is not None
    assert len(public_key) == 32


def test_public_id_to_account_id(account_manager):
    """Тест конвертации Public ID в account_id."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    public_id = reg_result["public_id"]
    account_id = reg_result["account_id"]

    resolved = account_manager.public_id_to_account_id(public_id)
    assert resolved == account_id


def test_public_id_to_account_id_server(account_manager):
    """Тест конвертации серверного Public ID в account_id."""
    reg_result = account_manager.register(
        "server@example.com", "pass123456", True
    )
    server_id = reg_result["server_id"]
    server_account_id = reg_result["server_account_id"]

    # Для серверного аккаунта используем server_id
    resolved = account_manager.public_id_to_account_id(server_id)
    # Должен вернуть server_account_id, а не client_account_id
    assert resolved == server_account_id


def test_account_id_to_public_id(account_manager):
    """Тест конвертации account_id в Public ID."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    account_id = reg_result["account_id"]
    public_id = reg_result["public_id"]

    resolved = account_manager.account_id_to_public_id(account_id)
    assert resolved == public_id


def test_get_private_key_by_id(account_manager):
    """Тест получения приватного ключа по Public ID."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    public_id = reg_result["public_id"]

    private_key = account_manager.get_private_key_by_id(
        public_id, "user@example.com"
    )
    assert private_key is not None
    assert len(private_key) == 32


def test_get_private_key_by_id_wrong_seed(account_manager):
    """Тест получения приватного ключа с неверной сид-фразой."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    public_id = reg_result["public_id"]

    private_key = account_manager.get_private_key_by_id(
        public_id, "wrong phrase"
    )
    assert private_key is None


def test_jwt_payload_structure(account_manager):
    """Тест структуры JWT payload."""
    account_manager.register("user@example.com", "pass123456", False)
    login_result = account_manager.login("user@example.com", "pass123456")

    payload = account_manager.verify_token(login_result["token"])

    assert "sub" in payload
    assert "account_id" in payload
    assert "is_server" in payload
    assert "iat" in payload
    assert "exp" in payload
    assert "jti" in payload
    assert payload["sub"] == login_result["public_id"]
    assert payload["is_server"] is False


def test_get_connected_clients_no_ws(account_manager):
    """Тест получения подключенных клиентов без WebSocketManager."""
    clients = account_manager.get_connected_clients()
    assert clients == []


def test_get_connected_clients_with_ws(account_manager):
    """Тест получения подключенных клиентов с WebSocketManager."""
    mock_ws = MagicMock()
    mock_ws.get_all_connections.return_value = [
        {"public_id": "@ALICE.ru", "connected_at": 123456}
    ]

    manager = AccountManager(
        storage=account_manager._storage,
        geoip_func=account_manager._geoip_func,
        rate_limiter=account_manager._rate_limiter,
        jwt_secret="test_secret",
        ws_manager=mock_ws,
    )

    clients = manager.get_connected_clients()
    assert len(clients) == 1
    assert clients[0]["public_id"] == "@ALICE.ru"


def test_is_online_no_ws(account_manager):
    """Тест проверки онлайн статуса без WebSocketManager."""
    assert account_manager.is_online("@ALICE.ru") is False


def test_is_online_with_ws(account_manager):
    """Тест проверки онлайн статуса с WebSocketManager."""
    mock_ws = MagicMock()
    mock_ws.get_connection.return_value = MagicMock()

    manager = AccountManager(
        storage=account_manager._storage,
        geoip_func=account_manager._geoip_func,
        rate_limiter=account_manager._rate_limiter,
        jwt_secret="test_secret",
        ws_manager=mock_ws,
    )

    assert manager.is_online("@ALICE.ru") is True

    mock_ws.get_connection.return_value = None
    assert manager.is_online("@ALICE.ru") is False


def test_get_active_connection_count_no_ws(account_manager):
    """Тест получения количества активных соединений без WS менеджера."""
    assert account_manager.get_active_connection_count() == 0


def test_get_active_connection_count_with_ws(account_manager):
    """Тест получения количества активных соединений с WS менеджером."""
    mock_ws = MagicMock()
    mock_ws.get_connection_count.return_value = 5

    manager = AccountManager(
        storage=account_manager._storage,
        geoip_func=account_manager._geoip_func,
        rate_limiter=account_manager._rate_limiter,
        jwt_secret="test_secret",
        ws_manager=mock_ws,
    )

    assert manager.get_active_connection_count() == 5


def test_update_last_login(account_manager):
    """Тест обновления времени последнего входа."""
    reg_result = account_manager.register(
        "user@example.com", "pass123456", False
    )
    account_id = reg_result["account_id"]

    before = int(time.time())
    time.sleep(0.01)

    account_manager.update_last_login(account_id)

    account = account_manager.get_account(account_id)
    assert account.last_login_at is not None
    assert account.last_login_at >= before


def test_get_ws_manager(account_manager):
    """Тест получения WebSocketManager."""
    assert account_manager.get_ws_manager() is None

    mock_ws = MagicMock()
    manager = AccountManager(
        storage=account_manager._storage,
        geoip_func=account_manager._geoip_func,
        rate_limiter=account_manager._rate_limiter,
        jwt_secret="test_secret",
        ws_manager=mock_ws,
    )

    assert manager.get_ws_manager() == mock_ws


def test_seed_hash_deterministic(account_manager):
    """Тест детерминированности хеша сид-фразы."""
    seed1 = account_manager._compute_seed_hash("test phrase")
    seed2 = account_manager._compute_seed_hash("test phrase")
    assert seed1 == seed2

    seed3 = account_manager._compute_seed_hash("different phrase")
    assert seed1 != seed3


def test_account_id_derivation(account_manager):
    """Тест получения account_id из seed_hash."""
    seed_hash = hashlib.sha256(b"test").digest()
    account_id = account_manager._account_id_from_seed_hash(seed_hash)
    assert len(account_id) == 20
    assert account_id == seed_hash[:20]


def test_geoip_integration(account_manager):
    """Тест интеграции с GeoIP."""
    result1 = account_manager.register("user1@example.com", "pass123456", False, "127.0.0.1")
    result2 = account_manager.register("user2@example.com", "pass123456", False, "8.8.8.8")

    assert result1["region"] == "ru"
    assert result2["region"] == "ru"


def test_server_id_format(account_manager):
    """Тест формата серверного ID."""
    result = account_manager.register(
        "server@example.com", "pass123456", True
    )
    assert result["success"] is True
    assert result["server_id"] is not None
    assert result["server_id"].endswith(".srv")
    assert is_valid_format(result["server_id"]) is True
    assert result["public_id"] != result["server_id"]


def test_private_key_uniqueness(account_manager):
    """Тест уникальности приватных ключей."""
    result1 = account_manager.register("user1@example.com", "pass123456", False)
    result2 = account_manager.register("user2@example.com", "pass123456", False)

    key1 = account_manager.get_private_key(result1["account_id"], "user1@example.com")
    key2 = account_manager.get_private_key(result2["account_id"], "user2@example.com")

    assert key1 != key2


def test_public_key_storage(account_manager):
    """Тест сохранения публичного ключа."""
    result = account_manager.register("user@example.com", "pass123456", False)
    account_id = result["account_id"]

    stored_key = account_manager.get_public_key(account_id)
    assert stored_key is not None
    assert len(stored_key) == 32

    seed_hash = account_manager._compute_seed_hash("user@example.com")
    _, expected_key = generate_keypair_from_seed(seed_hash)

    assert stored_key == expected_key


def test_multiple_accounts_isolation(account_manager):
    """Тест изоляции разных аккаунтов."""
    user1 = account_manager.register("user1@example.com", "pass123456", False)
    user2 = account_manager.register("user2@example.com", "pass123456", False)

    assert user1["account_id"] != user2["account_id"]
    assert user1["public_id"] != user2["public_id"]

    login1 = account_manager.login("user1@example.com", "pass123456")
    login2 = account_manager.login("user2@example.com", "pass123456")

    assert login1 is not None
    assert login2 is not None
    assert login1["account_id"] == user1["account_id"]
    assert login2["account_id"] == user2["account_id"]

    key1_as_user2 = account_manager.get_private_key(
        user2["account_id"], "user1@example.com"
    )
    assert key1_as_user2 is None


def test_change_password_with_ws_manager(account_manager):
    """Тест смены пароля с WebSocketManager."""
    mock_ws = MagicMock()
    manager = AccountManager(
        storage=account_manager._storage,
        geoip_func=account_manager._geoip_func,
        rate_limiter=account_manager._rate_limiter,
        jwt_secret="test_secret",
        ws_manager=mock_ws,
    )

    result = manager.register("user@example.com", "old_pass", False)
    account_id = result["account_id"]

    success = manager.change_password(account_id, "old_pass", "new_pass")
    assert success is True

    assert manager.login("user@example.com", "old_pass") is None
    assert manager.login("user@example.com", "new_pass") is not None


def test_register_different_ips(account_manager):
    """Тест регистрации с разных IP."""
    result1 = account_manager.register("user1@example.com", "pass123456", False, "10.0.0.1")
    result2 = account_manager.register("user2@example.com", "pass123456", False, "10.0.0.2")
    result3 = account_manager.register("user3@example.com", "pass123456", False, "10.0.0.3")

    assert result1["success"] is True
    assert result2["success"] is True
    assert result3["success"] is True


def test_register_whitespace_seed(account_manager):
    """Тест регистрации с сид-фразой, содержащей пробелы."""
    result = account_manager.register("  user@example.com моя фраза  ", "pass123456", False)
    assert result["success"] is True
    assert result["public_id"] is not None

    result2 = account_manager.register("user@example.com моя фраза", "pass123456", False)
    assert result2["success"] is False
    assert result2["error"] == "account_exists"


# =============================================================================
# Тесты для лимитов аккаунтов
# =============================================================================

class TestAccountLimits:
    """Тесты для лимитов клиентских и серверных аккаунтов."""

    # ----- Тесты для клиентских аккаунтов -----

    def test_count_client_accounts_empty(self, account_manager):
        """Подсчёт клиентских аккаунтов когда их нет."""
        count = account_manager.count_client_accounts()
        assert count == 0

    def test_count_client_accounts_after_register(self, account_manager):
        """Подсчёт после регистрации клиентского аккаунта."""
        result = account_manager.register(
            seed_phrase="client1@example.com",
            password="password123",
            is_server=False,
            client_ip="10.0.0.1",
        )
        assert result["success"] is True

        count = account_manager.count_client_accounts()
        assert count == 1

    def test_register_client_within_limit(self, account_manager):
        """Регистрация клиентского аккаунта в пределах лимита."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            count = account_manager.count_client_accounts()
            assert count == MAX_CLIENT_ACCOUNTS

    def test_register_client_at_limit(self, account_manager):
        """Попытка регистрации при достижении лимита."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем 3 клиентских
            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            # Пытаемся зарегистрировать 4-й
            result = account_manager.register(
                seed_phrase="client3@example.com",
                password="password123",
                is_server=False,
                client_ip="10.0.0.99",
            )

            assert result["success"] is False
            assert result["error"] == "max_clients_reached"
            assert result["client_count"] == MAX_CLIENT_ACCOUNTS
            assert result["max_clients"] == MAX_CLIENT_ACCOUNTS

    # ----- Тесты для серверных аккаунтов -----

    def test_count_server_accounts_empty(self, account_manager):
        """Подсчёт серверных аккаунтов когда их нет."""
        count = account_manager.count_server_accounts()
        assert count == 0

    def test_count_server_accounts_after_register(self, account_manager):
        """Подсчёт после регистрации серверного аккаунта."""
        result = account_manager.register(
            seed_phrase="server@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result["success"] is True

        count = account_manager.count_server_accounts()
        assert count == 1

    def test_register_server_success(self, account_manager):
        """Регистрация первого серверного аккаунта."""
        result = account_manager.register(
            seed_phrase="server@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result["success"] is True
        assert result["server_id"] is not None
        assert result["server_id"].endswith(".srv")

    def test_register_server_at_limit(self, account_manager):
        """Попытка регистрации второго серверного аккаунта."""
        # Регистрируем первый серверный
        result1 = account_manager.register(
            seed_phrase="server1@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.1",
        )
        assert result1["success"] is True

        # Пытаемся зарегистрировать второй
        result2 = account_manager.register(
            seed_phrase="server2@example.com",
            password="password123",
            is_server=True,
            client_ip="10.0.0.2",
        )

        assert result2["success"] is False
        assert result2["error"] == "max_servers_reached"
        assert result2["server_count"] == 1
        assert result2["max_servers"] == 1

    def test_register_server_unlimited_clients(self, account_manager):
        """Серверный аккаунт можно создать даже если клиентских уже 3."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Регистрируем 3 клиентских
            for i in range(MAX_CLIENT_ACCOUNTS):
                result = account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )
                assert result["success"] is True

            # "Перематываем время"
            mock_time.time.return_value = base_time + 25 * 3600

            # Регистрируем серверный
            # При достижении лимита клиентских (3), серверный создаётся, но клиентский не создаётся
            result = account_manager.register(
                seed_phrase="server@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.100",
            )
            # Проверяем, что серверный аккаунт создан
            assert result["success"] is True, f"Registration failed: {result}"
            assert result["server_id"] is not None
            # Клиентский аккаунт не создаётся из-за лимита
            # Проверяем, что клиентский аккаунт не был создан (public_id = None)
            assert result.get("public_id") is None

    def test_get_client_accounts(self, account_manager):
        """Получение списка клиентских аккаунтов."""
        with patch('src.server.network.rate_limiter.time') as mock_time:
            base_time = 1000000.0
            mock_time.time.return_value = base_time

            # Создаём 2 клиентских аккаунта
            for i in range(2):
                account_manager.register(
                    seed_phrase=f"client{i}@example.com",
                    password="password123",
                    is_server=False,
                    client_ip=f"10.0.0.{i+1}",
                )

            # "Перематываем время"
            mock_time.time.return_value = base_time + 25 * 3600

            # Создаём серверный аккаунт (создаётся только серверный, клиентский не создаётся,
            # так как лимит клиентских уже 2 из 3, можно создать ещё 1)
            # Но по логике, при создании серверного создаётся и клиентский, если есть место
            # Поэтому после этого будет 3 клиентских
            account_manager.register(
                seed_phrase="server@example.com",
                password="password123",
                is_server=True,
                client_ip="10.0.0.100",
            )

            clients = account_manager.get_client_accounts()
            # После создания серверного создаётся ещё один клиентский, всего 3
            assert len(clients) == 3

def test_register_duplicate(account_manager):
    """Повторная регистрация должна возвращать ошибку"""
    # Первая регистрация
    result1 = account_manager.register(
        "duplicate@test.com", "pass123456", False, "127.0.0.1"
    )
    assert result1["success"] is True

    # Вторая регистрация (дубликат)
    result2 = account_manager.register(
        "duplicate@test.com", "pass123456", False, "127.0.0.1"
    )
    assert result2["success"] is False
    assert result2["error"] == "account_exists"

def test_register_whitespace_seed(account_manager):
    """Сид-фраза с пробелами должна нормально обрабатываться"""
    result = account_manager.register(
        "  spaced@test.com  ", "pass123456", False, "127.0.0.1"
    )
    assert result["success"] is True

    # Проверяем, что пробелы обрезаны и аккаунт создан
    assert result["public_id"] is not None
