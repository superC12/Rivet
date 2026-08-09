from __future__ import annotations

import time

from backend.actions import N8nGateway
from backend.config import settings
from backend.nodes import NodeManager
from backend.providers import OllamaProvider, OpenAICompatibleProvider, OpenRouterProvider, Provider
from backend.storage.conversations import ConversationStore
from backend.storage.database import Database

database = Database(settings.database_path)
store = ConversationStore(database)


def action_gateway() -> N8nGateway:
    return N8nGateway(settings.rivet.get("actions", {}).get("n8n", {}))


def providers() -> dict[str, Provider]:
    result: dict[str, Provider] = {}
    for provider_id, config in settings.rivet.get("providers", {}).items():
        provider_type = config.get("type")
        if provider_type == "ollama":
            result[provider_id] = OllamaProvider(provider_id, config)
        elif provider_type == "openrouter":
            result[provider_id] = OpenRouterProvider(provider_id, config)
        elif provider_type == "openai_compatible":
            result[provider_id] = OpenAICompatibleProvider(provider_id, config)
    return result


def nodes() -> NodeManager:
    return NodeManager(settings.rivet.get("nodes", {}), settings.rivet.get("providers", {}))


def provider_node_type(provider: Provider) -> str | None:
    """Return where a provider's compute node actually runs."""
    if not provider.node:
        return None
    node = settings.rivet.get("nodes", {}).get(provider.node, {})
    return str(node.get("type", "local")).lower()


async def discover_models(use_cache: bool = True) -> list[dict]:
    """List every model Rivet can currently reach.

    Cached, because this runs on the critical path of every chat request
    and an unreachable provider costs a full connection timeout. Without
    it, a homelab whose desktop is asleep pays that delay on every
    message, before routing has even started.
    """
    if use_cache:
        cached = _model_cache.get()
        if cached is not None:
            return cached
    models = await _discover_models_uncached()
    _model_cache.set(models)
    return models


class _ModelCache:
    TTL_S = 20.0

    def __init__(self) -> None:
        self._models: list[dict] | None = None
        self._expires_at = 0.0

    def get(self) -> list[dict] | None:
        if self._models is None or time.monotonic() >= self._expires_at:
            return None
        return self._models

    def set(self, models: list[dict]) -> None:
        self._models = models
        self._expires_at = time.monotonic() + self.TTL_S

    def invalidate(self) -> None:
        self._models = None


_model_cache = _ModelCache()


def invalidate_model_cache() -> None:
    """Call after anything that changes what is reachable."""
    _model_cache.invalidate()


async def _discover_models_uncached() -> list[dict]:
    models: list[dict] = []
    for provider_id, provider in providers().items():
        config = settings.rivet["providers"][provider_id]
        configured = config.get("models", [])
        if configured:
            models.extend(
                {
                    "id": item if isinstance(item, str) else item["id"],
                    "name": item if isinstance(item, str) else item.get("name", item["id"]),
                    "provider": provider_id,
                    "node": provider.node,
                    "capabilities": ["chat"],
                }
                for item in configured
            )
            continue
        if config.get("type") == "openrouter":
            model_id = config.get("model", "administrator-selected-cloud-model")
            models.append({"id": model_id, "name": config.get("display_model", "OpenRouter Auto"), "provider": provider_id, "node": None, "capabilities": ["chat"]})
            continue
        models.extend(await provider.list_models())
    return models
