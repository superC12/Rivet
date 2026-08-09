from pathlib import Path

import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_and_management_command():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["requires-python"] == ">=3.12"
    assert metadata["project"]["scripts"]["rivet"] == "backend.cli:main"


def test_ubuntu_packaging_files_are_present():
    required = [
        ROOT / "install.sh",
        ROOT / "scripts" / "rivet-server",
        ROOT / "scripts" / "uninstall.sh",
        ROOT / "packaging" / "rivet.service",
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / ".github" / "workflows" / "release.yml",
    ]
    assert all(path.is_file() for path in required)


def test_installer_defaults_to_localhost_and_preserves_data_on_normal_removal():
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    uninstaller = (ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
    assert "RIVET_HOST=127.0.0.1" in installer
    assert 'RIVET_DEFAULT_REPOSITORY="superC12/Rivet"' in installer
    assert "YOUR_GITHUB_USER" not in installer
    assert 'if [[ "$PURGE" == true ]]' in uninstaller
