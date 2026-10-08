#!/usr/bin/env bash
# go-live.sh — switch the LIVE Command Center (127.0.0.1:7777) to a branch, safely, in one step.
#
#   scripts/go-live.sh                                 # the control room branch
#   scripts/go-live.sh <branch>                        # any other branch
#   CC_REPO=/srv/server/repos/CommandCenter bash go-live.sh   # run a copy fetched from the branch
#
# Run it on jay-server from the live checkout (/srv/server/repos/CommandCenter). It:
#   1. refuses if the checkout has uncommitted changes
#   2. backs up tasks.db with SQLite's backup API (~/command-center/backups/tasks.db.pre-<branch>-<stamp>)
#   3. frees the branch if another worktree (e.g. ~/cc-preview) has it checked out (that worktree is
#      left on the same commit, detached — its files do not change)
#   4. switches to the branch and fast-forwards it to origin
#   5. installs the server requirements, builds and installs the UI as an atomic release, and rebuilds the
#      Windows launcher offered under Settings → Desktop app
#   6. restarts ccd (which applies any additive tasks.db migration) and waits for it to answer
# and prints the exact rollback. It never deletes anything and never touches herdr or any agent.
set -euo pipefail

BRANCH="${1:-claude/amazing-keller-fpy0qw}"
REPO="${CC_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DB="${CCD_DATA_DIR:-$HOME/command-center/data}/tasks.db"
BACKUPS="$HOME/command-center/backups"
PORT="${CCD_PORT:-7777}"
cd "$REPO"

if [ -n "$(git status --porcelain)" ]; then
  echo "go-live: $REPO has uncommitted changes; commit or stash them first:" >&2
  git status --short >&2
  exit 1
fi
PREV_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
PREV_SHA="$(git rev-parse --short HEAD)"

echo "== fetch $BRANCH"
git fetch -q origin "$BRANCH"

stamp="$(date +%Y%m%dT%H%M%S)"
safe="$(echo "$BRANCH" | tr '/' '-')"
backup="$BACKUPS/tasks.db.pre-$safe-$stamp"
mkdir -p "$BACKUPS"
if [ -f "$DB" ]; then
  echo "== back up tasks.db -> $backup"
  server/.venv/bin/python - "$DB" "$backup" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY
else
  echo "== no tasks.db at $DB (nothing to back up)"
fi

# A branch can be checked out in one worktree only: detach any other worktree that holds it.
other="$(git worktree list --porcelain | awk -v b="refs/heads/$BRANCH" -v me="$REPO" '
  /^worktree /{w=substr($0,10)} $0=="branch " b && w!=me {print w}')"
if [ -n "$other" ]; then
  echo "== $other has $BRANCH checked out; detaching it there (its files stay as they are)"
  git -C "$other" switch -q --detach
fi

echo "== switch to $BRANCH"
if git show-ref -q --verify "refs/heads/$BRANCH"; then
  git switch -q "$BRANCH"
  git merge -q --ff-only "origin/$BRANCH"
else
  git switch -q -c "$BRANCH" --track "origin/$BRANCH"
fi
echo "   now at $(git rev-parse --short HEAD)"

echo "== server requirements"
server/.venv/bin/pip install -q -r server/requirements.txt

echo "== UI release"
scripts/deploy-web.sh

echo "== Windows launcher (Settings → Desktop app download)"
if command -v go >/dev/null 2>&1 || [ -x "$HOME/.local/go/bin/go" ]; then
  scripts/build-launcher.sh >/dev/null && echo "   CommandCenter.exe $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
    "${CCD_LAUNCHER_DIR:-$HOME/.local/share/command-center/launcher}/launcher.json") ready to download" \
    || echo "   launcher build failed (Command Center itself is unaffected): run scripts/build-launcher.sh to see why"
else
  echo "   Go is not installed here; the Desktop app page keeps the old exe"
fi

echo "== restart ccd"
systemctl --user restart ccd
for i in $(seq 1 30); do
  if curl -fsS -H "Host: 127.0.0.1:$PORT" "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "   ccd answers on 127.0.0.1:$PORT"
    break
  fi
  sleep 1
  if [ "$i" = 30 ]; then
    echo "go-live: ccd did not answer in 30 s — see: journalctl --user -u ccd -n 50" >&2
    echo "Rollback: see below." >&2
  fi
done

cat <<EOF

Live is on $BRANCH ($(git rev-parse --short HEAD)).
Next: Settings → Desktop app → download CommandCenter.exe (0.4.0), put it in place, double-click it once.
Sign in: start CommandCenter.exe on Windows, or run
  $REPO/scripts/cc-session --url
and open the link.

Rollback (back to $PREV_BRANCH @ $PREV_SHA):
  cd $REPO && git switch $PREV_BRANCH && scripts/deploy-web.sh
  systemctl --user stop ccd && cp "$backup" "$DB" && systemctl --user start ccd

Old Command Center UI tickets (dry run first, then --apply):
  $REPO/scripts/reconcile-cc-ui.py
EOF
