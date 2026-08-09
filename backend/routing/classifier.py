"""Lane classification.

Classification answers one question — *what kind of request is this* — and
nothing else. Which provider and model serve the lane is the selection
problem, and it lives in `engine.py`.

Two classifiers share one interface:

`HeuristicClassifier` is deterministic pattern matching. It is always
available, costs nothing, and is the floor the system falls back to.

`DispatchClassifier` asks a small local model to judge whether a stronger
model is needed. This is the part worth measuring rather than trusting: a
3B model assessing its own competence is exactly what small models are
worst at, so `eval/run_eval.py` is the gate before it is turned on.

ACTION is never model-decided. A request that reaches the ACTION lane can
cause a real side effect through n8n, so it is gated on deterministic
patterns only. A misfiring classifier should cost a wasted token, not an
email nobody meant to send.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import httpx

LOCAL = "LOCAL"
ESCALATE = "ESCALATE"
ACTION = "ACTION"
LANES = (LOCAL, ESCALATE, ACTION)

# Lanes the dispatch model is allowed to choose between. ACTION is absent
# on purpose; see the module docstring.
DISPATCH_LANES = (LOCAL, ESCALATE)


@dataclass(slots=True)
class Classification:
    lane: str
    reason: str
    source: str
    confident: bool = True
    latency_ms: int = 0
    raw: str | None = None
    error: str | None = None


class HeuristicClassifier:
    """Deterministic classification. Never fails, never calls out."""

    # An action needs an imperative verb *and* an object it acts on. Both
    # halves are required because "send" alone is a word people use while
    # asking questions.
    ACTION_PATTERN = re.compile(
        r"\b(add|create|make|send|schedule|book|remind|set|turn on|turn off|delete|remove|cancel|move)\b"
        r".{0,80}?\b(task|todo|to-do|email|message|meeting|event|invite|appointment|reminder|alarm|"
        r"timer|light|lights|thermostat|scene|list|note|calendar|shopping)\b",
        re.I | re.S,
    )

    # "Remind me to ..." is an instruction in every phrasing anyone
    # actually uses, and its object is open-ended ("take the bins out"),
    # so it gets its own rule rather than an ever-growing noun list.
    IMPERATIVE_PATTERN = re.compile(r"^\s*(remind me to|remind me about)\b", re.I)

    # A question about an action is not an action. "How do I create a
    # task" must never reach the gateway.
    QUESTION_PATTERN = re.compile(
        r"^\s*(how|what|what's|why|when|where|which|who|whose|can|could|should|would|will|is|are|was|"
        r"were|do|does|did|explain|tell me|show me|help me understand)\b",
        re.I,
    )

    # An explicit scope limit outranks the topic. "Explain what a VPN
    # does in two sentences" is a small job about a big subject, and the
    # user already said how much answer they want.
    BOUNDED_PATTERN = re.compile(
        r"\b(in (one|two|three|a few) sentences?|in a sentence|briefly|one line|short answer|tl;?dr|"
        r"in bullet points?)\b",
        re.I,
    )

    # --- signals that a small model will handle a request badly -------

    HEAVY_PATTERN = re.compile(
        r"\b(analy[sz]e|architecture|refactor|repositor(y|ies)|codebase|derive|prove|proof|benchmark|"
        r"optimi[sz]e|migrat(e|ion)|legal|contract|liabilit(y|ies)|medical|diagnos(e|is)|financial|"
        r"comprehensive|multi-step|trade-?offs?|quanti[sz]|schema)\b",
        re.I,
    )

    # Debugging is the single most common thing a 3B model gets
    # confidently wrong, because a plausible-sounding cause is worthless.
    TROUBLESHOOTING_PATTERN = re.compile(
        r"\bwhy (is|does|do|would|won'?t|doesn'?t|isn'?t|aren'?t|are|am|did|can'?t|cannot)\b"
        r"|\bwhat'?s going on\b|\bnot working\b|\bfail(s|ing|ed|ure)?\b|\bstuck\b|\bcrash(es|ing|ed)?\b"
        r"|\bexit(s|ed|ing)?\b.{0,24}\bcode\b|\btimes? out\b|\btimed out\b|\bsilently\b|\bhangs?\b",
        re.I,
    )

    CODE_PATTERN = re.compile(
        r"\b(write|implement|create|build|generate|fix|debug|refactor|rewrite)\b.{0,40}?"
        r"\b(function|class|script|query|regex|endpoint|api|component|module|tests?|parser|algorithm|"
        r"code|snippet|migration)\b"
        r"|\b(python|javascript|typescript|golang|sql|bash|dockerfile)\b.{0,40}?"
        r"\b(function|script|code|error|snippet|class)\b",
        re.I,
    )

    # Infrastructure questions carry version- and configuration-specific
    # detail that a small model tends to invent.
    INFRA_PATTERN = re.compile(
        r"\b(self-hosted|reverse proxy|webhook|docker|container|kubernetes|nginx|tailscale|"
        r"mutual tls|mtls|firewall|port forward(ing)?|load balancer|systemd)\b",
        re.I,
    )

    PROCEDURE_PATTERN = re.compile(
        r"\bwalk me through\b|\bstep by step\b|\bhow (do|can|would) I\b"
        r"|\bset(ting)? up\b.{0,40}?\b(tls|ssl|proxy|vpn|cluster|server|pipeline|ci|certificate)\b",
        re.I,
    )

    PLANNING_PATTERN = re.compile(
        r"\bwork out (a|an|the)\b|\bminimi[sz]e\b|\border that\b|\bwhich (order|approach)\b"
        r"|\bplan\b.{0,30}?\bdependenc",
        re.I,
    )

    HEALTH_PATTERN = re.compile(
        r"\b(hurts?|hurting|pain(ful)?|tingling|numb|swollen|dizzy|fever|rash|symptoms?|"
        r"bleeding|lump)\b",
        re.I,
    )

    # "Compare X and Y" needs stated assumptions to be useful. Note that
    # "the difference between X and Y" deliberately does not match — that
    # is a definition question, and a small model answers it fine.
    COMPARISON_PATTERN = re.compile(
        r"\b(cheaper|costlier|faster|slower|better|worse|safer|riskier)\b.{0,60}?\b(or|than|vs\.?|versus)\b"
        r"|\bcompare\b.{0,60}?\b(and|or|vs\.?|versus|against)\b",
        re.I,
    )

    MONEY_MATH_PATTERN = re.compile(
        r"\b\d+\s*(percent|%)\b.{0,60}?\b(year|month|annum)|compound|interest rate|index fund|"
        r"\bmortgage\b|\bamorti[sz]",
        re.I,
    )

    ESCALATION_SIGNALS = (
        ("HEAVY_PATTERN", "Subject matter a small model handles badly"),
        ("TROUBLESHOOTING_PATTERN", "Diagnostic request; a plausible wrong answer is worse than none"),
        ("CODE_PATTERN", "Writing or fixing real code"),
        ("INFRA_PATTERN", "Infrastructure specifics are easy to invent"),
        ("PROCEDURE_PATTERN", "Multi-step procedure with dependencies"),
        ("PLANNING_PATTERN", "Planning with competing constraints"),
        ("HEALTH_PATTERN", "Health question; being subtly wrong matters"),
        ("COMPARISON_PATTERN", "Comparison needing stated assumptions"),
        ("MONEY_MATH_PATTERN", "Multi-step financial arithmetic"),
    )

    SIMPLE_PATTERN = re.compile(
        r"^\s*(what is|what's|who is|who wrote|define|spell|rewrite|rephrase|summari[sz]e|translate|"
        r"convert|calculate|how many|how much|how do you spell|hello|hi\b|hey\b|thanks)",
        re.I,
    )

    # Long input is a proxy for a document the small model will handle
    # badly, independent of how the request is phrased.
    LONG_INPUT_CHARS = 1800

    def is_action(self, text: str) -> bool:
        if self.QUESTION_PATTERN.search(text):
            return False
        if self.IMPERATIVE_PATTERN.search(text):
            return True
        return bool(self.ACTION_PATTERN.search(text))

    def classify(self, text: str) -> Classification:
        started = time.perf_counter()
        if self.is_action(text):
            return self._result(ACTION, "Action verb and target detected", started)
        if len(text) > self.LONG_INPUT_CHARS:
            return self._result(ESCALATE, "Input is long enough to need a larger context", started)
        # An explicit scope limit is the user telling us how big the
        # answer needs to be, which beats guessing from the topic.
        if not self.BOUNDED_PATTERN.search(text):
            for attribute, reason in self.ESCALATION_SIGNALS:
                if getattr(self, attribute).search(text):
                    return self._result(ESCALATE, reason, started)
        if self.SIMPLE_PATTERN.search(text):
            return self._result(LOCAL, "Short, well-defined request", started)
        return self._result(LOCAL, "No signal that a larger model is needed", started)

    def _result(self, lane: str, reason: str, started: float) -> Classification:
        return Classification(
            lane=lane,
            reason=reason,
            source="heuristic",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )


SYSTEM_PROMPT = """You are a request classifier. You do not answer questions.
You emit exactly one word and then stop.

