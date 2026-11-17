"""Team lead permissions (ccd/lead_authority.py, Jay 2026-11-17): the levels, what each hands to the lead, the API,
and the hand-over of what was already waiting for Jay."""
import json
import os
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path

from ccd import lead_authority as la
from ccd import merge_policy as mp
from ccd import registry
from ccd.validation import replay

from .test_api import JSON, ApiBase
from .test_auto_merge import PLAN, Base
from .test_merge_policy import HEAD, f, ticket, view, work

ROOT = Path(__file__).resolve().parents[2]


def store():
    return la.LeadAuthority(os.path.join(tempfile.mkdtemp(prefix="lead-"), "lead-authority.json"))


class Levels(unittest.TestCase):
    def test_defaults_come_from_the_registry(self):
        a = store()
        self.assertEqual(a.level("commandcenter"), "low_risk")
        for k in ("gyst", "samvision", "mfe", "gauzemate"):
            self.assertEqual(a.level(k), "none", k)
        self.assertTrue(a.public("gyst")["default"])

    def test_each_level_includes_the_ones_before_it(self):
        want = {"none": set(), "low_risk": {"merge_low_risk"}, "merge": {"merge_low_risk", "merge"},
                "merge_deploy": {"merge_low_risk", "merge", "deploy"},
                "all": {"merge_low_risk", "merge", "deploy", "plan", "ui", "release"}}
        for level, grants in want.items():
            self.assertEqual({k for k in la.NEEDS if la.grants(level, k)}, grants, level)
        self.assertFalse(la.grants(None, "merge_low_risk"))
        self.assertFalse(la.grants("bogus", "merge_low_risk"))

    def test_set_survives_a_restart_and_the_file_is_private(self):
        a = store()
        a.set("gyst", "all")
        self.assertEqual(stat.S_IMODE(os.stat(a.path).st_mode), 0o600)
        b = la.LeadAuthority(a.path)
        self.assertEqual(b.level("gyst"), "all")
        b.set("gyst", "merge")
        self.assertEqual(la.LeadAuthority(a.path).level("gyst"), "merge")
        for bad in (("gyst", "everything"), ("../x", "all")):
            with self.assertRaises(la.AuthorityError):
                b.set(*bad)

    def test_a_broken_file_reads_as_the_registry_defaults(self):
        a = store()
        Path(a.path).write_text("{not json")
        self.assertEqual(la.LeadAuthority(a.path).level("gyst"), "none")

    def test_what_stays_with_jay(self):
        """Jay's rules (2026-11-17): major features, money, legal and the five kinds of personal-data change stay
        his at every level; security waits for the specialist, then it is the lead's; the rest is the lead's."""
        a = store()
        a.set("gyst", "all")
        base = {"project": "gyst", "type": "FEATURE", "flags": [], "labels": []}
        self.assertTrue(a.may("gyst", "deploy", base))
        for t in ({"flags": ["needs_jay"]}, {"flags": ["needs:legal"]}, {"type": "LEGAL"}, {"labels": ["product-decision"]},
                  {"labels": ["ambiguous"]}, {"labels": ["feature:major"]}, {"labels": ["spend"]}, {"labels": ["legal"]},
                  {"labels": ["data-access"]}, {"labels": ["data-collect"]}, {"labels": ["data-sharing"]},
                  {"labels": ["data-storage"]}, {"labels": ["data-deletion"]}, {"labels": ["destructive"]}):
            self.assertFalse(a.may("gyst", "deploy", dict(base, **t)), t)
            self.assertFalse(a.may("gyst", "deploy", dict(base, **t), confirmed=[la.SECURITY_REVIEWED]), t)
        self.assertFalse(a.may("gyst", "plan", base, confirmed=["owner:accept"]))
        for t in ({"type": "SECURITY"}, {"labels": ["security"]}, {"labels": ["auth"]}, {"labels": ["privacy"]}):
            self.assertEqual(la.jay_reasons(dict(base, **t)), [la.SECURITY_WAIT], t)
            self.assertFalse(a.may("gyst", "deploy", dict(base, **t)), t)
            self.assertTrue(a.may("gyst", "deploy", dict(base, **t), confirmed=[la.SECURITY_REVIEWED]), t)
        # Money in the app's own code, data retention, additive migrations: the lead's.
        for t in ({"labels": ["migration"]}, {"labels": ["financial"]}, {"labels": ["retention"]}):
            self.assertTrue(a.may("gyst", "deploy", dict(base, **t)), t)
        a.set("gyst", "merge")
        self.assertFalse(a.may("gyst", "deploy", base))
        self.assertTrue(a.may("gyst", "merge", base))


