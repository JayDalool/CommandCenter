"""The Autonomy Engine in shadow mode (ccd/autonomy.py, D-008): the pure verdicts per project, what ccd did as read
from pipeline events, the append-only record, and above all that recording changes nothing ccd does."""
import copy
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from ccd import autonomy, profiles, registry
from ccd.config import task_projects
from ccd.daemon import Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db
from .test_auto_merge import PLAN, FakeGh
from .test_merge_policy import HEAD, f, view

POL = profiles.load()


def facts(**over):
    base = {"project": "commandcenter", "type": "FEATURE", "labels": [], "flags": [], "plan_accepted": True,
            "review_at_head": True, "merged": False, "verified": None, "ci": "green", "files": None,
            # a PR that is ready to merge as reviewed (engine v2 needs every one of these for an auto merge)
            "review_head": HEAD, "pr_head": HEAD, "ci_passed": True, "draft": False, "mergeable": "MERGEABLE",
            "base": "main", "cross_repo": False, "state": "OPEN"}
    base.update(over)
    return base


def ev(action, project, **over):
    return autonomy.evaluate(action, POL.profile(project), facts(project=project, **over))


class Verdicts(unittest.TestCase):
    def test_never_auto_without_a_valid_profile_and_never_for_an_unknown_action(self):
        for p in (None, {}, "x"):
            v = autonomy.evaluate("merge", p if p != {} else None, facts())
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "profile:invalid"))
        self.assertEqual(autonomy.evaluate("delete_prod", POL.profile("commandcenter"), facts())["outcome"], "jay")
        self.assertFalse(ev("merge", "commandcenter")["enforced"])                 # shadow: never enforced

    def test_paused_gauzemate_refuses_everything(self):
        for a in autonomy.ACTIONS:
            self.assertEqual(ev(a, "gauzemate")["outcome"], "refuse", a)

    def test_human_boundaries_beat_any_profile(self):
        for over in ({"flags": ["needs_jay"]}, {"flags": ["needs:legal"]}, {"type": "LEGAL"}, {"labels": ["legal"]}):
            v = ev("plan", "commandcenter", **over)
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "boundary"), over)

    def test_commandcenter_merge(self):
        docs = [f("docs/a.md"), f("server/tests/test_x.py", "ADDED")]
        v = ev("merge", "commandcenter", files=docs, additions=20, deletions=2)
        self.assertEqual((v["outcome"], v["rule"]), ("auto", "target.merge"))   # low risk, CI green, approved
        # D-007: Command Center's own rails always need Jay, even if everything else holds.
        for path in ("server/ccd/autonomy.py", "policy/projects/gyst.toml", "server/ccd/security.py",
                     "server/ccd/daemon.py", "server/ccd/registry.py", ".github/workflows/ci.yml"):
            v = ev("merge", "commandcenter", files=[f(path)])
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-007:self_protection"), path)
        # unknown files or unknown risk is never a yes
        v = ev("merge", "commandcenter")
        self.assertEqual(v["outcome"], "jay")
        self.assertIn("changed files", v["missing"])
        v = ev("merge", "commandcenter", files=[f("plans/x.md")])                 # outside the allowlist, not a rail
        self.assertEqual((v["outcome"], v["missing"]), ("jay", ["risk"]))
        v = ev("merge", "commandcenter", files=[f("web/app/src/x.tsx")])          # the UI is a rail since v2 (L-01)
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-007:self_protection"))
        self.assertEqual(ev("merge", "commandcenter", files=docs, additions=1, deletions=0, ci="failing")["outcome"], "jay")
        self.assertEqual(ev("merge", "commandcenter", files=docs, additions=1, deletions=0,
                            review_at_head=False)["outcome"], "jay")

    def test_a_label_can_raise_risk_but_never_lower_it(self):
        src = [f("web/app/src/x.tsx")]
        for labels in (["risk:low"], ["risk:medium"], ["security", "risk:low"], ["migration", "risk:medium"]):
            self.assertEqual(ev("merge", "commandcenter", files=src, labels=labels)["outcome"], "jay", labels)
        self.assertEqual(autonomy.risk_of(facts(labels=["risk:low", "security"])), "high")
        self.assertEqual(autonomy.risk_of(facts(labels=["risk:low"])), None)
        self.assertEqual(autonomy.risk_of(facts(labels=["risk:high"], files=[f("docs/a.md")], additions=1, deletions=0)), "high")

    def test_no_ci_checks_is_not_green(self):
        v = ev("merge", "commandcenter", files=[f("docs/a.md")], additions=1, deletions=0, ci="none")
        self.assertEqual(v["outcome"], "jay")
        self.assertIn("the PR has no CI checks", v["reasons"])

    def test_a_truncated_file_list_or_a_rename_can_hide_a_protected_path(self):
        many = [f(f"docs/a{i}.md") for i in range(100)]
        v = ev("merge", "commandcenter", files=many, additions=100, deletions=0)
        self.assertEqual(v["outcome"], "jay")
        self.assertIn("the complete list of changed files", v["missing"])
        v = ev("merge", "commandcenter", files=[f("docs/old-policy.md", "RENAMED")], additions=0, deletions=0)
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-007:self_protection"))
        v = ev("merge", "commandcenter", files=[{"path": "docs/a.md", "additions": 1, "deletions": 0}],
               additions=1, deletions=0)                                         # no changeType: unknown, never safe
        self.assertEqual(v["outcome"], "jay")

    def test_gyst_personal_data_needs_jay(self):
        v = ev("merge", "gyst", files=[f("app/models/person.py")])
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-005:personal_data"))
        v = ev("merge", "gyst", files=[f("app/ui/button.tsx")])
        self.assertEqual((v["outcome"], v["missing"]), ("jay", ["risk"]))      # nothing assesses risk yet

    def test_samvision_and_mfe_merge_wait_for_the_release_train_and_never_deploy_unattended(self):
        for p in ("samvision", "mfe"):
            self.assertEqual(ev("merge", p, labels=["risk:low"], files=[f("a.py")])["rule"], "target.merge:release_train")
            v = ev("deploy", p, env="live", merged=True, verified=True, labels=["risk:low"], files=[f("a.py")])
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.release:unattended_requires"))   # D-004

    def test_live_deploys_need_capabilities_that_do_not_exist(self):
        for p in ("commandcenter", "gyst"):
            v = ev("deploy", p, env="live", merged=True, verified=True, files=[f("docs/a.md")], labels=["risk:low"])
            self.assertEqual(v["outcome"], "jay", p)
            self.assertTrue(any("health checks" in r for r in v["reasons"]), v)
        self.assertEqual(ev("deploy", "commandcenter", env="preview")["outcome"], "auto")   # no path check off live

    def test_plans(self):
        v = ev("plan", "commandcenter")                                              # Q-01: required_for = [risk_high]
        self.assertEqual((v["outcome"], v["missing"]), ("jay", ["risk"]))           # and nothing assesses risk yet
        self.assertEqual(ev("plan", "commandcenter", labels=["migration"])["rule"], "target.plan_approval")
        v = ev("plan", "gyst")
        self.assertEqual((v["outcome"], v["missing"]), ("jay", ["risk"]))           # risk_high, risk unknown
        self.assertEqual(ev("plan", "gyst", labels=["risk:low"])["outcome"], "jay")   # a label never lowers risk
        self.assertEqual(ev("plan", "gyst", labels=["migration"])["outcome"], "jay")  # migration label = high risk
        v = ev("plan", "samvision")
        self.assertEqual(v["outcome"], "jay")                                       # UI/workflow/API impact unknown
        self.assertIn("api change", v["missing"])
        self.assertEqual(ev("plan", "samvision", labels=["ui"])["rule"], "target.plan_approval")

    def test_odd_input_never_raises(self):
        prof = POL.profile("gyst")
        for fx in (None, {}, {"files": "x"}, {"files": [None, 3, {"path": "../etc"}]}, {"labels": None, "flags": None}):
            for a in autonomy.ACTIONS:
                self.assertIn(autonomy.evaluate(a, prof, fx)["outcome"], autonomy.OUTCOMES)
        bad = copy.deepcopy(prof)
        bad["target"]["merge"]["requires"] = ["telepathy"]
        self.assertEqual(autonomy.evaluate("merge", bad, facts(project="gyst", files=[f("a.py")]))["outcome"], "jay")


