"""The control room backend (plans/COMMAND-CENTER-CONTROL-ROOM.md): questions that resume the SAME task
session, scope-change routing, rework vs re-plan, merge acceptance, the live-deploy notice, the one writer
with checkpoints, evidence, readable records, task terminals and what closing a task releases."""
import asyncio
import json
import os
import tempfile
import unittest

from ccd import coordid, pty, records, registry
from ccd.pipeline import Pipeline, needs_acceptance, visible_stage
from ccd.tasks import TaskError

from .test_api import JSON
from .test_pipeline import HEAD, PLAN, Base
from .test_tasks_api import PipelineApi


class Questions(Base):
    def test_one_and_three_questions_persist_and_are_answered_once_by_jay(self):
        k = self.ticket()
        self.pl.ask(k, ["Should mobile use the same layout?"], "agent:coordinator")
        w = self.pl.work(k)
        self.assertEqual((w["openQuestions"], w["visibleStage"]), (1, "Needs Jay"))
        self.pl.ask(k, [{"text": "Apply to CMA too?", "kind": "yesno"},
                        {"text": "Which option?", "options": ["A", "B"]},
                        "Which user groups first?"], "agent:coordinator")
        w = self.pl.work(k)
        self.assertEqual([q["batch"] for q in w["questions"]], [1, 2, 2, 2])
        self.assertEqual([q["kind"] for q in w["questions"]], ["text", "yesno", "choice", "text"])
        ids = [q["id"] for q in w["questions"]]
        with self.assertRaises(TaskError) as e:
            self.pl.answer(k, [{"id": ids[0], "answer": "yes"}], "agent:coordinator")
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(TaskError):
            self.pl.answer(k, [{"id": ids[1], "answer": "maybe"}], "jay")       # yes/no question
        self.pl.answer(k, [{"id": ids[0], "answer": "Same layout"}, {"id": ids[1], "answer": "No"}], "jay")
        with self.assertRaises(TaskError) as e:
            self.pl.answer(k, [{"id": ids[0], "answer": "changed my mind"}], "jay")
        self.assertEqual(e.exception.status, 409)
        w = self.pl.work(k)
        self.assertEqual(w["openQuestions"], 2)
        self.assertEqual([n["kind"] for n in self.pl.needs()], ["questions"])
        self.pl.answer(k, [{"id": ids[2], "answer": "B"}, {"id": ids[3], "answer": "Agents"}], "jay")
        w = self.pl.work(k)
        self.assertEqual((w["openQuestions"], w["visibleStage"]), (0, "Planning"))
        self.assertEqual(self.pl.needs(), [])

    def test_bad_questions_are_refused(self):
        k = self.ticket()
        for bad in ([], [{"text": ""}], [{"text": "x", "kind": "choice", "options": ["only"]}], ["q"] * 11):
            with self.assertRaises(TaskError):
                self.pl.ask(k, bad, "agent:coordinator")


class Routing(Base):
    def test_rework_goes_to_implementation_and_replan_to_planning(self):
        k = self.ticket()
        self.to_review(k)
        self.pl.review(k, "REQUEST_CHANGES", HEAD, "agent:reviewer")
        t, _, _ = self.pl.rework(k, "button overlaps on mobile", "jay")
        self.assertEqual(t["status"], "IN_PROGRESS")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation")
        t, _, _ = self.pl.replan(k, "auth model changes", "jay")
        w = self.pl.work(k)
        self.assertEqual((t["status"], w["planState"], w["visibleStage"]), ("RESEARCHING", "proposed", "Planning"))
        self.assertIn("owner:accept", w["confirmed"])
        kinds = [e["kind"] for e in self.ts.get(k)["timeline"]]
        self.assertIn("pipeline.rework", kinds)
        self.assertIn("pipeline.replan", kinds)

    def test_implementer_cannot_approve_its_own_work(self):
        k = self.ticket()
        self.to_review(k)
        self.pl.role(k, "implementer", "agent:implementer", model="sonnet", session="sv-x")
        with self.assertRaises(TaskError):
            self.pl.review(k, "APPROVE", HEAD, "agent:implementer")
        with self.assertRaises(TaskError):
            self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="sv-x")
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", session="sv-review", pr=self.pr())
        self.assertEqual(self.ts.get(k)["status"], "READY_TO_MERGE")


