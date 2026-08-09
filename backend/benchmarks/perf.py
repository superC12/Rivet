"""Performance benchmark: speed, memory, and GPU offload per model.

Everything here happens over Ollama's HTTP API, which is a deliberate
departure from the shell-based script this replaces.

**Why not `nvidia-smi`.** Rivet routes to compute that is frequently not
the machine Rivet runs on — a desktop over Tailscale, an always-on
server. Sampling the local GPU would confidently report the wrong card's
memory, and it would be wrong *silently*, which is the worst kind of
measurement. `GET /api/ps` reports `size` and `size_vram` for the model
that is actually loaded on the machine that actually ran it, so the
numbers follow the work.

**Why not `journalctl -u ollama`.** The offload line it greps for is
derivable: `size_vram / size` is the fraction of the model resident on
the GPU. Reading it from the API costs no privileges, whereas shelling
out to `sudo journalctl` from an HTTP request would hand a web endpoint
root, on a dashboard whose entire security posture is built on never
executing arbitrary commands. It also only ever worked when Ollama was
local and systemd-managed.

The one thing genuinely lost is per-layer offload detail. The ratio
answers the question that detail was being used for.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

# A cold model has to be read from disk, so the first token includes load
# time. Reporting a warm number as if it were cold is how benchmarks come
# to disagree with lived experience.
UNLOAD_KEEP_ALIVE = 0
SETTLE_S = 1.0
GENERATE_TIMEOUT_S = 600.0
CONTROL_TIMEOUT_S = 15.0

# Roughly four characters per token. Only used to size a filler prompt,
# where being 20% off changes nothing about what is measured.
CHARS_PER_TOKEN = 4
FILLER = "The quick brown fox jumps over the lazy dog. "


def build_prompt(definition: dict) -> str:
    """The prompt to measure against, generated if none was supplied."""
    custom = str(definition.get("prompt_text") or "").strip()
    if custom:
        return custom
    approx_tokens = max(1, int(definition.get("prompt_tokens", 512)))
    needed = approx_tokens * CHARS_PER_TOKEN
    repeats = (needed // len(FILLER)) + 1
    return (FILLER * repeats)[:needed]


def _rate(count: int | None, duration_ns: int | None) -> float | None:
    """Tokens per second from Ollama's nanosecond durations."""
    if not count or not duration_ns:
        return None
    return round(count / (duration_ns / 1e9), 2)


def summarise(results: list[dict]) -> str:
    measured = [r for r in results if not r.get("error")]
    if not measured:
        return "No model completed the benchmark"
    fastest = max(measured, key=lambda r: r.get("gen_tok_s") or 0)
    return f"{len(measured)} model(s) measured · fastest {fastest['model']} at {fastest.get('gen_tok_s')} tok/s"


class PerfRunner:
    """Measures one Ollama endpoint, one model at a time."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")

    async def _loaded(self, client: httpx.AsyncClient) -> list[dict]:
        try:
            response = await client.get(f"{self.endpoint}/api/ps", timeout=CONTROL_TIMEOUT_S)
            response.raise_for_status()
            return response.json().get("models", []) or []
        except (httpx.HTTPError, ValueError):
            return []

    async def _unload_everything(self, client: httpx.AsyncClient) -> list[str]:
        """Evict every resident model so the next run is genuinely cold."""
        names = [item.get("name") or item.get("model") for item in await self._loaded(client)]
        for name in filter(None, names):
            try:
                await client.post(
                    f"{self.endpoint}/api/generate",
                    json={"model": name, "keep_alive": UNLOAD_KEEP_ALIVE, "stream": False},
                    timeout=CONTROL_TIMEOUT_S,
                )
            except httpx.HTTPError:
                # A model that will not unload is worth reporting, but it
                # is not worth aborting the whole suite over.
                continue
        return [name for name in names if name]

    async def run(self, definition: dict) -> AsyncIterator[dict]:
        """Yield progress events, then one result per model."""
        models = [m for m in definition.get("models", []) if m]
        prompt = build_prompt(definition)
        cold_start = bool(definition.get("cold_start", True))

        async with httpx.AsyncClient() as client:
            for index, model in enumerate(models, 1):
                yield {"event": "progress", "message": f"Testing {model} ({index}/{len(models)})",
                       "current": index, "total": len(models)}

                if cold_start:
                    evicted = await self._unload_everything(client)
                    if evicted:
                        yield {"event": "progress", "message": f"Unloaded {', '.join(evicted)}"}
                    # Eviction is not instantaneous; give it a moment
                    # before asserting the box is actually clear.
                    await asyncio.sleep(SETTLE_S)
                    still = await self._loaded(client)
                    if still:
                        yield {"event": "progress",
                               "message": f"Warning: {len(still)} model(s) still resident; not a clean cold start"}

                yield {"event": "result", "result": await self._measure(client, model, prompt, cold_start)}

    async def _measure(self, client: httpx.AsyncClient, model: str, prompt: str, cold_start: bool) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{self.endpoint}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "think": False},
                timeout=GENERATE_TIMEOUT_S,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"model": model, "error": f"{type(exc).__name__}: {exc}"}

        wall_ms = round((time.perf_counter() - started) * 1000)
        # Read residency while the model is still loaded; keep_alive has
        # not expired yet, so this reflects the run we just did.
        resident = next(
            (item for item in await self._loaded(client) if (item.get("name") or item.get("model")) == model),
            {},
        )
        size = resident.get("size")
        vram = resident.get("size_vram")

        return {
            "model": model,
            "cold_start": cold_start,
            "prompt_tokens": body.get("prompt_eval_count"),
            "gen_tokens": body.get("eval_count"),
            "gen_tok_s": _rate(body.get("eval_count"), body.get("eval_duration")),
            "prompt_tok_s": _rate(body.get("prompt_eval_count"), body.get("prompt_eval_duration")),
            "load_ms": round(body["load_duration"] / 1e6) if body.get("load_duration") else None,
            "total_ms": round(body["total_duration"] / 1e6) if body.get("total_duration") else None,
            "wall_ms": wall_ms,
            "size_bytes": size,
            "vram_bytes": vram,
            # 1.0 means fully on the GPU, 0.0 fully on the CPU. None when
            # the Ollama build does not report residency.
            "gpu_offload": round(vram / size, 3) if size and vram is not None else None,
            "error": None,
        }
