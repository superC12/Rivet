from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.nodes import health
from backend.providers import OllamaProvider


class _OllamaStub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path != "/api/tags":
            self.send_error(404)
            return
        body = json.dumps({"models": [{"name": "qwen3:8b", "size": 42}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def test_auto_detection_finds_an_administrator_candidate_and_lists_models():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    detected = f"http://127.0.0.1:{server.server_port}"
    provider = OllamaProvider(
        "local-ollama",
        {
            "type": "ollama",
            "node": "homelab",
            "endpoint": "http://127.0.0.1:1",
            "auto_detect": True,
            "discovery_endpoints": [detected],
        },
    )

    async def exercise():
        assert await provider.health()
        assert provider.endpoint == detected
        models = await provider.list_models()
        assert [model["id"] for model in models] == ["qwen3:8b"]

    try:
        health.cache.invalidate()
        asyncio.run(exercise())
    finally:
        health.cache.invalidate()
        server.shutdown()
        server.server_close()


def test_manual_or_disabled_connection_is_never_redirected(monkeypatch):
    probed = []

    async def fake_probe(endpoint, *_args, **_kwargs):
        probed.append(endpoint)
        return False

    monkeypatch.setattr("backend.providers.ollama.probe", fake_probe)
    provider = OllamaProvider(
        "manual-lab",
        {
            "type": "ollama",
            "manual": True,
            "endpoint": "http://manual-host:11434",
            "auto_detect": False,
            "discovery_endpoints": ["http://should-not-run:11434"],
        },
    )

    assert asyncio.run(provider.health()) is False
    assert probed == ["http://manual-host:11434"]
    assert provider.endpoint == "http://manual-host:11434"


def test_environment_candidates_are_bounded_and_deduplicated(monkeypatch):
    monkeypatch.setenv(
        "RIVET_OLLAMA_ENDPOINTS",
        "http://homelab:11434,http://homelab:11434/,http://backup:11434",
    )
    provider = OllamaProvider(
        "local-ollama",
        {
            "type": "ollama",
            "endpoint": "http://127.0.0.1:11434/",
            "auto_detect": True,
            "discovery_endpoints": ["http://backup:11434"],
        },
    )

    candidates = provider._discovery_candidates()
    assert candidates[0] == "http://127.0.0.1:11434"
    assert candidates.count("http://homelab:11434") == 1
    assert candidates.count("http://backup:11434") == 1
    assert "http://host.docker.internal:11434" in candidates
    assert "http://ollama:11434" in candidates


def test_provider_api_reports_the_effective_detected_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import models as models_api
    from backend.main import app

    provider = OllamaProvider(
        "local-ollama",
        {
            "type": "ollama",
            "node": "homelab",
            "endpoint": "http://127.0.0.1:11434",
            "auto_detect": True,
        },
    )

    async def detect_elsewhere():
        provider.endpoint = "http://host.docker.internal:11434"
        return True

    monkeypatch.setattr(provider, "health", detect_elsewhere)
    monkeypatch.setattr(models_api, "providers", lambda: {"local-ollama": provider})
    with TestClient(app) as client:
        result = client.get("/api/providers").json()[0]

    assert result["status"] == "online"
    assert result["configured_endpoint"] == "http://127.0.0.1:11434"
    assert result["endpoint"] == "http://host.docker.internal:11434"
    assert result["auto_detect"] is True
    assert result["detected"] is True


def test_model_api_marks_onboarding_exclusions_without_hiding_discovery(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import models as models_api
    from backend.main import app

    async def discovered():
        return [
            {"id": "small", "name": "Small", "provider": "local", "node": "homelab"},
            {"id": "large", "name": "Large", "provider": "local", "node": "homelab"},
        ]

    monkeypatch.setattr(models_api, "discover_models", discovered)
    monkeypatch.setitem(models_api.settings.rivet["router"], "disabled_models", ["local:small"])
    monkeypatch.setitem(models_api.settings.rivet["router"], "model_priority", ["local:large", "local:small"])
    with TestClient(app) as client:
        result = client.get("/api/models").json()

    assert [(model["id"], model["enabled"]) for model in result] == [("large", True), ("small", False)]


def test_explicit_provider_refresh_bypasses_negative_health_cache(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import models as models_api
    from backend.main import app

    invalidations = []

    class OfflineProvider:
        id = "local-ollama"
        node = "homelab"
        endpoint = "http://127.0.0.1:11434"
        config = {"type": "ollama", "endpoint": endpoint, "auto_detect": True}

        async def health(self):
            return False

    monkeypatch.setattr(models_api.health_cache, "invalidate", lambda: invalidations.append("health"))
    monkeypatch.setattr(models_api, "invalidate_model_cache", lambda: invalidations.append("models"))
    monkeypatch.setattr(models_api, "providers", lambda: {"local-ollama": OfflineProvider()})

    with TestClient(app) as client:
        assert client.get("/api/providers?refresh=true").status_code == 200

    assert invalidations == ["health", "models"]