class Blockers(Base):
    def test_a_blocker_is_explained_for_a_manager_first(self):
        k = self.ticket()
        self.to_review(k)
        self.pl.block(k, "mobile UI test failed", "agent:verifier", {
            "what": "The action buttons overlap on narrow screens.", "why": "Merging would ship a mobile regression.",
            "action": "Fix the mobile layout and rerun UI verification.", "impact": "Small.",
            "technical": "playwright: tests/ui/valuation.spec.ts:42 expected no overlap"})
        b = self.pl.work(k)["blocked"]
        self.assertEqual((b["stage"], b["what"][:15], b["impact"]), ("REVIEW", "The action butt", "Small."))
        t, _, _ = self.pl.rework(k, "fix the mobile layout", "jay")      # Fix and continue
        self.assertEqual((t["status"], self.pl.work(k)["blocked"]), ("IN_PROGRESS", None))


class MergeAcceptance(Base):
    """Clean work merges without Jay; Jay accepts UI, needs:jay, owner-policy and re-planned work."""
    def gz(self, **fields):
        t, _ = self.ts.create("gyst", "Inbox rules", **fields)
        k = t["key"]
        self.pl.plan(k, PLAN, "agent:planner")
        self.pl.start(k, f"{k}-rules", f"/srv/w/{k}", "agent:coordinator")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation")
        return k

    def test_clean_work_needs_no_merge_gate(self):
        k = self.gz()
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", pr=dict(self.pr(), ref="JayDalool/gyst#1"))
        w = self.pl.work(k)
        self.assertEqual((self.ts.get(k)["status"], w["gate"], w["visibleStage"]), ("READY_TO_MERGE", None, "Ready to Merge"))

    def test_ui_and_owner_projects_and_replans_need_jay(self):
        k = self.gz(labels=["ui"])
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", pr=dict(self.pr(), ref="JayDalool/gyst#1"))
        self.assertEqual(self.pl.work(k)["gate"], "merge")
        sv = self.ticket()                       # SamVision keeps its owner merge rule
        self.to_review(sv)
        self.pl.review(sv, "APPROVE", HEAD, "agent:reviewer", pr=self.pr())
        self.assertEqual(self.pl.work(sv)["gate"], "merge")
        t = self.ts.get(self.gz())
        self.assertFalse(needs_acceptance(t, {"confirmed": []}))
        self.assertTrue(needs_acceptance(t, {"confirmed": ["owner:accept"]}))
        self.assertEqual(registry.pipeline_of("samvision")["merge"], "owner")
        self.assertEqual(registry.pipeline_of("gauzemate")["merge"], "auto")


class LiveDeploy(Base):
    def verifying(self):
        k = self.ticket()
        self.to_review(k)
        self.pl.review(k, "APPROVE", HEAD, "agent:reviewer", pr=self.pr())
        self.pl.confirm(k, "merge", "jay")
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR #1 merged")
        self.pl.merged(k, "JayDalool/SamVisionAI#1", "f" * 40)
        return k

    def test_live_deploy_always_waits_for_jay_then_is_verified_then_closes(self):
        k = self.verifying()
        self.pl.verify(k, "pass", "UI checked on staging", "agent:verifier")
        self.assertEqual(self.ts.get(k)["status"], "DONE")           # no deploy asked: closes as before

        k = self.verifying()
        self.pl.deploy_request(k, "live", "valuation layout v2", "UI tests 12/12, verifier pass", "agent:coordinator")
        w = self.pl.work(k)
        self.assertEqual((w["gate"], w["visibleStage"]), ("deploy", "Needs Jay"))
        self.assertIn("deploy", [n["gate"] for n in self.pl.needs()])
        with self.assertRaises(TaskError) as e:                       # never silently live
            self.pl.deployed(k, "live", "pass", "smoke ok", "agent:coordinator")
        self.assertEqual(e.exception.status, 409)
        self.pl.verify(k, "pass", "verified before deploy", "agent:verifier")
        self.assertEqual(self.ts.get(k)["status"], "VERIFYING")      # the deploy is still owed
        self.pl.confirm(k, "deploy", "jay")
        w = self.pl.work(k)
        self.assertEqual((self.ts.get(k)["status"], w["visibleStage"]), ("VERIFYING", "Deploying"))
        t, _, _ = self.pl.deployed(k, "live", "pass", "https://samvision.example/health 200", "agent:coordinator")
        self.assertEqual(t["status"], "DONE")
        w = self.pl.work(k)
        self.assertEqual(w["deploy"]["result"], "pass")
        self.assertEqual([e["kind"] for e in w["evidence"]], ["deploy"])

    def test_preview_deploys_need_no_gate_and_a_failed_deploy_blocks(self):
        k = self.verifying()
        self.pl.deploy_request(k, "preview", "preview build", "", "agent:coordinator")
        self.assertIsNone(self.pl.work(k)["gate"])
        t, _, _ = self.pl.deployed(k, "preview", "fail", "500 on /", "agent:coordinator")
        self.assertEqual((t["status"], self.pl.work(k)["visibleStage"]), ("BLOCKED", "Blocked"))


