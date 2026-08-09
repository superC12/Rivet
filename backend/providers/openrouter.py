from __future__ import annotations

import os

from backend.config import settings
from .openai_compatible import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, provider_id: str, config: dict) -> None:
        prepared = {**config, "endpoint": "https://openrouter.ai/api", "api_key_env": "OPENROUTER_API_KEY"}
        super().__init__(provider_id, prepared)
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")

    @property
    def headers(self) -> dict[str, str]:
        headers = super().headers
        headers.update({"HTTP-Referer": "http://127.0.0.1", "X-Title": settings.assistant["platform"]["name"]})
        return headers

    async def health(self) -> bool:
        return bool(self.api_key) and await super().health()
