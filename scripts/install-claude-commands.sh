#!/usr/bin/env bash
# install-claude-commands.sh — Claude Code skills Command Center ships, for every repo on this machine.
#
#   scripts/install-claude-commands.sh     link them into ~/.claude/skills (idempotent)
#
# /night-shift   work this repo's Command Center tasks end to end while Jay is away; never deploys
# /ui-test       test the UI merged since the last run with Playwright, keep the tests, report findings to Jay
# (the same texts the Dashboard's Night shift and UI tests buttons send: server/ccd/skills/<name>/SKILL.md)
#
# Links, not copies: every go-live brings the current rules. Anything already there that is not our link is
# left alone and reported. The older ~/.claude/commands/night-shift.md link is removed when it is ours.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OLD="$HOME/.claude/commands/night-shift.md"
if [ -L "$OLD" ] && [ "$(readlink "$OLD")" = "$REPO/server/ccd/night_shift.md" ]; then
  rm -f "$OLD"
fi
mkdir -p "$HOME/.claude/skills"
for name in night-shift ui-test; do
  SRC="$REPO/server/ccd/skills/$name"
  DST="$HOME/.claude/skills/$name"
  if [ -L "$DST" ]; then
    # a link already there is replaced only when it points into a Command Center checkout (ours, maybe an older one)
    case "$(readlink "$DST")" in
      */server/ccd/skills/$name) ;;
      *) echo "install-claude-commands: $DST is a link to $(readlink "$DST"), not Command Center's; left as it is" >&2
         continue ;;
    esac
  elif [ -e "$DST" ]; then
    echo "install-claude-commands: $DST exists and is not Command Center's; left as it is" >&2
    continue
  fi
  ln -sfn "$SRC" "$DST"
  echo "/$name -> $SRC"
done
