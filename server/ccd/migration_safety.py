"""Migration safety for tasks.db: a rehearsal of the newest migration (v11) on a copy, and the way back. Never imported by the
daemon; it adds no route.

    python -m ccd.migration_safety drill --snapshot COPY.db --out DIR [--old-ccd OLD_CHECKOUT/server]
                                         [--redact --label "where the snapshot came from"] [--clean]
    python -m ccd.migration_safety rollback --db tasks.db --to 10 --backup-dir DIR       (stop ccd first)
    python -m ccd.migration_safety export-onboarding --db tasks.db --out FILE.json       (read-only; ccd may run)

drill     Works only on copies it makes inside DIR. The snapshot is opened read-only and never written; make it with
          `sqlite3 tasks.db ".backup COPY.db"`. Writes drill.json and drill.md, and exits 0 when every check passes,
          1 when one fails, 2 when it cannot run. The checks:
            backup    SQLite's online backup of the snapshot holds exactly the same rows in every table
            upgrade   v10 -> v11 adds exactly the tables migration 11 adds (identity_tokens, identity_observations)
                      and their indexes and triggers; every existing
                      table, row, index and trigger is unchanged; integrity, foreign keys and the audit hash chain
                      still check; reopening applies nothing; ccd reads the upgraded file
            old ccd   a v10 ccd refuses the v11 file and changes nothing (in process; with --old-ccd, also a real
                      older checkout in its own process)
            rollback  v11 -> v10 in place, after new work was written at v11: the schema is exactly v10 again, the new
                      work is kept, and a v10 ccd opens it; it refuses, changing nothing, when a table migration 11
                      added holds a row
            restore   copying the backup back gives the snapshot's rows exactly, and a v10 ccd opens it
            recovery  a migration interrupted part-way, or whose process is killed part-way (with uncommitted pages
                      already in the write-ahead log), leaves v10 exactly; killed straight after its commit leaves v11
                      complete; either way the next start finishes the job
          --redact  the report names no path, host or user: the snapshot is shown by --label, folders as <out>,
                    <older checkout> and ~, and each detail is cut to 300 characters. It never holds row contents.
          --clean   deletes the database copies in DIR after the run (they hold the snapshot's data); the
                    reports stay.
          An older snapshot is lifted to the drill's starting version on the copy first, and the report says so.
export-onboarding  Writes every row of the four onboarding tables (migration 10) to a JSON file with its SHA-256, through a
          read-only connection, so the records are kept outside the database before a backup is restored over them
          (docs/runbooks/tasks-db-v10-rollback.md, docs/runbooks/tasks-db-v11-rollback.md). It changes nothing.
rollback  Takes a backup with SQLite's backup API, then runs tasks.downgrade(): it drops only tables a migration added,
          only when they are empty, in one transaction, and checks the result is exactly the older schema.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time

from . import tasks

# The drill rehearses the newest migration, one step. v10's drill (onboarding tables) passed on 2026-10-24.
TO = tasks.SCHEMA_VERSION
FROM = TO - 1
ONBOARDING = 10                     # the migration whose tables export-onboarding copies
# A row in a table migration TO adds, to show the rollback refuses to drop history. A new migration adds its own
# entry here (the drill fails loudly with a KeyError until it does).
HISTORY_ROW = {
    10: ("INSERT INTO onboarding_drafts (id, kind, state, body, body_sha, revision, created_at, created_by, updated_at) "
         "VALUES ('d-000000000001', 'agent', 'open', '{}', ?, 1, 0, 'jay', 0)", ("0" * 64,)),
    11: ("INSERT INTO identity_tokens (kind, subject, token_sha, issued_at, issued_by, expires_at) "
         "VALUES ('agent', 'agent:drill', ?, 0, 'jay', 1)", ("0" * 64,)),
}
# The areas Jay asked to see (2026-10-23), in report order.
AREAS = (("backup", "Backup"), ("upgrade", f"v{FROM} -> v{TO} migration and schema integrity"),
         ("old ccd", "Backward compatibility"), ("rollback", "Rollback"), ("restore", "Restore"),
         ("recovery", "Crash recovery"))
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Run in a child process with -I: open a tasks.db the way TaskStore does and migrate it, with a kill point.
_CHILD = r"""
import os, sqlite3, sys
sys.path.insert(0, sys.argv[1])
from ccd import tasks
path, mode = sys.argv[2], sys.argv[3]
db = sqlite3.connect(path, isolation_level=None)
db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL"); db.execute("PRAGMA foreign_keys=ON")
db.execute("PRAGMA cache_size=1")      # spill uncommitted pages into the WAL: the hard case for recovery
if mode == "mid":
    at, n = int(sys.argv[4]), [0]
    def tick():
        if db.in_transaction:
            n[0] += 1
            if n[0] >= at:
                os._exit(137)          # no rollback, no close: as if the power went
        return 0
    db.set_progress_handler(tick, 1)
    tasks.migrate(db)
    os._exit(3)                        # finished before the kill point