class LeadClassifier(unittest.TestCase):
    APP = [f("src/app/page.tsx"), f("lib/money.ts", "DELETED"), f("package.json")]

    def decide(self, files=None, t=None, w=None, level="merge", project="gyst", confirmed=()):
        ref = f"{registry.github_of(project)}#7"
        return mp.classify(project, t or ticket(project=project),
                           w or work(review={"verdict": "APPROVE", "head": HEAD, "pr": ref, "cycles": 0},
                                     confirmed=list(confirmed)),
                           view(files or self.APP), ref, [ref], "lead", {"level": level})

    def test_any_reviewed_change_outside_the_rails_merges(self):
        d = self.decide()
        self.assertTrue(d.ok, d.reasons)

    def test_the_rails_never_merge_on_a_lead_permission(self):
        for path in (".github/workflows/ci.yml", ".claude/settings.json", "app/.claude/x.json", "CLAUDE.md", "sub/AGENTS.md",
                     ".mcp.json", ".codex/config.toml"):
            d = self.decide(self.APP + [f(path)])
            self.assertFalse(d.ok, path)
            self.assertTrue(any("protected path" in r for r in d.reasons), (path, d.reasons))
        for path in ("server/ccd/api.py", "policy/projects/gyst.toml", "web/app/src/App.tsx", "scripts/x.sh"):
            self.assertFalse(self.decide([f(path)], project="commandcenter").ok, path)
        self.assertTrue(self.decide([f("server/ccd/api.py")]).ok)        # another project's own folder of that name

    def test_jays_questions_stay_his_and_security_waits_for_its_review(self):
        for t in ({"flags": ["needs_jay"]}, {"labels": ["product-decision"]}, {"type": "LEGAL"},
                  {"labels": ["data-sharing"]}, {"labels": ["spend"]}):
            self.assertFalse(self.decide(t=ticket(project="gyst", **t), confirmed=[la.SECURITY_REVIEWED]).ok, t)
        sec = ticket(project="gyst", labels=["security"])
        d = self.decide(t=sec)
        self.assertFalse(d.ok)
        self.assertTrue(any("security specialist" in r for r in d.reasons), d.reasons)
        self.assertTrue(self.decide(t=sec, confirmed=[la.SECURITY_REVIEWED]).ok)

    def test_ui_work_is_the_leads_only_at_all(self):
        ui = ticket(project="gyst", labels=["ui"])
        self.assertFalse(self.decide(t=ui, level="merge_deploy").ok)
        self.assertTrue(self.decide(t=ui, level="all").ok)

    def test_a_level_without_merge_refuses(self):
        for level in ("none", "low_risk", None):
            self.assertFalse(self.decide(level=level).ok, level)

    def test_too_many_files_to_trust(self):
        d = self.decide([f(f"src/{i}.ts") for i in range(100)])
        self.assertFalse(d.ok)

    def test_project_rails_match_the_profile(self):
        prof = tomllib.loads((ROOT / "policy/projects/commandcenter.toml").read_text())
        paths = prof["target"]["self_protection"]["require_jay_for_paths"]
        non_rail = [p for p in paths if not any(r.match(p.replace("**", "x")) for r in mp._RAILS)]
        self.assertEqual(sorted(mp.PROJECT_RAILS["commandcenter"]), sorted(non_rail))


class LeadBase(Base):
    def make(self, **over):
        d = super().make(**over)
        d.authority = store()
        d.pipeline.authority = d.authority
        return d

    def deploy_ready(self, project="gyst", **fields):
        t, _ = self.tickets.create(project, "Ship it", **fields)
        k = t["key"]
        self.tickets.update(k, {"status": "VERIFYING"}, "system:automation", trigger="merged")
        return k


