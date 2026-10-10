"""UI test runs (ccd/uitests.py): findings.json is model output, validated field by field; Jay decides each one."""
import json
import os
import tempfile
import unittest

from ccd.uitests import UiTests, clean_findings


class Findings(unittest.TestCase):
    def test_only_documented_fields_bounded_and_ordered_by_severity(self):
        raw = {"summary": {"features": 3, "passed": 9, "failed": "x", "extra": 1},
               "findings": [
                   {"id": "F2", "severity": "minor", "title": "Cut text", "steps": ["a", 5, "b"], "evil": "<script>"},
                   {"id": "F1", "severity": "showstopper", "title": "Data lost\x00 on save", "expected": "x" * 5000},
                   {"id": "F1", "severity": "major", "title": "duplicate id"},
                   {"id": "X9", "severity": "major", "title": "bad id"},
                   {"id": "F3", "severity": "critical", "title": "unknown severity"},
                   {"id": "F4", "severity": "major", "title": ""},
                   "not an object"]}
        out = clean_findings(raw)
        self.assertEqual(out["summary"], {"features": 3, "passed": 9})
        self.assertEqual([f["id"] for f in out["findings"]], ["F1", "F2"])
        f1, f2 = out["findings"]
        self.assertEqual(f1["title"], "Data lost  on save")
        self.assertEqual(len(f1["expected"]), 1000)
        self.assertEqual(f2["steps"], ["a", "b"])
        self.assertNotIn("evil", f2)
        self.assertEqual(clean_findings("nonsense"), {"summary": {}, "findings": []})

    def test_runs_reports_and_decisions(self):
        root = tempfile.mkdtemp(prefix="ui-")
        d = os.path.join(root, "gyst", "2026-10-10-0930")
        os.makedirs(d)
        with open(os.path.join(d, "report.md"), "w") as f:
            f.write("Status: complete\n\n3 features\n")
        with open(os.path.join(d, "findings.json"), "w") as f:
            json.dump({"summary": {"features": 3}, "findings": [{"id": "F1", "severity": "major", "title": "x"}]}, f)
        os.makedirs(os.path.join(root, "gyst", "not-a-run"))
        ui = UiTests(root)
        self.assertEqual(ui.runs("gyst"), ["2026-10-10-0930"])
        r = ui.latest("gyst")
        self.assertEqual((r["status"], r["findings"][0]["decision"]), ("complete", None))
        ui.decide("gyst", "2026-10-10-0930", "F1", "fix", "GYST-40", now=5)
        self.assertEqual(ui.latest("gyst")["findings"][0]["decision"], {"decision": "fix", "ticket": "GYST-40", "at": 5})
        for bad in (("../x", "2026-10-10-0930"), ("gyst", "../../etc"), ("gyst", "2026-10-10")):
            self.assertIsNone(ui.run(*bad))
        with self.assertRaises(ValueError):
            ui.decide("gyst", "2026-10-10-0930", "F1", "merge")
        self.assertEqual(ui.runs("nope"), [])


if __name__ == "__main__":
    unittest.main()
