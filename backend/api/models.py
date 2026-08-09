from __future__ import annotations

import asyncio

from fastapi import APIRouter

from backend.config import settings
from backend.nodes.health import cache as health_cache
from .dependencies import discover_models, invalidate_model_cache, provider_node_type, providers

router = APIRouter(prefix="/api")


@router.get("/models")
async def models() -> list[dict]:
    router_config = settings.rivet.get("router", {}) or {}
    disabled = set(router_config.get("disabled_models", []) or [])
    priority = {key: index for index, key in enumerate(router_config.get("model_priority", []) or [])}
    discovered = await discover_models()
    if priority:
        discovered = [
            model
            for _, model in sorted(
                enumerate(discovered),
                key=lambda pair: priority.get(
                    f'{pair[1].get("provider", "")}:{pair[1].get("id", "")}',
                    len(priority) + pair[0],
                ),
            )
        ]
    return [
        {
            **model,
            "enabled": f'{model.get("provider", "")}:{model.get("id", "")}' not in disabled,
        }
        for model in discovered
    ]


@router.get("/providers")
async def list_providers(refresh: bool = False) -> list[dict]:
    if refresh:
        # A deliberate retry should not be held behind the long negative
        # health TTL. This matters during onboarding when Ollama may finish
        # starting a few seconds after Rivet.
        health_cache.invalidate()
        invalidate_model_cache()
    instances = providers()
    health = await asyncio.gather(*(provider.health() for provider in instances.values()))
    return [
        {
            "id": provider_id,
            "type": provider.config.get("type"),
            "name": provider.config.get("display_name", provider_id),
            "node": provider.node,
            "node_type": provider_node_type(provider),
            "endpoint": provider.endpoint if provider.config.get("type") != "openrouter" else "OpenRouter",
            "configured_endpoint": provider.config.get("endpoint"),
            "auto_detect": bool(provider.config.get("auto_detect")),
            "detected": bool(
                provider.config.get("type") == "ollama"
                and provider.endpoint != str(provider.config.get("endpoint", "")).rstrip("/")
            ),
            "manual": bool(provider.config.get("manual")),
            "status": "online" if online else "offline",
        }
        for (provider_id, provider), online in zip(instances.items(), health, strict=False)
    ]
