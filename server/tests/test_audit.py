"""PR 7: verified actor identity (ccd/identity.py), the global audit trail (ccd/audit.py) and token metering
(ccd/meter.py). All three record; none refuses a request or stops work."""
import json
import os
import sqlite3
import tempfile
import unittest

from ccd import audit, identity, meter, security
from ccd.config import task_projects
from ccd.daemon import ActionError, Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db

TOKEN = "t" * 43
DEV = "d" * 43


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def tasks_db():
    return TaskStore(os.path.join(tempfile.mkdtemp(prefix="au-"), "tasks.db"), task_projects(cfg()))


class AuditChain(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.a = audit.Audit(self.ts.db, Clock())

    def rec(self, **kw):
        base = dict(actor="jay", verified=False, via="none", method="POST", path="/api/tasks", status=201)
        return self.a.record(**dict(base, **kw))

    def test_chain_verifies_and_breaks_when_a_row_is_edited_in_the_file(self):
        for i in range(5):
            self.rec(path=f"/api/tasks/SAM-{i}/comments", body={"body": f"note {i}"})
        self.assertEqual(self.a.verify(), {"ok": True, "checked": 5, "brokenAt": None, "full": False})
        with self.assertRaises(sqlite3.DatabaseError):
            self.ts.db.execute("UPDATE audit_events SET actor='agent:x' WHERE id=3")
        with self.assertRaises(sqlite3.DatabaseError):
            self.ts.db.execute("DELETE FROM audit_events WHERE id=3")
        # Someone with the file drops the trigger and edits a row: the chain says where.
        self.ts.db.execute("DROP TRIGGER audit_events_append_only_u")
        self.ts.db.execute("UPDATE audit_events SET actor='agent:x' WHERE id=3")
        self.assertEqual(self.a.verify(full=True), {"ok": False, "checked": 2, "brokenAt": 3, "full": True})

    def test_verify_checks_new_rows_and_a_full_walk_catches_old_edits(self):
        for i in range(3):
            self.rec(path=f"/api/x/{i}")
        self.assertEqual(self.a.verify()["checked"], 3)
        self.rec(path="/api/x/3")
        self.assertEqual(self.a.verify()["checked"], 4)                     # resumes from the last good row
        self.ts.db.execute("DROP TRIGGER audit_events_append_only_u")
        self.ts.db.execute("UPDATE audit_events SET path='/edited' WHERE id=1")
        self.assertTrue(self.a.verify()["ok"])                              # already-checked rows: only a full walk
        self.assertEqual(self.a.verify(full=True), {"ok": False, "checked": 0, "brokenAt": 1, "full": True})
        self.assertFalse(self.a.verify(full=True)["ok"])
        self.assertEqual(self.a.verify()["brokenAt"], 1)                    # a break stays reported on every look
        self.rec(path="/api/x/4")
        self.assertFalse(self.a.verify()["ok"])

    def test_actor_is_stored_without_control_characters(self):
        self.rec(actor="evil\x1b[2Jname")
        self.assertNotIn("\x1b", self.a.list()[0]["actor"])

    def test_the_body_is_never_stored_only_its_hash_and_keys(self):
        self.rec(path="/api/tasks/SAM-1/answers", body={"answers": {"1": "the password is hunter2"}, "project": "samvision"})
        dump = "\n".join(str(r) for r in self.ts.db.execute("SELECT * FROM audit_events"))
        self.assertNotIn("hunter2", dump)
        row = self.a.list()[0]
        self.assertEqual(row["bodyKeys"], ["answers", "project"])
        self.assertEqual(row["ref"], "SAM-1")
        self.assertEqual(row["project"], "samvision")

    def test_record_inside_a_callers_transaction_uses_a_savepoint(self):
        self.ts.db.execute("BEGIN")
        self.rec()
        self.assertTrue(self.ts.db.in_transaction)
        self.ts.db.execute("ROLLBACK")
        self.assertEqual(self.a.list(), [])

    def test_schema_refuses_a_verified_row_with_nothing_behind_it(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.rec(verified=True, via="none")
        with self.assertRaises(sqlite3.IntegrityError):
            self.rec(via="trust-me")

    def test_summary_measures_what_enforcement_would_refuse(self):
        self.rec()                                                       # jay, unverified
        self.rec(verified=True, via="developer")
        self.rec(actor="agent:coder", via="none")
        self.rec(actor="agent:coder", via="token", token_actor="agent:reviewer")
        self.rec(actor="system:ccd", verified=True, via="system", method="EVENT", path="pipeline.gate_opened", status=0)
        s = self.a.summary()
        self.assertEqual((s["total"], s["unverifiedJay"], s["agentUnverified"], s["mismatch"], s["wouldRefuse"]),
                         (5, 1, 2, 1, 3))


class Identity(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.clock = Clock()
        self.t = identity.ActorTokens(self.ts.db, self.clock)

    def test_only_jay_issues_and_only_for_agents(self):
        with self.assertRaises(identity.IdentityError) as e:
            self.t.issue("agent:coder", "agent:coordinator")
        self.assertEqual(e.exception.status, 403)
        for bad in ("jay", "agent:", "agent:Coder", "agent:a b", "system:ccd", None):
            with self.assertRaises(identity.IdentityError):
                self.t.issue(bad, "jay")
        for ttl in (0, -1, 366, "x"):
            with self.assertRaises(identity.IdentityError):
                self.t.issue("agent:coder", "jay", ttl)

    def test_issue_verify_expire_revoke(self):
        out = self.t.issue("agent:coder", "jay", 1, note="laptop\nlane")
        self.assertTrue(out["token"].startswith("cca_"))
        self.assertEqual(self.t.verify(out["token"]), "agent:coder")
        self.assertIsNone(self.t.verify(out["token"] + "x"))
        self.assertIsNone(self.t.verify("cca_" + "x" * 200))
        self.assertNotIn(out["token"], json.dumps(self.t.list()))           # shown once; only its fingerprint after
        self.assertEqual(self.t.list()[0]["note"], "laptop lane")
        self.clock.t += 86401
        self.assertIsNone(self.t.verify(out["token"]))
        self.assertEqual(self.t.list()[0]["status"], "expired")
        other = self.t.issue("agent:reviewer", "jay")
        self.assertEqual(self.t.revoke(other["id"], "jay")["status"], "revoked")
        self.assertIsNone(self.t.verify(other["token"]))
        with self.assertRaises(identity.IdentityError):
            self.t.revoke(other["id"], "jay")
        with self.assertRaises(identity.IdentityError):
            self.t.revoke(out["id"], "agent:coder")

    def test_schema_keeps_tokens_as_history(self):
        out = self.t.issue("agent:coder", "jay", project="samvision")
        for sql in ("DELETE FROM identity_tokens", "UPDATE identity_tokens SET subject='agent:root'",
                    "UPDATE identity_tokens SET kind='service'", "UPDATE identity_tokens SET project=NULL",
                    "UPDATE identity_tokens SET expires_at=expires_at+1e9",
                    "UPDATE identity_tokens SET issued_by='agent:x'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.ts.db.execute(sql)
        self.t.revoke(out["id"], "jay")
        with self.assertRaises(sqlite3.DatabaseError):                     # revoke is once
            self.ts.db.execute("UPDATE identity_tokens SET revoked_at=NULL")
        for kind, subject, by in (("agent", "agent:x", "agent:x"), ("agent", "svc:x", "jay"),
                                  ("service", "agent:x", "jay"), ("agent", "jay", "jay"), ("user", "agent:x", "jay")):
            with self.subTest(kind=kind, subject=subject, by=by), self.assertRaises(sqlite3.IntegrityError):
                self.ts.db.execute("INSERT INTO identity_tokens (kind, subject, token_sha, issued_at, issued_by, "
                                   "expires_at) VALUES (?, ?, ?, 0, ?, 1)", (kind, subject, "a" * 64, by))
        # the pre-Phase-2 table keeps its own guards
        self.ts.db.execute("INSERT INTO actor_tokens (actor, token_sha, issued_at, issued_by, expires_at) "
                           "VALUES ('agent:old', ?, 0, 'jay', 1)", ("b" * 64,))
        for sql in ("DELETE FROM actor_tokens", "UPDATE actor_tokens SET actor='agent:root'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.ts.db.execute(sql)

    def test_identify(self):
        self.assertEqual(identity.identify("jay", True, None)["via"], "developer")
        self.assertFalse(identity.identify("jay", False, None)["verified"])
        self.assertFalse(identity.identify("agent:x", True, None)["verified"])   # Unlock vouches only for Jay
        self.assertTrue(identity.identify("agent:x", False, "agent:x")["verified"])
        m = identity.identify("jay", False, "agent:x")
        self.assertEqual((m["verified"], m["mismatch"], m["via"]), (False, True, "token"))

    def test_developer_check_is_read_only(self):
        now = [100.0]
        g = security.DeveloperGate(DEV, clock=lambda: now[0])
        sid, _ = g.unlock(DEV)
        used = g.sessions[sid][1]
        now[0] += 10
        self.assertTrue(identity.developer_session_valid(g, sid))
        self.assertEqual(g.sessions[sid][1], used)                         # idle timer untouched
        self.assertFalse(identity.developer_session_valid(g, "nope"))
        self.assertFalse(identity.developer_session_valid(None, sid))
        now[0] += 10 ** 6
        self.assertFalse(identity.developer_session_valid(g, sid))


class OverHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from starlette.testclient import TestClient
        from ccd.api import create_app
        self.store = Store(new_db())
        self.ts = tasks_db()
        self.d = Daemon(cfg(meter={"enabled": False}), self.store, None, tasks=self.ts)
        self.d.dev_gate = security.DeveloperGate(DEV)
        guarded, _app = create_app(self.d, TOKEN, 7799)
        self.c = TestClient(guarded, base_url="http://127.0.0.1:7799")
        self.h = {"x-ccd-token": TOKEN}

    async def asyncTearDown(self):
        self.store.close()

    def unlock(self):
        r = self.c.post("/api/developer/unlock", headers=self.h, json={"token": DEV})
        return dict(self.h, **{"x-ccd-developer": r.json()["session"]})

    def test_every_write_is_recorded_with_how_far_its_actor_is_verified(self):
        r = self.c.post("/api/tasks", headers=self.h, json={"project": "samvision", "title": "audit me"})
        self.assertEqual(r.status_code, 201)
        key = r.json()["key"]
        self.c.get("/api/tasks", headers=self.h)                            # reads are not recorded
        self.c.post(f"/api/tasks/{key}/comments", headers=dict(self.h, **{"x-ccd-actor": "agent:coder"}),
                    json={"body": "secret words"})
        dev = self.unlock()
        self.c.post(f"/api/tasks/{key}/comments", headers=dev, json={"body": "hi"})
        rows = self.c.get("/api/audit", headers=self.h).json()["events"]
        got = [(e["method"], e["path"], e["status"], e["actor"], e["via"], e["verified"]) for e in reversed(rows)]
        self.assertEqual(got, [
            ("POST", "/api/tasks", 201, "jay", "none", False),
            ("POST", f"/api/tasks/{key}/comments", 201 if got[1][2] == 201 else 200, "agent:coder", "none", False),
            ("POST", "/api/developer/unlock", 200, "jay", "none", False),
            ("POST", f"/api/tasks/{key}/comments", got[3][2], "jay", "developer", True)])
        self.assertEqual(rows[-1]["project"], "samvision")
        self.assertEqual(rows[0]["ref"], key)
        self.assertIsNone(self.ts.db.execute("SELECT body_sha FROM audit_events WHERE path='/api/developer/unlock'")
                          .fetchone()[0])                                    # the unlock secret is not even hashed
        dump = "\n".join(str(r) for r in self.ts.db.execute("SELECT * FROM audit_events"))
        self.assertNotIn("secret words", dump)
        self.assertNotIn(DEV, dump)
        self.assertTrue(self.c.get("/api/audit", headers=self.h).json()["chain"]["ok"])

    def test_a_lock_is_credited_to_the_session_it_ends(self):
        dev = self.unlock()
        self.c.post("/api/developer/lock", headers=dev, json={})
        row = self.d.audit.list()[0]
        self.assertEqual((row["path"], row["via"], row["verified"]), ("/api/developer/lock", "developer", True))
        self.assertTrue(self.c.get("/api/audit?full=1", headers=self.h).json()["chain"]["full"])

    def test_requests_without_the_token_are_not_recorded_and_failures_are(self):
        self.c.post("/api/tasks", json={"project": "samvision", "title": "x"})
        self.assertEqual(self.d.audit.list(), [])
        self.c.post("/api/tasks", headers=dict(self.h, **{"x-ccd-actor": "root"}), json={"title": "x"})
        self.c.post("/api/workers/approve", headers=self.h, json={"id": "nope"})
        rows = self.d.audit.list()
        self.assertEqual([(e["status"], e["actor"]) for e in reversed(rows)], [(400, "root"), (403, "jay")])

    def test_actor_tokens_verify_agents_and_mismatches_are_recorded(self):
        self.assertEqual(self.c.post("/api/actors/issue", headers=self.h, json={"actor": "agent:coder"}).status_code, 403)
        dev = self.unlock()
        self.assertEqual(self.c.post("/api/actors/issue", headers=dict(dev, **{"x-ccd-actor": "agent:x"}),
                                     json={"actor": "agent:coder"}).status_code, 403)
        out = self.c.post("/api/actors/issue", headers=dev, json={"actor": "agent:coder", "ttlDays": 7}).json()
        tok = out["token"]
        self.assertNotIn(tok, json.dumps(self.c.get("/api/actors", headers=self.h).json()))
        h = dict(self.h, **{"x-ccd-actor": "agent:coder", "x-ccd-actor-token": tok})
        self.c.post("/api/tasks", headers=h, json={"project": "samvision", "title": "by a verified agent"})
        h2 = dict(self.h, **{"x-ccd-actor": "jay", "x-ccd-actor-token": tok})
        r = self.c.post("/api/tasks", headers=h2, json={"project": "samvision", "title": "claims jay"})
        self.assertEqual(r.status_code, 201)                                 # recorded, not refused (Phase 2)
        rows = self.d.audit.list(limit=2)
        self.assertEqual((rows[0]["via"], rows[0]["verified"], rows[0]["tokenActor"]), ("token", False, "agent:coder"))
        self.assertIn("different actor", rows[0]["summary"])
        self.assertEqual((rows[1]["via"], rows[1]["verified"]), ("token", True))
        self.assertNotIn(tok, "\n".join(str(r) for r in self.ts.db.execute("SELECT * FROM audit_events")))
        self.assertEqual(self.c.post("/api/actors/revoke", headers=dev, json={"id": "1"}).status_code, 400)
        self.assertEqual(self.c.post("/api/actors/revoke", headers=dev, json={"id": out["id"]}).json()["status"],
                         "revoked")
        self.assertEqual(self.c.get("/api/audit?verified=1", headers=self.h).status_code, 200)
        self.assertEqual(self.c.get("/api/audit?verified=x", headers=self.h).status_code, 400)

    def test_a_broken_audit_never_breaks_the_write(self):
        def boom(**_):
            raise sqlite3.OperationalError("disk I/O error")
        self.d.audit.record = boom
        r = self.c.post("/api/tasks", headers=self.h, json={"project": "samvision", "title": "still works"})
        self.assertEqual(r.status_code, 201)

    def test_pipeline_steps_are_recorded_as_system(self):
        t = self.d.task_create({"project": "samvision", "title": "x"}, "jay")
        self.d._pipeline_result(t, [], [("pipeline.gate_opened", "plan gate opened", {})])
        row = self.d.audit.list()[0]
        self.assertEqual((row["actor"], row["via"], row["verified"], row["path"], row["ref"]),
                         ("system:ccd", "system", True, "pipeline.gate_opened", t["key"]))


def claude_line(mid, model="claude-opus-5-5", cwd="/srv/x", branch="main", out=100, text="hello world"):
    return json.dumps({"type": "assistant", "timestamp": "2026-10-20T10:00:00Z", "sessionId": "s1", "cwd": cwd,
                       "gitBranch": branch, "message": {"id": mid, "model": model, "content": [{"type": "text",
                       "text": text}], "usage": {"input_tokens": 1000, "output_tokens": out,
                       "cache_read_input_tokens": 10000, "cache_creation_input_tokens": 2000,
                       "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 2000}}}}) + "\n"


class Metering(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.dir = tempfile.mkdtemp(prefix="mt-")
        self.claude = os.path.join(self.dir, "claude", "proj")
        self.codex = os.path.join(self.dir, "codex", "2026", "10")
        os.makedirs(self.claude)
        os.makedirs(self.codex)
        self.clock = Clock(1_792_000_000.0)                                   # 2026-10-15
        self.m = meter.Meter(self.ts.db, [("claude", os.path.join(self.dir, "claude")),
                                          ("codex", os.path.join(self.dir, "codex"))],
                             attribute=lambda cwd, br: ("samvision", "SAM-7") if cwd == "/srv/sam" else (None, None),
                             clock=self.clock)

    def test_prices_and_costs(self):
        self.assertEqual(meter.price_of("claude-opus-5-5"), (4.0, 20.0, 0.20))
        self.assertEqual(meter.price_of("claude-sonnet-4-6-20260101"), (3.0, 15.0, 0.30))
        self.assertIsNone(meter.price_of("gpt-5"))
        # 1000 in * 4 + 100 out * 20 + 10000 read * 0.2 + 2000 1h-write * 8 = 4000+2000+2000+16000 = 24000 / 1e6
        self.assertAlmostEqual(meter.cost_usd("claude-opus-5-5", 1000, 100, 10000, 0, 2000), 0.024)

    def test_claude_logs_are_read_once_deduplicated_and_never_store_text(self):
        f = os.path.join(self.claude, "a.jsonl")
        with open(f, "w") as fh:
            fh.write(claude_line("m1", cwd="/srv/sam", text="TOP SECRET PLAN"))
            fh.write(claude_line("m1", cwd="/srv/sam"))                           # the same reply, another block
            fh.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
            fh.write("not json\n")
            fh.write(claude_line("m2", model="<synthetic>"))
            fh.write(claude_line("m3", model="claude-sonnet-5-5"))
            fh.write(claude_line("m4")[:-30])                                     # still being written
        self.assertEqual(self.m.scan(), 2)
        self.assertEqual(self.m.scan(), 0)
        rows = self.ts.db.execute("SELECT ref, project, ticket_key, model, cost_usd FROM usage_records ORDER BY ref").fetchall()
        self.assertEqual(rows, [("m1", "samvision", "SAM-7", "claude-opus-5-5", 0.024),
                                ("m3", None, None, "claude-sonnet-5-5", 0.013)])
        self.assertNotIn("TOP SECRET", "\n".join(str(r) for r in self.ts.db.execute("SELECT * FROM usage_records")))
        with open(f, "a") as fh:                                                   # the rest of m4 arrives
            fh.write(claude_line("m4")[-30:])
        self.assertEqual(self.m.scan(), 1)
        with self.assertRaises(sqlite3.DatabaseError):
            self.ts.db.execute("DELETE FROM usage_records")

    def test_a_replaced_log_is_read_again_without_double_counting(self):
        f = os.path.join(self.claude, "b.jsonl")
        with open(f, "w") as fh:
            fh.write(claude_line("m1") + claude_line("m2"))
        self.m.scan()
        os.remove(f)
        with open(f, "w") as fh:
            fh.write(claude_line("m1"))
        self.assertEqual(self.m.scan(), 0)
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0], 2)

    def test_codex_logs_count_tokens_without_a_price(self):
        f = os.path.join(self.codex, "rollout-1.jsonl")
        lines = [{"type": "session_meta", "payload": {"id": "cx1", "cwd": "/srv/sam"}},
                 {"type": "turn_context", "payload": {"model": "gpt-5-codex"}},
                 {"type": "event_msg", "timestamp": "2026-10-20T10:00:00Z", "payload": {"type": "token_count",
                  "info": {"last_token_usage": {"input_tokens": 500, "cached_input_tokens": 200, "output_tokens": 50}}}},
                 {"type": "event_msg", "payload": {"type": "token_count", "info": None}}]
        with open(f, "w") as fh:
            fh.write("".join(json.dumps(x) + "\n" for x in lines))
        self.assertEqual(self.m.scan(), 1)
        row = self.ts.db.execute("SELECT source, project, model, input, cache_read, output, cost_usd, session "
                                 "FROM usage_records").fetchone()
        self.assertEqual(row, ("codex", "samvision", "gpt-5-codex", 300, 200, 50, None, "cx1"))

    def test_scan_budget_resumes_where_it_stopped(self):
        f = os.path.join(self.claude, "c.jsonl")
        with open(f, "w") as fh:
            fh.write("".join(claude_line(f"m{i}") for i in range(50)))
        n = self.m.scan(budget=2000)
        self.assertTrue(0 < n < 50)
        while self.m.scan(budget=2000):
            pass
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0], 50)

    def test_reported_usage_and_summary_with_budgets(self):
        self.assertFalse(self.m.report("r0", "gyst", None, "agent:x", {"inputTokens": "lots"}))
        self.assertFalse(self.m.report("r0", "gyst", None, "agent:x", None))
        self.assertTrue(self.m.report("r1", "gyst", "GYS-1", "agent:coder",
                                      {"model": "claude-haiku-5-5", "inputTokens": 1_000_000, "outputTokens": 0}))
        self.assertFalse(self.m.report("r1", "gyst", "GYS-1", "agent:coder", {"inputTokens": 5}))   # dedupe by ref
        f = os.path.join(self.claude, "r.jsonl")
        with open(f, "w") as fh:
            fh.write(claude_line("m1", model="claude-haiku-5-5"))
        self.m.scan()
        s = self.m.summary(14, {"gyst": {"monthly_usd": 5}, "mfe": {"monthly_tokens": 1000}})
        self.assertEqual(s["total"]["replies"], 1)                          # the log's reply; reported is not added
        self.assertEqual({r["key"]: r["replies"] for r in s["bySource"]}, {"claude": 1, "reported": 1})
        self.assertEqual(s["byTicket"], [])
        self.assertEqual(s["budgets"], [
            {"project": "gyst", "monthlyUsd": 5, "monthlyTokens": None, "spentUsd": 0, "spentTokens": 0},
            {"project": "mfe", "monthlyUsd": None, "monthlyTokens": 1000, "spentUsd": 0, "spentTokens": 0}])

    def test_the_fullest_count_of_a_reply_wins(self):
        f = os.path.join(self.claude, "d.jsonl")
        with open(f, "w") as fh:
            fh.write(claude_line("m1", out=5) + claude_line("m1", out=400) + claude_line("m1", out=7))
        self.m.scan()
        self.assertEqual(self.ts.db.execute("SELECT output FROM usage_records").fetchall(), [(400,)])

    def test_a_repeated_codex_count_is_not_counted_twice(self):
        f = os.path.join(self.codex, "rollout-2.jsonl")
        tc = {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 500, "output_tokens": 50},
            "total_token_usage": {"input_tokens": 500, "output_tokens": 50}}}}
        with open(f, "w") as fh:
            fh.write(json.dumps(tc) + "\n" + json.dumps(tc) + "\n")
        self.assertEqual(self.m.scan(), 1)

    def test_store_inside_a_callers_transaction_and_attribution_once_per_place(self):
        calls = []
        self.m.attribute = lambda cwd, br: calls.append((cwd, br)) or ("samvision", None)
        f = os.path.join(self.claude, "e.jsonl")
        with open(f, "w") as fh:
            fh.write("".join(claude_line(f"m{i}") for i in range(20)))
        self.ts.db.execute("BEGIN")
        self.assertEqual(self.m.scan(), 20)
        self.assertTrue(self.ts.db.in_transaction)
        self.ts.db.execute("COMMIT")
        self.assertEqual(len(calls), 1)


class MeterInTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(new_db())
        self.ts = tasks_db()
        self.d = Daemon(cfg(meter={"roots": []}), self.store, None, tasks=self.ts)

    async def asyncTearDown(self):
        self.store.close()

    def test_attribution_by_worktree_then_ticket_key(self):
        t = self.d.task_create({"project": "samvision", "title": "x"}, "jay")
        wt = tempfile.mkdtemp(prefix="wt-")
        tid = self.ts._id_of(t["key"])
        self.ts.db.execute("INSERT INTO ticket_work (ticket_id, worktree, updated_at) VALUES (?, ?, 0)", (tid, wt))
        self.assertEqual(self.d._meter_attribute(os.path.join(wt, "server"), "x"), ("samvision", t["key"]))
        self.assertEqual(self.d._meter_attribute("/srv/server/apps/samvisionai", f"feat/{t['key'].lower()}-thing"),
                         ("samvision", t["key"]))
        self.assertEqual(self.d._meter_attribute("/srv/server/repos/gyst-lifeops", f"{t['key']}"), ("gyst", None))
        self.assertEqual(self.d._meter_attribute("/nowhere", "claude-0"), (None, None))

    def test_work_step_usage_is_recorded_and_a_bad_one_never_fails_the_step(self):
        t = self.d.task_create({"project": "samvision", "title": "x"}, "jay")
        plan = {"summary": "s", "steps": ["a"], "acceptance": ["b"]}
        try:
            self.d.task_work_op(t["key"], "plan", {"plan": plan, "usage": {"model": "claude-opus-5-5",
                                                                           "inputTokens": 10, "outputTokens": 5}},
                                "agent:planner")
        except ActionError:
            pass                                       # the step's own validation is not what this test is about
        try:
            self.d.task_work_op(t["key"], "plan", {"plan": plan, "usage": "garbage"}, "agent:planner")
        except ActionError as e:
            self.assertNotIn("usage", e.message)        # a bad usage object is ignored, never the reason it fails
        rows = self.ts.db.execute("SELECT source, project, ticket_key, actor FROM usage_records").fetchall()
        self.assertEqual(rows, [("reported", "samvision", t["key"], "agent:planner")])
        self.assertTrue(self.d.usage_state()["available"])
        self.assertIn("not billed per token", self.d.usage_state()["note"])


if __name__ == "__main__":
    unittest.main()
