import asyncio

from backend.nodes import health
from backend.providers import OllamaProvider


def test_provider_health_reuses_the_shared_reachability_cache(monkeypatch):
    requests = []

    class Response:
        is_success = True

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            requests.append(url)
            return Response()

    monkeypatch.setattr(health.httpx, "AsyncClient", Client)
    health.cache.invalidate()
    provider = OllamaProvider(
        "test-ollama",
        {"type": "ollama", "node": "homelab", "endpoint": "http://127.0.0.1:11434"},
    )

    async def check_twice():
        assert await provider.health()
        assert await provider.health()

    try:
        asyncio.run(check_twice())
        assert requests == ["http://127.0.0.1:11434/api/tags"]
    finally:
        health.cache.invalidate()