LOCAL - a small 3B model can answer this well. Everyday questions, short
explanations, rewriting, summarising text the user supplied, simple factual
recall, chit-chat, formatting, quick definitions.

ESCALATE - this needs a stronger model. Multi-step reasoning, non-trivial
maths, writing or debugging real code, long-document analysis, specialist
professional knowledge (legal, medical, financial), anything asking for
careful comparison or a plan with dependencies, anything where being subtly
wrong would matter.

If you are unsure whether a 3B model would get it right, answer ESCALATE.

Reply with one word: LOCAL or ESCALATE."""

FEW_SHOT = (
    ("what's the capital of Norway", LOCAL),
    ("rewrite this sentence to be shorter: the meeting has been moved", LOCAL),
    ("why is my kubernetes pod stuck in CrashLoopBackOff", ESCALATE),
    ("what time zone is Denver in", LOCAL),
    ("derive the closed form for this recurrence and prove it by induction", ESCALATE),
    ("give me a name for a golden retriever", LOCAL),
)

# The classifier reads the request to label it, so a long request costs
# dispatch latency for no extra signal. The opening is where the intent is.
MAX_CLASSIFIED_CHARS = 1200


def build_prompt(text: str) -> str:
    examples = [f"Request: {example}\nLabel: {label}" for example, label in FEW_SHOT]
    examples.append(f"Request: {text[:MAX_CLASSIFIED_CHARS]}\nLabel:")
    return "\n\n".join(examples)


def normalise(raw: str) -> str | None:
    """Pull a known lane out of whatever the model actually said.

    A 3B model will occasionally return 'Label: LOCAL', 'local.', or a
    whole sentence. Match on the lane token rather than demanding exact
    output. If more than one lane appears the answer is ambiguous, and an
    ambiguous answer becomes a flagged fallback rather than a coin flip.
    """
    upper = raw.strip().upper()
    hits = [lane for lane in DISPATCH_LANES if lane in upper]
    return hits[0] if len(hits) == 1 else None


class DispatchClassifier:
    """Asks a small local model for a LOCAL/ESCALATE label.

    Never raises. A classifier that can take the whole request down with
    it is worse than no classifier, so every failure path returns a
    Classification with `confident=False` and the reason in `error`.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        timeout_s: float = 5.0,
        max_tokens: int = 8,
        fallback_lane: str = ESCALATE,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.fallback_lane = fallback_lane

    async def classify(self, text: str) -> Classification:
        started = time.perf_counter()
        if not self.model.strip():
            return Classification(
                lane=self.fallback_lane,
                reason="Dispatcher is not configured",
                source="dispatch",
                confident=False,
                latency_ms=0,
                error="Select a classifier model before enabling dispatch mode.",
            )
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt(text),
            "stream": False,
            "options": {"temperature": 0, "num_predict": self.max_tokens, "stop": ["\n", "Request:"]},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.endpoint}/api/generate", json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "")
        except Exception as exc:  # noqa: BLE001 - every failure lands in the fallback
            return Classification(
                lane=self.fallback_lane,
                reason="Dispatcher unavailable",
                source="dispatch",
                confident=False,
                latency_ms=self._elapsed(started),
                error=f"{type(exc).__name__}: {exc}",
            )

        lane = normalise(raw)
        return Classification(
            lane=lane or self.fallback_lane,
            reason="Dispatcher label" if lane else "Dispatcher label was unreadable",
            source="dispatch",
            confident=lane is not None,
            latency_ms=self._elapsed(started),
            raw=raw.strip(),
            error=None if lane else "unparseable label",
        )

    async def health(self, use_cache: bool = True) -> dict:
        """Probe the dispatcher for real, not just this process.

        Distinguishes the two failures that look identical from inside a
        request: the configured service being unreachable, and the model
        selected by the administrator not being installed there.

        Cached briefly: the dashboard polls status on a timer, and a
        classifier that is fine now is still fine a few seconds later.
        """
        key = f"{self.endpoint}|{self.model}"
        if use_cache:
            cached = _health_cache.get(key)
            if cached is not None:
                return cached
        result = await self._probe()
        _health_cache.set(key, result)
        return result

    async def _probe(self) -> dict:
        if not self.model.strip():
            return {
                "status": "unconfigured",
                "endpoint": self.endpoint,
                "model": "",
                "model_installed": False,
                "latency_ms": 0,
                "error": "Select a classifier model before enabling dispatch mode.",
            }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.get(f"{self.endpoint}/api/tags")
                response.raise_for_status()
                tags = [item.get("name", "") for item in response.json().get("models", [])]
        except Exception as exc:  # noqa: BLE001 - health never raises
            return {
                "status": "unreachable",
                "endpoint": self.endpoint,
                "model": self.model,
                "model_installed": False,
                "latency_ms": self._elapsed(started),
                "error": f"{type(exc).__name__}: {exc}",
            }

        installed = any(_tag_matches(self.model, tag) for tag in tags)
        return {
            "status": "ok" if installed else "model_missing",
            "endpoint": self.endpoint,
            "model": self.model,
            "model_installed": installed,
            "latency_ms": self._elapsed(started),
            "error": None if installed else f"The configured classifier model '{self.model}' is not installed.",
        }

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)


