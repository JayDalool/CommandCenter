#!/usr/bin/env bash
# go-live.sh — switch the LIVE Command Center (127.0.0.1:7777) to origin/main, safely, in one step.
#
#   scripts/go-live.sh [--dry-run] [--branch <name> --i-know]
#
#   scripts/go-live.sh --dry-run                  # print the target sha, the new commits and the rollback; change nothing
#   scripts/go-live.sh                            # deploy origin/main
#   scripts/go-live.sh --branch <name> --i-know   # emergency only: deploy another branch
#   CC_REPO=/srv/server/repos/CommandCenter bash go-live.sh   # run a copy fetched from the branch
#
# main is the reviewed release line. Any other branch is unreviewed and needs --branch <name> --i-know.
#
# Run it on jay-server from the live checkout (/srv/server/repos/CommandCenter). It:
#   1. refuses if tracked files have uncommitted changes (untracked files such as .claude/ are left alone)
#   2. fetches, prints the target sha, the new commits and the commits leaving live (live = the commit named by
#      the UI release ccd serves, else HEAD), and refuses if the local branch has diverged
#      (--dry-run stops here and writes nothing)
#   3. backs up tasks.db with SQLite's backup API (~/command-center/backups/tasks.db.pre-<branch>-<stamp>)
#   4. frees the branch if another worktree (e.g. ~/cc-preview) has it checked out (that worktree is
#      left on the same commit, detached — its files do not change)
#   5. switches to the branch and fast-forwards it to origin
#   6. installs the server requirements, builds and installs the UI as an atomic release, and rebuilds the
#      Windows launcher offered under Settings → Desktop app
#   7. links Claude's /night-shift skill into ~/.claude/skills (scripts/install-claude-commands.sh)
#   8. restarts ccd (which applies any additive tasks.db migration) and waits for it to answer
# and prints the exact rollback. It never deletes anything and never touches herdr or any agent.
set -euo pipefail

usage() {
  echo "usage: go-live.sh [--dry-run] [--branch <name> --i-know]   (default branch: main, the reviewed release line)" >&2
  exit 2
}
BRANCH=main
DRY_RUN=0
I_KNOW=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --i-know) I_KNOW=1 ;;
    --branch)
      [ $# -ge 2 ] || usage
      case "$2" in ""|-*) usage ;; esac
      BRANCH="$2"
      shift ;;
    *) usage ;;
  esac
  shift
done
# BRANCH must be a plain branch name: never a refspec (main:refs/heads/x, feature:refs/remotes/origin/main, main:).
case "$BRANCH" in *:*|*@\{*) usage ;; esac
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || usage
git check-ref-format "refs/heads/$BRANCH" >/dev/null 2>&1 || usage
if [ "$BRANCH" != main ] && [ "$I_KNOW" != 1 ]; then
  echo "go-live: $BRANCH is not main; deploy only reviewed main, or add --i-know" >&2
  exit 2
fi

REPO="${CC_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DB="${CCD_DATA_DIR:-$HOME/command-center/data}/tasks.db"
BACKUPS="$HOME/command-center/backups"
PORT="${CCD_PORT:-7777}"
cd "$REPO"

# Only real changes to tracked files stop the switch. Untracked files (e.g. Claude Code's local .claude/)
# are left exactly where they are; git itself refuses the switch if the branch would overwrite one.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "go-live: $REPO has uncommitted changes to tracked files; commit or stash them first:" >&2
  git status --short --untracked-files=no >&2
  exit 1
fi
PREV_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
PREV_SHA="$(git rev-parse HEAD)"
# What is live is what ccd serves: deploy-web.sh names each UI release <stamp>-<rev>[-dirty] from the commit it
# was built at, and ccd was restarted on that same commit. The checkout's HEAD can be ahead of it (a git pull
# after a merge), so the release name decides the rollback; HEAD is only the fallback.
WEB="${CCD_WEB_DIR:-$HOME/.local/share/command-center/web}"
live_rev="$(basename "$(readlink "$WEB/current" 2>/dev/null || true)" | cut -s -d- -f2)"
LIVE_SHA=""
if [ -n "$live_rev" ]; then
  LIVE_SHA="$(git rev-parse -q --verify "$live_rev^{commit}" 2>/dev/null || true)"
