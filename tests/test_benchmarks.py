import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from backend.benchmarks import EvalRunner, PerfRunner, build_prompt
from backend.benchmarks.evals import score
from backend.benchmarks.graders import grade, status_of
from backend.benchmarks.perf import summarise as summarise_perf
from backend.main import app
from backend.storage.benchmarks import BenchmarkStore
from backend.storage.database import Database


# --- graders (pure, no network) --------------------------------------


def test_exact_number_ignores_formatting_a_model_adds():
    # The script this replaces failed "1,116." even though the maths was
    # right. Getting the arithmetic right and the prose chatty is a pass.
    for response in ("1116", "The answer is 1116.", "1,116", "= 1116!", "1116.0"):
        assert grade("exact_number", response, "1116") is True, response


def test_exact_number_rejects_a_wrong_number():
    assert grade("exact_number", "The answer is 1117.", "1116") is False
    assert grade("exact_number", "no idea", "1116") is False


def test_exact_number_handles_negatives_and_decimals():
    assert grade("exact_number", "it is -42.5 degrees", "-42.5") is True


def test_contains_is_case_insensitive():
    assert grade("contains", "The capital is paris.", "Paris") is True
    assert grade("contains", "The capital is Lyon.", "Paris") is False


def test_exact_lowercase_allows_a_model_to_explain_after_answering():
    assert grade("exact_lowercase", "yes, water is wet", "yes") is True
    assert grade("exact_lowercase", "**yes**", "yes") is True
    assert grade("exact_lowercase", "Well, it depends. Yes.", "yes") is False


def test_exact_match_tolerates_trailing_punctuation():
    assert grade("exact_match", "ESCALATE", "ESCALATE") is True
    assert grade("exact_match", "escalate.", "ESCALATE") is True
    assert grade("exact_match", "I would escalate this", "ESCALATE") is False


def test_valid_json_tool_extracts_json_from_surrounding_prose():
    wrapped = 'Sure! ```json\n{"tool": "create_task", "title": "milk", "due_date": "tomorrow"}\n```'
    assert grade("valid_json_tool", wrapped, "create_task") is True


def test_valid_json_tool_rejects_unparseable_or_wrong_tool():
    assert grade("valid_json_tool", "{not json", "create_task") is False
    assert grade("valid_json_tool", '{"tool": "delete_everything"}', "create_task") is False
    assert grade("valid_json_tool", "I will create a task for you.", "create_task") is False


def test_manual_and_unknown_graders_ask_for_a_human():
    # "Did it admit it does not know?" has no honest automatic answer,
    # and a made-up one would quietly corrupt the score.
    assert grade("manual", "I have no memory of that.", "admits") is None
    assert grade("not_a_real_grader", "anything", "") is None


def test_status_names_the_three_outcomes():
    assert status_of(True) == "pass"
    assert status_of(False) == "fail"
    assert status_of(None) == "review"


def test_score_reports_none_rather_than_zero_when_nothing_was_auto_graded():
    result = score([{"status": "review"}, {"status": "review"}])
    assert result["rate"] is None
    assert result["review"] == 2


def test_score_counts_only_auto_graded_tests():
    result = score([{"status": "pass"}, {"status": "fail"}, {"status": "review"}])
    assert (result["passed"], result["graded"], result["review"]) == (1, 2, 1)
    assert result["rate"] == 0.5


# --- prompt building --------------------------------------------------


def test_generated_prompt_is_about_the_requested_size():
    text = build_prompt({"prompt_tokens": 100})
    assert 350 <= len(text) <= 450


def test_a_custom_prompt_wins_over_the_generated_one():
    assert build_prompt({"prompt_tokens": 5000, "prompt_text": "measure this"}) == "measure this"


# --- runners against a stub Ollama ------------------------------------


