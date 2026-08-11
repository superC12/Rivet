from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.actions import EXECUTED, NOT_CONFIGURED
from backend.config import settings
from backend.providers import ChatRequest, ProviderError
from backend.routing import RoutingEngine, RoutingPolicy, tier_of, trace_step
from backend.routing.policies import sort_candidates
from .dependencies import action_gateway, discover_models, invalidate_model_cache, nodes, providers, store

logger = logging.getLogger("rivet.chat")
router = APIRouter(prefix="/api")


class ChatPayload(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=200_000)
    mode: str = "auto"
    model: str | None = None


def event(name: str, data: object) -> bytes:
    """Frame one SSE event.

    Every payload is JSON-encoded, including plain token strings. A raw
    string containing a newline would otherwise split into a second line
    with no `data:` prefix, and the browser would silently drop it —
    which quietly ate every blank line and code block in a response.
    """
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@router.post("/chat")
async def chat(payload: ChatPayload) -> StreamingResponse:
    conversation = store.get(payload.conversation_id) if payload.conversation_id else None
    if payload.conversation_id and not conversation:
        raise HTTPException(404, "Conversation not found")
    conversation_id = payload.conversation_id or store.create()["id"]
    store.add_message(conversation_id, "user", payload.message)
    request_id = str(uuid4())

    async def stream() -> AsyncIterator[bytes]:
        started = time.perf_counter()
        available_models = await discover_models()
        provider_instances = providers()

        async def ask_routing_model(model: dict, messages: list[dict[str, str]]) -> str:
            provider = provider_instances.get(model.get("provider"))
            if provider is None:
                raise ProviderError("The routing model provider is unavailable")
            result = ""
            async for token in provider.chat(
                ChatRequest(messages=messages, model=model["id"], temperature=0.0, think=False)
            ):
                result += token
            return result

        affinity = store.affinity(conversation_id)
        engine = RoutingEngine(
            settings.rivet,
            available_models,
            model_router_ask=ask_routing_model,
        )
        decision = await engine.decide(payload.message, payload.mode, payload.model, affinity)
        yield event("conversation", {"id": conversation_id})
        yield event("route", {
            "route": decision.route, "confidence": decision.confidence, "reason": decision.reason,
            "provider": decision.provider, "model": decision.model, "node": decision.node,
            "lane": decision.lane, "thinking": decision.thinking, "trace": decision.trace,
        })

        if decision.route == "ACTION":
            async for chunk in run_action(conversation_id, request_id, payload.message, decision, started):
                yield chunk
            return

        if decision.route == "ERROR" or not decision.provider or not decision.model:
            text = f"I couldn't get a model to answer. {decision.reason}"
            store.add_message(conversation_id, "assistant", text, route="ERROR", trace=decision.trace)
            yield event("error", {"message": text, "trace": decision.trace})
            return

        if decision.provider not in provider_instances:
            yield event("error", {"message": "The selected provider is not configured.", "trace": decision.trace})
            return

        if decision.node and not await nodes().reachable(decision.node):
            node_config = settings.rivet.get("nodes", {}).get(decision.node, {})
            display = node_config.get("display_name", decision.node)
            decision.step(f"{display} offline")
            if node_config.get("wake_on_lan", {}).get("enabled"):
                decision.step("Wake packet sent")
                yield event("status", {"state": "waking", "message": f"Waking {display}..."})
                if await nodes().wake_and_wait(decision.node):
                    decision.step(f"{display} reachable")
                    invalidate_model_cache()
                else:
                    decision.step(f"{display} did not respond")

        system_message = {"role": "system", "content": settings.assistant["assistant"]["instructions"]}
        messages = [system_message, *store.history(conversation_id)]
        full_text = ""
        actual_provider = decision.provider
        actual_model = decision.model
        actual_route = decision.route
        actual_node = decision.node
        completed = False

        try:
            try:
                async for token in provider_instances[actual_provider].chat(
                    ChatRequest(messages=messages, model=actual_model, think=decision.thinking)
                ):
                    full_text += token
                    yield event("token", token)
                completed = True
            except ProviderError as exc:
                fallback = choose_fallback(
                    available_models, provider_instances, actual_provider, payload.mode
                )
                if not fallback:
                    logger.warning(
                        "request=%s route=%s provider=%s error=%s",
                        request_id, actual_route, actual_provider, type(exc).__name__,
                    )
                    yield event("error", {"message": "The selected model stopped responding.", "trace": decision.trace})
                    return  # `finally` keeps whatever text arrived first

                fallback_id, fallback_model, fallback_tier = fallback
                yield event("notice", "The first model stopped responding. I switched to the configured fallback.")
                decision.step(f"Fallback → {fallback_id}")
                # The partial text came from a model that failed mid-answer.
                # Both sides have to forget it, or the browser splices the
                # abandoned fragment onto the front of the real answer.
                full_text = ""
                yield event("reset", {"reason": "fallback"})
                actual_provider = fallback_id
                actual_model = fallback_model["id"]
                actual_node = fallback_model.get("node")
                actual_route = fallback_tier
                try:
                    async for token in provider_instances[actual_provider].chat(
                        ChatRequest(messages=messages, model=actual_model, think=decision.thinking)
                    ):
                        full_text += token
                        yield event("token", token)
                    completed = True
                except ProviderError as fallback_exc:
                    logger.warning(
                        "request=%s route=%s provider=%s error=%s",
                        request_id, actual_route, actual_provider, type(fallback_exc).__name__,
                    )
                    yield event("error", {"message": "I couldn't get a model to answer.", "trace": decision.trace})
                    return  # `finally` keeps whatever text arrived first
        finally:
            # A closed browser tab throws GeneratorExit through here. The
            # tokens already generated were paid for either way, so they
            # are kept rather than silently discarded.
            if not completed and full_text:
                store_partial(conversation_id, full_text, decision, actual_provider, actual_model, started)

        usage = provider_instances[actual_provider].usage or {}
        latency = round((time.perf_counter() - started) * 1000)
        metadata = {
            "route": actual_route, "provider": actual_provider, "model": actual_model, "node": actual_node,
            "thinking": decision.thinking,
            "latency_ms": latency, "trace": decision.trace,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        }
        store.add_message(conversation_id, "assistant", full_text, **metadata)
        if settings.rivet["router"].get("session_affinity", True):
            store.set_affinity(conversation_id, actual_provider, actual_model)
        logger.info(
            "request=%s route=%s provider=%s model=%s latency_ms=%s",
            request_id, actual_route, actual_provider, actual_model, latency,
        )
        yield event("done", {**metadata, "conversation_id": conversation_id})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def run_action(conversation_id: str, request_id: str, text: str, decision, started: float) -> AsyncIterator[bytes]:
    """Execute an action and report exactly what the gateway confirmed."""
    gateway = action_gateway()
    if gateway.enabled:
        yield event("status", {"state": "routing", "message": "Running that through your action gateway…"})

    result = await gateway.execute(
        text,
        {
            "conversation_id": conversation_id,
            "request_id": request_id,
            "assistant": settings.assistant["assistant"]["name"],
        },
    )
    if result.status == NOT_CONFIGURED:
        decision.step("No action gateway configured")
    else:
        decision.step(f"n8n → {result.status}")
        if result.workflow:
            decision.step(f"Workflow → {result.workflow}")

    metadata = {
        "route": "ACTION",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "action_status": result.status,
        "trace": decision.trace,
    }
    store.add_message(conversation_id, "assistant", result.message, **metadata)
    logger.info("request=%s route=ACTION action_status=%s", request_id, result.status)
    yield event("token", result.message)
    yield event("done", {**metadata, "conversation_id": conversation_id, "action_succeeded": result.status == EXECUTED})


