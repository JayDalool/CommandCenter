"""The delivery flow (ccd/flow.py over ccd/pipeline.py): sizes, acceptance criteria, intake, technical review, user
check, the closing note, WIP limits, children before parents, stale tickets, and the flow / handoffs read shapes."""
import unittest
from unittest import mock

from ccd import flow, pipeline, pipeline_cli
from ccd.pipeline import Pipeline
from ccd.tasks import TaskError, TaskStore

PROJECTS = [{"key": "samvision", "name": "SamVision", "prefix": "SV"}, {"key": "gyst", "name": "GYST", "prefix": "GYST"}]
PLAN = {"summary": "Show the valuation comparison", "approach": "new view", "reproduced": "yes",
        "findings": ["the comps query ignores sold dates"]}
HEAD = "abcdef1234567890abcdef1234567890abcdef12"
HEAD2 = "1234567890abcdef1234567890abcdef12345678"
WT = "/srv/server/worktrees/sv/"


class Base(unittest.TestCase):
    def setUp(self):
        self.ts = TaskStore(":memory:", PROJECTS)
        self.pl = Pipeline(self.ts)

    def ticket(self, project="samvision", description="Comps table is empty for sold homes", **fields):
        return self.ts.create(project, "Valuation comparison", description=description, **fields)[0]["key"]

    def sized(self, size="standard", **fields):
        k = self.ticket(**fields)
        self.pl.intake(k, size, ["Five comps show", "Sold dates are used"], "agent:coordinator")
        return k

    def pr(self, head=HEAD):
        return {"ref": "JayDalool/SamVisionAI#1", "head": head, "ciGreen": True, "draft": False}

    def planned(self, size="standard", **fields):
        k = self.sized(size, **fields)
        self.pl.role(k, "planner", "agent:planner", session="inv-1")
        self.pl.plan(k, PLAN, "agent:planner", session="inv-1")
        return k

    def approved(self, **fields):
        k = self.planned(**fields)
        self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", "small, contained", blast="one view",
                            tests=["unit"], session="tr-1")
        return k

    def in_review(self, k):
        self.pl.start(k, f"{k}-valuation", WT + k, "agent:coordinator")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #1 is open")

    def passed(self, k, head=HEAD):
        ids = [c["id"] for c in self.pl.work(k)["criteria"]]
        return self.pl.user_check(k, "pass", head, "agent:user-reviewer", "tried both", {i: "pass" for i in ids},
                                  pr=self.pr(head), session="ur-1")

    def status(self, k):
        return self.ts.get(k)["status"]

    def refused(self, status, fn, *a, **kw):
        with self.assertRaises(TaskError) as e:
            fn(*a, **kw)
        self.assertEqual(e.exception.status, status, e.exception.message)
        return e.exception.message


class Intake(Base):
    def test_intake_needs_a_description_a_size_and_a_criterion(self):
        k = self.ticket(description="")
        self.assertIn("no description", self.refused(409, self.pl.intake, k, "small", ["works"], "agent:coordinator"))
        k = self.ticket()
        self.refused(400, self.pl.intake, k, "huge", ["works"], "agent:coordinator")
        self.refused(400, self.pl.intake, k, "small", [], "agent:coordinator")
        self.refused(403, self.pl.intake, k, "small", ["works"], "agent:planner")
        self.assertEqual(self.status(k), "INBOX")

    def test_small_goes_to_build_and_standard_to_investigation(self):
        s = self.sized("small")
        self.assertEqual(self.status(s), "READY_TO_IMPLEMENT")
        w = self.pl.work(s)
        self.assertEqual((w["size"], w["flow"]["stage"]), ("small", "build"))
        self.assertEqual([c["id"] for c in w["criteria"]], ["c1", "c2"])
        self.assertEqual({c["state"] for c in w["criteria"]}, {"open"})
        st = {x["stage"]: x["state"] for x in w["flow"]["stages"]}
        self.assertEqual((st["investigate"], st["techReview"], st["userCheck"], st["intake"]),
                         ("skipped", "skipped", "skipped", "done"))
        # small starts with no plan at all
        self.assertEqual(self.pl.start(s, f"{s}-x", WT + s, "agent:coordinator")[0]["status"], "IN_PROGRESS")
        k = self.sized("standard")
        self.assertEqual(self.status(k), "RESEARCHING")
        self.assertEqual(self.pl.work(k)["flow"]["stage"], "investigate")

    def test_a_ui_ticket_keeps_its_user_check_when_small(self):
        k = self.sized("small", labels=["ui"])
        self.assertIn("userCheck", self.pl.work(k)["flow"]["route"])

    def test_the_policy_makes_a_ticket_risky_whatever_was_typed(self):
        k = self.sized("small", labels=["migration"])
        w = self.pl.work(k)
        self.assertEqual((w["size"], self.status(k)), ("risky", "RESEARCHING"))

    def test_a_ticket_nobody_sized_keeps_todays_steps(self):
        k = self.ticket()
        w = self.pl.work(k)
        self.assertIsNone(w["size"])
        self.assertEqual(w["flow"]["route"], list(flow.LEGACY_ROUTE))
        t, _, _ = self.pl.plan(k, PLAN, "agent:planner")
        self.assertEqual(t["status"], "READY_TO_IMPLEMENT")          # no technical review for an unsized ticket


