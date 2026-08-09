"""Measure the classifier.

An endpoint that returns a label is not evidence that the label is right.
This is the gate: run it before trusting a routing change, and keep
`cases.jsonl` as the regression test for every prompt edit.

    python eval/run_eval.py                 # the built-in heuristic
    python eval/run_eval.py --mode dispatch # the small local model

Four numbers, in the order they should be read:

  ACTION precision - of the requests we would have sent to n8n, how many
    were really instructions? This is first because it is the only metric
    whose failure has a side effect in the world. A false ACTION is an
    email nobody meant to send.

  ACTION recall - of the real instructions, how many did we catch? A miss
    here is merely annoying: the user gets an answer instead of an action.

  ESCALATE recall - of the things that genuinely needed a stronger model,
    how many did we catch? A miss is a confidently bad answer.

  LOCAL precision - of the things we kept local, how many belonged there?
    This is the cost side: the OpenRouter bill.

A warning about the score you are about to read: the heuristic patterns
were tuned against these exact cases, so its 100% is a statement that the
suite passes, not evidence of 100% accuracy on your traffic. The real job
of this file is regression detection — when you change a pattern or a
prompt, it tells you what you broke. Add cases from your own use,
especially ones Rivet got wrong, and the number becomes worth something.
`--mode dispatch` is the honest comparison: that model has never seen
these cases.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.routing.classifier import ACTION, ESCALATE, LOCAL, Classifier  # noqa: E402

CASES_PATH = pathlib.Path(__file__).parent / "cases.jsonl"


def load_cases() -> list[dict]:
    cases = []
    with CASES_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def ratio(numerator: int, denominator: int) -> float | None:
    """None when the metric is undefined, so it is never read as zero."""
    return numerator / denominator if denominator else None


def rate(numerator: int, denominator: int) -> str:
    value = ratio(numerator, denominator)
    return f"{value:.1%}" if value is not None else "  n/a"


# Floors, not targets. The bundled cases currently score 100% across the
# board; these exist to catch a slide, and are deliberately loose enough
# that adding a genuinely hard new case does not break the build on its
# own. Tighten them per deployment with the --min-* flags.
DEFAULT_THRESHOLDS = {
    "accuracy": 0.90,
    # A false gateway fire has a side effect in the world, so this one
    # has no slack at all.
    "action-precision": 1.00,
    "action-recall": 0.90,
    "escalate-recall": 0.90,
    "local-precision": 0.85,
}


async def run(mode: str, endpoint: str, model: str, thresholds: dict[str, float]) -> int:
    cases = load_cases()
    # CLI arguments are the most explicit configuration in an eval run. Do
    # not let deployment environment variables silently redirect the test to
    # another dispatcher or model.
    classifier = Classifier(
        {"mode": mode, "endpoint": endpoint, "model": model},
        honor_environment=False,
    )

    print(f"mode:   {mode}")
    if mode == "dispatch":
        print(f"model:  {model}")
        print(f"ollama: {endpoint}")
    print(f"cases:  {len(cases)}\n")

    results = []
    for index, case in enumerate(cases, 1):
        outcome = await classifier.classify(case["text"])
        hit = outcome.lane == case["label"]
        results.append((case, outcome, hit))
        mark = "ok  " if hit else "MISS"
        flag = "" if outcome.confident else "  [fallback]"
        print(f"{mark} {index:>2}/{len(cases)}  {outcome.lane:<9}{outcome.latency_ms:>5}ms{flag}")

    print()
    hits = sum(1 for _, _, hit in results if hit)

    def count(expected: str | None, predicted: str | None) -> int:
        return sum(
            1
            for case, outcome, _ in results
            if (expected is None or case["label"] == expected) and (predicted is None or outcome.lane == predicted)
        )

    action_tp = count(ACTION, ACTION)
    action_predicted = count(None, ACTION)
    action_actual = count(ACTION, None)

    escalate_tp = count(ESCALATE, ESCALATE)
    escalate_actual = count(ESCALATE, None)

    local_tp = count(LOCAL, LOCAL)
    local_predicted = count(None, LOCAL)

    latencies = sorted(outcome.latency_ms for _, outcome, _ in results)
    fallbacks = sum(1 for _, outcome, _ in results if not outcome.confident)

    # A question about an action that we would have executed is the worst
    # failure the classifier can produce, so it gets counted by name.
    fired_on_a_question = [
        case["text"] for case, outcome, _ in results if outcome.lane == ACTION and case["label"] != ACTION
    ]

    print(f"accuracy          {rate(hits, len(results))}  ({hits}/{len(results)})")
    print(f"ACTION precision  {rate(action_tp, action_predicted)}  "
          f"({action_predicted - action_tp} would have fired the gateway wrongly)")
    print(f"ACTION recall     {rate(action_tp, action_actual)}  "
          f"({action_actual - action_tp} instructions answered instead of run)")
    print(f"ESCALATE recall   {rate(escalate_tp, escalate_actual)}  "
          f"({escalate_actual - escalate_tp} needed a stronger model and did not get one)")
    print(f"LOCAL precision   {rate(local_tp, local_predicted)}  "
          f"({local_predicted - local_tp} kept local that should not have been)")
    print(f"fallbacks         {fallbacks}  (unparseable or dispatcher unreachable)")
    if latencies:
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(f"latency           p50 {statistics.median(latencies):.0f}ms   p95 {p95}ms   max {latencies[-1]}ms")

    misses = [(case, outcome) for case, outcome, hit in results if not hit]
    if misses:
        print("\nmisses:")
        for case, outcome in misses:
            note = f"  ({case['note']})" if case.get("note") else ""
            print(f"  expected {case['label']:<9} got {outcome.lane:<9} {case['text'][:60]!r}{note}")
            if outcome.raw and outcome.raw != outcome.lane:
                print(f"      raw: {outcome.raw!r}")

    if fired_on_a_question:
        print("\nWOULD HAVE FIRED THE GATEWAY ON A NON-ACTION:")
        for text in fired_on_a_question:
            print(f"  {text!r}")

    # Every metric is gated, not just the catastrophic ones. A quiet drop
    # in ESCALATE recall is a real regression — it just fails as worse
    # answers rather than as an incident — and a gate that only trips on
    # disasters lets that kind of rot through unnoticed.
    measured = {
        "accuracy": ratio(hits, len(results)),
        "action-precision": ratio(action_tp, action_predicted),
        "action-recall": ratio(action_tp, action_actual),
        "escalate-recall": ratio(escalate_tp, escalate_actual),
        "local-precision": ratio(local_tp, local_predicted),
    }
    breaches = [
        (name, value, thresholds[name])
        for name, value in measured.items()
        # An undefined metric (no cases of that class) cannot breach.
        if value is not None and value + 1e-9 < thresholds[name]
    ]

    if breaches:
        print("\nBELOW THRESHOLD:")
        for name, value, minimum in breaches:
            print(f"  {name:<17} {value:.1%} < {minimum:.1%}")
    if fallbacks:
        print(f"\n{fallbacks} classification(s) fell back to the default lane.")

    failed = bool(breaches or fired_on_a_question or fallbacks)
    print(f"\n{'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Rivet's request classifier.")
    parser.add_argument("--mode", default="heuristic", choices=("heuristic", "dispatch"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="administrator-selected-classifier")
    for name, default in DEFAULT_THRESHOLDS.items():
        parser.add_argument(
            f"--min-{name}",
            type=float,
            default=default,
            metavar="RATIO",
            help=f"minimum {name.replace('-', ' ')} (default {default:.2f})",
        )
    args = parser.parse_args()
    thresholds = {name: getattr(args, f"min_{name.replace('-', '_')}") for name in DEFAULT_THRESHOLDS}
    return asyncio.run(run(args.mode, args.endpoint, args.model, thresholds))


if __name__ == "__main__":
    raise SystemExit(main())
