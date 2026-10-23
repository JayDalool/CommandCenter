"""Migration v10 safety (Jay, 2026-10-23: "Before backend merge, demonstrate migration v10 backup, restore, backward
compatibility and recovery testing"). The drill in ccd/migration_safety.py runs every check on a populated v9
database; these tests run it, show it catches a migration that touches existing data, and test the in-place
rollback's refusals."""
import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from ccd import audit, autonomy, identity, ledger, meter, migration_safety as ms, tasks, workers
from ccd.pipeline import Pipeline
from ccd.validation import fixtures

from .helpers import PROJECTS

V9 = [m for m in tasks.MIGRATIONS if m[0] <= 9]


def build_v9(path):
    """A v9 tasks.db written by the v9 code paths, with rows in 20 of its 22 tables."""
    with mock.patch.object(tasks, "MIGRATIONS", V9), mock.patch.object(tasks, "SCHEMA_VERSION", 9):
        ts = tasks.TaskStore(path, PROJECTS)
        pl = Pipeline(ts)
        keys = [ts.create(["samvision", "gyst", "mfe"][i % 3], f"Ticket {i}")[0]["key"] for i in range(9)]
        k = keys[0]
        ts.update(k, {"labels": ["frontend", "p1"]}, "jay")
        ts.comment(k, "Looks right on mobile too.", "jay")
        ts.relate(keys[3], "blocked_by", k, "jay")
        ts.link(k, "github", "pr", "JayDalool/SamVisionAI#12", url="https://github.com/JayDalool/SamVisionAI/pull/12")
        pl.plan(k, {"summary": "Valuation view", "requirements": ["comps"], "approach": "new view",
                    "affected": ["web/valuation.tsx"], "risk": "low", "tests": ["unit"], "questions": []}, "agent:planner")
        pl.start(k, f"{k}-valuation", f"/srv/server/worktrees/sv/{k}", "agent:coordinator")
        pl.ask(k, ["Same layout on mobile?"], "agent:coordinator")
        pl.evidence(k, "screenshot", "mobile-375.png", "narrow screen", "agent:verifier")
        pl.finding(k, {"scope": "in", "category": "ux", "summary": "missing empty state"}, "agent:reviewer")
        tid = ts._id_of(k)
        lg = ledger.Ledger(ts.db)
        lg.add_decision(project="samvision", question="Use MLS comps?", decision="yes", decided_by="jay",
                        source="policy", source_ref="d1")
        lg.request(tid, "samvision", "merge", "PR #12", "needs Jay")
        identity.ActorTokens(ts.db).issue("agent:nova", "jay")
        a = audit.Audit(ts.db)
        for i in range(4):
            a.record(actor="jay", verified=True, via="token", method="POST", path=f"/api/tasks/{k}/comment",
                     status=200, body={"i": i})
        f = fixtures.ready()
        autonomy.Shadow(ts.db).record(tid, "commandcenter", "merge", "jay", autonomy.evaluate("merge", None, f), f, "fp")
        meter.Meter(ts.db, roots=[]).report("step-1", "samvision", k, "agent:nova",
                                            {"model": "claude-sonnet-5-5", "inputTokens": 1200, "outputTokens": 300})
        w = workers.Workers(ts.db, version="test")
        w.register_server("test")
        w.enrol("laptop-1", "laptop", {}, "1.0", "jay")
        w.approve("laptop-1", "jay")
        ts.close()                                   # checkpoints the WAL, like sqlite3 .backup