class Criteria(Base):
    def test_the_lead_edits_criteria_until_investigation_ends_then_only_jay(self):
        k = self.sized()
        self.pl.define(k, "agent:coordinator", criteria=[{"id": "c1", "text": "Five comps show"}, "New: CSV export"],
                       requirements=["keep the old URL"])
        w = self.pl.work(k)
        self.assertEqual([(c["id"], c["text"]) for c in w["criteria"]], [("c1", "Five comps show"),
                                                                        ("c3", "New: CSV export")])
        self.assertEqual(w["requirements"], ["keep the old URL"])
        self.pl.role(k, "planner", "agent:planner", session="inv-1")
        self.pl.plan(k, PLAN, "agent:planner", session="inv-1")
        self.refused(409, self.pl.define, k, "agent:coordinator", criteria=["x"])
        self.pl.define(k, "jay", criteria=[{"id": "c1", "text": "Five comps show"}, {"id": "c3", "text": "XLSX export"}])
        self.assertEqual(self.pl.work(k)["criteria"][1]["text"], "XLSX export")

    def test_an_edited_criterion_is_open_again(self):
        k = self.approved()
        self.in_review(k)
        self.passed(k)
        self.assertEqual({c["state"] for c in self.pl.work(k)["criteria"]}, {"pass"})
        self.pl.define(k, "jay", criteria=[{"id": "c1", "text": "Five comps show"}, {"id": "c2", "text": "Sold dates, newest first"}])
        crit = self.pl.work(k)["criteria"]
        self.assertEqual([(c["id"], c["state"]) for c in crit], [("c1", "pass"), ("c2", "open")])

    def test_only_jay_lowers_a_risky_ticket(self):
        k = self.sized("risky")
        self.refused(403, self.pl.define, k, "agent:coordinator", size="standard")
        self.pl.define(k, "jay", size="standard")
        self.assertEqual(self.pl.work(k)["size"], "standard")
        self.pl.define(k, "agent:coordinator", size="risky")             # raising is anyone's
        self.assertEqual(self.pl.work(k)["size"], "risky")

    def test_twenty_criteria_at_most(self):
        k = self.ticket()
        self.refused(400, self.pl.intake, k, "small", [f"c{i}" for i in range(21)], "agent:coordinator")