class Observed(unittest.TestCase):
    def test_what_ccd_did_is_read_from_its_events(self):
        o = autonomy.observed
        self.assertEqual(o([("pipeline.plan_accepted", "", {})]), [("plan", "auto", {})])
        self.assertEqual(o([("pipeline.gate_opened", "", {"gate": "plan"})]), [("plan", "jay", {})])
        self.assertEqual(o([("pipeline.ready_to_merge", "", {"ci": "none"}),
                            ("pipeline.gate_opened", "", {"gate": "merge"})]), [("merge", "jay", {})])
        self.assertEqual(o([("pipeline.auto_merged", "", {"ci": "green"})]), [("merge", "auto", {"ci": "green"})])
        # ccd decided to merge and gh refused: the gate that follows is not "ccd asked Jay"
        self.assertEqual(o([("pipeline.auto_merge_failed", "", {}), ("pipeline.gate_opened", "", {"gate": "merge"})]),
                         [("merge", "auto", {})])
        self.assertEqual(o([("pipeline.deploy_requested", "", {"env": "live"}),
                            ("pipeline.gate_opened", "", {"gate": "deploy"})]), [("deploy", "jay", {"env": "live"})])
        self.assertEqual(o([("pipeline.deploy_requested", "", {"env": "preview"})]), [("deploy", "auto", {"env": "preview"})])
        self.assertEqual(o([("pipeline.gate_opened", "", {"gate": "ui"}), ("pipeline.review", "", {}),
                            ("pipeline.ready_to_merge", "", {})]), [])


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sh-")
        self.ts = TaskStore(os.path.join(self.tmp, "tasks.db"), task_projects(cfg()))
        self.sh = autonomy.Shadow(self.ts.db)

    def test_it_is_append_only_and_agree_cannot_lie(self):
        v = ev("merge", "samvision")
        self.sh.record(None, "samvision", "merge", "jay", v, facts(files=[f("a.py")]), POL.fingerprint)
        for sql in ("UPDATE autonomy_shadow SET engine='auto'", "DELETE FROM autonomy_shadow"):
            with self.assertRaises(sqlite3.DatabaseError):
                self.ts.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ts.db.execute("INSERT INTO autonomy_shadow (at, project, action, observed, engine, agree, rule, policy, "
                               "engine_version) VALUES (1, 'x', 'merge', 'jay', 'auto', 1, 'r', 'p', 1)")
        row = self.ts.db.execute("SELECT agree, facts FROM autonomy_shadow").fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(json.loads(row[1])["files"], ["a.py"])

    def test_summary_counts_and_lists_disagreements(self):
        self.sh.record(None, "gyst", "plan", "auto", ev("plan", "gyst"), facts(project="gyst"), "fp")
        self.sh.record(None, "gyst", "plan", "auto", autonomy._verdict("auto", "x"), facts(project="gyst"), "fp")
        s = self.sh.summary()
        self.assertEqual((s["total"], s["agree"], s["disagree"], s["mode"]), (2, 1, 1, "shadow"))
        self.assertEqual(s["counts"]["gyst"]["plan"]["pairs"], {"auto->jay": 1, "auto->auto": 1})
        self.assertEqual(s["missing"], {"risk": 1})
        self.assertEqual([(d["project"], d["observed"], d["engine"]) for d in s["disagreements"]], [("gyst", "auto", "jay")])


