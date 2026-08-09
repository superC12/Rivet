"""Action gateway interface.

An action is the only thing Rivet does that changes the world outside
itself. Everything here exists to make one rule enforceable:

    Rivet reports success only when the gateway confirms success.

Not when the request returned 200. Not when a model said it worked. A
webhook that accepts a payload and silently drops it is the single most
common way an automation chain lies to its user, so "accepted" and
"executed" are different statuses and Rivet never collapses them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Confirmed by the gateway. The only status that may be phrased as done.
EXECUTED = "executed"
# The gateway explicitly reported a failure.
FAILED = "failed"
# 2xx, but nothing in the response confirms the work actually happened.
UNCONFIRMED = "unconfirmed"
# Could not reach the gateway at all.
UNREACHABLE = "unreachable"
# The gateway answered with an error status.
REJECTED = "rejected"
# No gateway is configured.
NOT_CONFIGURED = "not_configured"

SUCCESS_STATUSES = frozenset({EXECUTED})


@dataclass(slots=True)
class ActionResult:
    status: str
    message: str
    detail: str | None = None
    workflow: str | None = None
    steps: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    data: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in SUCCESS_STATUSES


class ActionGateway(ABC):
    """A deterministic executor of user intent.

    Implementations translate a request into a structured payload for a
    system that actually performs work. They do not decide *what* to do
    beyond passing the request along — improvising tool calls is exactly
    the behaviour this design exists to prevent.
    """

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    async def execute(self, text: str, context: dict[str, Any] | None = None) -> ActionResult: ...
