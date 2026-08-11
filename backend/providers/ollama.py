from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncIterator

import httpx

from backend.nodes.health import probe
from .base import ChatRequest, Provider, ProviderError


_CAPABILITY_TTL_S = 300.0
_capability_cache: dict[tuple[str, str], tuple[list[str], float]] = {}


class OllamaProvider(Provider):
    DEFAULT_DISCOVERY_ENDPOINTS = (
        "http://host.docker.internal:11434",
        "http://ollama:11434",
    )

    def _discovery_candidates(self) -> list[str]:
        """Return bounded, server-controlled Ollama candidates.

        Rivet deliberately does not scan the LAN. The configured endpoint
        remains authoritative and is tried first; discovery only adds
        administrator-provided addresses and the two conventional Docker
        host/service names.
        """
        candidates = [self.endpoint]
        if self.config.get("auto_detect", False):
            environment = os.getenv("RIVET_OLLAMA_ENDPOINTS", "")
            candidates.extend(item.strip() for item in environment.split(","))
            configured = self.config.get("discovery_endpoints", [])
            if isinstance(configured, str):
                configured = [configured]
            candidates.extend(str(item).strip() for item in configured)
            candidates.extend(self.DEFAULT_DISCOVERY_ENDPOINTS)

        unique: list[str] = []
        for candidate in candidates:
            normalized = str(candidate).rstrip("/")
            if normalized and normalized not in unique:
                unique.append(normalized)
        return unique

    async def _resolve_endpoint(self) -> str | None:
        candidates = self._discovery_candidates()
        if not candidates:
            return None
        if await probe(candidates[0]):
            self.endpoint = candidates[0]
            return self.endpoint
        if len(candidates) == 1:
            return None

        # Alternative Docker/admin candidates are independent. Probe them
        # concurrently so a missing DNS name costs one timeout, not one per
        # candidate.
        results = await asyncio.gather(*(probe(candidate) for candidate in candidates[1:]))
        for candidate, online in zip(candidates[1:], results, strict=False):
            if online:
                self.endpoint = candidate
                return self.endpoint
        return None

    async def health(self) -> bool:
        return await self._resolve_endpoint() is not None

    async def list_models(self) -> list[dict]:
        endpoint = await self._resolve_endpoint()
        if endpoint is None:
            return []
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{endpoint}/api/tags")
                response.raise_for_status()
            items = response.json().get("models", [])
            # /api/tags does not report thinking/vision support. /api/show
            # does, and these small metadata calls run concurrently and are
            # cached so routing never guesses from a model name.
            capabilities = await asyncio.gather(
                *(self.model_capabilities(item["name"], endpoint=endpoint) for item in items)
            )
            return [
                {
                    "id": item["name"],
                    "name": item["name"],
                    "provider": self.id,
                    "node": self.node,
                    "size": item.get("size"),
                    "capabilities": sorted({"chat", *caps}),
                }
                for item, caps in zip(items, capabilities, strict=False)
            ]
        except (httpx.HTTPError, KeyError, ValueError):
            return []

    async def chat(self, request: ChatRequest) -> AsyncIterator[str]:
        payload = {"model": request.model, "messages": request.messages, "stream": True, "options": {"temperature": request.temperature}}
        endpoint = await self._resolve_endpoint() or self.endpoint
        if request.think is not None:
            capabilities = await self.model_capabilities(request.model, endpoint=endpoint)
            # Sending think=true to an unsupported Ollama model is a 400.
            # think=false is safe and is the hard switch hybrid Qwen models
            # need, so unsupported "on" requests downgrade rather than fail.
            payload["think"] = request.think if "thinking" in capabilities else False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                async with client.stream("POST", f"{endpoint}/api/chat", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            self._record_usage(chunk)
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Ollama stopped responding: {exc}") from exc

    async def model_capabilities(self, model: str, endpoint: str | None = None) -> list[str]:
        resolved = (endpoint or await self._resolve_endpoint() or self.endpoint).rstrip("/")
        key = (resolved, model)
        cached = _capability_cache.get(key)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(f"{resolved}/api/show", json={"model": model})
                response.raise_for_status()
            values = response.json().get("capabilities", [])
            capabilities = [str(value).lower() for value in values if isinstance(value, str)]
        except (httpx.HTTPError, KeyError, ValueError):
            capabilities = []
        _capability_cache[key] = (capabilities, time.monotonic() + _CAPABILITY_TTL_S)
        return capabilities

    def _record_usage(self, chunk: dict) -> None:
        prompt = chunk.get("prompt_eval_count")
        completion = chunk.get("eval_count")
        if prompt is None and completion is None:
            return
        self.usage = {"prompt_tokens": prompt, "completion_tokens": completion}