def tmp(*parts):
    return os.path.join(tempfile.mkdtemp(prefix="migdrill-"), *parts)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ms.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Drill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = tmp("snapshot.db")
        build_v9(cls.snapshot)

    def test_every_check_passes_on_a_populated_v9_database(self):
        out = tmp("drill")
        code, md, _ = run("drill", "--snapshot", self.snapshot, "--out", out)
        with open(os.path.join(out, "drill.json")) as f:
            report = json.load(f)
        failed = [c for c in report["checks"] if not c["ok"]]
        self.assertEqual(failed, [])
        self.assertEqual((code, report["result"]), (0, "PASS"))
        self.assertEqual({c["area"] for c in report["checks"]},
                         {"backup", "upgrade", "old ccd", "rollback", "restore", "recovery"})
        self.assertGreaterEqual(sum(1 for c in report["checks"]), 26)
        self.assertGreaterEqual(report["snapshot"]["rows"], 60)
        self.assertTrue(md.startswith("# Migration v10 drill: PASS"))
        with open(os.path.join(out, "drill.md")) as f:
            self.assertTrue(f.read().startswith("# Migration v10 drill: PASS"))
        snap = sqlite3.connect(self.snapshot)
        self.assertEqual(snap.execute("PRAGMA user_version").fetchone()[0], 9)     # the snapshot is never written
        snap.close()

    def test_a_killed_migration_had_uncommitted_pages_on_disk(self):
        out = tmp("drill")
        report = ms.drill(self.snapshot, out)
        killed = next(c for c in report["checks"] if c["check"].startswith("its process killed part-way"))
        self.assertTrue(killed["ok"], killed)
        self.assertRegex(killed["detail"], r"^exit 137, WAL [1-9]\d* bytes$")   # recovery had something to ignore

    def test_it_fails_a_migration_that_changes_existing_rows_or_tables(self):
        sql = dict(tasks.MIGRATIONS)[10]
        for extra, check in (("UPDATE tickets SET title = title || '!';", "every existing row is unchanged"),
                             ("CREATE INDEX tickets_title ON tickets(title);",
                              "it adds only the onboarding tables and their own indexes and triggers")):
            bad = V9 + [(10, sql + extra)]
            with self.subTest(extra=extra), mock.patch.object(tasks, "MIGRATIONS", bad):
                report = ms.drill(self.snapshot, tmp("drill"))
                self.assertEqual(report["result"], "FAIL")
                self.assertFalse(next(c for c in report["checks"] if c["check"] == check)["ok"])

    def test_a_redacted_report_names_no_path_and_the_copies_can_be_removed(self):
        out = tmp("drill")
        label = "live tasks.db, backup 2026-10-23T14:30Z"
        code, md, _ = run("drill", "--snapshot", self.snapshot, "--out", out, "--redact", "--label", label, "--clean")
        self.assertEqual(code, 0, md)
        with open(os.path.join(out, "drill.json")) as f:
            text = f.read()
        report = json.loads(text)
        for secret in (self.snapshot, os.path.dirname(self.snapshot), out, ms.SERVER_DIR, os.path.expanduser("~")):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, md)
        self.assertEqual((report["redacted"], report["snapshot"]["path"]), (True, label))
        self.assertIn(f"Snapshot: {label}.", md)
        for name in ("Backup", "v9 -> v10 migration and schema integrity", "Backward compatibility", "Rollback",
                     "Restore", "Crash recovery"):
            self.assertRegex(md, rf"\| {name} \| PASS \| (\d+) of \1 \|")
        self.assertEqual(sorted(os.listdir(out)), ["drill.json", "drill.md"])      # no copy of the data is left

    def test_it_will_not_run_on_unsafe_input(self):
        live = tmp("live.db")
        build_v9(live)
        with open(live + "-wal", "wb") as f:                     # a file ccd still has open
            f.write(b"x" * 32)
        v10 = tmp("v10.db")
        tasks.TaskStore(v10, PROJECTS).close()
        out = tmp("out")
        inside = os.path.join(out, "snapshot.db")
        os.makedirs(out)
        build_v9(inside)
        for snapshot, words in ((live, "write-ahead log"), (v10, "schema v10"), (inside, "inside the output folder"),
                                (tmp("missing.db"), "no snapshot")):
            with self.subTest(words=words):
                code, _, err = run("drill", "--snapshot", snapshot, "--out", out)
                self.assertEqual(code, 2)
                self.assertIn(words, err)


