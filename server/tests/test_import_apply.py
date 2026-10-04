"""CC-008: the one-time import's apply step, its CLI, provenance and idempotency."""
import json
import os
import sqlite3
import tempfile
import unittest

from ccd import import_tasks, importer
from ccd.tasks import TaskError, TaskStore

ALL = [{"key": k} for k in ("samvision", "gauzemate", "mfe", "gyst", "commandcenter")]


def tmpdir():
    return tempfile.mkdtemp(prefix="imp-")


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


class Apply(unittest.TestCase):
    def setUp(self):
        sv, gz, gy = tmpdir(), tmpdir(), tmpdir()
        write(sv, "docs/tasks/INDEX.md",
              "| ID | Task | Priority | Status | Dependency | PR | Last |\n|---|---|---|---|---|---|---|\n"
              "| SV-001 | Done thing | P0 | DONE | — | #38 | x |\n"
              "| SV-002 | Denied thing | P2 | DENIED | — | — | x |\n"
              "| SV-056 | Verifying | P1 | VERIFYING (needs Jay) | SV-001 | #88 | x |\n"
              "| SV-060 | Weird | P2 | MAYBE | — | — | x |\n")
        write(sv, "docs/jay/MY_ACTIONS.md", "- [ ] SV-056 · run the drill · docs/x.md\n- [ ] Mileage · fix a trip\n")
        write(gz, "docs/jay/MY_ACTIONS.md", "- [ ] GM-014 · check the sterile field photo · docs/x.md\n"
                                             "- [ ] GM-003 · another\n")
        write(gy, "docs/tasks/UI-3-projects.md", "# UI-3 — Projects screen\n\n**Status:** DONE\n")
        write(gy, "docs/tasks/UI-4-board.md", "# UI-4 — Board\n\n**Status:** IN_PROGRESS\n")
        write(gy, "docs/tasks/NOID.md", "# nothing\n**Status:** DONE\n")
        self.projects = [
            {"key": "samvision", "repo": "o/sv", "path": sv, "index": "docs/tasks/INDEX.md",
             "actions": "docs/jay/MY_ACTIONS.md"},
            {"key": "gauzemate", "repo": "o/gz", "path": gz, "actions": "docs/jay/MY_ACTIONS.md"},
            {"key": "gyst", "repo": "o/gy", "path": gy, "actions": "docs/jay/MY_ACTIONS.md"}]
        self.gh = {"samvision": {"issues": [{"number": 8, "title": "Brand new bug", "url": "https://i/8",
                                             "labels": [{"name": "bug"}]}]},
                   "gauzemate": {"issues": [{"number": 3, "title": "A gz issue", "url": "https://i/3", "labels": []}]}}
        self.dir = tmpdir()
        self.path = os.path.join(self.dir, "tasks.db")
        self.s = TaskStore(self.path, ALL)
        self.handoff = tmpdir()

    def tearDown(self):
        self.s.close()

    def apply(self):
        return importer.apply(self.projects, self.gh, self.s, handoff_dir=self.handoff)

    def test_apply_creates_keys_statuses_and_archives_history(self):
        r = self.apply()
        self.assertEqual(r["errors"], [])
        self.assertEqual(set(r["keys"]) >= {"SV-001", "SV-002", "SV-056", "GM-014", "GM-003", "GYST-001"}, True)
        t = {x["key"]: x for x in self.s.list(include_archived=True)}
        self.assertTrue(t["SV-001"]["archived"] and t["SV-002"]["archived"])
        self.assertEqual((t["SV-001"]["status"], t["SV-002"]["status"]), ("DONE", "DENIED"))
        self.assertFalse(t["SV-056"]["archived"])
        self.assertEqual(r["archived"], sum(1 for k in r["keys"] if t[k]["archived"]))
        self.assertIn("needs_jay", [f for f, v in t["SV-056"]["flags"].items() if v]
                      if isinstance(t["SV-056"]["flags"], dict) else t["SV-056"]["flags"])
        active = {x["key"] for x in self.s.list()}
        self.assertNotIn("SV-001", active)
        self.assertIn("SV-056", active)

    def test_legacy_ids_are_kept_and_new_keys_never_collide(self):
        r = self.apply()
        self.assertIn("GM-014", r["keys"])
        self.assertNotIn("GZ-014", r["keys"])
        gz = [k for k in r["keys"] if k.startswith("GZ-")]
        # the GZ issue and the Mileage-style actions mint live-prefix numbers above every reserved GM number
        self.assertTrue(gz and all(int(k.split("-")[1]) > 14 for k in gz), gz)
        self.assertEqual(len(set(r["keys"])), len(r["keys"]))
        nxt = self.s.create("gauzemate", "later")[0]["key"]
        self.assertNotIn(nxt, r["keys"])

    def test_every_ticket_gets_a_provenance_link(self):
        r = self.apply()
        for k in r["keys"]:
            kinds = [(l["provider"], l["kind"]) for l in self.s.get(k)["links"]]
            self.assertIn(("legacy", "import_source"), kinds, k)
        refs = {l["ref"] for k in r["keys"] for l in self.s.get(k)["links"] if l["kind"] == "import_source"}
        self.assertIn("index:docs/tasks/INDEX.md#SV-056", refs)
        self.assertIn("github_issue:o/sv#8", refs)
        self.assertIn("task_file:docs/tasks/UI-3-projects.md", refs)
        self.assertTrue(any(x.startswith("my_actions:samvision:") and len(x.rsplit(":", 1)[1]) == 12 for x in refs))
        self.assertEqual(self.s.get("SV-056")["blockedBy"], ["SV-001"])

    def test_second_apply_creates_nothing(self):
        first = self.apply()
        n = self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        links = self.s.db.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0]
        second = self.apply()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["keys"], [])
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], n)
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM ticket_links").fetchone()[0], links)
        self.assertGreaterEqual(second["existing"], first["created"] - 1)
        pv = importer.preview(self.projects, self.gh, self.s, self.handoff)
        self.assertEqual(pv["summary"]["wouldCreate"], 0)

    def test_new_source_after_first_apply_gets_a_fresh_number(self):
        first = self.apply()
        write(self.projects[2]["path"], "docs/tasks/UI-5-new.md", "# UI-5 — New\n**Status:** PROPOSED\n")
        second = self.apply()
        self.assertEqual(len(second["keys"]), 1)
        self.assertNotIn(second["keys"][0], first["keys"])

    def test_ambiguous_are_reported_not_created(self):
        r = self.apply()
        self.assertTrue(r["ambiguous"] >= 1)
        self.assertFalse(self.s.exists("SV-060"))
        self.assertIn("SV-060", [a["ref"] for a in r["ambiguousItems"]])

    def test_report_counts(self):
        r = self.apply()
        self.assertEqual(r["created"], len(r["keys"]))
        self.assertEqual(r["sourceCounts"]["samvision"]["index"], 4)
        self.assertEqual(r["sourceCounts"]["gyst"]["task_files"], 3)
        self.assertEqual(r["updated"], 0)
        self.assertIn("skipped", r)
        self.assertIn("duplicate", r)

    def test_one_project_rolls_back_whole_on_error(self):
        orig = self.s.create

        def boom(*a, **kw):
            if a[0] == "gyst" and kw.get("number") == 2:
                raise TaskError(409, "boom")
            return orig(*a, **kw)
        self.s.create = boom
        r = self.apply()
        self.assertEqual([e["project"] for e in r["errors"]], ["gyst"])
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM tickets WHERE project='gyst'").fetchone()[0], 0)
        self.assertEqual(self.s.db.execute("SELECT next_number FROM task_projects WHERE key='gyst'").fetchone()[0], 1)
        self.assertTrue(self.s.exists("SV-056"))  # other projects are unaffected
        self.s.create = orig
        self.assertEqual(self.apply()["created"], 2)  # and the failed project imports cleanly next time

    def test_batch_rolls_back_every_write(self):
        before = self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        with self.assertRaises(TaskError):
            with self.s.batch():
                self.s.create("samvision", "a")
                self.s.create("samvision", "")  # empty title
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], before)
        self.assertEqual(self.s.create("samvision", "b")[0]["key"], "SV-001")


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir()
        self.db = os.path.join(self.dir, "tasks.db")
        self.s = TaskStore(self.db, ALL)
        root = tmpdir()
        write(root, "docs/jay/MY_ACTIONS.md", "- [ ] Do a thing\n")
        self.cfg = {"projects": [{"key": "mfe", "repo": "o/m", "path": root, "actions": "docs/jay/MY_ACTIONS.md"}]}

    def tearDown(self):
        self.s.close()

    def test_dry_run_writes_nothing_and_makes_no_backup(self):
        rep = import_tasks.run(self.db, self.cfg, False, gh_data={})
        self.assertEqual(rep["summary"]["wouldCreate"], 1)
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)
        self.assertEqual([f for f in os.listdir(self.dir) if "bak-import" in f], [])

    def test_apply_backs_up_first_and_saves_the_report(self):
        out = os.path.join(self.dir, "r.json")
        rep = import_tasks.run(self.db, self.cfg, True, gh_data={}, out=out)
        self.assertEqual(rep["created"], 1)
        bak = rep["backup"]
        self.assertTrue(os.path.exists(bak) and ".bak-import-" in bak)
        b = sqlite3.connect(bak)
        self.assertEqual(b.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)  # taken before the import
        b.close()
        self.assertEqual(json.load(open(out))["created"], 1)

    def test_github_failure_is_a_warning_not_a_crash(self):
        got = import_tasks.gather_github(self.cfg["projects"], fetch=lambda p: {"issues": {"error": "gh failed"}})
        self.assertEqual(got, {})


if __name__ == "__main__":
    unittest.main()
