#!/usr/bin/env bash
# install-claude-commands.sh — Claude Code commands Command Center ships, for every repo on this machine.
#
#   scripts/install-claude-commands.sh     link them into ~/.claude/commands (idempotent)
#
# /night-shift   work this repo's Command Center tasks while Jay is away; never deploys
#                (the same text the Dashboard's Night shift button sends: server/ccd/night_shift.md)
#
# A link, not a copy: every go-live brings the current rules. An existing file that is not our link is left
# alone and reported.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)/server/ccd/night_shift.md"
DST="$HOME/.claude/commands/night-shift.md"
mkdir -p "$(dirname "$DST")"
if [ -e "$DST" ] && [ ! -L "$DST" ]; then
  echo "install-claude-commands: $DST exists and is not Command Center's; left as it is" >&2
  exit 0
fi
ln -sfn "$SRC" "$DST"
echo "/night-shift -> $SRC"
