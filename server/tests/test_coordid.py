"""The one coordinator resolver (ccd/coordid.py): identity is never the title alone."""
import os
import tempfile
import unittest
from pathlib import Path

from ccd import coordid

SV, GZ, MFE, GYST, CC = ("/srv/x/samvisionai", "/srv/x/GauzeMate", "/srv/x/MyFamilyExpenses",
                         "/srv/x/gyst-lifeops", "/srv/x/CommandCenter")


def agent(pane, sid, cwd, title="Claude Code", name=None, kind="claude", status="idle"):
    a = {"agent": kind, "pane_id": pane, "agent_session": {"value": sid}, "cwd": cwd,
         "terminal_title_stripped": title, "agent_status": status}
    if name:
        a["name"] = name
    return a


S1, S2, S3, S4, S5 = ("ae9345c7-8e20-474f-9d2a-de7c3828a8dc", "76230988-02a9-4cea-bf4c-1367f75972bb",
                      "4de6de1b-3cc5-4846-9382-3f5a361bec11", "94dd2aad-791e-4e06-987d-ef236f0c078a",
                      "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0")
# Tonight's real shapes: SV and GZ titled canonically, GYST and MFE renamed by Claude.
LIVE = [agent("wE:p2", S1, SV, "samvision"), agent("wE:p4", S2, GZ, "gauzemate"),
        agent("w9:p1", S3, GYST, "Where did we stop last"), agent("wA:p1", S4, MFE, "Claude Code")]


class Resolve(unittest.TestCase):
    def test_canonical_titles_still_resolve(self):
        r = coordid.resolve("samvision", SV, LIVE)
        self.assertEqual((r["state"], r["paneId"], r["how"]), ("ready", "wE:p2", "title"))
        self.assertEqual(coordid.resolve("gauzemate", GZ, LIVE)["paneId"], "wE:p4")

    def test_renamed_conversation_is_offered_for_adoption_not_called_missing(self):
        for key, root, sid in (("gyst", GYST, S3), ("mfe", MFE, S4)):
            r = coordid.resolve(key, root, LIVE)
            self.assertEqual(r["state"], "found", key)
            self.assertIsNone(r["paneId"])             # never attached on cwd alone
            self.assertEqual(r["sessionId"], sid)

    def test_renamed_conversation_resolves_once_bound(self):
        r = coordid.resolve("gyst", GYST, LIVE, {"sessionId": S3})
        self.assertEqual((r["state"], r["paneId"], r["how"]), ("ready", "w9:p1", "binding"))
        renamed = [agent("w9:p1", S3, GYST, "Something else entirely")]
        self.assertEqual(coordid.resolve("gyst", GYST, renamed, {"sessionId": S3})["paneId"], "w9:p1")

    def test_new_pane_same_session_follows_the_session(self):
        moved = [agent("wF:p7", S3, GYST, "Where did we stop last")]
        r = coordid.resolve("gyst", GYST, moved, {"sessionId": S3, "paneId": "w9:p1"})
        self.assertEqual((r["state"], r["paneId"]), ("ready", "wF:p7"))

    def test_reused_pane_id_with_another_session_never_matches(self):
        reused = [agent("w9:p1", S5, "/tmp", "Where did we stop last")]
        r = coordid.resolve("gyst", GYST, reused, {"sessionId": S3, "paneId": "w9:p1"})
        self.assertEqual(r["state"], "none")
        self.assertTrue(r["staleBinding"])

    def test_stale_binding_falls_back_to_discovery(self):
        r = coordid.resolve("samvision", SV, LIVE, {"sessionId": S5})
        self.assertTrue(r["staleBinding"])
        self.assertEqual((r["state"], r["paneId"], r["how"]), ("ready", "wE:p2", "title"))

    def test_multiple_sessions_in_one_repo_require_a_choice(self):
        two = LIVE + [agent("wB:p1", S5, GZ, "Claude Code")]
        self.assertEqual(coordid.resolve("gauzemate", GZ, two)["paneId"], "wE:p4")   # the named one wins
        both_unnamed = [agent("wA:p1", S4, MFE), agent("wB:p1", S5, MFE)]
        r = coordid.resolve("mfe", MFE, both_unnamed)
        self.assertEqual(r["state"], "multiple")
        self.assertEqual({c["sessionId"] for c in r["candidates"]}, {S4, S5})
        two_titled = [agent("wE:p2", S1, SV, "samvision"), agent("wF:p1", S5, SV, "samvision")]
        self.assertEqual(coordid.resolve("samvision", SV, two_titled)["state"], "multiple")

    def test_cwd_only_is_the_exact_root_never_a_subdirectory_or_worktree(self):
        sub = [agent("wA:p1", S4, MFE + "/web"), agent("wB:p1", S5, "/srv/server/worktrees/MFE/lane")]
        self.assertEqual(coordid.resolve("mfe", MFE, sub)["state"], "none")
        titled_elsewhere = [agent("wE:p2", S1, "/tmp", "samvision")]
        self.assertEqual(coordid.resolve("samvision", SV, titled_elsewhere)["state"], "none")

    def test_a_lane_that_moved_into_a_worktree_is_not_at_the_root(self):
        lane = dict(agent("wE:p2", S5, SV, "Implementing SV-056"), foreground_cwd="/srv/server/worktrees/sv/SV-056")
        self.assertEqual(coordid.resolve("samvision", SV, [lane, LIVE[0]])["paneId"], "wE:p2")
        self.assertEqual(coordid.resolve("samvision", SV, [lane])["state"], "none")

    def test_herdr_label_or_agent_name_resolves(self):
        named = [agent("wA:p1", S4, MFE, "Claude Code", name="mfe")]
        r = coordid.resolve("mfe", MFE, named)
        self.assertEqual((r["state"], r["how"]), ("ready", "label"))
        labelled = [dict(agent("w9:p1", S3, GYST, "x"), label="gyst")]
        self.assertEqual(coordid.resolve("gyst", GYST, labelled)["how"], "label")

    def test_command_center_answers_to_command_center(self):
        self.assertEqual(coordid.canonical_name("commandcenter"), "command-center")
        cc = [agent("wC:p1", S5, CC, "command-center")]
        self.assertEqual(coordid.resolve("commandcenter", CC, cc)["paneId"], "wC:p1")

    def test_non_claude_and_malformed_rows_are_ignored(self):
        junk = [agent("wE:p2", S1, SV, "samvision", kind="codex"), agent("wE:p2;id", S1, SV, "samvision"),
                agent("wE:p3", "", SV, "samvision"), agent("wE:p4", "a b", SV, "samvision"),
                dict(agent("wE:p5", S1, SV, "samvision"), live=False)]
        self.assertEqual(coordid.resolve("samvision", SV, junk)["state"], "none")

    def test_pane_rows_from_the_snapshot_resolve_the_same_way(self):
        # sources.panes_from rows: title/agent_name/session_id/pane_cwd instead of herdr's names
        rows = [{"pane_id": "w9:p1", "agent": "claude", "session_id": S3, "title": "Where did we stop last",
                 "cwd": GYST, "status": "idle", "live": True}]
        self.assertEqual(coordid.resolve("gyst", GYST, rows, {"sessionId": S3})["paneId"], "w9:p1")


