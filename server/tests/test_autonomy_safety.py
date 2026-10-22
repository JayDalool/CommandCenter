"""Engine v2 safety patch (Phase 1 validation, 2026-10-22): every case where the shadow engine said "auto" but the
agreed policy needs Jay (U-01 … U-08), the latent gaps (L-01 … L-05), Q-01, and the suites that catch the next case
of the same kind: unknown never becomes "auto", boundaries hold for every action and profile, every deploy goes
through the deploy rules, and every profile key is either read by the engine or makes it fail closed.

Each regression asserts the verdict AND the rule, so a right answer for the wrong reason fails too."""
import copy
import glob
import inspect
import os
import unittest
from unittest import mock

from ccd import autonomy, merge_policy, profiles

from .test_merge_policy import HEAD, f

POL = profiles.load()
OLD = "cd" * 20
PROFILES = {k: POL.profile(k) for k in POL.profiles}
PROFILES["example-restricted"] = POL.examples["example-restricted"]["profile"]


def ready(**over):
    """A CommandCenter merge the target policy allows: tests-only, CI passed, approved at the PR's current head,
    and a PR that GitHub can merge into main from this repository."""
    x = {"project": "commandcenter", "type": "MAINTENANCE", "labels": [], "flags": [], "plan_accepted": True,
         "review_at_head": True, "review_head": HEAD, "pr_head": HEAD, "merged": False, "verified": None,
         "ci": "green", "ci_passed": True, "draft": False, "mergeable": "MERGEABLE", "base": "main",
         "cross_repo": False, "state": "OPEN", "files": [f("server/tests/test_x.py", "ADDED")], "additions": 5, "deletions": 2}
    x.update(over)
    return x


def ev(action, facts, project="commandcenter"):
    return autonomy.evaluate(action, PROFILES.get(project), facts)


class Baselines(unittest.TestCase):
    """The starting points really are "auto": otherwise every "never auto" test below would pass vacuously."""

    def test_the_starting_points_are_auto(self):
        self.assertEqual(ev("merge", ready())["outcome"], "auto")
        self.assertEqual(ev("deploy", ready(env="preview"))["outcome"], "auto")
        self.assertEqual(ev("plan", ready())["outcome"], "auto")     # allowlisted files make the risk low
        self.assertEqual(autonomy.ENGINE_VERSION, 2)


