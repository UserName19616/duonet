# tests/unit/mock_ws_manager.py
"""
Заглушка для WebSocketManager.
"""

from typing import Any, Dict, List, Optional


class MockWebSocketManager:
    """Заглушка для WebSocketManager с поддержкой тестов."""

    def __init__(self):
        self._connections: Dict[str, Any] = {}

    def get_connection(self, public_id: str) -> Optional[Any]:
        return self._connections.get(public_id)

    def get_all_connections(self) -> List[Dict[str, Any]]:
        return [{"public_id": pid, "connected_at": 123456} for pid in self._connections]

    def get_connection_count(self) -> int:
        return len(self._connections)

    def add_connection(self, websocket, public_id: str, client_ip: str, **kwargs) -> None:
        self._connections[public_id] = websocket

    def remove_connection(self, public_id: str) -> bool:
        if public_id in self._connections:
            del self._connections[public_id]
            return True
        return False

    def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        return True

    def update_heartbeat(self, public_id: str) -> None:
        pass
