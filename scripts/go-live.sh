#!/usr/bin/env bash
# go-live.sh — switch the LIVE Command Center (127.0.0.1:7777) to origin/main, safely, in one step.
#
#   scripts/go-live.sh [--dry-run] [--branch <name> --i-know]
#   scripts/go-live.sh --result                   # read-only: the verdict of the newest release watch (CC-063)
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
#   7. links Claude's /night-shift and /ui-test skills into ~/.claude/skills and sets the AskUserQuestion hook in
#      ~/.claude/settings.json (scripts/install-claude-commands.sh)
#   8. restarts ccd (which applies any additive tasks.db migration)
#   9. starts the release watch (server/ccd/release_watch.py, its own systemd user unit, run from a copy) and waits
#      for its verdict. The watch checks the new release for 5 minutes and, if it is bad, puts the previous one
#      back by itself (CC-063). Exit codes: 0 healthy, 3 rolled back, 4 rollback failed, 5 no previous release,
#      6 still watching (run --result), 7 not watched. Anything but 0: do not record the ticket deployed.
# and prints the exact manual rollback. It never touches herdr or any agent.
set -euo pipefail

usage() {
  echo "usage: go-live.sh [--dry-run] [--branch <name> --i-know] | --result   (default branch: main, the reviewed release line)" >&2
  exit 2
}
BRANCH=main
DRY_RUN=0
I_KNOW=0
RESULT_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --i-know) I_KNOW=1 ;;
    --result) RESULT_ONLY=1 ;;
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

[ "$RESULT_ONLY" = 0 ] || [ "$DRY_RUN$I_KNOW" = 00 ] || usage
REPO="${CC_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DB="${CCD_DATA_DIR:-$HOME/command-center/data}/tasks.db"
BACKUPS="$HOME/command-center/backups"
PORT="${CCD_PORT:-7777}"
cd "$REPO"

# ---- CC-063: the release watch --------------------------------------------------------------------------------
# After the restart a detached watcher (its own systemd user unit, run from a copy of server/ccd/release_watch.py)
# checks the new release and puts the previous one back if it is bad. This script only starts it and waits for its
# verdict in watch/<stamp>/result.json. The deadline counts from the start of this script because the coordinator's
# Bash tool ends a call after 10 minutes, build included.
DEPLOYS="$HOME/command-center/deploys/commandcenter"
WATCH_ROOT="$DEPLOYS/watch"
DEADLINE="${CC_GOLIVE_DEADLINE_S:-540}"

unit_active() { systemctl --user is-active --quiet "$1" 2>/dev/null; }
jget() {  # jget <file> <key>: a JSON value as text, "" when missing
  python3 -c 'import json,sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2])
    print("" if v is None else v)
except Exception:
    print("")' "$1" "$2"
}
newest_watch() {  # the newest watch dir, "" when there is none
  python3 -c 'import os,sys
r = sys.argv[1]
d = sorted(n for n in os.listdir(r) if os.path.isdir(os.path.join(r, n))) if os.path.isdir(r) else []
print(os.path.join(r, d[-1]) if d else "")' "$1"
}

# Printed by every run, --dry-run too: a rollback Jay was never told about, and a watcher that died without a verdict.
print_notices() {
  [ -d "$WATCH_ROOT" ] || return 0
  python3 - "$WATCH_ROOT" <<'PY'
import json, os, subprocess, sys, time
root = sys.argv[1]
def active(unit):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0
for name in sorted(os.listdir(root)):
    d = os.path.join(root, name)
    if not os.path.isdir(d) or time.time() - os.path.getmtime(d) > 3 * 86400:
        continue
    unit = "cc-release-watch-" + name
    if not os.path.isfile(os.path.join(d, "plan.json")):
        continue   # a go-live that has not reached its watcher yet (or stopped before it): nothing to report
    try:
        res = json.load(open(os.path.join(d, "result.json")))
    except (OSError, ValueError):
        # The 20 s margin: a watch dir is made a moment before its unit starts.
        if time.time() - os.path.getmtime(d) > 20 and not active(unit):
            print(f"!! WATCHER DIED: {name} has no result and its unit is not running. ccd may be stopped: "
                  f"systemctl --user start ccd. Log: {d}/watch.log")
        continue
    if res.get("result") != "healthy" and res.get("notified") is not True and not active(unit):
        print(f"!! UNNOTIFIED: {name} ended {res.get('result')}"
              f"{' at ' + res['step'] if res.get('step') else ''} and Jay was never told in Messages: "
              f"{res.get('message') or 'see ' + d + '/result.json'}")
PY
}

