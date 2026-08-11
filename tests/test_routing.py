import asyncio
import json

from backend.routing import Classification, HeuristicClassifier, RoutingEngine, heuristic_decision
from backend.routing.policies import RoutingPolicy, tier_of

NODES = {
    "homelab": {"type": "local", "always_on": True},
    "gaming-pc": {"type": "tailscale", "always_on": False},
}

MODELS = [
    {"id": "small", "name": "Small", "provider": "local", "node": "homelab"},
    {"id": "big", "name": "Big", "provider": "desktop", "node": "gaming-pc"},
    {"id": "cloud", "name": "Cloud", "provider": "openrouter-main", "node": None},
]

LOCAL_ONLY_MODELS = [MODELS[0], MODELS[2]]


def config(**router):
    return {"router": router, "nodes": NODES}


def decide(text, models=MODELS, **kwargs):
    router = kwargs.pop("router", {})
    return heuristic_decision({"router": router, "nodes": NODES}, models, text, **kwargs)


# --- classification -------------------------------------------------


def test_simple_prompt_classifies_local():
    assert HeuristicClassifier().classify("What is 18% of 275?").lane == "LOCAL"


def test_complex_prompt_classifies_escalate():
    result = HeuristicClassifier().classify("Analyze this large repository for architecture problems")
    assert result.lane == "ESCALATE"


def test_long_input_escalates_regardless_of_wording():
    result = HeuristicClassifier().classify("hello " * 400)
    assert result.lane == "ESCALATE"


def test_action_is_detected():
    assert HeuristicClassifier().classify("Create a task called Buy milk").lane == "ACTION"


def test_question_about_an_action_is_not_an_action():
    # The difference between asking and instructing is the difference
    # between an answer and a side effect.
    for text in ("How do I create a task in n8n?", "What happens if I delete an event?"):
        assert HeuristicClassifier().classify(text).lane != "ACTION", text


# --- selection ------------------------------------------------------


def test_tier_uses_node_type_not_node_name():
    assert tier_of(MODELS[0], NODES) == "LOCAL"
    assert tier_of(MODELS[1], NODES) == "REMOTE"
    assert tier_of(MODELS[2], NODES) == "CLOUD"


def test_simple_prompt_stays_local():
    decision = decide("What is 18% of 275?")
    assert decision.route == "LOCAL"
    assert decision.provider == "local"


def test_complex_prompt_prefers_owned_hardware_over_cloud():
    decision = decide("Analyze this large repository for architecture problems")
    assert decision.route == "REMOTE"
    assert decision.provider == "desktop"


def test_complex_prompt_falls_to_cloud_without_a_remote_node():
    decision = decide("Analyze this large repository for architecture problems", LOCAL_ONLY_MODELS)
    assert decision.route == "CLOUD"


def test_privacy_mode_blocks_cloud_but_allows_owned_remote():
    decision = decide(
        "Analyze this large repository for architecture problems",
        router={"privacy_mode": "local_only"},
    )
    assert decision.route == "REMOTE"


def test_privacy_mode_falls_back_to_local_when_no_remote_exists():
    decision = decide(
        "Analyze this large repository for architecture problems",
        LOCAL_ONLY_MODELS,
        router={"privacy_mode": "local_only"},
    )
    assert decision.route == "LOCAL"


def test_local_only_mode_pins_to_the_local_machine():
    decision = decide("Analyze this large repository", mode="local_only")
    assert decision.route == "LOCAL"


def test_cloud_mode_is_refused_under_local_only_privacy():
    decision = decide("Anything at all", mode="cloud", router={"privacy_mode": "local_only"})
    assert decision.route == "ERROR"
    assert "privacy" in decision.reason.lower()


def test_prefer_local_off_reaches_for_bigger_hardware():
    decision = decide("What is 18% of 275?", router={"prefer_local": False})
    assert decision.route == "REMOTE"


def test_model_override_wins():
    decision = decide("What is 18% of 275?", model_override="big")
    assert decision.route == "REMOTE"
    assert decision.model == "big"
    assert decision.confidence == 1.0


def test_model_override_cannot_escape_privacy_mode():
    decision = decide("Anything", model_override="cloud", router={"privacy_mode": "local_only"})
    assert decision.route == "ERROR"


def test_unknown_model_override_is_an_error_not_a_silent_reroute():
    decision = decide("Anything", model_override="does-not-exist")
    assert decision.route == "ERROR"