class Regressions(unittest.TestCase):
    def check(self, facts, rule, action="merge", project="commandcenter", outcome="jay"):
        v = ev(action, facts, project)
        self.assertEqual((v["outcome"], v["rule"]), (outcome, rule), v)
        return v

    def test_u01_draft_pr(self):
        self.check(ready(draft=True), "merge:readiness")
        v = self.check(ready(draft=None), "merge:readiness:unknown")
        self.assertIn("whether the PR is a draft", v["missing"])

    def test_u02_not_mergeable(self):
        for m in ("CONFLICTING", "BLOCKED", "mergeable"):
            self.check(ready(mergeable=m), "merge:readiness")
        for m in (None, "UNKNOWN"):
            self.check(ready(mergeable=m), "merge:readiness:unknown")

    def test_u03_not_based_on_main(self):
        for b in ("release", "Main", "main2", ""):
            self.check(ready(base=b), "merge:readiness")
        self.check(ready(base=None), "merge:readiness:unknown")

    def test_u04_pr_from_a_fork(self):
        self.check(ready(cross_repo=True), "merge:readiness")
        self.check(ready(cross_repo="false"), "merge:readiness")       # anything but False is not "same repo"
        self.check(ready(cross_repo=None), "merge:readiness:unknown")

    def test_u05_review_on_an_older_head(self):
        v = self.check(ready(review_head=OLD), "target.merge:requires")
        self.assertIn("the approving review is for an older head of the PR", v["reasons"])
        for h in (None, "", HEAD[:12], 42):
            v = self.check(ready(pr_head=h), "target.merge:unknown")
            self.assertIn("the PR head the review is for", v["missing"])
        # facts_of never claims the review is for the current head without knowing the PR head
        fx = autonomy.facts_of({"project": "commandcenter"}, {"review": {"verdict": "APPROVE", "head": OLD}})
        self.assertEqual((fx["review_head"], fx.get("pr_head")), (OLD, None))

    def test_u06_every_deploy_goes_through_the_deploy_rules(self):
        for env in ("prod", "production", "staging", "", "  ", "live2", 7):
            v = self.check(ready(env=env, merged=True, verified=True), "deploy:unknown_env", action="deploy")
            self.assertNotIn("plan", v["rule"])
        for env in ("live", "Live", " LIVE ", None):        # live, however spelt: needs capabilities that don't exist
            self.check(ready(env=env, merged=True, verified=True), "target.deploy:requires", action="deploy")
        self.check(ready(env="preview"), "deploy:not_live", action="deploy", outcome="auto")
        # deploy = never refuses every environment, before a boundary could soften it to "jay"
        restricted = copy.deepcopy(PROFILES["example-restricted"])
        restricted["target"]["plan_approval"] = {"required_for": []}
        for env in ("preview", "dev", "live", None, "prod"):
            for labels in ([], ["destructive"]):
                v = autonomy.evaluate("deploy", restricted, ready(env=env, labels=labels))
                self.assertEqual((v["outcome"], v["rule"]), ("refuse", "target.deploy:never"), (env, labels))

    def test_u07_human_only_boundary_labels(self):
        for label in sorted(autonomy.BOUNDARY_LABELS):
            for action in ("plan", "merge"):
                v = self.check(ready(labels=[label]), "boundary", action=action)
                self.assertTrue(v["reasons"])
        self.check(ready(labels=["Destructive"]), "boundary", action="plan")
        self.check(ready(labels=["secrets"], env="preview"), "boundary", action="deploy")

    def test_u08_all_skipped_ci_is_not_a_pass(self):
        skipped = [{"conclusion": "SKIPPED"}, {"conclusion": "NEUTRAL"}]
        self.assertEqual(merge_policy.ci_state(skipped), "green")   # legacy is unchanged (it decides auto-merge today)
        self.assertIs(autonomy.ci_passed(skipped), False)
        self.assertIs(autonomy.ci_passed([{"conclusion": "SUCCESS"}, {"conclusion": "SKIPPED"}]), True)
        for r in (None, [], "x", [{"conclusion": "FAILURE"}], [{"status": "IN_PROGRESS"}], [None]):
            self.assertIsNone(autonomy.ci_passed(r), r)
        v = self.check(ready(ci_passed=False), "target.merge:requires")
        self.assertIn("no CI check passed (every check was skipped)", v["reasons"])
        v = self.check(ready(ci_passed=None), "target.merge:unknown")
        self.assertIn("a passing CI check", v["missing"])

    def test_l01_every_rail_is_self_protected(self):
        rails = PROFILES["commandcenter"]["target"]["self_protection"]["require_jay_for_paths"]
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for path in sorted(glob.glob(os.path.join(here, "ccd", "*.py"))):
            rel = "server/ccd/" + os.path.basename(path)
            self.assertTrue(autonomy._matches(rel, rails), rel)
            self.check(ready(files=[f(rel)]), "D-007:self_protection")
        for rel in ("server/ccd/broker.py", "scripts/go-live.sh", "launcher/main.py", ".github/workflows/ci.yml",
                    "policy/projects/gyst.toml", "web/app/src/App.tsx", ".claude/settings.json", "AGENTS.md",
                    "docs/CLAUDE.md"):
            self.check(ready(files=[f(rel)]), "D-007:self_protection")

    def test_l02_gyst_personal_data_categories(self):
        gyst = copy.deepcopy(PROFILES["gyst"])
        gyst["target"]["merge"] = {"policy": "low-risk"}       # as if GYST could ever reach an auto merge
        with mock.patch.object(autonomy, "risk_of", return_value="low"):
            v = autonomy.evaluate("merge", gyst, ready(project="gyst", files=[f("app/jobs/retention.py")]))
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "merge:readiness:unknown"))
            self.assertIn("which personal-data categories it touches", v["missing"])
            v = autonomy.evaluate("merge", gyst, ready(project="gyst", personal_data=["retention"],
                                                       files=[f("app/jobs/retention.py")]))
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-005:personal_data"))
            v = autonomy.evaluate("merge", gyst, ready(project="gyst", personal_data=[], files=[f("app/x.py")]))
            self.assertEqual(v["outcome"], "auto")         # categories known and none touched

    def test_l03_case_never_bypasses_a_boundary(self):
        for flags in (["NEEDS:JAY"], ["Needs-Jay"], ["needs_legal"]):
            self.check(ready(flags=flags), "boundary")
        for labels in (["Legal"], ["LEGAL"], [" secrets "]):
            self.check(ready(labels=labels), "boundary")
        self.check(ready(type="legal"), "boundary")
        self.check(ready(type="security"), "target.merge:requires")      # high risk, whatever the case
        for bad in ("destructive", {"a": 1}, 3):                        # unreadable labels or flags are not "none"
            self.check(ready(labels=bad), "boundary")
            self.check(ready(flags=bad), "boundary")

    def test_l04_profile_fields_the_engine_cannot_check_fail_closed(self):
        cc = copy.deepcopy(PROFILES["commandcenter"])
        cc["mode"] = "restricted"
        for action, fx in (("merge", ready()), ("plan", ready()), ("deploy", ready(env="preview"))):
            v = autonomy.evaluate(action, cc, fx)
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "profile:fails_closed"), action)
        cc = copy.deepcopy(PROFILES["commandcenter"])
        cc["target"]["constraints"] = {"never": ["prod_database"]}
        for action, fx in (("merge", ready()), ("deploy", ready(env="preview"))):
            v = autonomy.evaluate(action, cc, fx)
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "profile:fails_closed"), action)
        cc["target"]["deploy"]["env"] = "none"
        self.assertEqual(autonomy.evaluate("deploy", cc, ready(env="preview"))["rule"], "target.deploy:env_none")

    def test_l05_unattended_live_deploy_needs_migration_downtime_and_workflow_facts(self):
        cc = copy.deepcopy(PROFILES["commandcenter"])
        cc["capabilities"] = {"health_checks": True, "auto_rollback": True}
        base = ready(env="live", merged=True, verified=True)
        v = autonomy.evaluate("deploy", cc, base)
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.deploy:unknown"))
        self.assertEqual(len(v["missing"]), 3)
        v = autonomy.evaluate("deploy", cc, dict(base, no_migration=False, no_downtime=True, no_client_workflow_change=True))
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.deploy:requires"))
        v = autonomy.evaluate("deploy", cc, dict(base, no_migration=True, no_downtime=True, no_client_workflow_change=True))
        self.assertEqual(v["outcome"], "auto")

    def test_q01_high_risk_commandcenter_plans_need_jay(self):
        for over in ({"labels": ["migration"]}, {"labels": ["security"]}, {"type": "SECURITY"},
                     {"labels": ["architecture"]}):
            self.check(ready(**over), "target.plan_approval", action="plan")
        v = self.check(ready(files=None), "target.plan_approval:unknown", action="plan")
        self.assertEqual(v["missing"], ["risk"])