def choose_fallback(
    available_models: list[dict],
    provider_instances: dict,
    failed_provider: str,
    mode: str,
) -> tuple[str, dict, str] | None:
    """Pick a fallback model that this request is actually allowed to use.

    Checking `privacy_mode` alone is not enough. A request sent with the
    per-request `Local only` mode has to stay local even when the local
    provider is the thing that just died — otherwise the one control a
    user has for "do not send this anywhere" leaks precisely when it
    matters, and it does so silently, as a recovery path.

    Returns `(provider_id, model, tier)`, or None when no permitted
    fallback exists.
    """
    fallback_id = settings.rivet["router"].get("fallback")
    if not fallback_id or fallback_id == failed_provider or fallback_id not in provider_instances:
        return None

    nodes_config = settings.rivet.get("nodes", {}) or {}
    allowed = RoutingPolicy.from_config(settings.rivet).allowed_tiers(mode)
    for model in sort_candidates([m for m in available_models if m["provider"] == fallback_id]):
        tier = tier_of(model, nodes_config)
        if tier in allowed:
            return fallback_id, model, tier
    return None


def store_partial(conversation_id: str, text: str, decision, provider: str | None, model: str | None, started: float) -> None:
    if not text:
        return
    store.add_message(
        conversation_id,
        "assistant",
        text,
        route=decision.route,
        provider=provider,
        model=model,
        node=decision.node,
        latency_ms=round((time.perf_counter() - started) * 1000),
        trace=[*decision.trace, trace_step("Response ended early")],
    )
