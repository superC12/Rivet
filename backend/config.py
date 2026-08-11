from __future__ import annotations

import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.getenv("RIVET_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.getenv("RIVET_DATA_DIR", ROOT / "data"))

DEFAULT_ASSISTANT: dict[str, Any] = {
    "version": "1.0",
    "platform": {"name": "Rivet"},
    "assistant": {
        "name": "Atlas",
        "tagline": "Local when it can. Powerful when it needs to be.",
        "instructions": "Be concise.\nExplain important technical decisions.\nDo not claim an external action succeeded unless execution confirms it.",
    },
    "interface": {
        "appearance": "system",
        "accent": {"mode": "adaptive", "color": "#e4b45f"},
        # Benchmarks are opt-out rather than opt-in: they are useful on
        # first run, and removing every suite puts the panel away.
        "show_benchmarks": True,
        "motion": {"mode": "dynamic", "intensity": 0.18, "speed": 1.1, "reaction": 0.9},
        "density": "minimal",
    },
}

DEFAULT_RIVET: dict[str, Any] = {
    "router": {
        "strategy": "auto",
        "engine": "builtin",
        "prefer_local": True,
        "fallback": "openrouter-main",
        "privacy_mode": "standard",
        "session_affinity": True,
        # Qualified as provider:model so equal model names on two servers
        # can be enabled independently.
        "disabled_models": [],
        # First entry wins within a routing tier. Entries use the same
        # provider:model identity as disabled_models.
        "model_priority": [],
        # Optional. When empty, Rivet uses only its normal deterministic
        # classifier and selection rules with no extra model call.
        "routing_model": {
            "enabled": False,
            "model": "",
            "thinking_policy": "auto",
        },
        "classifier": {
            # "heuristic" needs nothing installed. "dispatch" asks a model
            # selected by the administrator — Rivet ships no model or recipe.
            "mode": "heuristic",
            "endpoint": "http://127.0.0.1:11434",
            "model": "",
            "timeout_s": 5.0,
            # Unreadable classification fails upward by default.
            "fallback_lane": "ESCALATE",
        },
    },
    "actions": {
        "n8n": {"enabled": False, "endpoint": "", "timeout_s": 30.0},
    },
    "providers": {
        "local-ollama": {
            "type": "ollama",
            "node": "homelab",
            "endpoint": "http://127.0.0.1:11434",
            "auto_detect": True,
            "discovery_endpoints": [
                "http://host.docker.internal:11434",
                "http://ollama:11434",
            ],
        },
        "openrouter-main": {"type": "openrouter", "node": None},
    },
    "nodes": {
        "homelab": {"type": "local", "display_name": "Homelab", "always_on": True}
    },
    "onboarding": {"complete": False},
    "logging": {"verbose": False},
}


def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _drop_blank_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Ignore a blank assistant name or platform name.

    A settings form that posts before it has been populated sends empty
    strings, and merging those wipes the assistant's identity — the user
    sees their assistant lose its name for no reason they can trace.
    Nobody ever means to have a nameless assistant, so a blank name is
    treated as "unchanged". Instructions are left alone: clearing those
    is a legitimate thing to want.
    """
    assistant = payload.get("assistant")
    if not isinstance(assistant, dict) or str(assistant.get("name", "x")).strip():
        return payload
    trimmed = {**payload, "assistant": {k: v for k, v in assistant.items() if k != "name"}}
    return trimmed


def _seed_from_template(path: Path) -> None:
    """Create a live config file from its shipped template, once.

    The templates are tracked; the files beside them are not. Rivet
    rewrites its own config whenever settings are saved, so a tracked
    live file means finishing onboarding on a dev machine silently edits
    the defaults every new installation will receive. Keeping the two
    apart makes that impossible rather than merely unlikely.
    """
    template = path.with_suffix(f"{path.suffix}.example")
    if path.exists() or not template.exists():
        return
    shutil.copyfile(template, path)


def _load(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(defaults)
    with path.open("r", encoding="utf-8") as handle:
        return _merge(defaults, yaml.safe_load(handle) or {})


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    temp.replace(path)


class Settings:
    CONFIG_FILES = ("assistant.yaml", "rivet.yaml")

    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for name in self.CONFIG_FILES:
            _seed_from_template(CONFIG_DIR / name)
        self.reload()

    def reload(self) -> None:
        self.assistant = _load(CONFIG_DIR / "assistant.yaml", DEFAULT_ASSISTANT)
        self.rivet = _load(CONFIG_DIR / "rivet.yaml", DEFAULT_RIVET)

    @property
    def database_path(self) -> Path:
        return Path(os.getenv("RIVET_DATABASE_PATH", DATA_DIR / "rivet.db"))

    def public(self) -> dict[str, Any]:
        return {
            "platform": self.assistant["platform"],
            "assistant": self.assistant["assistant"],
            "interface": self.assistant["interface"],
            "router": self.rivet["router"],
            "actions": self.public_actions(),
            "onboarding": self.rivet.get("onboarding", {"complete": False}),
        }

    def public_actions(self) -> dict[str, Any]:
        """Action config minus the endpoint.

        An n8n webhook URL carries its own authorisation in the path, so
        it is a credential and never leaves the server. Callers only need
        to know whether a gateway exists.
        """
        actions = self.rivet.get("actions", {}) or {}
        return {
            name: {"enabled": bool(config.get("enabled")), "configured": bool(str(config.get("endpoint", "")).strip())}
            for name, config in actions.items()
            if isinstance(config, dict)
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = _drop_blank_identity(payload)
        allowed_assistant = {k: payload[k] for k in ("assistant", "interface") if k in payload}
        allowed_rivet = {k: payload[k] for k in ("router", "onboarding", "providers", "nodes", "actions") if k in payload}
        if allowed_assistant:
            self.assistant = _merge(self.assistant, allowed_assistant)
            _save(CONFIG_DIR / "assistant.yaml", self.assistant)
        if allowed_rivet:
            self.rivet = _merge(self.rivet, allowed_rivet)
            _save(CONFIG_DIR / "rivet.yaml", self.rivet)
        return self.public()

    def remove_manual_provider(self, provider_id: str) -> dict[str, Any] | None:
        provider = self.rivet.get("providers", {}).get(provider_id)
        if not isinstance(provider, dict) or not provider.get("manual"):
            return None

        updated = deepcopy(self.rivet)
        removed = updated.get("providers", {}).pop(provider_id)
        node_id = removed.get("node")
        node_is_unused = node_id and not any(
            candidate.get("node") == node_id
            for candidate in updated.get("providers", {}).values()
            if isinstance(candidate, dict)
        )
        expected_manual_node = node_id == f"{provider_id}-node"
        node_config = updated.get("nodes", {}).get(node_id, {}) if node_id else {}
        if node_is_unused and (expected_manual_node or node_config.get("manual")):
            updated.get("nodes", {}).pop(node_id, None)

        self.rivet = updated
        _save(CONFIG_DIR / "rivet.yaml", self.rivet)
        return self.public()


settings = Settings()
