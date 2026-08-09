"""Cached reachability probes.

Rivet is meant to sit on hardware that has better things to do. Opening a
socket to every node every time a settings panel renders is exactly the
"unnecessary polling" the design rules out, so probe results are cached
for a short TTL and shared across callers.

Two TTLs, because the two answers decay differently. A node that just
answered is very likely still up a few seconds later. A node that is
asleep stays asleep until something wakes it, and re-probing it costs a
full connection timeout every time — so negative results are held longer.

`invalidate()` exists for the one moment the cache is actively wrong:
immediately after sending a wake packet, when the whole point is to
notice the state change as soon as it happens.
"""

from __future__ import annotations

import time

import httpx

ONLINE_TTL_S = 60.0
OFFLINE_TTL_S = 120.0
PROBE_TIMEOUT_S = 2.0


class HealthCache:
    def __init__(self, online_ttl: float = ONLINE_TTL_S, offline_ttl: float = OFFLINE_TTL_S) -> None:
        self.online_ttl = online_ttl
        self.offline_ttl = offline_ttl
        self._entries: dict[str, tuple[bool, float]] = {}

    def get(self, key: str) -> bool | None:
        entry = self._entries.get(key)
        if not entry:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: bool) -> bool:
        ttl = self.online_ttl if value else self.offline_ttl
        self._entries[key] = (value, time.monotonic() + ttl)
        return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)


# Shared so that a status page, a chat request and a settings panel
# opening at the same moment cost one probe between them, not three.
cache = HealthCache()


async def probe_url(
    url: str,
    timeout_s: float = PROBE_TIMEOUT_S,
    use_cache: bool = True,
    *,
    headers: dict[str, str] | None = None,
    cache_key: str | None = None,
) -> bool:
    """Probe an HTTP health URL through the shared reachability cache."""
    key = cache_key or url
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return cached
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers=headers)
        online = response.is_success
    except httpx.HTTPError:
        online = False
    return cache.set(key, online)


async def probe(endpoint: str, timeout_s: float = PROBE_TIMEOUT_S, use_cache: bool = True) -> bool:
    """Is an Ollama-compatible endpoint answering right now?"""
    normalized = endpoint.rstrip("/")
    return await probe_url(
        f"{normalized}/api/tags",
        timeout_s,
        use_cache,
        cache_key=normalized,
    )