class TechReview(Base):
    def test_a_plan_waits_for_the_technical_reviewer(self):
        k = self.planned()
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["planState"], w["gate"], w["flow"]["stage"]),
                         ("RESEARCHING", "proposed", None, "techReview"))
        self.assertEqual(w["plan"]["reproduced"], "yes")
        self.assertEqual(w["flow"]["waitingOn"], "reviewer")
        self.refused(409, self.pl.start, k, f"{k}-x", WT + k, "agent:coordinator")     # no accepted plan

    def test_the_investigator_cannot_review_its_own_plan(self):
        k = self.planned()
        self.assertIn("own plan", self.refused(409, self.pl.plan_review, k, "APPROVE", "agent:tech-reviewer", "ok",
                                               session="inv-1"))
        self.refused(403, self.pl.plan_review, k, "APPROVE", "agent:reviewer", "ok", session="tr-1")
        self.refused(400, self.pl.plan_review, k, "APPROVE", "agent:tech-reviewer", "ok")      # no session

    def test_approve_sends_it_to_build(self):
        k = self.approved()
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["planState"], w["flow"]["stage"]), ("READY_TO_IMPLEMENT", "accepted", "build"))
        self.assertEqual(w["planReview"]["verdict"], "APPROVE")
        self.assertEqual(w["planReview"]["blast"], "one view")

    def test_two_send_backs_block_it(self):
        k = self.planned()
        self.pl.plan_review(k, "SEND_BACK", "agent:tech-reviewer", "no repro", session="tr-1")
        w = self.pl.work(k)
        self.assertEqual((w["flow"]["stage"], w["flow"]["rounds"], self.status(k)), ("investigate", 0, "RESEARCHING"))
        self.refused(409, self.pl.plan_review, k, "APPROVE", "agent:tech-reviewer", "x", session="tr-1")  # nothing to review
        self.pl.plan(k, PLAN, "agent:planner", session="inv-1")
        self.assertEqual(self.pl.work(k)["flow"]["rounds"], 1)
        self.pl.plan_review(k, "SEND_BACK", "agent:tech-reviewer", "still no repro", session="tr-1")
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["gate"], w["flow"]["stage"]), ("BLOCKED", "failure", "techReview"))
        self.pl.confirm(k, "failure", "jay")
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["flow"]["stage"]), ("RESEARCHING", "investigate"))

    def test_a_risky_plan_goes_to_jay_after_the_review(self):
        k = self.planned(size="risky")
        self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", "ok", session="tr-1")
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["gate"], w["flow"]["stage"], w["flow"]["waitingOn"]),
                         ("RESEARCHING", "plan", "techReview", "jay"))
        self.pl.confirm(k, "plan", "jay")
        self.assertEqual(self.pl.work(k)["flow"]["stage"], "build")

    def test_the_reviewer_raises_a_size_but_never_lowers_it(self):
        k = self.planned()
        self.refused(403, self.pl.plan_review, k, "APPROVE", "agent:tech-reviewer", "ok", size="small", session="tr-1")
        self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", "touches auth", size="risky", session="tr-1")
        w = self.pl.work(k)
        self.assertEqual((w["size"], w["gate"]), ("risky", "plan"))

    def test_a_small_ticket_has_no_investigation(self):
        k = self.sized("small")
        self.refused(409, self.pl.plan, k, PLAN, "agent:planner")


