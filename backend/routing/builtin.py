"""The built-in router: turn a lane into a concrete provider and model.

Classification decided *what kind* of request this is. Selection decides
*which machine answers it*. Splitting the two is what makes routing
testable — selection can be exercised against a fixed model list with no
classifier in the loop, and the classifier can be scored by `eval/`
without a provider anywhere near it.
"""

from __future__ import annotations

from .classifier import ACTION as ACTION_LANE
from .classifier import Classification
from .decision import RouteDecision, trace_step
from .policies import ACTION, CLOUD, ERROR, LOCAL, RoutingPolicy, sort_candidates, tier_of

# Confidence is a report on how the decision was reached, not a
# probability. Explicit user intent outranks a remembered choice, which
# outranks a fresh classification, which outranks a guess.
CONFIDENCE_OVERRIDE = 1.0
CONFIDENCE_AFFINITY = 0.90
CONFIDENCE_CLASSIFIED = 0.92
CONFIDENCE_FALLBACK = 0.50


class BuiltInRouter:
    """Rivet's default selection strategy."""

    name = "builtin"

    def __init__(self, policy: RoutingPolicy, nodes: dict) -> None:
        self.policy = policy
        self.nodes = nodes

    def select(
        self,
        classification: Classification,
        models: list[dict],
        mode: str = "auto",
        model_override: str | None = None,
        affinity: tuple[str | None, str | None] = (None, None),
    ) -> RouteDecision:
        trace: list[dict] = []
        candidates = sort_candidates(models)

        if model_override:
            return self._explicit_model(model_override, candidates, trace)

        if classification.lane == ACTION_LANE:
            trace.append(trace_step("Classified → action"))
            return RouteDecision(
                route=ACTION,
                confidence=CONFIDENCE_CLASSIFIED,
                reason="Action intent detected",
                lane=ACTION_LANE,
                trace=trace,
            )

        trace.append(trace_step(f"Classified → {classification.lane.lower()} ({classification.source})"))
        if not classification.confident:
            # Failing upward is only safe if it is visible. Say so.
            trace.append(trace_step(f"Classifier fell back → {classification.error or 'low confidence'}"))

        affinity_choice = self._affinity(classification, candidates, mode, affinity, trace)
        if affinity_choice:
            return affinity_choice

        preference = self.policy.preference(classification.lane, mode)
        if not preference:
            return RouteDecision(
                route=ERROR,
                confidence=CONFIDENCE_OVERRIDE,
                reason="Cloud is disabled by the privacy policy",
                lane=classification.lane,
                trace=trace,
            )

        confidence = CONFIDENCE_CLASSIFIED if classification.confident else CONFIDENCE_FALLBACK
        for index, tier in enumerate(preference):
            pool = [model for model in candidates if tier_of(model, self.nodes) == tier]
            if not pool:
                continue
            selected = pool[0]
            if index > 0:
                trace.append(trace_step(f"No {preference[0].lower()} model available"))
            trace.append(trace_step(f"{selected['name']} selected"))
            return RouteDecision(
                route=tier,
                confidence=confidence,
                reason=self._reason(classification, tier),
                provider=selected["provider"],
                model=selected["id"],
                node=selected.get("node"),
                lane=classification.lane,
                confident=classification.confident,
                trace=trace,
            )

        return RouteDecision(
            route=ERROR,
            confidence=CONFIDENCE_OVERRIDE,
            reason="No compatible model is available",
            lane=classification.lane,
            trace=trace,
        )

    def _explicit_model(self, override: str, candidates: list[dict], trace: list[dict]) -> RouteDecision:
        selected = next(
            (m for m in candidates if m["id"] == override or f'{m["provider"]}:{m["id"]}' == override),
            None,
        )
        if not selected:
            trace.append(trace_step("Requested model is not available"))
            return RouteDecision(ERROR, CONFIDENCE_OVERRIDE, "The requested model is not available", trace=trace)

        tier = tier_of(selected, self.nodes)
        if tier == CLOUD and not self.policy.cloud_allowed:
            # An explicit pick is still user intent, but privacy_mode is a
            # guarantee the user made to themselves earlier. It wins.
            trace.append(trace_step("Requested model is a cloud model; privacy policy blocks it"))
            return RouteDecision(ERROR, CONFIDENCE_OVERRIDE, "Cloud is disabled by the privacy policy", trace=trace)

        trace.append(trace_step(f"Manual model → {selected['name']}"))
        return RouteDecision(
            route=tier,
            confidence=CONFIDENCE_OVERRIDE,
            reason="Manual model override",
            provider=selected["provider"],
            model=selected["id"],
            node=selected.get("node"),
            trace=trace,
        )

    def _affinity(
        self,
        classification: Classification,
        candidates: list[dict],
        mode: str,
        affinity: tuple[str | None, str | None],
        trace: list[dict],
    ) -> RouteDecision | None:
        """Stay on the previous model when nothing has changed.

        Affinity breaks when the lane escalates past what the remembered
        model is for, when the mode no longer permits its tier, or when
        the model has disappeared. Those are the cases where reusing the
        last choice would quietly downgrade the answer.
        """
        provider_id, model_id = affinity
        if not self.policy.session_affinity or not provider_id:
            return None

        selected = next((m for m in candidates if m["provider"] == provider_id and m["id"] == model_id), None)
        if not selected:
            return None

        tier = tier_of(selected, self.nodes)
        if tier not in self.policy.allowed_tiers(mode):
            trace.append(trace_step("Affinity broken → route policy changed"))
            return None
        if classification.lane == "ESCALATE" and tier == LOCAL:
            trace.append(trace_step("Affinity broken → request needs a stronger model"))
            return None

        trace.append(trace_step(f"Session affinity → {selected['name']}"))
        return RouteDecision(
            route=tier,
            confidence=CONFIDENCE_AFFINITY,
            reason="Conversation affinity",
            provider=selected["provider"],
            model=selected["id"],
            node=selected.get("node"),
            lane=classification.lane,
            confident=classification.confident,
            trace=trace,
        )

    def _reason(self, classification: Classification, tier: str) -> str:
        if tier == LOCAL and classification.lane == "ESCALATE":
            return "No stronger model is reachable; answering locally"
        if classification.lane == "ESCALATE":
            return "Complex request"
        return "Local model is sufficient" if tier == LOCAL else classification.reason
