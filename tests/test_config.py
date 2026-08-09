from backend.config import _drop_blank_identity


def test_blank_assistant_name_is_ignored():
    # A settings form that posts before it is populated must not wipe
    # the assistant's identity.
    payload = {"assistant": {"name": "  ", "tagline": "Still here"}}
    assert _drop_blank_identity(payload)["assistant"] == {"tagline": "Still here"}


def test_a_real_name_is_preserved():
    payload = {"assistant": {"name": "Atlas"}}
    assert _drop_blank_identity(payload)["assistant"]["name"] == "Atlas"


def test_clearing_instructions_is_allowed():
    payload = {"assistant": {"name": "Atlas", "instructions": ""}}
    assert _drop_blank_identity(payload)["assistant"]["instructions"] == ""


def test_payloads_without_an_assistant_block_pass_through():
    payload = {"router": {"prefer_local": False}}
    assert _drop_blank_identity(payload) == payload


def test_secrets_never_appear_in_the_public_settings():
    from backend.config import settings

    public = settings.public()
    for gateway in public["actions"].values():
        assert set(gateway) == {"enabled", "configured"}
        assert "endpoint" not in gateway


def test_accent_settings_survive_a_save_and_reload():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        saved = client.post(
            "/api/settings",
            json={"interface": {"accent": {"mode": "fixed", "color": "#63a7ff"}}},
        )
        assert saved.status_code == 200
        accent = client.get("/api/settings").json()["interface"]["accent"]

    assert accent == {"mode": "fixed", "color": "#63a7ff"}


# --- settings API round-trip -----------------------------------------


def test_n8n_settings_survive_a_save_and_reload():
    from fastapi.testclient import TestClient

    from backend.main import app

    webhook = "https://n8n.example/webhook/rivet-test"
    with TestClient(app) as client:
        saved = client.post(
            "/api/settings",
            json={"actions": {"n8n": {"enabled": True, "endpoint": webhook}}},
        )
        assert saved.status_code == 200
        reloaded = client.get("/api/settings").json()

    n8n = reloaded["actions"]["n8n"]
    assert n8n["enabled"] is True
    assert n8n["configured"] is True
    # The webhook URL carries its own authorisation, so it must not come
    # back out of the API even though it was just accepted by it.
    assert webhook not in saved.text
    assert "endpoint" not in n8n


def test_the_saved_webhook_actually_reaches_the_gateway():
    from backend.api.dependencies import action_gateway
    from backend.config import settings

    settings.update({"actions": {"n8n": {"enabled": True, "endpoint": "https://n8n.example/hook"}}})
    gateway = action_gateway()
    assert gateway.enabled
    assert gateway.endpoint == "https://n8n.example/hook"


def test_manual_provider_is_saved_as_a_real_routable_connection():
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from backend.api.dependencies import invalidate_model_cache, providers
    from backend.config import CONFIG_DIR, _save, settings
    from backend.main import app

    original = deepcopy(settings.rivet)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/providers/manual",
                json={
                    "name": "Lab Backup",
                    "type": "ollama",
                    "endpoint": "http://10.0.0.42:11434",
                    "location": "remote",
                },
            )
        assert response.status_code == 200
        assert response.json()["provider_id"] == "manual-lab-backup"
        provider = providers()["manual-lab-backup"]
        assert provider.endpoint == "http://10.0.0.42:11434"
        assert provider.node == "manual-lab-backup-node"
        assert provider.config["auto_detect"] is False
        assert settings.rivet["nodes"][provider.node]["type"] == "remote"
        assert settings.rivet["providers"]["manual-lab-backup"]["manual"] is True
    finally:
        settings.rivet = original
        _save(CONFIG_DIR / "rivet.yaml", original)
        invalidate_model_cache()


def test_manual_non_openrouter_provider_requires_an_endpoint():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/providers/manual",
            json={"name": "Missing address", "type": "ollama", "location": "local"},
        )
    assert response.status_code == 422


def test_manual_provider_and_its_orphaned_node_can_be_deleted():
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from backend.api.dependencies import invalidate_model_cache
    from backend.config import CONFIG_DIR, _save, settings
    from backend.main import app

    original = deepcopy(settings.rivet)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/providers/manual",
                json={
                    "name": "Temporary Remote",
                    "type": "ollama",
                    "endpoint": "http://100.64.0.42:11434",
                    "location": "remote",
                },
            )
            provider_id = created.json()["provider_id"]
            node_id = settings.rivet["providers"][provider_id]["node"]

            removed = client.delete(f"/api/providers/manual/{provider_id}")

            assert removed.status_code == 200
            assert provider_id not in settings.rivet["providers"]
            assert node_id not in settings.rivet["nodes"]
            assert client.delete("/api/providers/manual/local-ollama").status_code == 404
    finally:
        settings.rivet = original
        _save(CONFIG_DIR / "rivet.yaml", original)
        invalidate_model_cache()


# --- config templates -------------------------------------------------


def test_templates_are_shipped_and_live_config_is_ignored():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("assistant.yaml", "rivet.yaml"):
        assert (root / "config" / f"{name}.example").is_file(), name
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    assert "config/assistant.yaml" in ignored
    assert "config/rivet.yaml" in ignored


def test_a_missing_config_file_is_seeded_from_its_template(tmp_path):
    import shutil

    from backend.config import _seed_from_template

    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    shutil.copyfile(root / "config" / "rivet.yaml.example", tmp_path / "rivet.yaml.example")
    live = tmp_path / "rivet.yaml"

    _seed_from_template(live)
    assert live.is_file()

    # Seeding happens once; it must never overwrite a real config.
    live.write_text("router:\n  strategy: custom\n", encoding="utf-8")
    _seed_from_template(live)
    assert "custom" in live.read_text(encoding="utf-8")
