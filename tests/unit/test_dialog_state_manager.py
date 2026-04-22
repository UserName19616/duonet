#!/usr/bin/env python3
"""
Тесты для DialogStateManager
Управление состоянием диалогов, счётчиками сообщений и паддингом
"""

import pytest
import tempfile

from src.client.messaging.dialog_state import DialogStateManager
from src.client.crypto.pfs import DialogState
from src.common.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = SQLiteStorage(f.name)
        yield db
        db.close()


@pytest.fixture
def dialog_manager():
    return DialogStateManager()


class TestDialogStateManagerInit:
    """Тесты инициализации"""

    def test_init(self, dialog_manager):
        """Проверка создания менеджера"""
        assert dialog_manager is not None
        assert dialog_manager._dialog_states == {}
        assert dialog_manager._dialog_padding_state == {}
        assert dialog_manager._dialog_message_counter == {}


class TestDialogStateManagerStates:
    """Тесты управления состоянием диалогов"""

    def test_get_dialog_state_not_found(self, dialog_manager):
        """Получение несуществующего состояния"""
        state = dialog_manager.get_dialog_state("alice:bob")
        assert state is None

    def test_set_and_get_dialog_state(self, dialog_manager):
        """Установка и получение состояния"""
        dialog_id = "alice:bob"
        session_key = b"test_key_32_bytes_test_key_32_b"

        state = DialogState(
            contact_id="bob",
            session_key=session_key,
            current_key=session_key,
            outgoing_counter=0,
            incoming_counter=0,
        )

        dialog_manager.set_dialog_state(dialog_id, state)
        retrieved = dialog_manager.get_dialog_state(dialog_id)

        assert retrieved is not None
        assert retrieved.contact_id == "bob"
        assert retrieved.session_key == session_key
        assert retrieved.outgoing_counter == 0

    def test_update_existing_state(self, dialog_manager):
        """Обновление существующего состояния"""
        dialog_id = "alice:bob"
        session_key = b"test_key_32_bytes_test_key_32_b"

        state = DialogState(
            contact_id="bob",
            session_key=session_key,
            current_key=session_key,
            outgoing_counter=0,
            incoming_counter=0,
        )

        dialog_manager.set_dialog_state(dialog_id, state)

        # Обновляем счётчик
        state.outgoing_counter = 5
        dialog_manager.set_dialog_state(dialog_id, state)

        retrieved = dialog_manager.get_dialog_state(dialog_id)
        assert retrieved.outgoing_counter == 5


class TestDialogStateManagerPadding:
    """Тесты управления паддингом"""

    def test_get_padding_default(self, dialog_manager):
        """Получение паддинга по умолчанию (0)"""
        padding = dialog_manager.get_padding("alice:bob")
        assert padding == 0

    def test_set_and_get_padding(self, dialog_manager):
        """Установка и получение паддинга"""
        dialog_id = "alice:bob"
        expected_padding = 64

        dialog_manager.set_padding(dialog_id, expected_padding)
        padding = dialog_manager.get_padding(dialog_id)

        assert padding == expected_padding

    def test_update_padding(self, dialog_manager):
        """Обновление паддинга"""
        dialog_id = "alice:bob"

        dialog_manager.set_padding(dialog_id, 32)
        assert dialog_manager.get_padding(dialog_id) == 32

        dialog_manager.set_padding(dialog_id, 64)
        assert dialog_manager.get_padding(dialog_id) == 64

    def test_multiple_dialogs_padding(self, dialog_manager):
        """Разные диалоги имеют разные паддинги"""
        dialog1 = "alice:bob"
        dialog2 = "alice:charlie"

        dialog_manager.set_padding(dialog1, 32)
        dialog_manager.set_padding(dialog2, 64)

        assert dialog_manager.get_padding(dialog1) == 32
        assert dialog_manager.get_padding(dialog2) == 64


