import json

import pytest
from fastapi.testclient import TestClient

from backend.api import chat as chat_api
from backend.main import app

MODELS = [{"id": "small", "name": "Small", "provider": "local", "node": "homelab", "capabilities": ["chat"]}]


class FakeProvider:
    """A provider that streams exactly what it is told to."""

    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.usage = {"prompt_tokens": 11, "completion_tokens": 7}
        self.node = "homelab"

    async def chat(self, request):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error


def parse_sse(body: str) -> list[tuple[str, object]]:
    """Parse a stream the same way the browser client does."""
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        raw = "\n".join(data)
        try:
            events.append((name, json.loads(raw)))
        except json.JSONDecodeError:
            events.append((name, raw))
    return events


@pytest.fixture
def stub(monkeypatch):
    def install(chunks, error=None):
        provider = FakeProvider(chunks, error)

        async def fake_discover():
            return MODELS

        monkeypatch.setattr(chat_api, "discover_models", fake_discover)
        monkeypatch.setattr(chat_api, "providers", lambda: {"local": provider})
        return provider

    return install


def collect(chunks, message="What is 18% of 275?", error=None, stub=None):
    stub(chunks, error)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": message, "mode": "local_only"})
        assert response.status_code == 200
        return parse_sse(response.text)


def tokens_of(events):
    return "".join(payload for name, payload in events if name == "token")


def test_tokens_containing_newlines_survive_the_stream(stub):
    # Ollama streams "\n" as its own chunk constantly. Raw SSE framing
    # dropped every line after the first, which silently ate blank lines
    # and mangled every code block.
    chunks = ["Here:\n", "\n", "```python\n", "x = 1\n", "```", "\n\ndone"]
    events = collect(chunks, stub=stub)
    assert tokens_of(events) == "".join(chunks)


def test_multiline_token_is_a_single_event(stub):
    events = collect(["line one\nline two\nline three"], stub=stub)
    assert tokens_of(events) == "line one\nline two\nline three"


def test_carriage_returns_and_unicode_survive(stub):
    chunks = ["a\r\nb", " — em dash ", "🙂"]
    events = collect(chunks, stub=stub)
    assert tokens_of(events) == "".join(chunks)


def test_stream_reports_route_then_done(stub):
    events = collect(["hello"], stub=stub)
    names = [name for name, _ in events]
    assert names[0] == "conversation"
    assert "route" in names
    assert names[-1] == "done"


def test_token_counts_are_persisted(stub):
    events = collect(["hello"], stub=stub)
    done = next(payload for name, payload in events if name == "done")
    assert done["prompt_tokens"] == 11
    assert done["completion_tokens"] == 7


def test_conversation_survives_the_request(stub):
    events = collect(["hello ", "world"], stub=stub)
    conversation_id = next(payload for name, payload in events if name == "conversation")["id"]
    with TestClient(app) as client:
        stored = client.get(f"/api/conversations/{conversation_id}").json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][1]["content"] == "hello world"


def test_partial_output_is_kept_when_the_model_dies_mid_answer(stub):
    from backend.providers import ProviderError

    events = collect(["I was saying "], error=ProviderError("boom"), stub=stub)
    assert any(name == "error" for name, _ in events)
    conversation_id = next(payload for name, payload in events if name == "conversation")["id"]
    with TestClient(app) as client:
        stored = client.get(f"/api/conversations/{conversation_id}").json()
    assistant = [m for m in stored["messages"] if m["role"] == "assistant"]
    assert assistant and assistant[0]["content"] == "I was saying "
    assert any("ended early" in step["message"] for step in assistant[0]["trace"])


def test_action_without_a_gateway_does_not_claim_success(stub):
    events = collect([], message="Add buy milk to my task list", stub=stub)
    done = next(payload for name, payload in events if name == "done")
    assert done["route"] == "ACTION"
    assert done["action_status"] == "not_configured"
    assert done["action_succeeded"] is False
    text = tokens_of(events).lower()
    assert "done" not in text and "created" not in text


def test_unknown_api_path_returns_json_404_not_the_frontend():
    with TestClient(app) as client:
        response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


def test_missing_conversation_is_a_404():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "hi", "conversation_id": "nope"})
    assert response.status_code == 404


def test_frontend_assets_cannot_be_reused_across_an_upgrade():
    # Revalidation still allowed a reverse proxy/browser combination to
    # retain an old ES module beside new markup. The frontend is small;
    # never storing it is safer than a split-version interface.
    with TestClient(app) as client:
        for path in ("/", "/static/js/app.js", "/static/css/tokens.css"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers.get("cache-control") == "no-store, max-age=0", path
            assert response.headers.get("pragma") == "no-cache", path


# --- fallback behaviour ----------------------------------------------

FALLBACK_MODELS = [
    {"id": "small", "name": "Small", "provider": "local", "node": "homelab", "capabilities": ["chat"]},
    {"id": "cloud", "name": "Cloud", "provider": "openrouter-main", "node": None, "capabilities": ["chat"]},
    {"id": "spare", "name": "Spare", "provider": "spare-local", "node": "homelab", "capabilities": ["chat"]},
]


@pytest.fixture
def two_providers(monkeypatch):
    """Install a failing primary and a working fallback."""

    def install(fallback_provider, models=FALLBACK_MODELS, primary_chunks=("half ",)):
        from backend.config import settings as live
        from backend.providers import ProviderError

        primary = FakeProvider(list(primary_chunks), ProviderError("boom"))
        fallback = FakeProvider(["the real answer"])

        async def fake_discover():
            return models

        monkeypatch.setattr(chat_api, "discover_models", fake_discover)
        monkeypatch.setattr(
            chat_api, "providers",
            lambda: {"local": primary, "openrouter-main": fallback, "spare-local": fallback},
        )
        monkeypatch.setitem(live.rivet["router"], "fallback", fallback_provider)
        monkeypatch.setitem(live.rivet, "nodes", {"homelab": {"type": "local", "always_on": True}})
        return primary, fallback

    return install


def run_chat(mode):
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "What is 18% of 275?", "mode": mode})
        assert response.status_code == 200
        return parse_sse(response.text)


