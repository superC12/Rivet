from __future__ import annotations

from fastapi import APIRouter

from backend.config import settings

router = APIRouter(prefix="/api/routes")


@router.get("")
async def routes() -> dict:
    config = settings.rivet["router"]
    return {
        "strategy": config.get("strategy", "auto"),
        "modes": ["auto", "local_only", "cloud", "model_override"],
        "prefer_local": config.get("prefer_local", True),
        "privacy_mode": config.get("privacy_mode", "standard"),
        "session_affinity": config.get("session_affinity", True),
        "fallback": config.get("fallback"),
    }
