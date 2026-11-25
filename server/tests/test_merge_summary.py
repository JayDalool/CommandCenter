"""CC-057 c8: the three summary lines of a merge DM are pure formatting of facts already read."""
import unittest

from ccd import merge_summary as ms

HEAD = "a" * 40
CRIT = [{"id": "c1", "state": "pass", "head": HEAD}, {"id": "c2", "state": "pass", "head": "b" * 40},
        {"id": "c3", "state": "fail", "head": HEAD}, {"id": "c4", "state": "open", "head": None}]


class Summary(unittest.TestCase):
    def test_achieved_counts_only_passes_recorded_at_this_head(self):
        self.assertEqual(ms.achieved(CRIT, HEAD), "criteria 1/4 passed at this head, c2 open, c3 failed, c4 open")
        self.assertEqual(ms.achieved([], HEAD), "no acceptance criteria recorded")

    def test_sensitive_paths_over_report_across_slashes(self):
        pats = ["server/ccd/**", "**/migrations/**"]
        files = ["server/ccd/a/b.py", "app/migrations/0001.py", "migrations/x.sql", "docs/a.md"]
        self.assertEqual(ms.sensitive_paths(files, pats), ["server/ccd/a/b.py", "app/migrations/0001.py", "migrations/x.sql"])

    def lines(self, facts, **kw):
        return ms.lines(**dict(dict(title="CC-1: x", done="did it", criteria=CRIT[:1], head=HEAD, pr_facts=facts,
                                    patterns=["server/ccd/**"], security="not required"), **kw))

    def test_three_lines_from_a_fixture_ticket(self):
        a, b, c = self.lines({"files": ["server/ccd/x.py", "docs/y.md"], "additions": 5, "deletions": 1})
        self.assertEqual(a, "*Changed:* CC-1: x (2 files, +5/-1) · did it")
        self.assertEqual(b, "*Achieved:* criteria 1/1 passed at this head")
        self.assertEqual(c, "*Sensitive:* server/ccd/x.py · security sign-off: not required")

    def test_a_docs_only_change_names_no_sensitive_path(self):
        c = self.lines({"files": ["docs/y.md"], "additions": 1, "deletions": 0})[2]
        self.assertIn("none of the protected or personal-data paths", c)

    def test_unread_files_are_said_not_hidden(self):
        a, _, c = self.lines(None)
        self.assertIn(ms.UNREAD, a)
        self.assertIn(ms.UNREAD, c)

    def test_a_long_list_is_cut_with_a_count(self):
        facts = {"files": [f"server/ccd/f{i}.py" for i in range(9)], "additions": 1, "deletions": 1}
        self.assertIn("and 3 more", self.lines(facts)[2])
