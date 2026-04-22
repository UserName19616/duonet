#!/usr/bin/env python3
"""
Модульные тесты для MessageSender (без БД)
"""

import pytest
from unittest.mock import MagicMock

from src.client.messaging.message_sender import MessageSender


class TestMessageSenderUnit:
    """Модульные тесты MessageSender"""

    def test_check_contact_exists_returns_false_for_unknown(self):
        """Неизвестный контакт -> False"""
        mock_account = MagicMock()
        mock_invite = MagicMock()
        mock_invite.get_contacts.return_value = []

        sender = MessageSender(
            account_manager=mock_account,
            messages_storage=MagicMock(),
            invite_protocol=mock_invite,
            ws_manager=MagicMock(),
            storage=MagicMock(),
            rotation_manager=MagicMock(),
            dialog_manager=MagicMock(),
        )

        result = sender._check_contact_exists("alice", "bob")
        assert result is False

    def test_check_contact_exists_returns_true_for_known(self):
        """Известный контакт -> True"""
        mock_account = MagicMock()
        mock_invite = MagicMock()
        mock_invite.get_contacts.return_value = ["bob"]

        sender = MessageSender(
            account_manager=mock_account,
            messages_storage=MagicMock(),
            invite_protocol=mock_invite,
            ws_manager=MagicMock(),
            storage=MagicMock(),
            rotation_manager=MagicMock(),
            dialog_manager=MagicMock(),
        )

        result = sender._check_contact_exists("alice", "bob")
        assert result is True

    def test_get_dialog_id(self):
        """Формирование ID диалога"""
        mock_account = MagicMock()
        sender = MessageSender(
            account_manager=mock_account,
            messages_storage=MagicMock(),
            invite_protocol=MagicMock(),
            ws_manager=MagicMock(),
            storage=MagicMock(),
            rotation_manager=MagicMock(),
            dialog_manager=MagicMock(),
        )

        # alice < bob
        dialog_id = sender._get_dialog_id("alice", "bob")
        assert dialog_id == "alice:bob"

        # bob > alice (порядок должен сохраняться)
        dialog_id2 = sender._get_dialog_id("bob", "alice")
        assert dialog_id2 == "alice:bob"