# The facts that gate an "auto" verdict, and values that must never be read as a yes.
CORRUPT = (None, "", 0, 1, "yes", "True", [], {}, "UNKNOWN")
GATES = {
    "merge": ("ci", "ci_passed", "review_at_head", "review_head", "pr_head", "draft", "mergeable", "base",
              "cross_repo", "state", "files", "additions", "deletions", "project"),
    "deploy": ("env",),
    "plan": ("files", "additions", "deletions", "project"),
}


class UnknownIsNeverAuto(unittest.TestCase):
    def test_every_gating_fact_missing_or_corrupt_is_never_auto(self):
        starts = {"merge": ready(), "deploy": ready(env="preview"), "plan": ready()}
        n = 0
        for action, keys in GATES.items():
            for key in keys:
                variants = [("missing", None)] + [("value", c) for c in CORRUPT
                                                  if not (key in ("additions", "deletions") and c in (0, 1))]
                # (0 or 1 is a real line count; the per-file counts still bound the size)
                for kind, value in variants:
                    fx = copy.deepcopy(starts[action])
                    if kind == "missing":
                        fx.pop(key, None)
                    else:
                        fx[key] = value
                    if action == "deploy" and key == "env" and (kind == "missing" or value is None):
                        continue        # a deploy that does not say where is treated as live: checked elsewhere
                    v = ev(action, fx)
                    n += 1
                    self.assertNotEqual(v["outcome"], "auto", (action, key, kind, value, v))
        self.assertGreater(n, 150)

    def test_for_every_profile_a_corrupt_fact_never_turns_into_auto(self):
        for name, prof in PROFILES.items():
            for action, keys in GATES.items():
                for key in keys:
                    fx = ready(project=name, env="preview") if action == "deploy" else ready(project=name)
                    fx[key] = "UNKNOWN"
                    v = autonomy.evaluate(action, prof, fx)
                    if v["outcome"] == "auto":
                        self.fail(f"{name} {action} with {key}=UNKNOWN is auto: {v}")

    def test_the_engine_never_raises_and_an_internal_error_is_jay(self):
        hostile = ({"files": [{"path": None}, {"path": 3}, "x" * 10000]}, {"labels": [None, 3, [1]]},
                   {"env": object()}, {"review_head": ["a"], "pr_head": {"b": 1}}, {"personal_data": "retention"})
        for name, prof in PROFILES.items():
            for fx in hostile:
                for action in autonomy.ACTIONS:
                    self.assertIn(autonomy.evaluate(action, prof, ready(**fx))["outcome"], autonomy.OUTCOMES)
        with mock.patch.object(autonomy, "_decide", side_effect=RuntimeError("boom")):
            v = ev("merge", ready())
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "engine:error"))