class Writer(Base):
    def test_one_writer_and_a_checkpointed_handover(self):
        k = self.ticket()
        self.pl.writer(k, "codex", "agent:coordinator")
        with self.assertRaises(TaskError) as e:
            self.pl.writer(k, "claude", "agent:coordinator")
        self.assertEqual(e.exception.status, 409)
        cp = {"reason": "Codex hit its rate limit", "branch": f"{k}-x", "commit": "abc1234", "dirty": "2 files",
              "changed": ["a.ts", "b.ts"], "tests": "unit 40/41", "remaining": "fix the last test"}
        self.pl.writer(k, "claude", "agent:coordinator", checkpoint=cp)
        w = self.pl.work(k)
        self.assertEqual((w["writer"], w["checkpoint"]["frm"], w["checkpoint"]["changed"]), ("claude", "codex", ["a.ts", "b.ts"]))
        with self.assertRaises(TaskError):
            self.pl.writer(k, "codex", "agent:coordinator", checkpoint={"commit": "not-a-sha", "remaining": "x"})

    def test_evidence_is_append_only(self):
        k = self.ticket()
        self.pl.evidence(k, "screenshot", "mobile-375.png", "narrow screen", "agent:verifier")
        self.pl.evidence(k, "link", "https://github.com/JayDalool/SamVisionAI/actions/runs/1", None, "agent:verifier")
        self.assertEqual([e["kind"] for e in self.pl.work(k)["evidence"]], ["screenshot", "link"])
        with self.assertRaises(Exception):
            self.ts.db.execute("DELETE FROM ticket_evidence")
        with self.assertRaises(TaskError):
            self.pl.evidence(k, "video", "x", None, "agent:verifier")


class VisibleStages(unittest.TestCase):
    def test_the_ten_stages(self):
        t = lambda st, **kw: dict({"status": st, "flags": [], "labels": [], "type": None, "project": "gyst"}, **kw)  # noqa: E731
        self.assertEqual(visible_stage(t("RESEARCHING")), "Planning")
        self.assertEqual(visible_stage(t("IN_PROGRESS")), "Implementing")
        self.assertEqual(visible_stage(t("IN_REVIEW")), "Reviewing")
        self.assertEqual(visible_stage(t("READY_TO_MERGE")), "Ready to Merge")
        self.assertEqual(visible_stage(t("VERIFYING")), "Verifying")
        self.assertEqual(visible_stage(t("VERIFYING", labels=["ui"])), "UI Testing")
        self.assertEqual(visible_stage(t("VERIFYING"), {"deploy": {"approvedAt": 1}}), "Deploying")
        self.assertEqual(visible_stage(t("IN_PROGRESS"), {"openQuestions": 2}), "Needs Jay")
        self.assertEqual(visible_stage(t("IN_REVIEW"), {"gate": "failure"}), "Blocked")
        self.assertEqual(visible_stage(t("BLOCKED")), "Blocked")
        self.assertEqual(visible_stage(t("CANCELLED")), "Closed")


class Records(Base):
    def test_task_and_workflow_markdown_capture_the_path_and_evidence(self):
        t, _ = self.ts.create("samvision", "Valuation layout", description="## Why\nClearer valuations.\n\n"
                              "## Acceptance criteria\n- [ ] works on all screen sizes\n- [ ] no breaking changes")
        k = t["key"]
        self.to_review(k)
        self.pl.review(k, "REQUEST_CHANGES", HEAD, "agent:reviewer", findings=[{"summary": "overlap on mobile"}])
        self.pl.rework(k, "overlap on mobile", "agent:coordinator")
        self.pl.evidence(k, "screenshot", "mobile.png", None, "agent:verifier")
        t, w = self.ts.get(k), self.pl.work(k)
        task_md, flow = records.render_task(t, w), records.render_workflow(t, w)
        self.assertIn("## Why\n\nClearer valuations.", task_md)
        self.assertIn("- [ ] works on all screen sizes", task_md)
        self.assertIn("## Review round 1", flow)
        self.assertIn("overlap on mobile", flow)
        self.assertIn("## Rework", flow)
        self.assertIn("IN_REVIEW → **IN_PROGRESS**", flow)
        self.assertIn("screenshot: mobile.png", flow)
        with tempfile.TemporaryDirectory() as d:
            out = records.write(t, w, d)
            self.assertEqual(sorted(os.listdir(out)), ["files", "task.md", "workflow.md"])
            self.assertTrue(str(out).endswith(f"samvision/{k}"))
        with self.assertRaises(ValueError):
            records.record_dir({"project": "../x", "key": k}, "/tmp")