class UserCheck(Base):
    def test_code_review_approves_only_after_the_user_check_on_that_head(self):
        k = self.approved()
        self.in_review(k)
        self.assertEqual(self.pl.work(k)["flow"]["stage"], "userCheck")
        self.assertIn("user check", self.refused(409, self.pl.review, k, "APPROVE", HEAD, "agent:reviewer",
                                                 session="cr-1", pr=self.pr()))
        self.passed(k)
        self.assertEqual(self.pl.work(k)["flow"]["stage"], "codeReview")
        t, _, _ = self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="cr-1", pr=self.pr())
        self.assertEqual(t["status"], "READY_TO_MERGE")

    def test_the_head_must_be_the_prs_current_head(self):
        k = self.approved()
        self.in_review(k)
        self.refused(409, self.pl.user_check, k, "pass", HEAD, "agent:user-reviewer", "ok", pr=self.pr(HEAD2),
                     session="ur-1")
        self.refused(409, self.pl.user_check, k, "pass", HEAD, "agent:user-reviewer", "ok", pr=None, session="ur-1")
        self.refused(409, self.pl.user_check, k, "pass", HEAD, "agent:user-reviewer", "ok", pr=self.pr(),
                     session=k.lower())                              # the developer's own session

    def test_pass_needs_every_criterion(self):
        k = self.approved()
        self.in_review(k)
        msg = self.refused(409, self.pl.user_check, k, "pass", HEAD, "agent:user-reviewer", "ok", {"c1": "pass"},
                           pr=self.pr(), session="ur-1")
        self.assertIn("c2", msg)
        self.refused(400, self.pl.user_check, k, "pass", HEAD, "agent:user-reviewer", "ok", {"c9": "pass"},
                     pr=self.pr(), session="ur-1")

    def test_a_new_head_after_a_pass_clears_it(self):
        k = self.approved()
        self.in_review(k)
        self.passed(k)
        self.pl.sync_pr(k, self.pr(HEAD2))
        w = self.pl.work(k)
        self.assertIsNone(w["userCheck"])
        self.assertEqual(w["flow"]["stage"], "userCheck")
        self.assertEqual(w["handoffs"][-1]["note"], flow.NOTES["user_stale"])

    def test_a_failed_check_goes_back_to_build_and_two_block_it(self):
        k = self.approved()
        self.in_review(k)
        t, _, _ = self.pl.user_check(k, "fail", HEAD, "agent:user-reviewer", "button overlaps", ["c1=fail"],
                                     pr=self.pr(), open_prs=[self.pr()], session="ur-1")
        self.assertEqual(t["status"], "IN_PROGRESS")
        self.assertEqual(self.pl.work(k)["criteria"][0]["state"], "fail")
        self.assertFalse(self.pl.new_head(k, self.pr()))              # the same head does not return it to review
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="new head")
        t, _, _ = self.pl.user_check(k, "fail", HEAD2, "agent:user-reviewer", "still overlaps", pr=self.pr(HEAD2),
                                     session="ur-1")
        self.assertEqual((t["status"], self.pl.work(k)["gate"]), ("BLOCKED", "failure"))
        self.assertEqual(self.pl.work(k)["flow"]["stage"], "userCheck")

    def test_a_route_without_a_user_check_refuses_one(self):
        k = self.sized("small")
        self.in_review(k)
        self.refused(409, self.pl.user_check, k, "pass", HEAD, "agent:user-reviewer", "ok", pr=self.pr(), session="u")


class Closing(Base):
    def verified(self, k):
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR merged")
        self.pl.merged(k, "JayDalool/SamVisionAI#1", "f" * 40)
        return self.pl.verify(k, "pass", "health ok", "agent:verifier")

    def through_review(self, **kw):
        k = self.approved(**kw)
        self.in_review(k)
        self.passed(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="cr-1", pr=self.pr())
        return k

    def test_a_standard_ticket_waits_for_the_leads_closing_note(self):
        k = self.through_review()
        t, _, _ = self.verified(k)
        w = self.pl.work(k)
        self.assertEqual((t["status"], w["flow"]["waitingOn"]), ("VERIFYING", "lead"))
        self.refused(403, self.pl.close, k, "done", "agent:verifier")
        t, _, _ = self.pl.close(k, "Comps fixed; sold dates now drive the query.", "agent:coordinator")
        self.assertEqual(t["status"], "DONE")
        w = self.pl.work(k)
        self.assertEqual(w["closing"]["by"], "agent:coordinator")
        self.assertEqual({s["state"] for s in w["flow"]["stages"]}, {"done"})
        kinds = [h["kind"] for h in w["handoffs"]]
        self.assertEqual(kinds[0], "advanced")
        self.assertEqual([h["stage"] for h in w["handoffs"] if h["kind"] == "advanced"],
                         ["intake", "investigate", "techReview", "build", "build", "userCheck", "codeReview",
                          "merge", "release"])

    def test_a_small_ticket_closes_on_verification(self):
        k = self.sized("small")
        self.pl.start(k, f"{k}-x", WT + k, "agent:coordinator")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR")
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="cr-1", pr=self.pr())
        t, _, _ = self.verified(k)
        self.assertEqual(t["status"], "DONE")

    def test_a_risky_release_waits_for_jays_deploy_approval(self):
        k = self.sized("risky")
        self.pl.role(k, "planner", "agent:planner", session="inv-1")
        self.pl.plan(k, PLAN, "agent:planner", session="inv-1")
        self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", "ok", session="tr-1")
        self.pl.confirm(k, "plan", "jay")
        self.in_review(k)
        self.passed(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="cr-1", pr=self.pr())
        self.verified(k)
        self.assertEqual(self.pl.work(k)["gate"], "deploy")


