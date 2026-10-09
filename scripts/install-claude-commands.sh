#!/usr/bin/env bash
# install-claude-commands.sh — Claude Code skills Command Center ships, for every repo on this machine.
#
#   scripts/install-claude-commands.sh     link them into ~/.claude/skills (idempotent)
#
# /night-shift   work this repo's Command Center tasks end to end while Jay is away; never deploys
#                (the same text the Dashboard's Night shift button sends: server/ccd/skills/night-shift/SKILL.md)
#
# A link, not a copy: every go-live brings the current rules. Anything already there that is not our link is
# left alone and reported. The older ~/.claude/commands/night-shift.md link is removed when it is ours.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/server/ccd/skills/night-shift"
DST="$HOME/.claude/skills/night-shift"
OLD="$HOME/.claude/commands/night-shift.md"
if [ -L "$OLD" ] && [ "$(readlink "$OLD")" = "$REPO/server/ccd/night_shift.md" ]; then
  rm -f "$OLD"
fi
mkdir -p "$(dirname "$DST")"
if [ -e "$DST" ] && [ ! -L "$DST" ]; then
  echo "install-claude-commands: $DST exists and is not Command Center's; left as it is" >&2
  exit 0
fi
ln -sfn "$SRC" "$DST"
echo "/night-shift -> $SRC"
