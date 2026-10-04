"""python -m ccd.import_tasks [--apply] [--db PATH] [--config PATH] [--out report.json]

The one-time import of existing work (INDEX.md rows, task files, open GitHub
issues, MY_ACTIONS.md lines) into tasks.db. Without --apply it is a dry run and
opens the database read-only. With --apply it first copies the database with
SQLite's backup API to `<db>.bak-import-<UTC timestamp>`, prints that path,
then creates the tickets. There is deliberately no HTTP endpoint for this.

GitHub is read once per project with `gh` (read-only); issues are never edited.
"""
import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

from . import config, importer, sources
from .tasks import TaskStore


def backup(db_path):
    """Copy the live database with the backup API (safe while ccd has it open)."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(f"{db_path}.bak-import-{stamp}")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    dest.chmod(0o600)
    return dest


def gather_github(projects, fetch=None):
    """One-shot issue fetch, shaped like the daemon's cache: {project: {"issues": [...]}}."""
    fetch = fetch or sources.github
    out = {}
    for p in projects:
        if not p.get("repo"):
            continue
        data = fetch(p)
        if isinstance(data.get("issues"), list):
            out[p["key"]] = data
        else:
            print(f"warning: no GitHub issues for {p['key']}: {(data.get('issues') or {}).get('error')}",
                  file=sys.stderr)
    return out


def run(db_path, cfg, do_apply, gh_data=None, out=None):
    gh_data = gather_github(cfg["projects"]) if gh_data is None else gh_data
    if do_apply:
        bak = backup(db_path)
        print(f"backup: {bak}", file=sys.stderr)
        store = TaskStore(db_path, config.task_projects(cfg))
        try:
            report = importer.apply(cfg["projects"], gh_data, store)
        finally:
            store.close()
        report["backup"] = str(bak)
    else:
        # read-only: a dry run must not even run migrations on the file
        store = TaskStore(db_path, readonly=True)
        try:
            report = importer.preview(cfg["projects"], gh_data, store)
        finally:
            store.close()
    if out:
        Path(out).write_text(json.dumps(report, indent=2))
        Path(out).chmod(0o600)
    return report


def summary(report):
    keys = ("wouldCreate", "wouldUpdate", "existing", "ambiguous", "duplicates", "skipped") \
        if not report.get("applied") else ("created", "updated", "archived", "existing", "duplicate", "ambiguous",
                                           "skipped")
    s = report.get("summary") or report
    return {k: s.get(k) for k in keys}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ccd.import_tasks", description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="create the tickets (default: dry run)")
    ap.add_argument("--db", default=str(config.DATA_DIR / "tasks.db"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None, help="write the full report here as JSON")
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    report = run(a.db, cfg, a.apply, out=a.out)
    print(json.dumps(summary(report), indent=2))
    if report.get("errors"):
        print(f"errors: {json.dumps(report['errors'])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
