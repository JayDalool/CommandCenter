"""CC-082: approval tiers for GYST and Command Center. The technical reviewer records Tier 1 or 2 at plan review;
Tier 2 opens only Jay's plan gate; no tier ever lowers a size, closes a gate or removes a review stage; every other
project behaves as before."""
import json
import unittest

from ccd import flow, pipeline, pipeline_cli, registry
from ccd.pipeline import Pipeline, tier2_hit
from ccd.tasks import TaskError, TaskStore

from .test_flow import PLAN, WT

PROJECTS = [{"key": "samvision", "name": "SamVision", "prefix": "SV"}, {"key": "gyst", "name": "GYST", "prefix": "GYST"},
            {"key": "commandcenter", "name": "Command Center", "prefix": "CC"},
            {"key": "mfe", "name": "MyFamilyExpenses", "prefix": "MFE"}]
CC_SMALL_FIXES = ["server/ccd/pipeline.py", "web/app/src/x.tsx", "scripts/y.sh", "server/tests/test_x.py"]
RAILS = ["server/ccd/autonomy.py", "server/ccd/broker.py", "server/ccd/security.py", "server/ccd/profiles.py",
         "server/ccd/merge_policy.py", "policy/projects/x.toml", ".claude/settings.json", ".github/workflows/ci.yml",
         "AGENTS.md", "CLAUDE.md"]


class Base(unittest.TestCase):
    def setUp(self):
        self.ts = TaskStore(":memory:", PROJECTS)
        self.pl = Pipeline(self.ts)

    def planned(self, project="commandcenter", affected=None, size="standard", **fields):
        k = self.ts.create(project, "Tier test", description="A change to look at", **fields)[0]["key"]
        self.pl.intake(k, size, ["It works", "It is tested"], "agent:coordinator", priority="MEDIUM")
        self.pl.role(k, "planner", "agent:planner", session="inv-1")
        plan = dict(PLAN, affected=CC_SMALL_FIXES if affected is None else affected)
        self.pl.plan(k, plan, "agent:planner", session="inv-1")
        return k

    def review(self, k, tier=None, reason=None, note="ok", **kw):
        return self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", note, session="tr-1", tier=tier,
                                   tier_reason=reason, **kw)

    def status(self, k):
        return self.ts.get(k)["status"]

    def refused(self, status, fn, *a, **kw):
        with self.assertRaises(TaskError) as e:
            fn(*a, **kw)
        self.assertEqual(e.exception.status, status, e.exception.message)
        return e.exception.message


class TierOne(Base):
    def test_a_fix_outside_the_rails_goes_straight_to_build_on_command_center(self):       # c8
        k = self.planned()
        self.review(k, 1, "a bug fix in one module")
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["gate"]), ("READY_TO_IMPLEMENT", None))
        self.assertEqual((w["planReview"]["tier"], w["planReview"]["tierReason"]), (1, "a bug fix in one module"))
        kinds = [r[0] for r in self.pl.db.execute("SELECT kind FROM ticket_events")]
        self.assertNotIn("pipeline.gate_opened", kinds)

    def test_the_same_on_gyst(self):                                                       # c8
        k = self.planned("gyst", ["internal/x.go", "web/src/Card.tsx"])
        self.review(k, 1, "polish")
        self.assertEqual((self.status(k), self.pl.work(k)["gate"]), ("READY_TO_IMPLEMENT", None))

    def test_tier_one_needs_a_reason(self):                                                # c4
        k = self.planned()
        self.assertIn("reason", self.refused(400, self.review, k, 1))
        self.assertEqual(self.status(k), "RESEARCHING")

    def test_a_tier_one_does_not_close_a_risky_or_labelled_gate(self):                     # c9
        k = self.planned(size="risky")
        self.review(k, 1, "a small fix")
        self.assertEqual((self.pl.work(k)["gate"], self.status(k)), ("plan", "RESEARCHING"))
        k = self.planned(labels=["security"])
        self.review(k, 1, "a small fix")
        self.assertEqual(self.pl.work(k)["gate"], "plan")

    def test_a_tier_never_changes_the_size(self):                                          # c11
        k = self.planned()
        self.review(k, 1, "small")
        self.assertEqual(self.pl.work(k)["size"], "standard")
        k = self.planned()
        self.review(k, 2, "a new screen")
        self.assertEqual(self.pl.work(k)["size"], "standard")
        self.assertEqual(self.status(k), "RESEARCHING")