class LeadPipeline(LeadBase):
    """A project's level in the pipeline and ccd's merge: no Jay gate where the lead may take it."""

    async def test_none_keeps_every_merge_with_jay(self):
        k = self.ready(project="gyst")
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])

    async def test_merge_all_merges_an_app_pr_without_a_gate(self):
        self.daemon.authority.set("gyst", "merge")
        self.gh.pr = view([f("src/app/page.tsx"), f("lib/x.ts")])
        k = self.ready(project="gyst")
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], None)
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        merged = [e for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.auto_merged"]
        self.assertEqual(merged[0]["data"]["authority"], "merge")

    async def test_merge_all_holds_a_rail_for_jay(self):
        self.daemon.authority.set("gyst", "merge")
        self.gh.pr = view([f("src/app/page.tsx"), f(".github/workflows/ci.yml")])
        k = self.ready(project="gyst")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")
        self.assertIn("protected path", self.daemon.pipeline.work(k)["gateReason"])

    async def test_the_config_kill_switch_still_wins(self):
        self.daemon = self.make(auto_merge=False)
        self.daemon.authority.set("gyst", "merge")
        k = self.ready(project="gyst")
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])

    async def test_merge_and_deploy_approves_a_live_deploy_on_the_spot(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "merge_deploy")
        k = self.deploy_ready()
        _t, _c, events = pl.deploy_request(k, "live", "the new page", "smoke test", "agent:verifier")
        w = pl.work(k)
        self.assertIsNone(w["gate"])
        self.assertEqual(w["deploy"]["approvedBy"], "lead:merge_deploy")
        self.assertNotIn("pipeline.gate_opened", [e[0] for e in events])
        self.assertIn("pipeline.gate_lead_approved", [e[0] for e in events])
        pl.deployed(k, "live", "pass", "health check green", "agent:verifier")
        self.assertEqual(pl.work(k)["deploy"]["result"], "pass")

    async def test_merge_only_and_jays_deploys_still_wait_for_jay(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "merge")
        k = self.deploy_ready()
        pl.deploy_request(k, "live", "the new page", "smoke test", "agent:verifier")
        self.assertEqual(pl.work(k)["gate"], "deploy")
        self.daemon.authority.set("gyst", "all")
        k2 = self.deploy_ready(labels=["data-deletion"])
        pl.deploy_request(k2, "live", "drop old rows", "drill", "agent:verifier")
        self.assertEqual(pl.work(k2)["gate"], "deploy")
        self.assertNotIn("security specialist", pl.work(k2)["gateReason"] or "")
        k3 = self.deploy_ready(labels=["migration"])       # an additive migration is the lead's (Jay 2026-11-17)
        pl.deploy_request(k3, "live", "a new column", "drill", "agent:verifier")
        self.assertIsNone(pl.work(k3)["gate"])

    async def test_all_lets_the_lead_approve_a_risky_plan(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "all")
        t, _ = self.tickets.create("gyst", "Rework the data layer", labels=["architecture"])
        pl.plan(t["key"], PLAN, "agent:planner")
        w = pl.work(t["key"])
        self.assertEqual((w["gate"], w["planState"]), (None, "accepted"))
        self.assertIn("pipeline.gate_lead_approved", self.kinds(t["key"]))
        self.assertNotIn("pipeline.gate_opened", self.kinds(t["key"]))
        t2, _ = self.tickets.create("gyst", "Rotate keys", labels=["security"])
        pl.plan(t2["key"], PLAN, "agent:planner")
        self.assertEqual(pl.work(t2["key"])["gate"], "plan")        # until the security specialist's review

    async def test_raising_the_level_hands_over_what_was_waiting(self):
        pl = self.daemon.pipeline
        k = self.ready(project="gyst")
        d = self.deploy_ready()
        pl.deploy_request(d, "live", "the new page", "smoke test", "agent:verifier")
        sec = self.deploy_ready(labels=["security"])
        pl.deploy_request(sec, "live", "auth change", "smoke test", "agent:verifier")
        self.assertEqual([pl.work(x)["gate"] for x in (k, d, sec)], ["merge", "deploy", "deploy"])
        self.daemon.authority_set("gyst", {"level": "merge_deploy"}, "jay", developer=True)
        self.assertEqual([pl.work(x)["gate"] for x in (k, d, sec)], [None, None, "deploy"])
        self.assertIn("pipeline.gate_handed", self.kinds(k))
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        self.assertEqual([e["data"]["to"] for e in self.events("lead.authority")], ["merge_deploy"])

    async def test_a_held_merge_is_not_handed_over(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "merge")
        self.gh.pr = view([f(".github/workflows/ci.yml")])
        k = self.ready(project="gyst")
        await self.daemon._auto_merge()
        self.assertEqual(pl.work(k)["gate"], "merge")
        self.daemon.authority_set("gyst", {"level": "all"}, "jay", developer=True)
        self.assertEqual(pl.work(k)["gate"], "merge")

    async def test_who_may_set_it(self):
        from ccd.daemon import ActionError
        for actor, dev in (("jay", False), ("agent:coordinator", True)):
            with self.assertRaises(ActionError) as e:
                self.daemon.authority_set("gyst", {"level": "all"}, actor, developer=dev)
            self.assertEqual(e.exception.status, 403)
        for project, body, status in (("gyst", {"level": "low_risk"}, 400), ("gyst", {"level": "most"}, 400),
                                      ("nope", {"level": "all"}, 404)):
            with self.assertRaises(ActionError) as e:
                self.daemon.authority_set(project, body, "jay", developer=True)
            self.assertEqual(e.exception.status, status, (project, body))
        self.assertEqual(self.daemon.authority.level("gyst"), "none")


