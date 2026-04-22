# src/server/network/rendezvous/rendezvous_server.py
"""
Сервер знакомств (Rendezvous Server).
"""

import asyncio
import argparse
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from aiohttp import web

from src.common.identity.public_id import extract_region, is_server_id, is_valid_format
from src.config import SERVER_TTL_SECONDS, CLEANUP_INTERVAL_SECONDS

logger = logging.getLogger(__name__)


@dataclass
class ServerInfo:
    public_id: str
    type: str
    region: str
    ws_url: str
    capacity: int
    load: int = 0
    last_seen: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + SERVER_TTL_SECONDS)

    def is_active(self) -> bool:
        return time.time() < self.expires_at


class ServerStore:
    def __init__(self):
        self._servers: Dict[str, ServerInfo] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

    async def register(self, server: ServerInfo) -> None:
        async with self._lock:
            self._servers[server.public_id] = server
            logger.info(f"Server registered: {server.public_id}")

    async def heartbeat(self, public_id: str, load: Optional[int] = None) -> Optional[ServerInfo]:
        async with self._lock:
            server = self._servers.get(public_id)
            if not server:
                return None
            server.last_seen = time.time()
            server.expires_at = time.time() + SERVER_TTL_SECONDS
            if load is not None:
                server.load = max(0, min(100, load))
            return server

    async def get(self, public_id: str) -> Optional[ServerInfo]:
        async with self._lock:
            server = self._servers.get(public_id)
            if server and server.is_active():
                return server
            return None

    async def get_by_region(self, region: str) -> List[ServerInfo]:
        async with self._lock:
            return [s for s in self._servers.values() if s.region == region and s.is_active()]

    async def get_by_region_with_load(self, region: str) -> List[ServerInfo]:
        servers = await self.get_by_region(region)
        servers = [s for s in servers if s.load <= 90]
        servers.sort(key=lambda s: s.load)
        return servers

    async def get_all_active(self) -> List[ServerInfo]:
        async with self._lock:
            return [s for s in self._servers.values() if s.is_active()]

    async def cleanup(self) -> int:
        async with self._lock:
            expired = [pid for pid, s in self._servers.items() if not s.is_active()]
            for pid in expired:
                del self._servers[pid]
            self._last_cleanup = time.time()
            return len(expired)


