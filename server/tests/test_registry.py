"""The project registry: one prefix per project, GauzeMate on GZ, GM kept as history."""
import os
import sqlite3
import tempfile
import unittest

from ccd import config, registry, tasks
from ccd.tasks import TaskStore

ALL = [{"key": k} for k in ("samvision", "gauzemate", "mfe", "gyst", "commandcenter")]


def tmpdb():
    return os.path.join(tempfile.mkdtemp(prefix="registry-"), "tasks.db")


class TheRegistry(unittest.TestCase):
    def test_project_to_prefix(self):
        self.assertEqual({r["key"]: r["prefix"] for r in registry.rows()},
                         {"samvision": "SV", "gauzemate": "GZ", "mfe": "MFE",
                          "commandcenter": "CC", "gyst": "GYST"})

    def test_gauzemate_is_gz_not_gm(self):
        self.assertEqual(registry.prefix_of("gauzemate"), "GZ")
        self.assertEqual(registry.legacy_of("gauzemate"), ("GM",))

    def test_prefix_to_project(self):
        self.assertEqual(registry.prefixes()["GZ"], "gauzemate")
        self.assertEqual(registry.prefixes()["GYST"], "gyst")
        self.assertNotIn("GM", registry.prefixes())          # retired: resolves, never mints
        self.assertEqual(registry.legacy_prefixes()["GM"], "gauzemate")
        self.assertEqual(registry.resolve_prefix("gm"), ("GM", "gauzemate", True))
        self.assertEqual(registry.resolve_prefix("GZ"), ("GZ", "gauzemate", False))
        self.assertIsNone(registry.resolve_prefix("ZZ"))

    def test_every_prefix_is_claimed_once(self):
        seen = {}
        for pre, (key, _legacy) in registry.all_prefixes().items():
            self.assertNotIn(pre, seen, f"{pre} claimed by {seen.get(pre)} and {key}")
            seen[pre] = key
        self.assertTrue(all(registry.PREFIX_RE.match(p) for p in registry.prefixes()))

    def test_longest_prefix_wins_in_the_board_id_pattern(self):
        ids = registry.board_id_prefixes()
        self.assertLess(ids.index("GYST-VN"), ids.index("GYST"))

    def test_an_unregistered_project_must_declare_a_prefix(self):
        with self.assertRaises(registry.RegistryError):
            registry.check("someday")
        self.assertEqual(registry.check("someday", "SD"), "SD")

    def test_a_prefix_is_never_recycled(self):
        with self.assertRaises(registry.RegistryError):
            registry.check("other", "SV")      # live elsewhere
        with self.assertRaises(registry.RegistryError):
            registry.check("other", "GM")      # retired elsewhere

    def test_a_config_prefix_may_repeat_the_registry_but_not_contradict_it(self):
        self.assertEqual(registry.check("gauzemate", "GZ"), "GZ")
        with self.assertRaises(registry.RegistryError):
            registry.check("gauzemate", "GM")
        with self.assertRaises(registry.RegistryError):
            registry.check("gauzemate", "XX")

    def test_a_bad_prefix_is_refused(self):
        for bad in ("sv", "S", "TOOLONGX", "S V", "S-V", ""):
            with self.assertRaises(registry.RegistryError):
                registry.check("other", bad)


class ConfigUsesTheRegistry(unittest.TestCase):
    def test_names_and_prefixes_come_from_the_registry(self):
        path = os.path.join(tempfile.mkdtemp(prefix="cfg-"), "config.json")
        with open(path, "w") as f:
            f.write('{"projects": [{"key": "gauzemate", "name": "Gauze", "repo": "o/r", "path": "/tmp"}]}')
        cfg = config.load(path)
        p = cfg["projects"][0]
        self.assertEqual((p["name"], p["prefix"], p["legacy_prefixes"]), ("GauzeMate", "GZ", ["GM"]))
        self.assertIn("prefix", config.PUBLIC_PROJECT_FIELDS)
        self.assertEqual(config.public_project(p)["prefix"], "GZ")


class Generation(unittest.TestCase):
    def setUp(self):
        self.s = TaskStore(tmpdb(), ALL)

    def tearDown(self):
        self.s.close()

    def test_new_gauzemate_tickets_use_gz(self):
        a, _ = self.s.create("gauzemate", "first")
        b, _ = self.s.create("gauzemate", "second")
        self.assertEqual((a["key"], b["key"]), ("GZ-001", "GZ-002"))

    def test_other_projects_keep_their_prefixes(self):
        keys = [self.s.create(k, "t")[0]["key"] for k in ("samvision", "mfe", "gyst", "commandcenter")]
        self.assertEqual(keys, ["SV-001", "MFE-001", "GYST-001", "CC-001"])

    def test_a_retired_prefix_never_mints(self):
        for _ in range(3):
            self.s.create("gauzemate", "t")
        self.assertTrue(all(t["key"].startswith("GZ-") for t in self.s.list()))

    def test_the_counter_is_shared_so_a_number_is_never_reused(self):
        self.s.create("gauzemate", "legacy", number=14)      # as the import keeps GM-014's number
        nxt, _ = self.s.create("gauzemate", "new")
        self.assertEqual(nxt["key"], "GZ-015")

    def test_an_unregistered_project_is_refused_before_any_ticket_exists(self):
        with self.assertRaises(registry.RegistryError):
            self.s.sync_projects([{"key": "newthing", "name": "New"}])
        from ccd.tasks import TaskError
        with self.assertRaises(TaskError):
            self.s.create("newthing", "no key for you")


