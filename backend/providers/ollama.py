from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import ChatRequest, Provider, ProviderError


class OllamaProvider(Provider):
    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                return (await client.get(f"{self.endpoint}/api/tags")).is_success
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{self.endpoint}/api/tags")
                response.raise_for_status()
            return [
                {
                    "id": item["name"],
                    "name": item["name"],
                    "provider": self.id,
                    "node": self.node,
                    "size": item.get("size"),
                    "capabilities": ["chat"],
                }
                for item in response.json().get("models", [])
            ]
        except (httpx.HTTPError, KeyError, ValueError):
            return []

    async def chat(self, request: ChatRequest) -> AsyncIterator[str]:
        payload = {"model": request.model, "messages": request.messages, "stream": True, "options": {"temperature": request.temperature}}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                async with client.stream("POST", f"{self.endpoint}/api/chat", json=payload) as response:
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

    def _record_usage(self, chunk: dict) -> None:
        prompt = chunk.get("prompt_eval_count")
        completion = chunk.get("eval_count")
        if prompt is None and completion is None:
            return
        self.usage = {"prompt_tokens": prompt, "completion_tokens": completion}
