import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routing.classifier import Classifier, DispatchClassifier, _health_cache, _tag_matches


@pytest.fixture(autouse=True)
def clear_health_cache():
    _health_cache.invalidate()
    yield
    _health_cache.invalidate()


def stub_ollama(tags):
    """A minimal stand-in for Ollama's /api/tags."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"models": [{"name": tag} for tag in tags]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --- tag matching ----------------------------------------------------


def test_untagged_model_matches_the_latest_tag():
    # Ollama reports `name:latest` for a model created without a tag, so
    # an exact compare would call a working dispatcher missing.
    assert _tag_matches("route-labeler", "route-labeler:latest")
    assert _tag_matches("route-labeler", "route-labeler")


def test_an_explicit_tag_must_match_exactly():
    assert _tag_matches("route-labeler:v1", "route-labeler:v1")
    assert not _tag_matches("route-labeler:v1", "route-labeler:v2")


def test_a_different_model_does_not_match():
    assert not _tag_matches("route-labeler", "assistant-model:latest")


# --- dispatcher health -----------------------------------------------


def test_health_reports_ok_when_the_model_is_installed():
    server = stub_ollama(["route-labeler:latest", "assistant-model:latest"])
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        result = asyncio.run(DispatchClassifier(endpoint, "route-labeler").health())
    finally:
        server.shutdown()
    assert result["status"] == "ok"
    assert result["model_installed"] is True
    assert result["error"] is None


def test_health_names_the_missing_model_rather_than_just_failing():
    server = stub_ollama(["assistant-model:latest"])
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        result = asyncio.run(DispatchClassifier(endpoint, "route-labeler").health())
    finally:
        server.shutdown()
    assert result["status"] == "model_missing"
    assert result["model_installed"] is False
    assert "route-labeler" in result["error"]
    assert "Modelfile" not in result["error"]


def test_dispatch_without_a_selected_model_is_explicitly_unconfigured():
    classifier = Classifier({"mode": "dispatch", "model": ""}, honor_environment=False)
    health = asyncio.run(classifier.health(use_cache=False))
    result = asyncio.run(classifier.classify("hello"))

    assert health["status"] == "unconfigured"
    assert health["model"] == ""
    assert "Select a classifier model" in health["error"]
    assert result.confident is False
    assert result.error == health["error"]


def test_health_reports_unreachable_without_raising():
    # Port 1 is reserved, so the connection is refused immediately.
    result = asyncio.run(DispatchClassifier("http://127.0.0.1:1", "any-model", timeout_s=1.0).health())
    assert result["status"] == "unreachable"
    assert result["model_installed"] is False
    assert result["error"]


def test_heuristic_mode_is_healthy_without_probing_anything():
    result = asyncio.run(Classifier({"mode": "heuristic"}).health())
    assert result["status"] == "ok"
    assert result["mode"] == "heuristic"
    assert result["model"] is None


# --- environment overrides -------------------------------------------


def test_environment_overrides_the_config_file(monkeypatch):
    monkeypatch.setenv("RIVET_DISPATCH_ENDPOINT", "http://server:11434")
    monkeypatch.setenv("RIVET_DISPATCH_MODEL", "custom-dispatch")
    monkeypatch.setenv("RIVET_CLASSIFIER_MODE", "dispatch")
    classifier = Classifier({"mode": "heuristic", "endpoint": "http://127.0.0.1:11434", "model": "granite"})
    assert classifier.mode == "dispatch"
    assert classifier.endpoint == "http://server:11434"
    assert classifier.model == "custom-dispatch"


def test_conventional_env_names_also_work(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://always-on:11434")
    monkeypatch.setenv("DISPATCH_MODEL", "route-labeler")
    classifier = Classifier({"mode": "dispatch"})
    assert classifier.endpoint == "http://always-on:11434"
    assert classifier.model == "route-labeler"


def test_prefixed_env_wins_over_the_conventional_one(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://conventional:11434")
    monkeypatch.setenv("RIVET_DISPATCH_ENDPOINT", "http://prefixed:11434")
    assert Classifier({"mode": "dispatch"}).endpoint == "http://prefixed:11434"


def test_explicit_configuration_can_ignore_deployment_environment(monkeypatch):
    monkeypatch.setenv("RIVET_CLASSIFIER_MODE", "heuristic")
    monkeypatch.setenv("OLLAMA_URL", "http://environment:11434")
    monkeypatch.setenv("DISPATCH_MODEL", "environment-model")
    classifier = Classifier(
        {
            "mode": "dispatch",
            "endpoint": "http://cli:11434",
            "model": "cli-model",
        },
        honor_environment=False,
    )
    assert classifier.mode == "dispatch"
    assert classifier.endpoint == "http://cli:11434"
    assert classifier.model == "cli-model"


def test_a_malformed_timeout_does_not_stop_startup(monkeypatch):
    monkeypatch.setenv("RIVET_DISPATCH_TIMEOUT_S", "not-a-number")
    assert Classifier({"mode": "dispatch"}).timeout_s == Classifier.DEFAULT_TIMEOUT_S


def test_an_unknown_fallback_lane_falls_back_to_escalate(monkeypatch):
    monkeypatch.setenv("RIVET_FALLBACK_LANE", "SIDEWAYS")
    assert Classifier({}).fallback_lane == "ESCALATE"


def test_fallback_lane_can_be_pinned_local(monkeypatch):
    monkeypatch.setenv("RIVET_FALLBACK_LANE", "local")
    assert Classifier({}).fallback_lane == "LOCAL"


# --- the endpoint ----------------------------------------------------


def classify(text, mode="auto"):
    with TestClient(app) as client:
        response = client.post("/api/classify", json={"text": text, "mode": mode})
        assert response.status_code == 200
        return response.json()


def test_classify_returns_the_lane():
    assert classify("What is 18% of 275?")["lane"] == "LOCAL"
    assert classify("Analyze this repository architecture")["lane"] == "ESCALATE"
    assert classify("add buy milk to my shopping list")["lane"] == "ACTION"


def test_classify_reports_allowed_tiers_for_the_requested_mode():
    assert classify("Analyze this repository architecture", "local_only")["allowed_tiers"] == ["LOCAL"]
    assert "CLOUD" in classify("Analyze this repository architecture", "auto")["allowed_tiers"]


def test_action_has_no_tiers_because_it_does_not_use_a_model():
    assert classify("add buy milk to my shopping list")["allowed_tiers"] == []


def test_classify_is_side_effect_free():
    with TestClient(app) as client:
        before = len(client.get("/api/conversations").json())
        client.post("/api/classify", json={"text": "add buy milk to my shopping list"})
        after = len(client.get("/api/conversations").json())
    # An ACTION classification must not run the action or store anything.
    assert before == after


def test_empty_text_is_rejected():
    with TestClient(app) as client:
        assert client.post("/api/classify", json={"text": ""}).status_code == 422


def test_classifier_endpoint_describes_the_configuration():
    with TestClient(app) as client:
        body = client.get("/api/classifier").json()
    assert body["mode"] in {"heuristic", "dispatch"}
    assert body["lanes"] == ["LOCAL", "ESCALATE", "ACTION"]
    assert body["fallback_lane"] in {"LOCAL", "ESCALATE"}


def test_status_surfaces_classifier_health():
    with TestClient(app) as client:
        body = client.get("/api/status").json()
    assert "classifier" in body
    assert body["classifier"]["status"] in {"ok", "model_missing", "unreachable"}
