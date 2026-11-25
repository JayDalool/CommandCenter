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
from .test_merge_policy import HEAD, REF, f, run, view, green

PLAN = {"summary": "add tests", "requirements": [], "approach": "tests", "affected": [], "risk": "low",
        "tests": ["unit"], "questions": []}
REPO = "JayDalool/CommandCenter"


class FakeGh:
    """The `gh` the daemon would run. Records every argv; answers `pr view` and `pr merge`."""

    def __init__(self, pr=None):
        self.calls = []
        self.api_calls = []   # `gh api` reads (CC-057 merge facts); kept apart so the merge-argument tests stay exact
        self.labels = []
        self.body = ""
        self.mode = "100644"
        self.truncated = False
        self.text = "hello\n"
        self.api_fail = False
        self.linked = []          # `gh pr view --json closingIssuesReferences`
        self.issue_labels = {}    # issue number -> [label names]
        self.history_extra = []   # paths touched by an intermediate commit that the net diff no longer shows
        self.base_ref = None      # the PR's base branch as the pulls API says it (default: what `pr view` says)
        self.base_sha = "ba" * 20
        self.pr = pr if pr is not None else view()
        self.merge = (0, "", "")
        self.delay = 0
        self.on_view = None
        self.merged = False       # what the pulls API says after a successful `gh pr merge`

    def api(self, args):
        """The `gh api` answers merge_facts.fetch reads, derived from the PR the fake serves."""
        import base64
        self.api_calls.append(list(args))
        if self.api_fail:
            return 1, "", "api down"
        path = args[2]
        if "/compare/" in path:      # CC-057 round 3: the one pinned base...head comparison
            status = {"ADDED": "added", "MODIFIED": "modified", "DELETED": "removed", "RENAMED": "renamed"}
            return 0, json.dumps({"status": "ahead", "total_commits": 1, "commits": [{"sha": self.pr.get("headRefOid")}],
                                  "files": [{"filename": x["path"], "status": status.get(x["changeType"], "modified"),
                                             "additions": x["additions"], "deletions": x["deletions"]}
                                            for x in self.pr.get("files") or []]}), ""
        if "/commits/" in path:
            names = [x["path"] for x in self.pr.get("files") or []] + list(self.history_extra)
            return 0, json.dumps({"sha": path.rsplit("/", 1)[1], "files": [{"filename": n} for n in names]}), ""
        if "/pulls/" in path:
            return 0, json.dumps({"base": {"sha": self.base_sha, "ref": self.base_ref or self.pr.get("baseRefName")},
                                  "head": {"sha": self.pr.get("headRefOid")}, "merged": self.merged,
                                  "labels": [{"name": x} for x in self.labels], "body": self.body}), ""
        if "/issues/" in path:
            n = int(path.rsplit("/", 1)[1])
            return 0, json.dumps({"labels": [{"name": x} for x in self.issue_labels.get(n, [])]}), ""
        if "/git/trees/" in path:
            base = ("ba" * 20) in path      # an ADDED file is not in the base tree
            return 0, json.dumps({"truncated": self.truncated,
                                  "tree": [{"path": x["path"], "mode": self.mode} for x in self.pr.get("files") or []
                                           if not (base and x.get("changeType") == "ADDED")]}), ""
        if "/contents/" in path:
            return 0, json.dumps({"type": "file", "encoding": "base64",
                                  "content": base64.b64encode(self.text.encode()).decode()}), ""
        return 1, "", "unexpected gh api call"

    def __call__(self, args):
        if args[:2] == ["gh", "api"]:
            return self.api(args)
        if args[:3] == ["gh", "pr", "view"] and "closingIssuesReferences" in args:
            self.api_calls.append(list(args))
            return 0, json.dumps({"closingIssuesReferences": self.linked}), ""
        self.calls.append(list(args))
        if args[:3] == ["gh", "pr", "view"]:
            if self.delay:
                time.sleep(self.delay)
            if self.on_view:
                self.on_view()
            return 0, json.dumps(self.pr), ""
        if args[:3] == ["gh", "pr", "merge"]:
            self.merged = self.merge[0] == 0
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

    def size(self, key, size="small"):
        """Store a size on the ticket (CC-057: only a ticket sized small, never risky before, may auto-merge)."""
        pl = self.daemon.pipeline
        pl.ts._begin()
        pl._flow_set(pl.ts._id_of(key), time.time(), size=size)
        pl.ts._commit()

    def ready(self, project="commandcenter", number=7, head=HEAD, cache=True, small=True, **fields):
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
        if small:
            self.size(k)
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
                         [("system:auto-merge", HEAD, "green")])
        self.assertIn("CI green", merged[0]["trigger"])
        sec = self.events("merge.auto")
        self.assertEqual([(e["source"], e["ref"]) for e in sec], [("security", k)])

    async def test_green_ci_is_said_as_green(self):
        k = self.ready()
        self.gh.pr = view(statusCheckRollup=green("backend", "web"))
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