tasks.migrate(db)
os._exit(137)                          # killed straight after the commit
"""

# Run in a child process with -I against an OLDER checkout's server/ directory: what that ccd does with a file.
_OLD = r"""
import json, sqlite3, sys
sys.path.insert(0, sys.argv[1])
from ccd import tasks
db = sqlite3.connect(sys.argv[2], isolation_level=None)
try:
    applied = tasks.migrate(db)
    n = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    print(json.dumps({"opened": True, "schema": tasks.SCHEMA_VERSION, "applied": applied, "tickets": n}))
except RuntimeError as e:
    print(json.dumps({"opened": False, "schema": tasks.SCHEMA_VERSION, "error": str(e)}))
"""


class DrillError(Exception):
    """The drill cannot run (exit 2)."""


def connect(path):
    """The way TaskStore opens tasks.db."""
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def version(db):
    return db.execute("PRAGMA user_version").fetchone()[0]


def tables(db):
    return sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                           "AND name NOT LIKE 'sqlite_stat%'"))


def digests(db):
    """{table: sha256 of every row, in a fixed order}. Equal digests mean equal contents."""
    out = {}
    for t in tables(db):
        cols = len(db.execute(f'SELECT * FROM "{t}" LIMIT 0').description)
        order = ", ".join(str(i) for i in range(1, cols + 1))
        h = hashlib.sha256()
        n = 0
        for row in db.execute(f'SELECT * FROM "{t}" ORDER BY {order}'):
            h.update(repr(row).encode())
            n += 1
        out[t] = f"{n}:{h.hexdigest()[:16]}"
    return out


def audit(db):
    if "audit_events" not in tables(db):
        return {"ok": None, "checked": 0}
    from .audit import Audit
    r = Audit(db).verify(full=True)
    return {"ok": r.get("ok"), "checked": r.get("checked")}


def copy(src, dst):
    """SQLite's online backup API, from a read-only source. Replaces dst."""
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dst + suffix):
            os.remove(dst + suffix)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def checked(db):
    return (db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            and not db.execute("PRAGMA foreign_key_check").fetchall())


def _child(code, *args, timeout=60):
    return subprocess.run([sys.executable, "-I", "-c", code, *args], capture_output=True, text=True, timeout=timeout)


def _refusal(fn, kind=RuntimeError):
    """The message when fn() raises `kind`, else None."""
    try:
        fn()
    except kind as e:
        return str(e) or type(e).__name__
    return None


def old_ccd(old_server, path):
    """What an older checkout's ccd does with this file, in its own process."""
    r = _child(_OLD, os.path.abspath(old_server), path)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"opened": None, "error": (r.stderr or r.stdout).strip()[-400:]}


