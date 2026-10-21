"""Project Operating Profiles (policy/, ccd/profiles.py): the repo's own files are valid and match the registry;
the validator refuses what it must; loading never raises."""
import copy
import tempfile
import tomllib
import unittest
import unittest.mock
from pathlib import Path

from ccd import merge_policy, profiles, registry

ROOT = profiles.POLICY_DIR


def _load(path):
    return tomllib.loads(Path(path).read_text())


class RepoPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = profiles.load()

    def test_every_file_in_policy_is_valid_and_matches_the_registry(self):
        self.assertEqual(self.policy.problems(), [])
        self.assertEqual(set(self.policy.profiles), set(registry.PROJECTS))   # one profile per registered project
        for key, rec in self.policy.profiles.items():
            self.assertTrue(rec["valid"], (key, rec["errors"]))
            self.assertEqual(rec["drift"], [], key)                           # [enforced] == what ccd does today
            self.assertRegex(rec["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(self.policy.examples["example-restricted"]["valid"])

    def test_jays_decisions_are_encoded(self):
        p = {k: self.policy.profile(k) for k in registry.PROJECTS}
        self.assertEqual({k: v["mode"] for k, v in p.items()}, {
            "commandcenter": "experimental_autonomy", "gyst": "autonomous_product",
            "samvision": "controlled_production", "mfe": "controlled_production", "gauzemate": "paused"})
        # D-008: nothing auto-merges or deploys beyond today; enforced merge is unchanged.
        self.assertEqual({k: v["enforced"]["merge"] for k, v in p.items()},
                         {"commandcenter": "low-risk", "gyst": "owner", "samvision": "owner", "mfe": "owner",
                          "gauzemate": "owner"})
        # D-004: unattended SamVision deploys need capabilities that do not exist yet.
        rel = p["samvision"]["target"]["release"]
        self.assertEqual(rel["windows"], ["Thu 01:00 America/Winnipeg", "Sat 01:00 America/Winnipeg"])
        self.assertEqual(rel["unattended_requires"], ["health_checks", "auto_rollback"])
        self.assertFalse(any(p["samvision"]["capabilities"].values()))
        # D-005: GYST personal-data triggers.
        self.assertIn("deletion", p["gyst"]["target"]["personal_data"]["require_approval_for"])
        # D-007: Command Center's rails need Jay.
        paths = p["commandcenter"]["target"]["self_protection"]["require_jay_for_paths"]
        for f in ("server/ccd/autonomy.py", "server/ccd/broker.py", "server/ccd/security.py", "policy/**"):
            self.assertIn(f, paths)
        # D-009: GauzeMate paused, no target.
        self.assertEqual(p["gauzemate"]["target"], {})
        # D-002: the restricted example keeps everything on the laptop but allows AI.
        ex = self.policy.examples["example-restricted"]["profile"]["target"]["execution"]
        self.assertEqual((ex["allowed_nodes"], ex["repo_storage"], ex["secrets"]), (["laptop"], "laptop_only", "laptop_only"))
        self.assertEqual(ex["model_providers"], ["anthropic", "openai"])

    def test_policy_files_can_never_auto_merge(self):
        # D-007: no agent may expand its own authority. A PR touching policy/ is never low-risk.
        for f in ("policy/projects/commandcenter.toml", "policy/decisions/D-001.toml", "policy/README.md"):
            self.assertTrue(merge_policy.denied(f), f)


class Validator(unittest.TestCase):
    def setUp(self):
        self.decisions = {p.stem: _load(p) for p in (ROOT / "decisions").glob("*.toml")}
        self.good = _load(ROOT / "projects" / "gyst.toml")

    def errs(self, p, name="gyst", registered=True):
        return profiles.validate_profile(p, self.decisions, name, registered)

    def test_the_good_profile_has_no_errors(self):
        self.assertEqual(self.errs(self.good), [])

    def test_unknown_keys_and_bad_values_are_errors_not_silence(self):
        cases = [
            (lambda p: p["target"]["merge"].update(polcy="auto"), "target.merge.polcy is not a known key"),
            (lambda p: p["target"].update(deploi={}), "target.deploi is not a known key"),
            (lambda p: p["target"]["merge"].update(policy="yolo"), "target.merge.policy must be one of"),
            (lambda p: p["target"]["merge"].update(requires=["ci_green", "vibes"]), "unknown value(s) vibes"),
            (lambda p: p.update(mode="anarchy"), "mode must be one of"),
            (lambda p: p["enforced"].pop("merge"), "enforced.merge is missing"),
            (lambda p: p["enforced"].update(max_lanes=99), "enforced.max_lanes must be a whole number"),
            (lambda p: p["capabilities"].update(auto_rollback="yes"), "capabilities.auto_rollback must be true or false"),
            (lambda p: p.update(extra=1), "extra is not a known section or key"),
            (lambda p: p.update(decisions=["D-404"]), "D-404 does not exist"),
            (lambda p: p.update(decisions=["D-004"]), "D-004 does not apply to gyst"),
            (lambda p: p["target"]["execution"].update(preferred_node="laptop"), "preferred_node is not in allowed_nodes"),
            (lambda p: p.update(project="samvision"), "does not match its file name"),
            (lambda p: p.update(decisions=["D-001", "D-001"]), "decisions has duplicates"),
            (lambda p: p["target"]["merge"].pop("policy"), "target.merge.policy is missing"),
            (lambda p: p["target"]["personal_data"].update(trigger_paths=["app/models/"]), "badly formed: app/models/"),
        ]
        for change, expected in cases:
            p = copy.deepcopy(self.good)
            change(p)
            got = self.errs(p)
            self.assertTrue(any(expected in e for e in got), (expected, got))

    def test_release_windows_must_name_a_day_time_and_zone(self):
        p = _load(ROOT / "projects" / "samvision.toml")
        p["target"]["release"]["windows"] = ["Thursday 1am"]
        self.assertTrue(any("badly formed" in e for e in self.errs(p, "samvision")))

    def test_paused_and_restricted_rules(self):
        gz = _load(ROOT / "projects" / "gauzemate.toml")
        self.assertEqual(self.errs(gz, "gauzemate"), [])
        bad = copy.deepcopy(gz)
        bad["enforced"]["paused"] = ""
        self.assertTrue(any("needs enforced.paused" in e for e in self.errs(bad, "gauzemate")))
        bad = copy.deepcopy(gz)
        bad["target"] = {"merge": {"policy": "auto", "requires": []}}
        self.assertTrue(any("no target policy" in e for e in self.errs(bad, "gauzemate")))
        ex = _load(ROOT / "examples" / "example-restricted.toml")
        self.assertEqual(self.errs(ex, "example-restricted", registered=False), [])
        for change in (lambda t: t["execution"].update(server_clone="allowed"),
                       lambda t: t["execution"].update(allowed_nodes=["laptop", "server"]),
                       lambda t: t["execution"].update(secrets="server_scoped"),
                       lambda t: t["artifacts"].update(store="server")):
            bad = copy.deepcopy(ex)
            change(bad["target"])
            self.assertTrue(any("restricted profile" in e for e in self.errs(bad, "example-restricted", False)))
        self.assertTrue(any("no row in ccd/registry.py" in e for e in self.errs(ex, "example-restricted", True)))

    def test_decision_validation(self):
        d = copy.deepcopy(self.decisions["D-001"])
        self.assertEqual(profiles.validate_decision(d, "D-001"), [])
        d["decided_by"] = "agent:coordinator"                                  # only Jay decides policy
        self.assertTrue(any("decided_by" in e for e in profiles.validate_decision(d, "D-001")))
        self.assertTrue(any("does not match its file name" in e
                            for e in profiles.validate_decision(self.decisions["D-001"], "D-002")))
        for change, expected in ((dict(date="2026-13-45"), "must be a date"),
                                 (dict(projects=["gyst", "nope"]), "unknown project(s) nope")):
            d = dict(self.decisions["D-001"], **change)
            self.assertTrue(any(expected in e for e in profiles.validate_decision(d, "D-001")), expected)


class Loading(unittest.TestCase):
    def copy_policy(self):
        tmp = Path(tempfile.mkdtemp(prefix="policy-"))
        for sub in ("projects", "decisions", "examples"):
            (tmp / sub).mkdir()
            for f in (ROOT / sub).glob("*.toml"):
                (tmp / sub / f.name).write_bytes(f.read_bytes())
        return tmp

    def test_a_broken_file_is_reported_never_raised_and_its_profile_is_unusable(self):
        tmp = self.copy_policy()
        (tmp / "projects" / "gyst.toml").write_text("mode = = broken")
        pol = profiles.load(tmp)
        self.assertFalse(pol.profiles["gyst"]["valid"])
        self.assertIsNone(pol.profile("gyst"))                                 # the engine treats it as most restrictive
        self.assertTrue(any("gyst.toml" in e and "cannot read" in e for e in pol.problems()))
        self.assertIsNotNone(pol.profile("samvision"))                         # the others still load

    def test_a_missing_profile_and_drift_are_problems(self):
        tmp = self.copy_policy()
        (tmp / "projects" / "mfe.toml").unlink()
        text = (tmp / "projects" / "samvision.toml").read_text().replace('night = "careful"', 'night = "normal"')
        (tmp / "projects" / "samvision.toml").write_text(text)
        pol = profiles.load(tmp)
        probs = pol.problems()
        self.assertTrue(any("mfe.toml is missing" in e for e in probs))
        self.assertTrue(any("enforced.night is 'normal' but the registry says 'careful'" in e for e in probs))

    def test_the_fingerprint_changes_with_any_file(self):
        tmp = self.copy_policy()
        before = profiles.load(tmp).fingerprint
        self.assertEqual(profiles.load(tmp).fingerprint, before)
        f = tmp / "decisions" / "D-003.toml"
        f.write_text(f.read_text() + "\n")
        self.assertNotEqual(profiles.load(tmp).fingerprint, before)

    def test_a_type_broken_decision_that_a_profile_cites_never_raises(self):
        tmp = self.copy_policy()
        f = tmp / "decisions" / "D-009.toml"
        f.write_text(f.read_text().replace('projects = ["gauzemate"]', "projects = 5"))
        pol = profiles.load(tmp)                                               # must not raise
        self.assertFalse(pol.decisions["D-009"]["valid"])
        self.assertIsNone(pol.profile("gauzemate"))
        self.assertTrue(any("D-009 is itself invalid" in e for e in pol.problems()))

    def test_an_invalid_decision_makes_the_citing_profile_invalid(self):
        tmp = self.copy_policy()
        f = tmp / "decisions" / "D-005.toml"
        f.write_text(f.read_text().replace('decided_by = "jay"', 'decided_by = "agent:x"'))
        self.assertIsNone(profiles.load(tmp).profile("gyst"))

    def test_summary_stays_json_even_when_a_file_holds_toml_dates(self):
        import json
        tmp = self.copy_policy()
        f = tmp / "decisions" / "D-003.toml"
        f.write_text(f.read_text().replace('date = "2026-10-21"', "date = 2026-10-21"))
        g = tmp / "projects" / "mfe.toml"
        g.write_text(g.read_text().replace("[target]", "[target]\nwhen = 2026-10-21T01:00:00"))
        pol = profiles.load(tmp)
        self.assertTrue(any("D-003" in e for e in pol.problems()))
        s = json.loads(json.dumps(pol.summary()))
        self.assertEqual(s["decisions"]["D-003"]["date"], "2026-10-21")
        self.assertFalse(s["projects"]["mfe"]["valid"])

    def test_supersedes_must_exist(self):
        tmp = self.copy_policy()
        f = tmp / "decisions" / "D-003.toml"
        f.write_text(f.read_text() + '\nsupersedes = "D-777"\n')
        pol = profiles.load(tmp)
        self.assertFalse(pol.decisions["D-003"]["valid"])
        self.assertTrue(any("D-777, which does not exist" in e for e in pol.problems()))

    def test_drift_shows_the_registrys_raw_merge_value(self):
        real = registry.pipeline_of
        with unittest.mock.patch.object(registry, "pipeline_of",
                                        lambda k: dict(real(k), merge="auto") if k == "gyst" else real(k)):
            d = profiles.drift("gyst", profiles.load().profiles["gyst"]["profile"])
        self.assertEqual(d, [{"field": "merge", "profile": "owner", "registry": "auto"}])

    def test_a_policy_problem_is_an_alert(self):
        from ccd.daemon import Daemon
        from ccd.store import Store
        from .helpers import cfg, new_db
        tmp = self.copy_policy()
        (tmp / "projects" / "mfe.toml").unlink()
        store = Store(new_db())
        d = Daemon(cfg(), store, None, policy=profiles.load(tmp))
        alerts = d._compute_alerts({"blocked": [], "needs": []})
        self.assertTrue(any(a["id"] == "policy:problems" and "mfe.toml is missing" in a["text"] for a in alerts))
        store.close()

    def test_summary_is_plain_data(self):
        import json
        s = profiles.load().summary()
        json.dumps(s)
        self.assertEqual(s["projects"]["samvision"]["mode"], "controlled_production")
        self.assertIn("D-008", s["decisions"])


if __name__ == "__main__":
    unittest.main()
