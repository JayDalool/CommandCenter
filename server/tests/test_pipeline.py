"""The ticket pipeline (ccd/pipeline.py): conditional gates, head-bound reviews, durable resumable state."""
import json
import sqlite3
import tempfile
import unittest

from ccd import pipeline_cli, tasks
from ccd.pipeline import MAX_REVIEW_CYCLES, Pipeline, policy, stage_of
from ccd.tasks import TaskError, TaskStore

PROJECTS = [{"key": "samvision", "name": "SamVision", "prefix": "SV"}, {"key": "gyst", "name": "GYST", "prefix": "GYST"},
            {"key": "commandcenter", "name": "Command Center", "prefix": "CC"}]
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

    def test_a_new_plan_needs_a_new_approval(self):
        k = self.ticket(labels=["migration"])
        self.pl.plan(k, PLAN, "agent:planner")
        self.pl.confirm(k, "plan", "jay")
        t, _, _ = self.pl.plan(k, dict(PLAN, summary="v2: drop the table"), "agent:planner")
        w = self.pl.work(k)
        self.assertEqual((t["status"], w["gate"], w["planState"]), ("RESEARCHING", "plan", "proposed"))
        self.assertNotIn("plan", w["confirmed"])

    def test_needs_jay_names_the_gate(self):
        k = self.ticket(labels=["architecture"])
        self.pl.plan(k, PLAN, "agent:planner")
        [n] = self.pl.needs()
        self.assertEqual((n["ref"], n["gate"], n["kind"]), (k, "plan", "gate"))
        self.assertTrue(n["text"].startswith("Plan needs approval"))

    def test_gate_counts_are_two_integers_that_only_grow(self):
        self.assertEqual(self.pl.gate_counts(), {"open": 0, "last": 0})
        a = self.ticket(labels=["architecture"])
        self.pl.plan(a, PLAN, "agent:planner")
        c1 = self.pl.gate_counts()
        self.assertEqual(c1["open"], 1)
        self.assertGreater(c1["last"], 0)
        b = self.ticket(labels=["architecture"])
        self.pl.plan(b, PLAN, "agent:planner")
        c2 = self.pl.gate_counts()
        self.assertEqual(c2["open"], 2)
        self.assertGreater(c2["last"], c1["last"])
        self.pl.confirm(a, "plan", "jay")      # closing a gate lowers open, never `last`
        c3 = self.pl.gate_counts()
        self.assertEqual((c3["open"], c3["last"]), (1, c2["last"]))
        self.pl.confirm(b, "plan", "jay")
        self.assertEqual(self.pl.gate_counts(), {"open": 0, "last": c2["last"]})
        self.assertTrue(all(type(v) is int for v in self.pl.gate_counts().values()))

    def test_a_block_moves_the_gate_marker(self):
        k = self.ticket()
        self.to_review(k)
        before = self.pl.gate_counts()["last"]
        self.pl.block(k, "tests keep failing", "agent:coordinator")
        after = self.pl.gate_counts()
        self.assertGreater(after["last"], before)
        self.assertEqual(after["open"], 1)

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
        with self.assertRaises(TaskError) as e:                      # third lane in the same project
            self.pl.start(others[1], f"{others[1]}-b", "/srv/w/b", "agent:coordinator")
        self.assertIn("lanes", e.exception.message)
        self.assertIn("samvision", e.exception.message)

    def test_lanes_are_counted_per_project(self):
        sv = [self.ticket() for _ in range(3)]
        for k in sv:
            self.pl.plan(k, PLAN, "agent:planner")
        for k in sv[:2]:
            self.pl.start(k, f"{k}-x", f"/srv/w/{k}", "agent:coordinator")
        gz, _ = self.ts.create("gyst", "Galaxy keyboard navigation", "jay")
        self.pl.plan(gz["key"], PLAN, "agent:planner")              # SamVision's two lanes do not hold GYST
        self.assertEqual(self.pl.start(gz["key"], f"{gz['key']}-x", "/srv/w/gz", "agent:coordinator")[0]["status"],
                         "IN_PROGRESS")
        self.assertEqual((self.pl.lanes("samvision"), self.pl.lanes("gyst")), (2, 1))
        with self.assertRaises(TaskError):
            self.pl.start(sv[2], f"{sv[2]}-x", "/srv/w/c", "agent:coordinator")
        from ccd import registry
        old = registry.PROJECTS["samvision"].get("pipeline")
        registry.PROJECTS["samvision"]["pipeline"] = dict(old or {}, max_lanes=3)
        try:
            self.assertEqual(self.pl.start(sv[2], f"{sv[2]}-x", "/srv/w/c", "agent:coordinator")[0]["status"],
                             "IN_PROGRESS")
        finally:
            registry.PROJECTS["samvision"]["pipeline"] = old