class TaskTerminals(unittest.TestCase):
    def test_names_cwds_and_commands(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as wt:
            task = lambda key: (root, wt if key == "SV-071" else None)  # noqa: E731
            self.assertEqual(pty.session_cwd("repo:SV-071", task=task), os.path.realpath(wt))
            self.assertEqual(pty.session_cwd("codex:SV-071", task=task), os.path.realpath(wt))
            self.assertEqual(pty.session_cwd("claude:SV-071", task=task), os.path.realpath(root))
            self.assertEqual(pty.session_cwd("repo:SV-072", task=task), os.path.realpath(root))   # no worktree: root
            self.assertEqual(pty.session_cwd("codex:SV", roots={"SV": root}), os.path.realpath(root))
            for bad in ("repo:sv-071", "codex:../x", "claude:SV-071;rm", "repo:SV-071/..", "shell:SV"):
                with self.assertRaises(pty.PtyError):
                    pty.session_cwd(bad, roots={"SV": root}, task=task)
            with self.assertRaises(pty.PtyError):
                pty.session_cwd("repo:SV-071")       # no resolver: task terminals off
        m = pty.PtyManager(shell="/bin/bash", python="/usr/bin/python3", cc_terminal="/x/cc-terminal")
        self.assertEqual(m.command_for("claude:SV-071"), ["/usr/bin/python3", "/x/cc-terminal", "task", "SV-071"])
        self.assertEqual(m.command_for("claude:SV"), ["/usr/bin/python3", "/x/cc-terminal", "claude", "SV"])
        self.assertEqual(m.command_for("codex:SV-071")[:3], ["/bin/bash", "-l", "-c"])
        self.assertEqual(m.command_for("repo:SV-071"), ["/bin/bash", "-l"])

    def test_task_session_resolver(self):
        rows = [{"pane_id": "w1:p1", "agent": "claude", "name": "sv-071", "agent_status": "idle", "cwd": "/x",
                 "agent_session": {"value": "s1"}},
                {"pane_id": "w1:p2", "agent": "claude", "name": "samvision", "agent_status": "idle", "cwd": "/x"}]
        r = coordid.task_session("SV-071", rows)
        self.assertEqual((r["state"], r["paneId"]), ("ready", "w1:p1"))
        self.assertEqual(coordid.task_session("SV-072", rows)["state"], "none")
        self.assertEqual(coordid.task_session("SV-071", rows + [dict(rows[0], pane_id="w1:p3")])["state"], "multiple")


class ControlRoomApi(PipelineApi):
    """Over HTTP with a fake herdr: answers go to the SAME task Claude session, never a new one."""
    def task_agent(self, status="idle"):
        self.fake.add_agent("w7:p1", "/srv/server/apps/samvisionai", name="sv-056", status=status)
        self.client.portal.call(self.daemon.resync, "test")

    def dev(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON)
        return {"x-ccd-developer": r.json()["session"]}

    def test_answers_resume_the_same_task_session_and_scope_change_replans(self):
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        r = self.step("ask", {"questions": ["Same layout on mobile?", "Apply to CMA?", "Which option?"]})
        self.assertEqual(r.json()["openQuestions"], 3, r.text)
        needs = [n for n in self.get("/api/state").json()["needs"] if n.get("ref") == "SV-056"]
        self.assertEqual([n["kind"] for n in needs], ["questions"])
        ids = [q["id"] for q in r.json()["questions"]]
        body = {"answers": [{"id": ids[0], "answer": "yes"}]}
        self.assertEqual(self.client.post("/api/tasks/SV-056/answers", content=json.dumps(body), headers=JSON).status_code, 403)
        dev = self.dev()
        self.task_agent()
        h = dict(JSON, **dev)
        out = self.client.post("/api/tasks/SV-056/answers", content=json.dumps(body), headers=h).json()
        self.assertEqual((out["complete"], out["delivered"]), (False, False))     # 2 still open: nothing sent yet
        prompts = lambda: [p for m, p in self.fake.calls if m == "agent.prompt"]  # noqa: E731
        self.assertEqual(prompts(), [])
        body = {"answers": [{"id": ids[1], "answer": "no"}, {"id": ids[2], "answer": "B"}], "scopeChange": False}
        out = self.client.post("/api/tasks/SV-056/answers", content=json.dumps(body), headers=h).json()
        self.assertEqual((out["complete"], out["delivered"], out["replanned"]), (True, True, False), out)
        sent = prompts()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["target"], "w7:p1")                              # the existing task session
        self.assertIn("Which option?\n   → B", sent[0]["text"])
        self.assertIn("replan SV-056", sent[0]["text"])                            # the scope guard
        self.assertEqual(self.get("/api/tasks/SV-056/work").json()["status"], "READY_TO_IMPLEMENT")
        # A scope-changing answer sends it back to planning, through the same session.
        ids = [q["id"] for q in self.step("ask", {"questions": ["Use the new auth model?"]}).json()["questions"]
               if q["answer"] is None]
        self.fake.set_status("w7:p1", "idle")
        import time
        time.sleep(1.1)                                                            # the per-pane prompt throttle
        out = self.client.post("/api/tasks/SV-056/answers", content=json.dumps(
            {"answers": [{"id": ids[0], "answer": "yes, switch to SSO"}], "scopeChange": True}), headers=h).json()
        self.assertEqual((out["delivered"], out["replanned"], out["work"]["status"]), (True, True, "RESEARCHING"), out)
        self.assertIn("back in Planning", prompts()[-1]["text"])
        agents = [a for a in self.get("/api/state").json()["agents"] if a.get("agent_name") == "sv-056"]
        self.assertEqual(len(agents), 1)                                           # never a duplicate session

    def test_no_task_session_keeps_answers_and_says_so(self):
        self.ticket("INBOX")
        q = self.step("ask", {"questions": ["One?"]}).json()["questions"][0]
        out = self.client.post("/api/tasks/SV-056/answers", content=json.dumps(
            {"answers": [{"id": q["id"], "answer": "ok"}]}), headers=dict(JSON, **self.dev())).json()
        self.assertEqual((out["complete"], out["delivered"]), (True, False))
        self.assertIn("no task Claude session", out["reason"])
        self.assertEqual(self.get("/api/tasks/SV-056/work").json()["questions"][0]["answer"], "ok")

    def test_lists_carry_the_visible_stage_and_the_record_renders(self):
        self.ticket("IN_PROGRESS")
        self.step("ask", {"questions": ["?"]})
        row = next(t for t in self.get("/api/tasks").json()["tickets"] if t["key"] == "SV-056")
        self.assertEqual((row["openQuestions"], row["visibleStage"]), (1, "Needs Jay"))
        rec = self.get("/api/tasks/SV-056/record").json()
        self.assertIn("# SV-056", rec["taskMd"])
        self.assertIn("## Questions for Jay", rec["workflowMd"])
        self.assertIsNone(rec["dir"])                                              # records off in tests

    def test_closing_a_task_ends_its_terminals_and_asks_its_session_to_exit(self):
        self.ticket("IN_PROGRESS")
        self.task_agent()
        closed = []

        class Ptys:
            async def close_task(self, key):
                closed.append(key)
                return [f"repo:{key}"]
        self.daemon.ptys = Ptys()
        self.client.patch("/api/tasks/SV-056", content=json.dumps({"status": "CANCELLED"}), headers=JSON)
        from .helpers import wait_sync
        wait_sync(lambda: (self.get("/api/tasks/SV-056/work").json().get("released") or None) is not None,
                  what="released")
        w = self.get("/api/tasks/SV-056/work").json()
        self.assertEqual(closed, ["SV-056"])
        self.assertEqual(w["released"]["ptys"], ["repo:SV-056"])
        self.assertIn("/exit", [p["text"] for m, p in self.fake.calls if m == "agent.prompt"])
        coordinator_exits = [p for m, p in self.fake.calls if m == "agent.prompt" and p["target"] != "w7:p1"]
        self.assertEqual(coordinator_exits, [])                                    # the coordinator is never touched

    def test_task_terminal_cwd_uses_only_a_known_worktree(self):
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        with tempfile.TemporaryDirectory() as wt:
            self.step("start", {"branch": "SV-056-x", "worktree": wt})
            root, got = self.daemon.task_cwd("SV-056")
            self.assertIsNone(got)                                                 # not a known worktree
            self.daemon.git["worktrees"]["samvision"] = [wt]
            self.assertEqual(self.daemon.task_cwd("SV-056")[1], os.path.realpath(wt))
        with self.assertRaises(pty.PtyError):
            self.daemon.task_cwd("SV-999")


if __name__ == "__main__":
    unittest.main()