# Turns a verdict into this script's exit code (0, 3, 4, 5) and the words for the coordinator.
exit_for() {
  local dir="$1" res step
  res="$(jget "$dir/result.json" result)"
  step="$(jget "$dir/result.json" step)"
  local rec="Do not record the ticket deployed with pass: python -m ccd.pipeline_cli deployed <KEY> --role coordinator --env live --result fail"
  case "$res" in
    healthy)
      echo "== release watch: healthy ($(jget "$dir/result.json" restarts) restarts; log $dir/watch.log)"
      exit 0 ;;
    rolled_back)
      echo "== ROLLED BACK: the new release failed $(jget "$dir/result.json" check) and the previous release is live again."
      echo "   $(jget "$dir/result.json" message)"
      echo "   Log: $dir/watch.log"
      echo "   $rec"
      exit 3 ;;
    rollback_failed)
      echo "== ROLLBACK FAILED at ${step:-?}: $(jget "$dir/result.json" reason)"
      echo "   $(jget "$dir/result.json" message)"
      echo "   Log: $dir/watch.log; steps: docs/runbooks/go-live-auto-rollback.md"
      echo "   $rec"
      exit 4 ;;
    no_previous)
      echo "== NO PREVIOUS RELEASE: the new release failed $(jget "$dir/result.json" check) and there was nothing to go back to; nothing was changed."
      echo "   Log: $dir/watch.log"
      echo "   $rec"
      exit 5 ;;
    *)
      echo "go-live: $dir/result.json has no usable verdict" >&2
      exit 4 ;;
  esac
}

# One look at a watch: a verdict, still running (6), or a dead watcher. A watcher that died between ccd's stop and
# start leaves ccd stopped (Restart=always does not restart a stopped unit): start it here and say so (4).
check_watch() {
  local dir="$1" unit="cc-release-watch-$(basename "$1")"
  [ -f "$dir/result.json" ] && exit_for "$dir"
  if unit_active "$unit"; then
    echo "== still watching ($unit). Run: scripts/go-live.sh --result"
    exit 6
  fi
  [ -f "$dir/result.json" ] && exit_for "$dir"
  systemctl --user start ccd >/dev/null 2>&1 || true
  printf '{"result":"rollback_failed","step":"watcher_died","reason":"the watcher stopped without a verdict","notified":false,"message":"The release watcher died before reporting; ccd was started again but the release is unchecked."}\n' > "$dir/result.json"
  exit_for "$dir"
}

print_notices

if [ "$RESULT_ONLY" = 1 ]; then
  latest="$(newest_watch "$WATCH_ROOT")"
  [ -n "$latest" ] || { echo "go-live: no release watch found under $WATCH_ROOT" >&2; exit 1; }
  check_watch "$latest"
fi

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

# One go-live at a time, and not while a watch is still running or rolling back: refuse before anything is
# backed up, switched, installed or built. (After the read-only refusals above, so a refused run leaves HOME alone.)
mkdir -p "$WATCH_ROOT"
exec 9>"$DEPLOYS/.go-live.lock"
if ! flock -n 9; then
  echo "go-live: another go-live or release watch holds $DEPLOYS/.go-live.lock; nothing was changed" >&2
  exit 1
fi
busy="$(jget "$WATCH_ROOT/active.json" unit)"
if [ -n "$busy" ] && unit_active "$busy"; then
  echo "go-live: release watch $busy is still running; wait for it (scripts/go-live.sh --result); nothing was changed" >&2
  exit 1
