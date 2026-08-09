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