def test_local_only_request_never_falls_back_to_cloud(two_providers):
    # The one control a user has for "do not send this anywhere" must
    # hold on the recovery path too, which is exactly where it is easy
    # to forget and impossible for the user to notice.
    two_providers("openrouter-main")
    events = run_chat("local_only")
    assert any(name == "error" for name, _ in events)
    assert not any(name == "done" for name, _ in events)
    assert "the real answer" not in tokens_of(events)


def test_local_only_request_may_fall_back_to_another_local_provider(two_providers):
    two_providers("spare-local")
    events = run_chat("local_only")
    done = next(payload for name, payload in events if name == "done")
    assert done["route"] == "LOCAL"
    assert done["provider"] == "spare-local"


def test_auto_request_may_fall_back_to_cloud(two_providers):
    two_providers("openrouter-main")
    events = run_chat("auto")
    done = next(payload for name, payload in events if name == "done")
    assert done["route"] == "CLOUD"


def test_fallback_on_a_local_node_is_not_labelled_remote(two_providers):
    two_providers("spare-local")
    events = run_chat("auto")
    done = next(payload for name, payload in events if name == "done")
    assert done["node"] == "homelab"
    assert done["route"] == "LOCAL"


def test_fallback_emits_reset_before_its_tokens(two_providers):
    two_providers("openrouter-main")
    events = run_chat("auto")
    names = [name for name, _ in events]
    assert "reset" in names
    # Everything the dead model produced arrives before the reset, and
    # everything after it belongs to the fallback.
    reset_at = names.index("reset")
    before = "".join(p for n, p in events[:reset_at] if n == "token")
    after = "".join(p for n, p in events[reset_at:] if n == "token")
    assert before == "half "
    assert after == "the real answer"


def test_stored_fallback_answer_is_not_spliced(two_providers):
    two_providers("openrouter-main")
    events = run_chat("auto")
    conversation_id = next(p for n, p in events if n == "conversation")["id"]
    with TestClient(app) as client:
        stored = client.get(f"/api/conversations/{conversation_id}").json()
    answers = [m["content"] for m in stored["messages"] if m["role"] == "assistant"]
    assert answers == ["the real answer"]


# --- an explicitly selected classifier is not an assistant ------------


def test_the_configured_classifier_is_kept_out_of_the_chat_model_list(monkeypatch):
    from backend.api import dependencies

    monkeypatch.setattr(dependencies, "classifier_model_name", lambda: "route-labeler")
    assert dependencies.is_classifier_model({"id": "route-labeler:latest", "node": "homelab"})
    assert dependencies.is_classifier_model({"id": "route-labeler", "node": "homelab"})
    assert not dependencies.is_classifier_model({"id": "assistant-model", "node": "homelab"})


def test_a_cloud_model_is_never_mistaken_for_the_classifier(monkeypatch):
    from backend.api import dependencies

    monkeypatch.setattr(dependencies, "classifier_model_name", lambda: "route-labeler")
    assert not dependencies.is_classifier_model({"id": "route-labeler", "node": None})


def test_no_classifier_is_hidden_by_default(monkeypatch):
    from backend.api import dependencies

    monkeypatch.setattr(dependencies, "classifier_model_name", lambda: "")
    assert not dependencies.is_classifier_model({"id": "any-model", "node": "homelab"})


def test_openrouter_has_no_predefined_model(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from backend.api import dependencies

    monkeypatch.setitem(
        dependencies.settings.rivet,
        "providers",
        {"cloud": {"type": "openrouter", "node": None}},
    )
    monkeypatch.setattr(dependencies, "providers", lambda: {"cloud": SimpleNamespace(node=None)})

    assert asyncio.run(dependencies._discover_models_uncached()) == []


def test_discovery_hides_the_dispatcher_from_chat_but_not_from_benchmarks(monkeypatch):
    import asyncio

    from backend.api import dependencies

    everything = [
        {"id": "route-labeler:latest", "node": "homelab", "provider": "local-ollama"},
        {"id": "assistant-model:latest", "node": "homelab", "provider": "local-ollama"},
    ]

    async def fake_uncached():
        return everything

    monkeypatch.setattr(dependencies, "_discover_models_uncached", fake_uncached)
    monkeypatch.setattr(dependencies, "classifier_model_name", lambda: "route-labeler")
    dependencies.invalidate_model_cache()

    for_chat = asyncio.run(dependencies.discover_models())
    for_benchmarks = asyncio.run(dependencies.discover_models(include_classifier=True))
    dependencies.invalidate_model_cache()

    assert [m["id"] for m in for_chat] == ["assistant-model:latest"]
    assert len(for_benchmarks) == 2
