"""python -m ccd.validation phase1-readiness [--fixtures] [--replay SNAPSHOT.db [--github-cache FILE]]
    [--live URL --token-file FILE] [--evidence FILE] [--restore-backup BACKUP.db] [--engine-live-at ISO]
    [--go-live-at ISO] [--now ISO] --out DIR

Writes DIR/readiness.json and DIR/readiness.md. Exit 0 PASS, 1 FAIL, 2 cannot run.

  --fixtures         the fixture decisions (every sweep class); runs anywhere, also in CI
  --replay           a COPY of tasks.db, opened read-only; a path inside the live data folder is refused
  --github-cache     {pr ref: gh pr view JSON} for the replayed merges (facts read after the fact are marked)
  --live             a running ccd; GET requests only. --token-file holds the ccd token
  --evidence         JSON with what the harness cannot see itself: engineLiveAt, nightShift.cycles,
                     drills.restart / drills.rollback, auditWalks [{when: start|after_restart|end, ok}],
                     suites {commit, green}, restarts, unexplainedExits
  --restore-backup   restore drill: copy this backup to a temporary folder, migrate the copy, check it
                     (row 4 counts only a restore this run did, never one claimed in --evidence)
  --now              the time to score at; never later than the wall clock
  jayLogins          (evidence) GitHub logins that are Jay's, for merges ccd saw on GitHub (default JayDalool)
"""
import argparse
import json
import sys
from pathlib import Path

from . import readiness


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m ccd.validation", description="Phase 1 validation harness")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("phase1-readiness", help="score the Phase 1 graduation gate")
    r.add_argument("--fixtures", action="store_true")
    r.add_argument("--replay")
    r.add_argument("--github-cache")
    r.add_argument("--live")
    r.add_argument("--token-file")
    r.add_argument("--evidence")
    r.add_argument("--restore-backup")
    r.add_argument("--engine-live-at")
    r.add_argument("--go-live-at")
    r.add_argument("--now")
    r.add_argument("--out", required=True)
    a = p.parse_args(argv)
    if not (a.fixtures or a.replay or a.live):
        print("phase1-readiness: give at least one of --fixtures, --replay, --live", file=sys.stderr)
        return 2
    if a.live and not a.live.startswith(("http://", "https://")):
        print("phase1-readiness: --live must be an http(s) URL", file=sys.stderr)
        return 2
    out = Path(a.out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        report = readiness.run({k: getattr(a, k) for k in (
            "fixtures", "replay", "github_cache", "live", "token_file", "evidence", "restore_backup",
            "engine_live_at", "go_live_at", "now", "out")})
    except readiness.CannotRun as e:
        print(f"phase1-readiness: cannot run: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — anything unexpected means no verdict: "cannot run", never FAIL or PASS
        print(f"phase1-readiness: cannot run: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    readiness.write(report, out)
    print(json.dumps({"result": report["result"], "out": str(out),
                      "gate": {r["row"]: r["status"] for r in report["gate"]}}))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