class TierTwo(Base):
    def test_every_rail_path_refuses_tier_one(self):                                       # c9
        for path in RAILS:
            k = self.planned(affected=["server/ccd/pipeline.py", path])
            msg = self.refused(409, self.review, k, 1, "just a fix")
            self.assertIn(path, msg)
            self.assertEqual((self.status(k), self.pl.work(k)["planReview"]), ("RESEARCHING", None))

    def test_gyst_migrations_and_d005_paths_refuse_tier_one(self):                         # c9, q218
        for path in ("migrations/006_x.sql", "db/migrations/x.sql", "internal/models/user.go", "internal/auth/x.go",
                     "internal/crypto/k.go", "internal/schema.sql", ".claude/settings.json"):
            k = self.planned("gyst", [path])
            self.refused(409, self.review, k, 1, "just a fix")

    def test_no_affected_list_and_a_feature_refuse_tier_one(self):                         # c9
        k = self.planned(affected=[])
        self.assertIn("no affected files", self.refused(409, self.review, k, 1, "a fix"))
        k = self.planned(type="FEATURE")
        self.assertIn("feature", self.refused(409, self.review, k, 1, "a fix"))

    def test_tier_two_opens_the_plan_gate_and_jay_releases_it(self):                       # c9, c11
        k = self.planned(affected=["server/ccd/profiles.py"])
        self.review(k, 2, "a D-007 rail")
        w = self.pl.work(k)
        self.assertEqual((self.status(k), w["gate"], w["size"]), ("RESEARCHING", "plan", "standard"))
        self.assertTrue(w["gateReason"].startswith("Tier 2"), w["gateReason"])
        self.assertEqual(w["planReview"]["tier"], 2)
        self.assertEqual(w["flow"]["waitingOn"], "jay")
        self.refused(409, self.pl.start, k, f"{k}-x", WT + k, "agent:coordinator")           # jay_first holds it
        self.pl.confirm(k, "plan", "jay")
        self.assertEqual(self.status(k), "READY_TO_IMPLEMENT")
        self.assertEqual(self.pl.work(k)["flow"]["stage"], "build")

    def test_an_unclear_tier_is_tier_two(self):                                            # c4
        for tier in (None, "unsure"):
            k = self.planned()
            self.review(k, tier)
            w = self.pl.work(k)
            self.assertEqual((w["gate"], w["planReview"]["tier"], w["planReview"]["tierReason"]),
                             ("plan", 2, "unclear: treated as Tier 2"))

    def test_a_replanned_ticket_that_needed_jay_cannot_take_tier_one(self):
        k = self.planned()
        self.review(k, 2, "a new screen")
        self.pl.confirm(k, "plan", "jay")
        self.pl.replan(k, "agent:coordinator", "scope changed")
        self.pl.plan(k, dict(PLAN, affected=CC_SMALL_FIXES), "agent:planner", session="inv-2")
        self.assertIn("needed Jay", self.refused(409, self.pl.plan_review, k, "APPROVE", "agent:tech-reviewer", "ok",
                                                  session="tr-2", tier=1, tier_reason="small now"))


class RailMatching(unittest.TestCase):
    """The match fails closed (tech review amendments 1 and 2)."""
    CC = registry.pipeline_of("commandcenter")["tier2_paths"]

    def test_odd_spellings_still_hit(self):
        for e in ("server/ccd/profiles.py:99-105", "server/ccd/autonomy.py (note)", "server/ccd", "policy",
                  "server/ccd/*.py", "Policy/projects/x.toml", "./policy/x.toml", "server/ccd/", "../x", "/etc/x"):
            self.assertIsNotNone(tier2_hit(e, self.CC), e)

    def test_agent_files_and_dot_paths_hit_anywhere(self):
        for e in ("AGENTS.md", "CLAUDE.md", "docs/x/CLAUDE.md", "a/GEMINI.md", "a/SKILL.md", ".codex/config.toml",
                  ".mcp.json", ".claude/settings.json"):
            self.assertIsNotNone(tier2_hit(e, self.CC), e)

    def test_ordinary_paths_do_not(self):
        for e in ("server/ccd/pipeline.py:1805", "web/app/src/x.tsx", "scripts/y.sh", "server/tests/test_x.py",
                  "docs/FLOW.md", "server/ccd/tasks.py"):
            self.assertIsNone(tier2_hit(e, self.CC), e)


