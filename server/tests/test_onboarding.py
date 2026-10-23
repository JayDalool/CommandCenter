"""Onboarding groundwork (ccd/onboarding.py, tasks.db migration 10) and shadow budgets (ccd/budgets.py).

Jay, 2026-10-23: policy-independent groundwork behind a disabled flag (registration records, drafts, validation,
audit, read-only APIs); no permission granted, no agent started, no proposed policy enforced. These tests pin that:
off by default, Jay-only writes with Developer Unlock, records with no active state and no credential, secrets never
stored, and budgets that only report."""
import os
import sqlite3
import tempfile
import unittest

from ccd import budgets, onboarding, security
from ccd.config import task_projects
from ccd.daemon import ActionError, Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db

TOKEN = "t" * 43
DEV = "d" * 43
NOVA = {"id": "nova", "name": "Nova", "title": "Implementation Agent", "template": "implementer",
        "model": {"provider": "anthropic", "model": "claude-sonnet-5-5", "reasoning": "medium"},
        "requested": {"repo.read": "allow", "repo.push": "allow", "prod.deploy": "approval", "repo.merge": "deny"},
        "budget": {"dailyUsd": 20, "monthlyUsd": 300, "alerts": [50, 75, 90]},
        "projects": ["commandcenter"], "reportsTo": "jay"}
PROJECT = {"key": "atlas-app", "name": "Atlas App", "prefix": "ATL", "repo": "JayDalool/atlas-app", "type": "personal"}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def tasks_db():
    return TaskStore(os.path.join(tempfile.mkdtemp(prefix="onb-"), "tasks.db"), task_projects(cfg()))


