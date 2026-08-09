"""Classification as a first-class endpoint.

Rivet classifies every chat request internally, but the label is useful
on its own: it is what a dashboard, a script, or a workflow needs to ask
"where would this go?" without actually spending a model call answering
it.

Classifying is deliberately side-effect free. It picks no provider, wakes
no node, runs no action, and writes nothing. `POST /api/chat` is the
endpoint that does things; this one only has an opinion.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.config import settings
from backend.routing import ACTION, Classifier
from backend.routing.policies import RoutingPolicy

router = APIRouter(prefix="/api")


def build_classifier() -> Classifier:
    return Classifier((settings.rivet.get("router", {}) or {}).get("classifier", {}))


class ClassifyPayload(BaseModel):
    text: str = Field(min_length=1, max_length=200_000, description="The request, verbatim.")
    mode: str = "auto"


@router.post("/classify")
async def classify(payload: ClassifyPayload) -> dict:
    classification = await build_classifier().classify(payload.text)
    policy = RoutingPolicy.from_config(settings.rivet)
    return {
        "lane": classification.lane,
        "confident": classification.confident,
        "source": classification.source,
        "reason": classification.reason,
        "latency_ms": classification.latency_ms,
        "raw": classification.raw,
        "error": classification.error,
        # Which execution tiers this lane could actually use under the
        # current policy. The lane alone does not tell you that. ACTION
        # goes to the gateway rather than to a model, so it has none.
        "allowed_tiers": [] if classification.lane == ACTION else list(
            policy.preference(classification.lane, payload.mode)
        ),
    }


@router.get("/classifier")
async def classifier_status() -> dict:
    """Configuration and live health of the classifier."""
    return await build_classifier().health()