class Review(Base):
    def test_approval_is_tied_to_the_pr_head_and_green_checks(self):
        k = self.ticket()
        self.to_review(k)
        t, _, _ = self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="review-1", pr=self.pr(green=False))
        self.assertEqual(t["status"], "IN_REVIEW")                           # CI not green yet
        t, _, _ = self.pl.sync_pr(k, self.pr(green=True))
        self.assertEqual(t["status"], "READY_TO_MERGE")
        self.assertEqual(self.pl.work(k)["gate"], "merge")                  # owner merge by default
        self.pl.confirm(k, "merge", "jay")                                  # Jay authorised the merge…
        t, _, ev = self.pl.sync_pr(k, self.pr(head="1234567" + "0" * 33))   # …then a new commit lands
        self.assertEqual(t["status"], "IN_REVIEW")
        self.assertEqual([e[0] for e in ev], ["pipeline.review_stale"])
        w = self.pl.work(k)
        self.assertEqual((w["review"]["verdict"], w["gate"], w["review"]["head"]), (None, None, HEAD))
        self.assertNotIn("merge", w["confirmed"])                           # the authorisation was for the old head
        new = "1234567" + "0" * 33
        self.pl.review(k, "APPROVE", new, "agent:reviewer", session="review-1", pr=self.pr(head=new))
        self.assertEqual((self.ts.get(k)["status"], self.pl.work(k)["gate"]), ("READY_TO_MERGE", "merge"))

    def test_an_approval_for_another_head_never_promotes(self):
        k = self.ticket()
        self.to_review(k)
        t, _, _ = self.pl.review(k, "APPROVE", "fedcba9" + "0" * 33, "agent:reviewer", session="review-1", pr=self.pr())
        self.assertEqual(t["status"], "IN_REVIEW")
        self.assertEqual(self.pl.sync_pr(k, self.pr())[0]["status"], "IN_REVIEW")
        for draft in (True,):
            self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="review-1", pr=self.pr(draft=draft))
            self.assertEqual(self.ts.get(k)["status"], "IN_REVIEW")

    def test_two_failed_review_cycles_block_for_jay(self):
        k = self.ticket()
        self.to_review(k)
        f = [{"scope": "in", "category": "correctness", "summary": "off by one"},
             {"scope": "out", "category": "perf", "summary": "slow query elsewhere"}]
        t, _, _ = self.pl.review(k, "REQUEST_CHANGES", HEAD, "agent:reviewer", findings=f)
        self.assertEqual(t["status"], "IN_REVIEW")
        t, _, _ = self.pl.review(k, "REQUEST_CHANGES", "1234567" + "0" * 33, "agent:reviewer")
        self.assertEqual(t["status"], "BLOCKED")
        w = self.pl.work(k)
        self.assertEqual((w["gate"], w["review"]["cycles"], w["blocked"]["stage"]), ("failure", MAX_REVIEW_CYCLES, "REVIEW"))
        self.assertEqual([(x["scope"], x["category"]) for x in w["findings"]], [("in", "correctness"), ("out", "perf")])
        self.assertEqual(w["stage"], "REVIEW")
        self.assertEqual([s["state"] for s in w["stages"]], ["done", "done", "blocked", "todo", "todo"])
        t, _, _ = self.pl.confirm(k, "failure", "jay")                     # Jay unblocks: back to review
        self.assertEqual((t["status"], self.pl.work(k)["review"]["cycles"]), ("IN_REVIEW", 0))

    def ready_and_authorised(self, k):
        self.to_review(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="review-1", pr=self.pr())
        self.assertEqual((self.ts.get(k)["status"], self.pl.work(k)["gate"]), ("READY_TO_MERGE", "merge"))

    def test_changes_requested_after_ready_closes_the_merge_gate(self):
        k = self.ticket()
        self.ready_and_authorised(k)
        t, _, _ = self.pl.review(k, "REQUEST_CHANGES", HEAD, "agent:reviewer", pr=self.pr())
        w = self.pl.work(k)
        self.assertEqual((t["status"], w["gate"]), ("IN_REVIEW", None))
        self.assertEqual(self.pl.needs(), [])
        with self.assertRaises(TaskError):
            self.pl.confirm(k, "merge", "jay")

    def test_a_merge_authorisation_never_covers_another_head(self):
        k = self.ticket()
        self.ready_and_authorised(k)
        self.pl.confirm(k, "merge", "jay")                                 # Jay authorises head A
        self.assertEqual(self.pl.work(k)["confirmed"], [f"merge:{HEAD}"])
        b = "b" * 40
        t, _, _ = self.pl.review(k, "APPROVE", b, "agent:reviewer", session="review-1", pr=self.pr(head=b))   # before the poll sees B
        self.assertEqual((t["status"], self.pl.work(k)["gate"]), ("READY_TO_MERGE", "merge"))
        self.assertTrue(self.pl.needs()[0]["text"].startswith("Ready to merge"))

    def test_resume_after_a_block_needs_a_new_merge_authorisation_for_a_new_head(self):
        k = self.ticket()
        self.ready_and_authorised(k)
        self.pl.confirm(k, "merge", "jay")
        self.pl.block(k, "CI infra down", "agent:coordinator")
        self.pl.confirm(k, "failure", "jay")
        b = "c" * 40
        self.pl.review(k, "APPROVE", b, "agent:reviewer", session="review-1", pr=self.pr(head=b))
        self.assertEqual((self.ts.get(k)["status"], self.pl.work(k)["gate"]), ("READY_TO_MERGE", "merge"))

    def test_red_checks_or_draft_at_the_same_head_go_back_to_review_and_return(self):
        k = self.ticket()
        self.ready_and_authorised(k)
        t, _, ev = self.pl.sync_pr(k, self.pr(green=False))
        self.assertEqual((t["status"], self.pl.work(k)["gate"], ev[0][0]), ("IN_REVIEW", None, "pipeline.not_ready"))
        self.assertEqual(self.pl.sync_pr(k, self.pr())[0]["status"], "READY_TO_MERGE")      # green again
        self.assertEqual(self.pl.sync_pr(k, self.pr(draft=True))[0]["status"], "IN_REVIEW")

    def test_another_pr_on_the_ticket_says_nothing_about_the_reviewed_one(self):
        k = self.ticket()
        self.to_review(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="review-1", pr=self.pr())
        self.assertEqual(self.ts.get(k)["status"], "READY_TO_MERGE")
        other = {"ref": "JayDalool/SamVisionAI#2", "head": "2" * 40, "ciGreen": True, "draft": False}
        t, ch, ev = self.pl.sync_pr(k, other)
        self.assertEqual((t["status"], ch, ev), ("READY_TO_MERGE", [], []))

    def test_bad_input_is_refused(self):
        k = self.ticket()
        self.to_review(k)
        for verdict, head in (("LGTM", HEAD), ("APPROVE", "main"), ("APPROVE", "zzzzzzz"), ("APPROVE", None),
                              ("APPROVE", HEAD[:7]), ("APPROVE", HEAD[:39])):     # a prefix could match another head
            with self.assertRaises(TaskError):
                self.pl.review(k, verdict, head, "agent:reviewer")
        with self.assertRaises(TaskError):
            self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="review-1", findings=[{"scope": "maybe", "summary": "x"}])
        k2 = self.ticket()
        with self.assertRaises(TaskError):                                  # no review before a PR
            self.pl.review(k2, "APPROVE", HEAD, "agent:reviewer", session="review-1")


class Verify(Base):
    def merged(self, k):
        self.to_review(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="review-1", pr=self.pr())
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
        self.assertEqual(ts.applied, [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])
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