class Bindings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "coordinator-bindings.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_a_title_match_is_recorded_so_a_later_rename_cannot_break_it(self):
        coordid.resolve_and_record("samvision", SV, LIVE, path=self.path, now=1000)
        self.assertEqual(coordid.load(self.path)["samvision"]["sessionId"], S1)
        renamed = [agent("wE:p2", S1, SV, "Valuation work")]
        r = coordid.resolve_and_record("samvision", SV, renamed, path=self.path, now=1001)
        self.assertEqual((r["state"], r["how"]), ("ready", "binding"))

    def test_found_is_not_recorded_until_adopted(self):
        r = coordid.resolve_and_record("gyst", GYST, LIVE, path=self.path)
        self.assertEqual(r["state"], "found")
        self.assertNotIn("gyst", coordid.load(self.path))
        r = coordid.adopt("gyst", GYST, LIVE, S3, path=self.path)
        self.assertEqual((r["state"], r["paneId"]), ("ready", "w9:p1"))
        b = coordid.load(self.path)["gyst"]
        self.assertEqual((b["sessionId"], b["paneId"], b["canonical"], b["root"]), (S3, "w9:p1", "gyst", GYST))

    def test_adopt_only_binds_a_live_claude_at_the_root(self):
        for bad in (S1, S5, "x", None, "../../etc", S3 + "\n"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                coordid.adopt("gyst", GYST, LIVE, bad, path=self.path)
        self.assertEqual(coordid.load(self.path), {})

    def test_adopt_picks_one_of_multiple(self):
        both = [agent("wA:p1", S4, MFE), agent("wB:p1", S5, MFE)]
        r = coordid.adopt("mfe", MFE, both, S5, path=self.path)
        self.assertEqual(r["paneId"], "wB:p1")

    def test_verified_at_is_not_rewritten_every_poll(self):
        coordid.resolve_and_record("samvision", SV, LIVE, path=self.path, now=1000)
        mtime = os.stat(self.path).st_mtime_ns
        coordid.resolve_and_record("samvision", SV, LIVE, path=self.path, now=1100)
        self.assertEqual(os.stat(self.path).st_mtime_ns, mtime)
        coordid.resolve_and_record("samvision", SV, LIVE, path=self.path, now=1000 + coordid.REVERIFY_S + 1)
        self.assertEqual(coordid.load(self.path)["samvision"]["verifiedAt"], 1000 + coordid.REVERIFY_S + 1)

    def test_a_broken_file_is_just_no_bindings(self):
        self.path.write_text("{not json")
        self.assertEqual(coordid.load(self.path), {})
        self.assertEqual(coordid.resolve_and_record("gyst", GYST, LIVE, path=self.path)["state"], "found")


if __name__ == "__main__":
    unittest.main()
