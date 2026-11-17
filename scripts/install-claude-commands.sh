#!/usr/bin/env bash
# install-claude-commands.sh — Claude Code skills Command Center ships, for every repo on this machine.
#
#   scripts/install-claude-commands.sh     link them into ~/.claude/skills (idempotent)
#
# /night-shift   work this repo's Command Center tasks end to end while Jay is away; never deploys
# /ui-test       test the UI merged since the last run with Playwright, keep the tests, report findings to Jay
# (the same texts the Dashboard's Night shift and UI tests buttons send: server/ccd/skills/<name>/SKILL.md)
#
# and the AskUserQuestion hook (scripts/cc-ask-hook, server/ccd/ask_hook.py) in ~/.claude/settings.json: an agent's
# own question prompt goes to Jay through Command Center (Slack and the ticket) instead of stopping its pane.
# Only that one hook entry is added or pointed at this checkout; everything else in the file is kept as it is.
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

python3 - "$HOME/.claude/settings.json" "$REPO/scripts/cc-ask-hook" <<'PY'
import json
import os
import sys
import tempfile

path, hook = sys.argv[1], sys.argv[2]
say = lambda m: print(f"install-claude-commands: {m}", file=sys.stderr)
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except (OSError, ValueError) as e:
    say(f"{path} could not be read as JSON ({type(e).__name__}); the AskUserQuestion hook was not added")
    sys.exit(0)
hooks = data.setdefault("hooks", {}) if isinstance(data, dict) else None
pre = hooks.setdefault("PreToolUse", []) if isinstance(hooks, dict) else None
if not isinstance(pre, list):
    say(f"{path} has an unexpected hooks shape; the AskUserQuestion hook was not added")
    sys.exit(0)
ours = [h for e in pre if isinstance(e, dict) and e.get("matcher") == "AskUserQuestion"
        for h in (e.get("hooks") or []) if isinstance(h, dict)
        and str(h.get("command") or "").endswith("/scripts/cc-ask-hook")]
if ours and all(h.get("command") == hook for h in ours):
    print(f"AskUserQuestion hook -> {hook} (already set)")
    sys.exit(0)
for h in ours:            # ours, from another Command Center checkout: point it here
    h["command"] = hook
if not ours:
    pre.append({"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command": hook, "timeout": 45}]})
os.makedirs(os.path.dirname(path), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings.json.")
with os.fdopen(fd, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
if os.path.exists(path):
    os.chmod(tmp, os.stat(path).st_mode & 0o777)
os.replace(tmp, path)
print(f"AskUserQuestion hook -> {hook}")
PY
