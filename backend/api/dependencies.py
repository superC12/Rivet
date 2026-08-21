from __future__ import annotations

import time

from backend.actions import N8nGateway
from backend.config import settings
from backend.nodes import NodeManager
from backend.providers import OllamaProvider, OpenAICompatibleProvider, OpenRouterProvider, Provider
from backend.routing.classifier import Classifier, _tag_matches
from backend.storage.benchmarks import BenchmarkStore
from backend.storage.conversations import ConversationStore
from backend.storage.database import Database

database = Database(settings.database_path)
store = ConversationStore(database)
benchmark_store = BenchmarkStore(database)


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


def classifier_model_name() -> str:
    """The administrator-selected classifier model, if one is configured."""
    return Classifier((settings.rivet.get("router", {}) or {}).get("classifier", {})).model


def is_classifier_model(model: dict) -> bool:
    """Keep an explicitly configured classifier out of assistant routing.

    Rivet does not supply or assume a classifier model. When an
    administrator dedicates one to dispatch, though, it may be tuned for
    short lane labels rather than conversation and should not be selected
    as the assistant merely because the same provider reports it.
    """
    if not model.get("node"):
        return False
    configured_model = classifier_model_name().strip()
    return bool(configured_model) and _tag_matches(configured_model, str(model.get("id", "")))


async def discover_models(use_cache: bool = True, include_classifier: bool = False) -> list[dict]:
    """List every model Rivet can currently reach.

    Cached, because this runs on the critical path of every chat request
    and an unreachable provider costs a full connection timeout. Without
    it, a homelab whose desktop is asleep pays that delay on every
    message, before routing has even started.

    An explicitly configured classifier is filtered out by default.
    Benchmarks pass `include_classifier=True`, because measuring a model
    an administrator selected for dispatch is still reasonable.
    """
    if use_cache:
        cached = _model_cache.get()
        if cached is None:
            cached = await _discover_models_uncached()
            _model_cache.set(cached)
    else:
        cached = await _discover_models_uncached()
        _model_cache.set(cached)
    # Filter on the way out so one cache entry serves both callers.
    if include_classifier:
        return list(cached)
    return [model for model in cached if not is_classifier_model(model)]


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
                    "capabilities": ["chat"] if isinstance(item, str) else sorted({"chat", *(
                        str(value).lower()
                        for value in item.get("capabilities", [])
                        if isinstance(value, str)
                    )}),
                }
                for item in configured
            )
            continue
        if config.get("type") == "openrouter":
            # OpenRouter's automatic route is useful, but choosing it is
            # still a model decision. Rivet ships no predefined models, so
            # an OpenRouter target appears only after the owner names one.
            model_id = str(config.get("model", "")).strip()
            if model_id:
                models.append({
                    "id": model_id,
                    "name": config.get("display_model", model_id),
                    "provider": provider_id,
                    "node": None,
                    "capabilities": sorted({"chat", *(
                        str(value).lower()
                        for value in config.get("capabilities", [])
                        if isinstance(value, str)
                    )}),
                })
            continue
        models.extend(await provider.list_models())
    return models
