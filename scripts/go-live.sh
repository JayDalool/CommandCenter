#!/usr/bin/env bash
# go-live.sh — switch the LIVE Command Center (127.0.0.1:7777) to origin/main, safely, in one step.
#
#   scripts/go-live.sh [--dry-run] [--branch <name> --i-know]
#
#   scripts/go-live.sh --dry-run                  # print the target sha, the new commits and the rollback runbook; change nothing
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
#   7. links Claude's /night-shift and /ui-test skills into ~/.claude/skills and sets the AskUserQuestion hook in
#      ~/.claude/settings.json (scripts/install-claude-commands.sh)
#   8. restarts ccd (which applies any additive tasks.db migration)
#   9. runs the release check (server/ccd/release_check.py) for about 3 minutes in this pane (CC-063): it changes
#      nothing. Healthy: one line, exit 0. Not healthy: it alerts Jay in Messages and here, linking the rollback
#      runbook, and go-live exits non-zero (3 failed, 4 inconclusive, 5 healthy but not logged, 2 cannot run,
#      1 stopped part-way or the restart failed): do NOT record the deploy as a pass. go-live prints no rollback
#      commands and never rolls back: a wrong rollback (an old release on a newer database, a step failing
#      half-way) is worse than waiting for Jay (Q220), who follows the runbook.
# It never deletes anything and never touches herdr or any agent.
set -Eeuo pipefail

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
HEAD_SHA="$(git rev-parse HEAD)"
# What is live is what ccd serves: deploy-web.sh names each UI release <stamp>-<rev>[-dirty] from the commit it
# was built at, and ccd was restarted on that same commit. It is used only to list commits and to label the log;
# it is never a rollback target, because go-live prints no rollback commands (CC-063, Q220).
WEB="${CCD_WEB_DIR:-$HOME/.local/share/command-center/web}"
PREV_LINK="$(readlink "$WEB/current" 2>/dev/null || true)"
PREV_SHA=""
PREV_WEB_NAME=""
if [ -n "$PREV_LINK" ]; then
  case "$PREV_LINK" in /*) prev_dir="$PREV_LINK" ;; *) prev_dir="$WEB/$PREV_LINK" ;; esac
  prev_rev="$(basename "$PREV_LINK" | cut -s -d- -f2)"
  if [ -n "$prev_rev" ] && [ -f "$prev_dir/index.html" ]; then
    PREV_SHA="$(git rev-parse -q --verify "$prev_rev^{commit}" 2>/dev/null || true)"
    [ -z "$PREV_SHA" ] || PREV_WEB_NAME="$(basename "$PREV_LINK")"
  fi
fi
if [ -z "$PREV_SHA" ]; then
  echo "note: no previous release is recorded ($WEB/current names no commit this checkout has, or no index.html)"
elif [ "$PREV_SHA" != "$HEAD_SHA" ]; then
  echo "note: the checkout is at ${HEAD_SHA:0:12} but live is ${PREV_SHA:0:12}; commit lists use live"
fi
safe="$(echo "$BRANCH" | tr '/' '-')"
backup="$BACKUPS/tasks.db.pre-$safe-<stamp>"

# The one rollback text go-live ever prints: a pointer, never commands. Which steps are safe depends on the schema
# the old release supports and on rows written since, which a script cannot judge (Q220). Never "cp <backup>
# tasks.db": it loses every row written since go-live (Q182).
RUNBOOK="$REPO/docs/runbooks/tasks-db-v10-rollback.md"
rollback_text() {
  echo "Rollback: nothing was rolled back and go-live prints no rollback commands. If Jay decides to go back, follow"
  echo "  $RUNBOOK (newer migrations add a docs/runbooks/tasks-db-vN-rollback.md page to it)."
  echo "  The tasks.db backup is $backup; never copy it over tasks.db (it loses rows written since go-live)."
}

echo "== fetch $BRANCH"
git fetch -q origin "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
TARGET="$(git rev-parse "origin/$BRANCH")"
echo "== deploying $BRANCH @ $TARGET"
if [ "$BRANCH" != main ]; then
  echo "!! NOT main: $BRANCH has not been reviewed for release (--i-know given)"
fi
if [ -n "$PREV_SHA" ]; then
  log="$(git log --oneline "$PREV_SHA..origin/$BRANCH")"
  echo "${log:-(already at target)}"
  leaving="$(git log --oneline "origin/$BRANCH..$PREV_SHA")"
else
  echo "(no previous release is recorded: cannot list the new commits)"
  leaving=""
fi
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

# What the old ccd reports now (read only): its herdr state and process id. Unknown stays unknown (CC-063).
jget() {
  python3 -I -c 'import json, sys
try:
    d = json.load(sys.stdin)
    for k in sys.argv[1:]:
        d = d[k]
    print(str(d).lower() if isinstance(d, bool) else d)
except Exception:
    pass' "$@"
}
OLD_HEALTH="$(curl -fsS --max-time 5 -H "Host: 127.0.0.1:$PORT" "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true)"
OLD_HERDR="$(printf '%s' "$OLD_HEALTH" | jget herdr ok)"
case "$OLD_HERDR" in true|false) ;; *) OLD_HERDR=unknown ;; esac
OLD_PID="$(systemctl --user show ccd -p MainPID --value 2>/dev/null || true)"
case "$OLD_PID" in ""|*[!0-9]*) OLD_PID=0 ;; esac

# From here on the checkout, the UI or ccd may be half changed. A failing step must say where it stopped and point at
# the runbook, not just exit (before CC-063 set -e left no text at all). Nothing is rolled back for you.
STEPS="$(mktemp)"
trap 'rm -f "$STEPS"' EXIT
STEP="switch to $BRANCH"
rollback_text > "$STEPS"
on_err() {
  local rc=$?
  trap - ERR
  echo "go-live stopped at: $STEP (exit $rc). Nothing was rolled back." >&2
  cat "$STEPS" >&2
  echo "go-live: do not record deployed as pass" >&2
  exit 1
}
trap on_err ERR

echo "== switch to $BRANCH"
if git show-ref -q --verify "refs/heads/$BRANCH"; then
  git switch -q "$BRANCH"
  git merge -q --ff-only "origin/$BRANCH"
else
  git switch -q -c "$BRANCH" --track "origin/$BRANCH"
fi
echo "   now at $(git rev-parse --short HEAD)"

STEP="server requirements"
echo "== server requirements"
server/.venv/bin/pip install -q -r server/requirements.txt

STEP="UI release"
echo "== UI release"
scripts/deploy-web.sh
NEW_LINK="$(readlink "$WEB/current" 2>/dev/null || true)"
case "$NEW_LINK" in /*) NEW_DIR="$NEW_LINK" ;; *) NEW_DIR="$WEB/$NEW_LINK" ;; esac

STEP="Windows launcher"
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

STEP="Claude skills"
echo "== Claude skills (/night-shift, /ui-test) and the AskUserQuestion hook"
scripts/install-claude-commands.sh | sed 's/^/   /'

STEP="restart ccd"
echo "== restart ccd"
# A failing restart no longer aborts: the release check below sees an inactive unit and reports it with the steps.
# The failure is kept: a later healthy-looking sample must not turn it into exit 0 (Codex r3).
RESTART_FAILED=0
systemctl --user restart ccd || { RESTART_FAILED=1; echo "go-live: systemctl restart ccd failed; the release check still runs" >&2; }

# The release check watches ~3 minutes and changes nothing (CC-063). Run go-live under the 10-minute Bash limit.
STEP="release check"
echo "== release check (about 3 minutes; it changes nothing)"
check_rc=0
if [ -z "$NEW_LINK" ] || [ ! -f "$NEW_DIR/index.html" ]; then
  echo "go-live: the release check cannot run: $WEB/current names no UI release with an index.html" >&2
  cat "$STEPS" >&2
  check_rc=2
else
  python3 -I "$REPO/server/ccd/release_check.py" --port "$PORT" --new-dir "$NEW_DIR" --steps-file "$STEPS" \
    --log-file "$HOME/command-center/deploys/commandcenter/releases.jsonl" \
    --token-file "${CCD_TOKEN_FILE:-$HOME/.config/command-center/ccd.token}" \
    --from "$PREV_SHA" --to "$(git rev-parse HEAD)" --web "$(basename "$NEW_LINK")" --prev-web "$PREV_WEB_NAME" \
    --old-pid "$OLD_PID" --herdr-ok "$OLD_HERDR" || check_rc=$?
  # 0, 3, 4 and 5 are the checker's own verdicts. Anything else (no python3, a missing or broken file, a crash) means
  # no verdict at all: say so and point at the runbook instead of passing a stray 1 or 127 through.
  case "$check_rc" in
    0|3|4|5) ;;
    *) echo "go-live: the release check could not run (exit $check_rc)" >&2; cat "$STEPS" >&2; check_rc=2 ;;
  esac
fi
trap - ERR
if [ "$check_rc" -ne 0 ]; then
  echo "go-live: release check exit $check_rc (3 failed, 4 inconclusive, 5 healthy but not logged, 2 could not run): do not record deployed as pass" >&2
  exit "$check_rc"
fi
if [ "$RESTART_FAILED" = 1 ]; then
  echo "go-live: the restart of ccd failed earlier although the check looked healthy: do not record deployed as pass" >&2
  cat "$STEPS" >&2
  exit 1
fi

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
