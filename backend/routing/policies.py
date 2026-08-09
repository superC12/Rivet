"""Routing policy: the rules that constrain where a request may run.

Kept separate from both classification and selection because these are
the parts a user actually configures, and because they are the parts that
must hold even when everything else misbehaves. `privacy_mode` in
particular is a guarantee, not a preference — nothing in the selection
path is allowed to route around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Where a model physically runs.
LOCAL = "LOCAL"
REMOTE = "REMOTE"
CLOUD = "CLOUD"
ACTION = "ACTION"
ERROR = "ERROR"

TIERS = (LOCAL, REMOTE, CLOUD)


def tier_of(model: dict, nodes: dict[str, Any]) -> str:
    """Classify a model by where it executes.

    A model with no node is somebody else's computer, so it is CLOUD. A
    model on a node declared `type: local` is LOCAL. Anything else is a
    machine the user owns but has to reach across a network, so REMOTE.

    Node type drives this rather than a hardcoded node name, so renaming
    `homelab` does not silently reclassify every route.
    """
    node_id = model.get("node")
    if not node_id:
        return CLOUD
    node = nodes.get(node_id, {})
    return LOCAL if str(node.get("type", "local")).lower() == "local" else REMOTE


@dataclass(slots=True)
class RoutingPolicy:
    strategy: str = "auto"
    prefer_local: bool = True
    privacy_mode: str = "standard"
    session_affinity: bool = True
    fallback: str | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> RoutingPolicy:
        router = config.get("router", {}) or {}
        return cls(
            strategy=str(router.get("strategy", "auto")).lower(),
            prefer_local=bool(router.get("prefer_local", True)),
            privacy_mode=str(router.get("privacy_mode", "standard")).lower(),
            session_affinity=bool(router.get("session_affinity", True)),
            fallback=router.get("fallback"),
        )

    @property
    def cloud_allowed(self) -> bool:
        """`privacy_mode: local_only` bans third-party providers.

        It does not ban REMOTE. A remote node is hardware the user owns;
        reaching it over Tailscale keeps the content inside their own
        estate. The per-request `local_only` *mode* is the stricter one
        that pins execution to the local machine.
        """
        return self.privacy_mode != "local_only"

    def allowed_tiers(self, mode: str) -> tuple[str, ...]:
        """Tiers this request may use, before preference ordering."""
        normalized = mode.lower().replace("-", "_").replace(" ", "_")
        if normalized == "local_only":
            return (LOCAL,)
        if normalized == "cloud":
            return (CLOUD,) if self.cloud_allowed else ()
        allowed = [LOCAL, REMOTE]
        if self.cloud_allowed:
            allowed.append(CLOUD)
        return tuple(allowed)

    def preference(self, lane: str, mode: str) -> tuple[str, ...]:
        """Ordered tiers for a lane, filtered by what the mode allows.

        A LOCAL lane means a small model is enough, so the cheapest
        capable tier wins. An ESCALATE lane means it is not enough, so
        the user's own big hardware comes first and cloud second — local
        stays in the list only as a last resort, because a mediocre
        answer beats no answer, and the trace says which one happened.
        """
        if lane == "ESCALATE":
            order = (REMOTE, CLOUD, LOCAL)
        elif self.prefer_local:
            order = (LOCAL, REMOTE, CLOUD)
        else:
            # prefer_local off: use the bigger iron even for easy work.
            order = (REMOTE, CLOUD, LOCAL)
        allowed = self.allowed_tiers(mode)
        return tuple(tier for tier in order if tier in allowed)


def sort_candidates(models: list[dict]) -> list[dict]:
    """Deterministic candidate order.

    Model discovery walks dictionaries and network responses, so without
    an explicit sort the "first" candidate can change between restarts
    and a routing decision stops being reproducible. An explicit
    `priority` in provider config wins; ties break on name.
    """
    return sorted(models, key=lambda model: (int(model.get("priority", 100)), str(model.get("name", model.get("id", "")))))
