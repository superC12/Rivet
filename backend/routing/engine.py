"""The routing engine facade.

    request
       ↓
    classifier ──► lane (ACTION / LOCAL / ESCALATE)
       ↓
    router     ──► route (ACTION / LOCAL / REMOTE / CLOUD)
                   + provider + model + node

The engine owns the wiring and nothing else. Classification lives in
`classifier.py`, the constraints in `policies.py`, and selection in
`builtin.py`. Optional AI-assisted selection lives in `model_router.py`
and remains advisory to the same hard policy.

`decide()` is async because classification may call a model. `select()`
is synchronous and takes a `Classification` directly, which is what
selection tests use — they need no event loop and no network.
"""

from __future__ import annotations

from .classifier import Classification, Classifier, HeuristicClassifier
from .decision import RouteDecision, trace_step
from .model_router import AskModel, OptionalModelRouter, RoutingAdvice
from .policies import RoutingPolicy, tier_of
from .builtin import BuiltInRouter

__all__ = ["RouteDecision", "RoutingEngine", "trace_step"]


class RoutingEngine:
    def __init__(
        self,
        config: dict,
        models: list[dict],
        classifier: Classifier | None = None,
        model_router_ask: AskModel | None = None,
    ) -> None:
        self.config = config
        self.nodes = config.get("nodes", {}) or {}
        self.policy = RoutingPolicy.from_config(config)
        router_config = config.get("router", {}) or {}
        disabled_models = set(router_config.get("disabled_models", []) or [])
        eligible_models = [
            model for model in models
            if f'{model.get("provider", "")}:{model.get("id", "")}' not in disabled_models
        ]
        priority = {
            key: index
            for index, key in enumerate(router_config.get("model_priority", []) or [])
        }
        if priority:
            self.models = [
                {
                    **model,
                    "priority": priority.get(
                        f'{model.get("provider", "")}:{model.get("id", "")}',
                        len(priority) + int(model.get("priority", 100)),
                    ),
                }
                for model in eligible_models
            ]
        else:
            self.models = eligible_models
        self.classifier = classifier or Classifier(router_config.get("classifier", {}))
        self.model_router = OptionalModelRouter(
            router_config.get("routing_model", {}), self.nodes, self.policy, model_router_ask
        )
        self.router = BuiltInRouter(self.policy, self.nodes)

    async def decide(
        self,
        text: str,
        mode: str = "auto",
        model_override: str | None = None,
        affinity: tuple[str | None, str | None] = (None, None),
    ) -> RouteDecision:
        # A manual model choice is an instruction, not a question. Skip
        # the classifier entirely rather than paying for a label nobody
        # is going to read.
        if model_override:
            classification = Classification(lane="LOCAL", reason="Manual model override", source="override")
        elif self.model_router.enabled:
            # The optional routing model already performs semantic
            # selection. Keep the deterministic heuristic as its action
            # safety gate and as the zero-latency fallback.
            classification = HeuristicClassifier().classify(text)
        else:
            classification = await self.classifier.classify(text)
        if self.model_router.enabled and not model_override and classification.lane != "ACTION":
            advice, error = await self.model_router.advise(text, classification, self.models, mode, affinity)
            if advice:
                return self._advised_decision(classification, advice)
            decision = await self._select(classification, mode, model_override, affinity)
            if error:
                decision.step(f"Model router skipped → {error}; built-in rules used")
            return decision
        return await self._select(classification, mode, model_override, affinity)

    def select(
        self,
        classification: Classification,
        mode: str = "auto",
        model_override: str | None = None,
        affinity: tuple[str | None, str | None] = (None, None),
    ) -> RouteDecision:
        """Synchronous selection for a classification you already have."""
        return self.router.select(classification, self.models, mode, model_override, affinity)

    async def _select(
        self,
        classification: Classification,
        mode: str,
        model_override: str | None,
        affinity: tuple[str | None, str | None],
    ) -> RouteDecision:
        return self.router.select(classification, self.models, mode, model_override, affinity)

    def _advised_decision(self, classification: Classification, advice: RoutingAdvice) -> RouteDecision:
        selected = next(
            model
            for model in self.models
            if f'{model.get("provider", "")}:{model.get("id", "")}' == advice.model_key
        )
        tier = tier_of(selected, self.nodes)
        return RouteDecision(
            route=tier,
            confidence=0.88,
            reason=advice.reason,
            provider=selected["provider"],
            model=selected["id"],
            node=selected.get("node"),
            lane=classification.lane,
            confident=True,
            thinking=advice.thinking,
            trace=[
                trace_step(f"Classified → {classification.lane.lower()} (built-in safety gate)"),
                trace_step(f"Model router → {selected.get('name', selected['id'])}"),
                trace_step(f"Thinking → {'on' if advice.thinking else 'off'}"),
            ],
        )


def heuristic_decision(config: dict, models: list[dict], text: str, **kwargs) -> RouteDecision:
    """Classify with the heuristic and select, without an event loop.

    Convenience for tests and the eval harness.
    """
    engine = RoutingEngine(config, models)
    return engine.select(HeuristicClassifier().classify(text), **kwargs)