class PerProjectSwitch(Base):
    """CC-057: `auto_merge` is a list of project keys, and the pipeline reads list membership, not a bool."""

    async def test_a_ready_pr_of_a_project_outside_the_list_opens_a_merge_gate(self):
        self.daemon = self.make(auto_merge=["mfe"])
        k = self.ready()                  # a Command Center ticket while only mfe is switched on
        w = self.daemon.pipeline.work(k)
        self.assertEqual((w["gate"], self.tickets.get(k)["status"]), ("merge", "READY_TO_MERGE"))
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])

    async def test_a_ready_pr_of_a_listed_project_has_no_gate_and_is_merged(self):
        self.daemon = self.make(auto_merge=["commandcenter", "mfe"])
        k = self.ready()
        self.assertIsNone(self.daemon.pipeline.work(k)["gate"])
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)

    async def test_the_pipeline_still_reads_the_old_boolean(self):
        pl = self.daemon.pipeline
        pl.auto_merge = True
        self.assertEqual(tuple(pl.auto_merge), ("commandcenter",))
        for bad in (False, None, "commandcenter", 3):
            pl.auto_merge = bad
            self.assertEqual(tuple(pl.auto_merge), ())

    async def test_a_malformed_switch_is_ignored_and_says_so(self):
        for bad in ("mfe", {"mfe": True}, ["nope"], ["gauzemate"], 7):
            d = self.make(auto_merge=bad)
            self.assertEqual((d.auto_merge_list, d.auto_merge_on), ([], False), bad)
            self.assertEqual(d._auto_merge_projects(), [], bad)
            before = len(self.events("merge.config"))
            d._log_merge_policy()
            self.assertEqual(len(self.events("merge.config")), before + 1, bad)
        d = self.make(auto_merge=["mfe"])
        before = len(self.events("merge.config"))
        d._log_merge_policy()
        self.assertEqual(len(self.events("merge.config")), before)

    async def test_a_failed_fact_read_holds_the_merge(self):
        k = self.ready()
        self.gh.api_fail = True
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("could not read", w["gateReason"])

    async def test_a_symlink_a_risk_label_or_an_unsized_ticket_holds_the_merge(self):
        for name, setup in (("symlink", lambda gh: setattr(gh, "mode", "120000")),
                            ("label", lambda gh: setattr(gh, "labels", ["risk:elevated"])),
                            ("truncated", lambda gh: setattr(gh, "truncated", True))):
            self.gh = FakeGh()
            setup(self.gh)
            self.daemon = self.make()
            k = self.ready()
            await self.daemon._auto_merge()
            self.assertEqual(self.gh.of("merge"), [], name)
            self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge", name)
        self.gh = FakeGh()
        self.daemon = self.make()
        k = self.ready(small=False)
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("not sized small", self.daemon.pipeline.work(k)["gateReason"])

    async def test_the_facts_are_read_pinned_to_the_reviewed_head(self):
        self.ready()
        await self.daemon._auto_merge()
        refs = [c[2] for c in self.gh.api_calls]
        self.assertIn("repos/JayDalool/CommandCenter/git/trees/" + HEAD + "?recursive=1", refs)
        self.assertIn("repos/JayDalool/CommandCenter/git/trees/" + "ba" * 20 + "?recursive=1", refs)