CLASSIFIER_HEALTH_TTL_S = 60.0


class _HealthCache:
    """Tiny TTL memo for dispatcher probes.

    Module-level because a `Classifier` is built per request; instance
    state would never survive to be reused.
    """

    # The dashboard refreshes every 45 seconds. Keep a successful or failed
    # dispatcher probe alive beyond that boundary so each refresh does not
    # immediately repeat a potentially blocking network timeout.
    TTL_S = CLASSIFIER_HEALTH_TTL_S

    def __init__(self) -> None:
        self._entries: dict[str, tuple[dict, float]] = {}

    def get(self, key: str) -> dict | None:
        entry = self._entries.get(key)
        if not entry or time.monotonic() >= entry[1]:
            self._entries.pop(key, None)
            return None
        return entry[0]

    def set(self, key: str, value: dict) -> None:
        self._entries[key] = (value, time.monotonic() + self.TTL_S)

    def invalidate(self) -> None:
        self._entries.clear()


_health_cache = _HealthCache()


def _tag_matches(configured: str, available: str) -> bool:
    """Does an Ollama tag satisfy the configured model name?

    Ollama reports `name:latest` for a model created without an explicit
    tag, so an exact string compare would report a correctly installed
    dispatcher as missing.
    """
    if ":" in configured:
        return available == configured
    return available == configured or available.startswith(f"{configured}:")