class Children(Base):
    def test_two_levels_at_most(self):
        a, b, c = self.ticket(), self.ticket(), self.ticket()
        self.ts.update(b, {"parent": a}, "jay")
        self.assertIn("two levels", self.refused(400, self.ts.update, c, {"parent": b}, "jay"))
        self.assertIn("two levels", self.refused(400, self.ts.update, a, {"parent": c}, "jay"))

    def test_a_parent_finishes_after_its_children(self):
        parent = self.ticket()
        child = self.ticket()
        self.pl.intake(child, "small", ["works"], "agent:coordinator", parent=parent)
        self.assertEqual(self.ts.get(child)["parent"], parent)
        self.assertIn(child, self.refused(409, self.ts.update, parent, {"status": "DONE"}, "jay"))
        # A parent that is verified waits in VERIFYING for its children, then for the lead's close.
        self.ts.update(parent, {"status": "VERIFYING"}, "jay")
        t, _, _ = self.pl.verify(parent, "pass", "ok", "agent:verifier")
        self.assertEqual(t["status"], "VERIFYING")
        self.assertIn(child, self.refused(409, self.pl.close, parent, "all done", "agent:coordinator"))
        self.ts.update(child, {"status": "CANCELLED"}, "jay")
        self.assertEqual(self.pl.work(parent)["flow"]["waitingOn"], "lead")
        t, _, _ = self.pl.close(parent, "all done", "agent:coordinator")
        self.assertEqual(t["status"], "DONE")


class Limits(Base):
    def test_two_investigations_per_project(self):
        a, b, c = self.sized(), self.sized(), self.sized()
        self.pl.role(a, "planner", "agent:planner", session="i-a")
        self.pl.role(b, "planner", "agent:planner", session="i-b")
        self.assertIn("investigated", self.refused(409, self.pl.role, c, "planner", "agent:planner", session="i-c"))
        self.refused(409, self.pl.plan, c, PLAN, "agent:planner", session="i-c")
        other = self.sized(project="gyst")
        self.pl.role(other, "planner", "agent:planner", session="i-g")          # per project
        self.pl.plan(a, PLAN, "agent:planner", session="i-a")                   # a moves on to technical review
        self.pl.role(c, "planner", "agent:planner", session="i-c")

    def test_finishing_first_holds_new_work_behind_an_unseated_review(self):
        waiting = self.planned()
        k = self.ticket()
        self.pl.plan(k, PLAN, "agent:planner")                                  # an unsized ticket: ready to start
        later = pipeline._now() + 5 * 3600
        with mock.patch.object(pipeline, "_now", return_value=later):
            msg = self.refused(409, self.pl.start, k, f"{k}-x", WT + k, "agent:coordinator")
            self.assertIn(waiting, msg)
            self.pl.role(waiting, "tech-reviewer", "agent:tech-reviewer", session="tr-1")   # someone takes the seat
            self.assertEqual(self.pl.start(k, f"{k}-x", WT + k, "agent:coordinator")[0]["status"], "IN_PROGRESS")


