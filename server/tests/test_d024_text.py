"""D-024's full text (docs/decisions/D-024.md) and its decision of record (policy/decisions/D-024.toml): Jay made it
final on 2026-10-24T06:51Z. The record in the file and the policy file are the same and valid, and the text keeps
the parts Jay asked for. Making it final switches nothing on; that is tested where each switch lives."""
import os
import re
import tomllib
import unittest

from ccd import profiles

HERE = os.path.dirname(__file__)
DOC = os.path.join(HERE, "..", "..", "docs", "decisions", "D-024.md")
RECORD = os.path.join(HERE, "..", "..", "policy", "decisions", "D-024.toml")
ADR = os.path.join(HERE, "..", "..", "docs", "adr", "0009-d024-onboarding-final.md")


class D024Text(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DOC, encoding="utf-8") as f:
            cls.text = f.read()

    def test_the_policy_file_is_the_record_in_the_text_and_is_valid(self):
        block = re.search(r"```toml\n(.*?)```", self.text, re.S).group(1)
        with open(RECORD, encoding="utf-8") as f:
            on_disk = f.read()
        self.assertEqual(block, on_disk)
        record = tomllib.loads(on_disk)
        self.assertEqual(profiles.validate_decision(record, name="D-024"), [])
        self.assertEqual((record["id"], record["date"], record["decided_by"]), ("D-024", "2026-10-24", "jay"))

    def test_it_is_final_with_an_adr_and_names_what_it_does_not_authorize(self):
        self.assertIn("| Status | **Final.**", self.text)
        self.assertTrue(os.path.exists(ADR))
        for word in ("production enforcement", "agent\nactivation", "credential issuance", "Broker grants",
                     "budget holds", "Slack approval buttons", "Phase 2 enforcement", "production deployment"):
            self.assertIn(word, self.text)

    def test_it_has_eighteen_clauses_and_all_annexes(self):
        policy = self.text.split("## Policy text", 1)[1].split("**Scope:**", 1)[0]
        numbers = [int(n) for n in re.findall(r"^(\d+)\. ", policy, re.M)]
        self.assertEqual(numbers, list(range(1, 19)))
        for heading in ("## Annex A", "## Annex B", "## Annex C", "## Audit: clauses 14 to 18", "### Final review"):
            self.assertIn(heading, self.text)

    def test_jays_defaults_are_written_in(self):
        for words in ("80% (warning) and 95% (urgent)", "100% is the hard hold", "25% of the agent's daily budget or $10",
                      "above $10 needs the Project Lead's approval, above $25 Jay's", "25% of its daily allocation within one hour",
                      "No permanent dollar budgets are set yet", "None while the project is paused",
                      "The link is never an approval credential"):
            self.assertIn(words, self.text)

    def test_no_open_question_wording_left(self):
        self.assertNotRegex(self.text, r"(?i)Q16 to Q18[^.]*(still open|remain open)")
        self.assertNotIn("for Jay's decision", self.text)


if __name__ == "__main__":
    unittest.main()