class TestDialogStateManagerCounters:
    """Тесты управления счётчиками сообщений"""

    def test_get_next_counter_first(self, dialog_manager):
        """Первый счётчик = 0"""
        dialog_id = "alice:bob"
        counter = dialog_manager.get_next_counter(dialog_id)
        assert counter == 0

    def test_get_next_counter_increments(self, dialog_manager):
        """Последовательные вызовы увеличивают счётчик"""
        dialog_id = "alice:bob"

        counter0 = dialog_manager.get_next_counter(dialog_id)
        counter1 = dialog_manager.get_next_counter(dialog_id)
        counter2 = dialog_manager.get_next_counter(dialog_id)

        assert counter0 == 0
        assert counter1 == 1
        assert counter2 == 2

    def test_multiple_dialogs_counters(self, dialog_manager):
        """Разные диалоги имеют независимые счётчики"""
        dialog1 = "alice:bob"
        dialog2 = "alice:charlie"

        # Диалог 1
        assert dialog_manager.get_next_counter(dialog1) == 0
        assert dialog_manager.get_next_counter(dialog1) == 1

        # Диалог 2 (счётчик не зависит от диалога 1)
        assert dialog_manager.get_next_counter(dialog2) == 0
        assert dialog_manager.get_next_counter(dialog2) == 1

        # Диалог 1 продолжает свой счёт
        assert dialog_manager.get_next_counter(dialog1) == 2

    def test_counter_persistence(self, dialog_manager):
        """Счётчики сохраняются между вызовами"""
        dialog_id = "alice:bob"

        dialog_manager.get_next_counter(dialog_id)  # 0
        dialog_manager.get_next_counter(dialog_id)  # 1
        dialog_manager.get_next_counter(dialog_id)  # 2

        # Новый экземпляр менеджера должен помнить счётчики
        new_manager = DialogStateManager()
        new_manager._dialog_message_counter = dialog_manager._dialog_message_counter.copy()

        assert new_manager.get_next_counter(dialog_id) == 3


class TestDialogStateManagerIntegration:
    """Интеграционные тесты (состояние + паддинг + счётчик)"""

    def test_full_dialog_state(self, dialog_manager):
        """Полное состояние диалога"""
        dialog_id = "alice:bob"
        session_key = b"test_key_32_bytes_test_key_32_b"

        # 1. Создаём состояние
        state = DialogState(
            contact_id="bob",
            session_key=session_key,
            current_key=session_key,
            outgoing_counter=0,
            incoming_counter=0,
        )
        dialog_manager.set_dialog_state(dialog_id, state)

        # 2. Устанавливаем паддинг
        dialog_manager.set_padding(dialog_id, 32)

        # 3. Отправляем несколько сообщений
        counters = []
        for i in range(5):
            counter = dialog_manager.get_next_counter(dialog_id)
            counters.append(counter)

            # Обновляем паддинг после каждого сообщения
            dialog_manager.set_padding(dialog_id, 32 + i * 8)

        assert counters == [0, 1, 2, 3, 4]

        # 4. Проверяем финальное состояние
        final_state = dialog_manager.get_dialog_state(dialog_id)
        assert final_state.outgoing_counter == 0  # Не изменился (только incoming?)

        final_padding = dialog_manager.get_padding(dialog_id)
        assert final_padding == 32 + 4 * 8  # 32 + 32 = 64

    def test_multiple_users_independent(self, dialog_manager):
        """Состояния разных пользователей независимы"""
        alice_bob = "alice:bob"
        alice_charlie = "alice:charlie"
        bob_alice = "bob:alice"

        session_key = b"test_key_32_bytes_test_key_32_b"

        # Создаём состояния
        state1 = DialogState(contact_id="bob", session_key=session_key, current_key=session_key)
        state2 = DialogState(contact_id="charlie", session_key=session_key, current_key=session_key)
        state3 = DialogState(contact_id="alice", session_key=session_key, current_key=session_key)

        dialog_manager.set_dialog_state(alice_bob, state1)
        dialog_manager.set_dialog_state(alice_charlie, state2)
        dialog_manager.set_dialog_state(bob_alice, state3)

        # Разные счётчики
        assert dialog_manager.get_next_counter(alice_bob) == 0
        assert dialog_manager.get_next_counter(alice_charlie) == 0
        assert dialog_manager.get_next_counter(bob_alice) == 0

        # Разные паддинги
        dialog_manager.set_padding(alice_bob, 32)
        dialog_manager.set_padding(alice_charlie, 64)
        dialog_manager.set_padding(bob_alice, 128)

        assert dialog_manager.get_padding(alice_bob) == 32
        assert dialog_manager.get_padding(alice_charlie) == 64
        assert dialog_manager.get_padding(bob_alice) == 128


class TestDialogStateManagerEdgeCases:
    """Пограничные случаи"""

    def test_empty_dialog_id(self, dialog_manager):
        """Пустой ID диалога"""
        counter = dialog_manager.get_next_counter("")
        assert counter == 0

        dialog_manager.set_padding("", 32)
        assert dialog_manager.get_padding("") == 32

    def test_very_long_dialog_id(self, dialog_manager):
        """Очень длинный ID диалога"""
        long_id = "x" * 1000 + ":" + "y" * 1000

        dialog_manager.set_padding(long_id, 999)
        assert dialog_manager.get_padding(long_id) == 999

        counter = dialog_manager.get_next_counter(long_id)
        assert counter == 0

    def test_special_characters_in_dialog_id(self, dialog_manager):
        """Спецсимволы в ID диалога"""
        special_id = "user@domain.com:user2@domain.com"

        dialog_manager.set_padding(special_id, 42)
        assert dialog_manager.get_padding(special_id) == 42

        dialog_manager.get_next_counter(special_id)
        assert dialog_manager.get_next_counter(special_id) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