fi

stamp="$(date +%Y%m%dT%H%M%S)"
backup="$BACKUPS/tasks.db.pre-$safe-$stamp"
wdir="$WATCH_ROOT/$stamp"
unit="cc-release-watch-$stamp"
mkdir -p "$wdir"

# Old watch copies and wheels are not kept for ever: the newest 6 stay, a running watch never goes.
python3 - "$WATCH_ROOT" "$stamp" <<'PY'
import os, shutil, sys
root, mine = sys.argv[1], sys.argv[2]
names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and n != mine)
for n in names[:-5]:
    shutil.rmtree(os.path.join(root, n), ignore_errors=True)
PY

# The rollback must not need the network, so both pin sets are downloaded NOW, before anything changes (CC-063).
# If they cannot be, stop here: a go-live whose rollback could not run is not worth starting.
PINS_DIFFER=0
WHEELS_OK=0
git show "$PREV_SHA:server/requirements.txt" > "$wdir/old.req" 2>/dev/null || : > "$wdir/old.req"
git show "origin/$BRANCH:server/requirements.txt" > "$wdir/new.req" 2>/dev/null || : > "$wdir/new.req"
if ! cmp -s "$wdir/old.req" "$wdir/new.req"; then
  PINS_DIFFER=1
  echo "== requirements differ: downloading both pin sets for a rollback that needs no network"
  mkdir -p "$wdir/wheels"
  if server/.venv/bin/pip download -q -r "$wdir/old.req" -d "$wdir/wheels" \
     && server/.venv/bin/pip download -q -r "$wdir/new.req" -d "$wdir/wheels"; then
    cp "$wdir/old.req" "$wdir/wheels/old.txt"
    cp "$wdir/new.req" "$wdir/wheels/new.txt"
    WHEELS_OK=1
  else
    echo "go-live: could not download the wheels a rollback needs; nothing was changed" >&2
    exit 1
  fi
fi

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

# What the rollback must put back, recorded BEFORE anything is switched (CC-063): the exact UI release dir that is
# current (the previous release is not saved anywhere else), the schema version of tasks.db, and whether herdr was
# fine under the old ccd (herdr is not part of a release, so it only counts against the new one if it was ok before).
PREV_WEB=""
if [ -f "$WEB/current/index.html" ]; then
  PREV_WEB="$(readlink -f "$WEB/current")"
fi
PREV_SCHEMA=""
if [ -f "$DB" ]; then
  PREV_SCHEMA="$(python3 - "$DB" <<'PY' 2>/dev/null || true
import sqlite3, sys
db = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
print(db.execute("PRAGMA user_version").fetchone()[0])
PY
)"
fi
HERDR_OK_BEFORE="$(curl -fsS -m 5 -H "Host: 127.0.0.1:$PORT" "http://127.0.0.1:$PORT/api/health" 2>/dev/null | python3 -c '
import json, sys
try:
    ok = json.load(sys.stdin).get("herdr", {}).get("ok")
    print({True: "true", False: "false"}.get(ok, ""))
except Exception:
    print("")' 2>/dev/null || true)"

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

echo "== Claude skills (/night-shift, /ui-test) and the AskUserQuestion hook"
scripts/install-claude-commands.sh | sed 's/^/   /'

echo "== restart ccd"
systemctl --user restart ccd

# CC-063: from here the release watch decides. It replaces the old 30 s "does it answer" loop, which could only
# print a rollback and never checked more than /api/health once.
echo "== start the release watch ($unit)"
NEW_WEB="$(readlink -f "$WEB/current" 2>/dev/null || true)"
NEW_SCHEMA="$(cd server && .venv/bin/python -c 'from ccd import tasks; print(tasks.SCHEMA_VERSION)' 2>/dev/null || true)"
cp "$REPO/server/ccd/release_watch.py" "$wdir/release_watch.py"
STAMP="$stamp" UNIT="$unit" FROM_SHA="$PREV_SHA" TO_SHA="$(git rev-parse HEAD)" PREV_WEB="$PREV_WEB" NEW_WEB="$NEW_WEB" \
  PREV_SCHEMA="$PREV_SCHEMA" NEW_SCHEMA="$NEW_SCHEMA" HERDR_OK_BEFORE="$HERDR_OK_BEFORE" PINS_DIFFER="$PINS_DIFFER" \
  WHEELS_OK="$WHEELS_OK" BACKUP="$backup" python3 - "$wdir/plan.json" <<'PY'
