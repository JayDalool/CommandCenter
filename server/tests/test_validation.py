"""phase1-readiness (ccd/validation): the write guard really blocks, fixtures cover every sweep class and agree,
replay reads a copy read-only and rebuilds what the daemon saw, the classifier catches an engine that says "auto"
where a hard rule forbids it, and a run with full evidence passes while one without evidence never does.

The --fixtures part runs here on every PR, so the safety cases cannot quietly rot."""
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from ccd import autonomy
from ccd.config import task_projects
from ccd.tasks import TaskStore
from ccd.validation import __main__ as cli
from ccd.validation import classify, fixtures, guard, oracle, readiness, replay

from .helpers import cfg

HEAD = "ab" * 20


def run_cli(*args):
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = cli.main(["phase1-readiness", *args])
    return code, out.getvalue(), err.getvalue()


def make_db(path, tickets=3):
    """A small tasks.db with pipeline history: a plan accepted, a merge gated, a label added after the decision."""
    ts = TaskStore(path, task_projects(cfg()))
    keys = [ts.create("commandcenter", f"t{i}")[0]["key"] for i in range(tickets)]
    tid = ts._id_of(keys[0])
    ts.db.execute("BEGIN")
    ts._audit(tid, "ccd", "pipeline.plan_accepted", data={}, at=1000.0)
    ts._audit(tid, "ccd", "pipeline.review", data={"verdict": "APPROVE", "head": HEAD}, at=1100.0)
    ts._audit(tid, "ccd", "pipeline.gate_opened", data={"gate": "merge"}, at=1200.0)
    ts.db.execute("COMMIT")
    ts.update(keys[0], {"labels": ["secrets"]}, "jay")          # after every decision: must be undone in replay
    sh = autonomy.Shadow(ts.db)
    f = fixtures.ready()
    sh.record(tid, "commandcenter", "merge", "jay", autonomy.evaluate("merge", None, f), f, "fp", at=1200.0)
    ts.close()          # checkpoints the write-ahead log, like sqlite3 .backup
    return keys


class Guard(unittest.TestCase):
    def test_every_probe_is_blocked_and_everything_is_restored_after(self):
        tmp = tempfile.mkdtemp(prefix="guard-")
        with guard.installed(write_dirs=[tmp]):
            self.assertEqual([c for c in guard.self_check() if not c["blocked"]], [])
            with open(os.path.join(tmp, "ok.txt"), "w") as fh:     # the report folder is writable
                fh.write("x")
            with self.assertRaises(guard.GuardError):
                open(os.path.join(tempfile.gettempdir(), "not-here.txt"), "a")
            with self.assertRaises(guard.GuardError):
                sqlite3.connect(os.path.join(tempfile.gettempdir(), "nope.db"))
        self.assertEqual(subprocess.run(["true"]).returncode, 0)
        sqlite3.connect(":memory:").close()

    def test_a_guard_that_does_not_block_stops_the_run(self):
        tmp = tempfile.mkdtemp(prefix="guard-")
        with mock.patch.object(guard, "self_check", return_value=[{"probe": "x", "blocked": False}]):
            code, _o, err = run_cli("--fixtures", "--out", tmp)
        self.assertEqual(code, 2)
        self.assertIn("did not block", err)
        self.assertFalse(os.path.exists(os.path.join(tmp, "readiness.json")))