class FirstReview(unittest.TestCase):
    """Inputs the first independent review of the safety patch found still gave "auto" (none reachable from today's
    profiles or daemon facts). Each asserts the verdict and the rule."""

    def test_missing_labels_flags_or_type_are_never_read_as_none(self):
        for action, start in (("merge", ready()), ("plan", ready()), ("deploy", ready(env="preview"))):
            for key in ("labels", "flags", "type"):
                fx = dict(start)
                fx.pop(key)
                v = ev(action, fx)
                self.assertEqual((v["outcome"], v["rule"]), ("jay", "boundary:unknown"), (action, key))
            for key in ("labels", "flags"):
                v = ev(action, dict(start, **{key: None}))
                self.assertEqual((v["outcome"], v["rule"]), ("jay", "boundary:unknown"), (action, key))
        self.assertEqual(ev("merge", ready(type=None))["outcome"], "auto")     # an untyped ticket is a real ticket

    def test_readiness_holds_whatever_the_merge_conditions_say(self):
        for merge in ({"policy": "low-risk"}, {"policy": "auto", "requires": []}):
            prof = copy.deepcopy(PROFILES["commandcenter"])
            prof["target"]["merge"] = merge
            self.assertEqual(autonomy.evaluate("merge", prof, ready())["outcome"], "auto", merge)
            for over in ({"ci": "red"}, {"ci_passed": False}, {"review_at_head": False}, {"state": "CLOSED"},
                         {"ci": None}, {"ci_passed": None}, {"state": None}):
                v = autonomy.evaluate("merge", prof, ready(**over))
                self.assertEqual(v["outcome"], "jay", (merge, over, v))
                self.assertTrue(v["rule"].startswith("merge:readiness"), (merge, over, v))

    def test_a_profile_that_names_one_deploy_environment_allows_no_other(self):
        prof = copy.deepcopy(PROFILES["commandcenter"])
        prof["target"]["deploy"] = {"policy": "auto", "env": "preview", "requires": ["merged", "verify_pass"]}
        prof["capabilities"] = {"health_checks": True, "auto_rollback": True}
        live = ready(env="live", merged=True, verified=True, no_migration=True, no_downtime=True,
                     no_client_workflow_change=True)
        v = autonomy.evaluate("deploy", prof, live)
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.deploy:env"))
        self.assertEqual(autonomy.evaluate("deploy", prof, ready(env="dev"))["rule"], "target.deploy:env")
        self.assertEqual(autonomy.evaluate("deploy", prof, ready(env="preview"))["outcome"], "auto")

    def test_personal_data_categories_ignore_case_and_cover_live_deploys(self):
        prof = copy.deepcopy(PROFILES["commandcenter"])
        prof["target"]["personal_data"] = {"require_approval_for": ["deletion"]}
        v = autonomy.evaluate("merge", prof, ready(personal_data=["Deletion"]))
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-005:personal_data"))
        self.assertEqual(autonomy.evaluate("merge", prof, ready(personal_data=[]))["outcome"], "auto")
        prof["capabilities"] = {"health_checks": True, "auto_rollback": True}
        live = dict(ready(env="live", merged=True, verified=True, no_migration=True, no_downtime=True,
                          no_client_workflow_change=True, files=[f("docs/a.md")]))
        self.assertEqual(autonomy.evaluate("deploy", prof, dict(live, personal_data=[]))["outcome"], "auto")
        v = autonomy.evaluate("deploy", prof, dict(live, personal_data=["deletion"]))
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-005:personal_data"))
        v = autonomy.evaluate("deploy", prof, live)
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "D-005:personal_data:unknown"))

    def test_a_head_with_a_trailing_newline_is_not_a_head(self):
        v = ev("merge", ready(review_head=HEAD + "\n", pr_head=HEAD + "\n"))
        self.assertNotEqual(v["outcome"], "auto", v)


