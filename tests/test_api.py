import asyncio

from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings


def test_health():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_frontend_is_served():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "A lightweight home for your AI" in response.text
        assert "ROUTING &amp; EXECUTION" in response.text
        assert "NEW SESSION" not in response.text


def test_saved_appearance_is_injected_before_first_paint(monkeypatch):
    monkeypatch.setitem(settings.rivet["onboarding"], "complete", True)
    monkeypatch.setitem(settings.assistant["interface"]["accent"], "color", "#5fd39f")
    monkeypatch.setitem(settings.assistant["interface"], "appearance", "light")

    with TestClient(app) as client:
        response = client.get("/")

    assert 'data-theme-setting="light"' in response.text
    assert 'style="--accent: #5fd39f"' in response.text


def test_first_install_does_not_claim_an_accent_before_onboarding(monkeypatch):
    monkeypatch.setitem(settings.rivet["onboarding"], "complete", False)
    monkeypatch.setitem(settings.assistant["interface"]["accent"], "color", "#e4b45f")

    with TestClient(app) as client:
        response = client.get("/")

    assert 'style="--accent: transparent"' in response.text


def test_provider_diagnostics_include_real_metadata_and_latency():
    from backend.api.health import _provider_status

    class HealthyProvider:
        config = {"type": "ollama"}
        node = "homelab"

        async def health(self):
            return True

    result = asyncio.run(_provider_status("local-ollama", HealthyProvider()))
    assert result["id"] == "local-ollama"
    assert result["type"] == "ollama"
    assert result["node"] == "homelab"
    assert result["node_type"] == "local"
    assert result["status"] == "online"
    assert isinstance(result["latency_ms"], int)


def test_conversation_can_be_deleted_from_the_dashboard_api():
    with TestClient(app) as client:
        conversation = client.post("/api/conversations", json={"title": "Delete me"}).json()
        response = client.delete(f"/api/conversations/{conversation['id']}")
        assert response.status_code == 204
        assert client.get(f"/api/conversations/{conversation['id']}").status_code == 404
