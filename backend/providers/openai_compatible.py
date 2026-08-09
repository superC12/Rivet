from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx

from .base import ChatRequest, Provider, ProviderError


class OpenAICompatibleProvider(Provider):
    def __init__(self, provider_id: str, config: dict) -> None:
        super().__init__(provider_id, config)
        key_env = config.get("api_key_env", "OPENAI_COMPATIBLE_API_KEY")
        self.api_key = os.getenv(key_env, "")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def health(self) -> bool:
        if not self.endpoint:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                return (await client.get(f"{self.endpoint}/v1/models", headers=self.headers)).is_success
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[dict]:
        if not self.endpoint:
            return []
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.endpoint}/v1/models", headers=self.headers)
                response.raise_for_status()
            return [{"id": item["id"], "name": item["id"], "provider": self.id, "node": self.node, "capabilities": ["chat"]} for item in response.json().get("data", [])]
        except (httpx.HTTPError, KeyError, ValueError):
            return []

    async def chat(self, request: ChatRequest) -> AsyncIterator[str]:
        payload = {
            "model": request.model,
            "messages": request.messages,
            "stream": True,
            "temperature": request.temperature,
            # Ask for a usage chunk at the end of the stream. Providers
            # that don't support it ignore the field.
            "stream_options": {"include_usage": True},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                async with client.stream("POST", f"{self.endpoint}/v1/chat/completions", headers=self.headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        chunk = json.loads(line[6:])
                        self._record_usage(chunk)
                        choices = chunk.get("choices") or [{}]
                        text = choices[0].get("delta", {}).get("content", "")
                        if text:
                            yield text
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(f"The provider stopped responding: {exc}") from exc

    def _record_usage(self, chunk: dict) -> None:
        usage = chunk.get("usage")
        if not isinstance(usage, dict):
            return
        self.usage = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