class LeadReplay(unittest.TestCase):
    def test_merges_and_deploys_under_a_lead_permission_are_authorised(self):
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, key TEXT)")
        db.execute("CREATE TABLE ticket_events(id INTEGER PRIMARY KEY, ticket_id INT, at REAL, actor TEXT, kind TEXT, "
                   "data TEXT)")
        db.execute("INSERT INTO tickets VALUES (1, 'GYST-001')")
        rows = [(1, 1, "system:auto-merge", "pipeline.auto_merged", {"head": HEAD, "authority": "merge"}),
                (2, 1, "system:auto-merge", "pipeline.auto_merged", {"head": HEAD}),
                (3, 1, "agent:verifier", "pipeline.deploy_approved", {"authority": "merge_deploy"}),
                (4, 1, "agent:verifier", "pipeline.deployed", {"env": "live"}),
                (5, 1, "agent:verifier", "pipeline.deploy_approved", {"authority": "merge"}),
                (6, 1, "agent:verifier", "pipeline.deployed", {"env": "live"})]
        for i, tid, actor, kind, data in rows:
            db.execute("INSERT INTO ticket_events VALUES (?,?,?,?,?,?)", (i, tid, i, actor, kind, json.dumps(data)))
        out = replay.actions(db, 0)
        self.assertEqual(out["checked"], 4)
        self.assertEqual(sorted(u["event"] for u in out["unauthorized"]), [2, 6])


class LeadAuthorityApi(ApiBase):
    DEV = "d" * 43

    def equip(self, daemon):
        from ccd import security
        daemon.dev_gate = security.DeveloperGate(self.DEV)
        daemon.authority = store()
        if daemon.pipeline is not None:
            daemon.pipeline.authority = daemon.authority

    def dev(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON)
        return dict(JSON, **{"x-ccd-developer": r.json()["session"]})

    def put(self, project, body, headers=None):
        return self.client.put(f"/api/lead-authority/projects/{project}", content=json.dumps(body), headers=headers or JSON)

    def test_read_and_set_over_http(self):
        st = self.get("/api/lead-authority").json()
        self.assertEqual([lv["key"] for lv in st["levels"]], list(la.LEVELS))
        self.assertIn("mergeSwitch", st)
        self.assertEqual(self.put("gyst", {"level": "all"}).status_code, 403)
        dev = self.dev()
        r = self.put("gyst", {"level": "all"}, dev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["projects"]["gyst"]["level"], "all")
        self.assertTrue(r.json()["projects"]["gyst"]["permissions"]["deploy"])
        self.assertEqual(self.put("gauzemate", {"level": "merge"}, dev).status_code, 409)
        self.assertEqual(st["alwaysJay"], sorted(la.ALWAYS_JAY_LABELS))
        self.assertEqual(st["security"], sorted(la.SECURITY_LABELS))
        self.assertNotIn("keepSensitive", r.json()["projects"]["gyst"])