class Stale(Base):
    def test_one_mark_per_quiet_spell(self):
        k = self.sized()
        self.assertEqual(self.pl.sweep_stale(), [])
        later = pipeline._now() + 49 * 3600
        out = self.pl.sweep_stale(now=later)
        self.assertEqual([r[0]["key"] for r in out], [k])
        self.assertEqual(self.pl.sweep_stale(now=later + 60), [])
        with mock.patch.object(flow, "_now", return_value=later):
            self.assertTrue(self.pl.work(k)["flow"]["stale"])
        marks = self.pl.compact([self.ts.get(k)["id"]])
        self.assertTrue(Pipeline.list_marks(self.ts.get(k), marks[self.ts.get(k)["id"]], now=later)["stale"])
        with mock.patch.object(pipeline, "_now", return_value=later):
            self.pl.role(k, "planner", "agent:planner", session="i")             # any step ends the quiet spell
        with mock.patch.object(flow, "_now", return_value=later + 60):
            self.assertFalse(self.pl.work(k)["flow"]["stale"])

    def test_a_ticket_waiting_on_jay_is_not_stale(self):
        k = self.planned(size="risky")
        self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", "ok", session="tr-1")
        self.assertEqual(self.pl.sweep_stale(now=pipeline._now() + 49 * 3600), [])


class Shapes(Base):
    def test_the_flow_object_has_nine_stages_and_a_holder(self):
        k = self.planned()
        self.pl.role(k, "tech-reviewer", "agent:tech-reviewer", session="tr-1")
        fl = self.pl.work(k)["flow"]
        self.assertEqual([s["stage"] for s in fl["stages"]], list(flow.STAGES))
        self.assertEqual(set(fl), {"size", "stage", "stages", "holder", "next", "waitingOn", "rounds", "idleSince",
                                   "stale", "route", "openChildren"})
        self.assertEqual((fl["holder"]["seat"], fl["holder"]["session"]), ("techReviewer", "tr-1"))
        self.assertEqual(fl["next"], {"stage": "build", "seat": "developer"})
        self.assertIsNone(fl["waitingOn"])
        inv = next(s for s in fl["stages"] if s["stage"] == "investigate")
        self.assertEqual((inv["state"], inv["by"], inv["session"]), ("done", "agent:planner", "inv-1"))

    def test_handoff_notes_are_ccds_words_never_agent_text(self):
        k = self.planned()
        self.pl.plan_review(k, "SEND_BACK", "agent:tech-reviewer", "SECRET agent words", session="tr-1")
        notes = {h["note"] for h in self.pl.work(k)["handoffs"]}
        self.assertTrue(notes <= set(flow.NOTES.values()))
        self.assertEqual(self.pl.work(k)["handoffs"][-1]["kind"], "sentBack")

    def test_list_rows_carry_size_stage_and_stale(self):
        k = self.planned()
        t = self.ts.get(k)
        m = self.pl.compact([t["id"]])[t["id"]]
        self.assertEqual(Pipeline.list_marks(t, m), {"size": "standard", "stage": "techReview", "stale": False})


class Cli(unittest.TestCase):
    def test_the_flow_steps_build_with_their_seat(self):
        self.assertEqual(pipeline_cli.build(["intake", "SV-1", "--size", "small", "--criterion", "works",
                                             "--requirement", "keep CSV", "--parent", "SV-0"]),
                         ("POST", "/api/tasks/SV-1/work/intake", {"size": "small", "criteria": ["works"],
                                                                  "requirements": ["keep CSV"], "parent": "SV-0"},
                          "agent:coordinator"))
        m, path, body, actor = pipeline_cli.build(["plan-review", "SV-1", "SEND_BACK", "--session", "tr", "--note",
                                                   "no repro", "--test", "unit"])
        self.assertEqual((path, actor, body["verdict"], body["tests"]),
                         ("/api/tasks/SV-1/work/plan-review", "agent:tech-reviewer", "SEND_BACK", ["unit"]))
        m, path, body, actor = pipeline_cli.build(["user-check", "SV-1", "pass", "--head", HEAD, "--session", "u",
                                                   "--note", "ok", "--criterion", "c1=pass"])
        self.assertEqual((actor, body["result"], body["criteria"]), ("agent:user-reviewer", "pass", ["c1=pass"]))
        self.assertEqual(pipeline_cli.build(["close", "SV-1", "--note", "done"])[2:],
                         ({"note": "done"}, "agent:coordinator"))
        self.assertEqual(pipeline_cli.build(["user-check", "SV-1", "pass", "--role", "design-reviewer", "--head", HEAD,
                                             "--note", "ok"])[3], "agent:design-reviewer")


if __name__ == "__main__":
    unittest.main()
