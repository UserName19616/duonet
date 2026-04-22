# src/client/crypto.py - начало файла
"""
Клиентская криптография для TUI.
Реализует те же алгоритмы, что и в веб-версии:
- Направленное шифрование (directional)
- AES-256-GCM
- Поддержка дополнительной фразы (Double Key)
- Адаптивный паддинг для защиты от анализа трафика
"""

import hashlib
import secrets
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from src.config import MAX_TEXT_LENGTH
from src.common.crypto.padding import calculate_padding_size, add_padding, generate_message_id_with_counter, extract_counter_from_message_id

# Не импортируем из src.client.crypto.__init__, чтобы избежать циркулярности
# Все нужные функции импортированы выше из src.common.crypto.padding

class ClientCrypto:
    """Клиентские криптографические операции."""

    @staticmethod
    def generate_session_key() -> bytes:
        """
        Генерация случайного сессионного ключа (32 байта).
        """
        return secrets.token_bytes(32)

    @staticmethod
    def get_directional_key(session_key: bytes, from_id: str, to_id: str) -> bytes:
        """
        Получение ключа для направления from_id → to_id.

        Args:
            session_key: 32-байтовый сессионный ключ
            from_id: Public ID отправителя
            to_id: Public ID получателя

        Returns:
            32-байтовый ключ для шифрования в данном направлении
        """
        direction_str = f"{from_id}:{to_id}"
        direction_hash = hashlib.sha256(direction_str.encode()).digest()[:32]
        return bytes(a ^ b for a, b in zip(session_key, direction_hash))

    @staticmethod
    def derive_phrase_key(phrase: str, salt: bytes) -> bytes:
        """
        Получение 32-байтового ключа из дополнительной фразы.

        Args:
            phrase: Дополнительная фраза
            salt: Соль (16 байт)

        Returns:
            32-байтовый ключ
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        return kdf.derive(phrase.encode('utf-8'))

    @staticmethod
    def xor_keys(key1: bytes, key2: bytes) -> bytes:
        """
        Побайтовый XOR двух ключей одинаковой длины.

        Args:
            key1: Первый ключ
            key2: Второй ключ

        Returns:
            Результат XOR
        """
        if len(key1) != len(key2):
            raise ValueError(f"Key lengths must match: {len(key1)} != {len(key2)}")
        return bytes(a ^ b for a, b in zip(key1, key2))

    @classmethod
    def encrypt_message(
        cls,
        plaintext: str,
        session_key: bytes,
        from_id: str,
        to_id: str,
        phrase: Optional[str] = None,
    ) -> bytes:
        """
        Шифрование сообщения с учётом направления и опциональной фразы.
        (Без паддинга — для обратной совместимости)

        Формат выходных данных (без фразы):
            nonce (12 байт) + ciphertext

        Формат с фразой:
            salt (16 байт) + nonce (12 байт) + ciphertext

        Args:
            plaintext: Текст сообщения
            session_key: 32-байтовый сессионный ключ
            from_id: Public ID отправителя
            to_id: Public ID получателя
            phrase: Дополнительная фраза (опционально)

        Returns:
            Зашифрованные данные

        Raises:
            ValueError: Если текст сообщения превышает MAX_TEXT_LENGTH
        """
        # Проверка длины текста
        if len(plaintext) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Message too long: {len(plaintext)} chars (max {MAX_TEXT_LENGTH})"
            )

        # Получаем направленный ключ
        directional_key = cls.get_directional_key(session_key, from_id, to_id)

        # Если есть фраза — комбинируем
        if phrase:
            salt = secrets.token_bytes(16)
            phrase_key = cls.derive_phrase_key(phrase, salt)
            combined_key = cls.xor_keys(directional_key, phrase_key)
            # Шифруем с солью в начале
            nonce = secrets.token_bytes(12)
            aesgcm = AESGCM(combined_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
            return salt + nonce + ciphertext
        else:
            # Шифруем без фразы
            nonce = secrets.token_bytes(12)
            aesgcm = AESGCM(directional_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
            return nonce + ciphertext

    @classmethod
    def encrypt_message_with_padding(
        cls,
        plaintext: str,
        session_key: bytes,
        from_id: str,
        to_id: str,
        message_counter: int,
        prev_padding: int = 0,
        phrase: Optional[str] = None,
    ) -> Tuple[bytes, int]:
        """
        Шифрование сообщения с учётом направления, опциональной фразы
        и адаптивным паддингом.

        Args:
            plaintext: Текст сообщения
            session_key: 32-байтовый сессионный ключ
            from_id: Public ID отправителя
            to_id: Public ID получателя
            message_counter: Порядковый номер сообщения в диалоге
            prev_padding: Размер паддинга предыдущего сообщения
            phrase: Дополнительная фраза (опционально)

        Returns:
            Tuple[bytes, int]: (Зашифрованные данные с паддингом, размер паддинга)

        Raises:
            ValueError: Если текст сообщения превышает MAX_TEXT_LENGTH
        """
        # Проверка длины текста
        if len(plaintext) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Message too long: {len(plaintext)} chars (max {MAX_TEXT_LENGTH})"
            )

        # Получаем направленный ключ
        directional_key = cls.get_directional_key(session_key, from_id, to_id)

        # Шифруем
        if phrase:
            salt = secrets.token_bytes(16)
            phrase_key = cls.derive_phrase_key(phrase, salt)
            combined_key = cls.xor_keys(directional_key, phrase_key)
            nonce = secrets.token_bytes(12)
            aesgcm = AESGCM(combined_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
            encrypted = salt + nonce + ciphertext
        else:
            nonce = secrets.token_bytes(12)
            aesgcm = AESGCM(directional_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
            encrypted = nonce + ciphertext

        # Вычисляем размер паддинга
        padding_size = calculate_padding_size(
            session_key=session_key,
            from_id=from_id,
            to_id=to_id,
            message_counter=message_counter,
            plaintext_len=len(plaintext),
            prev_padding=prev_padding,
        )

        # Добавляем паддинг
        if padding_size > 0:
            encrypted = add_padding(encrypted, len(encrypted) + padding_size)

        return encrypted, padding_size

    @classmethod
    def decrypt_message(
        cls,
        ciphertext: bytes,
        session_key: bytes,
        from_id: str,
        to_id: str,
        phrase: Optional[str] = None,
    ) -> Optional[str]:
        """
        Расшифровка сообщения.

        Args:
            ciphertext: Зашифрованные данные
            session_key: 32-байтовый сессионный ключ
            from_id: Public ID отправителя
            to_id: Public ID получателя
            phrase: Дополнительная фраза (опционально)

        Returns:
            Расшифрованный текст или None при ошибке
        """
        # Получаем направленный ключ
        directional_key = cls.get_directional_key(session_key, from_id, to_id)

        try:
            if phrase:
                # Формат: salt(16) + nonce(12) + ciphertext
                if len(ciphertext) < 28:
                    return None
                salt = ciphertext[:16]
                nonce = ciphertext[16:28]
                encrypted = ciphertext[28:]

                phrase_key = cls.derive_phrase_key(phrase, salt)
                combined_key = cls.xor_keys(directional_key, phrase_key)

                aesgcm = AESGCM(combined_key)
                decrypted = aesgcm.decrypt(nonce, encrypted, None)
                return decrypted.decode('utf-8')
            else:
                # Формат: nonce(12) + ciphertext
                if len(ciphertext) < 12:
                    return None
                nonce = ciphertext[:12]
                encrypted = ciphertext[12:]

                aesgcm = AESGCM(directional_key)
                decrypted = aesgcm.decrypt(nonce, encrypted, None)
                return decrypted.decode('utf-8')
        except Exception:
            return None

    @classmethod
    def decrypt_message_with_padding(
        cls,
        ciphertext: bytes,
        session_key: bytes,
        from_id: str,
        to_id: str,
        original_size: int,
        phrase: Optional[str] = None,
    ) -> Optional[str]:
        """
        Расшифровка сообщения с удалением паддинга.

        Args:
            ciphertext: Зашифрованные данные (могут содержать паддинг)
            session_key: 32-байтовый сессионный ключ
            from_id: Public ID отправителя
            to_id: Public ID получателя
            original_size: Исходный размер зашифрованных данных без паддинга
            phrase: Дополнительная фраза (опционально)

        Returns:
            Расшифрованный текст или None при ошибке
        """
        # Удаляем паддинг
        if len(ciphertext) > original_size:
            ciphertext = ciphertext[:original_size]

        return cls.decrypt_message(ciphertext, session_key, from_id, to_id, phrase)

    @staticmethod
    def generate_message_id(counter: int) -> str:
        """
        Генерация уникального ID сообщения со встроенным счётчиком.

        Args:
            counter: Счётчик сообщения (0-65535)

        Returns:
            message_id в формате msg_{counter:04x}_{random}
        """
        return generate_message_id_with_counter(counter)

    @staticmethod
    def extract_counter_from_message_id(message_id: str) -> int:
        """
        Извлечение счётчика из message_id.

        Args:
            message_id: ID сообщения

        Returns:
            Счётчик (0 если не удалось извлечь)
        """
        return extract_counter_from_message_id(message_id)


# Для обратной совместимости с импортами из screens
CryptoHelper = ClientCrypto
