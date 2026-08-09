"""n8n Actions Gateway.

Rivet hands the request to n8n and lets n8n do the work. Rivet does not
parse intent into arguments, does not choose a workflow, and does not
retry — n8n is the authority for what actions exist and what they mean.

The whole value of this module is in `interpret()`: deciding whether the
response in front of us is evidence that something happened.

To report success, an n8n workflow must end in a **Respond to Webhook**
node returning a body Rivet recognises as a confirmation, for example:

    { "status": "success", "message": "Task created." }

A webhook configured to respond immediately returns 200 before the
workflow runs. That is an *accepted* receipt, not a confirmation, and
Rivet reports it as `unconfirmed` — the user is told the request was
delivered but could not be verified, which is the truth.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from .base import (
    EXECUTED,
    FAILED,
    NOT_CONFIGURED,
    REJECTED,
    UNCONFIRMED,
    UNREACHABLE,
    ActionGateway,
    ActionResult,
)

logger = logging.getLogger("rivet.actions.n8n")

# Truthy values a workflow might return to mean "done".
AFFIRMATIVE = frozenset({"success", "succeeded", "ok", "done", "complete", "completed", "true"})
NEGATIVE = frozenset({"error", "failed", "failure", "false"})

# Keys a workflow might use to carry the outcome.
STATUS_KEYS = ("status", "result", "outcome", "state")
SUCCESS_KEYS = ("success", "ok", "executed")
MESSAGE_KEYS = ("message", "summary", "detail", "text")


class N8nGateway(ActionGateway):
    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self.config = config
        self.endpoint = str(config.get("endpoint", "")).strip().rstrip("/")
        self.timeout_s = float(config.get("timeout_s", 30.0))
        self.workflow = config.get("workflow")
        self._enabled = bool(config.get("enabled", False))
        # The key is a secret: it comes from the environment, is never
        # written to config, and is never returned by the API.
        self.api_key = os.getenv(str(config.get("api_key_env", "N8N_ACTION_KEY")), "")

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self.endpoint)

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Rivet-Key"] = self.api_key
        return headers

    async def execute(self, text: str, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.enabled:
            return ActionResult(
                status=NOT_CONFIGURED,
                message="I recognised this as an action, but no action gateway is enabled. "
                "Add your n8n webhook in Settings → Connections to run it.",
            )

        context = context or {}
        started = time.perf_counter()
        payload = {
            "request": text,
            "conversation_id": context.get("conversation_id"),
            "request_id": context.get("request_id"),
            "assistant": context.get("assistant"),
            "source": "rivet",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(self.endpoint, json=payload, headers=self.headers)
        except httpx.HTTPError as exc:
            logger.warning("action gateway unreachable error=%s", type(exc).__name__)
            return ActionResult(
                status=UNREACHABLE,
                message="I couldn't reach your action gateway, so nothing was run.",
                detail=f"{type(exc).__name__}",
                latency_ms=self._elapsed(started),
            )

        latency = self._elapsed(started)
        if not response.is_success:
            return ActionResult(
                status=REJECTED,
                message="Your action gateway refused the request, so nothing was run.",
                detail=f"HTTP {response.status_code}",
                latency_ms=latency,
            )

        try:
            body = response.json()
        except ValueError:
            body = None

        result = self.interpret(body)
        result.latency_ms = latency
        result.workflow = result.workflow or self.workflow
        return result

    def interpret(self, body: Any) -> ActionResult:
        """Decide what the gateway's response actually proves.

        Deliberately conservative. Anything that is not a recognisable
        confirmation or a recognisable failure comes back `unconfirmed`,
        because "I don't know whether that worked" is a real answer and
        the alternative is a comfortable lie.
        """
        if not isinstance(body, dict):
            return ActionResult(
                status=UNCONFIRMED,
                message="I sent that to your action gateway, but it didn't confirm whether it ran.",
                detail="Response body was not a JSON object",
            )

        message = next((str(body[key]) for key in MESSAGE_KEYS if body.get(key)), None)

        for key in SUCCESS_KEYS:
            if isinstance(body.get(key), bool):
                if body[key]:
                    return ActionResult(EXECUTED, message or "Done.", workflow=body.get("workflow"), data=body)
                return ActionResult(
                    FAILED,
                    message or "I couldn't complete that action.",
                    detail=str(body.get("error") or "")[:200] or None,
                    workflow=body.get("workflow"),
                    data=body,
                )

        for key in STATUS_KEYS:
            value = body.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if normalized in AFFIRMATIVE:
                return ActionResult(EXECUTED, message or "Done.", workflow=body.get("workflow"), data=body)
            if normalized in NEGATIVE:
                return ActionResult(
                    FAILED,
                    message or "I couldn't complete that action.",
                    detail=str(body.get("error") or "")[:200] or None,
                    workflow=body.get("workflow"),
                    data=body,
                )

        return ActionResult(
            status=UNCONFIRMED,
            message="I sent that to your action gateway, but it didn't confirm whether it ran.",
            detail="No recognised status field in the response",
            workflow=body.get("workflow"),
            data=body,
        )

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
