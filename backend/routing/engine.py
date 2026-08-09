"""The routing engine facade.

    request
       ↓
    classifier ──► lane (ACTION / LOCAL / ESCALATE)
       ↓
    router     ──► route (ACTION / LOCAL / REMOTE / CLOUD)
                   + provider + model + node

The engine owns the wiring and nothing else. Classification lives in
`classifier.py`, the constraints in `policies.py`, selection in
`builtin.py`, and the optional external strategy in
`switchyard_adapter.py`.

`decide()` is async because classification may call a model. `select()`
is synchronous and takes a `Classification` directly, which is what
selection tests use — they need no event loop and no network.
"""

from __future__ import annotations

from .classifier import Classification, Classifier, HeuristicClassifier
from .decision import RouteDecision, trace_step
from .policies import RoutingPolicy
from .builtin import BuiltInRouter
from .switchyard_adapter import SwitchyardRouter

__all__ = ["RouteDecision", "RoutingEngine", "trace_step"]


class RoutingEngine:
    def __init__(self, config: dict, models: list[dict], classifier: Classifier | None = None) -> None:
        self.config = config
        self.nodes = config.get("nodes", {}) or {}
        self.policy = RoutingPolicy.from_config(config)
        router_config = config.get("router", {}) or {}
        disabled_models = set(router_config.get("disabled_models", []) or [])
        self.models = [
            model for model in models
            if f'{model.get("provider", "")}:{model.get("id", "")}' not in disabled_models
        ]
        self.classifier = classifier or Classifier(router_config.get("classifier", {}))
        self.engine_name = str(router_config.get("engine", "builtin")).lower()
        if self.engine_name == "switchyard":
            self.router: BuiltInRouter | SwitchyardRouter = SwitchyardRouter(
                self.policy, self.nodes, router_config.get("switchyard", {})
            )
        else:
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
        else:
            classification = await self.classifier.classify(text)
        return await self._select(classification, mode, model_override, affinity)

    def select(
        self,
        classification: Classification,
        mode: str = "auto",
        model_override: str | None = None,
        affinity: tuple[str | None, str | None] = (None, None),
    ) -> RouteDecision:
        """Synchronous selection for a classification you already have."""
        if isinstance(self.router, SwitchyardRouter):
            raise RuntimeError("The Switchyard router is async; use decide() instead")
        return self.router.select(classification, self.models, mode, model_override, affinity)

    async def _select(
        self,
        classification: Classification,
        mode: str,
        model_override: str | None,
        affinity: tuple[str | None, str | None],
    ) -> RouteDecision:
        if isinstance(self.router, SwitchyardRouter):
            return await self.router.select(classification, self.models, mode, model_override, affinity)
        return self.router.select(classification, self.models, mode, model_override, affinity)


def heuristic_decision(config: dict, models: list[dict], text: str, **kwargs) -> RouteDecision:
    """Classify with the heuristic and select, without an event loop.

    Convenience for tests and the eval harness.
    """
    engine = RoutingEngine(config, models)
    return engine.select(HeuristicClassifier().classify(text), **kwargs)