def test_no_models_available_is_an_error():
    decision = decide("Anything", [])
    assert decision.route == "ERROR"


def test_disabled_models_are_removed_from_automatic_and_manual_routing():
    routing_config = {"router": {"disabled_models": ["local:small"]}, "nodes": NODES}
    engine = RoutingEngine(routing_config, MODELS)

    automatic = engine.select(Classification(lane="LOCAL", reason="simple", source="test"))
    manual = engine.select(Classification(lane="LOCAL", reason="simple", source="test"), model_override="small")

    assert automatic.model != "small"
    assert manual.route == "ERROR"


def test_saved_model_priority_wins_within_the_same_routing_tier():
    models = [
        MODELS[0],
        {"id": "preferred", "name": "Preferred", "provider": "local", "node": "homelab"},
    ]
    routing_config = {
        "router": {"model_priority": ["local:preferred", "local:small"]},
        "nodes": NODES,
    }

    decision = RoutingEngine(routing_config, models).select(
        Classification(lane="LOCAL", reason="simple", source="test")
    )

    assert decision.model == "preferred"


# --- optional model-assisted Auto Route ----------------------------


def assisted_config(model="local:small", **routing_model):
    return {
        "router": {
            "model_priority": ["local:small", "desktop:big", "openrouter-main:cloud"],
            "routing_model": {
                "enabled": True,
                "model": model,
                "thinking_policy": "auto",
                **routing_model,
            },
        },
        "nodes": NODES,
    }


def test_auto_route_uses_builtin_rules_when_no_routing_model_is_selected():
    calls = []

    async def ask(*args):
        calls.append(args)
        return "{}"

    engine = RoutingEngine(config(), MODELS, model_router_ask=ask)
    decision = asyncio.run(engine.decide("What is 18% of 275?"))

    assert decision.model == "small"
    assert calls == []


def test_assisted_auto_route_selects_only_an_eligible_model_and_thinking_mode():
    seen = {}

    async def ask(model, messages):
        seen["router"] = model["id"]
        seen["system"] = messages[0]["content"]
        return json.dumps({"model": "desktop:big", "thinking": True, "reason": "Worth deeper reasoning"})

    thinking_models = [
        {**model, "capabilities": ["chat", "thinking"]} if model["id"] == "big" else model
        for model in MODELS
    ]
    engine = RoutingEngine(assisted_config(), thinking_models, model_router_ask=ask)
    decision = asyncio.run(engine.decide("Compare three possible architectures and identify failure modes."))

    assert seen["router"] == "small"
    assert '"priority":1' in seen["system"]
    assert decision.provider == "desktop"
    assert decision.model == "big"
    assert decision.thinking is True
    assert any("Model router" in step["message"] for step in decision.trace)


def test_assisted_auto_route_falls_back_if_it_returns_a_disabled_model():
    async def ask(_model, _messages):
        return json.dumps({"model": "desktop:big", "thinking": True, "reason": "Use disabled model"})

    cfg = assisted_config()
    cfg["router"]["disabled_models"] = ["desktop:big"]
    engine = RoutingEngine(cfg, MODELS, model_router_ask=ask)
    decision = asyncio.run(engine.decide("What is 18% of 275?"))

    assert decision.model == "small"
    assert any("invalid decision" in step["message"] for step in decision.trace)


def test_local_only_mode_never_sends_the_prompt_to_a_cloud_routing_model():
    calls = []

    async def ask(*args):
        calls.append(args)
        return "{}"

    engine = RoutingEngine(assisted_config(model="openrouter-main:cloud"), MODELS, model_router_ask=ask)
    decision = asyncio.run(engine.decide("Keep this private", mode="local_only"))

    assert decision.route == "LOCAL"
    assert calls == []
    assert any("privacy or route mode blocks" in step["message"] for step in decision.trace)


def test_thinking_policy_can_hard_disable_an_advisors_request():
    async def ask(_model, _messages):
        return json.dumps({"model": "local:small", "thinking": True, "reason": "Think"})

    thinking_models = [{**MODELS[0], "capabilities": ["chat", "thinking"]}, *MODELS[1:]]
    engine = RoutingEngine(assisted_config(thinking_policy="never"), thinking_models, model_router_ask=ask)
    decision = asyncio.run(engine.decide("Analyze this carefully"))

    assert decision.model == "small"
    assert decision.thinking is False


