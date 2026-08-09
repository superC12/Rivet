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

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)


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

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self.heuristic = HeuristicClassifier()
        self.mode = str(config.get("mode", "heuristic")).lower()
        self.fallback_lane = str(config.get("fallback_lane", ESCALATE)).upper()
        if self.fallback_lane not in DISPATCH_LANES:
            self.fallback_lane = ESCALATE
        self.dispatch: DispatchClassifier | None = None
        if self.mode == "dispatch":
            self.dispatch = DispatchClassifier(
                endpoint=config.get("endpoint", "http://127.0.0.1:11434"),
                model=config.get("model", "administrator-selected-classifier"),
                timeout_s=float(config.get("timeout_s", 5.0)),
                fallback_lane=self.fallback_lane,
            )

    async def classify(self, text: str) -> Classification:
        if self.heuristic.is_action(text):
            return self.heuristic.classify(text)
        if not self.dispatch:
            return self.heuristic.classify(text)
        return await self.dispatch.classify(text)
