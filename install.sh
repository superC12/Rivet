#!/usr/bin/env bash
set -Eeuo pipefail

# This is the only repository value used by the remote installer. Forks can
# override it with RIVET_GITHUB_REPOSITORY or --repository.
RIVET_DEFAULT_REPOSITORY="superC12/Rivet"

INSTALL_ROOT="/opt/rivet"
CONFIG_ROOT="/etc/rivet"
DATA_ROOT="/var/lib/rivet"
SERVICE_USER="rivet"
SERVICE_NAME="rivet.service"
LOCAL_SOURCE=""
UPDATE_MODE=false
REQUESTED_VERSION="${RIVET_VERSION:-latest}"
REPOSITORY="${RIVET_GITHUB_REPOSITORY:-$RIVET_DEFAULT_REPOSITORY}"
TEMP_ROOT=""

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
fail() { printf '\nRivet installer: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Install Rivet on Ubuntu Server.

Usage:
  sudo ./install.sh --local
  curl -fsSL https://raw.githubusercontent.com/OWNER/rivet/main/install.sh | sudo bash

Options:
  --local             Install the checkout containing this script.
  --update            Update an existing installation.
  --version VERSION   Install a release tag instead of the latest release.
  --repository SLUG   GitHub repository in owner/rivet form.
  --help              Show this help.

Environment:
  RIVET_GITHUB_REPOSITORY=owner/rivet
  RIVET_VERSION=v0.2.1
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) LOCAL_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; shift ;;
    --update) UPDATE_MODE=true; shift ;;
    --version) [[ $# -ge 2 ]] || fail "--version needs a value"; REQUESTED_VERSION="$2"; shift 2 ;;
    --repository) [[ $# -ge 2 ]] || fail "--repository needs owner/repository"; REPOSITORY="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run this installer as root (use sudo)"
[[ -r /etc/os-release ]] || fail "this installer requires Ubuntu Server or Debian"
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) fail "unsupported operating system: ${PRETTY_NAME:-unknown}. Use Docker or the manual Python setup." ;;
esac

if [[ -z "$LOCAL_SOURCE" ]]; then
  [[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "repository must look like owner/rivet"
fi
[[ "$REQUESTED_VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || fail "version contains unsupported characters"

cleanup() {
  [[ -n "$TEMP_ROOT" && -d "$TEMP_ROOT" ]] && rm -rf -- "$TEMP_ROOT"
}
trap cleanup EXIT

say "Preparing this server"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl python3 python3-pip python3-venv tar >/dev/null

python3 - <<'PY' || fail "Python 3.12 or newer is required. Ubuntu 24.04 LTS includes it; older servers can use Docker."
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY

TEMP_ROOT="$(mktemp -d -t rivet-install.XXXXXXXX)"
SOURCE_ROOT="$LOCAL_SOURCE"
RELEASE_LABEL="local-$(date -u +%Y%m%d%H%M%S)"

if [[ -z "$LOCAL_SOURCE" ]]; then
  say "Downloading Rivet"
  ARCHIVE="$TEMP_ROOT/rivet.tar.gz"
  if [[ "$REQUESTED_VERSION" == "latest" ]]; then
    RELEASE_URL="https://github.com/$REPOSITORY/releases/latest/download/rivet.tar.gz"
    CHECKSUM_URL="${RELEASE_URL}.sha256"
    if curl --proto '=https' --tlsv1.2 -fsSL "$RELEASE_URL" -o "$ARCHIVE"; then
      curl --proto '=https' --tlsv1.2 -fsSL "$CHECKSUM_URL" -o "$ARCHIVE.sha256" \
        || fail "release checksum could not be downloaded"
      (cd "$TEMP_ROOT" && sha256sum --check --status rivet.tar.gz.sha256) \
        || fail "release checksum did not match"
      RELEASE_LABEL="release-$(date -u +%Y%m%d%H%M%S)"
    else
      note "No release asset was found; installing the main branch."
      curl --proto '=https' --tlsv1.2 -fsSL "https://github.com/$REPOSITORY/archive/refs/heads/main.tar.gz" -o "$ARCHIVE"
      RELEASE_LABEL="main-$(date -u +%Y%m%d%H%M%S)"
    fi
  else
    curl --proto '=https' --tlsv1.2 -fsSL "https://github.com/$REPOSITORY/archive/refs/tags/$REQUESTED_VERSION.tar.gz" -o "$ARCHIVE"
    RELEASE_LABEL="${REQUESTED_VERSION//[^A-Za-z0-9._-]/-}-$(date -u +%Y%m%d%H%M%S)"
  fi
  mkdir -p "$TEMP_ROOT/source"
  tar -xzf "$ARCHIVE" -C "$TEMP_ROOT/source"
  SOURCE_ROOT="$(find "$TEMP_ROOT/source" -mindepth 1 -maxdepth 2 -type f -name pyproject.toml -printf '%h\n' | head -n 1)"
  [[ -n "$SOURCE_ROOT" ]] || fail "downloaded archive does not contain a Rivet project"
fi

[[ -f "$SOURCE_ROOT/backend/main.py" && -f "$SOURCE_ROOT/frontend/index.html" ]] || fail "source directory is not a complete Rivet checkout"

say "Installing Rivet"
if ! getent group "$SERVICE_USER" >/dev/null; then
  groupadd --system "$SERVICE_USER"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_USER" --home-dir "$DATA_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$INSTALL_ROOT/releases" "$CONFIG_ROOT" "$DATA_ROOT"
RELEASE_ROOT="$INSTALL_ROOT/releases/$RELEASE_LABEL"
mkdir -p "$RELEASE_ROOT"
tar \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='data/*.db*' \
  -C "$SOURCE_ROOT" -cf - . | tar -C "$RELEASE_ROOT" -xf -
chmod +x "$RELEASE_ROOT/install.sh" "$RELEASE_ROOT/scripts/rivet-server" "$RELEASE_ROOT/scripts/uninstall.sh"

# Seed live config from the shipped templates, never overwriting an
# existing file. An upgrade must not reset the user's assistant.
for config_file in assistant.yaml rivet.yaml; do
  if [[ ! -f "$CONFIG_ROOT/$config_file" ]]; then
    install -m 640 -o "$SERVICE_USER" -g "$SERVICE_USER" \
      "$RELEASE_ROOT/config/$config_file.example" "$CONFIG_ROOT/$config_file"
  fi
done
if [[ ! -f "$CONFIG_ROOT/rivet.env" ]]; then
  cat >"$CONFIG_ROOT/rivet.env" <<EOF
# Rivet runtime settings. Keep this file private.
RIVET_HOST=127.0.0.1
RIVET_PORT=8080
RIVET_GITHUB_REPOSITORY=$REPOSITORY
OPENROUTER_API_KEY=
N8N_ACTION_KEY=
EOF
else
  if ! grep -q '^RIVET_GITHUB_REPOSITORY=' "$CONFIG_ROOT/rivet.env"; then
    printf '\nRIVET_GITHUB_REPOSITORY=%s\n' "$REPOSITORY" >>"$CONFIG_ROOT/rivet.env"
  fi
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_ROOT" "$DATA_ROOT"
chmod 750 "$CONFIG_ROOT" "$DATA_ROOT"
chmod 600 "$CONFIG_ROOT/rivet.env"

OLD_RELEASE=""
if [[ -L "$INSTALL_ROOT/current" ]]; then
  OLD_RELEASE="$(readlink -f "$INSTALL_ROOT/current")"
fi

if [[ ! -x "$INSTALL_ROOT/venv/bin/python" ]]; then
  python3 -m venv "$INSTALL_ROOT/venv"
fi
"$INSTALL_ROOT/venv/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
if ! "$INSTALL_ROOT/venv/bin/python" -m pip install --quiet --upgrade --editable "$RELEASE_ROOT"; then
  rm -rf -- "$RELEASE_ROOT"
  fail "Python package installation failed"
fi

ln -sfn "$RELEASE_ROOT" "$INSTALL_ROOT/current.next"
mv -Tf "$INSTALL_ROOT/current.next" "$INSTALL_ROOT/current"
install -m 644 "$RELEASE_ROOT/packaging/rivet.service" "/etc/systemd/system/$SERVICE_NAME"
ln -sfn "$INSTALL_ROOT/venv/bin/rivet" /usr/local/bin/rivet
chown -R root:root "$INSTALL_ROOT"
chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_ROOT" "$DATA_ROOT"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"

HEALTH_HOST="$(sed -n 's/^RIVET_HOST=//p' "$CONFIG_ROOT/rivet.env" | tail -n 1)"
HEALTH_PORT="$(sed -n 's/^RIVET_PORT=//p' "$CONFIG_ROOT/rivet.env" | tail -n 1)"
[[ "$HEALTH_HOST" =~ ^[A-Za-z0-9:._-]+$ ]] || HEALTH_HOST="127.0.0.1"
[[ "$HEALTH_PORT" =~ ^[0-9]{1,5}$ ]] || HEALTH_PORT="8080"
[[ "$HEALTH_HOST" == "0.0.0.0" || "$HEALTH_HOST" == "::" ]] && HEALTH_HOST="127.0.0.1"
HEALTHY=false
for _ in {1..20}; do
  if curl -fsS "http://$HEALTH_HOST:$HEALTH_PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then
    HEALTHY=true
    break
  fi
  sleep 1
done

if [[ "$HEALTHY" != true ]]; then
  if [[ -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
    note "The new release did not become healthy; restoring the previous release."
    ln -sfn "$OLD_RELEASE" "$INSTALL_ROOT/current.next"
    mv -Tf "$INSTALL_ROOT/current.next" "$INSTALL_ROOT/current"
    "$INSTALL_ROOT/venv/bin/python" -m pip install --quiet --upgrade --editable "$OLD_RELEASE"
    systemctl restart "$SERVICE_NAME"
  fi
  journalctl -u "$SERVICE_NAME" -n 25 --no-pager >&2 || true
  fail "Rivet did not pass its startup health check"
fi

say "$([[ "$UPDATE_MODE" == true ]] && printf 'Rivet was updated' || printf 'Rivet is installed')"
note "Open http://$HEALTH_HOST:$HEALTH_PORT on the server."
note "Run 'rivet doctor' to verify the installation."
note "Run 'rivet logs' to follow service logs."
note "Configuration: $CONFIG_ROOT"
note "Conversation data: $DATA_ROOT"
printf '\nFor another device to connect, use Tailscale or an authenticated reverse proxy.\n'