class SecondReview(unittest.TestCase):
    """Inputs the second independent review found still gave "auto" (none reachable today)."""

    def test_unreadable_items_in_labels_flags_or_type_are_a_boundary(self):
        cases = [("merge", ready(labels=[{"name": "legal"}])), ("merge", ready(labels=[None])),
                 ("merge", ready(labels=[None, 3, [1]])), ("deploy", ready(env="preview", labels=[{"name": "x"}])),
                 ("plan", ready(flags=[{"needs_jay": 1}])), ("plan", ready(type=["LEGAL"])),
                 ("deploy", ready(env="preview", type=["LEGAL"])), ("merge", ready(type=["SECURITY"])),
                 ("merge", ready(type=7))]
        for action, fx in cases:
            v = ev(action, fx)
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "boundary"), (action, fx["labels"], fx["type"]))

    def test_a_needs_jay_or_needs_legal_label_counts_like_the_flag(self):
        for label in ("needs:jay", "needs:legal", "Needs:Jay"):
            self.assertEqual(ev("merge", ready(labels=[label]))["rule"], "boundary", label)

    def live(self, **over):
        x = dict(env="live", merged=True, verified=True, no_migration=True, no_downtime=True,
                 no_client_workflow_change=True, low_blast_radius=True, files=[f("docs/a.md")])
        x.update(over)
        return ready(**x)

    def test_release_rules_apply_to_every_unattended_live_deploy(self):
        prof = copy.deepcopy(PROFILES["commandcenter"])
        prof["target"]["deploy"] = {"policy": "auto", "env": "live", "requires": []}
        prof["target"]["release"] = {"unattended_requires": ["health_checks", "auto_rollback"],
                                     "unattended_when": ["risk_low", "no_migration", "no_meaningful_downtime",
                                                         "low_blast_radius", "no_client_workflow_change"]}
        self.assertEqual(profiles.validate_profile(prof, POL.decisions, "commandcenter"), [])
        v = autonomy.evaluate("deploy", prof, self.live())
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.release:unattended_requires"))
        prof["capabilities"] = {"health_checks": True, "auto_rollback": True}
        self.assertEqual(autonomy.evaluate("deploy", prof, self.live())["outcome"], "auto")
        v = autonomy.evaluate("deploy", prof, self.live(low_blast_radius=None))
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.deploy:unknown"))
        v = autonomy.evaluate("deploy", prof, self.live(low_blast_radius=False))
        self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.release:unattended_when"))
        v = autonomy.evaluate("deploy", prof, self.live(files=[f("server/ccd/x.py")]))
        self.assertEqual(v["outcome"], "jay")

    def test_a_required_review_that_is_not_recorded_makes_a_merge_jay(self):
        for review in ({"claude": "always", "codex": "always", "security": "never"},
                       {"claude": "always", "codex": "never", "security": "always"},
                       {"claude": "always", "codex": "on_plan_package", "security": "never"}):
            prof = copy.deepcopy(PROFILES["commandcenter"])
            prof["target"]["review"] = review
            self.assertEqual(profiles.validate_profile(prof, POL.decisions, "commandcenter"), [], review)
            v = autonomy.evaluate("merge", prof, ready())
            self.assertEqual((v["outcome"], v["rule"]), ("jay", "target.review"), review)
        self.assertEqual(ev("merge", ready())["outcome"], "auto")      # on_risk_high / on_trigger, nothing triggered
        prof = copy.deepcopy(PROFILES["commandcenter"])
        prof["target"]["merge"] = {"policy": "auto", "requires": ["ci_green", "review_approved_at_head"]}
        self.assertEqual(autonomy.evaluate("merge", prof, ready(labels=["security"]))["rule"], "target.review")