class Downgrade(unittest.TestCase):
    def v10(self):
        path = tmp("tasks.db")
        build_v9(path)
        ts = tasks.TaskStore(path, PROJECTS)
        self.assertEqual(ts.applied, [10])
        ts.close()
        return path

    def test_the_downgrade_list_names_exactly_the_tables_migration_10_adds(self):
        added = {o[1] for o in tasks.reference_schema(10) - tasks.reference_schema(9) if o[0] == "table"}
        self.assertEqual(added, set(tasks.DOWNGRADES[10]))

    def test_rollback_backs_up_then_returns_to_v9_keeping_every_row(self):
        path = self.v10()
        ts = tasks.TaskStore(path, PROJECTS)
        key = ts.create("samvision", "written at v10")[0]["key"]
        ts.close()
        db = ms.connect(path)
        before = ms.digests(db)
        db.close()
        code, out, _ = run("rollback", "--db", path, "--to", "9", "--backup-dir", tmp("backups"))
        self.assertEqual(code, 0, out)
        backup = out.split("backup: ")[1].splitlines()[0]
        b = ms.connect(backup)
        self.assertEqual((ms.version(b), ms.digests(b)), (10, before))       # the backup is the file as it was
        b.close()
        db = ms.connect(path)
        self.assertEqual(ms.version(db), 9)
        self.assertEqual(tasks.schema_objects(db), tasks.reference_schema(9))
        self.assertEqual(ms.digests(db), {t: v for t, v in before.items() if t not in tasks.DOWNGRADES[10]})
        self.assertEqual(tasks.migrate(db, V9), [])                           # a v9 ccd opens it
        self.assertIsNotNone(db.execute("SELECT 1 FROM tickets WHERE key=?", (key,)).fetchone())
        db.close()

    def test_it_refuses_and_changes_nothing_when_onboarding_tables_hold_history(self):
        path = self.v10()
        db = ms.connect(path)
        db.execute("INSERT INTO onboarding_events (subject, at, kind, actor) VALUES ('draft:d-1', 0, 'draft_created', "
                   "'jay')")
        before = ms.digests(db)
        db.close()
        code, _, err = run("rollback", "--db", path, "--to", "9", "--backup-dir", tmp("backups"))
        self.assertEqual(code, 1)
        self.assertIn("onboarding_events (1 row)", err)
        db = ms.connect(path)
        self.assertEqual((ms.version(db), ms.digests(db)), (10, before))
        db.close()

    def test_it_refuses_a_schema_it_does_not_recognise(self):
        path = self.v10()
        db = ms.connect(path)
        db.execute("CREATE INDEX local_extra ON tickets(title)")             # a change made by hand at some point
        with self.assertRaisesRegex(RuntimeError, "not exactly v9"):
            tasks.downgrade(db, 9)
        self.assertEqual(ms.version(db), 10)
        self.assertTrue({"agent_registrations", "onboarding_events"} <= set(ms.tables(db)))
        db.close()

    def test_it_refuses_steps_without_a_downgrade_and_targets_that_undo_nothing(self):
        path = self.v10()
        db = ms.connect(path)
        with self.assertRaisesRegex(RuntimeError, "v9 has no in-place downgrade"):
            tasks.downgrade(db, 8)
        for target in (10, 11, 0):
            with self.assertRaisesRegex(RuntimeError, "nothing to undo"):
                tasks.downgrade(db, target)
        self.assertEqual(ms.version(db), 10)
        db.close()

    def test_export_copies_the_onboarding_records_without_changing_the_file(self):
        path = self.v10()
        db = ms.connect(path)
        db.execute("INSERT INTO onboarding_events (subject, at, kind, actor) VALUES ('draft:d-1', 0, 'draft_created', "
                   "'jay')")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = ms.digests(db)
        db.close()
        out = tmp("onboarding.json")
        code, text, _ = run("export-onboarding", "--db", path, "--out", out)
        self.assertEqual(code, 0)
        with open(out, "rb") as f:
            body = f.read()
        self.assertIn(f"sha256: {hashlib.sha256(body).hexdigest()}", text)
        data = json.loads(body)
        self.assertEqual(data["tables"]["onboarding_events"][0]["kind"], "draft_created")
        self.assertEqual(sorted(data["tables"]), sorted(tasks.DOWNGRADES[10]))
        db = ms.connect(path)
        self.assertEqual(ms.digests(db), before)                                 # read-only
        db.close()
        self.assertEqual(run("export-onboarding", "--db", path, "--out", out)[0], 1)   # never overwrites

    def test_this_ccd_upgrades_a_rolled_back_file_again(self):
        path = self.v10()
        run("rollback", "--db", path, "--to", "9", "--backup-dir", tmp("backups"))
        ts = tasks.TaskStore(path, PROJECTS)
        self.assertEqual(ts.applied, [10])
        ts.close()


if __name__ == "__main__":
    unittest.main()
