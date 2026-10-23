"""D-024's text of record (docs/decisions/D-024.md): the record that would go into policy/decisions/ on Jay's approval
is valid today, and the file keeps the parts Jay asked for. It is not in policy/, so nothing loads or enforces it."""
import os
import re
import tomllib
import unittest

from ccd import profiles

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "decisions", "D-024.md")


class D024Text(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DOC, encoding="utf-8") as f:
            cls.text = f.read()

    def test_the_draft_record_is_a_valid_decision(self):
        block = re.search(r"```toml\n(.*?)```", self.text, re.S).group(1)
        record = tomllib.loads(block)
        self.assertEqual(profiles.validate_decision(record, name="D-024"), [])
        self.assertEqual(record["id"], "D-024")

    def test_it_is_proposed_not_final_and_not_in_policy(self):
        self.assertIn("| Status | **Proposed.**", self.text)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(DOC), "..", "..", "policy", "decisions",
                                                     "D-024.toml")))

    def test_it_has_eighteen_clauses_and_both_annexes(self):
        policy = self.text.split("## Policy text", 1)[1].split("**Scope:**", 1)[0]
        numbers = [int(n) for n in re.findall(r"^(\d+)\. ", policy, re.M)]
        self.assertEqual(numbers, list(range(1, 19)))
        for heading in ("## Annex A", "## Annex B", "## Audit: clauses 14 to 18"):
            self.assertIn(heading, self.text)


if __name__ == "__main__":
    unittest.main()
