from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .health import cache, probe
from .wol import send_magic_packet


class NodeManager:
    def __init__(self, nodes: dict, providers: dict) -> None:
        self.nodes = nodes
        self.providers = providers

    def _endpoint_for(self, node_id: str) -> str | None:
        for provider in self.providers.values():
            if provider.get("node") == node_id and provider.get("endpoint"):
                return str(provider["endpoint"]).rstrip("/")
        node = self.nodes.get(node_id, {})
        address = node.get("address") or node.get("hostname")
        return f"http://{address}" if address else None

    async def reachable(self, node_id: str, use_cache: bool = True) -> bool:
        node = self.nodes.get(node_id)
        if not node:
            return False
        endpoint = self._endpoint_for(node_id)
        if not endpoint:
            return node.get("type", "local") == "local"
        return await probe(endpoint, use_cache=use_cache)

    async def status(self, node_id: str) -> dict:
        node = self.nodes[node_id]
        online = await self.reachable(node_id)
        wol = node.get("wake_on_lan", {})
        return {
            "id": node_id,
            "display_name": node.get("display_name", node_id.replace("-", " ").title()),
            "type": str(node.get("type", "local")).upper(),
            "always_on": bool(node.get("always_on", False)),
            "reachable": online,
            "state": "online" if online else ("offline" if node.get("always_on") else "sleeping"),
            "last_seen": datetime.now(UTC).isoformat() if online else None,
            "wake_capable": bool(wol.get("enabled") and wol.get("mac")),
            "provider_count": sum(1 for provider in self.providers.values() if provider.get("node") == node_id),
        }

    async def list(self) -> list[dict]:
        return list(await asyncio.gather(*(self.status(node_id) for node_id in self.nodes)))

    async def wake(self, node_id: str) -> dict:
        node = self.nodes.get(node_id)
        if not node:
            raise KeyError(node_id)
        wol = node.get("wake_on_lan", {})
        if not wol.get("enabled") or not wol.get("mac"):
            raise ValueError("Wake-on-LAN is not configured for this node")
        await asyncio.to_thread(send_magic_packet, wol["mac"], wol.get("broadcast", "255.255.255.255"), int(wol.get("port", 9)))
        # The cached "offline" is about to become wrong on purpose.
        endpoint = self._endpoint_for(node_id)
        if endpoint:
            cache.invalidate(endpoint)
        return {"node": node_id, "status": "wake_sent"}

    async def wake_and_wait(self, node_id: str, timeout: int = 45, interval: int = 3) -> bool:
        await self.wake(node_id)
        for _ in range(max(1, timeout // interval)):
            await asyncio.sleep(interval)
            # Bypass the cache: the whole point of this loop is to catch
            # the state change the moment it happens.
            if await self.reachable(node_id, use_cache=False):
                return True
        return False