class Fixtures(unittest.TestCase):
    def test_every_case_agrees_and_every_regression_and_class_is_covered(self):
        rows = fixtures.run()
        for r in rows:
            c, note = classify.classify(r["verdict"], oracle.requirement(r["action"], r["profile"], r["facts"]),
                                        expected=r["expected"])
            self.assertEqual(c, "agree", (r["id"], note, r["verdict"]))
        self.assertEqual({r["regression"] for r in rows if r["regression"]}, set(readiness.REGRESSIONS))
        self.assertTrue({"auto", "jay", "refuse"} <= {r["expected"] for r in rows})

    def test_the_oracle_does_not_object_to_the_starting_points(self):
        for r in fixtures.run():
            if r["expected"] == "auto":
                self.assertIsNone(oracle.requirement(r["action"], r["profile"], r["facts"])["must"], r["id"])

    def test_a_fixtures_run_is_deterministic_and_never_passes_without_evidence(self):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        ca, _o, _e = run_cli("--fixtures", "--now", "2026-10-22T12:00:00Z", "--out", a)
        cb, _o, _e = run_cli("--fixtures", "--now", "2026-10-22T12:00:00Z", "--out", b)
        self.assertEqual((ca, cb), (1, 1))
        ja, jb = (json.load(open(os.path.join(d, "readiness.json"))) for d in (a, b))
        for j in (ja, jb):
            j.pop("performance")
        self.assertEqual(ja, jb)
        gate = {r["row"]: r["status"] for r in ja["gate"]}
        self.assertEqual({n for n in (9, 10, 11, 12, 13) if gate[n] != "pass"}, set(), ja["gate"])
        self.assertEqual(gate[1], "missing")
        self.assertEqual(ja["result"], "FAIL")
        self.assertTrue(open(os.path.join(a, "readiness.md")).read().startswith("# Phase 1 readiness: FAIL"))


class Fuzz(unittest.TestCase):
    def test_no_schema_valid_profile_variant_lets_the_engine_say_auto_against_a_hard_rule(self):
        from ccd.validation import fuzz
        for seed in (1, 2, 3):
            res = fuzz.problems(seed, n=1500)
            self.assertGreater(res["checked"], 1500)
            self.assertEqual(res["problems"], [], seed)

    def test_it_catches_an_engine_with_a_rule_switched_off(self):
        from ccd.validation import fuzz
        for name, value in (("_reviews", ([], [])), ("_unattended_when", ([], [])), ("_closed", None)):
            with mock.patch.object(autonomy, name, return_value=value):
                self.assertTrue(fuzz.problems(1, n=1500)["problems"], name)