class OtherProjectsAreUntouched(Base):
    def test_a_tier_on_samvision_or_mfe_is_refused_and_no_tier_behaves_as_before(self):
        for project in ("samvision", "mfe"):
            k = self.planned(project)
            self.refused(400, self.review, k, 1, "a fix")
            self.refused(400, self.review, k, "unsure")
            self.review(k)                                                                 # as today: straight to build
            w = self.pl.work(k)
            self.assertEqual((self.status(k), w["gate"], w["policy"]["tiers"]), ("READY_TO_IMPLEMENT", None, False))
            self.assertNotIn("tier", w["planReview"])

    def test_a_bad_tier_value_is_refused(self):
        k = self.planned()
        self.refused(400, self.review, k, 3, "x")

    def test_send_back_needs_no_tier(self):
        k = self.planned()
        self.pl.plan_review(k, "SEND_BACK", "agent:tech-reviewer", "no repro", session="tr-1")
        self.assertEqual(self.status(k), "RESEARCHING")
        self.assertIsNone(self.pl.work(k)["gate"])


class NothingElseMoves(Base):
    def test_a_tier_never_changes_the_route(self):                                         # c10
        base = {"plan": "auto", "planReasons": [], "merge": "owner", "ui": False, "deploy": False}
        for size in flow.SIZES:
            self.assertEqual(flow.route(size, dict(base, tiers=True)), flow.route(size, dict(base, tiers=False)), size)
        cc = pipeline.policy({"project": "commandcenter"})
        self.assertTrue(cc["tiers"])
        self.assertIn("codeReview", flow.route("standard", cc))
        self.assertIn("userCheck", flow.route("standard", cc))
        self.assertIn("codeReview", flow.route("small", cc))

    def test_merge_stays_with_jay(self):                                                   # c6, c10
        k = self.planned("gyst", ["internal/x.go"])
        before = self.pl.work(k)["policy"]["merge"]
        self.review(k, 1, "a fix")
        self.assertEqual((self.pl.work(k)["policy"]["merge"], before), ("owner", "owner"))
        self.assertEqual(registry.pipeline_of("gyst")["merge"], "owner")
        self.assertEqual(registry.pipeline_of("commandcenter")["merge"], "low-risk")      # unchanged; auto_merge is off

    def test_the_tier_reason_is_secret_filtered_and_kept_on_the_event(self):
        k = self.planned()
        self.refused(400, self.review, k, 1, "password=hunter2hunter2")
        self.assertEqual(self.pl.work(k)["planReviews"], [])
        self.review(k, 1, "a fix")
        self.assertEqual([(r["tier"], r["tierReason"]) for r in self.pl.work(k)["planReviews"]], [(1, "a fix")])
        self.assertEqual(json.loads(self.pl.db.execute(
            "SELECT data FROM ticket_events WHERE kind='pipeline.plan_reviewed'").fetchone()[0])["tier"], 1)


class CliAndRegistry(unittest.TestCase):
    def test_the_cli_passes_tier_and_reason(self):
        _, path, body, actor = pipeline_cli.build(["plan-review", "CC-1", "APPROVE", "--role", "tech-reviewer",
                                                   "--session", "s", "--note", "n", "--tier", "1",
                                                   "--tier-reason", "a fix"])
        self.assertEqual((body["tier"], body["tierReason"], actor), ("1", "a fix", "agent:tech-reviewer"))

    def test_only_gyst_and_command_center_have_tiers(self):                                # c1
        for key in ("samvision", "mfe", "gauzemate"):
            self.assertNotIn("plan_tiers", registry.pipeline_of(key))
            self.assertNotIn("tier2_paths", registry.pipeline_of(key))
        self.assertNotIn("plan_tiers", registry.PIPELINE_DEFAULTS)
        self.assertNotIn("tier2_paths", registry.PIPELINE_DEFAULTS)
        cc = registry.pipeline_of("commandcenter")
        for rail in ("server/ccd/autonomy.py", "server/ccd/broker.py", "server/ccd/security.py",
                     "server/ccd/profiles.py", "server/ccd/merge_policy.py", "policy/**", ".claude/**", ".github/**",
                     "AGENTS.md", "CLAUDE.md"):
            self.assertIn(rail, cc["tier2_paths"])
        g = registry.pipeline_of("gyst")
        for p in ("**/migrations/**", ".claude/**", "**/models/**", "**/schema*", "**/auth/**", "**/crypto/**"):
            self.assertIn(p, g["tier2_paths"])
        self.assertTrue(cc["plan_tiers"] and g["plan_tiers"])


if __name__ == "__main__":
    unittest.main()
