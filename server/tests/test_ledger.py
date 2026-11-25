"""Decision and Approval records (ccd/ledger.py, tasks.db migration 7): a mirror of today's gates and answered
questions. The schema keeps them honest; the daemon records them; nothing they say changes what ccd does."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from ccd import ledger, profiles, registry
from ccd.config import task_projects
from ccd.daemon import Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db
from .test_auto_merge import PLAN, FakeGh
from .test_merge_policy import HEAD, f, view

POL = profiles.load()
HEAD2 = "cd" * 20


class Schema(unittest.TestCase):
    def setUp(self):
        self.ts = TaskStore(os.path.join(tempfile.mkdtemp(prefix="lg-"), "tasks.db"), task_projects(cfg()))
        self.lg = ledger.Ledger(self.ts.db)
        self.t, _ = self.ts.create("gyst", "x")
        self.tid = self.ts._id_of(self.t["key"])

    def test_decisions_are_append_only_and_a_change_supersedes(self):
        a = self.lg.add_decision(project="gyst", question="q?", decision="yes", decided_by="jay", source="policy",
                                 source_ref="D-900")
        self.assertEqual(self.lg.add_decision(project="gyst", question="q?", decision="yes", decided_by="jay",
                                              source="policy", source_ref="D-900"), a)          # idempotent
        b = self.lg.add_decision(project="gyst", question="q?", decision="no", decided_by="jay", source="policy",
                                 source_ref="D-900")
        rows = self.lg.decisions()
        self.assertEqual([(r["id"], r["supersedes"], r["current"]) for r in rows], [(b, a, True), (a, None, False)])
        for sql in ("UPDATE decisions SET decision='maybe'", "DELETE FROM decisions"):
            with self.assertRaises(sqlite3.DatabaseError):
                self.ts.db.execute(sql)

    def test_an_approval_moves_only_forward_is_bound_to_its_subject_and_only_jay_approves(self):
        aid = self.lg.request(self.tid, "gyst", "merge", HEAD, "approved and green")
        db = self.ts.db
        for sql in ("UPDATE approvals SET subject_hash='x'", "UPDATE approvals SET state='consumed'",
                    "UPDATE approvals SET state='approved', decided_by='agent:coordinator', decided_at=1",
                    "DELETE FROM approvals"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):                       # one open approval per gate
            db.execute("INSERT INTO approvals (project, ticket_id, subject_type, subject_hash, action, state, "
                       "requested_at, requested_by) VALUES ('gyst', ?, 'merge', 'h', 'a', 'pending', 1, 'x')", (self.tid,))
        self.lg._set(aid, "approved", by="jay", via="ui")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE approvals SET state='pending'")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE approvals SET decided_by='jay', via='slack'")    # who and how: recorded once
        self.lg._set(aid, "consumed")
        with self.assertRaises(sqlite3.DatabaseError):
            self.lg._set(aid, "void", reason="x")                                # consumed is final

    def test_a_request_inside_a_callers_transaction_uses_a_savepoint(self):
        db = self.ts.db
        db.execute("BEGIN")
        aid = self.lg.request(self.tid, "gyst", "merge", HEAD, "inside")
        db.execute("ROLLBACK")                       # the caller's rollback takes the request with it
        self.assertIsNotNone(aid)
        self.assertEqual(self.lg.approvals(), [])
        self.lg.request(self.tid, "gyst", "merge", HEAD, "outside")
        self.assertEqual(len(self.lg.approvals()), 1)

    def test_subject_hashes(self):
        w = {"review": {"head": HEAD}, "plan": {"summary": "a"}, "deploy": {"env": "live", "what": "x"}}
        self.assertEqual(ledger.subject_hash("merge", "GYST-1", w), HEAD)
        p = ledger.subject_hash("plan", "GYST-1", w)
        self.assertRegex(p, r"^[0-9a-f]{64}$")
        self.assertNotEqual(p, ledger.subject_hash("plan", "GYST-1", dict(w, plan={"summary": "b"})))
        self.assertNotEqual(ledger.subject_hash("deploy", "GYST-1", w),
                            ledger.subject_hash("deploy", "GYST-1", dict(w, deploy={"env": "live", "what": "y"})))

    def test_a_policy_decision_reverted_to_an_earlier_text_is_recorded_again(self):
        kw = dict(project="gyst", question="q?", decided_by="jay", source="policy", source_ref="D-901")
        a = self.lg.add_decision(decision="A", **kw)
        b = self.lg.add_decision(decision="B", **kw)
        c = self.lg.add_decision(decision="A", **kw)                      # A → B → A: no IntegrityError
        self.assertEqual([(r["id"], r["decision"], r["supersedes"]) for r in self.lg.decisions()][:3],
                         [(c, "A", b), (b, "B", a), (a, "A", None)])
        self.assertNotEqual(self.lg.add_decision(decision="A", **dict(kw, project="gyst,mfe")), c)   # scope counts

    def test_approved_or_consumed_needs_jay_even_when_null(self):
        aid = self.lg.request(self.tid, "gyst", "plan", "h", "x")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ts.db.execute("UPDATE approvals SET state='approved' WHERE id=?", (aid,))

    def test_dates_keep_their_zone(self):
        self.assertEqual(ledger._date_ts("2026-10-21"), 1792540800.0)
        self.assertEqual(ledger._date_ts("2026-10-21T10:00:00+02:00"), 1792540800.0 + 8 * 3600)
        self.assertIsNone(ledger._date_ts("soon"))

    def test_project_filters_approvals_too(self):
        self.lg.request(self.tid, "gyst", "plan", "h", "x")
        self.assertEqual(len(self.lg.approvals(project="gyst")), 1)
        self.assertEqual(self.lg.approvals(project="mfe"), [])
        self.lg.add_decision(project="samvision,mfe", question="q", decision="d", decided_by="jay", source="policy",
                             source_ref="D-902")
        self.assertEqual(len(self.lg.decisions(project="mfe")), 1)
        self.assertEqual(self.lg.decisions(project="%"), [])                 # no LIKE wildcards

    def test_policy_decisions_seed_once(self):
        n = self.lg.seed_policy(POL)
        self.assertEqual(n, len([d for d in POL.decisions.values() if d["valid"]]))
        self.assertEqual(self.lg.seed_policy(POL), 0)
        d = {r["ref"]: r for r in self.lg.decisions(limit=500)}
        self.assertEqual((d["D-004"]["decidedBy"], d["D-004"]["source"], d["D-004"]["via"]), ("jay", "policy", "policy-file"))
        self.assertIn("D-004", {r["ref"] for r in self.lg.decisions(project="samvision", limit=500)})


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lgd-")
        self.store = Store(new_db())
        self.ts = TaskStore(os.path.join(self.tmp, "tasks.db"), task_projects(cfg()))
        self.gh = FakeGh()
        self.d = Daemon(cfg(auto_merge=True), self.store, None, tasks=self.ts, gh_cli=self.gh)
        self.d.auto_merge_stop = os.path.join(self.tmp, "stop")

    async def asyncTearDown(self):
        self.store.close()

    def appr(self, key=None):
        rows = self.d.ledger.approvals(limit=500)
        return [(a["subject"], a["state"], a["subjectHash"][:8]) for a in reversed(rows) if key is None or a["key"] == key]

    def to_ready(self, project="gyst", number=7, labels=None):
        d, pl = self.d, self.d.pipeline
        t, _ = self.ts.create(project, "Add tests", labels=labels or [])
        k = t["key"]
        ref = f"{registry.github_of(project)}#{number}"
        d._pipeline_result(*pl.plan(k, PLAN, "agent:planner"))
        if pl.work(k)["gate"] == "plan":
            d._pipeline_result(*pl.confirm(k, "plan", "jay"))
        pl.start(k, f"{k}-tests", f"/srv/server/worktrees/x/{k}", "agent:coordinator")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="open")
        self.ts.link(k, "github", "pr", ref, None, "x", "system:automation")
        d._pipeline_result(*pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="r",
                                      pr={"ref": ref, "head": HEAD, "ciGreen": True, "ciNone": True, "draft": False}))
        if not (d.gh.get(project) or {}).get("data"):
            d.gh[project] = {"data": {"prs": []}, "asOf": 1, "error": None}
        d.gh[project]["data"]["prs"].append({"number": number, "headRefOid": HEAD, "statusCheckRollup": [], "isDraft": False})
        return k, ref

    async def test_a_merge_gate_is_requested_approved_by_jay_and_consumed_by_the_merge(self):
        k, ref = self.to_ready()
        self.assertEqual(self.appr(k), [("merge", "pending", HEAD[:8])])
        self.d._pipeline_result(*self.d.pipeline.confirm(k, "merge", "jay"))
        self.assertEqual(self.appr(k), [("merge", "approved", HEAD[:8])])
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.d._pipeline_result(*self.d.pipeline.merged(k, ref, "f" * 40))
        a = self.d.ledger.approvals()[0]
        self.assertEqual((a["state"], a["decidedBy"], a["via"]), ("consumed", "jay", "ui"))
        self.assertIsNotNone(a["consumedAt"])

    async def test_an_approved_merge_is_void_when_the_head_changes_and_never_consumed_by_another_head(self):
        k, ref = self.to_ready()
        self.d._pipeline_result(*self.d.pipeline.confirm(k, "merge", "jay"))
        self.d._pipeline_result(*self.d.pipeline.sync_pr(k, {"ref": ref, "head": HEAD2, "ciGreen": True}))
        a = self.d.ledger.approvals()[0]
        self.assertEqual(a["state"], "void")
        self.assertIn("changed after the approval", a["voidReason"])
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.d._pipeline_result(*self.d.pipeline.merged(k, ref, "f" * 40))
        self.assertNotIn("consumed", [x["state"] for x in self.d.ledger.approvals()])

    async def test_rework_after_approval_voids_it(self):
        k, ref = self.to_ready()
        self.d._pipeline_result(*self.d.pipeline.confirm(k, "merge", "jay"))
        self.d._pipeline_result(*self.d.pipeline.rework(k, "a defect", "agent:reviewer", open_prs=[ref]))
        self.assertEqual(self.d.ledger.approvals()[0]["state"], "void")

    async def test_a_failure_gate_gets_its_approval_at_once(self):
        t, _ = self.ts.create("gyst", "Stuck")
        self.d._pipeline_result(*self.d.pipeline.block(t["key"], "the API key is missing", "agent:coordinator"))
        self.assertEqual(self.appr(t["key"])[0][:2], ("failure", "pending"))
        self.d._pipeline_result(*self.d.pipeline.confirm(t["key"], "failure", "jay"))
        self.assertEqual(self.appr(t["key"])[0][:2], ("failure", "consumed"))

    async def test_the_deploy_lifecycle(self):
        k, ref = self.to_ready()
        pl = self.d.pipeline
        self.d._pipeline_result(*pl.confirm(k, "merge", "jay"))
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.d._pipeline_result(*pl.merged(k, ref, "f" * 40))
        self.d._pipeline_result(*pl.deploy_request(k, "live", "the export", "smoke test", "agent:coordinator"))
        self.assertEqual(self.appr(k)[-1][:2], ("deploy", "pending"))
        self.d._pipeline_result(*pl.confirm(k, "deploy", "jay", "go-live"))
        a = self.d.ledger.approvals()[0]
        self.assertEqual((a["state"], a["via"]), ("approved", "go-live"))
        self.d._pipeline_result(*pl.deployed(k, "live", "fail", "health check failed", "agent:coordinator"))
        dep = [x for x in self.d.ledger.approvals() if x["subject"] == "deploy"][0]
        self.assertEqual(dep["state"], "consumed")                              # a failed live deploy used it
        self.assertEqual(self.appr(k)[-1][:2], ("failure", "pending"))

    async def test_a_successful_live_deploy_consumes_its_approval_even_though_it_closes_the_ticket(self):
        k, ref = self.to_ready()
        pl = self.d.pipeline
        self.d._pipeline_result(*pl.confirm(k, "merge", "jay"))
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.d._pipeline_result(*pl.merged(k, ref, "f" * 40))
        self.d._pipeline_result(*pl.deploy_request(k, "live", "x", "smoke", "agent:coordinator"))
        self.d._pipeline_result(*pl.confirm(k, "deploy", "jay", "gate"))
        self.d._pipeline_result(*pl.verify(k, "pass", "ok", "agent:verifier"))
        self.d._pipeline_result(*pl.deployed(k, "live", "pass", "healthy", "agent:coordinator"))
        states = {a["subject"]: a["state"] for a in self.d.ledger.approvals()}
        self.assertEqual((states["merge"], states["deploy"]), ("consumed", "consumed"))

    async def test_an_open_failure_gate_keeps_one_approval_while_unrelated_steps_happen(self):
        t, _ = self.ts.create("gyst", "Stuck")
        k = t["key"]
        self.d._pipeline_result(*self.d.pipeline.block(k, "the API key is missing", "agent:coordinator"))
        for i in range(3):
            self.d._pipeline_result(*self.d.pipeline.handoff(k, {"done": f"x{i}"}, "agent:coordinator"))
        self.assertEqual([a[:2] for a in self.appr(k)], [("failure", "pending")])

    async def test_a_confirmation_never_approves_an_approval_for_an_older_subject(self):
        k, _ = self.to_ready()
        tid = self.ts.get(k)["id"]
        # a step the ledger missed: the pending merge approval is bound to an older head
        old = self.d.ledger.request(tid, "gyst", "merge", HEAD2, "older head", by="system:test")
        self.d._pipeline_result(*self.d.pipeline.confirm(k, "merge", "jay"))
        rows = {a["id"]: a for a in self.d.ledger.approvals()}
        self.assertEqual(rows[old]["state"], "void")
        self.assertEqual([(a["state"], a["subjectHash"]) for a in rows.values() if a["state"] == "approved"],
                         [("approved", HEAD)])

    async def test_a_needs_deploy_confirmation_approves_the_real_request_not_a_backfill(self):
        k, ref = self.to_ready(labels=["needs:deploy"])
        pl = self.d.pipeline
        if pl.work(k)["gate"] == "merge":
            self.d._pipeline_result(*pl.confirm(k, "merge", "jay"))
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.ts.update(k, {"needs_deploy": True}, "jay")
        self.d._pipeline_result(*pl.merged(k, ref, "f" * 40))
        self.d._pipeline_result(*pl.verify(k, "pass", "ok", "agent:verifier"))
        self.assertEqual(pl.work(k)["gate"], "deploy")
        self.d._pipeline_result(*pl.confirm(k, "deploy", "jay", "gate"))
        dep = [(a["state"], a["requestedBy"]) for a in self.d.ledger.approvals() if a["subject"] == "deploy"]
        self.assertEqual(dep, [("approved", "system:pipeline")])

    async def test_a_replan_after_a_deploy_approval_voids_it(self):
        k, ref = self.to_ready()
        pl = self.d.pipeline
        self.d._pipeline_result(*pl.confirm(k, "merge", "jay"))
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.d._pipeline_result(*pl.merged(k, ref, "f" * 40))
        self.d._pipeline_result(*pl.deploy_request(k, "live", "the export", "smoke", "agent:coordinator"))
        self.d._pipeline_result(*pl.confirm(k, "deploy", "jay", "gate"))
        self.d._pipeline_result(*pl.replan(k, "scope changed", "agent:coordinator"))
        self.assertEqual(self.d.ledger.approvals()[0]["state"], "void")

    async def test_a_closed_ticket_voids_its_open_approvals_at_start(self):
        k, _ = self.to_ready()
        self.ts.update(k, {"status": "CANCELLED"}, "jay", trigger="not needed")
        self.d._ledger_start()
        self.assertEqual(self.appr(k)[-1][:2], ("merge", "void"))

    async def test_a_plan_gate_is_consumed_by_jays_confirmation(self):
        k, _ = self.to_ready(labels=["migration"])
        self.assertEqual(self.appr(k)[0], ("plan", "consumed", self.appr(k)[0][2]))

    async def test_a_new_head_voids_the_pending_merge_approval(self):
        k, ref = self.to_ready()
        self.d._pipeline_result(*self.d.pipeline.sync_pr(k, {"ref": ref, "head": HEAD2, "ciGreen": True}))
        self.assertEqual(self.appr(k), [("merge", "void", HEAD[:8])])
        self.assertIn("closed without an approval", self.d.ledger.approvals()[0]["voidReason"])

    async def test_an_auto_merge_hold_requests_an_approval_and_a_ccd_merge_needs_none(self):
        self.gh.pr = view([f("server/ccd/daemon.py")])
        k, _ = self.to_ready("commandcenter")
        self.assertEqual(self.appr(k), [])                                  # low-risk, auto-merge on: no gate yet
        await self.d._auto_merge()
        self.assertEqual(self.appr(k), [("merge", "pending", HEAD[:8])])
        self.gh.pr = view()
        k2, _ = self.to_ready("commandcenter", number=8)
        await self.d._auto_merge()
        self.assertEqual(self.appr(k2), [])

    async def test_answered_questions_become_decisions(self):
        t, _ = self.ts.create("gyst", "Ask")
        k = t["key"]
        pl = self.d.pipeline
        self.d._pipeline_result(*pl.ask(k, [{"text": "Keep the old export?", "kind": "yesno"}], "agent:coordinator"))
        qid = pl.work(k)["questions"][0]["id"]
        self.d._pipeline_result(*pl.answer(k, [{"id": qid, "answer": "no"}], "jay"))
        d = [r for r in self.d.ledger.decisions() if r["source"] == "question"]
        self.assertEqual([(r["key"], r["question"], r["decision"], r["decidedBy"], r["options"]) for r in d],
                         [(k, "Keep the old export?", "no", "jay", [])])

    async def test_start_seeds_policy_and_backfills_open_gates(self):
        k, _ = self.to_ready()
        self.ts.db.execute("CREATE TEMP TABLE x AS SELECT 1")                # harmless; the db is writable
        d2 = Daemon(cfg(), self.store, None, tasks=self.ts, gh_cli=self.gh)
        before = len(self.d.ledger.approvals())
        d2._ledger_start()
        self.assertEqual(len(d2.ledger.approvals()), before)               # already requested: nothing doubled
        self.assertIn("D-008", {r["ref"] for r in d2.ledger.decisions(limit=500)})
        # A gate the ledger never saw (opened before it existed) is backfilled once.
        self.ts.db.execute("INSERT INTO approvals (project, ticket_id, subject_type, subject_hash, action, state, "
                           "requested_at, requested_by) SELECT 'gyst', id, 'ui', 'h', 'a', 'void', 1, 'x' FROM tickets "
                           "WHERE key=?", (k,))
        self.ts.db.execute("UPDATE ticket_work SET gate='ui' WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)", (k,))
        d2._ledger_start()
        d2._ledger_start()
        self.assertEqual([a for a in self.appr(k) if a[0] == "ui" and a[1] == "pending"].__len__(), 1)

    async def test_the_ledger_changes_nothing_even_when_it_breaks(self):
        with mock.patch.object(ledger.Ledger, "observe", side_effect=RuntimeError("boom")):
            k, _ = self.to_ready()
        self.assertEqual(self.d.pipeline.work(k)["gate"], "merge")
        self.assertEqual(self.ts.get(k)["status"], "READY_TO_MERGE")
        with mock.patch.object(ledger.Ledger, "seed_policy", side_effect=RuntimeError("boom")):
            self.d._ledger_start()                                           # logged, not raised

    async def test_no_task_system_no_ledger(self):
        d = Daemon(cfg(), self.store, None)
        self.assertEqual(d.ledger_state()["available"], False)
        d._ledger_start()


if __name__ == "__main__":
    unittest.main()
