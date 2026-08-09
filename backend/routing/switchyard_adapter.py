"""Optional external routing engine adapter.

This is a **seam, not a shipped integration**. It exists so that adopting
an external router later is a configuration change rather than a rewrite,
and it has not been verified against a running Switchyard instance.

It is off unless `router.engine: switchyard` is set. When it is on and
the endpoint does not answer in a way this adapter understands, it hands
the request back to the built-in router and says so in the trace. It
never invents a decision — a router that guesses is worse than one that
admits it does not know.
"""

from __future__ import annotations

import logging

import httpx

from .builtin import BuiltInRouter
from .classifier import Classification
from .decision import RouteDecision, trace_step
from .policies import TIERS, RoutingPolicy, tier_of

logger = logging.getLogger("rivet.routing.switchyard")


class SwitchyardRouter:
    """Delegates selection to an external routing service."""

    name = "switchyard"

    def __init__(self, policy: RoutingPolicy, nodes: dict, config: dict | None = None) -> None:
        self.policy = policy
        self.nodes = nodes
        config = config or {}
        self.endpoint = str(config.get("endpoint", "")).rstrip("/")
        self.timeout_s = float(config.get("timeout_s", 3.0))
        self.builtin = BuiltInRouter(policy, nodes)

    async def select(
        self,
        classification: Classification,
        models: list[dict],
        mode: str = "auto",
        model_override: str | None = None,
        affinity: tuple[str | None, str | None] = (None, None),
    ) -> RouteDecision:
        fallback = self.builtin.select(classification, models, mode, model_override, affinity)
        if not self.endpoint or model_override:
            return fallback

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.endpoint}/route",
                    json={
                        "lane": classification.lane,
                        "mode": mode,
                        "models": [
                            {"id": m["id"], "provider": m["provider"], "tier": tier_of(m, self.nodes)}
                            for m in models
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("switchyard unavailable error=%s", type(exc).__name__)
            fallback.trace.insert(0, trace_step("External router unavailable; using built-in"))
            return fallback

        return self._interpret(payload, models, mode, fallback)

    def _interpret(self, payload: dict, models: list[dict], mode: str, fallback: RouteDecision) -> RouteDecision:
        """Accept an external decision only if it names a model we have.

        An external router pointing at a provider this deployment has not
        configured is a misconfiguration, not an instruction.
        """
        provider_id = payload.get("provider")
        model_id = payload.get("model")
        selected = next((m for m in models if m["provider"] == provider_id and m["id"] == model_id), None)
        if not selected:
            fallback.trace.insert(0, trace_step("External router named an unknown model; using built-in"))
            return fallback

        tier = tier_of(selected, self.nodes)
        # Validate against *this request's* mode, not "auto". A request
        # sent as Local only must stay local even when an external engine
        # is confident it knows better; the constraint is the user's, and
        # an outside service does not get to relax it.
        if tier not in self.policy.allowed_tiers(mode) or tier not in TIERS:
            fallback.trace.insert(0, trace_step("External router violated the route policy; using built-in"))
            return fallback

        return RouteDecision(
            route=tier,
            confidence=float(payload.get("confidence", 0.8)),
            reason=str(payload.get("reason", "External router decision")),
            provider=selected["provider"],
            model=selected["id"],
            node=selected.get("node"),
            lane=fallback.lane,
            trace=[trace_step(f"External router → {selected['name']}")],
        )
