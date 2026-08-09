import re
import tomllib
from pathlib import Path

from backend import __version__

ROOT = Path(__file__).resolve().parents[1]


def changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_version_is_consistent_across_the_project():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == __version__


def test_the_current_version_has_a_changelog_entry():
    # A release whose notes are generated from an absent section ships
    # raw commit subjects to users. Catch that here, not at tag time.
    assert re.search(rf"^## \[{re.escape(__version__)}\]", changelog(), re.M)


def test_changelog_sections_have_comparison_links():
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog(), re.M)
    assert versions, "changelog has no released versions"
    for version in versions:
        assert re.search(rf"^\[{re.escape(version)}\]: https://", changelog(), re.M), version


def test_release_notes_extract_cleanly_for_the_current_version():
    # Mirrors the extraction the release workflow performs.
    match = re.search(
        rf"^## \[{re.escape(__version__)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog(),
        re.M | re.S,
    )
    assert match
    section = match.group(1).strip()
    assert section
    # The section must stop before the previous release.
    assert "## [" not in section


def test_about_panel_does_not_hardcode_a_version():
    # It reads /api/status instead, so it cannot drift from the build.
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="about-version"' in markup
    assert not re.search(r"Version \d+\.\d+\.\d+", markup)


def test_adaptive_accent_has_a_status_target_and_is_not_pinned_by_root_transition():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    tokens = (ROOT / "frontend" / "css" / "tokens.css").read_text(encoding="utf-8")

    assert 'id="accent-context"' in markup
    assert 'aria-live="polite"' in markup
    assert not re.search(r"transition\s*:[^;]*--accent", tokens)


def test_atmosphere_uses_explicit_accent_invalidation_and_stays_within_the_brief():
    atmosphere = (ROOT / "frontend" / "js" / "atmosphere.js").read_text(encoding="utf-8")
    accent = (ROOT / "frontend" / "js" / "accent.js").read_text(encoding="utf-8")
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "getComputedStyle" not in atmosphere
    assert 'addEventListener("rivet:accentchange"' in atmosphere
    assert 'new CustomEvent("rivet:accentchange"' in accent
    assert "Math.min(.18, Math.max(.08," in atmosphere
    assert 'id="settings-intensity" type="range" min="0.08" max="0.18"' in markup


def test_status_poll_hits_the_shared_health_cache_and_remote_nodes_stay_remote():
    from backend.nodes.health import OFFLINE_TTL_S, ONLINE_TTL_S
    from backend.routing.classifier import CLASSIFIER_HEALTH_TTL_S

    app = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    runtime = (ROOT / "frontend" / "js" / "runtime.js").read_text(encoding="utf-8")
    poll_match = re.search(r"setInterval\(.*?,\s*(\d+)\);", app)

    assert poll_match
    poll_seconds = int(poll_match.group(1)) / 1000
    assert poll_seconds < ONLINE_TTL_S < OFFLINE_TTL_S
    assert poll_seconds < CLASSIFIER_HEALTH_TTL_S
    assert '["remote", "tailscale"].includes(provider.node_type)' in runtime
    assert 'kind === "local" ? "local_only" : "auto"' in runtime


def test_classifier_health_reaches_the_diagnostics_popover():
    runtime = (ROOT / "frontend" / "js" / "runtime.js").read_text(encoding="utf-8")
    assert "status.classifier" in runtime
    assert 'classifier.error || ""' in runtime
    assert '"Classifier"' in runtime


def test_eval_cli_arguments_do_not_inherit_deployment_environment():
    eval_runner = (ROOT / "eval" / "run_eval.py").read_text(encoding="utf-8")
    assert "honor_environment=False" in eval_runner


def test_manual_connections_have_a_removal_control():
    settings = (ROOT / "frontend" / "js" / "settings.js").read_text(encoding="utf-8")
    assert 'className = "connection-delete"' in settings
    assert '/api/providers/manual/${encodeURIComponent(provider.id)}' in settings


