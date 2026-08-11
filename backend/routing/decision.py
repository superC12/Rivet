"""The routing decision and its trace.

Lives in its own module so `engine.py` and `builtin.py` can both use it
without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def trace_step(message: str) -> dict:
    return {"time": datetime.now().strftime("%H:%M:%S"), "message": message}


@dataclass(slots=True)
class RouteDecision:
    route: str
    confidence: float
    reason: str
    provider: str | None = None
    model: str | None = None
    node: str | None = None
    lane: str | None = None
    confident: bool = True
    thinking: bool | str | None = None
    trace: list[dict] = field(default_factory=list)

    def step(self, message: str) -> None:
        self.trace.append(trace_step(message))
