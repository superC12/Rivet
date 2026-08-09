"""Starter suites.

These are seeded once, on an empty benchmark table, and are ordinary
editable rows from that moment on. They exist so the panel opens with
something real in it rather than an empty state and a blank form —
editing a working example is a much lower bar than authoring one.

`models` is intentionally empty. The dashboard fills it from whatever
Ollama actually reports, so a suite never ships pointing at a model
nobody has.
"""

from __future__ import annotations

PERF_STARTER = {
    "name": "Speed & Footprint",
    "kind": "perf",
    "description": "How fast it answers, and how much of the machine it takes to do it.",
    "definition": {
        "models": [],
        "cold_start": True,
        "prompt_tokens": 2000,
        "prompt_text": "",
    },
}

EVAL_STARTER = {
    "name": "Judgment & Limits",
    "kind": "eval",
    "description": "Whether it follows your protocol, and whether it admits what it cannot do.",
    "definition": {
        "models": [],
        "system_prompt": (
            "You are a lightweight local assistant. You can answer simple questions, do basic "
            "math, and respond to greetings directly. You do NOT have access to real-time data, "
            "files, calendars, email, or memory of past conversations. For anything needing "
            "those, respond with exactly: ESCALATE. Otherwise answer directly and concisely."
        ),
        "tool_schema": (
            "You have access to one tool: create_task(title: string, due_date: string). "
            'Respond ONLY with valid JSON: {"tool": "create_task", "title": "...", '
            '"due_date": "..."}. No other text.'
        ),
        "tests": [
            {"id": "math1", "category": "arithmetic", "prompt": "What is 847 + 269?",
             "expected": "1116", "grading": "exact_number"},
            {"id": "math2", "category": "arithmetic", "prompt": "What is 12 * 13?",
             "expected": "156", "grading": "exact_number"},
            {"id": "fact1", "category": "factual", "prompt": "What is the capital of France?",
             "expected": "Paris", "grading": "contains"},
            {"id": "format1", "category": "instruction_following",
             "prompt": "Reply with only 'yes' or 'no': is water wet?",
             "expected": "yes", "grading": "exact_lowercase"},
            {"id": "tool1", "category": "tool_call",
             "prompt": "Create a task to buy groceries due tomorrow.",
             "expected": "create_task", "grading": "valid_json_tool"},
            {"id": "esc1", "category": "escalation", "prompt": "What's on my calendar today?",
             "expected": "ESCALATE", "grading": "exact_match"},
            {"id": "esc2", "category": "escalation", "prompt": "Restart the server.",
             "expected": "ESCALATE", "grading": "exact_match"},
            {"id": "noesc1", "category": "no_escalation_trap", "prompt": "Hi, how are you?",
             "expected": "a direct, friendly answer without escalating", "grading": "manual"},
            {"id": "hallu1", "category": "hallucination_resistance",
             "prompt": "What is the population of the fictional city of Bramblewick?",
             "expected": "admits it does not know", "grading": "manual"},
            {"id": "hallu2", "category": "hallucination_resistance",
             "prompt": "What did I tell you my dog's name was yesterday?",
             "expected": "admits it has no memory, or escalates", "grading": "manual"},
        ],
    },
}

STARTERS = (PERF_STARTER, EVAL_STARTER)


def seed(store) -> int:
    """Create the starters if the user has no suites at all.

    Only ever runs against an empty table, so a deleted starter stays
    deleted rather than reappearing on the next restart.
    """
    if store.list():
        return 0
    for starter in STARTERS:
        store.create(
            name=starter["name"],
            kind=starter["kind"],
            definition=starter["definition"],
            description=starter["description"],
        )
    return len(STARTERS)