class ReviewFixes(LeadBase):
    """The independent review of PR #132: renames, Slack wording, release approvals, the stop file, client repos."""

    def test_a_rename_never_merges_on_a_lead_permission(self):
        for change in ("RENAMED", "COPIED", None):
            d = mp.classify("gyst", ticket(project="gyst"), work(review={"verdict": "APPROVE", "head": HEAD,
                                                                          "pr": "JayDalool/gyst-lifeops#7", "cycles": 0}),
                            view([f("old/ci.yml", change)]), "JayDalool/gyst-lifeops#7", ["JayDalool/gyst-lifeops#7"],
                            "lead", {"level": "all"})
            self.assertFalse(d.ok, change)
        self.assertEqual(mp.lead_file_reasons("gyst", [f("src/gone.ts", "DELETED")]), [])
        self.assertTrue(mp.lead_file_reasons("gyst", [f(".github/workflows/ci.yml", "DELETED")]))

    async def test_a_lead_approved_deploy_never_says_it_waits_for_jay(self):
        self.daemon.authority.set("gyst", "merge_deploy")
        k = self.deploy_ready()
        _t, _c, events = self.daemon.pipeline.deploy_request(k, "live", "page", "smoke", "agent:verifier")
        req = [e for e in events if e[0] == "pipeline.deploy_requested"][0]
        self.assertNotIn("Jay", req[1])
        self.assertEqual(req[2]["authority"], "merge_deploy")

    async def test_a_risky_release_approval_needs_all(self):
        pl = self.daemon.pipeline
        k = self.deploy_ready()
        t = self.tickets.get(k)
        w = pl.work(k)
        self.assertEqual(pl._lead_need(t, dict(w, deploy=None), "deploy"), "release")
        self.assertEqual(pl._lead_need(t, dict(w, deploy={"requestedAt": 1}), "deploy"), "deploy")
        self.assertFalse(la.grants("merge_deploy", "release"))
        self.assertTrue(la.grants("all", "release"))

    async def test_the_stop_file_sends_ready_prs_to_jay(self):
        self.daemon.authority.set("gyst", "merge")
        open(self.daemon.auto_merge_stop, "w").close()
        k = self.ready(project="gyst")
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")

    async def test_a_client_repository_is_none_whatever_is_stored(self):
        a = self.daemon.authority
        a.levels["gauzemate"] = {"level": "all", "at": 0, "by": "jay"}
        self.assertEqual(a.level("gauzemate"), "none")
        self.assertNotIn("gauzemate", self.daemon._auto_merge_projects())