class Coverage(unittest.TestCase):
    """A profile key, mode, trigger or condition the engine does not handle must fail the build, not be ignored."""

    def test_every_target_key_is_enforced_fails_closed_or_inert(self):
        self.assertEqual(set(profiles.TARGET), set(autonomy.FIELDS))
        self.assertTrue(set(autonomy.FIELDS.values()) <= {"enforced", "fails_closed", "inert"})

    def test_every_sub_key_of_an_enforced_field_is_read_or_safe_to_ignore(self):
        # Sub-keys the engine does not read, and why ignoring each can never make a verdict more permissive.
        ignored = {
            ("plan_approval", "package"): "what a plan package contains, not whether Jay approves it",
            ("plan_approval", "reviewers"): "who reviews a plan package; approval is required_for",
            ("review", "claude"): "the approving review is always required (readiness)",
            ("release", "windows"): "a release_window deploy is always jay until unattended release exists",
            ("release", "otherwise"): "the only value is prepare_and_hold_for_jay",
            ("release", "client_note"): "a note, not a permission",
            ("personal_data", "auto_allowed"): "can only allow; the engine never grants it",
            ("self_protection", "require_jay_for_actions"): "those actions are policy/** and .claude/** paths",
        }
        src = inspect.getsource(autonomy)
        for field, how in autonomy.FIELDS.items():
            spec = profiles.TARGET[field]
            if how != "enforced" or not isinstance(spec, dict):
                continue
            for sub in spec:
                if (field, sub) not in ignored:
                    self.assertIn(f'"{sub}"', src, f"{field}.{sub} is neither read nor listed as safe to ignore")

    def test_every_mode_is_handled(self):
        self.assertEqual(set(profiles.MODES), set(autonomy.MODES_HANDLED))

    def test_every_plan_trigger_and_condition_is_handled(self):
        plan, cond = inspect.getsource(autonomy._plan), inspect.getsource(autonomy._conditions)
        for t in profiles.PLAN_TRIGGERS:
            self.assertIn(f'"{t}"', plan, t)
        for c in profiles.CONDITIONS:
            self.assertIn(f'"{c}"', cond, c)
        prof = copy.deepcopy(PROFILES["commandcenter"])
        prof["target"]["plan_approval"] = {"required_for": ["telepathy"]}
        self.assertEqual(autonomy.evaluate("plan", prof, ready())["outcome"], "jay")   # unknown trigger: never a yes


if __name__ == "__main__":
    unittest.main()