def test_thinking_is_never_enabled_for_a_model_that_does_not_report_support():
    async def ask(_model, _messages):
        return json.dumps({"model": "local:small", "thinking": True, "reason": "Think"})

    engine = RoutingEngine(
        assisted_config(thinking_policy="always"), MODELS, model_router_ask=ask
    )
    decision = asyncio.run(engine.decide("Analyze this carefully"))

    assert decision.thinking is False


def test_actions_bypass_the_optional_routing_model():
    calls = []

    async def ask(*args):
        calls.append(args)
        return "{}"

    engine = RoutingEngine(assisted_config(), MODELS, model_router_ask=ask)
    decision = asyncio.run(engine.decide("Create a task called Buy milk"))

    assert decision.route == "ACTION"
    assert calls == []


# --- affinity -------------------------------------------------------


def test_affinity_keeps_the_previous_model():
    decision = decide("Now rewrite section three.", affinity=("desktop", "big"))
    assert decision.provider == "desktop"
    assert decision.reason == "Conversation affinity"


def test_affinity_breaks_when_the_request_needs_more():
    decision = decide(
        "Analyze this repository architecture in depth",
        affinity=("local", "small"),
    )
    assert decision.route == "REMOTE"


def test_affinity_breaks_when_the_mode_disallows_the_tier():
    decision = decide("Now rewrite section three.", mode="local_only", affinity=("cloud", "cloud"))
    assert decision.route == "LOCAL"


def test_affinity_is_ignored_when_the_model_disappeared():
    decision = decide("Now rewrite section three.", affinity=("desktop", "removed-model"))
    assert decision.reason != "Conversation affinity"


# --- policy ---------------------------------------------------------


def test_escalate_lane_orders_remote_before_cloud():
    policy = RoutingPolicy.from_config(config())
    assert policy.preference("ESCALATE", "auto") == ("REMOTE", "CLOUD", "LOCAL")


def test_local_only_privacy_removes_cloud_from_every_preference():
    policy = RoutingPolicy.from_config(config(privacy_mode="local_only"))
    assert "CLOUD" not in policy.preference("ESCALATE", "auto")
    assert "CLOUD" not in policy.preference("LOCAL", "auto")


def test_unconfident_classification_is_marked_in_the_trace():
    engine = RoutingEngine(config(), MODELS)
    unsure = Classification(lane="ESCALATE", reason="Dispatcher unavailable", source="dispatch", confident=False,
                            error="timeout")
    decision = engine.select(unsure)
    assert decision.confident is False
    assert decision.confidence < 0.9
    assert any("fell back" in step["message"] for step in decision.trace)


# --- switchyard ------------------------------------------------------


def switchyard(mode_policy=None):
    from backend.routing.switchyard_adapter import SwitchyardRouter

    return SwitchyardRouter(RoutingPolicy.from_config(config(**(mode_policy or {}))), NODES, {"endpoint": "http://x"})


def _classification(lane="LOCAL"):
    return Classification(lane=lane, reason="test", source="test")


def test_switchyard_cannot_escape_a_local_only_request():
    # The external engine proposes a remote model for a request the user
    # pinned to the local machine. The mode is the user's constraint; an
    # outside service does not get to relax it.
    router = switchyard()
    fallback = router.builtin.select(_classification(), MODELS, "local_only")
    decision = router._interpret({"provider": "desktop", "model": "big"}, MODELS, "local_only", fallback)
    assert decision.route == "LOCAL"
    assert any("violated the route policy" in step["message"] for step in decision.trace)


def test_switchyard_cannot_propose_cloud_under_local_only():
    router = switchyard()
    fallback = router.builtin.select(_classification(), MODELS, "local_only")
    decision = router._interpret({"provider": "openrouter-main", "model": "cloud"}, MODELS, "local_only", fallback)
    assert decision.route == "LOCAL"


def test_switchyard_cannot_escape_local_only_privacy_mode():
    router = switchyard({"privacy_mode": "local_only"})
    fallback = router.builtin.select(_classification("ESCALATE"), MODELS, "auto")
    decision = router._interpret({"provider": "openrouter-main", "model": "cloud"}, MODELS, "auto", fallback)
    assert decision.route != "CLOUD"


def test_switchyard_decision_is_accepted_when_the_mode_permits_it():
    router = switchyard()
    fallback = router.builtin.select(_classification(), MODELS, "auto")
    decision = router._interpret({"provider": "desktop", "model": "big"}, MODELS, "auto", fallback)
    assert decision.route == "REMOTE"
    assert decision.model == "big"
