from __future__ import annotations

import asyncio

from fastapi import APIRouter

from .dependencies import discover_models, provider_node_type, providers

router = APIRouter(prefix="/api")


@router.get("/models")
async def models() -> list[dict]:
    return await discover_models()


@router.get("/providers")
async def list_providers() -> list[dict]:
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
            "manual": bool(provider.config.get("manual")),
            "status": "online" if online else "offline",
        }
        for (provider_id, provider), online in zip(instances.items(), health, strict=False)
    ]
