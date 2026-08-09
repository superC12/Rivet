"""Grading a model's answer.

Pure functions: text in, verdict out. No network, no model, no state —
which is what makes them the one part of a benchmark you can actually
trust, because they can be tested exhaustively in milliseconds.

A grader returns `True`, `False`, or `None`. `None` means "a human has to
look at this", and it is a first-class answer rather than a failure.
Questions like "did it admit it does not know?" have no honest automatic
answer, and pretending otherwise would quietly convert judgement calls
into a score nobody should trust.
"""

from __future__ import annotations

import json
import re
from typing import Callable

MANUAL = None

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def exact_number(response: str, expected: str) -> bool:
    """Is the expected number among the numbers in the answer?

    Thousands separators are stripped and trailing sentence punctuation
    is ignored, so "1,116." grades the same as "1116". A model that gets
    the arithmetic right and the formatting chatty is still right.
    """
    cleaned = response.replace(",", "")
    found = NUMBER_PATTERN.findall(cleaned)
    target = expected.strip().replace(",", "")
    if target in found:
        return True
    # Compare numerically as well, so "156.0" satisfies "156".
    try:
        wanted = float(target)
    except ValueError:
        return False
    for candidate in found:
        try:
            if float(candidate) == wanted:
                return True
        except ValueError:
            continue
    return False


def contains(response: str, expected: str) -> bool:
    return expected.strip().lower() in response.lower()


def exact_lowercase(response: str, expected: str) -> bool:
    """Did the answer *start* with the required word?

    Used for "reply with only yes or no" style instructions, where a
    model that answers correctly and then explains itself has still
    followed the instruction more than one that leads with prose.
    """
    return response.strip().lower().lstrip("*_ ").startswith(expected.strip().lower())


def exact_match(response: str, expected: str) -> bool:
    return response.strip().strip(".!").upper() == expected.strip().upper()


def valid_json_tool(response: str, expected: str) -> bool:
    """Did the model emit a usable tool call?

    `expected` names the required tool. Models habitually wrap JSON in
    prose or a code fence, so the object is extracted rather than
    demanded — but the parse itself must succeed, because a tool call
    that does not parse is not a tool call.
    """
    match = JSON_OBJECT_PATTERN.search(response)
    if not match:
        return False
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    wanted = (expected or "").strip()
    if wanted and parsed.get("tool") != wanted:
        return False
    return bool(parsed.get("tool"))


def manual(response: str, expected: str) -> None:
    return MANUAL


GRADERS: dict[str, Callable[[str, str], bool | None]] = {
    "exact_number": exact_number,
    "contains": contains,
    "exact_lowercase": exact_lowercase,
    "exact_match": exact_match,
    "valid_json_tool": valid_json_tool,
    "manual": manual,
}

GRADER_NAMES = tuple(GRADERS)


def grade(grading: str, response: str, expected: str) -> bool | None:
    """Apply a named grader. An unknown name asks for a human."""
    grader = GRADERS.get((grading or "").strip())
    if grader is None:
        return MANUAL
    return grader(response, expected or "")


def status_of(verdict: bool | None) -> str:
    if verdict is True:
        return "pass"
    if verdict is False:
        return "fail"
    return "review"