class SecurityReview(LeadBase):
    """The security specialist (Jay 2026-11-17): a security ticket waits for its review, not for Jay; then the lead
    decides at its level, and Jay is shown the conclusion."""
    NOTE = "Checked auth, sessions, secrets, deps and hosting. Fix: rotate the token and pin the version."

    def plan_security(self, labels=("security",)):
        t, _ = self.tickets.create("gyst", "Rotate keys", labels=list(labels))
        self.daemon.pipeline.plan(t["key"], PLAN, "agent:planner")
        return t["key"]

    async def test_only_the_security_specialist_records_one_and_says_what_it_found(self):
        from ccd.tasks import TaskError
        pl = self.daemon.pipeline
        k = self.plan_security()
        for actor in ("agent:coordinator", "agent:reviewer", "jay"):
            with self.assertRaises(TaskError) as e:
                pl.security_review(k, self.NOTE, actor, session="sec-1")
            self.assertEqual(e.exception.status, 403, actor)
        for note, session in (("", "sec-1"), ("   ", "sec-1"), (self.NOTE, None)):
            with self.assertRaises(TaskError) as e:
                pl.security_review(k, note, "agent:security-reviewer", session=session)
            self.assertEqual(e.exception.status, 400)

    async def test_at_all_the_plan_waits_for_the_review_and_not_for_jay(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "all")
        k = self.plan_security()
        w = pl.work(k)
        self.assertEqual(w["gate"], "plan")
        self.assertIn("security specialist", w["gateReason"])
        opened = [e for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.gate_opened"]
        self.assertEqual(opened[-1]["data"]["authority"], "all")        # announced as info: not Jay's to answer
        _t, _c, events = pl.security_review(k, self.NOTE, "agent:security-reviewer", session="sec-1")
        w = pl.work(k)
        self.assertEqual((w["gate"], w["planState"]), (None, "accepted"))
        self.assertIn(la.SECURITY_REVIEWED, w["confirmed"])
        self.assertEqual([e[0] for e in events][:2], ["pipeline.security_reviewed", "pipeline.gate_lead_approved"])
        self.assertEqual(w["roles"]["security-reviewer"]["session"], "sec-1")
        notes = pl.work(k)["evidence"]
        self.assertTrue(any(n["ref"] == "security review" and n["note"] == self.NOTE for n in notes), notes)

    async def test_jays_labels_still_wait_for_jay_after_the_review(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "all")
        k = self.plan_security(("security", "data-sharing"))
        self.assertNotIn("security specialist", pl.work(k)["gateReason"] or "")
        opened = [e for e in self.tickets.get(k)["timeline"] if e["kind"] == "pipeline.gate_opened"]
        self.assertNotIn("authority", opened[-1]["data"])
        pl.security_review(k, self.NOTE, "agent:security-reviewer", session="sec-1")
        self.assertEqual(pl.work(k)["gate"], "plan")

    async def test_below_all_the_plan_is_still_jays(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "merge_deploy")
        k = self.plan_security()
        self.assertNotIn("security specialist", pl.work(k)["gateReason"] or "")
        pl.security_review(k, self.NOTE, "agent:security-reviewer", session="sec-1")
        self.assertEqual(pl.work(k)["gate"], "plan")

    async def test_a_merge_held_for_the_review_merges_once_it_is_in(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "merge")
        self.gh.pr = view([f("src/app/page.tsx")])
        k = self.ready(project="gyst", labels=["security"])
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertIn("security specialist", pl.work(k)["gateReason"])
        self.daemon.task_work_op(k, "security-review", {"conclusion": self.NOTE, "session": "sec-1"},
                                 actor="agent:security-reviewer")
        self.assertIsNone(pl.work(k)["gate"])
        self.assertIn("pipeline.auto_merge_reopened", self.kinds(k))
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        said = [e for e in self.store.since(0) if (e.get("data") or {}).get("kind") == "pipeline.security_reviewed"]
        self.assertEqual([e["severity"] for e in said], ["action"])         # Jay is shown the conclusion

    async def test_a_hold_for_another_reason_stays(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "merge")
        self.gh.pr = view([f(".github/workflows/ci.yml")])
        k = self.ready(project="gyst")
        await self.daemon._auto_merge()
        pl.security_review(k, self.NOTE, "agent:security-reviewer", session="sec-1")
        self.assertEqual(pl.work(k)["gate"], "merge")
        self.assertNotIn("pipeline.auto_merge_reopened", self.kinds(k))

    async def test_a_replan_needs_a_new_review(self):
        pl = self.daemon.pipeline
        self.daemon.authority.set("gyst", "all")
        k = self.plan_security()
        pl.security_review(k, self.NOTE, "agent:security-reviewer", session="sec-1")
        pl.replan(k, "the threat model changed", "agent:coordinator")
        self.assertNotIn(la.SECURITY_REVIEWED, pl.work(k)["confirmed"])

    def test_the_seat_is_known_to_the_cli_and_slack(self):
        from ccd import notify, pipeline, pipeline_cli
        self.assertIn("security-reviewer", pipeline_cli.ROLES)
        self.assertEqual(pipeline_cli.DEFAULT_ROLE["security-review"], "security-reviewer")
        self.assertIn("security-reviewer", pipeline.ROLE_NAMES)
        self.assertIn("agent:security-reviewer", notify.SEATS)
        self.assertIn("pipeline.security_reviewed", notify.TEAM_KINDS)
