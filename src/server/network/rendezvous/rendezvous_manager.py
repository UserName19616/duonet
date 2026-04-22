# src/server/network/rendezvous/rendezvous_manager.py
"""
Менеджер для управления Rendezvous Server процессом.
"""

import logging
import subprocess
import sys
import threading
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class RendezvousManager:
    def __init__(self, host: str = "0.0.0.0", port: int = 9878, log_file: str = "rendezvous.log"):
        self.host = host
        self.port = port
        self.log_file = log_file
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._status_listeners: list[Callable[[str, str], None]] = []
        self._log_listeners: list[Callable[[str], None]] = []

    def add_status_listener(self, listener: Callable[[str, str], None]) -> None:
        self._status_listeners.append(listener)

    def add_log_listener(self, listener: Callable[[str], None]) -> None:
        self._log_listeners.append(listener)

    def remove_status_listener(self, listener: Callable[[str, str], None]) -> None:
        if listener in self._status_listeners:
            self._status_listeners.remove(listener)

    def remove_log_listener(self, listener: Callable[[str], None]) -> None:
        if listener in self._log_listeners:
            self._log_listeners.remove(listener)

    def _notify_status(self, status: str, message: str) -> None:
        for listener in self._status_listeners:
            try:
                listener(status, message)
            except Exception as e:
                logger.error(f"Status listener error: {e}")

    def _notify_log(self, log: str) -> None:
        for listener in self._log_listeners:
            try:
                listener(log)
            except Exception as e:
                logger.error(f"Log listener error: {e}")

    def _run_server(self) -> None:
        try:
            self._notify_log(f"[{time.strftime('%H:%M:%S')}] Запуск Rendezvous сервера на {self.host}:{self.port}...")

            import os
            log_path = os.path.join("logs", self.log_file)
            os.makedirs("logs", exist_ok=True)
            log_fd = open(log_path, "a")

            cmd = [
                sys.executable, "-m", "src.server.network.rendezvous.rendezvous_server",
                "--host", self.host,
                "--port", str(self.port)
            ]

            self._process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=log_fd,
                text=True,
                bufsize=1
            )

            self._running = True
            self._notify_status("running", f"Сервер запущен на порту {self.port}")
            self._notify_log(f"[{time.strftime('%H:%M:%S')}] Rendezvous сервер запущен (PID: {self._process.pid})")

            return_code = self._process.wait()
            log_fd.close()

            if self._running:
                self._running = False
                self._notify_status("stopped", f"Сервер остановлен (код: {return_code})")
                self._notify_log(f"[{time.strftime('%H:%M:%S')}] Rendezvous сервер остановлен")

        except FileNotFoundError as e:
            self._running = False
            self._notify_status("error", f"Не найден Python: {e}")
            self._notify_log(f"[{time.strftime('%H:%M:%S')}] ❌ Ошибка: {e}")
        except Exception as e:
            self._running = False
            self._notify_status("error", f"Ошибка: {e}")
            self._notify_log(f"[{time.strftime('%H:%M:%S')}] ❌ Ошибка: {e}")

    def start(self) -> bool:
        if self._running:
            self._notify_log(f"[{time.strftime('%H:%M:%S')}] Сервер уже запущен")
            return True

        if self._thread and self._thread.is_alive():
            self._notify_log(f"[{time.strftime('%H:%M:%S')}] Сервер уже запускается")
            return False

        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        time.sleep(0.5)
        return self._running

    def start_background(self) -> bool:
        if self._running:
            return True

        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        time.sleep(1)
        return self._running

    def stop(self) -> bool:
        if not self._running or not self._process:
            return False

        self._running = False
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except (subprocess.TimeoutExpired, TimeoutError):
            self._process.kill()
            try:
                self._process.wait(timeout=2)
            except (subprocess.TimeoutExpired, TimeoutError):
                pass

        return True

    def is_running(self) -> bool:
        if not self._running or not self._process:
            return False
        return self._process.poll() is None

    def get_status(self) -> dict:
        return {
            "running": self.is_running(),
            "host": self.host,
            "port": self.port,
        }

    def get_pid(self) -> Optional[int]:
        return self._process.pid if self._process else None