class Drill:
    def __init__(self, snapshot, out, old_server=None):
        self.snapshot = os.path.abspath(snapshot)
        self.out = os.path.abspath(out)
        self.old_server = old_server
        self.checks = []

    def path(self, name):
        return os.path.join(self.out, name)

    def check(self, area, name, ok, detail=None):
        self.checks.append({"area": area, "check": name, "ok": bool(ok), "detail": detail})
        return ok

    def prepare(self):
        if not os.path.isfile(self.snapshot):
            raise DrillError(f"no snapshot at {self.snapshot}")
        wal = self.snapshot + "-wal"
        if os.path.exists(wal) and os.path.getsize(wal) > 0:
            raise DrillError("the snapshot has an unmerged write-ahead log (is ccd using it?); make a copy with "
                             "sqlite3 tasks.db \".backup COPY.db\"")
        if os.path.commonpath([self.snapshot, self.out]) == self.out:
            raise DrillError("the snapshot is inside the output folder; choose another --out")
        os.makedirs(self.out, exist_ok=True)
        snap = sqlite3.connect(f"file:{self.snapshot}?mode=ro&immutable=1", uri=True)
        try:
            v = version(snap)
        finally:
            snap.close()
        if v > FROM:
            raise DrillError(f"the snapshot is schema v{v}; the drill rehearses v{FROM} -> v{TO} on a v{FROM} copy")
        base = self.path("baseline.db")
        copy(self.snapshot, base)
        db = connect(base)
        try:
            lifted = tasks.migrate(db, [m for m in tasks.MIGRATIONS if m[0] <= FROM])
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
        return v, lifted

    def run(self):
        started = time.time()
        snap_version, lifted = self.prepare()
        db = connect(self.path("baseline.db"))
        self.d0, self.s0, self.a0 = digests(db), tasks.schema_objects(db), audit(db)
        self.tickets = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        db.close()
        self.older = [m for m in tasks.MIGRATIONS if m[0] <= FROM]
        self.added = tasks.reference_schema(TO) - tasks.reference_schema(FROM)
        self.ms, self.first = None, None
        rows = sum(int(v.split(":")[0]) for v in self.d0.values())
        for area, step in (("backup", self.backup), ("upgrade", self.upgrade), ("old ccd", self.old),
                           ("rollback", self.rollback), ("restore", self.restore), ("recovery", self.recovery)):
            try:
                step()
            except Exception as e:                     # an area that cannot finish is a failed check, not a crash
                self.check(area, "the area ran to the end", False, f"{type(e).__name__}: {e}")
        ok = all(c["ok"] for c in self.checks)
        return {"result": "PASS" if ok else "FAIL", "at": started, "seconds": round(time.time() - started, 2),
                "snapshot": {"path": self.snapshot, "schema": snap_version, "lifted": lifted, "liftedTo": FROM, "tables": len(self.d0),
                             "rows": rows, "tickets": self.tickets, "auditChain": self.a0},
                "upgradeMs": self.ms, "oldCcd": self.old_server, "checks": self.checks}

    def backup(self):
        copy(self.path("baseline.db"), self.path("backup.db"))
        db = connect(self.path("backup.db"))
        rows = sum(int(v.split(":")[0]) for v in self.d0.values())
        self.check("backup", "the backup holds exactly the snapshot's rows in every table", digests(db) == self.d0,
                   f"{len(self.d0)} tables, {rows} rows")
        self.check("backup", "the backup has the same schema and passes integrity and foreign-key checks",
                   tasks.schema_objects(db) == self.s0 and version(db) == FROM and checked(db))
        db.close()

    def upgrade(self):
        up = self.path("upgraded.db")
        copy(self.path("baseline.db"), up)
        db = connect(up)
        t0 = time.perf_counter()
        applied = tasks.migrate(db)
        self.ms = round((time.perf_counter() - t0) * 1000, 1)
        self.check("upgrade", f"v{FROM} -> v{TO} applies migration {TO} only", applied == [TO], f"{self.ms} ms")
        now = tasks.schema_objects(db)
        self.check("upgrade", "every existing table, index and trigger is unchanged", self.s0 <= now)
        own = set(tasks.DOWNGRADES[TO])
        self.check("upgrade", f"it adds only migration {TO}'s tables and their own indexes and triggers",
                   now - self.s0 == self.added and all(o[2] in own for o in now - self.s0),
                   sorted(f"{o[0]} {o[1]}" for o in now - self.s0 if o[2] not in own)
                   or sorted(o[1] for o in now - self.s0 if o[0] == "table"))
        d1 = digests(db)
        self.check("upgrade", "every existing row is unchanged", {t: d1.get(t) for t in self.d0} == self.d0)
        self.check("upgrade", "the new tables are empty",
                   all(d1.get(t, "").startswith("0:") for t in tasks.DOWNGRADES[TO]))
        a1 = audit(db)
        self.check("upgrade", "integrity, foreign keys and the audit hash chain check as before",
                   checked(db) and a1 == self.a0, a1)
        db.close()
        db = connect(up)
        self.check("upgrade", "reopening applies nothing", tasks.migrate(db) == [])
        db.close()
        ts = tasks.TaskStore(up, ())
        try:
            n = ts.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            first = ts.db.execute("SELECT key FROM tickets ORDER BY id LIMIT 1").fetchone()
            self.check("upgrade", "this ccd opens the upgraded file and reads every ticket",
                       ts.applied == [] and n == self.tickets, f"{n} tickets")
            if first:                                    # new work done after the upgrade, which a rollback must keep
                ts.comment(first[0], f"migration drill: written at v{TO}, kept by the rollback", "jay")
                self.first = first[0]
        finally:
            ts.close()

    def old(self):
        db = connect(self.path("upgraded.db"))
        before = digests(db)
        refused = _refusal(lambda: tasks.migrate(db, self.older))
        self.check("old ccd", f"a v{FROM} ccd refuses the v{TO} file", refused, refused or "it opened it")
        self.check("old ccd", "and changes nothing", digests(db) == before and version(db) == TO)
        db.close()
        if self.old_server:
            r = old_ccd(self.old_server, self.path("upgraded.db"))
            self.check("old ccd", f"the older checkout, in its own process, refuses the v{TO} file",
                       r.get("opened") is False and r.get("schema") == FROM, r)

    def rollback(self):
        rb = self.path("rolled-back.db")
        copy(self.path("upgraded.db"), rb)
        db = connect(rb)
        after_work = digests(db)
        refused = _refusal(lambda: tasks.downgrade(db, FROM))
        d2 = digests(db)
        self.check("rollback", f"v{TO} -> v{FROM} in place leaves exactly the v{FROM} schema",
                   not refused and version(db) == FROM and tasks.schema_objects(db) == self.s0, refused or None)
        self.check("rollback", f"every row is kept, including work written at v{TO}",
                   d2 == {t: after_work[t] for t in self.d0} and (not self.first or d2 != self.d0),
                   f"one comment written at v{TO} is still there" if self.first else "no ticket to write to")
        self.check("rollback", "integrity and the audit hash chain check",
                   checked(db) and audit(db)["ok"] == self.a0["ok"])
        self.check("rollback", f"a v{FROM} ccd opens it", not _refusal(lambda: tasks.migrate(db, self.older)))
        db.close()
        if self.old_server:
            r = old_ccd(self.old_server, rb)
            self.check("rollback", "the older checkout, in its own process, opens it and reads every ticket",
                       r.get("opened") is True and r.get("applied") == [] and r.get("tickets") == self.tickets, r)
        again = self.path("re-upgraded.db")
        copy(rb, again)
        db = connect(again)
        self.check("rollback", "upgrading again works", tasks.migrate(db) == ([TO] if not refused else []) and checked(db)
                   and not refused)
        db.close()
        held = self.path("held.db")
        copy(self.path("upgraded.db"), held)
        db = connect(held)
        db.execute(*HISTORY_ROW[TO])
        before = digests(db)
        refused = _refusal(lambda: tasks.downgrade(db, FROM))
        self.check("rollback", f"it refuses when a table migration {TO} added holds a row, and changes nothing",
                   refused and digests(db) == before and version(db) == TO, refused or "it dropped history")
        db.close()

    def restore(self):
        restored = self.path("restored.db")
        copy(self.path("upgraded.db"), restored)         # the file a restore would replace
        copy(self.path("backup.db"), restored)
        db = connect(restored)
        self.check("restore", "restoring the backup gives the snapshot's rows exactly",
                   digests(db) == self.d0 and tasks.schema_objects(db) == self.s0 and version(db) == FROM)
        self.check("restore", f"a v{FROM} ccd opens it, and this ccd upgrades it again",
                   tasks.migrate(db, self.older) == [] and tasks.migrate(db) == [TO] and checked(db))
        db.close()

    def recovery(self):
        base = self.path("baseline.db")
        ticks = self._ticks(base)
        cut = self.path("interrupted.db")
        copy(base, cut)
        db = connect(cut)
        n = [0]

        def stop():
            if db.in_transaction:
                n[0] += 1
                return 1 if n[0] >= ticks // 2 else 0
            return 0
        db.set_progress_handler(stop, 1)
        interrupted = _refusal(lambda: tasks.migrate(db), sqlite3.DatabaseError)
        db.close()                                       # ccd stops when its start fails
        self.check("recovery", f"a migration interrupted part-way leaves v{FROM} exactly",
                   interrupted and self._is_base(cut), interrupted or "it was not interrupted")
        self.check("recovery", "and the next start finishes it", self._finishes(cut))

        killed = self.path("killed-mid.db")
        copy(base, killed)
        r = _child(_CHILD, SERVER_DIR, killed, "mid", str(ticks // 2))
        wal = os.path.getsize(killed + "-wal") if os.path.exists(killed + "-wal") else 0
        self.check("recovery", f"its process killed part-way, with uncommitted pages in the WAL, leaves v{FROM} exactly",
                   r.returncode == 137 and self._is_base(killed), f"exit {r.returncode}, WAL {wal} bytes")
        self.check("recovery", "and the next start finishes it", self._finishes(killed))

        done = self.path("killed-after.db")
        copy(base, done)
        r = _child(_CHILD, SERVER_DIR, done, "after")
        db = connect(done)
        self.check("recovery", f"killed straight after its commit leaves v{TO} complete",
                   r.returncode == 137 and version(db) == TO and tasks.schema_objects(db) == self.s0 | self.added
                   and {t: v for t, v in digests(db).items() if t in self.d0} == self.d0 and checked(db),
                   f"exit {r.returncode}")
        self.check("recovery", "and the next start applies nothing", tasks.migrate(db) == [])
        db.close()

    def _ticks(self, base):
        """How many progress callbacks the migration makes inside its transaction, on a scratch copy."""
        scratch = self.path("scratch.db")
        copy(base, scratch)
        db = connect(scratch)
        n = [0]

        def count():
            if db.in_transaction:
                n[0] += 1
            return 0
        db.set_progress_handler(count, 1)
        tasks.migrate(db)
        db.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(scratch + suffix):
                os.remove(scratch + suffix)
        return max(n[0], 2)

    def _is_base(self, path):
        db = connect(path)
        try:
            return version(db) == FROM and tasks.schema_objects(db) == self.s0 and digests(db) == self.d0 and checked(db)
        finally:
            db.close()

    @staticmethod
    def _finishes(path):
        db = connect(path)
        try:
            return tasks.migrate(db) == [TO] and checked(db) and tasks.migrate(db) == []
        finally:
            db.close()


def _git_head(path):
    """The commit a checkout is at, or None. Read-only."""
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()[:40] or None


def redacted(report, out, old_server=None, label=None):
    """The same report with no path, host or user in it, for sharing. Row contents are never in a report."""
    names = []
    for path, name in ((report["snapshot"]["path"], label or "<snapshot>"), (out, "<out>"),
                       (old_server, "<older checkout>"), (SERVER_DIR, "<this checkout>")):
        if path:
            for p in {os.path.abspath(path), os.path.realpath(path)}:
                names.append((p, name))
    names.sort(key=lambda x: -len(x[0]))                 # longest first, so a folder never hides a file inside it
    home = os.path.expanduser("~")

    def clean(v):
        if isinstance(v, str):
            for p, name in names:
                v = v.replace(p, name)
            if home and home != "/":
                v = v.replace(home, "~")
            return v[:300]
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v
    r = clean(json.loads(json.dumps(report)))
    r["snapshot"]["path"] = label or "<snapshot>"
    r["oldCcd"] = "<older checkout>" if old_server else None
    r["redacted"] = True
    return r


def markdown(report):
    s = report["snapshot"]
    lines = [f"# Migration v{TO} drill: {report['result']}", "",
             f"Snapshot: {s['path']}. Schema v{s['schema']}"
             + (f" (lifted to v{FROM} on the copy: {s['lifted']})" if s["lifted"] else "")
             + f", {s['tables']} tables, {s['rows']} rows, {s['tickets']} tickets. Upgrade took {report['upgradeMs']} ms. "
             f"Older checkout: {report['oldCcd'] or 'not given'}"
             + (f" at {report['oldCcdCommit']}" if report.get("oldCcdCommit") else "") + ".",
             "",
             f"Drill code {report.get('codeCommit') or 'unknown'}; Python {report.get('python')}, "
             f"SQLite {report.get('sqlite')}; {report['seconds']} s"
             + ("; redacted: no paths, hosts, users or row contents" if report.get("redacted") else "") + ".", "",
             "| Area | Result | Checks passed |", "|---|---|---|"]
    for key, name in AREAS:
        mine = [c for c in report["checks"] if c["area"] == key]
        ok = mine and all(c["ok"] for c in mine)
        lines.append(f"| {name} | {'PASS' if ok else '**FAIL**'} | {sum(c['ok'] for c in mine)} of {len(mine)} |")
    lines += ["", "| Area | Check | Result | Detail |", "|---|---|---|---|"]
    for c in report["checks"]:
        detail = c["detail"] if isinstance(c["detail"], str) else json.dumps(c["detail"]) if c["detail"] is not None else ""
        lines.append(f"| {c['area']} | {c['check']} | {'pass' if c['ok'] else '**FAIL**'} | {detail.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def drill(snapshot, out, old_server=None, redact=False, label=None, clean=False):
    report = Drill(snapshot, out, old_server).run()
    report.update(codeCommit=_git_head(SERVER_DIR), oldCcdCommit=_git_head(old_server) if old_server else None,
                  python=sys.version.split()[0], sqlite=sqlite3.sqlite_version)
    if redact:
        report = redacted(report, out, old_server, label)
    elif label:
        report["snapshot"]["label"] = label
    with open(os.path.join(out, "drill.json"), "w") as f:
        json.dump(report, f, indent=2)
    with open(os.path.join(out, "drill.md"), "w") as f:
        f.write(markdown(report))
    if clean:                                            # the copies hold the snapshot's data; the reports do not
        for name in os.listdir(out):
            if name.endswith((".db", ".db-wal", ".db-shm", ".db-journal")):
                os.remove(os.path.join(out, name))
    return report


def rollback(path, target, backup_dir, clock=time.time):
    """Back up, then undo additive migrations in place. Returns (backup path, versions undone)."""
    if not os.path.isfile(path):
        raise RuntimeError(f"no tasks.db at {path}")
    os.makedirs(backup_dir, exist_ok=True)
    db = connect(path)
    try:
        current = version(db)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
        backup = os.path.join(backup_dir, f"tasks.db.pre-rollback-v{current}-to-v{target}-{stamp}")
        b = sqlite3.connect(backup)
        try:
            db.backup(b)
        finally:
            b.close()
        return backup, tasks.downgrade(db, target)
    finally:
        db.close()


def export_onboarding(path, out):
    """Every onboarding row as JSON, read-only. Returns {table: rows} counts and the file's SHA-256."""
    if not os.path.isfile(path):
        raise RuntimeError(f"no tasks.db at {path}")
    if os.path.exists(out):
        raise RuntimeError(f"{out} exists; choose a new file")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if version(db) < ONBOARDING:
            raise RuntimeError(f"tasks.db is schema v{version(db)}; it has no onboarding tables")
        data = {}
        for t in reversed(tasks.DOWNGRADES[ONBOARDING]):  # oldest table first
            cur = db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')
            cols = [c[0] for c in cur.description]
            data[t] = [dict(zip(cols, row)) for row in cur]
    finally:
        db.close()
    body = json.dumps({"schema": ONBOARDING, "tables": data}, indent=2, sort_keys=True).encode()
    with open(out, "xb") as f:
        f.write(body)
    return {t: len(rows) for t, rows in data.items()}, hashlib.sha256(body).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ccd.migration_safety", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drill", help=f"rehearse migration v{TO} on a copy")
    d.add_argument("--snapshot", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--old-ccd", help="an older checkout's server/ directory, to run its ccd against the files")
    d.add_argument("--redact", action="store_true", help="no paths, hosts or users in the report")
    d.add_argument("--label", help="how the report names the snapshot, e.g. 'live tasks.db, backup 2026-10-23T14:30Z'")
    d.add_argument("--clean", action="store_true", help="delete the database copies after the run; keep the reports")
    r = sub.add_parser("rollback", help="undo additive migrations in place (stop ccd first)")
    r.add_argument("--db", required=True)
    r.add_argument("--to", type=int, required=True)
    r.add_argument("--backup-dir", required=True)
    e = sub.add_parser("export-onboarding", help="copy the onboarding records to a JSON file (read-only)")
    e.add_argument("--db", required=True)
    e.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "export-onboarding":
        try:
            counts, sha = export_onboarding(a.db, a.out)
        except RuntimeError as err:
            print(f"export refused: {err}", file=sys.stderr)
            return 1
        print(f"exported: {', '.join(f'{t} {n}' for t, n in counts.items())}\nsha256: {sha}\nfile: {a.out}")
        return 0
    if a.cmd == "drill":
        try:
            report = drill(a.snapshot, a.out, a.old_ccd, redact=a.redact, label=a.label, clean=a.clean)
        except DrillError as e:
            print(f"migration drill: {e}", file=sys.stderr)
            return 2
        print(markdown(report))
        return 0 if report["result"] == "PASS" else 1
    try:
        backup, undone = rollback(a.db, a.to, a.backup_dir)
    except RuntimeError as e:
        print(f"rollback refused: {e}", file=sys.stderr)
        return 1
    print(f"backup: {backup}\nundone: {', '.join(f'v{v}' for v in undone)}; tasks.db is v{a.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