import json, os, sys
e = os.environ
def num(k):
    return int(e[k]) if e.get(k, "").isdigit() else None
json.dump({"stamp": e["STAMP"], "unit": e["UNIT"], "from_sha": e["FROM_SHA"], "to_sha": e["TO_SHA"],
           "prev_web": e["PREV_WEB"], "new_web": e["NEW_WEB"], "prev_schema": num("PREV_SCHEMA"),
           "new_schema": num("NEW_SCHEMA"), "herdr_ok_before": {"true": True, "false": False}.get(e["HERDR_OK_BEFORE"]),
           "pins_differ": e["PINS_DIFFER"] == "1", "wheels_ok": e["WHEELS_OK"] == "1", "backup": e["BACKUP"]},
          open(sys.argv[1], "w"))
PY

watching=0
if systemd-run --user --unit "$unit" --collect --quiet \
     -p "ExecStopPost=$(command -v systemctl) --user start ccd" \
     -p "StandardOutput=append:$wdir/watch.out" -p "StandardError=append:$wdir/watch.out" \
     -E "CCD_PORT=$PORT" -E "CCD_WEB_DIR=$WEB" -E "CCD_DATA_DIR=$(dirname "$DB")" -E "CC_REPO=$REPO" \
     -E "CCD_TOKEN_FILE=${CCD_TOKEN_FILE:-$HOME/.config/command-center/ccd.token}" \
     -E "CCD_HERDR_SOCKET=${CCD_HERDR_SOCKET:-$HOME/.config/herdr/herdr.sock}" \
     -E "HOME=$HOME" -E "PATH=$PATH" \
     "$(command -v python3)" "$wdir/release_watch.py" "$wdir" >/dev/null 2>&1; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if unit_active "$unit" || [ -f "$wdir/result.json" ]; then watching=1; break; fi
    sleep 0.5
  done
fi
if [ "$watching" = 0 ]; then
  echo "== NOT WATCHED: the release watch did not start, so nothing checks this release and nothing rolls it back." >&2
  echo "   ccd was restarted on the new release. Do not record the ticket deployed; tell Jay." >&2
  echo "   Check by hand (curl 127.0.0.1:$PORT/api/health, the UI), and if it is bad:" >&2
  rollback_text >&2
  exit 7
fi
# The watcher takes the lock for its whole run; active.json is written before this script lets go of it, so a second
# go-live is refused from the first moment (it checks both).
python3 -c 'import json,sys,time; json.dump({"unit": sys.argv[2], "until": time.time() + 600}, open(sys.argv[1], "w"))' \
  "$WATCH_ROOT/active.json" "$unit"
exec 9>&-

echo "== watching the release (up to $((DEADLINE - SECONDS)) s more; log $wdir/watch.log)"
while :; do
  if [ -f "$wdir/result.json" ]; then
    [ "$(jget "$wdir/result.json" result)" = healthy ] && break
    exit_for "$wdir"
  fi
  if ! unit_active "$unit"; then
    [ -f "$wdir/result.json" ] && continue   # the verdict landed as the unit ended: read it at the top
    check_watch "$wdir"                      # no verdict, no unit: ccd is started here and this exits 4
  fi
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    echo "== still watching: the release is not judged yet. Run: scripts/go-live.sh --result"
    echo "   Do not record the ticket deployed until it says healthy (exit 0)."
    exit 6
  fi
  sleep 0.5
done
echo "== release watch: healthy (log $wdir/watch.log)"

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
