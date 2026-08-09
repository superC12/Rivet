#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="/opt/rivet"
CONFIG_ROOT="/etc/rivet"
DATA_ROOT="/var/lib/rivet"
SERVICE_NAME="rivet.service"
SERVICE_USER="rivet"
PURGE=false
ASSUME_YES=false

for argument in "$@"; do
  case "$argument" in
    --purge) PURGE=true ;;
    --yes|-y) ASSUME_YES=true ;;
    --help|-h)
      printf 'Usage: sudo rivet uninstall [--purge] [--yes]\n\nWithout --purge, configuration and conversations are preserved.\n'
      exit 0
      ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; exit 1 ;;
  esac
done

[[ ${EUID:-$(id -u)} -eq 0 ]] || { printf 'Run with sudo.\n' >&2; exit 1; }

if [[ "$ASSUME_YES" != true ]]; then
  printf 'Remove the Rivet application and service? [y/N] '
  read -r answer
  [[ "$answer" =~ ^[Yy]$ ]] || { printf 'Cancelled.\n'; exit 0; }
fi

systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
rm -f -- "/etc/systemd/system/$SERVICE_NAME" "/usr/local/bin/rivet"
systemctl daemon-reload
rm -rf -- "$INSTALL_ROOT"

if [[ "$PURGE" == true ]]; then
  [[ "$CONFIG_ROOT" == "/etc/rivet" ]] && rm -rf -- "$CONFIG_ROOT"
  [[ "$DATA_ROOT" == "/var/lib/rivet" ]] && rm -rf -- "$DATA_ROOT"
  userdel "$SERVICE_USER" >/dev/null 2>&1 || true
  getent group "$SERVICE_USER" >/dev/null && groupdel "$SERVICE_USER" >/dev/null 2>&1 || true
  printf 'Rivet, its configuration, and its conversation data were removed.\n'
else
  printf 'Rivet was removed. Configuration and conversations remain in %s and %s.\n' "$CONFIG_ROOT" "$DATA_ROOT"
  printf 'Reinstalling Rivet will reuse them. Use --purge to remove them permanently.\n'
fi
