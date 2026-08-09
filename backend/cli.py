from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVICE = "rivet.service"
INSTALL_ROOT = Path("/opt/rivet")
CONFIG_ROOT = Path(os.getenv("RIVET_CONFIG_DIR", "/etc/rivet"))
DATA_ROOT = Path(os.getenv("RIVET_DATA_DIR", "/var/lib/rivet"))


def run(command: list[str], *, check: bool = False) -> int:
    try:
        return subprocess.run(command, check=check).returncode
    except FileNotFoundError:
        print(f"Required command is not available: {command[0]}", file=sys.stderr)
        return 127


def service_command(action: str) -> int:
    command = ["systemctl", action, SERVICE]
    if os.geteuid() != 0 and action in {"restart", "start", "stop"}:
        command.insert(0, "sudo")
    return run(command)


def doctor() -> int:
    host = os.getenv("RIVET_HOST", "127.0.0.1")
    port = os.getenv("RIVET_PORT", "8080")
    url = f"http://{host if host not in {'0.0.0.0', '::'} else '127.0.0.1'}:{port}/api/status"
    checks = {
        "service": subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0,
        "config": (CONFIG_ROOT / "assistant.yaml").is_file() and (CONFIG_ROOT / "rivet.yaml").is_file(),
        "data_directory": DATA_ROOT.is_dir(),
        "api": False,
    }
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            status = json.load(response)
            checks["api"] = status.get("status") in {"ok", "degraded"}
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass

    print("Rivet doctor")
    for name, healthy in checks.items():
        print(f"  {'OK' if healthy else 'FAIL':4}  {name.replace('_', ' ')}")
    return 0 if all(checks.values()) else 1


def update() -> int:
    installer = INSTALL_ROOT / "current" / "install.sh"
    if not installer.is_file():
        print("Rivet's installer was not found. Reinstall from the GitHub repository.", file=sys.stderr)
        return 1
    repository = os.getenv("RIVET_GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        print("Set RIVET_GITHUB_REPOSITORY=owner/rivet in /etc/rivet/rivet.env first.", file=sys.stderr)
        return 1
    command = [str(installer), "--update"]
    environment = os.environ.copy()
    environment["RIVET_GITHUB_REPOSITORY"] = repository
    if os.geteuid() != 0:
        command = ["sudo", "env", f"RIVET_GITHUB_REPOSITORY={repository}", *command]
    return subprocess.run(command, env=environment).returncode


def uninstall(*, purge: bool = False, assume_yes: bool = False) -> int:
    script = INSTALL_ROOT / "current" / "scripts" / "uninstall.sh"
    if not script.is_file():
        print("The uninstaller was not found.", file=sys.stderr)
        return 1
    command = [str(script)]
    if purge:
        command.append("--purge")
    if assume_yes:
        command.append("--yes")
    if os.geteuid() != 0:
        command.insert(0, "sudo")
    return run(command)


def main() -> None:
    parser = argparse.ArgumentParser(prog="rivet", description="Manage a Rivet server installation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show the systemd service status")
    subparsers.add_parser("doctor", help="Check the service, API, configuration, and data directory")
    subparsers.add_parser("restart", help="Restart Rivet")
    logs = subparsers.add_parser("logs", help="Follow Rivet's service logs")
    logs.add_argument("--lines", type=int, default=100)
    subparsers.add_parser("update", help="Install the latest GitHub release")
    remove = subparsers.add_parser("uninstall", help="Remove Rivet from this server")
    remove.add_argument("--purge", action="store_true", help="Also permanently remove configuration and conversations")
    remove.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    subparsers.add_parser("paths", help="Show installation paths")
    args = parser.parse_args()

    if args.command == "status":
        code = run(["systemctl", "status", SERVICE, "--no-pager"])
    elif args.command == "doctor":
        code = doctor()
    elif args.command == "restart":
        code = service_command("restart")
    elif args.command == "logs":
        code = run(["journalctl", "-u", SERVICE, "-n", str(max(1, args.lines)), "-f"])
    elif args.command == "update":
        code = update()
    elif args.command == "uninstall":
        code = uninstall(purge=args.purge, assume_yes=args.yes)
    else:
        print(f"Application: {INSTALL_ROOT / 'current'}")
        print(f"Configuration: {CONFIG_ROOT}")
        print(f"Data: {DATA_ROOT}")
        code = 0
    raise SystemExit(code)


if __name__ == "__main__":
    main()