class Classifier(unittest.TestCase):
    def test_an_engine_that_says_auto_against_a_hard_rule_fails_the_gate(self):
        tmp = tempfile.mkdtemp()
        always = {"outcome": "auto", "rule": "target.merge", "reasons": [], "missing": [], "engine": 2}
        with mock.patch.object(autonomy, "evaluate", return_value=always):
            code, _o, _e = run_cli("--fixtures", "--out", tmp)
        rep = json.load(open(os.path.join(tmp, "readiness.json")))
        gate = {r["row"]: r for r in rep["gate"]}
        self.assertEqual(code, 1)
        self.assertEqual(gate[9]["status"], "fail")
        self.assertGreater(rep["classes"]["fixture"]["unsafe-permissive"], 30)
        self.assertEqual(gate[13]["status"], "fail")

    def test_the_classes(self):
        auto = {"outcome": "auto", "rule": "target.merge", "missing": []}
        jay = {"outcome": "jay", "rule": "merge:readiness", "missing": []}
        must = {"must": "jay", "why": [("O-READY", "draft")]}
        clean = {"must": None, "why": []}
        self.assertEqual(classify.classify(auto, must, observed="jay")[0], "unsafe-permissive")
        self.assertEqual(classify.classify(jay, {"must": "refuse", "why": []}, observed="jay")[0], "boundary-softened")
        self.assertEqual(classify.classify(jay, must, observed="auto")[0], "legacy-permissive")
        self.assertEqual(classify.classify(jay, clean, observed="auto")[0], "expected-stricter")
        self.assertEqual(classify.classify(dict(jay, rule="new:rule"), clean, observed="auto")[0], "unknown")
        self.assertEqual(classify.classify(dict(jay, missing=["ci"]), clean, observed="auto")[0], "safe-conservative")
        self.assertEqual(classify.classify(auto, clean, observed="jay")[0], "expected-permissive")
        self.assertEqual(classify.classify(dict(auto, rule="new:rule"), clean, observed="jay")[0], "unknown")
        self.assertEqual(classify.classify(dict(jay, missing=["ci"]), clean, observed="jay")[0], "vacuous-agree")
        self.assertEqual(classify.classify({"outcome": "jay", "rule": "engine:error"}, clean)[0], "engine-bug")

    def test_every_rule_the_engine_can_give_is_cited(self):
        import inspect
        import re
        src = inspect.getsource(autonomy)
        rules = set(re.findall(r'_verdict\(\s*"(?:auto|jay|refuse)",\s*"([^"]+)"', src))
        self.assertTrue(rules)
        self.assertEqual(rules - set(classify.RULE_CITATIONS) - {"engine:error"}, set())


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="replay-")
        self.db = os.path.join(self.tmp, "copy.db")
        self.keys = make_db(self.db)

    def test_history_is_rebuilt_as_the_daemon_saw_it(self):
        snap = replay.open_snapshot(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            snap.execute("UPDATE tickets SET title = 'x'")
        hist = replay.history(snap)
        self.assertEqual([(d["action"], d["observed"]) for d in hist], [("plan", "auto"), ("merge", "jay")])
        merge = hist[1]
        self.assertEqual(merge["facts"]["labels"], [])                # "secrets" came later
        self.assertEqual((merge["facts"]["review_head"], merge["facts"]["review_at_head"]), (HEAD, True))
        rows = replay.shadow_rows(snap)
        self.assertEqual([(r["action"], r["observed"], r["recorded"]["version"]) for r in rows],
                         [("merge", "jay", autonomy.ENGINE_VERSION)])
        self.assertEqual(replay.integrity(snap)["eventsGaps"], 0)
        self.assertEqual(replay.unauthorized(snap, 0), [])

    def test_the_github_cache_supplies_pr_facts_and_says_so(self):
        snap = sqlite3.connect(self.db)
        tid = snap.execute("SELECT id FROM tickets WHERE key=?", (self.keys[0],)).fetchone()[0]
        snap.execute("INSERT INTO ticket_links (ticket_id, provider, kind, ref, created_at, created_by) "
                     "VALUES (?, 'github', 'pr', 'o/r#5', 1, 'ccd')", (tid,))
        snap.commit()
        snap.close()
        cache = {"o/r#5": {"headRefOid": HEAD, "isDraft": True, "mergeable": "MERGEABLE", "baseRefName": "main",
                           "isCrossRepository": False, "files": [], "statusCheckRollup": [{"conclusion": "SUCCESS"}]}}
        merge = replay.history(replay.open_snapshot(self.db), cache)[1]
        self.assertTrue(merge["facts"]["draft"])
        self.assertEqual(merge["facts"]["ci_passed"], True)
        self.assertTrue(merge["inferred"])

    def test_the_live_data_folder_and_a_live_write_ahead_log_are_refused(self):
        with mock.patch.dict(os.environ, {"CCD_DATA_DIR": self.tmp}):
            code, _o, err = run_cli("--replay", self.db, "--out", tempfile.mkdtemp())
        self.assertEqual(code, 2)
        self.assertIn("live data folder", err)
        with open(self.db + "-wal", "wb") as fh:
            fh.write(b"x")
        code, _o, err = run_cli("--replay", self.db, "--out", tempfile.mkdtemp())
        self.assertEqual(code, 2)
        self.assertIn("write-ahead log", err)

    def test_an_agent_merge_after_go_live_is_unauthorised(self):
        snap = sqlite3.connect(self.db)
        tid = snap.execute("SELECT id FROM tickets LIMIT 1").fetchone()[0]
        snap.execute("INSERT INTO ticket_events (ticket_id, at, actor, kind, data) VALUES (?, 5000, 'ccd', "
                     "'pipeline.auto_merged', '{}'), (?, 5001, 'ccd', 'pipeline.deployed', '{\"env\": \"live\"}')",
                     (tid, tid))
        snap.commit()
        snap.close()
        un = replay.unauthorized(replay.open_snapshot(self.db), 0)
        self.assertEqual([u["kind"] for u in un], ["pipeline.auto_merged", "pipeline.deployed"])

    def test_restore_drill_migrates_a_copy_and_leaves_the_backup_alone(self):
        before = open(self.db, "rb").read()
        with mock.patch.object(replay, "GO_LIVE_TICKETS", 3):
            res = readiness.restore_drill(self.db, tempfile.mkdtemp())
        self.assertTrue(res["pass"], res)
        self.assertTrue(res["refusesNewerSchema"])
        self.assertEqual(open(self.db, "rb").read(), before)


class _Live(BaseHTTPRequestHandler):
    BODIES = {
        "/api/health": {"ok": True, "uptimeS": 26 * 3600, "version": "test"},
        "/api/autonomy": {"mode": "shadow", "engine": 2, "total": 3, "agree": 3, "disagree": 0, "counts": {
            "commandcenter": {"plan": {"total": 3, "agree": 3}}}, "disagreements": []},
        "/api/profiles": {"problems": []},
        "/api/audit": {"chain": {"ok": True, "checked": 10}, "summary": {"wouldRefuse": 4}},
        "/api/workers": {"nodes": [{"status": "online"}]},
        "/api/night-shift": {"projects": {}},
        "/api/decisions": {"counts": {}},
        "/api/usage": {"total": {}},
        "/api/activity": {"events": [{"kind": "merge.policy", "data": {"status": "disabled"}}]},
    }
    seen = []

    def do_GET(self):     # noqa: N802
        type(self).seen.append((self.command, self.headers.get("X-CCD-Token")))
        body = self.BODIES.get(self.path.split("?")[0])
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def log_message(self, *_a):
        pass


class FullRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="full-")
        self.db = os.path.join(self.tmp, "copy.db")
        make_db(self.db)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Live)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.token = os.path.join(self.tmp, "token")
        with open(self.token, "w") as fh:
            fh.write("tok\n")
        self.evidence = {
            "engineLiveAt": "2026-10-23T22:00:00Z",
            "nightShift": {"cycles": [{"project": "commandcenter", "withWork": True, "ended": "cutoff", "reminders": 2}]},
            "drills": {"restart": {"pass": True}, "rollback": {"pass": True, "refusedV9": True, "bootedOnBackup": True}},
            "auditWalks": [{"when": w, "ok": True} for w in ("start", "after_restart", "end")],
            "suites": {"commit": "f" * 40, "green": True},
        }

    def run_full(self, now="2026-10-25T00:00:00Z", **change):
        ev = dict(self.evidence, **change)
        path = os.path.join(self.tmp, "evidence.json")
        with open(path, "w") as fh:
            json.dump(ev, fh)
        out = tempfile.mkdtemp()
        with mock.patch.object(replay, "GO_LIVE_TICKETS", 3):
            code, _o, err = run_cli("--fixtures", "--replay", self.db, "--live", self.url, "--token-file", self.token,
                                    "--evidence", path, "--restore-backup", self.db, "--now", now, "--out", out)
        rep = json.load(open(os.path.join(out, "readiness.json"))) if code != 2 else None
        return code, rep, err

    def test_full_evidence_passes_and_live_mode_sent_only_gets(self):
        _Live.seen.clear()
        code, rep, err = self.run_full()
        self.assertEqual(code, 0, (err, [r for r in (rep or {}).get("gate", []) if r["status"] != "pass"]))
        self.assertEqual(rep["result"], "PASS")
        self.assertEqual({m for m, _t in _Live.seen}, {"GET"})
        self.assertEqual({t for _m, t in _Live.seen}, {"tok"})
        self.assertEqual(rep["classes"]["replay-history"]["unknown"], 0)

    def test_too_early_or_a_quiet_night_or_a_broken_walk_fails(self):
        code, rep, _e = self.run_full(now="2026-10-24T12:00:00Z")
        self.assertEqual((code, rep["gate"][0]["status"]), (1, "fail"))
        code, rep, _e = self.run_full(nightShift={"cycles": [{"withWork": False, "ended": "cutoff", "reminders": 0}]})
        self.assertEqual((code, rep["gate"][1]["status"]), (1, "fail"))
        code, rep, _e = self.run_full(auditWalks=[{"when": "start", "ok": False}])
        self.assertEqual((code, rep["gate"][5]["status"]), (1, "fail"))
        self.assertEqual(rep["gate"][14]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
