from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from backend import __version__
from backend.config import settings
from .classify import build_classifier
from .dependencies import database, nodes, provider_node_type, providers

router = APIRouter()


async def _provider_status(provider_id: str, provider) -> dict:
    started = time.perf_counter()
    try:
        healthy = await provider.health()
    except Exception:
        healthy = False
    return {
        "id": provider_id,
        "type": provider.config.get("type"),
        "node": provider.node,
        "node_type": provider_node_type(provider),
        "status": "online" if healthy else "offline",
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/api/status")
async def status() -> dict:
    provider_instances = providers()
    provider_status = await asyncio.gather(
        *(_provider_status(provider_id, provider) for provider_id, provider in provider_instances.items())
    )
    node_status = await nodes().list()
    classifier = await build_classifier().health()
    return {
        "status": "ok" if database.healthy() else "degraded",
        "version": __version__,
        "platform": settings.assistant["platform"]["name"],
        "database": {"status": "ok" if database.healthy() else "error"},
        "router": {
            "status": "ok" if classifier["status"] == "ok" else "degraded",
            "strategy": settings.rivet["router"].get("strategy", "auto"),
        },
        # A broken dispatcher does not fail loudly — it quietly sends
        # every request to the fallback lane. Surface it here or nobody
        # finds out until the bill arrives.
        "classifier": classifier,
        "providers": provider_status,
        "nodes": node_status,
    }
