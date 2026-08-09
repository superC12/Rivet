from __future__ import annotations

import re
from typing import Any
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import AnyHttpUrl, BaseModel, Field, model_validator

from backend.config import settings
from backend.nodes.health import cache as health_cache
from .dependencies import invalidate_model_cache

router = APIRouter(prefix="/api")


class SettingsPayload(BaseModel):
    assistant: dict[str, Any] | None = None
    interface: dict[str, Any] | None = None
    router: dict[str, Any] | None = None
    onboarding: dict[str, Any] | None = None
    providers: dict[str, Any] | None = None
    nodes: dict[str, Any] | None = None
    # Without this, Pydantic drops the field before `Settings.update` ever
    # sees it, and the Connections panel saves successfully while changing
    # nothing at all.
    actions: dict[str, Any] | None = None


class ManualProviderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    type: Literal["ollama", "openai_compatible", "openrouter"]
    endpoint: AnyHttpUrl | None = None
    location: Literal["local", "remote", "cloud"] = "local"
    api_key_env: str = Field(default="", pattern=r"^(?:[A-Z_][A-Z0-9_]*)?$")

    @model_validator(mode="after")
    def endpoint_is_present_when_needed(self):
        if self.type != "openrouter" and self.endpoint is None:
            raise ValueError("An endpoint is required for this provider type")
        return self


def _manual_provider_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return f"manual-{slug or 'provider'}"


@router.get("/settings")
async def get_settings() -> dict:
    return settings.public()


@router.post("/settings")
async def save_settings(payload: SettingsPayload) -> dict:
    result = settings.update(payload.model_dump(exclude_none=True))
    # Providers may have changed, so what is reachable may have changed.
    invalidate_model_cache()
    return result


@router.post("/providers/manual")
async def save_manual_provider(payload: ManualProviderPayload) -> dict:
    """Persist a provider the user entered explicitly.

    API keys are never accepted here. The optional value is the *name* of
    an environment variable already present on the Rivet server.
    """
    provider_id = _manual_provider_id(payload.name)
    location = "cloud" if payload.type == "openrouter" else payload.location
    node_id = None if location == "cloud" else f"{provider_id}-node"
    provider: dict[str, Any] = {
        "type": payload.type,
        "display_name": payload.name.strip(),
        "node": node_id,
        "manual": True,
        # An explicitly named connection must never be silently redirected
        # to a different Ollama instance when its endpoint is offline.
        "auto_detect": False,
    }
    if payload.endpoint is not None:
        provider["endpoint"] = str(payload.endpoint).rstrip("/")
    if payload.type == "openai_compatible" and payload.api_key_env:
        provider["api_key_env"] = payload.api_key_env

    update: dict[str, Any] = {"providers": {provider_id: provider}}
    if node_id:
        update["nodes"] = {
            node_id: {
                "type": "local" if location == "local" else "remote",
                "display_name": payload.name.strip(),
                "always_on": True,
                "manual": True,
            }
        }
    result = settings.update(update)
    health_cache.invalidate()
    invalidate_model_cache()
    return {"provider_id": provider_id, "settings": result}


@router.delete("/providers/manual/{provider_id}")
async def delete_manual_provider(provider_id: str) -> dict:
    result = settings.remove_manual_provider(provider_id)
    if result is None:
        raise HTTPException(404, "Manual provider not found")
    health_cache.invalidate()
    invalidate_model_cache()
    return {"provider_id": provider_id, "settings": result}


@router.post("/onboarding")
async def onboarding(payload: SettingsPayload) -> dict:
    data = payload.model_dump(exclude_none=True)
    data["onboarding"] = {"complete": True}
    result = settings.update(data)
    invalidate_model_cache()
    return result