class Records(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.clock = Clock()
        self.o = onboarding.Onboarding(self.ts.db, clock=self.clock, enabled=True)

    def err(self, status, fn, *a):
        with self.assertRaises(onboarding.OnboardingError) as e:
            fn(*a)
        self.assertEqual(e.exception.status, status, e.exception.message)
        return e.exception.message

    def test_off_by_default_every_read_and_write_is_a_404(self):
        off = onboarding.Onboarding(self.ts.db)
        for fn, args in ((off.summary, ()), (off.agents, ()), (off.drafts, ()), (off.events, ()),
                         (off.validate, ("agent", NOVA)), (off.create_draft, ("agent", NOVA, "jay")),
                         (off.agent_budgets, ()), (off.retire_agent, ("nova", "jay"))):
            self.assertEqual(self.err(404, fn, *args), onboarding.OFF_MESSAGE)
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM onboarding_drafts").fetchone()[0], 0)

    def test_a_draft_is_saved_changed_and_discarded_by_jay_with_events(self):
        d = self.o.create_draft("agent", {"id": "nova", "name": "Nova"}, "jay")
        self.assertEqual((d["state"], d["revision"], d["kind"]), ("open", 1, "agent"))
        self.assertFalse(d["validation"]["ok"])                       # incomplete drafts may be saved
        self.assertIn("required", {e["code"] for e in d["validation"]["errors"]})
        d = self.o.update_draft(d["id"], NOVA, 1, "jay")
        self.assertEqual(d["revision"], 2)
        self.assertTrue(d["validation"]["ok"], d["validation"])
        self.err(409, self.o.update_draft, d["id"], NOVA, 1, "jay")    # someone else's edit is never overwritten
        self.err(400, self.o.update_draft, d["id"], NOVA, "2", "jay")
        d = self.o.discard_draft(d["id"], "jay", "not now")
        self.assertEqual(d["state"], "discarded")
        self.err(409, self.o.update_draft, d["id"], NOVA, 2, "jay")    # closed is final
        self.err(409, self.o.discard_draft, d["id"], "jay")
        kinds = [e["kind"] for e in reversed(self.o.events())]
        self.assertEqual(kinds, ["draft_created", "draft_updated", "draft_discarded"])
        self.assertEqual(self.err(404, self.o.draft, "d-nothere"), "no such draft")

    def test_no_agent_can_write_any_onboarding_record(self):
        d = self.o.create_draft("agent", NOVA, "jay")
        for actor in ("agent:nova", "agent:coordinator", "system:ccd", ""):
            self.err(403, self.o.create_draft, "agent", NOVA, actor)
            self.err(403, self.o.update_draft, d["id"], NOVA, 1, actor)
            self.err(403, self.o.discard_draft, d["id"], actor)
            self.err(403, self.o.register_agent, d["id"], 1, [], actor)
            self.err(403, self.o.retire_agent, "nova", actor)
        self.assertEqual(self.o.draft(d["id"])["revision"], 1)

    def test_a_secret_anywhere_in_a_draft_is_refused_and_nothing_is_stored(self):
        for body in (dict(NOVA, notes="use ghp_abcdefghijklmnopqrstuvwxyz1234"),
                     dict(NOVA, notes="clone https://jay:hunter22@github.com/x/y"),
                     dict(NOVA, spec="api_key = sk-livevalue"),
                     dict(NOVA, model={"provider": "anthropic", "model": "sk-abcdefghijklmnop"}),
                     {"id": "x", "-----BEGIN RSA PRIVATE KEY-----": 1}):
            msg = self.err(400, self.o.create_draft, "agent", body, "jay")
            self.assertIn("nothing was stored", msg)
            self.assertNotIn("ghp_", msg + "")
        d = self.o.create_draft("agent", NOVA, "jay")
        self.err(400, self.o.update_draft, d["id"], dict(NOVA, notes="token: abcdefgh"), 1, "jay")
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM onboarding_drafts").fetchone()[0], 1)
        self.assertNotIn("abcdefgh", self.ts.db.execute("SELECT body FROM onboarding_drafts").fetchone()[0])
        self.err(413, self.o.create_draft, "agent", dict(NOVA, notes="x" * (onboarding.MAX_BODY + 1)), "jay")
        self.err(400, self.o.create_draft, "robot", NOVA, "jay")
        self.err(400, self.o.create_draft, "agent", ["not", "an", "object"], "jay")

    def test_registering_writes_a_record_only_no_active_state_no_grant_no_credential(self):
        d = self.o.create_draft("agent", NOVA, "jay")
        a = self.o.register_agent(d["id"], 1, [], "jay")
        self.assertEqual((a["id"], a["name"], a["status"], a["active"], a["credentials"], a["version"]),
                         ("agent:nova", "Nova", "registered", False, None, 1))
        [v] = a["versions"]
        self.assertEqual(v["config"]["requested"]["prod.deploy"], "approval")
        self.assertEqual(len(v["configSha"]), 64)
        self.assertNotIn("id", v["config"])
        self.assertEqual(self.o.draft(d["id"])["state"], "registered")
        self.assertEqual(self.o.draft(d["id"])["result"], "agent:nova")
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM actor_tokens").fetchone()[0], 0)
        self.err(409, self.o.register_agent, d["id"], 1, [], "jay")        # a draft registers once
        self.assertEqual([e["kind"] for e in a["events"]], ["registered"])
        self.assertEqual(self.o.agent_budgets(), {"agent:nova": NOVA["budget"]})
        self.assertEqual(self.o.agent("nova")["id"], self.o.agent("agent:nova")["id"])
        self.assertEqual(self.o.summary()["agents"], {"registered": 1, "retired": 0})

    def test_registration_refuses_every_validation_error(self):
        self.o.register_agent(self.o.create_draft("agent", NOVA, "jay")["id"], 1, [], "jay")
        bad = {
            "duplicate_id": dict(NOVA, name="Other"),
            "reserved_id": dict(NOVA, id="coordinator", name="Coord"),
            "bad_id": dict(NOVA, id="Nova!", name="Other"),
            "duplicate_name": dict(NOVA, id="nova-2", name=" nova "),
            "reserved_name": dict(NOVA, id="jay-2", name="Jay"),
            "ceiling_exceeded": dict(NOVA, id="merger", name="Merger", requested={"repo.merge": "allow"}),
            "unknown_permission": dict(NOVA, id="perm", name="Perm", requested={"root.everything": "allow"}),
            "bad_grant": dict(NOVA, id="perm2", name="Perm Two", requested={"repo.read": "always"}),
            "unknown_project": dict(NOVA, id="proj", name="Proj", projects=["not-a-project"]),
            "bad_model": dict(NOVA, id="mdl", name="Mdl", model={"provider": "anthropic", "model": "gpt-5-codex"}),
            "bad_budget": dict(NOVA, id="bud", name="Bud", budget={"monthlyUsd": -1}),
            "self_report": dict(NOVA, id="selfie", name="Selfie", reportsTo="agent:selfie"),
            "bad_reports_to": dict(NOVA, id="orph", name="Orph", reportsTo="agent:ghost"),
            "unknown_field": dict(NOVA, id="extra", name="Extra", grants={"repo.merge": "allow"}),
        }
        for code, body in bad.items():
            d = self.o.create_draft("agent", body, "jay")
            self.assertIn(code, {e["code"] for e in d["validation"]["errors"]}, code)
            self.assertIn("fix the draft first", self.err(409, self.o.register_agent, d["id"], 1, [], "jay"))
            self.o.discard_draft(d["id"], "jay")
        self.assertEqual(len(self.o.agents()), 1)
        self.assertTrue(self.o.validate("agent", dict(NOVA, id="lead", name="Lead", reportsTo="agent:nova"))["ok"])

    def test_warnings_must_be_acknowledged_before_registering(self):
        self.o.register_agent(self.o.create_draft("agent", NOVA, "jay")["id"], 1, [], "jay")
        d = self.o.create_draft("agent", dict(NOVA, id="n0va", name="N0va"), "jay")
        self.assertEqual([w["code"] for w in d["validation"]["warnings"]], ["confusable_name"])
        self.assertIn("confusable_name", self.err(409, self.o.register_agent, d["id"], 1, [], "jay"))
        self.err(409, self.o.register_agent, d["id"], 1, "confusable_name", "jay")      # a list, not a string
        a = self.o.register_agent(d["id"], 1, ["confusable_name"], "jay")
        self.assertEqual(a["events"][0]["data"]["acknowledged"], ["confusable_name"])

    def test_retiring_is_final_and_the_id_is_never_reused(self):
        self.o.register_agent(self.o.create_draft("agent", NOVA, "jay")["id"], 1, [], "jay")
        self.clock.t -= 3600                                             # a clock stepped back still retires
        a = self.o.retire_agent("agent:nova", "jay", "replaced")
        self.assertEqual((a["status"], a["active"]), ("retired", False))
        self.err(409, self.o.retire_agent, "nova", "jay")
        self.err(404, self.o.retire_agent, "ghost", "jay")
        v = self.o.validate("agent", NOVA)
        self.assertIn("retired_id", {e["code"] for e in v["errors"]})
        v = self.o.validate("agent", dict(NOVA, id="nova-two"))
        self.assertTrue(v["ok"])
        self.assertIn("retired_name", {w["code"] for w in v["warnings"]})
        self.assertEqual(self.o.agent_budgets(), {})                     # a retired agent has no budget line

    def test_project_drafts_are_checked_against_the_registry_and_never_become_projects(self):
        self.assertTrue(self.o.validate("project", PROJECT)["ok"])
        cases = {"duplicate_key": dict(PROJECT, key="samvision"), "reserved_key": dict(PROJECT, key="commandcenter"), "prefix_taken": dict(PROJECT, prefix="GM"),
                 "repo_already_bound": dict(PROJECT, repo="jaydalool/commandcenter"),
                 "bad_repo": dict(PROJECT, repo="https://github.com/JayDalool/x"),
                 "duplicate_name": dict(PROJECT, name="samvision"), "bad_type": dict(PROJECT, type="startup"),
                 "bad_prefix": dict(PROJECT, prefix="9AB")}
        for code, body in cases.items():
            self.assertIn(code, {e["code"] for e in self.o.validate("project", body)["errors"]}, code)
        self.assertIn("prefix_taken", {e["code"] for e in self.o.validate("project", dict(PROJECT, prefix="VN"))["errors"]})
        self.assertIn("laptop_only", {w["code"] for w in self.o.validate("project", dict(PROJECT, type="employer"))["warnings"]})
        d = self.o.create_draft("project", PROJECT, "jay")
        self.assertIn("registry", self.err(409, self.o.register_agent, d["id"], 1, [], "jay"))
        self.assertEqual({w["code"] for w in self.o.validate("project", PROJECT)["warnings"]}, {"draft_key", "draft_prefix"})
        self.assertEqual(self.o.validate("project", PROJECT, except_id=d["id"])["warnings"], [])

    def test_a_record_never_lands_without_its_event(self):
        d = self.o.create_draft("agent", NOVA, "jay")
        real = self.o._event

        def boom(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        self.o._event = boom
        for op in (lambda: self.o.register_agent(d["id"], 1, [], "jay"), lambda: self.o.discard_draft(d["id"], "jay"),
                   lambda: self.o.create_draft("agent", NOVA, "jay")):
            with self.assertRaises(sqlite3.OperationalError):
                op()
        self.o._event = real
        self.assertEqual(self.o.agents(), [])
        self.assertEqual(self.o.draft(d["id"])["state"], "open")
        self.assertEqual(len(self.o.drafts()), 1)

    def test_open_drafts_are_capped(self):
        for _ in range(onboarding.MAX_OPEN_DRAFTS):
            self.o.create_draft("project", {}, "jay")
        self.err(429, self.o.create_draft, "project", {}, "jay")

    def test_the_schema_refuses_what_the_module_never_does(self):
        self.o.register_agent(self.o.create_draft("agent", NOVA, "jay")["id"], 1, [], "jay")
        db = self.ts.db
        for sql in ("DELETE FROM agent_registrations",
                    "UPDATE agent_registrations SET status='active'",
                    "UPDATE agent_registrations SET display_name='Nova 2'",
                    "UPDATE agent_registrations SET status='retired', retired_at=1, retired_by='agent:x'",
                    "INSERT INTO agent_registrations (id, display_name, status, created_at, created_by) "
                    "VALUES ('agent:x1', 'X', 'registered', 1, 'agent:nova')",
                    "INSERT INTO agent_registrations (id, display_name, status, created_at, created_by) "
                    "VALUES ('agent:Bad', 'X', 'registered', 1, 'jay')",
                    "INSERT INTO agent_registrations (id, display_name, status, created_at, created_by) "
                    "VALUES ('nova2', 'X', 'registered', 1, 'jay')",
                    "UPDATE agent_config_versions SET config='{}'", "DELETE FROM agent_config_versions",
                    "UPDATE onboarding_drafts SET body='{}'", "DELETE FROM onboarding_drafts",
                    "UPDATE onboarding_events SET kind='retired'", "DELETE FROM onboarding_events",
                    "INSERT INTO onboarding_events (subject, at, kind, actor) VALUES ('agent:nova', 1, 'registered', "
                    "'agent:nova')",
                    "INSERT INTO onboarding_events (subject, at, kind, actor) VALUES ('agent:nova', 1, 'activated', "
                    "'jay')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql)
        self.o.retire_agent("nova", "jay")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE agent_registrations SET status='registered', retired_at=NULL, retired_by=NULL")


class Budgets(unittest.TestCase):
    def test_assess_alerts_before_the_limit_and_holds_at_it(self):
        lim = {"usd": 100, "tokens": None}
        self.assertEqual(budgets.assess(10, 0, {"usd": None, "tokens": None})["state"], "none")
        self.assertEqual(budgets.assess(10, 0, lim)["state"], "ok")
        a = budgets.assess(76, 0, lim)
        self.assertEqual((a["state"], a["threshold"], a["pct"]), ("alert", 75, 76.0))
        self.assertEqual(budgets.assess(100, 0, lim)["state"], "hold")
        self.assertEqual(budgets.assess(0, 0, {"usd": 0, "tokens": None})["state"], "hold")   # zero = no billable work
        self.assertEqual(budgets.assess(1, 950, {"usd": 100, "tokens": 1000})["threshold"], 90)  # worst of the two
        self.assertTrue(budgets.assess(40, 0, lim, elapsed=0.25)["onCourseToHold"])
        self.assertFalse(budgets.assess(10, 0, lim, elapsed=0.5)["onCourseToHold"])
        self.assertEqual(budgets.assess(60, 0, lim, alerts=(60,))["threshold"], 60)

    def test_one_agent_over_its_limit_never_stops_its_project(self):
        holds = {("agent", "agent:nova")}
        w = lambda agent, project="commandcenter", kind="build", billable=True: budgets.would_start(  # noqa: E731
            {"agent": agent, "project": project, "kind": kind, "billable": billable}, holds)
        self.assertFalse(w("agent:nova")["start"])
        self.assertIn("checkpoints", w("agent:nova")["inProgress"])
        self.assertTrue(w("agent:atlas")["start"])                         # same project, other agent
        holds.add(("project", "gyst"))
        self.assertFalse(w("agent:atlas", "gyst")["start"])
        self.assertTrue(w("agent:atlas", "samvision")["start"])            # other projects carry on
        holds.add(("company", "*"))
        self.assertFalse(w("agent:atlas", "samvision")["start"])
        for kind in sorted(budgets.SAFETY_KINDS):                           # safety is never held
            self.assertTrue(w("agent:nova", "gyst", kind)["start"], kind)
        self.assertTrue(w("agent:nova", billable=False)["start"])

    def test_an_override_raises_a_limit_until_it_expires_and_never_lowers_it(self):
        lim = {"usd": 100, "tokens": None}
        self.assertEqual(budgets.effective_limit(lim, {"usd": 50, "until": 10}, now=5)["usd"], 150)
        self.assertEqual(budgets.effective_limit(lim, {"usd": 50, "until": 10}, now=10)["usd"], 100)
        self.assertEqual(budgets.effective_limit(lim, {"usd": -80, "until": 10}, now=5)["usd"], 100)
        self.assertIsNone(budgets.effective_limit(lim, {"tokens": 5, "until": 10}, now=5)["tokens"])

    def test_the_report_reads_the_meter_and_holds_nothing(self):
        ts = tasks_db()
        now = 1_800_000_000.0
        start, _ = budgets.period_bounds(now, "month")
        rows = [("claude", "r1", "commandcenter", None, 60.0, 1000), ("claude", "r2", "gyst", None, 5.0, 100),
                ("codex", "r3", "gyst", None, None, 500_000), ("reported", "r4", "commandcenter", "agent:nova", 25.0, 10),
                ("claude", "old", "commandcenter", None, 999.0, 1)]
        for src, ref, project, actor, cost, tokens in rows:
            ts.db.execute("INSERT INTO usage_records (at, source, ref, project, actor, input, cost_usd) "
                          "VALUES (?,?,?,?,?,?,?)", (start - 10 if ref == "old" else now - 60, src, ref, project, actor,
                                                     tokens, cost))
        r = budgets.report(ts.db, now, company={"monthly_usd": 100, "daily_usd": 1000},
                           projects={"commandcenter": {"monthly_usd": 50}, "gyst": {"monthly_tokens": 400_000}},
                           agents={"agent:nova": {"monthlyUsd": 100, "dailyUsd": 20}, "agent:atlas": {}})
        got = {(x["scope"], x["key"], x["period"]): (x["state"], x["spentUsd"], x["source"]) for x in r["lines"]}
        self.assertEqual(got[("company", "*", "month")], ("alert", 65.0, "measured"))   # reported usage not added in
        self.assertEqual(got[("project", "commandcenter", "month")], ("hold", 60.0, "measured"))
        self.assertEqual(got[("project", "gyst", "month")][0], "hold")                   # Codex counted by tokens
        self.assertEqual(got[("agent", "agent:nova", "month")], ("ok", 25.0, "reported"))
        self.assertEqual(got[("agent", "agent:nova", "day")][0], "hold")
        self.assertNotIn(("agent", "agent:atlas", "month"), got)
        self.assertEqual(r["wouldHold"], [{"scope": "agent", "key": "agent:nova"},
                                          {"scope": "project", "key": "commandcenter"},
                                          {"scope": "project", "key": "gyst"}])
        self.assertEqual((r["mode"], r["enforced"]), ("shadow", False))
        gyst = next(x for x in r["lines"] if x["key"] == "gyst")
        self.assertEqual(gyst["unpricedReplies"], 1)


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(new_db())

    async def asyncTearDown(self):
        self.store.close()

    async def test_off_by_default_and_nothing_is_logged(self):
        d = Daemon(cfg(meter={"enabled": False}), self.store, None, tasks=tasks_db())
        self.assertFalse(d.onboarding_on)
        d._log_onboarding()
        self.assertFalse(any(e["kind"].startswith("onboarding") for e in self.store.since(0)))
        for fn in (d.onboarding_state, d.onboarding_agents, d.onboarding_budgets,
                   lambda: d.act_onboarding("create", "jay", True, kind="agent", body=NOVA)):
            with self.assertRaises(ActionError) as e:
                fn()
            self.assertEqual(e.exception.status, 404)
        d2 = Daemon(cfg(meter={"enabled": False}, onboarding_groundwork="yes"), self.store, None, tasks=tasks_db())
        self.assertFalse(d2.onboarding_on)                                   # only the literal true turns it on

    async def test_writes_need_jay_and_developer_unlock_and_registering_is_logged(self):
        d = Daemon(cfg(meter={"enabled": False}, onboarding_groundwork=True), self.store, None, tasks=tasks_db())
        d._log_onboarding()
        self.assertTrue(any(e["kind"] == "onboarding.groundwork" for e in self.store.since(0)))
        for actor, dev in (("jay", False), ("agent:nova", True)):
            with self.assertRaises(ActionError) as e:
                d.act_onboarding("create", actor, dev, kind="agent", body=NOVA)
            self.assertEqual(e.exception.status, 403)
        dr = d.act_onboarding("create", "jay", True, kind="agent", body=NOVA)
        a = d.act_onboarding("register", "jay", True, id=dr["id"], revision=1, acknowledge=[])
        self.assertEqual(a["status"], "registered")
        self.assertTrue(any(e["kind"] == "onboarding.registered" for e in self.store.since(0)))
        with self.assertRaises(ActionError) as e:
            d.act_onboarding("launch", "jay", True)
        self.assertEqual(e.exception.status, 400)
        self.assertEqual(d.onboarding_budgets()["enforced"], False)

    async def test_no_task_system(self):
        d = Daemon(cfg(onboarding_groundwork=True), self.store, None)
        with self.assertRaises(ActionError) as e:
            d.onboarding_state()
        self.assertEqual(e.exception.status, 404)


class OverHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(new_db())

    def client(self, on):
        from starlette.testclient import TestClient
        from ccd.api import create_app
        self.ts = tasks_db()
        self.d = Daemon(cfg(meter={"enabled": False}, onboarding_groundwork=on), self.store, None, tasks=self.ts)
        self.d.dev_gate = security.DeveloperGate(DEV)
        guarded, _app = create_app(self.d, TOKEN, 7799)
        self.c = TestClient(guarded, base_url="http://127.0.0.1:7799")
        self.h = {"x-ccd-token": TOKEN}

    async def asyncTearDown(self):
        self.store.close()

    def unlock(self):
        r = self.c.post("/api/developer/unlock", headers=self.h, json={"token": DEV})
        return dict(self.h, **{"x-ccd-developer": r.json()["session"]})

    ROUTES = (("GET", "/api/onboarding"), ("GET", "/api/onboarding/agents"), ("GET", "/api/onboarding/agents/nova"),
              ("POST", "/api/onboarding/agents/nova/retire"), ("GET", "/api/onboarding/drafts"),
              ("POST", "/api/onboarding/drafts"), ("GET", "/api/onboarding/drafts/d-000000000000"),
              ("PUT", "/api/onboarding/drafts/d-000000000000"), ("POST", "/api/onboarding/drafts/d-000000000000/discard"),
              ("POST", "/api/onboarding/drafts/d-000000000000/register"), ("POST", "/api/onboarding/validate"),
              ("GET", "/api/onboarding/events"), ("GET", "/api/onboarding/budgets"))

    def test_off_every_route_is_a_404_even_with_developer_unlock(self):
        self.client(False)
        dev = self.unlock()
        for method, path in self.ROUTES:
            r = self.c.request(method, path, headers=dev, json={"kind": "agent", "body": NOVA} if method != "GET" else None)
            self.assertEqual(r.status_code, 404, (method, path))
            self.assertEqual(r.json()["error"], onboarding.OFF_MESSAGE)
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM onboarding_drafts").fetchone()[0], 0)
        self.assertEqual(self.c.get("/api/onboarding", headers={}).status_code, 401)   # still behind ccd's token

    def test_on_jay_with_unlock_drafts_registers_and_retires_and_each_write_is_audited(self):
        self.client(True)
        agent = dict(self.h, **{"x-ccd-actor": "agent:nova"})
        self.assertEqual(self.c.post("/api/onboarding/drafts", headers=self.h, json={"kind": "agent", "body": NOVA})
                         .status_code, 403)                                              # Jay without Unlock
        dev = self.unlock()
        self.assertEqual(self.c.post("/api/onboarding/drafts", headers=dict(dev, **{"x-ccd-actor": "agent:nova"}),
                                     json={"kind": "agent", "body": NOVA}).status_code, 403)
        v = self.c.post("/api/onboarding/validate", headers=agent, json={"kind": "agent", "body": NOVA}).json()
        self.assertTrue(v["ok"])                                                         # read-only, for anyone
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM onboarding_drafts").fetchone()[0], 0)
        r = self.c.post("/api/onboarding/drafts", headers=dev, json={"kind": "agent", "body": dict(NOVA, title="")})
        self.assertEqual(r.status_code, 200)
        did = r.json()["id"]
        r = self.c.put(f"/api/onboarding/drafts/{did}", headers=dev, json={"body": NOVA, "revision": 1})
        self.assertEqual(r.json()["revision"], 2)
        self.assertEqual(self.c.get(f"/api/onboarding/drafts/{did}", headers=agent).json()["validation"]["ok"], True)
        self.assertEqual(self.c.post(f"/api/onboarding/drafts/{did}/register", headers=agent,
                                     json={"revision": 2}).status_code, 403)
        a = self.c.post(f"/api/onboarding/drafts/{did}/register", headers=dev, json={"revision": 2}).json()
        self.assertEqual((a["id"], a["status"], a["active"]), ("agent:nova", "registered", False))
        self.assertEqual([x["id"] for x in self.c.get("/api/onboarding/agents", headers=self.h).json()["agents"]],
                         ["agent:nova"])
        self.assertEqual(self.c.get("/api/onboarding/agents/agent:nova", headers=self.h).json()["version"], 1)
        self.assertEqual(self.c.get("/api/onboarding/drafts?state=registered", headers=self.h).json()["drafts"][0]["id"],
                         did)
        self.assertEqual(self.c.get("/api/onboarding/drafts?state=weird", headers=self.h).status_code, 400)
        r = self.c.post("/api/onboarding/agents/nova/retire", headers=dev, json={"reason": "done"})
        self.assertEqual(r.json()["status"], "retired")
        self.assertEqual(self.c.get("/api/onboarding/events?limit=x", headers=self.h).status_code, 400)
        kinds = [e["kind"] for e in self.c.get("/api/onboarding/events", headers=self.h).json()["events"]]
        self.assertEqual(kinds[0], "retired")
        audit = [(e["method"], e["path"], e["status"], e["via"]) for e in
                 self.c.get("/api/audit", headers=self.h).json()["events"] if e["path"].startswith("/api/onboarding")]
        self.assertIn(("POST", "/api/onboarding/agents/nova/retire", 200, "developer"), audit)
        self.assertIn(("POST", "/api/onboarding/drafts", 403, "none"), audit)             # refusals are audited too
        secret = self.c.post("/api/onboarding/drafts", headers=dev,
                             json={"kind": "agent", "body": dict(NOVA, notes="ghp_abcdefghijklmnopqrstuvwxyz12")})
        self.assertEqual(secret.status_code, 400)
        self.assertNotIn("ghp_", secret.text)
        budget = self.c.get("/api/onboarding/budgets", headers=self.h).json()
        self.assertEqual((budget["mode"], budget["enforced"]), ("shadow", False))
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM actor_tokens").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
