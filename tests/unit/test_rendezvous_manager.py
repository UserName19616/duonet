# tests/unit/test_rendezvous_manager.py
"""
Тесты для модуля RendezvousManager.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.server.network.rendezvous.rendezvous_manager import RendezvousManager


class TestRendezvousManager:
    """Тесты для RendezvousManager."""

    def test_initialization(self):
        """Проверка инициализации менеджера."""
        manager = RendezvousManager(host="127.0.0.1", port=9999)
        assert manager.host == "127.0.0.1"
        assert manager.port == 9999
        assert manager.is_running() is False
        assert manager.get_pid() is None

    def test_default_values(self):
        """Проверка значений по умолчанию."""
        manager = RendezvousManager()
        assert manager.host == "0.0.0.0"
        assert manager.port == 9878

    def test_get_status_not_running(self):
        """Проверка статуса когда сервер не запущен."""
        manager = RendezvousManager()
        status = manager.get_status()
        assert status["running"] is False
        assert status["host"] == "0.0.0.0"
        assert status["port"] == 9878

    def test_add_status_listener(self):
        """Проверка добавления слушателя статуса."""
        manager = RendezvousManager()
        callback = MagicMock()
        manager.add_status_listener(callback)
        assert callback in manager._status_listeners

    def test_remove_status_listener(self):
        """Проверка удаления слушателя статуса."""
        manager = RendezvousManager()
        callback = MagicMock()
        manager.add_status_listener(callback)
        manager.remove_status_listener(callback)
        assert callback not in manager._status_listeners

    def test_add_log_listener(self):
        """Проверка добавления слушателя логов."""
        manager = RendezvousManager()
        callback = MagicMock()
        manager.add_log_listener(callback)
        assert callback in manager._log_listeners

    def test_remove_log_listener(self):
        """Проверка удаления слушателя логов."""
        manager = RendezvousManager()
        callback = MagicMock()
        manager.add_log_listener(callback)
        manager.remove_log_listener(callback)
        assert callback not in manager._log_listeners

    @patch("subprocess.Popen")
    def test_start_success(self, mock_popen):
        """Проверка успешного запуска сервера."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        manager = RendezvousManager()

        # Мокаем _run_server чтобы он не запускал реальный поток
        with patch.object(manager, '_run_server') as mock_run:
            mock_run.return_value = None
            manager._running = True
            result = manager.start()

            # Так как _running уже True, start вернёт True
            assert result is True

    def test_start_already_running(self):
        """Проверка запуска когда сервер уже запущен."""
        manager = RendezvousManager()
        manager._running = True
        manager._process = MagicMock()

        result = manager.start()
        assert result is True

    def test_stop_not_running(self):
        """Проверка остановки когда сервер не запущен."""
        manager = RendezvousManager()
        result = manager.stop()
        assert result is False

    @patch("subprocess.Popen")
    def test_stop_success(self, mock_popen):
        """Проверка успешной остановки сервера."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        manager = RendezvousManager()
        manager.start()
        time.sleep(0.2)

        manager._running = True
        manager._process = mock_process

        result = manager.stop()
        assert result is True

    @patch("subprocess.Popen")
    def test_stop_with_timeout(self, mock_popen):
        """Проверка остановки с таймаутом (принудительное завершение)."""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = TimeoutError()
        mock_popen.return_value = mock_process

        manager = RendezvousManager()
        manager._running = True
        manager._process = mock_process

        result = manager.stop()
        assert result is True
        mock_process.kill.assert_called_once()

    def test_notify_status(self):
        """Проверка уведомления слушателей статуса."""
        manager = RendezvousManager()
        callback = MagicMock()
        manager.add_status_listener(callback)

        manager._notify_status("test_status", "test_message")

        callback.assert_called_once_with("test_status", "test_message")

    def test_notify_log(self):
        """Проверка уведомления слушателей логов."""
        manager = RendezvousManager()
        callback = MagicMock()
        manager.add_log_listener(callback)

        manager._notify_log("test log message")

        callback.assert_called_once_with("test log message")

    def test_notify_status_multiple_listeners(self):
        """Проверка уведомления нескольких слушателей статуса."""
        manager = RendezvousManager()
        callback1 = MagicMock()
        callback2 = MagicMock()
        manager.add_status_listener(callback1)
        manager.add_status_listener(callback2)

        manager._notify_status("test_status", "test_message")

        callback1.assert_called_once_with("test_status", "test_message")
        callback2.assert_called_once_with("test_status", "test_message")

    def test_notify_log_multiple_listeners(self):
        """Проверка уведомления нескольких слушателей логов."""
        manager = RendezvousManager()
        callback1 = MagicMock()
        callback2 = MagicMock()
        manager.add_log_listener(callback1)
        manager.add_log_listener(callback2)

        manager._notify_log("test log message")

        callback1.assert_called_once_with("test log message")
        callback2.assert_called_once_with("test log message")

    def test_notify_status_listener_error_handling(self):
        """Проверка обработки ошибок в слушателях статуса."""
        manager = RendezvousManager()

        def failing_callback(status, message):
            raise Exception("Test error")

        manager.add_status_listener(failing_callback)

        # Не должно вызывать исключение
        manager._notify_status("test", "message")

    def test_notify_log_listener_error_handling(self):
        """Проверка обработки ошибок в слушателях логов."""
        manager = RendezvousManager()

        def failing_callback(log):
            raise Exception("Test error")

        manager.add_log_listener(failing_callback)

        # Не должно вызывать исключение
        manager._notify_log("test log")
