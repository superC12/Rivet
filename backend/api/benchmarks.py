"""Saved benchmarks: store, edit, and run them from the dashboard.

Runs stream over SSE for the same reason chat does — a suite across
several models takes minutes, and a progress bar that only moves at the
end is a spinner with extra steps.

Benchmarks target Ollama endpoints specifically. The metrics that make
them worth running (prompt-eval throughput, resident size, GPU offload)
come from Ollama's own accounting; there is no honest equivalent to read
from a cloud provider that bills per token.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.benchmarks import EvalRunner, PerfRunner, summarise_eval, summarise_perf
from backend.benchmarks import seed as seed_starters
from backend.benchmarks.graders import GRADER_NAMES
from backend.config import settings
from .dependencies import benchmark_store, discover_models, providers

logger = logging.getLogger("rivet.benchmarks")
router = APIRouter(prefix="/api/benchmarks")


class BenchmarkPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["perf", "eval"]
    description: str = Field(default="", max_length=280)
    definition: dict[str, Any] = Field(default_factory=dict)


class BenchmarkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=280)
    definition: dict[str, Any] | None = None


class RunPayload(BaseModel):
    # Overrides for a one-off run, so trying another model does not mean
    # editing and saving the suite first.
    provider: str | None = None
    models: list[str] | None = None


def event(name: str, data: Any) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def ollama_providers() -> dict[str, Any]:
    return {
        provider_id: provider
        for provider_id, provider in providers().items()
        if provider.config.get("type") == "ollama" and provider.endpoint
    }


@router.get("/targets")
async def targets() -> dict:
    """What the dashboard offers in its model dropdowns.

    Auto-detected rather than typed, so a suite cannot reference a model
    that is not installed, and adding a model to Ollama is enough to make
    it selectable here.
    """
    available = ollama_providers()
    models = [model for model in await discover_models() if model["provider"] in available]
    nodes_config = settings.rivet.get("nodes", {}) or {}
    return {
        "providers": [
            {
                "id": provider_id,
                "name": provider.config.get("display_name", provider_id),
                "endpoint": provider.endpoint,
                "node": provider.node,
                "node_type": str(nodes_config.get(provider.node, {}).get("type", "local")).lower()
                if provider.node
                else None,
                "models": sorted(m["id"] for m in models if m["provider"] == provider_id),
            }
            for provider_id, provider in available.items()
        ],
        "graders": list(GRADER_NAMES),
    }


@router.get("")
async def list_benchmarks() -> list[dict]:
    return benchmark_store.list()


@router.post("/restore")
async def restore_starters() -> dict:
    """Put the starter suites back after they were removed.

    Only seeds when nothing is saved, so this can never bury a user's own
    suites under two they already deleted once.
    """
    created = seed_starters(benchmark_store)
    return {"created": created, "benchmarks": benchmark_store.list()}


@router.post("", status_code=201)
async def create_benchmark(payload: BenchmarkPayload) -> dict:
    return benchmark_store.create(payload.name, payload.kind, payload.definition, payload.description)


@router.get("/{benchmark_id}")
async def get_benchmark(benchmark_id: str) -> dict:
    suite = benchmark_store.get(benchmark_id)
    if not suite:
        raise HTTPException(404, "Benchmark not found")
    return suite


@router.put("/{benchmark_id}")
async def update_benchmark(benchmark_id: str, payload: BenchmarkUpdate) -> dict:
    suite = benchmark_store.update(benchmark_id, payload.name, payload.definition, payload.description)
    if not suite:
        raise HTTPException(404, "Benchmark not found")
    return suite


@router.delete("/{benchmark_id}", status_code=204)
async def delete_benchmark(benchmark_id: str) -> None:
    if not benchmark_store.delete(benchmark_id):
        raise HTTPException(404, "Benchmark not found")


def resolve_endpoint(preferred: str | None) -> tuple[str, str]:
    """Pick which Ollama the suite runs against."""
    available = ollama_providers()
    if not available:
        raise HTTPException(409, "No Ollama provider is configured. Add one in Connections.")
    if preferred:
        provider = available.get(preferred)
        if not provider:
            raise HTTPException(404, f"'{preferred}' is not a configured Ollama provider")
        return preferred, provider.endpoint
    provider_id, provider = next(iter(available.items()))
    return provider_id, provider.endpoint


@router.post("/{benchmark_id}/run")
async def run_benchmark(benchmark_id: str, payload: RunPayload | None = None) -> StreamingResponse:
    suite = benchmark_store.get(benchmark_id)
    if not suite:
        raise HTTPException(404, "Benchmark not found")

    payload = payload or RunPayload()
    definition = dict(suite["definition"])
    if payload.models is not None:
        definition["models"] = payload.models
    if not definition.get("models"):
        raise HTTPException(400, "Select at least one model before running this benchmark.")

    provider_id, endpoint = resolve_endpoint(payload.provider or definition.get("provider"))
    runner = PerfRunner(endpoint) if suite["kind"] == "perf" else EvalRunner(endpoint)
    summarise = summarise_perf if suite["kind"] == "perf" else summarise_eval
    run_id = benchmark_store.start_run(benchmark_id)

    async def stream() -> AsyncIterator[bytes]:
        results: list[dict] = []
        status = "completed"
        yield event("started", {"run_id": run_id, "provider": provider_id, "endpoint": endpoint,
                                "models": definition["models"], "kind": suite["kind"]})
        try:
            async for item in runner.run(definition):
                if item["event"] == "result":
                    results.append(item["result"])
                    yield event("result", item["result"])
                else:
                    yield event("progress", item)
        except asyncio.CancelledError:
            # Closing the browser stream cancels Starlette's response task.
            # Preserve partial measurements, but never call a stopped run
            # completed in its saved history.
            status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - a failed run is reported, not raised
            status = "failed"
            logger.warning("benchmark=%s run=%s error=%s", benchmark_id, run_id, type(exc).__name__)
            yield event("error", {"message": f"The benchmark stopped: {type(exc).__name__}"})
        finally:
            # Whatever was measured before a failure is still a real
            # measurement, so it is recorded rather than thrown away.
            summary = summarise(results) if results else "No results"
            benchmark_store.finish_run(run_id, status, summary, results)

        yield event("done", {"run_id": run_id, "status": status,
                             "summary": summarise(results) if results else "No results",
                             "results": results})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
