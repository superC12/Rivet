import asyncio

from backend.actions import EXECUTED, FAILED, NOT_CONFIGURED, UNCONFIRMED, UNREACHABLE, N8nGateway


def gateway(**config):
    return N8nGateway({"enabled": True, "endpoint": "http://n8n.example/webhook/rivet", **config})


def test_gateway_is_only_enabled_when_it_has_somewhere_to_send():
    assert gateway().enabled
    assert not N8nGateway({"enabled": False, "endpoint": "http://n8n.example/hook"}).enabled
    assert not N8nGateway({"enabled": True, "endpoint": ""}).enabled
    assert not N8nGateway({}).enabled


def test_explicit_confirmation_is_the_only_success():
    assert gateway().interpret({"status": "success"}).status == EXECUTED
    assert gateway().interpret({"success": True}).status == EXECUTED
    assert gateway().interpret({"result": "ok"}).status == EXECUTED
    assert gateway().interpret({"status": "completed"}).status == EXECUTED


def test_explicit_failure_is_reported_as_failure():
    result = gateway().interpret({"success": False, "error": "workflow threw"})
    assert result.status == FAILED
    assert not result.succeeded
    assert result.detail == "workflow threw"


def test_bare_200_is_not_success():
    # An n8n webhook set to "respond immediately" answers before the
    # workflow runs. Treating that as success is exactly the lie this
    # gateway exists to prevent.
    for body in ({}, {"message": "Workflow was started"}, None, [1, 2, 3], "OK"):
        result = gateway().interpret(body)
        assert result.status == UNCONFIRMED, body
        assert not result.succeeded


def test_unconfirmed_copy_never_claims_the_work_happened():
    message = gateway().interpret({}).message.lower()
    assert "didn't confirm" in message
    assert "done" not in message


def test_gateway_message_is_passed_through_on_success():
    assert gateway().interpret({"status": "success", "message": "Task created."}).message == "Task created."


def test_not_configured_short_circuits_before_any_network_call():
    outcome = asyncio.run(N8nGateway({"enabled": False}).execute("Add buy milk to my list"))
    assert outcome.status == NOT_CONFIGURED
    assert not outcome.succeeded
    assert "Connections" in outcome.message


def test_unreachable_gateway_says_nothing_was_run():
    # Port 1 is reserved, so the connection is refused immediately.
    unreachable = N8nGateway({"enabled": True, "endpoint": "http://127.0.0.1:1/webhook", "timeout_s": 1.0})
    outcome = asyncio.run(unreachable.execute("Add buy milk to my list"))
    assert outcome.status == UNREACHABLE
    assert "nothing was run" in outcome.message
    assert not outcome.succeeded


def test_api_key_comes_from_the_environment_not_config(monkeypatch):
    monkeypatch.setenv("N8N_ACTION_KEY", "secret-value")
    instance = gateway()
    assert instance.headers["X-Rivet-Key"] == "secret-value"
    # The key must never sit in the config that gets written back to
    # disk or returned by the settings API.
    assert "secret-value" not in str(instance.config)
