"""Reliability eval: does a model follow the protocol you depend on?

Speed is easy to measure and easy to over-value. This is the other half:
whether a model does arithmetic correctly, obeys a format instruction,
emits a parseable tool call, escalates what it cannot do, and admits what
it does not know.

The last one matters most for Rivet specifically. A small local model
that confidently invents an answer is worse than one that says ESCALATE,
because the router's whole premise is that a model knows when to hand
over.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .graders import grade, status_of

ASK_TIMEOUT_S = 120.0

# Tests in this category get the tool schema as their system prompt
# instead of the assistant one, because asking for JSON while telling a
# model to be conversational tests nothing but the contradiction.
TOOL_CATEGORY = "tool_call"


def summarise(results: list[dict]) -> str:
    lines = []
    for entry in results:
        graded = [t for t in entry["tests"] if t["status"] in ("pass", "fail")]
        passed = sum(1 for t in graded if t["status"] == "pass")
        review = sum(1 for t in entry["tests"] if t["status"] == "review")
        lines.append(f"{entry['model']} {passed}/{len(graded)}" + (f" (+{review} to review)" if review else ""))
    return " · ".join(lines) if lines else "No model was evaluated"


def score(tests: list[dict]) -> dict[str, Any]:
    graded = [t for t in tests if t["status"] in ("pass", "fail")]
    passed = sum(1 for t in graded if t["status"] == "pass")
    return {
        "passed": passed,
        "graded": len(graded),
        "review": sum(1 for t in tests if t["status"] == "review"),
        "errors": sum(1 for t in tests if t.get("error")),
        # None rather than 0 when nothing was auto-graded, so an
        # all-manual suite does not display as a 0% failure.
        "rate": round(passed / len(graded), 3) if graded else None,
    }


class EvalRunner:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")

    async def _ask(self, client: httpx.AsyncClient, model: str, system_prompt: str, prompt: str) -> tuple[str, str | None]:
        body = {
            "model": model,
            "prompt": f"{system_prompt}\n\nUser: {prompt}\nAssistant:" if system_prompt else prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        try:
            response = await client.post(f"{self.endpoint}/api/generate", json=body, timeout=ASK_TIMEOUT_S)
            response.raise_for_status()
            return str(response.json().get("response", "")).strip(), None
        except (httpx.HTTPError, ValueError) as exc:
            return "", f"{type(exc).__name__}: {exc}"

    async def run(self, definition: dict) -> AsyncIterator[dict]:
        models = [m for m in definition.get("models", []) if m]
        tests = definition.get("tests", []) or []
        system_prompt = str(definition.get("system_prompt", "")).strip()
        tool_schema = str(definition.get("tool_schema", "")).strip() or system_prompt

        total = len(models) * len(tests)
        done = 0

        async with httpx.AsyncClient() as client:
            for model in models:
                outcomes = []
                for test in tests:
                    done += 1
                    yield {
                        "event": "progress",
                        "message": f"{model} · {test.get('id', 'test')}",
                        "current": done,
                        "total": total,
                    }
                    prompt = str(test.get("prompt", ""))
                    system = tool_schema if test.get("category") == TOOL_CATEGORY else system_prompt

                    started = time.perf_counter()
                    answer, error = await self._ask(client, model, system, prompt)
                    latency_ms = round((time.perf_counter() - started) * 1000)

                    verdict = None if error else grade(str(test.get("grading", "manual")), answer, str(test.get("expected", "")))
                    outcomes.append({
                        "id": test.get("id"),
                        "category": test.get("category"),
                        "prompt": prompt,
                        "expected": test.get("expected"),
                        "grading": test.get("grading"),
                        "response": answer,
                        "status": "error" if error else status_of(verdict),
                        "error": error,
                        "latency_ms": latency_ms,
                    })

                yield {"event": "result", "result": {"model": model, "tests": outcomes, "score": score(outcomes)}}
