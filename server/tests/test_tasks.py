"""The ticket store: numbering, audit, status, relations, flags, migrations, import preview."""
import os
import sqlite3
import tempfile
import unittest

from ccd import importer, registry, tasks
from ccd.tasks import TaskError, TaskStore

PROJECTS = [{"key": "samvision", "name": "SamVision"}, {"key": "gauzemate", "name": "GauzeMate"},
            {"key": "commandcenter", "name": "Command Center"}]


def tmpdb():
    return os.path.join(tempfile.mkdtemp(prefix="tasks-"), "tasks.db")


class Base(unittest.TestCase):
    def setUp(self):
        self.path = tmpdb()
        self.s = TaskStore(self.path, PROJECTS)

    def tearDown(self):
        self.s.close()

    def kinds(self, key):
        return [e["kind"] for e in self.s.get(key)["timeline"]]


class Numbering(Base):
    def test_keys_come_from_the_project_prefix_and_counter(self):
        a, _ = self.s.create("commandcenter", "one")
        b, _ = self.s.create("commandcenter", "two")
        c, _ = self.s.create("samvision", "three")
        self.assertEqual((a["key"], b["key"], c["key"]), ("CC-001", "CC-002", "SV-001"))

    def test_numbers_are_never_recycled(self):
        self.s.create("commandcenter", "one")
        self.s.update("CC-001", {"archived": True})
        b, _ = self.s.create("commandcenter", "two")
        self.assertEqual(b["key"], "CC-002")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("DELETE FROM tickets WHERE key='CC-001'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("UPDATE task_projects SET next_number=1 WHERE key='commandcenter'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("UPDATE tickets SET key='CC-009' WHERE key='CC-001'")

    def test_an_imported_id_is_kept_and_the_counter_moves_past_it(self):
        t, _ = self.s.create("samvision", "kept", number=56)
        self.assertEqual(t["key"], "SV-056")
        nxt, _ = self.s.create("samvision", "next")
        self.assertEqual(nxt["key"], "SV-057")
        with self.assertRaises(TaskError):
            self.s.create("samvision", "clash", number=56)

    def test_a_config_prefix_that_contradicts_the_registry_is_refused(self):
        with self.assertRaises(registry.RegistryError):
            self.s.sync_projects([{"key": "samvision", "name": "x", "prefix": "XX"}])
        self.assertEqual({p["key"]: p["prefix"] for p in self.s.projects()}["samvision"], "SV")

    def test_an_unregistered_project_without_a_prefix_can_hold_no_tickets(self):
        with self.assertRaises(registry.RegistryError):
            self.s.sync_projects([{"key": "someday", "name": "Someday"}])
        self.assertNotIn("someday", [p["key"] for p in self.s.projects()])

    def test_survives_a_restart(self):
        self.s.create("commandcenter", "durable")
        self.s.close()
        self.s = TaskStore(self.path, PROJECTS)
        self.assertEqual(self.s.get("CC-001")["title"], "durable")
        self.assertEqual(self.s.create("commandcenter", "after")[0]["key"], "CC-002")


class Fields(Base):
    def setUp(self):
        super().setUp()
        self.s.create("commandcenter", "ticket")

    def test_only_project_and_title_are_required(self):
        t = self.s.get("CC-001")
        self.assertEqual((t["status"], t["priority"], t["assignee"], t["flags"]), ("INBOX", "NO_PRIORITY", None, []))
        with self.assertRaises(TaskError):
            self.s.create("commandcenter", "  ")
        with self.assertRaises(TaskError):
            self.s.create("nope", "x")

    def test_validation(self):
        for bad in ({"status": "WAT"}, {"priority": "P0"}, {"type": "NOPE"}, {"assignee": "bob"},
                    {"labels": ["Has Space"]}, {"title": "a\x1b[2J"}, {"nonsense": 1}, {"agentRole": "BOSS"}):
            with self.assertRaises(TaskError, msg=str(bad)):
                self.s.update("CC-001", bad)

    def test_status_sets_started_and_completed(self):
        t, _ = self.s.update("CC-001", {"status": "IN_PROGRESS"})
        self.assertIsNotNone(t["startedAt"])
        self.assertIsNone(t["completedAt"])
        t, _ = self.s.update("CC-001", {"status": "DONE"})
        self.assertIsNotNone(t["completedAt"])
        t, _ = self.s.update("CC-001", {"status": "IN_REVIEW"})
        self.assertIsNone(t["completedAt"])

    def test_assignees_human_role_agent(self):
        for a in ("jay", "role:IMPLEMENTER", "agent:samvision", None):
            t, _ = self.s.update("CC-001", {"assignee": a})
            self.assertEqual(t["assignee"], a)

    def test_description_keeps_newlines(self):
        t, _ = self.s.update("CC-001", {"description": "line one\nline two\n\t- item"})
        self.assertIn("\n\t- item", t["description"])


class Audit(Base):
    def test_every_mutation_is_one_event_and_noops_write_nothing(self):
        self.s.create("commandcenter", "a")
        self.s.create("commandcenter", "b")
        self.s.update("CC-001", {"title": "a2", "description": "d", "status": "PROPOSED", "priority": "HIGH",
                                 "assignee": "jay", "needs_jay": True, "branch": "cc/a", "labels": ["ui"]})
        self.s.update("CC-001", {"status": "PROPOSED", "priority": "HIGH"})  # no-op
        self.s.relate("CC-001", "blocks", "CC-002")
        self.s.link("CC-001", "github", "pr", "o/r#5", "https://github.com/o/r/pull/5")
        self.s.link("CC-001", "github", "pr", "o/r#5")  # idempotent
        self.s.comment("CC-001", "a note")
        kinds = self.kinds("CC-001")
        self.assertEqual(kinds, ["created", "updated", "updated", "updated", "status", "updated", "assigned", "flag",
                                 "label_added", "relation_added", "linked", "commented"])
        self.assertIn("relation_added", self.kinds("CC-002"))

    def test_last_status_event_carries_the_trigger(self):
        self.s.create("commandcenter", "a")
        self.assertIsNone(self.s.last_status_event("CC-001"))
        self.s.update("CC-001", {"status": "PROPOSED"}, "jay")
        self.assertEqual(self.s.last_status_event("CC-001"),
                         {"actor": "jay", "from": "INBOX", "to": "PROPOSED", "trigger": None})
        self.s.update("CC-001", {"status": "READY_TO_IMPLEMENT"}, "system:automation", trigger="because")
        last = self.s.last_status_event("CC-001")
        self.assertEqual((last["actor"], last["trigger"]), ("system:automation", "because"))

    def test_history_rebuilds_the_status(self):
        self.s.create("commandcenter", "a")
        for st in ("PROPOSED", "READY_TO_IMPLEMENT", "IN_PROGRESS", "BLOCKED", "IN_PROGRESS"):
            self.s.update("CC-001", {"status": st})
        ev = [e for e in self.s.get("CC-001")["timeline"] if e["field"] == "status"]
        rebuilt = "INBOX"
        for e in ev:
            self.assertEqual(e["from"], rebuilt)
            rebuilt = e["to"]
        self.assertEqual(rebuilt, self.s.get("CC-001")["status"])

    def test_audit_is_append_only(self):
        self.s.create("commandcenter", "a")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("DELETE FROM ticket_events")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.db.execute("UPDATE ticket_events SET actor='x'")

    def test_automatic_changes_carry_their_trigger(self):
        self.s.create("commandcenter", "a")
        self.s.update("CC-001", {"status": "IN_REVIEW"}, "system:automation", trigger="PR #5 is open")
        e = self.s.get("CC-001")["timeline"][-1]
        self.assertEqual((e["actor"], e["trigger"]), ("system:automation", "PR #5 is open"))


class Relations(Base):
    def setUp(self):
        super().setUp()
        for t in ("parent", "child", "other", "dup"):
            self.s.create("commandcenter", t)

    def test_parent_and_subtasks(self):
        self.s.update("CC-002", {"parent": "CC-001"})
        p = self.s.get("CC-001")
        self.assertEqual([x["key"] for x in p["subtaskList"]], ["CC-002"])
        self.assertEqual(self.s.get("CC-002")["parent"], "CC-001")
        with self.assertRaises(TaskError):
            self.s.update("CC-001", {"parent": "CC-002"})  # loop
        with self.assertRaises(TaskError):
            self.s.update("CC-001", {"parent": "CC-001"})

    def test_blocks_and_blocked_by_are_one_edge(self):
        self.s.relate("CC-001", "blocked_by", "CC-003")
        self.assertEqual(self.s.get("CC-001")["blockedBy"], ["CC-003"])
        self.assertEqual(self.s.get("CC-003")["blocks"], ["CC-001"])
        with self.assertRaises(TaskError):
            self.s.relate("CC-001", "blocks", "CC-003")  # the reverse edge
        self.s.relate("CC-003", "blocks", "CC-001", remove=True)
        self.assertEqual(self.s.get("CC-001")["blockedBy"], [])

    def test_related_is_symmetric_and_duplicates_directional(self):
        self.s.relate("CC-003", "related", "CC-001")
        _, changed = self.s.relate("CC-001", "related", "CC-003")
        self.assertFalse(changed)
        self.s.relate("CC-004", "duplicates", "CC-001")
        self.assertEqual([x["key"] for x in self.s.get("CC-001")["relations"]["duplicated_by"]], ["CC-004"])

    def test_list_carries_relations_and_pr(self):
        self.s.relate("CC-001", "blocked_by", "CC-003")
        self.s.link("CC-001", "github", "pr", "o/r#12", "https://x")
        row = next(t for t in self.s.list() if t["key"] == "CC-001")
        self.assertEqual((row["blockedBy"], row["prNumber"]), (["CC-003"], 12))
        self.assertNotIn("description", row)


class NeedsJay(Base):
    def test_flags_feed_the_queue_until_closed(self):
        self.s.create("commandcenter", "a")
        self.s.create("samvision", "b")
        self.s.update("CC-001", {"needs_jay": True})
        self.s.update("SV-001", {"flags": {"needs_legal": True, "needs_deploy": True}})
        needs = {n["ref"]: n["flags"] for n in self.s.needs()}
        self.assertEqual(needs, {"CC-001": ["needs_jay"], "SV-001": ["needs_legal", "needs_deploy"]})
        self.s.update("CC-001", {"status": "DONE"})
        self.s.update("SV-001", {"archived": True})
        self.assertEqual(self.s.needs(), [])


class KeysInText(Base):
    def test_find_keys(self):
        # GM is GauzeMate's retired prefix, so GM-009 is still a key; GZ is the live one.
        self.assertEqual(self.s.find_keys("SV-56: fix; branch cc-12-thing GM-9 GZ-4 XX-1 GYST-VN-9 SV-0056"),
                         ["SV-056", "GM-009", "GZ-004"])  # case-sensitive: cc-12 is not a key


class Migrations(unittest.TestCase):
    def test_fresh_database_lands_on_the_latest_version(self):
        s = TaskStore(tmpdb(), PROJECTS)
        self.assertEqual(s.db.execute("PRAGMA user_version").fetchone()[0], tasks.SCHEMA_VERSION)
        self.assertEqual(s.applied, [v for v, _ in tasks.MIGRATIONS])
        s.close()

    def test_reopening_applies_nothing(self):
        path = tmpdb()
        TaskStore(path, PROJECTS).close()
        s = TaskStore(path, PROJECTS)
        self.assertEqual(s.applied, [])
        s.close()

    def test_a_newer_database_is_refused(self):
        path = tmpdb()
        db = sqlite3.connect(path)
        db.execute(f"PRAGMA user_version = {tasks.SCHEMA_VERSION + 1}")
        db.close()
        with self.assertRaises(RuntimeError):
            TaskStore(path, PROJECTS)

    def test_a_failed_migration_leaves_the_old_version(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        saved = tasks.MIGRATIONS[:]
        tasks.MIGRATIONS.append((99, "CREATE TABLE ok_one(x); THIS IS NOT SQL;"))
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                tasks.migrate(db)
        finally:
            tasks.MIGRATIONS[:] = saved
        db.execute("ROLLBACK") if db.in_transaction else None
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], tasks.SCHEMA_VERSION)
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='ok_one'").fetchone())