class RendezvousServer:
    def __init__(self):
        self._store = ServerStore()
        self._app = None
        self._runner = None
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._start_time: Optional[float] = None

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/register", self.handle_register)
        app.router.add_post("/api/heartbeat", self.handle_heartbeat)
        app.router.add_get("/api/lookup/{public_id}", self.handle_lookup)
        app.router.add_get("/api/region/{region}", self.handle_region)
        app.router.add_get("/api/region/{region}/with-load", self.handle_region_with_load)
        app.router.add_get("/api/health", self.handle_health)
        app.router.add_get("/api/stats", self.handle_stats)
        return app

    async def handle_register(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        public_id = data.get("public_id")
        server_type = data.get("type")
        region = data.get("region")
        ws_url = data.get("ws_url")
        capacity = data.get("capacity", 1000)

        if not is_valid_format(public_id):
            return web.json_response({"error": "Invalid Public ID format"}, status=400)
        if not is_server_id(public_id):
            return web.json_response({"error": "Public ID must be a server ID (ends with .srv)"}, status=400)
        if server_type not in ("validator", "nat"):
            return web.json_response({"error": "Type must be 'validator' or 'nat'"}, status=400)
        if not region or len(region) != 2 or not region.isalpha():
            return web.json_response({"error": "Region must be 2-letter code"}, status=400)

        extracted_region = extract_region(public_id)
        if extracted_region != region:
            return web.json_response({"error": f"Region mismatch: ID has {extracted_region}, but got {region}"}, status=400)

        server = ServerInfo(public_id=public_id, type=server_type, region=region, ws_url=ws_url, capacity=capacity)
        await self._store.register(server)

        return web.json_response({
            "public_id": server.public_id,
            "type": server.type,
            "region": server.region,
            "ws_url": server.ws_url,
            "capacity": server.capacity,
            "load": server.load,
            "expires_at": server.expires_at,
        }, status=201)

    async def handle_heartbeat(self, request: web.Request) -> web.Response:
        public_id = request.query.get("public_id")
        if not public_id:
            return web.json_response({"error": "Missing public_id parameter"}, status=400)

        load_str = request.query.get("load")
        load = int(load_str) if load_str and load_str.isdigit() else None

        server = await self._store.heartbeat(public_id, load)
        if not server:
            return web.json_response({"error": "Server not found"}, status=404)

        return web.json_response({
            "public_id": server.public_id,
            "load": server.load,
            "expires_at": server.expires_at,
        })

    async def handle_lookup(self, request: web.Request) -> web.Response:
        public_id = request.match_info.get("public_id")
        if not public_id:
            return web.json_response({"error": "Missing public_id"}, status=400)

        server = await self._store.get(public_id)
        if not server:
            return web.json_response({"server": None})

        return web.json_response({
            "server": {
                "public_id": server.public_id,
                "type": server.type,
                "region": server.region,
                "ws_url": server.ws_url,
                "capacity": server.capacity,
                "load": server.load,
                "last_seen": server.last_seen,
                "expires_at": server.expires_at,
            }
        })

    async def handle_region(self, request: web.Request) -> web.Response:
        region = request.match_info.get("region")
        if not region or len(region) != 2 or not region.isalpha():
            return web.json_response({"error": "Region must be 2-letter code"}, status=400)

        servers = await self._store.get_by_region(region)

        return web.json_response({
            "servers": [{
                "public_id": s.public_id,
                "type": s.type,
                "region": s.region,
                "ws_url": s.ws_url,
                "capacity": s.capacity,
                "load": s.load,
                "last_seen": s.last_seen,
                "expires_at": s.expires_at,
            } for s in servers]
        })

    async def handle_region_with_load(self, request: web.Request) -> web.Response:
        region = request.match_info.get("region")
        if not region or len(region) != 2 or not region.isalpha():
            return web.json_response({"error": "Region must be 2-letter code"}, status=400)

        servers = await self._store.get_by_region_with_load(region)

        return web.json_response({
            "servers": [{
                "public_id": s.public_id,
                "type": s.type,
                "ws_url": s.ws_url,
                "load": s.load,
                "capacity": s.capacity,
                "last_seen": s.last_seen,
                "expires_at": s.expires_at,
            } for s in servers]
        })

    async def handle_health(self, request: web.Request) -> web.Response:
        active = await self._store.get_all_active()
        return web.json_response({
            "status": "healthy",
            "servers": len(active),
            "uptime": time.time() - self._start_time if self._start_time else 0,
        })

    async def handle_stats(self, request: web.Request) -> web.Response:
        active = await self._store.get_all_active()
        by_region = {}
        for s in active:
            by_region[s.region] = by_region.get(s.region, 0) + 1

        return web.json_response({
            "total_servers": len(active),
            "active_servers": len(active),
            "by_region": by_region,
        })

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            count = await self._store.cleanup()
            if count > 0:
                logger.info(f"Cleaned up {count} expired servers")

    async def start(self, host: str = "0.0.0.0", port: int = 9878) -> None:
        if self._running:
            logger.warning("Server already running")
            return

        self._start_time = time.time()
        self._running = True
        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Rendezvous server started on {host}:{port}")

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._runner:
            await self._runner.cleanup()

        logger.info("Rendezvous server stopped")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


def main():
    parser = argparse.ArgumentParser(description="Rendezvous Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=9878, help="Port to bind")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    async def run():
        server = RendezvousServer()
        await server.start(host=args.host, port=args.port)
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            await server.stop()

    asyncio.run(run())


if __name__ == "__main__":
    main()