fi
if [ -z "$LIVE_SHA" ]; then
  echo "note: cannot tell the live version from $WEB/current; using the checkout's HEAD ${PREV_SHA:0:12}"
elif [ "$LIVE_SHA" != "$PREV_SHA" ]; then
  echo "note: the checkout is at ${PREV_SHA:0:12} but live is ${LIVE_SHA:0:12}; rollback and commit lists use live"
  PREV_BRANCH=live
  PREV_SHA="$LIVE_SHA"
fi
safe="$(echo "$BRANCH" | tr '/' '-')"
backup="$BACKUPS/tasks.db.pre-$safe-<stamp>"

# Printed by --dry-run and at the end of a real run. "git switch --detach <sha>" is right from main and from
# a detached HEAD alike; the sha is the full one.
rollback_text() {
  cat <<EOF
Rollback (back to $PREV_BRANCH @ ${PREV_SHA:0:12}):
  cd $REPO && git switch --detach $PREV_SHA && server/.venv/bin/pip install -q -r server/requirements.txt && scripts/deploy-web.sh
  (then git switch main once fixed)
  systemctl --user stop ccd && cp "$backup" "$DB" && systemctl --user start ccd
EOF
}

echo "== fetch $BRANCH"
git fetch -q origin "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
TARGET="$(git rev-parse "origin/$BRANCH")"
echo "== deploying $BRANCH @ $TARGET"
if [ "$BRANCH" != main ]; then
  echo "!! NOT main: $BRANCH has not been reviewed for release (--i-know given)"
fi
log="$(git log --oneline "$PREV_SHA..origin/$BRANCH")"
echo "${log:-(already at target)}"
leaving="$(git log --oneline "origin/$BRANCH..$PREV_SHA")"
echo "leaving live:"
echo "${leaving:-(none)}"

# A local branch that is not behind origin (diverged or ahead) cannot be fast-forwarded: stop before any change.
if git show-ref -q --verify "refs/heads/$BRANCH" && ! git merge-base --is-ancestor "$BRANCH" "origin/$BRANCH"; then
  echo "go-live: local $BRANCH has diverged from origin/$BRANCH; fix it by hand first (nothing was changed)" >&2
  exit 1
fi

if [ "$DRY_RUN" = 1 ]; then
  echo
  echo "Rollback would be:"
  rollback_text
  echo
  echo "(dry run: nothing was changed)"
  exit 0
fi

stamp="$(date +%Y%m%dT%H%M%S)"
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
LAUNCHER_VERSION=""
if command -v go >/dev/null 2>&1 || [ -x "$HOME/.local/go/bin/go" ]; then
  if scripts/build-launcher.sh >/dev/null; then
    LAUNCHER_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
      "${CCD_LAUNCHER_DIR:-$HOME/.local/share/command-center/launcher}/launcher.json" 2>/dev/null || true)"
    echo "   CommandCenter.exe ${LAUNCHER_VERSION:+$LAUNCHER_VERSION }ready to download"
  else
    echo "   launcher build failed (Command Center itself is unaffected): run scripts/build-launcher.sh to see why"
  fi
else
  echo "   Go is not installed here; the Desktop app page keeps the old exe"
fi

echo "== Claude skills (/night-shift)"
scripts/install-claude-commands.sh | sed 's/^/   /'

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
Next: Settings → Desktop app → download CommandCenter.exe${LAUNCHER_VERSION:+ ($LAUNCHER_VERSION)}, put it in place, double-click it once.
Sign in: start CommandCenter.exe on Windows, or run
  $REPO/scripts/cc-session --url
and open the link.

$(rollback_text)

Old Command Center UI tickets (dry run first, then --apply):
  $REPO/scripts/reconcile-cc-ui.py
EOF
