#!/usr/bin/env bash
# Install and start ccd as a systemd user service. Idempotent. No root needed.
#
#   scripts/install-user-unit.sh            install (or refresh) and start
#   scripts/install-user-unit.sh --remove   stop, disable, remove the unit
#
# Rollback is --remove: the legacy board falls back to building locally on its
# own the moment ccd stops answering.
set -euo pipefail
UNIT_DIR="$HOME/.config/systemd/user"
SRC="$(cd "$(dirname "$0")" && pwd)/ccd.service"

if [ "${1:-}" = "--remove" ]; then
  systemctl --user disable --now ccd.service 2>/dev/null || true
  rm -f "$UNIT_DIR/ccd.service"
  systemctl --user daemon-reload
  echo "ccd removed. The legacy board builds locally again."
  exit 0
fi

mkdir -p "$UNIT_DIR"
install -m 0644 "$SRC" "$UNIT_DIR/ccd.service"
systemctl --user daemon-reload
systemctl --user enable ccd.service >/dev/null
systemctl --user restart ccd.service
systemctl --user --no-pager --lines=0 status ccd.service | head -5
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo
  echo "NOTE: Linger=no. ccd (like herdr) stops when jay's last session ends."
  echo "      'loginctl enable-linger $USER' keeps it running; that is Jay's call."
fi