def _env_first(*names: str) -> str | None:
    """First environment variable that is set and non-empty."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


class Classifier:
    """The facade the request path uses.

    Order is fixed and deliberate:

    1. Deterministic ACTION check. Side effects are never model-decided.
    2. The dispatch model, when configured, for LOCAL vs ESCALATE.
    3. The heuristic, as the answer when dispatch is off.

    When dispatch fails or returns something unreadable, the lane fails
    *upward* to `fallback_lane` (ESCALATE by default) rather than quietly
    landing on the cheap option. An unclassified request handled by a 3B
    model is a confidently wrong answer; the same request handled by a
    stronger model is a slightly larger bill.

    `privacy_mode: local_only` still clamps the result during selection,
    so failing upward can never leak content to a cloud provider the user
    has disabled. Deployments that would rather absorb the occasional bad
    answer than the spend can set `fallback_lane: LOCAL`.

    Every fallback is visible in `source`, `confident` and `error`. It is
    never silent.
    """

    # Environment overrides the config file. The dispatcher usually runs
    # on the always-on server rather than wherever Rivet's YAML was last
    # edited, and a deployment should be able to point it somewhere else
    # without hand-editing config. `RIVET_`-prefixed names win; the
    # unprefixed ones are the conventional spellings.
    ENV_MODE = ("RIVET_CLASSIFIER_MODE", "CLASSIFIER_MODE")
    ENV_ENDPOINT = ("RIVET_DISPATCH_ENDPOINT", "OLLAMA_URL")
    ENV_MODEL = ("RIVET_DISPATCH_MODEL", "DISPATCH_MODEL")
    ENV_TIMEOUT = ("RIVET_DISPATCH_TIMEOUT_S", "DISPATCH_TIMEOUT_S")
    ENV_FALLBACK = ("RIVET_FALLBACK_LANE", "FALLBACK_LANE")

    DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
    DEFAULT_MODEL = ""
    DEFAULT_TIMEOUT_S = 5.0

    def __init__(self, config: dict | None = None, *, honor_environment: bool = True) -> None:
        config = config or {}

        def configured(env_names: tuple[str, ...], key: str, default):
            override = _env_first(*env_names) if honor_environment else None
            return override or config.get(key, default)

        self.heuristic = HeuristicClassifier()
        self.mode = str(configured(self.ENV_MODE, "mode", "heuristic")).lower()

        fallback = str(configured(self.ENV_FALLBACK, "fallback_lane", ESCALATE)).upper()
        self.fallback_lane = fallback if fallback in DISPATCH_LANES else ESCALATE

        self.endpoint = str(configured(self.ENV_ENDPOINT, "endpoint", self.DEFAULT_ENDPOINT))
        self.model = str(configured(self.ENV_MODEL, "model", self.DEFAULT_MODEL))
        try:
            self.timeout_s = float(configured(self.ENV_TIMEOUT, "timeout_s", self.DEFAULT_TIMEOUT_S))
        except (TypeError, ValueError):
            # A malformed timeout must not stop Rivet from starting.
            self.timeout_s = self.DEFAULT_TIMEOUT_S

        self.dispatch: DispatchClassifier | None = None
        if self.mode == "dispatch":
            self.dispatch = DispatchClassifier(
                endpoint=self.endpoint,
                model=self.model,
                timeout_s=self.timeout_s,
                fallback_lane=self.fallback_lane,
            )

    async def classify(self, text: str) -> Classification:
        if self.heuristic.is_action(text):
            return self.heuristic.classify(text)
        if not self.dispatch:
            return self.heuristic.classify(text)
        return await self.dispatch.classify(text)

    def describe(self) -> dict:
        """What this classifier is, without probing anything."""
        return {
            "mode": self.mode,
            "lanes": list(LANES),
            "fallback_lane": self.fallback_lane,
            "model": self.model if self.dispatch else None,
            "endpoint": self.endpoint if self.dispatch else None,
            "timeout_s": self.timeout_s if self.dispatch else None,
        }

    async def health(self, use_cache: bool = True) -> dict:
        """Is classification actually working?

        The heuristic runs in-process with no dependencies, so it is
        healthy by construction. Only the dispatch mode can be broken in
        a way the user cannot see from the outside.
        """
        if not self.dispatch:
            return {**self.describe(), "status": "ok", "model_installed": None, "latency_ms": 0, "error": None}
        return {**self.describe(), **await self.dispatch.health(use_cache=use_cache)}
