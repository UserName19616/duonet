# src/client/state_manager.py
"""
Управление состоянием TUI приложения.
"""

from typing import Dict, Optional


class StateManager:
    def __init__(self):
        self._token: Optional[str] = None
        self._public_id: Optional[str] = None
        self._is_server: bool = False
        self._phrase_cache: Dict[str, str] = {}
        self._seed_phrase: Optional[str] = None
        self._selected_region: str = "ru"
        self._charter_accepted: bool = False
        self._selected_lang: str = "ru"
        self._creating_client: bool = False

    @property
    def token(self) -> Optional[str]:
        return self._token

    @token.setter
    def token(self, value: Optional[str]) -> None:
        self._token = value

    @property
    def public_id(self) -> Optional[str]:
        return self._public_id

    @public_id.setter
    def public_id(self, value: Optional[str]) -> None:
        self._public_id = value

    @property
    def is_server(self) -> bool:
        return self._is_server

    @is_server.setter
    def is_server(self, value: bool) -> None:
        self._is_server = value

    def is_authenticated(self) -> bool:
        return self._token is not None and self._public_id is not None

    def clear_auth(self) -> None:
        self._token = None
        self._public_id = None
        self._is_server = False
        self._phrase_cache.clear()

    def save_phrase(self, contact_id: str, phrase: str) -> None:
        self._phrase_cache[contact_id] = phrase

    def get_phrase(self, contact_id: str) -> Optional[str]:
        return self._phrase_cache.get(contact_id)

    def forget_phrase(self, contact_id: str) -> None:
        self._phrase_cache.pop(contact_id, None)

    def clear_all_phrases(self) -> None:
        self._phrase_cache.clear()

    @property
    def seed_phrase(self) -> Optional[str]:
        return self._seed_phrase

    @seed_phrase.setter
    def seed_phrase(self, value: Optional[str]) -> None:
        self._seed_phrase = value

    @property
    def selected_region(self) -> str:
        return self._selected_region

    @selected_region.setter
    def selected_region(self, value: str) -> None:
        self._selected_region = value.lower()

    @property
    def charter_accepted(self) -> bool:
        return self._charter_accepted

    @charter_accepted.setter
    def charter_accepted(self, value: bool) -> None:
        self._charter_accepted = value

    @property
    def selected_lang(self) -> str:
        return self._selected_lang

    @selected_lang.setter
    def selected_lang(self, value: str) -> None:
        self._selected_lang = value.lower()[:2]

    @property
    def creating_client(self) -> bool:
        return self._creating_client

    @creating_client.setter
    def creating_client(self, value: bool) -> None:
        self._creating_client = value

    def reset(self) -> None:
        self._token = None
        self._public_id = None
        self._is_server = False
        self._phrase_cache.clear()
        self._seed_phrase = None
        self._selected_region = "ru"
        self._charter_accepted = False
        self._selected_lang = "ru"
        self._creating_client = False

    def get_debug_info(self) -> Dict[str, any]:
        return {
            "authenticated": self.is_authenticated(),
            "public_id": self._public_id,
            "is_server": self._is_server,
            "selected_region": self._selected_region,
            "selected_lang": self._selected_lang,
            "charter_accepted": self._charter_accepted,
            "creating_client": self._creating_client,
            "phrases_count": len(self._phrase_cache),
        }
