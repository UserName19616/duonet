# src/server/network/rendezvous/rendezvous_client.py
"""
Клиент для взаимодействия с сервером знакомств (Rendezvous Server).
"""

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from src.common.identity.public_id import extract_region, is_server_id, is_valid_format


class RendezvousClient:
    def __init__(self, rendezvous_url: str, cache_ttl: int = 3600):
        self._base_url = rendezvous_url.rstrip("/")
        self._cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}
        self._session = requests.Session()
        self._session.timeout = 5

    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        self._cache[key] = (data, time.time())

    def invalidate_cache(self, key: Optional[str] = None) -> None:
        if key is None:
            self._cache.clear()
        elif key in self._cache:
            del self._cache[key]

    def find_server_by_id(self, public_id: str) -> Optional[Dict[str, Any]]:
        if not is_valid_format(public_id) or not is_server_id(public_id):
            return None

        cache_key = f"server:{public_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            response = self._session.get(urljoin(self._base_url, f"/api/lookup/{public_id}"))
            if response.status_code != 200:
                return None
            data = response.json()
            server = data.get("server")
            if server:
                self._set_cache(cache_key, server)
            return server
        except requests.RequestException:
            return None

    def find_servers_by_region(self, region: str, server_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if len(region) != 2 or not region.isalpha():
            return []

        cache_key = f"region:{region}:{server_type}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            response = self._session.get(urljoin(self._base_url, f"/api/region/{region}"))
            if response.status_code != 200:
                return []
            data = response.json()
            servers = data.get("servers", [])
            if server_type:
                servers = [s for s in servers if s.get("type") == server_type]
            self._set_cache(cache_key, servers)
            return servers
        except requests.RequestException:
            return []

    def find_validators_by_region(self, region: str) -> List[Dict[str, Any]]:
        return self.find_servers_by_region(region, server_type="validator")

    def find_nat_servers_by_region(self, region: str) -> List[Dict[str, Any]]:
        return self.find_servers_by_region(region, server_type="nat")

    def get_servers_by_region_with_load(self, region: str) -> List[Dict[str, Any]]:
        if len(region) != 2 or not region.isalpha():
            return []

        cache_key = f"region_load:{region}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            response = self._session.get(urljoin(self._base_url, f"/api/region/{region}/with-load"))
            if response.status_code != 200:
                return []
            data = response.json()
            servers = data.get("servers", [])
            self._set_cache(cache_key, servers)
            return servers
        except requests.RequestException:
            return []

    def resolve_contact(self, identifier: str) -> Optional[Dict[str, Any]]:
        if not identifier:
            return None

        if identifier.startswith("@*.") and not identifier.endswith(".srv"):
            region = identifier[3:]
            if len(region) == 2:
                servers = self.find_servers_by_region(region)
                return {"type": "list", "items": servers}

        if identifier.startswith("@*.") and identifier.endswith(".srv"):
            region = identifier[3:-4]
            if len(region) == 2:
                servers = self.find_servers_by_region(region, server_type="nat")
                return {"type": "list", "items": servers}

        if is_valid_format(identifier):
            if is_server_id(identifier):
                return self.find_server_by_id(identifier)

        return None

    def register_server(
        self,
        public_id: str,
        server_type: str,
        region: str,
        ws_url: str,
        capacity: int = 1000,
        provides_proxy: bool = False,
    ) -> bool:
        if not is_valid_format(public_id) or not is_server_id(public_id):
            return False

        data = {
            "public_id": public_id,
            "type": server_type,
            "region": region,
            "ws_url": ws_url,
            "capacity": capacity,
            "provides_proxy": provides_proxy,
        }

        try:
            response = self._session.post(urljoin(self._base_url, "/api/register"), json=data)
            success = response.status_code == 201
            if success:
                self.invalidate_cache()
            return success
        except requests.RequestException:
            return False

    def send_heartbeat(self, public_id: str, load: Optional[int] = None) -> bool:
        if not is_valid_format(public_id) or not is_server_id(public_id):
            return False

        params = {"public_id": public_id}
        if load is not None:
            params["load"] = load

        try:
            response = self._session.post(urljoin(self._base_url, "/api/heartbeat"), params=params)
            success = response.status_code == 200
            if success:
                self.invalidate_cache(f"server:{public_id}")
            return success
        except requests.RequestException:
            return False

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