def test_instance_branding_uses_the_setup_identity_but_about_stays_rivet():
    app = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    runtime = (ROOT / "frontend" / "js" / "runtime.js").read_text(encoding="utf-8")
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "const brandLetters = Array.from(name.toUpperCase())" in app
    assert "runtime.setInstanceName(name)" in app
    assert 'config.onboarding.complete ? savedName : "Your assistant"' in app
    assert 'onboarding.setInstanceName(config.onboarding.complete ? name : "", true)' in app
    assert 'document.querySelector("#about-platform").textContent = platform' in app
    assert "`${this.instanceName} Router`" in runtime
    assert "`${this.instanceName} API`" in runtime
    assert markup.count(">Rivet<") == 1
    assert 'id="about-platform">Rivet<' in markup
    assert 'id="onboarding-platform">YOUR ASSISTANT<' in markup
    assert 'id="setup-name" value=""' in markup


def test_benchmark_editor_uses_compact_collapsible_sections():
    benchmarks = (ROOT / "frontend" / "js" / "benchmarks.js").read_text(encoding="utf-8")
    settings = (ROOT / "frontend" / "js" / "settings.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "css" / "settings.css").read_text(encoding="utf-8")

    assert 'disclosure("Execution target"' in benchmarks
    assert 'disclosure("Prompt rules"' in benchmarks
    assert 'disclosure("Test cases"' in benchmarks
    assert 'create("div", "benchmark-test-head")' in benchmarks
    assert 'create("div", "benchmark-test-body")' in benchmarks
    assert 'classList.toggle("benchmarks-active", name === "benchmarks")' in settings
    assert ".settings-dialog.benchmarks-active .settings-footer { display: none; }" in styles
    assert "grid-template-columns: 96px 120px 1fr 120px 128px 28px" not in styles


def test_onboarding_model_rows_are_real_persisted_controls():
    onboarding = (ROOT / "frontend" / "js" / "onboarding.js").read_text(encoding="utf-8")
    runtime = (ROOT / "frontend" / "js" / "runtime.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "css" / "motion.css").read_text(encoding="utf-8")

    assert 'document.createElement("button")' in onboarding
    assert 'item.setAttribute("aria-pressed"' in onboarding
    assert "disabled_models: disabledModels" in onboarding
    assert "model_priority: this.modelPriority" in onboarding
    assert 'item.addEventListener("dragstart"' in onboarding
    assert 'event.altKey' in onboarding
    assert "model.enabled !== false" in runtime
    assert ".setup-model.excluded strong" in styles


def test_frontend_assets_cannot_survive_an_upgrade_in_browser_cache():
    main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

    assert '"Cache-Control"] = "no-store, max-age=0"' in main
    assert 'NO_STORE = {"Cache-Control": "no-store, max-age=0"' in main


def test_about_easter_egg_opens_a_non_destructive_onboarding_preview():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    onboarding = (ROOT / "frontend" / "js" / "onboarding.js").read_text(encoding="utf-8")

    assert 'id="onboarding-return-dialog"' in markup
    assert 'data-tooltip="Some marks remember their beginning."' in markup
    assert "if (markClicks.length < 5) return" in app
    assert "await onboarding.openPreview()" in app
    assert "if (this.previewMode)" in onboarding
    assert "this.closePreview();\n      return;" in onboarding


def test_the_app_shell_constrains_its_row_so_the_conversation_scrolls():
    # Without an explicit row the shell has one implicit auto row, which
    # sizes to content: a long conversation then grows the page instead
    # of scrolling, pushing the composer off the bottom of the screen.
    layout = (ROOT / "frontend" / "css" / "layout.css").read_text(encoding="utf-8")
    shell = next(line for line in layout.splitlines() if line.startswith(".app-shell {"))
    canvas = next(line for line in layout.splitlines() if line.startswith(".main-canvas {"))
    assert "grid-template-rows:" in shell
    assert "min-height: 0" in canvas
    assert "overflow-y: auto" in next(
        line for line in layout.splitlines() if line.startswith(".conversation {")
    )