class RoundTwo(Base):
    """Codex review round 1: sign-off wiring, base race, history, per-project stop file."""

    def prepare(self, **gh):
        for k, v in gh.items():
            setattr(self.gh, k, v)
        self.daemon = self.make(auto_merge=[])           # switch empty: Jay's path is what is under test
        return self.ready()

    def sign(self, key, head=HEAD, result="pass"):
        pr = {"ref": f"{REPO}#7", "head": head}
        self.daemon.pipeline.security_check(key, result, head, "agent:security-engineer", "looked", pr=pr, session="sec-1")

    async def test_a_sensitive_ticket_is_not_offered_to_jay_without_a_sign_off(self):
        k = self.prepare(labels=["migration"])
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")
        await self.daemon._security_probes()
        ready, skipped = self.daemon.merge_batch("commandcenter")
        self.assertEqual((ready, [s_["key"] for s_ in skipped]), ([], [k]))
        self.assertIn("security sign-off", skipped[0]["reason"])
        self.sign(k, result="fail")                                  # a failed check is not a pass
        self.assertEqual(self.daemon.merge_batch("commandcenter")[0], [])
        self.sign(k)
        self.assertEqual([r["key"] for r in self.daemon.merge_batch("commandcenter")[0]], [k])

    async def test_a_sign_off_at_another_head_does_not_count(self):
        k = self.prepare(labels=["migration"])
        await self.daemon._security_probes()
        self.sign(k, head=HEAD)
        self.assertEqual(len(self.daemon.merge_batch("commandcenter")[0]), 1)
        self.daemon.pipeline.review(k, "APPROVE", "cd" * 20, "agent:reviewer", session="review-2",
                                    pr={"ref": f"{REPO}#7", "head": "cd" * 20, "ciGreen": True, "ciNone": True, "draft": False})
        self.daemon._sec.pop(k, None)
        self.daemon.pipeline.confirm  # (the merge gate itself is not what this test is about)
        self.assertIn("security sign-off", self.daemon.security_wait(k) or "")

    async def test_a_ticket_that_needs_no_sign_off_is_offered_as_before(self):
        k = self.prepare()
        await self.daemon._security_probes()
        self.assertEqual([r["key"] for r in self.daemon.merge_batch("commandcenter")[0]], [k])
        self.assertIsNone(self.daemon.security_wait(k))

    async def test_a_ticket_the_probe_has_not_read_yet_waits_and_an_unreadable_pr_is_required(self):
        k = self.prepare()
        self.assertIn("security sign-off", self.daemon.security_wait(k))           # not probed yet: not offered
        self.gh.api_fail = True
        await self.daemon._security_probes()
        self.assertIn("security sign-off", self.daemon.security_wait(k))           # unreadable: required, never "no"

    async def test_the_slack_merge_and_the_merge_ready_press_refuse_without_a_sign_off(self):
        k = self.prepare(labels=["security"])
        await self.daemon._security_probes()
        for via, dev in (("slack", False), (None, True)):
            with self.assertRaises(Exception) as e:
                await self.daemon.act_merge("commandcenter", [{"key": k, "head": HEAD}], developer=dev, via=via)
            self.assertIn("security sign-off", str(getattr(e.exception, "message", e.exception)))
        # Daemon.slack_merge ends in act_merge(via="slack"), the first case above

    async def test_the_merge_question_in_slack_waits_for_the_sign_off(self):
        from ccd import notify

        class Slack:
            pass
        k = self.prepare(labels=["migration"])
        await self.daemon._security_probes()
        n = notify.Notifier(self.daemon, {"notify": {}}, slack=Slack())
        refs = lambda: [x["ref"] for x in n.needs() if x.get("gate") == "merge"]       # noqa: E731
        self.assertEqual(refs(), [])
        self.sign(k)
        self.assertEqual(refs(), [k])

    async def test_auto_merge_refuses_a_sensitive_ticket_until_it_is_signed_and_signs_for_its_head(self):
        self.gh.labels = ["migration"]
        k = self.ready()                                  # auto-merge on for commandcenter
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("security sign-off", self.daemon.pipeline.work(k)["gateReason"])
        self.assertTrue(self.daemon._sec[k][1])

    async def test_a_base_retarget_with_the_same_head_stops_the_merge(self):
        k = self.ready()
        seen = {"n": 0}
        real = self.gh.api

        def retarget(args):
            if "/pulls/" in args[2] and not args[2].endswith("per_page=100"):
                seen["n"] += 1
                if seen["n"] >= 2:                         # the re-read right before the merge
                    self.gh.base_ref = "release"
            return real(args)
        self.gh.api = retarget
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)      # a wait, not a hold: the next pass judges it
        self.assertGreaterEqual(seen["n"], 2)

    async def test_a_base_other_than_the_registered_one_in_the_pinned_read_refuses(self):
        k = self.ready()
        self.gh.base_ref = "release"
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("base branch", self.daemon.pipeline.work(k)["gateReason"])

    async def test_a_denied_path_in_an_intermediate_commit_holds_the_merge(self):
        self.gh.history_extra = ["server/ccd/security.py"]
        k = self.ready()
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("a commit of the PR touched", self.daemon.pipeline.work(k)["gateReason"])

    async def test_a_risk_label_on_an_issue_the_pr_links_holds_the_merge(self):
        self.gh.linked = [{"number": 9, "url": f"https://github.com/{REPO}/issues/9",       # gh 2.98's export shape
                           "repository": {"name": "CommandCenter", "owner": {"login": "JayDalool"}}}]
        self.gh.issue_labels = {9: ["risk:privileged"]}
        k = self.ready()
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("risk label", self.daemon.pipeline.work(k)["gateReason"])

    async def test_a_pending_non_required_check_waits_and_is_not_merged_as_green(self):
        k = self.ready()
        self.gh.pr = view(statusCheckRollup=green("backend", "web") + [run("web-e2e", "", "IN_PROGRESS")])
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        self.assertEqual([e for e in self.kinds(k) if e == "pipeline.auto_merged"], [])

    async def test_a_project_stop_file_stops_only_that_project(self):
        d = self.make(auto_merge=["commandcenter", "gyst"])
        self.daemon = d
        stop = os.path.join(self.tmp, "auto-merge.gyst.stop")
        open(stop, "w").close()
        self.assertFalse(d._auto_merge_stopped("commandcenter"))
        self.assertTrue(d._auto_merge_stopped("gyst"))
        self.assertFalse(d._auto_merge_stopped())         # the global file is its own file
        k = self.ready()
        await d._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)      # commandcenter still merges
        os.remove(stop)
        open(os.path.join(self.tmp, "auto-merge.commandcenter.stop"), "w").close()
        self.gh.calls.clear()
        k2 = self.ready(number=8, head="cd" * 20)
        await d._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])          # now its own stop file stops it
        self.assertEqual(self.daemon.pipeline.work(k2)["gate"], None)

    async def test_the_project_stop_file_is_checked_again_right_before_the_merge(self):
        self.ready()
        name = os.path.join(self.tmp, "auto-merge.commandcenter.stop")
        self.gh.on_view = lambda: open(name, "w").close()
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])

    async def test_an_unreadable_stop_file_counts_as_stopped(self):
        d = self.daemon
        os.mkdir(os.path.join(self.tmp, "locked"), 0o000)
        try:
            d.auto_merge_stop = os.path.join(self.tmp, "locked", "auto-merge.stop")   # stat fails: permission denied
            self.assertTrue(d._auto_merge_stopped())
            self.assertTrue(d._auto_merge_stopped("commandcenter"))
        finally:
            os.chmod(os.path.join(self.tmp, "locked"), 0o700)


