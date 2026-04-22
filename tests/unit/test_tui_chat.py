# tests/unit/test_tui_chat.py
"""
Тесты для TUI чата (криптография и API клиент).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.client.client_crypto import ClientCrypto


class TestClientCrypto:
    """Тесты клиентской криптографии."""

    def test_generate_session_key(self):
        """Генерация session_key."""
        key1 = ClientCrypto.generate_session_key()
        key2 = ClientCrypto.generate_session_key()
        assert len(key1) == 32
        assert key1 != key2

    def test_get_directional_key(self):
        """Направленный ключ."""
        session_key = ClientCrypto.generate_session_key()
        key_ab = ClientCrypto.get_directional_key(session_key, "@A.ru", "@B.ru")
        key_ba = ClientCrypto.get_directional_key(session_key, "@B.ru", "@A.ru")

        assert len(key_ab) == 32
        assert key_ab != key_ba

    def test_derive_phrase_key(self):
        """Ключ из фразы."""
        salt = b"\x00" * 16
        key1 = ClientCrypto.derive_phrase_key("test phrase", salt)
        key2 = ClientCrypto.derive_phrase_key("test phrase", salt)
        key3 = ClientCrypto.derive_phrase_key("different phrase", salt)

        assert len(key1) == 32
        assert key1 == key2
        assert key1 != key3

    def test_xor_keys(self):
        """XOR ключей."""
        key1 = b"\x01" * 32
        key2 = b"\x02" * 32
        result = ClientCrypto.xor_keys(key1, key2)
        assert result == b"\x03" * 32

        with pytest.raises(ValueError):
            ClientCrypto.xor_keys(b"\x01" * 32, b"\x02" * 16)

    def test_encrypt_decrypt_message(self):
        """Шифрование и расшифровка сообщения."""
        session_key = ClientCrypto.generate_session_key()
        plaintext = "Hello, World!"
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        encrypted = ClientCrypto.encrypt_message(
            plaintext, session_key, from_id, to_id
        )
        decrypted = ClientCrypto.decrypt_message(
            encrypted, session_key, from_id, to_id
        )

        assert decrypted == plaintext
        assert len(encrypted) > 12

    def test_encrypt_decrypt_with_phrase(self):
        """Шифрование и расшифровка с дополнительной фразой."""
        session_key = ClientCrypto.generate_session_key()
        phrase = "зеленый дом"
        plaintext = "Secret message"
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        encrypted = ClientCrypto.encrypt_message(
            plaintext, session_key, from_id, to_id, phrase=phrase
        )
        decrypted = ClientCrypto.decrypt_message(
            encrypted, session_key, from_id, to_id, phrase=phrase
        )

        assert decrypted == plaintext
        assert len(encrypted) > 28

    def test_wrong_phrase_fails(self):
        """Неверная фраза не расшифровывает."""
        session_key = ClientCrypto.generate_session_key()
        correct_phrase = "зеленый дом"
        wrong_phrase = "красный дом"
        plaintext = "Secret"
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        encrypted = ClientCrypto.encrypt_message(
            plaintext, session_key, from_id, to_id, phrase=correct_phrase
        )
        decrypted = ClientCrypto.decrypt_message(
            encrypted, session_key, from_id, to_id, phrase=wrong_phrase
        )

        assert decrypted is None

    def test_wrong_session_key_fails(self):
        """Неверный session_key не расшифровывает."""
        sk1 = ClientCrypto.generate_session_key()
        sk2 = ClientCrypto.generate_session_key()
        plaintext = "Secret"
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        encrypted = ClientCrypto.encrypt_message(
            plaintext, sk1, from_id, to_id
        )
        decrypted = ClientCrypto.decrypt_message(
            encrypted, sk2, from_id, to_id
        )

        assert decrypted is None

    def test_wrong_direction_fails(self):
        """Неправильное направление не расшифровывает."""
        session_key = ClientCrypto.generate_session_key()
        plaintext = "Secret"
        from_id = "@ALICE.ru"
        to_id = "@BOB.ru"

        encrypted = ClientCrypto.encrypt_message(
            plaintext, session_key, from_id, to_id
        )
        # Пытаемся расшифровать с обратным направлением
        decrypted = ClientCrypto.decrypt_message(
            encrypted, session_key, to_id, from_id
        )

        assert decrypted is None

    def test_generate_message_id(self):
        id1 = ClientCrypto.generate_message_id(0)
        id2 = ClientCrypto.generate_message_id(1)
        id3 = ClientCrypto.generate_message_id(0)

        # Проверка формата msg_XXXX_XXXXXXXXXXXX
        assert id1.startswith("msg_")
        assert "_" in id1

        # Разные счётчики дают разные ID
        assert id1 != id2

        # Одинаковые счётчики дают разные ID (разный random)
        assert id1 != id3

        # Извлечение счётчика работает
        from src.common.crypto.padding import extract_counter_from_message_id
        assert extract_counter_from_message_id(id1) == 0
        assert extract_counter_from_message_id(id2) == 1


class TestAPIClientMessages:
    """Тесты API методов для сообщений (моки)."""

    @pytest.mark.asyncio
    async def test_get_dialogs(self):
        from src.client.api_client import APIClient

        client = APIClient("http://test", debug=True)
        with patch.object(client, '_request', new_callable=AsyncMock) as mock:
            mock.return_value = {
                "success": True,
                "data": {"dialogs": [{"public_id": "@TEST.ru", "name": "Test"}]}
            }
            result = await client.get_dialogs()
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_messages(self):
        from src.client.api_client import APIClient

        client = APIClient("http://test", debug=True)
        with patch.object(client, '_request', new_callable=AsyncMock) as mock:
            mock.return_value = {
                "success": True,
                "messages": [{"id": "msg1", "from_id": "@A.ru"}]
            }
            result = await client.get_messages("@B.ru")
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_session_key(self):
        from src.client.api_client import APIClient

        client = APIClient("http://test", debug=True)
        with patch.object(client, '_request', new_callable=AsyncMock) as mock:
            mock.return_value = {
                "success": True,
                "data": {"session_key": "a" * 64}
            }
            result = await client.get_session_key("@B.ru")
            assert result == "a" * 64

    @pytest.mark.asyncio
    async def test_send_message(self):
        from src.client.api_client import APIClient

        client = APIClient("http://test", debug=True)
        with patch.object(client, '_request', new_callable=AsyncMock) as mock:
            mock.return_value = {"success": True, "message_id": "msg123"}
            result = await client.send_message("@B.ru", "encrypted", "key123")
            assert result["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
