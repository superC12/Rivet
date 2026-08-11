from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class ChatRequest:
    messages: list[dict[str, str]]
    model: str
    temperature: float = 0.4
    think: bool | str | None = None


class Provider(ABC):
    def __init__(self, provider_id: str, config: dict) -> None:
        self.id = provider_id
        self.config = config
        self.node = config.get("node")
        self.endpoint = str(config.get("endpoint", "")).rstrip("/")
        # Populated from the final stream chunk when the upstream API
        # reports it. Stays None when it does not — an absent count is
        # recorded as absent rather than estimated.
        self.usage: dict[str, int] | None = None

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def list_models(self) -> list[dict]: ...

    @abstractmethod
    async def chat(self, request: ChatRequest) -> AsyncIterator[str]:
        yield ""
