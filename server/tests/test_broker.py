"""Capability Broker, Phase 2 shadow step 3 (ccd/broker.py): the eight checks, the record, and that recording never
changes what ccd does."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from ccd import broker, identity
from ccd.config import task_projects
from ccd.daemon import Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db
from .test_auto_merge import Base as AutoMergeBase

SYSTEM = broker.system_who()
JAY = identity.resolve("jay", True, None)
JAY_NO_UNLOCK = identity.resolve("jay", False, None)
AGENT = {"resolvedActor": "agent:builder", "assertedActor": "agent:builder", "via": "token", "reasons": []}


def tasks_db():
    return TaskStore(os.path.join(tempfile.mkdtemp(prefix="br-"), "tasks.db"), task_projects(cfg()))


def results(d):
    return {t: v["result"] for t, v in d["terms"].items()}


class Check(unittest.TestCase):
    def test_ccd_merging_with_the_engine_saying_auto_passes_every_term(self):
        d = broker.check("pr.merge", SYSTEM, "commandcenter", "ok", {"engine": "auto"})
        self.assertEqual((d["wouldRefuse"], d["reasons"], d["enforced"], d["kind"]), (False, [], False, "system"))
        self.assertEqual(set(d["terms"]), set(broker.TERMS))
        self.assertEqual(results(d)["approval"], "ok")

    def test_the_engine_not_saying_auto_or_not_known_would_refuse(self):
        self.assertEqual(broker.check("pr.merge", SYSTEM, "x", "ok", {"engine": "jay"})["reasons"],
                         ["approval:engine_not_auto"])
        self.assertEqual(broker.check("pr.merge", SYSTEM, "x", "ok", {"engine": None})["reasons"],
                         ["approval:engine_unknown"])

    def test_jay_needs_his_unlocked_session(self):
        self.assertFalse(broker.check("pr.merge", JAY, "x", "ok", {"developer": True})["wouldRefuse"])
        self.assertFalse(broker.check("go_live.approve", JAY, "x", "ok", {"developer": True})["wouldRefuse"])
        d = broker.check("go_live.approve", JAY_NO_UNLOCK, "x", "ok", {"developer": False})
        # without Unlock a "jay" claim proves nobody: unverified, so not even allowed to ask
        self.assertEqual(d["reasons"], ["actor:unverified", "capability:not_allowed_for_actor", "approval:no_jay_session"])
        # `developer` only counts for a request that proves to be Jay
        self.assertIn("approval:no_jay_session", broker.check("go_live.approve", AGENT, "x", "ok",
                                                              {"developer": True})["reasons"])

    def test_an_agent_is_unknown_until_grants_and_task_modes_exist(self):
        d = broker.check("deploy.request", AGENT, "x", "ok")
        self.assertEqual(d["reasons"], ["agent_grant:no_agent_grants", "task_mode:no_task_mode"])
        self.assertEqual(results(d)["capability"], "ok")
        self.assertIn("capability:not_allowed_for_actor", broker.check("pr.merge", AGENT, "x", "ok")["reasons"])

    def test_an_unverified_caller_is_denied_on_the_actor_term(self):
        who = identity.resolve("agent:builder", False, None)
        d = broker.check("pane.input", who, "x", "ok")
        self.assertEqual(d["terms"]["actor"], {"result": "deny", "reason": "unverified"})
        self.assertEqual(d["kind"], "unknown")

    def test_writes_to_jays_checkout_are_never_a_phase2_capability(self):
        for verb, who in (("repo.write", JAY), ("worktree.remove", SYSTEM)):
            self.assertEqual(broker.check(verb, who, "x", "ok", {"developer": True})["reasons"],
                             ["capability:writes_jay_checkout"])

    def test_project_unknown_verb_node_and_deploy_approval(self):
        self.assertEqual(broker.check("pane.input", JAY, "x", "paused")["reasons"], ["project:project_paused"])
        self.assertEqual(broker.check("pane.input", JAY, "x", "missing")["reasons"], ["project:no_profile"])
        self.assertEqual(results(broker.check("pane.input", JAY, None, None))["project"], "n/a")
        self.assertEqual(broker.check("rm.rf", JAY, None)["reasons"], ["capability:unknown_verb"])
        self.assertEqual(broker.check("pane.input", JAY, None, node="laptop")["reasons"], ["node:unknown_node"])
        self.assertEqual(broker.check("deploy.record", JAY, "x", "ok", {"deployApproved": False})["reasons"],
                         ["approval:no_deploy_approval"])
        self.assertFalse(broker.check("deploy.record", JAY, "x", "ok", {"deployApproved": True})["wouldRefuse"])

    def test_every_reason_is_listed(self):
        for who in (SYSTEM, JAY, JAY_NO_UNLOCK, AGENT, identity.resolve(None, False, None)):
            for verb in (*broker.VERBS, "nope"):
                for profile in ("ok", "paused", "missing", None):
                    for approval in ({}, {"engine": "jay"}, {"engine": None}, {"developer": True}):
                        for r in broker.check(verb, who, "x" if profile else None, profile, approval)["reasons"]:
                            self.assertIn(r.split(":", 1)[1], broker.REASONS)


class Record(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.sh = broker.Shadow(self.ts.db)

    def put(self, verb="pr.merge", who=SYSTEM, approval=None, project="samvision"):
        self.sh.observe(verb, project, "t", who, broker.check(verb, who, project, "ok", approval or {"engine": "auto"}))

    def test_a_chain_that_refuses_enforced_edits_and_deletes(self):
        self.put()
        self.put("repo.write", JAY, {"developer": True})
        self.assertEqual(self.sh.errors, 0)
        rows = self.ts.db.execute("SELECT verb, would_refuse, enforced, reasons FROM broker_observations").fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [("pr.merge", 0, 0), ("repo.write", 1, 0)])
        self.assertEqual(json.loads(rows[1][3]), ["capability:writes_jay_checkout"])
        self.assertTrue(self.sh.verify(full=True)["ok"])
        for sql in ("UPDATE broker_observations SET would_refuse=0", "DELETE FROM broker_observations",
                    "INSERT INTO broker_observations (at, verb, target, actor, via, terms, would_refuse, enforced, "
                    "version, prev_sha, sha) VALUES (0, 'x', '', 'jay', 'none', '{}', 0, 1, 1, '', 'y')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.ts.db.execute(sql)
        self.ts.db.execute("DROP TRIGGER broker_observations_append_only_u")
        self.ts.db.execute("UPDATE broker_observations SET would_refuse=0 WHERE verb='repo.write'")
        self.assertEqual(self.sh.verify(full=True)["ok"], False)

    def test_summary_and_recent(self):
        self.put()
        self.put("pane.input", AGENT, {})
        s = self.sh.summary()
        self.assertEqual((s["total"], s["wouldRefuse"], s["enforced"]), (2, 1, False))
        self.assertEqual(s["byVerb"]["pane.input"], {"total": 1, "wouldRefuse": 1})
        self.assertEqual(s["byReason"], {"agent_grant:no_agent_grants": 1, "task_mode:no_task_mode": 1})
        self.assertEqual(s["byTerm"]["agent_grant"], {"ok": 0, "n/a": 1, "deny": 0, "unknown": 1})
        r = self.sh.recent(1)
        self.assertEqual((len(r), r[0]["verb"], r[0]["actor"], r[0]["enforced"]), (1, "pane.input", "agent:builder",
                                                                                     False))

    def test_a_failure_is_counted_never_raised(self):
        self.sh.observe("pr.merge", "x", "t", SYSTEM, {"terms": {}})       # missing terms
        self.assertEqual(self.sh.errors, 1)
        self.ts.db.execute("BEGIN")
        self.put()                                                          # inside the caller's transaction
        self.ts.db.execute("ROLLBACK")
        self.assertEqual((self.sh.errors, self.sh.summary()["total"]), (1, 0))


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(new_db())
        self.ts = tasks_db()

    async def asyncTearDown(self):
        self.store.close()

    def rows(self):
        return self.ts.db.execute("SELECT verb, project, actor, via, would_refuse FROM broker_observations").fetchall()

    async def test_switch_off_records_nothing(self):
        d = Daemon(cfg(), self.store, None, tasks=self.ts)
        self.assertFalse(d.broker_shadow_on)
        d._broker("pane.input", "samvision", "t")
        self.assertEqual(self.rows(), [])
        self.assertEqual(d.broker_state()["brokerShadow"], False)

    async def test_ccd_on_its_own_is_system_and_a_request_is_resolved(self):
        d = Daemon(cfg(phase2_broker_shadow=True), self.store, None, tasks=self.ts)
        d._broker("worktree.remove", "samvision", "SV-1: /x")
        tok = d.actor_tokens.issue("agent:builder", "jay")["token"]
        ctx = broker.REQUEST.set({"developer": False, "token": tok, "asserted": "agent:builder"})
        try:
            d._broker("deploy.request", "samvision", "SV-1")
        finally:
            broker.REQUEST.reset(ctx)
        self.assertEqual(self.rows(), [("worktree.remove", "samvision", "system:ccd", "system", 1),
                                       ("deploy.request", "samvision", "agent:builder", "token", 1)])
        st = d.broker_state()
        self.assertEqual((st["summary"]["total"], st["chain"]["ok"], st["errors"], st["enforced"]), (2, True, 0, False))

    async def test_a_ticket_closed_by_a_request_tears_down_as_ccd_not_as_that_request(self):
        import asyncio
        d = Daemon(cfg(phase2_broker_shadow=True), self.store, None, tasks=self.ts)
        key = self.ts.create("samvision", "done soon")[0]["key"]
        seen = []

        async def exit_when_idle(k):
            seen.append(broker.REQUEST.get())
            return None
        ctx = broker.REQUEST.set({"developer": True, "token": None, "asserted": "jay"})
        try:
            with mock.patch.object(d, "_exit_when_idle", exit_when_idle):
                d._closed_soon(key)
                await asyncio.sleep(0.05)
            self.assertEqual(broker.REQUEST.get()["asserted"], "jay")          # the request's own context is kept
        finally:
            broker.REQUEST.reset(ctx)
        self.assertEqual(seen, [None])

    async def test_a_broken_record_never_reaches_the_caller(self):
        d = Daemon(cfg(phase2_broker_shadow=True), self.store, None, tasks=self.ts)
        with mock.patch.object(broker, "check", side_effect=RuntimeError("boom")):
            d._broker("pane.input", "samvision", "t")
        with mock.patch.object(d.policy, "profile", side_effect=RuntimeError("boom")):
            d._broker("pane.input", "samvision", "t")
        self.assertEqual((d.broker.errors, self.rows()), (2, []))
        with mock.patch.object(d.broker, "summary", side_effect=sqlite3.OperationalError("locked")):
            self.assertEqual(d.broker_state()["enforced"], False)


class AutoMerge(AutoMergeBase):
    async def test_an_auto_merge_is_recorded_and_merges_exactly_as_before(self):
        self.daemon = self.make(phase2_broker_shadow=True)
        k = self.ready()
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)                       # merged, the same one call
        rows = self.tickets.db.execute("SELECT verb, project, actor, target, terms FROM broker_observations").fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [("pr.merge", "commandcenter", "system:ccd")])
        self.assertIn(k, rows[0][3])
        # this fixture has no CI checks, so the engine's target policy says "jay": the record says so; ccd merged anyway
        self.assertEqual(json.loads(rows[0][4])["approval"], {"result": "deny", "reason": "engine_not_auto"})

    async def test_with_the_switch_off_nothing_is_recorded(self):
        self.ready()
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        self.assertEqual(self.tickets.db.execute("SELECT COUNT(*) FROM broker_observations").fetchone()[0], 0)


class OverHttp(unittest.IsolatedAsyncioTestCase):
    def client(self, on):
        from starlette.testclient import TestClient
        from ccd.api import create_app
        self.store = Store(new_db())
        self.ts = tasks_db()
        self.d = Daemon(cfg(phase2_broker_shadow=on), self.store, None, tasks=self.ts)
        guarded, _app = create_app(self.d, "t" * 43, 7799)
        return TestClient(guarded, base_url="http://127.0.0.1:7799")

    async def asyncTearDown(self):
        self.store.close()

    def deploy_request(self, on, token=None):
        c = self.client(on)
        key = self.ts.create("samvision", "ship it")[0]["key"]
        h = {"x-ccd-token": "t" * 43, "x-ccd-actor": "agent:builder"}
        if token:
            h["x-ccd-actor-token"] = self.d.actor_tokens.issue("agent:builder", "jay")["token"]
        r = c.post(f"/api/tasks/{key}/work/deploy-request", headers=h, json={"env": "live", "what": "x"})
        rows = self.ts.db.execute("SELECT verb, project, actor, via, reasons FROM broker_observations").fetchall()
        return r.status_code, r.json(), rows

    def test_a_request_is_recorded_with_who_it_proves_to_be_and_answers_as_before(self):
        on = self.deploy_request(True, token=True)
        off = self.deploy_request(False, token=True)
        self.assertEqual(on[:2], off[:2])                                   # the same answer, switch on or off
        self.assertEqual(off[2], [])
        self.assertEqual([r[:4] for r in on[2]], [("deploy.request", "samvision", "agent:builder", "token")])
        self.assertEqual(json.loads(on[2][0][4]), ["agent_grant:no_agent_grants", "task_mode:no_task_mode"])
        st = self.client(True).get("/api/broker", headers={"x-ccd-token": "t" * 43})
        self.assertEqual((st.status_code, st.json()["enforced"]), (200, False))
        self.assertEqual(self.client(True).get("/api/broker?limit=0", headers={"x-ccd-token": "t" * 43}).status_code,
                         400)

    def test_without_a_token_the_caller_is_unverified(self):
        _s, _b, rows = self.deploy_request(True)
        self.assertEqual(rows[0][2:4], ("unknown", "none"))
        self.assertIn("actor:unverified", json.loads(rows[0][4]))


if __name__ == "__main__":
    unittest.main()