class ImportPreview(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-")
        os.makedirs(os.path.join(self.root, "docs", "tasks"))
        os.makedirs(os.path.join(self.root, "docs", "jay"))
        with open(os.path.join(self.root, "docs", "tasks", "INDEX.md"), "w") as f:
            f.write("| ID | Task | Priority | Status | Dependency | PR | Last |\n|---|---|---|---|---|---|---|\n"
                    "| SV-001 | Done thing | P0 | DONE | — | #38 | x |\n"
                    "| SV-014 | Legal thing | P0 | BLOCKED | legal answer | — | x |\n"
                    "| SV-056 | Verifying | P1 | VERIFYING (drill pending, needs Jay) | SV-001 | #88 | x |\n"
                    "| SV-060 | Weird | P2 | MAYBE | — | — | x |\n")
        with open(os.path.join(self.root, "docs", "jay", "MY_ACTIONS.md"), "w") as f:
            f.write("- [ ] SV-056 · run the drill · docs/x.md\n- [ ] Mileage · fix a trip · https://x\n- [x] SV-001 · done\n")
        self.projects = [{"key": "samvision", "name": "SamVision", "repo": "o/sv", "path": self.root,
                          "index": "docs/tasks/INDEX.md", "actions": "docs/jay/MY_ACTIONS.md"}]
        self.gh = {"samvision": {"issues": [
            {"number": 7, "title": "SV-014 — legal thing", "url": "https://i/7", "labels": [{"name": "needs:legal"}]},
            {"number": 8, "title": "Brand new bug", "url": "https://i/8", "labels": [{"name": "bug"},
                                                                                     {"name": "priority:p1"}]},
        ]}}
        self.s = TaskStore(tmpdb(), PROJECTS)
        self.handoff = tempfile.mkdtemp()
        open(os.path.join(self.handoff, "samvision.md"), "w").write("notes")

    def preview(self):
        return importer.preview(self.projects, self.gh, self.s, self.handoff)

    def test_preview_sorts_everything_and_writes_nothing(self):
        before = self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        pv = self.preview()
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], before)
        self.assertFalse(pv["applied"])
        created = {c["proposedKey"]: c for c in pv["wouldCreate"]}
        self.assertEqual(set(created), {"SV-001", "SV-014", "SV-056", "SV-061", "SV-062"})
        self.assertEqual(created["SV-001"]["status"], "DONE")  # history is not dropped
        self.assertEqual(created["SV-014"]["flags"], ["needs_legal"])
        self.assertEqual(created["SV-056"]["flags"], ["needs_jay"])
        self.assertEqual(created["SV-056"]["priority"], "HIGH")
        self.assertEqual(created["SV-056"]["blockedBy"], ["SV-001"])
        self.assertEqual(created["SV-061"]["title"], "Brand new bug")
        self.assertEqual((created["SV-061"]["type"], created["SV-061"]["priority"]), ("BUG", "HIGH"))
        self.assertEqual(created["SV-062"]["type"], "OWNER_ACTION")
        self.assertEqual([a["ref"] for a in pv["ambiguous"]], ["SV-060"])
        self.assertEqual({d["key"] for d in pv["duplicates"]}, {"SV-014", "SV-056"})
        self.assertIn("handoff", {s["source"] for s in pv["skipped"]})

    def test_second_preview_after_import_shows_updates_not_creates(self):
        self.s.create("samvision", "Legal thing", number=14, status="BLOCKED")
        pv = self.preview()
        self.assertNotIn("SV-014", {c["proposedKey"] for c in pv["wouldCreate"]})
        upd = {u["key"]: u for u in pv["wouldUpdate"]}
        self.assertIn("SV-014", upd)
        self.assertIn("needs_legal", {c["field"] for c in upd["SV-014"]["changes"]})


if __name__ == "__main__":
    unittest.main()
