"""ccd's auto-merge (daemon._auto_merge, Pipeline.hold_merge): the exact gh commands, the switches, the holds."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from ccd import registry
from ccd.daemon import Daemon
from ccd.config import task_projects, DEFAULTS
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db
from .test_merge_policy import HEAD, REF, f, view

PLAN = {"summary": "add tests", "requirements": [], "approach": "tests", "affected": [], "risk": "low",
        "tests": ["unit"], "questions": []}
REPO = "JayDalool/CommandCenter"


class FakeGh:
    """The `gh` the daemon would run. Records every argv; answers `pr view` and `pr merge`."""

    def __init__(self, pr=None):
        self.calls = []
        self.pr = pr if pr is not None else view()
        self.merge = (0, "", "")
        self.delay = 0
        self.on_view = None

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:3] == ["gh", "pr", "view"]:
            if self.delay:
                time.sleep(self.delay)
            if self.on_view:
                self.on_view()
            return 0, json.dumps(self.pr), ""
        if args[:3] == ["gh", "pr", "merge"]:
            return self.merge
        return 1, "", "unexpected gh call"

    def of(self, verb):
        return [c for c in self.calls if c[:3] == ["gh", "pr", verb]]


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="am-")
        self.config = cfg(auto_merge=True)
        self.store = Store(new_db())
        self.tickets = TaskStore(os.path.join(self.tmp, "tasks.db"), task_projects(self.config))
        self.gh = FakeGh()
        self.daemon = self.make()

    def make(self, **over):
        d = Daemon(dict(self.config, **over), self.store, None, tasks=self.tickets, gh_cli=self.gh)
        d.auto_merge_stop = os.path.join(self.tmp, "auto-merge.stop")
        return d

    async def asyncTearDown(self):
        self.store.close()

    def ready(self, project="commandcenter", number=7, head=HEAD, cache=True, **fields):
        """A ticket in READY_TO_MERGE: planned, started, its PR linked, an approving review recorded at `head`."""
        d, pl = self.daemon, self.daemon.pipeline
        t, _ = self.tickets.create(project, "Add tests", **fields)
        k = t["key"]
        repo = registry.github_of(project)
        ref = f"{repo}#{number}"
        pl.plan(k, PLAN, "agent:planner")
        if pl.work(k)["gate"] == "plan":
            pl.confirm(k, "plan", "jay")
        pl.start(k, f"{k}-tests", f"/srv/server/worktrees/x/{k}", "agent:coordinator")
        self.tickets.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger=f"PR #{number} is open")
        self.tickets.link(k, "github", "pr", ref, None, "x", "system:automation")
        pl.review(k, "APPROVE", head, "agent:reviewer", session="review-1",
                  pr={"ref": ref, "head": head, "ciGreen": True, "ciNone": True, "draft": False})
        if cache:
            if not (d.gh.get(project) or {}).get("data"):
                d.gh[project] = {"data": {"prs": []}, "asOf": 1, "error": None}
            d.gh[project]["data"]["prs"].append({"number": number, "headRefOid": head, "statusCheckRollup": [],
                                                 "isDraft": False})
        return k

    def kinds(self, key):
        return [e["kind"] for e in self.tickets.get(key)["timeline"]]

    def events(self, kind):
        return [e for e in self.store.since(0) if e["kind"] == kind]


class Merges(Base):
    async def test_a_qualifying_pr_is_merged_with_exactly_these_arguments(self):
        k = self.ready()
        self.assertEqual((self.tickets.get(k)["status"], self.daemon.pipeline.work(k)["gate"]), ("READY_TO_MERGE", None))
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("view"), [["gh", "pr", "view", "7", "--repo", REPO, "--json",
                                               "state,isDraft,mergeable,baseRefName,headRefOid,isCrossRepository,files,"
                                               "additions,deletions,statusCheckRollup"]])
        self.assertEqual(self.gh.of("merge"), [["gh", "pr", "merge", "7", "--repo", REPO, "--merge",
                                                "--match-head-commit", HEAD]])
        self.assertEqual(len(self.gh.calls), 2)
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        merged = [e for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.auto_merged"]
        self.assertEqual([(e["actor"], e["data"]["head"], e["data"]["ci"]) for e in merged],
                         [("system:auto-merge", HEAD, "none")])
        self.assertIn("no CI checks", merged[0]["trigger"])
        self.assertNotIn("green", merged[0]["trigger"])
        sec = self.events("merge.auto")
        self.assertEqual([(e["source"], e["ref"]) for e in sec], [("security", k)])

    async def test_green_ci_is_said_as_green(self):
        k = self.ready()
        self.gh.pr = view(statusCheckRollup=[{"conclusion": "SUCCESS"}])
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        text = [e["trigger"] for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.auto_merged"][0]
        self.assertIn("CI green", text)

    async def test_no_gh_call_ever_carries_a_dangerous_flag(self):
        self.ready()
        self.ready(number=8, head="cd" * 20)
        self.gh.merge = (1, "", "boom")
        await self.daemon._auto_merge()
        for argv in self.gh.calls:
            for bad in ("--admin", "--auto", "--squash", "--rebase", "--delete-branch", "-d", "-s", "-r"):
                self.assertNotIn(bad, argv)
        self.assertTrue(self.gh.of("merge"))

    async def test_the_second_pass_does_not_merge_again(self):
        self.ready()
        await self.daemon._auto_merge()
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        self.assertEqual(len(self.gh.of("view")), 1)

    async def test_already_merged_by_jay_is_left_to_the_poll(self):
        k = self.ready()
        self.gh.pr = view(state="MERGED")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertEqual((self.daemon.pipeline.work(k)["gate"], self.tickets.get(k)["status"]), (None, "READY_TO_MERGE"))

    async def test_the_poll_still_moves_a_merged_ticket_to_verifying(self):
        k = self.ready()
        await self.daemon._auto_merge()
        self.tickets.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR #7 merged")   # what the poll does
        self.daemon._pipeline_result(*self.daemon.pipeline.merged(k, f"{REPO}#7", "f" * 40))
        self.assertEqual(self.tickets.get(k)["status"], "VERIFYING")
        self.assertIn("pipeline.merged", self.kinds(k))

    async def test_every_derive_runs_it_after_the_ticket_automation(self):
        order = []
        self.daemon._ticket_automation = lambda: order.append("automation")

        async def am():
            order.append("auto-merge")
        self.daemon._auto_merge = am
        await self.daemon.rederive()
        self.assertEqual(order, ["automation", "auto-merge"])


class Skips(Base):
    async def assertQuiet(self, k, daemon=None):
        await (daemon or self.daemon)._auto_merge()
        self.assertEqual(self.gh.calls, [])
        self.assertEqual((self.daemon.pipeline.work(k)["gate"], self.tickets.get(k)["status"]), (None, "READY_TO_MERGE"))

    async def test_config_off(self):
        d = self.make(auto_merge=False)
        self.assertFalse(d.pipeline.auto_merge)
        k = self.ready()
        self.daemon.pipeline.auto_merge = True   # the ticket is ready ungated; only the config switch is under test
        await self.assertQuiet(k, d)

    async def test_config_must_be_exactly_true(self):
        for v in (None, "true", 1, "yes"):
            d = self.make(auto_merge=v)
            self.assertFalse(d.auto_merge_on, v)
        self.assertIs(DEFAULTS["auto_merge"], False)

    async def test_the_stop_file(self):
        k = self.ready()
        open(self.daemon.auto_merge_stop, "w").close()
        await self.assertQuiet(k)
        os.remove(self.daemon.auto_merge_stop)
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)

    async def test_the_stop_file_is_checked_right_before_the_merge(self):
        k = self.ready()
        self.gh.on_view = lambda: open(self.daemon.auto_merge_stop, "w").close()   # appears while gh view runs
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("view")), 1)
        self.assertEqual(self.gh.of("merge"), [])
        self.assertEqual((self.daemon.pipeline.work(k)["gate"], self.tickets.get(k)["status"]), (None, "READY_TO_MERGE"))

    async def test_policy_owner(self):
        k = self.ready()
        with mock.patch.dict(registry.PROJECTS["commandcenter"], {"pipeline": {"merge": "owner"}}):
            await self.assertQuiet(k)
        with mock.patch.dict(registry.PROJECTS["commandcenter"], {"pipeline": {"merge": "auto"}}):
            await self.assertQuiet(k)

    async def test_owner_projects_never_reach_gh(self):
        self.assertEqual(self.daemon._auto_merge_projects(), ["commandcenter"])
        for project in ("gyst", "mfe", "gauzemate", "samvision"):
            if project not in {p["key"] for p in task_projects(self.config)}:
                continue
            k = self.ready(project)
            self.tickets.db.execute("UPDATE ticket_work SET gate=NULL WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)", (k,))
            self.assertEqual(self.tickets.get(k)["status"], "READY_TO_MERGE")
        self.ready()
        self.gh.calls.clear()
        # the commandcenter ticket merges; nothing else is looked at
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        self.assertTrue(all(c[5] == REPO for c in self.gh.calls))

    async def test_a_project_without_an_allowlist_is_not_a_candidate_even_if_low_risk(self):
        with mock.patch.dict(registry.PROJECTS["gyst"], {"pipeline": {"merge": "low-risk"}}):
            self.assertEqual(self.daemon._auto_merge_projects(), ["commandcenter"])

    async def test_a_stale_head_is_skipped_without_a_gate(self):
        k = self.ready()
        self.gh.pr = view(headRefOid="cd" * 20)
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertEqual((self.daemon.pipeline.work(k)["gate"], self.tickets.get(k)["status"]), (None, "READY_TO_MERGE"))
        self.assertEqual(self.events("merge.auto"), [])

    async def test_an_open_gate_is_never_touched_or_retried(self):
        k = self.ready()
        self.daemon.pipeline.hold_merge(k, HEAD, "Jay wants to look")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])

    async def test_pending_ci_and_unknown_mergeability_wait_without_a_gate(self):
        k = self.ready()
        self.gh.pr = view(statusCheckRollup=[{"status": "IN_PROGRESS", "conclusion": ""}])
        await self.daemon._auto_merge()
        await self.daemon._auto_merge()      # looked at once, then left alone for a minute
        self.assertEqual((len(self.gh.of("view")), self.gh.of("merge")), (1, []))
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        self.daemon._am_next.clear()
        self.gh.pr = view()
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)

    async def test_gh_down_changes_nothing(self):
        k = self.ready()
        self.daemon.gh_cli = lambda args: (1, "", "gh: not logged in")
        await self.daemon._auto_merge()
        self.assertEqual((self.daemon.pipeline.work(k)["gate"], self.tickets.get(k)["status"]), (None, "READY_TO_MERGE"))
        self.assertEqual([e["data"].get("kind") for e in self.events("task.pipeline")][-1:], ["pipeline.auto_merge_unreadable"])


class Holds(Base):
    async def test_a_pr_that_does_not_qualify_opens_a_merge_gate_with_the_reason(self):
        k = self.ready()
        self.gh.pr = view([f("server/ccd/daemon.py"), f("server/tests/test_a.py", "ADDED")])
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("server/ccd/daemon.py is never auto-merged", w["gateReason"])
        self.assertIn("auto-merge held", w["gateReason"])
        self.assertEqual(w["visibleStage"], "Needs Jay")
        self.assertEqual([n["gate"] for n in self.daemon.pipeline.needs()], ["merge"])
        self.assertIn("pipeline.auto_merge_held", self.kinds(k))
        self.assertIn("pipeline.gate_opened", self.kinds(k))
        held = [e for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.auto_merge_held"][0]
        self.assertEqual((held["actor"], held["data"]["head"]), ("system:auto-merge", HEAD))
        self.assertEqual(len(self.events("merge.auto")), 1)
        self.assertIn("pipeline.auto_merge_held", [e["data"].get("kind") for e in self.events("task.pipeline")
                                                    if e["severity"] == "action"])

    async def test_each_exclusion_holds(self):
        for over, pr in (({"labels": ["migration"]}, None), ({"needs_jay": True}, None),
                         ({}, view(isDraft=True)), ({}, view(mergeable="CONFLICTING")),
                         ({}, view(baseRefName="dev")), ({}, view(isCrossRepository=True)),
                         ({}, view(statusCheckRollup=[{"conclusion": "FAILURE"}])),
                         ({}, view([f("docs/API.md", "DELETED")])), ({}, view([f("docs/img/a.png", "ADDED")])),
                         ({}, view([f(f"docs/a{i}.md", "ADDED") for i in range(11)]))):
            gh = FakeGh(pr or view())
            self.gh = gh
            self.daemon = d = self.make()
            k = self.ready(**over)
            self.tickets.db.execute("UPDATE ticket_work SET gate=NULL WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)", (k,))
            await d._auto_merge()
            self.assertEqual(gh.of("merge"), [], (over, pr))
            self.assertEqual(d.pipeline.work(k)["gate"], "merge", (over, pr))

    async def test_a_failed_merge_opens_a_gate_and_is_not_retried(self):
        k = self.ready()
        self.gh.merge = (1, "", "GraphQL: Head branch was modified. Review and try the merge again.")
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("auto-merge failed", w["gateReason"])
        self.assertIn("Head branch was modified", w["gateReason"])
        self.assertIn("pipeline.auto_merge_failed", self.kinds(k))
        self.assertNotIn("pipeline.auto_merged", self.kinds(k))
        for _ in range(3):
            await self.daemon._auto_merge()
        self.assertEqual((len(self.gh.of("merge")), len(self.gh.of("view"))), (1, 1))
        # Jay closes the gate: the same head is still never retried by ccd (he merges it himself)
        self.daemon.pipeline.confirm(k, "merge", "jay")
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)

    async def test_a_new_reviewed_head_is_a_new_candidate(self):
        k = self.ready()
        self.gh.merge = (1, "", "boom")
        await self.daemon._auto_merge()
        new = "ef" * 20
        pl = self.daemon.pipeline
        self.tickets.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #7 new head")
        pl.db.execute("UPDATE ticket_work SET gate=NULL WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)", (k,))
        pl.review(k, "APPROVE", new, "agent:reviewer", session="review-2",
                  pr={"ref": f"{REPO}#7", "head": new, "ciGreen": True, "ciNone": True, "draft": False})
        self.daemon.gh["commandcenter"]["data"]["prs"][0]["headRefOid"] = new
        self.gh.pr = view(headRefOid=new)
        self.gh.merge = (0, "", "")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge")[-1][-1], new)

    async def test_hold_merge_is_exact_about_the_head_and_the_state(self):
        pl = self.daemon.pipeline
        k = self.ready()
        t, ch, ev = pl.hold_merge(k, "cd" * 20, "wrong head")
        self.assertEqual((ev, pl.work(k)["gate"]), ([], None))
        t, ch, ev = pl.hold_merge(k, HEAD, "x" * 500)
        self.assertEqual(pl.work(k)["gateReason"], "auto-merge held: " + "x" * 280)
        n = len(self.tickets.get(k)["timeline"])
        t, ch, ev = pl.hold_merge(k, HEAD, "again")          # a gate is already open: nothing new
        self.assertEqual((ev, len(self.tickets.get(k)["timeline"])), ([], n))

    async def test_a_pr_with_no_known_number_is_held(self):
        k = self.ready(cache=False)
        w = self.daemon.pipeline.work(k)
        self.tickets.db.execute("UPDATE ticket_work SET review_pr=NULL WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)", (k,))
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")
        self.assertIn("no single open PR", self.daemon.pipeline.work(k)["gateReason"])
        self.assertTrue(w)


class Loop(Base):
    async def test_the_event_loop_is_not_blocked_by_gh(self):
        self.ready()
        self.gh.delay = 0.4
        ticks = []

        async def ticker():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        t = asyncio.create_task(ticker())
        started = time.monotonic()
        await self.daemon._auto_merge()
        t.cancel()
        self.assertGreaterEqual(time.monotonic() - started, 0.4)
        self.assertGreaterEqual(len(ticks), 10)          # the loop kept running while gh slept in its thread
        self.assertEqual(len(self.gh.of("merge")), 1)

    async def test_two_passes_at_once_merge_once(self):
        self.ready()
        self.gh.delay = 0.2
        await asyncio.gather(self.daemon._auto_merge(), self.daemon._auto_merge())
        self.assertEqual(len(self.gh.of("merge")), 1)


class Startup(Base):
    async def test_the_enabled_state_is_a_security_event(self):
        self.daemon._log_merge_policy()
        ev = self.events("merge.policy")
        self.assertEqual([(e["source"], e["data"]["status"]) for e in ev], [("security", "enabled")])
        self.assertIn("auto-merge ON", ev[0]["text"])
        self.assertIn("commandcenter", ev[0]["text"])
        off = self.make(auto_merge=False)
        off._log_merge_policy()
        last = self.events("merge.policy")[-1]
        self.assertEqual(last["data"]["status"], "disabled")
        self.assertIn("auto-merge OFF", last["text"])
        open(off.auto_merge_stop, "w").close()
        off._log_merge_policy()
        self.assertIn("stop file present", self.events("merge.policy")[-1]["text"])

    async def test_the_default_config_is_off_and_the_stop_file_lives_in_the_state_folder(self):
        from ccd import config
        self.assertIs(config.DEFAULTS["auto_merge"], False)
        self.assertEqual(config.AUTO_MERGE_STOP.name, "auto-merge.stop")
        self.assertEqual(config.AUTO_MERGE_STOP.parent, config.STATE_DIR)


class Texts(Base):
    async def test_no_checks_is_never_called_green_in_the_ready_event(self):
        k = self.ready()
        ev = [e["trigger"] for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.ready_to_merge"]
        self.assertEqual(len(ev), 1)
        self.assertIn("no CI checks", ev[0])
        self.assertNotIn("green", ev[0])


class Gates(Base):
    """Tickets that were READY_TO_MERGE with no gate (approved under the old rules) get their merge gate on the poll."""
    def prstate(self, head=HEAD):
        return {"ref": f"{REPO}#7", "head": head, "ciGreen": True, "ciNone": True, "draft": False}

    def ungate(self, k):
        self.tickets.db.execute("UPDATE ticket_work SET gate=NULL, gate_reason=NULL WHERE ticket_id="
                                "(SELECT id FROM tickets WHERE key=?)", (k,))

    async def test_a_ready_ticket_without_a_gate_gets_one_when_auto_merge_is_off(self):
        d = self.make(auto_merge=False)
        self.daemon = d
        k = self.ready()
        self.assertEqual(d.pipeline.work(k)["gate"], "merge")        # a fresh transition: gate at once
        self.ungate(k)
        t, ch, ev = d.pipeline.sync_pr(k, self.prstate())
        w = d.pipeline.work(k)
        self.assertEqual((t["status"], w["gate"]), ("READY_TO_MERGE", "merge"))
        self.assertEqual([e[0] for e in ev], ["pipeline.gate_opened"])
        self.assertEqual([n["gate"] for n in d.pipeline.needs()], ["merge"])
        n = len(self.tickets.get(k)["timeline"])
        d.pipeline.sync_pr(k, self.prstate())                          # idempotent: one gate
        self.assertEqual(len(self.tickets.get(k)["timeline"]), n)
        await d._auto_merge()
        self.assertEqual(self.gh.calls, [])

    async def test_a_ready_owner_project_ticket_without_a_gate_gets_one(self):
        k = self.ready("gyst")
        self.ungate(k)
        pr = dict(self.prstate(), ref="JayDalool/gyst-lifeops#7")
        self.daemon.pipeline.sync_pr(k, pr)
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")

    async def test_no_gate_is_added_while_auto_merge_is_on_or_after_jay_decided_or_for_another_head(self):
        k = self.ready()
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        self.daemon.pipeline.sync_pr(k, self.prstate())
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)        # low-risk with auto-merge on: ccd decides
        d = self.make(auto_merge=False)
        self.daemon = d
        k2 = self.ready(number=8, head="cd" * 20)
        d.pipeline.confirm(k2, "merge", "jay")
        d.pipeline.sync_pr(k2, dict(self.prstate("cd" * 20), ref=f"{REPO}#8"))
        self.assertEqual(d.pipeline.work(k2)["gate"], None)                 # Jay's merge:<head> stands
        self.assertEqual(self.daemon.pipeline.work(k2)["review"]["head"], "cd" * 20)

    async def test_jays_decision_stops_ccd_from_opening_a_second_gate(self):
        k = self.ready(labels=["ui"])          # ui: the classifier would hold it
        self.ungate(k)
        self.daemon.pipeline.hold_merge(k, HEAD, "first hold")
        self.daemon.pipeline.confirm(k, "merge", "jay")
        self.assertEqual(self.daemon.pipeline.merge_candidates("commandcenter"), [])
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)

    async def test_jay_confirming_a_gate_before_any_hold_also_blocks_the_candidate(self):
        k = self.ready(labels=["ui"])
        self.daemon.pipeline.confirm(k, "merge", "jay") if self.daemon.pipeline.work(k)["gate"] else None
        self.assertIn(f"merge:{HEAD}", self.daemon.pipeline.work(k)["confirmed"])
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])


class Pending(Base):
    async def test_a_pr_pending_too_long_opens_a_gate(self):
        k = self.ready()
        self.gh.pr = view(statusCheckRollup=[{"status": "QUEUED", "conclusion": ""}])
        await self.daemon._auto_merge()
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        self.daemon._am_next.clear()
        self.daemon._am_waiting[k] = (HEAD, time.monotonic() - self.daemon.AUTO_MERGE_WAIT_LIMIT - 5)
        await self.daemon._auto_merge()
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("CI is still running for over 30 minutes", w["gateReason"])
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("pipeline.auto_merge_held", self.kinds(k))

    async def test_a_pr_that_stops_waiting_forgets_the_clock(self):
        k = self.ready()
        self.gh.pr = view(mergeable="UNKNOWN")
        await self.daemon._auto_merge()
        self.assertIn(k, self.daemon._am_waiting)
        self.daemon._am_next.clear()
        self.gh.pr = view()
        await self.daemon._auto_merge()
        self.assertNotIn(k, self.daemon._am_waiting)
        self.assertEqual(len(self.gh.of("merge")), 1)
