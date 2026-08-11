"""Optional model-assisted routing layered over Rivet's hard rules.

The normal router remains authoritative and is always available.  This
module only advises on the best enabled candidate and whether deliberate
thinking is worth its latency for this request.  Privacy, action safety,
manual overrides, and candidate validation stay deterministic.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .classifier import Classification
from .policies import RoutingPolicy, sort_candidates, tier_of

AskModel = Callable[[dict, list[dict[str, str]]], Awaitable[str]]
MAX_ROUTED_CHARS = 2400


@dataclass(slots=True)
class RoutingAdvice:
    model_key: str
    thinking: bool
    reason: str


class OptionalModelRouter:
    """Ask one user-selected model for a compact, validated route decision."""

    def __init__(self, config: dict | None, nodes: dict, policy: RoutingPolicy, ask: AskModel | None) -> None:
        self.config = config or {}
        self.nodes = nodes
        self.policy = policy
        self.ask = ask
        self.model_key = str(self.config.get("model", "")).strip()
        self.thinking_policy = str(self.config.get("thinking_policy", "auto")).lower()

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False) and self.model_key and self.ask)

    async def advise(
        self,
        text: str,
        classification: Classification,
        models: list[dict],
        mode: str,
        affinity: tuple[str | None, str | None],
    ) -> tuple[RoutingAdvice | None, str | None]:
        if not self.enabled:
            return None, None

        ordered = sort_candidates(models)
        router_model = next((model for model in ordered if self._key(model) == self.model_key), None)
        if not router_model:
            return None, "selected routing model is disabled or unavailable"

        allowed = set(self.policy.allowed_tiers(mode))
        if tier_of(router_model, self.nodes) not in allowed:
            return None, "privacy or route mode blocks the selected routing model"

        candidates = [model for model in ordered if tier_of(model, self.nodes) in allowed]
        if not candidates:
            return None, "no policy-compatible model is available"

        manifest = [
            {
                "key": self._key(model),
                "name": model.get("name", model.get("id", "model")),
                "tier": tier_of(model, self.nodes),
                "priority": index + 1,
                "capabilities": model.get("capabilities", ["chat"]),
            }
            for index, model in enumerate(candidates)
        ]
        provider_id, model_id = affinity
        affinity_key = f"{provider_id}:{model_id}" if provider_id and model_id else None
        messages = [
            {
                "role": "system",
                "content": self._system_prompt(manifest, classification, affinity_key),
            },
            {"role": "user", "content": text[:MAX_ROUTED_CHARS]},
        ]
        try:
            raw = await self.ask(router_model, messages)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - optional advice never breaks routing
            return None, f"routing model unavailable ({type(exc).__name__})"

        advice = self._parse(raw, {item["key"] for item in manifest})
        if not advice:
            return None, "routing model returned an invalid decision"
        if self.thinking_policy == "never":
            advice.thinking = False
        elif self.thinking_policy == "always":
            advice.thinking = True
        selected = next(model for model in candidates if self._key(model) == advice.model_key)
        if "thinking" not in selected.get("capabilities", []):
            advice.thinking = False
        return advice, None

    def _system_prompt(self, manifest: list[dict], classification: Classification, affinity: str | None) -> str:
        return (
            "You are Rivet's optional routing advisor. Do not answer the request. "
            "Choose exactly one candidate and whether deliberate thinking is worth its extra latency and energy. "
            "Hard policy filtering is already done. Priority 1 is preferred; choose a lower-priority model only "
            "when its tier or capability materially improves this request. A local model with thinking may be "
            "better than waking remote compute for moderate reasoning. Use thinking=false for greetings, lookup, "
            "rewrites, summaries, and straightforward instructions; use true only for genuinely multi-step math, "
            "code, diagnosis, planning, or analysis. Preserve affinity when it remains suitable. Return JSON only: "
            '{"model":"provider:model","thinking":false,"reason":"short reason"}. '
            f"Fallback lane: {classification.lane}. Affinity: {affinity or 'none'}. "
            f"Candidates: {json.dumps(manifest, separators=(',', ':'))}"
        )

    @staticmethod
    def _parse(raw: str, allowed: set[str]) -> RoutingAdvice | None:
        match = re.search(r"\{.*?\}", raw or "", re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            return None
        model_key = str(payload.get("model", ""))
        thinking = payload.get("thinking")
        if model_key not in allowed or not isinstance(thinking, bool):
            return None
        reason = " ".join(str(payload.get("reason", "Model-assisted route")).split())[:160]
        return RoutingAdvice(model_key=model_key, thinking=thinking, reason=reason or "Model-assisted route")

    @staticmethod
    def _key(model: dict) -> str:
        return f'{model.get("provider", "")}:{model.get("id", "")}'