class StubOllama:
    """Enough of Ollama's API to exercise the runners for real."""

    def __init__(self, generate=None, ps=None):
        self.generate_body = generate or {}
        self.ps_body = ps or {"models": []}
        self.unloaded = []
        self.prompts = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send(stub.ps_body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                request = json.loads(self.rfile.read(length) or b"{}")
                if request.get("keep_alive") == 0:
                    stub.unloaded.append(request.get("model"))
                    stub.ps_body = {"models": []}
                else:
                    stub.prompts.append(request.get("prompt", ""))
                self._send(stub.generate_body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


async def collect(runner, definition):
    return [item async for item in runner.run(definition)]


def test_perf_reports_speed_memory_and_offload_from_the_api():
    # VRAM and offload come from /api/ps, not nvidia-smi, so they
    # describe the machine that ran the model rather than this one.
    stub = StubOllama(
        generate={"eval_count": 100, "eval_duration": 2_000_000_000,
                  "prompt_eval_count": 500, "prompt_eval_duration": 1_000_000_000,
                  "load_duration": 3_000_000_000, "total_duration": 6_000_000_000},
        ps={"models": [{"name": "granite:3b", "size": 4_000_000_000, "size_vram": 3_000_000_000}]},
    )
    try:
        events = asyncio.run(collect(PerfRunner(stub.endpoint), {"models": ["granite:3b"], "cold_start": False}))
    finally:
        stub.close()

    result = next(e["result"] for e in events if e["event"] == "result")
    assert result["gen_tok_s"] == 50.0
    assert result["prompt_tok_s"] == 500.0
    assert result["load_ms"] == 3000
    assert result["size_bytes"] == 4_000_000_000
    assert result["gpu_offload"] == 0.75
    assert result["error"] is None


def test_perf_cold_start_evicts_resident_models_first():
    stub = StubOllama(
        generate={"eval_count": 10, "eval_duration": 1_000_000_000},
        ps={"models": [{"name": "other:7b", "size": 1, "size_vram": 1}]},
    )
    try:
        asyncio.run(collect(PerfRunner(stub.endpoint), {"models": ["granite:3b"], "cold_start": True}))
    finally:
        stub.close()
    assert "other:7b" in stub.unloaded


def test_perf_records_an_error_without_aborting_the_suite():
    results = asyncio.run(collect(PerfRunner("http://127.0.0.1:1"), {"models": ["a", "b"], "cold_start": False}))
    outcomes = [e["result"] for e in results if e["event"] == "result"]
    assert len(outcomes) == 2
    assert all(o["error"] for o in outcomes)


def test_perf_summary_names_the_fastest_model():
    assert "fast" in summarise_perf([
        {"model": "slow", "gen_tok_s": 10},
        {"model": "fast", "gen_tok_s": 90},
    ])


def test_eval_grades_each_test_and_scores_the_model():
    stub = StubOllama(generate={"response": "1116"})
    try:
        events = asyncio.run(collect(EvalRunner(stub.endpoint), {
            "models": ["granite:3b"],
            "system_prompt": "be brief",
            "tests": [
                {"id": "m1", "prompt": "847+269?", "expected": "1116", "grading": "exact_number"},
                {"id": "m2", "prompt": "12*13?", "expected": "156", "grading": "exact_number"},
            ],
        }))
    finally:
        stub.close()

    result = next(e["result"] for e in events if e["event"] == "result")
    assert [t["status"] for t in result["tests"]] == ["pass", "fail"]
    assert result["score"]["passed"] == 1


def test_eval_uses_the_tool_schema_for_tool_tests_only():
    stub = StubOllama(generate={"response": "ok"})
    try:
        asyncio.run(collect(EvalRunner(stub.endpoint), {
            "models": ["m"],
            "system_prompt": "ASSISTANT-PROMPT",
            "tool_schema": "TOOL-PROMPT",
            "tests": [
                {"id": "a", "category": "arithmetic", "prompt": "x", "grading": "manual"},
                {"id": "b", "category": "tool_call", "prompt": "y", "grading": "manual"},
            ],
        }))
    finally:
        stub.close()
    assert "ASSISTANT-PROMPT" in stub.prompts[0]
    assert "TOOL-PROMPT" in stub.prompts[1]


def test_eval_marks_an_unreachable_model_as_errored_not_failed():
    events = asyncio.run(collect(EvalRunner("http://127.0.0.1:1"), {
        "models": ["m"],
        "tests": [{"id": "t", "prompt": "x", "expected": "y", "grading": "contains"}],
    }))
    result = next(e["result"] for e in events if e["event"] == "result")
    assert result["tests"][0]["status"] == "error"
    assert result["score"]["graded"] == 0


# --- storage ----------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    database = Database(tmp_path / "bench.db")
    database.initialize()
    return BenchmarkStore(database)


def test_suites_round_trip_with_their_definition(store):
    suite = store.create("Speed", "perf", {"models": ["a"], "cold_start": True}, "desc")
    loaded = store.get(suite["id"])
    assert loaded["name"] == "Speed"
    assert loaded["definition"]["models"] == ["a"]
    assert loaded["description"] == "desc"


def test_an_unknown_kind_is_rejected(store):
    with pytest.raises(ValueError):
        store.create("Nope", "chaos", {})


def test_editing_a_suite_keeps_fields_that_were_not_sent(store):
    suite = store.create("Speed", "perf", {"models": ["a"]}, "original")
    updated = store.update(suite["id"], name="Renamed")
    assert updated["name"] == "Renamed"
    assert updated["description"] == "original"
    assert updated["definition"]["models"] == ["a"]


def test_runs_are_recorded_and_returned_with_the_suite(store):
    suite = store.create("Speed", "perf", {"models": ["a"]})
    run_id = store.start_run(suite["id"])
    store.finish_run(run_id, "completed", "1 model measured", [{"model": "a", "gen_tok_s": 12}])
    loaded = store.get(suite["id"])
    assert loaded["runs"][0]["status"] == "completed"
    assert loaded["runs"][0]["results"][0]["gen_tok_s"] == 12


def test_list_reports_status_and_summary_from_the_actual_latest_run(store, monkeypatch):
    suite = store.create("Speed", "perf", {"models": ["a"]})
    timestamps = iter((
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:30:00+00:00",
        "2026-01-02T00:00:00+00:00",
    ))
    monkeypatch.setattr("backend.storage.benchmarks.now", lambda: next(timestamps))
    older = store.start_run(suite["id"])
    store.finish_run(older, "failed", "older failure", [])
    newer = store.start_run(suite["id"])
    # Supply explicit timestamps for finish_run without changing which
    # started_at value determines recency.
    monkeypatch.setattr("backend.storage.benchmarks.now", lambda: "2026-01-03T00:00:00+00:00")
    store.finish_run(newer, "completed", "newest success", [])

    last_run = store.list()[0]["last_run"]
    assert last_run["started_at"] == "2026-01-02T00:00:00+00:00"
    assert last_run["status"] == "completed"
    assert last_run["summary"] == "newest success"


def test_cancelled_runs_are_a_distinct_history_state(store):
    suite = store.create("Speed", "perf", {"models": ["a"]})
    run_id = store.start_run(suite["id"])
    store.finish_run(run_id, "cancelled", "Stopped after one result", [{"model": "a"}])
    run = store.get(suite["id"])["runs"][0]
    assert run["status"] == "cancelled"
    assert run["results"] == [{"model": "a"}]


def test_deleting_a_suite_removes_its_runs(store):
    suite = store.create("Speed", "perf", {})
    store.finish_run(store.start_run(suite["id"]), "completed", "x", [])
    assert store.delete(suite["id"])
    assert store.get(suite["id"]) is None


# --- the API ----------------------------------------------------------


def test_starter_suites_are_seeded_and_editable():
    with TestClient(app) as client:
        suites = client.get("/api/benchmarks").json()
    kinds = {suite["kind"] for suite in suites}
    assert {"perf", "eval"} <= kinds
    reliability = next(s for s in suites if s["kind"] == "eval")
    # Seeded with no models, so a suite never ships pointing at a model
    # the user does not have.
    assert reliability["definition"]["models"] == []
    assert reliability["definition"]["tests"]


def test_targets_expose_graders_and_only_ollama_providers():
    with TestClient(app) as client:
        body = client.get("/api/benchmarks/targets").json()
    assert "exact_number" in body["graders"]
    assert "manual" in body["graders"]
    for provider in body["providers"]:
        assert provider["endpoint"]


def test_a_suite_can_be_created_edited_and_deleted():
    with TestClient(app) as client:
        created = client.post("/api/benchmarks", json={
            "name": "Temporary", "kind": "perf", "description": "", "definition": {"models": []},
        })
        assert created.status_code == 201
        suite_id = created.json()["id"]

        edited = client.put(f"/api/benchmarks/{suite_id}", json={"name": "Renamed"})
        assert edited.json()["name"] == "Renamed"

        assert client.delete(f"/api/benchmarks/{suite_id}").status_code == 204
        assert client.get(f"/api/benchmarks/{suite_id}").status_code == 404


def test_running_without_models_is_refused_with_a_clear_reason():
    with TestClient(app) as client:
        suites = client.get("/api/benchmarks").json()
        target = next(s for s in suites if s["kind"] == "perf")
        response = client.post(f"/api/benchmarks/{target['id']}/run", json={"models": []})
    assert response.status_code == 400
    assert "model" in response.json()["detail"].lower()


def test_running_an_unknown_suite_is_a_404():
    with TestClient(app) as client:
        assert client.post("/api/benchmarks/nope/run", json={}).status_code == 404


# --- starter identity and restore ------------------------------------


def test_starters_have_plain_names_and_a_question_each():
    from backend.benchmarks import STARTERS

    names = {starter["name"] for starter in STARTERS}
    assert names == {"Speed & Footprint", "Judgment & Limits"}
    for starter in STARTERS:
        # The description says what the suite answers, not what it is.
        assert starter["description"].endswith(".")
        assert len(starter["description"]) < 120


def test_restore_brings_the_starters_back_after_deletion():
    with TestClient(app) as client:
        for suite in client.get("/api/benchmarks").json():
            client.delete(f"/api/benchmarks/{suite['id']}")
        assert client.get("/api/benchmarks").json() == []

        restored = client.post("/api/benchmarks/restore").json()
        assert restored["created"] == 2
        assert {s["kind"] for s in restored["benchmarks"]} == {"perf", "eval"}


def test_restore_never_duplicates_onto_existing_benchmarks():
    with TestClient(app) as client:
        client.post("/api/benchmarks/restore")
        before = len(client.get("/api/benchmarks").json())
        assert client.post("/api/benchmarks/restore").json()["created"] == 0
        assert len(client.get("/api/benchmarks").json()) == before


def test_benchmark_visibility_is_a_saved_preference():
    from fastapi.testclient import TestClient as Client

    with Client(app) as client:
        client.post("/api/settings", json={"interface": {"show_benchmarks": False}})
        assert client.get("/api/settings").json()["interface"]["show_benchmarks"] is False
        # Hiding the panel must not touch saved benchmarks.
        assert client.get("/api/benchmarks").json()
        client.post("/api/settings", json={"interface": {"show_benchmarks": True}})
        assert client.get("/api/settings").json()["interface"]["show_benchmarks"] is True


def test_saving_appearance_does_not_clear_benchmark_visibility():
    with TestClient(app) as client:
        client.post("/api/settings", json={"interface": {"show_benchmarks": True}})
        client.post("/api/settings", json={"interface": {"appearance": "dark"}})
        assert client.get("/api/settings").json()["interface"]["show_benchmarks"] is True
