# src/network/gossip/message.py
"""
Структура gossip-сообщения.
"""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class GossipMessage:
    """Структура gossip-сообщения."""

    sender_id: str
    timestamp: int
    nonce: str
    payload: Dict[str, Any]
    signature: str

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь."""
        return {
            "sender_id": self.sender_id,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "payload": self.payload,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GossipMessage":
        """Создание из словаря."""
        return cls(
            sender_id=data["sender_id"],
            timestamp=data["timestamp"],
            nonce=data["nonce"],
            payload=data["payload"],
            signature=data["signature"],
        )
