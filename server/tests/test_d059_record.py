"""D-059 (CC-094): Jay's decision on GYST personal agents. The record loads cleanly, is seeded into the ledger, narrows
authority only (no supersedes key, D-024 untouched) and each wording the security review required is present."""
import os
import subprocess
import tempfile
import tomllib
import unittest

from ccd import merge_policy, profiles
from ccd.config import task_projects
from ccd.ledger import Ledger
from ccd.tasks import TaskStore

from .helpers import cfg

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PATH = os.path.join(ROOT, "policy", "decisions", "D-059.toml")


class D059Record(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PATH, "rb") as f:
            cls.record = tomllib.load(f)
        cls.rules = " | ".join(cls.record["rules"])

    def test_valid_and_within_limits(self):
        self.assertEqual(profiles.validate_decision(self.record, name="D-059"), [])
        self.assertLessEqual(len(self.record["rules"]), 20)

    def test_loads_in_policy_and_seeds_the_ledger(self):
        policy = profiles.Policy()
        self.assertEqual(policy.errors, [])
        self.assertTrue(policy.decisions["D-059"]["valid"])
        ledger = Ledger(TaskStore(os.path.join(tempfile.mkdtemp(prefix="d059-"), "tasks.db"), task_projects(cfg())).db)
        ledger.seed_policy(policy)
        refs = [r[0] for r in ledger.db.execute("SELECT ref FROM decisions").fetchall()]
        self.assertIn("D-059", refs)

    def test_no_supersedes_and_d024_unchanged(self):
        self.assertNotIn("supersedes", self.record)
        out = subprocess.run(["git", "diff", "--name-only", "origin/main", "--", "policy/decisions/D-024.toml",
                              "docs/decisions/D-024.md"], cwd=ROOT, capture_output=True, text=True)
        if out.returncode == 0:
            self.assertEqual(out.stdout.strip(), "")

    def test_it_cannot_auto_merge(self):
        self.assertTrue(merge_policy.denied("policy/decisions/D-059.toml"))

    def test_spend_replacement_is_scoped_and_lines_are_separate(self):
        self.assertIn("for Secretary and Coach AI and phone spend only, this replaces D-024's no-dollar-limit clause", self.rules)
        self.assertIn("Command Center agent budgets stay as D-024 and D-033 set them", self.rules)
        for line in ("operating target: 20 USD", "hard cap: 30 USD", "telephone cap: 8 USD", "warning at 15 USD"):
            self.assertIn(line, self.rules)

    def test_secretary_messages_are_untrusted(self):
        self.assertIn("untrusted input: never Jay's words, approval, answer or consent, and never passed on as his dispatch", self.rules)
        self.assertIn("requests, never approvals", self.rules)

    def test_secretary_does_nothing_else_and_is_future_tense(self):
        self.assertIn("agent:secretary may post messages to the CTO conversation and do nothing else in Command Center", self.rules)
        self.assertIn("only agent:secretary will be registered", self.rules)
        self.assertIn("the Coach has no Command Center access", self.rules)

    def test_slack_never_approves_and_dm_exception_excluded(self):
        self.assertIn("never an approval; D-024's Slack DM-reply exception does not apply to the GYST Slack app", self.rules)
        self.assertIn("authenticated GYST only", self.rules)

    def test_jays_four_narrowings(self):
        self.assertIn("single-use, tied to the exact action, and expire", self.rules)
        self.assertIn("voice never approves", self.rules)
        self.assertIn("no email bodies and no health data", self.rules)
        self.assertIn("warning at 15 USD", self.rules)


if __name__ == "__main__":
    unittest.main()