class RetiringAPrefix(unittest.TestCase):
    """The GauzeMate GM → GZ move, on a file that already holds GM keys."""

    def setUp(self):
        self.path = tmpdb()
        # A v1 file as it was before the registry: gauzemate on GM, with GM keys.
        db = sqlite3.connect(self.path, isolation_level=None)
        db.executescript(f"BEGIN;\n{tasks.MIGRATIONS[0][1]}\nPRAGMA user_version = 1;\nCOMMIT;")
        db.execute("INSERT INTO task_projects(key, name, prefix, next_number, created_at) "
                   "VALUES ('gauzemate', 'GauzeMate', 'GM', 15, 0)")
        for n in (4, 14):
            db.execute("INSERT INTO tickets(project, number, key, title, status, creator, created_at, updated_at) "
                       f"VALUES ('gauzemate', {n}, 'GM-{n:03d}', 'old work', 'INBOX', 'jay', 0, 0)")
        db.close()
        self.s = TaskStore(self.path, ALL)

    def tearDown(self):
        self.s.close()

    def test_historical_keys_are_not_renumbered(self):
        self.assertEqual(sorted(t["key"] for t in self.s.list()), ["GM-004", "GM-014"])
        self.assertEqual(self.s.get("GM-014")["title"], "old work")

    def test_the_live_prefix_moved_and_gm_became_history(self):
        p = {r["key"]: r for r in self.s.projects()}["gauzemate"]
        self.assertEqual(p["prefix"], "GZ")
        self.assertEqual(p["legacyPrefixes"], ["GM"])
        self.assertEqual(self.s.aliases(), {"GM": "gauzemate"})

    def test_new_keys_are_gz_and_continue_the_numbering(self):
        t, _ = self.s.create("gauzemate", "new work")
        self.assertEqual(t["key"], "GZ-015")

    def test_a_legacy_key_is_still_found_resolved_and_linkable(self):
        self.assertEqual(self.s.find_keys("see GM-014 and GZ-15"), ["GM-014", "GZ-015"])
        self.assertEqual(self.s.pr_keys("GM-14: finish it"), ["GM-014"])
        self.assertEqual(self.s.pr_keys("feat: x", "gm-004-fix"), ["GM-004"])
        self.assertEqual(self.s.key_prefixes()["GM"], "gauzemate")
        self.s.link("GM-014", "github", "pr", "o/r#9", None, None, "jay")
        self.assertEqual(self.s.keys_linked("github", "pr", "o/r#9"), ["GM-014"])

    def test_a_retired_prefix_cannot_be_deleted_or_reassigned(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("DELETE FROM task_project_aliases WHERE prefix='GM'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("UPDATE task_project_aliases SET project='samvision' WHERE prefix='GM'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("INSERT INTO task_project_aliases(prefix, project, retired_at) "
                              "VALUES ('SV', 'gauzemate', 0)")

    def test_a_prefix_cannot_change_without_being_retired_first(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("UPDATE task_projects SET prefix='QQ' WHERE key='gauzemate'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("UPDATE task_projects SET next_number=1 WHERE key='gauzemate'")

    def test_the_registry_must_list_a_prefix_it_is_moving_away_from(self):
        saved = dict(registry.PROJECTS["gauzemate"])
        registry.PROJECTS["gauzemate"] = {**saved, "prefix": "QQ", "legacy": ()}
        try:
            with self.assertRaises(registry.RegistryError):
                TaskStore(self.path, ALL)
        finally:
            registry.PROJECTS["gauzemate"] = saved

    def test_a_historical_id_can_be_created_with_its_retired_prefix(self):
        t, _ = self.s.create("gauzemate", "kept", number=7, prefix="GM")
        self.assertEqual(t["key"], "GM-007")
        self.assertEqual(self.s.create("gauzemate", "after")[0]["key"], "GZ-015")

    def test_a_retired_prefix_can_never_take_a_number_from_the_counter(self):
        from ccd.tasks import TaskError
        with self.assertRaises(TaskError):
            self.s.create("gauzemate", "no", prefix="GM")
        with self.assertRaises(TaskError):
            self.s.create("gauzemate", "no", number=99, prefix="ZZ")
        with self.assertRaises(TaskError):
            self.s.create("gauzemate", "clash", number=14, prefix="GM")   # GM-014 exists

    def test_the_import_preview_keeps_legacy_ids_instead_of_renumbering(self):
        import os
        import tempfile
        from ccd import importer
        root = tempfile.mkdtemp(prefix="gauzemate-")
        os.makedirs(os.path.join(root, "docs", "jay"))
        with open(os.path.join(root, "docs", "jay", "MY_ACTIONS.md"), "w") as f:
            f.write("# My actions\n\n- [ ] GM-014 · check the sterile field photo · docs/x.md\n")
        out = importer.preview([{"key": "gauzemate", "name": "GauzeMate", "path": root,
                                 "actions": "docs/jay/MY_ACTIONS.md"}], {}, self.s)
        keys = [c.get("proposedKey") or c.get("key") for c in out["wouldCreate"] + out["wouldUpdate"]]
        self.assertIn("GM-014", keys)
        self.assertNotIn("GZ-014", keys)

    def test_reopening_the_file_changes_nothing(self):
        self.s.close()
        self.s = TaskStore(self.path, ALL)
        self.assertEqual(self.s.applied, [])
        self.assertEqual(self.s.aliases(), {"GM": "gauzemate"})
        self.assertEqual({r["key"]: r["prefix"] for r in self.s.projects()}["gauzemate"], "GZ")