class Versions(unittest.TestCase):
    """Engine v2 fixed verdicts v1 got wrong, so a v1 row never counts or shows next to a v2 one."""

    def test_summary_and_needs_you_read_the_current_engine_only(self):
        from ccd import inbox
        tmp = tempfile.mkdtemp(prefix="shv-")
        ts = TaskStore(os.path.join(tmp, "tasks.db"), task_projects(cfg()))
        t, _ = ts.create("commandcenter", "x")
        tid = ts._id_of(t["key"])
        sh = autonomy.Shadow(ts.db)
        with mock.patch.object(autonomy, "ENGINE_VERSION", 1):
            sh.record(tid, "commandcenter", "merge", "jay", autonomy._verdict("auto", "v1"), {}, "fp")
        s = sh.summary()
        self.assertEqual((s["engine"], s["total"], s["older"], s["disagreements"]), (2, 0, 1, []))
        self.assertEqual(sh.summary(engine=1)["total"], 1)
        self.assertEqual(inbox.Inbox(ts.db)._engine(time.time()), {})
        sh.record(tid, "commandcenter", "merge", "jay", autonomy._verdict("jay", "v2"), {}, "fp")
        self.assertEqual(inbox.Inbox(ts.db)._engine(time.time())[(t["key"], "merge")]["rule"], "v2")
        self.assertEqual(sh.summary()["total"], 1)


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shd-")
        self.store = Store(new_db())
        self.ts = TaskStore(os.path.join(self.tmp, "tasks.db"), task_projects(cfg()))
        self.gh = FakeGh()
        self.d = Daemon(cfg(auto_merge=True), self.store, None, tasks=self.ts, gh_cli=self.gh)
        self.d.auto_merge_stop = os.path.join(self.tmp, "stop")

    async def asyncTearDown(self):
        self.store.close()

    def rows(self):
        return [r for r in self.ts.db.execute("SELECT project, action, observed, engine, rule FROM autonomy_shadow "
                                               "ORDER BY id")]

    def to_ready(self, project="commandcenter", number=7, **fields):
        d, pl = self.d, self.d.pipeline
        t, _ = self.ts.create(project, "Add tests", **fields)
        k = t["key"]
        ref = f"{registry.github_of(project)}#{number}"
        d._pipeline_result(*pl.plan(k, PLAN, "agent:planner"))
        if pl.work(k)["gate"] == "plan":
            pl.confirm(k, "plan", "jay")
        pl.start(k, f"{k}-tests", f"/srv/server/worktrees/x/{k}", "agent:coordinator")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="open")
        self.ts.link(k, "github", "pr", ref, None, "x", "system:automation")
        d._pipeline_result(*pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="r",
                                      pr={"ref": ref, "head": HEAD, "ciGreen": True, "ciNone": True, "draft": False}))
        if not (d.gh.get(project) or {}).get("data"):
            d.gh[project] = {"data": {"prs": []}, "asOf": 1, "error": None}
        d.gh[project]["data"]["prs"].append(
            {"number": number, "headRefOid": HEAD, "statusCheckRollup": [], "isDraft": False})
        return k

    async def test_each_decision_is_recorded_next_to_what_ccd_did(self):
        self.to_ready()                                     # CC plan auto; low-risk + auto_merge on: no gate yet
        self.to_ready("gyst")                               # GYST plan auto today; owner: merge gate
        await self.d._auto_merge()                          # CC: docs-only PR merged by ccd
        self.assertEqual(self.rows(), [
            ("commandcenter", "plan", "auto", "jay", "target.plan_approval:unknown"),   # Q-01: risk unknown
            ("gyst", "plan", "auto", "jay", "target.plan_approval:unknown"),
            ("gyst", "merge", "jay", "jay", "target.merge:requires"),
            ("commandcenter", "merge", "auto", "jay", "target.merge:requires"),   # ADR 0007 allows no checks; target doesn't
        ])
        s = self.d.autonomy_state()
        self.assertEqual((s["total"], s["disagree"], s["available"]), (4, 3, True))

    async def test_green_ci_and_allowlisted_files_agree(self):
        self.gh.pr = view(statusCheckRollup=[{"conclusion": "SUCCESS"}])
        self.to_ready()
        await self.d._auto_merge()
        self.assertEqual(self.rows()[-1], ("commandcenter", "merge", "auto", "auto", "target.merge"))

    async def test_the_readiness_ccd_already_read_reaches_the_engine(self):
        # engine v2: the PR object _auto_merge_one fetched anyway supplies draft/mergeable/base/fork/head and whether
        # a check passed. No extra gh call: the same single `gh pr view` per ticket.
        ok = [{"conclusion": "SUCCESS"}]
        # The last case is U-08 seen from both sides: today's auto-merge (ci_state) merges an all-skipped PR; the
        # engine says Jay. Legacy is deliberately unchanged here; the engine records the disagreement.
        for over, did, rule in (({"isDraft": True}, "jay", "merge:readiness"),
                                ({"isCrossRepository": True}, "jay", "merge:readiness"),
                                ({"baseRefName": "release"}, "jay", "merge:readiness"),
                                ({"statusCheckRollup": [{"conclusion": "SKIPPED"}]}, "auto", "target.merge:requires")):
            self.gh.pr = view(**dict({"statusCheckRollup": ok}, **over))
            before = len(self.gh.of("view"))
            self.to_ready(number=11 + len(self.rows()))
            await self.d._auto_merge()
            self.assertEqual(self.rows()[-1][1:], ("merge", did, "jay", rule), over)
            self.assertEqual(len(self.gh.of("view")) - before, 1)
        self.assertEqual(len(self.gh.of("merge")), 1)               # only the all-skipped one, by legacy, as before

    async def test_a_pr_at_a_newer_head_is_not_used_as_the_reviewed_one(self):
        k = self.to_ready("gyst")
        self.d._shadow_pr[k] = dict(view([f("docs/a.md")]), headRefOid="ee" * 20)
        self.d._pipeline_result(*self.d.pipeline.hold_merge(k, HEAD, "x"))      # no event: gate already open
        self.ts.db.execute("UPDATE ticket_work SET gate=NULL WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)", (k,))
        self.d._pipeline_result(*self.d.pipeline.hold_merge(k, HEAD, "held"))
        facts_row = json.loads(self.ts.db.execute("SELECT facts FROM autonomy_shadow ORDER BY id DESC").fetchone()[0])
        self.assertIsNone(facts_row.get("files"))

    async def test_one_deploy_decision_per_deployment(self):
        k = self.to_ready("gyst")
        tid = self.ts._id_of(k)
        self.d.shadow.record(tid, "gyst", "deploy", "jay", autonomy._verdict("jay", "x"), {}, "fp")
        self.assertTrue(self.d._shadow_deploy_seen(tid))
        self.d._shadow_record(self.ts.get(k), [("pipeline.deploy_requested", "", {"env": "live"}),
                                               ("pipeline.gate_opened", "", {"gate": "deploy"})])
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM autonomy_shadow WHERE action='deploy'").fetchone()[0], 1)

    async def test_a_held_merge_on_protected_paths_agrees(self):
        self.gh.pr = view([f("server/ccd/autonomy.py")])
        self.to_ready()
        await self.d._auto_merge()
        self.assertEqual(self.rows()[-1], ("commandcenter", "merge", "jay", "jay", "D-007:self_protection"))

    async def test_shadow_changes_nothing_even_if_the_engine_says_auto_to_everything_or_breaks(self):
        always = lambda *a, **k: autonomy._verdict("auto", "test:always")              # noqa: E731
        with mock.patch.object(autonomy, "evaluate", always):
            k = self.to_ready("gyst")
            self.gh.pr = view([f("server/ccd/daemon.py")])
            k2 = self.to_ready()
            await self.d._auto_merge()
        self.assertEqual(self.d.pipeline.work(k)["gate"], "merge")                      # owner project: still Jay
        self.assertEqual(self.d.pipeline.work(k2)["gate"], "merge")                     # held, as before
        self.assertEqual(self.gh.of("merge"), [])
        with mock.patch.object(autonomy, "evaluate", side_effect=RuntimeError("boom")):
            k3 = self.to_ready("gyst", number=9)
        self.assertEqual(self.d.pipeline.work(k3)["gate"], "merge")
        self.assertEqual(self.ts.get(k3)["status"], "READY_TO_MERGE")

    async def test_no_task_system_no_record(self):
        d = Daemon(cfg(), self.store, None)
        self.assertEqual(d.autonomy_state()["available"], False)
        d._shadow_record({"key": "X-1", "project": "x"}, [("pipeline.plan_accepted", "", {})])   # no error


if __name__ == "__main__":
    unittest.main()
