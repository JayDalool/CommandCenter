"""The ticket pipeline (ccd/pipeline.py): conditional gates, head-bound reviews, durable resumable state."""
import json
import sqlite3
import tempfile
import unittest

from ccd import pipeline_cli, tasks
from ccd.pipeline import MAX_REVIEW_CYCLES, Pipeline, policy, stage_of
from ccd.tasks import TaskError, TaskStore

PROJECTS = [{"key": "samvision", "name": "SamVision", "prefix": "SV"}, {"key": "gyst", "name": "GYST", "prefix": "GYST"}]
PLAN = {"summary": "Show the valuation comparison", "requirements": ["table of comps"], "approach": "new view",
        "affected": ["web/valuation.tsx"], "risk": "low", "tests": ["unit", "ui"], "questions": []}
HEAD = "abcdef1234567890abcdef1234567890abcdef12"


def store():
    return TaskStore(":memory:", PROJECTS)


class Base(unittest.TestCase):
    def setUp(self):
        self.ts = store()
        self.pl = Pipeline(self.ts)

    def ticket(self, **fields):
        t, _ = self.ts.create("samvision", "Valuation comparison", **fields)
        return t["key"]

    def to_review(self, key, branch=None):
        self.pl.plan(key, PLAN, "agent:planner")
        self.pl.start(key, branch or f"{key}-valuation", f"/srv/server/worktrees/sv/{key}", "agent:coordinator")
        self.ts.update(key, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #1 is open")

    def pr(self, head=HEAD, green=True, draft=False):
        return {"ref": "JayDalool/SamVisionAI#1", "head": head, "ciGreen": green, "draft": draft}


class Stages(Base):
    def test_every_canonical_status_maps_to_one_stage(self):
        self.assertEqual({stage_of(s) for s in tasks.STATUSES},
                         {"PLAN", "BUILD", "REVIEW", "MERGE", "VERIFY", "DONE"})
        for s in tasks.OFF_PIPELINE:
            self.assertIsNone(stage_of(s))

    def test_low_risk_plan_proceeds_without_jay(self):
        k = self.ticket()
        t, _, ev = self.pl.plan(k, PLAN, "agent:planner", model="opus")
        self.assertEqual(t["status"], "READY_TO_IMPLEMENT")
        w = self.pl.work(k)
        self.assertEqual((w["planState"], w["gate"], w["plan"]["summary"]), ("accepted", None, PLAN["summary"]))
        self.assertEqual(w["roles"]["planner"]["model"], "opus")
        self.assertEqual(self.pl.needs(), [])

    def test_risky_plan_waits_for_jay_and_only_jay_opens_it(self):
        for fields in ({"labels": ["migration"]}, {"needs_jay": True}, {"type": "SECURITY"}, {"labels": ["gate:plan"]}):
            k = self.ticket(**fields)
            t, _, _ = self.pl.plan(k, PLAN, "agent:planner")
            self.assertEqual(t["status"], "RESEARCHING", fields)
            self.assertEqual(self.pl.work(k)["gate"], "plan")
            with self.assertRaises(TaskError):
                self.pl.start(k, f"{k}-x", "/srv/w/x", "agent:coordinator")     # no accepted plan
            with self.assertRaises(TaskError) as e:
                self.pl.confirm(k, "plan", "agent:coordinator")
            self.assertEqual(e.exception.status, 403)
            t, _, _ = self.pl.confirm(k, "plan", "jay")
            self.assertEqual(t["status"], "READY_TO_IMPLEMENT")
        self.assertEqual([n["gate"] for n in self.pl.needs()], [])

    def test_needs_jay_names_the_gate(self):
        k = self.ticket(labels=["architecture"])
        self.pl.plan(k, PLAN, "agent:planner")
        [n] = self.pl.needs()
        self.assertEqual((n["ref"], n["gate"], n["kind"]), (k, "plan", "gate"))
        self.assertTrue(n["text"].startswith("Plan needs approval"))

    def test_start_needs_the_ticket_branch_convention_and_a_free_lane(self):
        k = self.ticket()
        self.pl.plan(k, PLAN, "agent:planner")
        for bad in ("main", "feature/x", f"{k}", f"{k}-UPPER", f"SV-999-{k}", f"{k}-x;rm"):
            with self.assertRaises(TaskError, msg=bad):
                self.pl.start(k, bad, "/srv/w/x", "agent:coordinator")
        for bad in ("relative/path", "/srv/../etc", "/srv/w x", ""):
            with self.assertRaises(TaskError, msg=bad):
                self.pl.start(k, f"{k}-x", bad, "agent:coordinator")
        t, _, _ = self.pl.start(k, f"{k}-valuation", f"/srv/w/{k}", "agent:coordinator", model="sonnet")
        self.assertEqual((t["status"], t["branch"]), ("IN_PROGRESS", f"{k}-valuation"))
        others = [self.ticket() for _ in range(2)]
        for o in others:
            self.pl.plan(o, PLAN, "agent:planner")
        self.pl.start(others[0], f"{others[0]}-a", "/srv/w/a", "agent:coordinator")
        with self.assertRaises(TaskError) as e:                      # third lane
            self.pl.start(others[1], f"{others[1]}-b", "/srv/w/b", "agent:coordinator")
        self.assertIn("lanes", e.exception.message)


class Review(Base):
    def test_approval_is_tied_to_the_pr_head_and_green_checks(self):
        k = self.ticket()
        self.to_review(k)
        t, _, _ = self.pl.review(k, "APPROVE", HEAD[:12], "agent:reviewer", pr=self.pr(green=False))
        self.assertEqual(t["status"], "IN_REVIEW")                           # CI not green yet
        t, _, _ = self.pl.sync_pr(k, self.pr(green=True))
        self.assertEqual(t["status"], "READY_TO_MERGE")
        self.assertEqual(self.pl.work(k)["gate"], "merge")                  # owner merge by default
        t, _, ev = self.pl.sync_pr(k, self.pr(head="1234567" + "0" * 33))   # a new commit
        self.assertEqual(t["status"], "IN_REVIEW")
        self.assertEqual([e[0] for e in ev], ["pipeline.review_stale"])
        w = self.pl.work(k)
        self.assertEqual((w["review"]["verdict"], w["gate"]), (None, None))

    def test_an_approval_for_another_head_never_promotes(self):
        k = self.ticket()
        self.to_review(k)
        t, _, _ = self.pl.review(k, "APPROVE", "fedcba9", "agent:reviewer", pr=self.pr())
        self.assertEqual(t["status"], "IN_REVIEW")
        self.assertEqual(self.pl.sync_pr(k, self.pr())[0]["status"], "IN_REVIEW")
        for draft in (True,):
            self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", pr=self.pr(draft=draft))
            self.assertEqual(self.ts.get(k)["status"], "IN_REVIEW")

    def test_two_failed_review_cycles_block_for_jay(self):
        k = self.ticket()
        self.to_review(k)
        f = [{"scope": "in", "category": "correctness", "summary": "off by one"},
             {"scope": "out", "category": "perf", "summary": "slow query elsewhere"}]
        t, _, _ = self.pl.review(k, "REQUEST_CHANGES", HEAD, "agent:reviewer", findings=f)
        self.assertEqual(t["status"], "IN_REVIEW")
        t, _, _ = self.pl.review(k, "REQUEST_CHANGES", "1234567", "agent:reviewer")
        self.assertEqual(t["status"], "BLOCKED")
        w = self.pl.work(k)
        self.assertEqual((w["gate"], w["review"]["cycles"], w["blocked"]["stage"]), ("failure", MAX_REVIEW_CYCLES, "REVIEW"))
        self.assertEqual([(x["scope"], x["category"]) for x in w["findings"]], [("in", "correctness"), ("out", "perf")])
        self.assertEqual(w["stage"], "REVIEW")
        self.assertEqual([s["state"] for s in w["stages"]], ["done", "done", "blocked", "todo", "todo"])
        t, _, _ = self.pl.confirm(k, "failure", "jay")                     # Jay unblocks: back to review
        self.assertEqual((t["status"], self.pl.work(k)["review"]["cycles"]), ("IN_REVIEW", 0))

    def test_bad_input_is_refused(self):
        k = self.ticket()
        self.to_review(k)
        for verdict, head in (("LGTM", HEAD), ("APPROVE", "main"), ("APPROVE", "zzzzzzz"), ("APPROVE", None)):
            with self.assertRaises(TaskError):
                self.pl.review(k, verdict, head, "agent:reviewer")
        with self.assertRaises(TaskError):
            self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", findings=[{"scope": "maybe", "summary": "x"}])
        k2 = self.ticket()
        with self.assertRaises(TaskError):                                  # no review before a PR
            self.pl.review(k2, "APPROVE", HEAD, "agent:reviewer")


class Verify(Base):
    def merged(self, k):
        self.to_review(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", pr=self.pr())
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR #1 merged")
        self.pl.merged(k, "JayDalool/SamVisionAI#1", "9" * 40)

    def test_merge_records_the_pr_and_sha_and_closes_the_merge_gate(self):
        k = self.ticket()
        self.merged(k)
        w = self.pl.work(k)
        self.assertEqual((w["merge"]["pr"], w["merge"]["sha"], w["gate"]), ("JayDalool/SamVisionAI#1", "9" * 40, None))
        _, ch, ev = self.pl.merged(k, "JayDalool/SamVisionAI#1", "9" * 40)   # idempotent
        self.assertEqual((ch, ev), ([], []))

    def test_pass_without_owner_checks_is_done(self):
        k = self.ticket()
        self.merged(k)
        t, _, _ = self.pl.verify(k, "pass", "health ok; /valuation renders", "agent:verifier", model="sonnet")
        self.assertEqual(t["status"], "DONE")
        self.assertIsNotNone(t["completedAt"])
        w = self.pl.work(k)
        self.assertEqual((w["verification"]["result"], [s["state"] for s in w["stages"]]), ("pass", ["done"] * 5))

    def test_ui_review_waits_for_jay_before_done(self):
        k = self.ticket(needs_ui_review=True)
        self.merged(k)
        t, _, _ = self.pl.verify(k, "pass", "deployed", "agent:verifier")
        self.assertEqual((t["status"], self.pl.work(k)["gate"]), ("VERIFYING", "ui"))
        self.assertEqual(self.pl.needs()[0]["gate"], "ui")
        t, _, _ = self.pl.confirm(k, "ui", "jay")
        self.assertEqual(t["status"], "DONE")

    def test_failed_verification_blocks_visibly(self):
        k = self.ticket()
        self.merged(k)
        t, _, _ = self.pl.verify(k, "fail", "500 on /valuation", "agent:verifier")
        self.assertEqual(t["status"], "BLOCKED")
        self.assertIn("500 on /valuation", self.pl.work(k)["blocked"]["reason"])
        with self.assertRaises(TaskError):
            self.pl.verify(k, "pass", "", "agent:verifier")


class Durable(Base):
    def test_everything_needed_to_resume_is_in_one_read(self):
        k = self.ticket()
        self.to_review(k)
        self.pl.handoff(k, {"done": "built the view", "next": "review", "decisions": "reuse table", "blockers": ""},
                        "agent:coordinator")
        w = self.pl.work(k)
        for f in ("plan", "stage", "branch", "worktree", "roles", "review", "gate", "handoff", "policy", "prs", "stages"):
            self.assertIn(f, w)
        self.assertEqual((w["stage"], w["branch"], w["handoff"]["next"]), ("REVIEW", f"{k}-valuation", "review"))
        kinds = [e["kind"] for e in self.ts.timeline(self.ts._id_of(k))]
        for kind in ("pipeline.plan", "pipeline.plan_accepted", "pipeline.started", "pipeline.handoff"):
            self.assertIn(kind, kinds)

    def test_a_refused_step_changes_nothing(self):
        k = self.ticket()
        before = self.pl.work(k)
        with self.assertRaises(TaskError):
            self.pl.verify(k, "pass", "x", "agent:verifier")
        self.assertEqual(self.pl.work(k)["stage"], before["stage"])
        self.assertEqual(self.ts.get(k)["status"], "INBOX")

    def test_migration_3_upgrades_a_v2_file_without_touching_tickets(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        __import__("os").close(fd)
        db = sqlite3.connect(path, isolation_level=None)
        for version, sql in tasks.MIGRATIONS[:2]:
            db.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        db.close()
        ts = TaskStore(path, PROJECTS)
        self.assertEqual(ts.applied, [3])
        t, _ = ts.create("samvision", "x")
        self.assertEqual(Pipeline(ts).work(t["key"])["planState"], "none")
        ts.close()

    def test_policy_defaults(self):
        p = policy({"project": "samvision", "labels": [], "flags": [], "type": "FEATURE"})
        self.assertEqual((p["plan"], p["merge"], p["ui"], p["deploy"]), ("auto", "owner", False, False))


class Cli(unittest.TestCase):
    def test_writes_carry_the_agent_role_and_cannot_confirm_gates(self):
        m, path, body, actor = pipeline_cli.build(["review", "SV-056", "--role", "reviewer", "--verdict", "APPROVE",
                                                  "--head", "abcdef1"])
        self.assertEqual((m, path, actor), ("POST", "/api/tasks/SV-056/work/review", "agent:reviewer"))
        self.assertEqual((body["verdict"], body["head"], body["findings"]), ("APPROVE", "abcdef1", []))
        self.assertEqual(pipeline_cli.build(["work", "SV-056"])[:2], ("GET", "/api/tasks/SV-056/work"))
        for argv in (["confirm", "SV-056", "--role", "coordinator"], ["review", "SV-056", "--verdict", "APPROVE"]):
            with self.assertRaises(SystemExit):
                pipeline_cli.build(argv)

    def test_plan_reads_a_json_file(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(PLAN, f)
        f.close()
        _, _, body, _ = pipeline_cli.build(["plan", "SV-056", "--role", "planner", "--plan-file", f.name, "--model", "opus"])
        self.assertEqual((body["plan"]["summary"], body["model"]), (PLAN["summary"], "opus"))


if __name__ == "__main__":
    unittest.main()