class RoundThree(RoundTwo):
    """Codex review round 2: a same-head risk change, stale answers, the pinned comparison, the late guards after the
    last GitHub read, and a retarget after the merge call."""

    def age(self, key, seconds):
        head, required, at = self.daemon._sec[key]
        self.daemon._sec[key] = (head, required, at - seconds)

    def on_pull(self, n, fn):
        """Run `fn` while the n-th `gh api repos/R/pulls/N` read is in flight (1 = facts, 2 = verify, 3 = landed)."""
        seen = {"n": 0}
        real = self.gh.api

        def hook(args):
            if "/pulls/" in args[2]:
                seen["n"] += 1
                if seen["n"] == n:
                    fn()
            return real(args)
        self.gh.api = hook
        return seen

    async def test_a_risk_label_added_at_the_same_head_is_read_fresh_by_the_merge_press_and_slack(self):
        k = self.prepare()
        await self.daemon._security_probes()
        self.assertEqual([r["key"] for r in self.daemon.merge_batch("commandcenter")[0]], [k])   # clean when read
        self.gh.labels = ["risk:privileged"]                     # same head; the cached answer is still fresh
        for via, dev in (("slack", False), (None, True)):
            with self.assertRaises(Exception) as e:
                await self.daemon.act_merge("commandcenter", [{"key": k, "head": HEAD}], developer=dev, via=via)
            self.assertIn("security sign-off", str(getattr(e.exception, "message", e.exception)))
        self.assertIn("security sign-off", self.daemon.security_wait(k))     # the fresh read is remembered
        self.sign(k)
        self.assertEqual([r["key"] for r in self.daemon.merge_batch("commandcenter")[0]], [k])

    async def test_an_issue_linked_later_at_the_same_head_is_read_by_the_next_probe(self):
        k = self.prepare()
        await self.daemon._security_probes()
        self.assertIsNone(self.daemon.security_wait(k))
        self.gh.body = "Refs #9"
        self.gh.issue_labels = {9: ["security"]}
        await self.daemon._security_probes()
        self.assertIsNone(self.daemon.security_wait(k))           # within SEC_REFRESH: not read again yet
        self.age(k, self.daemon.SEC_REFRESH + 1)
        await self.daemon._security_probes()
        self.assertIn("security sign-off", self.daemon.security_wait(k))

    async def test_an_old_not_required_answer_is_not_believed(self):
        k = self.prepare()
        await self.daemon._security_probes()
        self.assertIsNone(self.daemon.security_wait(k))
        self.age(k, self.daemon.SEC_TTL + 1)
        self.assertIn("security sign-off", self.daemon.security_wait(k))
        self.assertEqual(self.daemon.merge_batch("commandcenter")[0], [])

    async def test_a_probe_failure_after_a_clean_result_is_required(self):
        k = self.prepare()
        await self.daemon._security_probes()
        self.assertIsNone(self.daemon.security_wait(k))
        self.gh.api_fail = True
        self.age(k, self.daemon.SEC_REFRESH + 1)
        await self.daemon._security_probes()
        self.assertIn("security sign-off", self.daemon.security_wait(k))
        # and on Jay's press: the fresh read fails, so the ticket is skipped, never offered
        with self.assertRaises(Exception) as e:
            await self.daemon.act_merge("commandcenter", [{"key": k, "head": HEAD}], developer=True)
        self.assertIn("security sign-off", str(getattr(e.exception, "message", e.exception)))

    async def test_a_whole_probe_pass_that_fails_forgets_every_earlier_answer(self):
        k = self.prepare()
        await self.daemon._security_probes()
        self.assertIsNone(self.daemon.security_wait(k))
        self.age(k, self.daemon.SEC_REFRESH + 1)
        with mock.patch.object(self.daemon.pipeline, "review_head", side_effect=RuntimeError("store down")):
            await self.daemon._security_probes_safe()           # what derive runs: it must not raise
        self.assertEqual(self.daemon._sec, {})
        self.assertIn("security sign-off", self.daemon.security_wait(k))

    async def test_an_intermediate_only_sensitive_change_needs_a_sign_off_on_jays_path(self):
        k = self.prepare(history_extra=["server/ccd/security.py"])
        await self.daemon._security_probes()
        ready, skipped = self.daemon.merge_batch("commandcenter")
        self.assertEqual((ready, [s_["key"] for s_ in skipped]), ([], [k]))
        self.assertIn("security sign-off", skipped[0]["reason"])

    async def test_the_files_judged_are_the_pinned_comparisons(self):
        k = self.ready()
        await self.daemon._auto_merge()
        refs = [c[2] for c in self.gh.api_calls]
        self.assertIn(f"repos/{REPO}/compare/{'ba' * 20}...{HEAD}?per_page=100", refs)
        self.assertFalse([r for r in refs if "/pulls/7/commits" in r])
        self.assertEqual(len(self.gh.of("merge")), 1)
        self.assertIn("pipeline.auto_merged", self.kinds(k))

    async def test_a_comparison_that_differs_from_the_pr_view_is_what_counts(self):
        k = self.ready()
        real = self.gh.api

        def compare_with_a_denied_file(args):
            if "/compare/" in args[2]:
                return 0, json.dumps({"status": "ahead", "total_commits": 1, "commits": [{"sha": HEAD}],
                                      "files": [{"filename": "server/ccd/security.py", "status": "modified",
                                                 "additions": 1, "deletions": 0}]}), ""
            return real(args)
        self.gh.api = compare_with_a_denied_file
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("server/ccd/security.py", self.daemon.pipeline.work(k)["gateReason"])

    async def test_a_stop_file_that_appears_during_the_last_github_read_stops_the_merge(self):
        for name in ("auto-merge.stop", "auto-merge.commandcenter.stop"):
            self.gh = FakeGh()
            self.daemon = self.make()
            self.ready()
            path = os.path.join(self.tmp, name)
            seen = self.on_pull(2, lambda: open(path, "w").close())
            await self.daemon._auto_merge()
            self.assertEqual(seen["n"], 2, name)                  # the verify read ran, and the file came during it
            self.assertEqual(self.gh.of("merge"), [], name)
            os.remove(path)

    async def test_a_needs_jay_flag_set_during_the_last_github_read_holds_the_merge(self):
        k = self.ready()
        seen = self.on_pull(2, lambda: self.tickets.update(k, {"needs_jay": True}, "jay"))
        await self.daemon._auto_merge()
        self.assertEqual(seen["n"], 2)
        self.assertEqual(self.gh.of("merge"), [])
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("needs Jay", w["gateReason"])

    async def test_a_sign_off_withdrawn_during_the_last_github_read_holds_the_merge(self):
        self.gh.labels = ["migration"]
        k = self.ready()
        self.sign(k)
        seen = self.on_pull(2, lambda: self.sign(k, result="fail"))
        await self.daemon._auto_merge()
        self.assertEqual(seen["n"], 2)
        self.assertEqual(self.gh.of("merge"), [])
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("security sign-off", w["gateReason"])

    async def test_a_signed_sensitive_change_still_merges_when_nothing_changes(self):
        self.gh.labels = ["migration"]
        k = self.ready()
        self.sign(k)
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        self.assertEqual(self.events("merge.base_mismatch"), [])

    async def test_a_retarget_after_the_merge_call_is_raised_to_jay(self):
        k = self.ready()
        real = self.gh.__call__

        def retarget_on_merge(args):
            out = real(args)
            if args[:3] == ["gh", "pr", "merge"]:
                self.gh.base_ref = "release"                     # GitHub has no base precondition for the write
            return out
        self.daemon.gh_cli = retarget_on_merge
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        ev = self.events("merge.base_mismatch")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["severity"], "action")
        self.assertIn("release", ev[0]["text"])
        self.assertIn(k, ev[0]["text"])


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
        self.assertEqual(DEFAULTS["auto_merge"], [])

    async def test_the_stop_file(self):
        k = self.ready()
        open(self.daemon.auto_merge_stop, "w").close()
        await self.assertQuiet(k)
        os.remove(self.daemon.auto_merge_stop)
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)

    async def test_a_ui_label_added_while_gh_view_runs_holds_the_merge(self):
        k = self.ready()
        self.gh.on_view = lambda: self.tickets.update(k, {"labels": ["ui"]}, "jay")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        w = self.daemon.pipeline.work(k)
        self.assertEqual((w["gate"], self.tickets.get(k)["status"]), ("merge", "READY_TO_MERGE"))
        self.assertIn("ui label", w["gateReason"])
        self.assertIn("pipeline.auto_merge_held", self.kinds(k))

    async def test_a_needs_jay_flag_set_after_the_size_was_classified_holds_the_merge(self):
        k = self.ready()
        real = self.daemon.pipeline.merge_size_facts

        def late(key):
            out = real(key)                                   # the size is classified small ...
            self.tickets.update(key, {"needs_jay": True}, "jay")      # ... and only then the flag arrives
            return out
        self.daemon.pipeline.merge_size_facts = late
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        w = self.daemon.pipeline.work(k)
        self.assertEqual(w["gate"], "merge")
        self.assertIn("needs Jay", w["gateReason"])
        self.assertNotIn("sized small", w["gateReason"])

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

    async def test_a_project_not_in_the_config_list_is_not_a_candidate_even_if_low_risk(self):
        # CC-057: gyst, mfe and samvision are low-risk with allow lists, but only the listed project is looked at.
        self.assertEqual(self.daemon._auto_merge_projects(), ["commandcenter"])
        self.assertEqual(self.make(auto_merge=["commandcenter", "gyst"])._auto_merge_projects(), ["commandcenter", "gyst"])

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
        self.gh.pr = view(statusCheckRollup=[run("backend"), run("web", "", "IN_PROGRESS")])
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
                         ({}, view(statusCheckRollup=[run("backend", "FAILURE"), run("web")])),
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
        self.assertEqual(config.DEFAULTS["auto_merge"], [])
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
        self.gh.pr = view(statusCheckRollup=[run("backend"), run("web", "", "QUEUED")])
        await self.daemon._auto_merge()
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        self.daemon._am_next.clear()
        self.daemon._am_waiting[k] = (self.daemon._review_stamp(self.daemon.pipeline.work(k)),
                                      time.monotonic() - self.daemon.AUTO_MERGE_WAIT_LIMIT - 5)
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

    async def test_the_clock_resets_when_the_ticket_goes_back_to_review_and_returns_with_the_same_head(self):
        k = self.ready()
        d = self.daemon
        self.gh.pr = view(mergeable="UNKNOWN")
        await d._auto_merge()
        old = d._am_waiting[k]
        d._am_waiting[k] = (old[0], old[1] - d.AUTO_MERGE_WAIT_LIMIT + 60)   # nearly at the limit
        self.tickets.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="back to review")
        d._am_next.clear()
        await d._auto_merge()                                              # not a candidate: the entry is dropped
        self.assertNotIn(k, d._am_waiting)
        self.tickets.update(k, {"status": "READY_TO_MERGE"}, "system:automation", trigger="ready again")
        d._am_next.clear()
        await d._auto_merge()
        self.assertGreater(d._am_waiting[k][1], old[1])                    # a fresh clock, not the old one
        self.assertEqual(d.pipeline.work(k)["gate"], None)
        self.assertEqual(self.gh.of("merge"), [])

    async def test_a_new_review_at_the_same_head_restarts_the_clock(self):
        k = self.ready()
        d = self.daemon
        self.gh.pr = view(mergeable="UNKNOWN")
        await d._auto_merge()
        first = d._am_waiting[k]
        d._am_waiting[k] = (first[0], first[1] - d.AUTO_MERGE_WAIT_LIMIT - 5)
        stamp = d._review_stamp(d.pipeline.work(k))
        d.pipeline.db.execute("UPDATE ticket_work SET roles=? WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)",
                              (json.dumps({"reviewer": {"model": None, "session": "review-2", "at": "2099-01-01T00:00:00Z"}}), k))
        self.assertNotEqual(stamp, d._review_stamp(d.pipeline.work(k)))
        d._am_next.clear()
        await d._auto_merge()
        self.assertEqual(d.pipeline.work(k)["gate"], None)                 # the old clock would have opened a gate
