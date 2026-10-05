"""scripts/cc-terminal: the server half of the native Windows Terminal actions."""
import importlib.machinery
import importlib.util
import os
import unittest

from ccd import registry

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "cc-terminal")
_loader = importlib.machinery.SourceFileLoader("cc_terminal", _PATH)
_spec = importlib.util.spec_from_loader("cc_terminal", _loader)
cct = importlib.util.module_from_spec(_spec)
_loader.exec_module(cct)


def agent(pane, title, cwd, kind="claude", sid=None):
    sid = sid or f"{abs(hash((pane, title, cwd))):016x}-session"
    return {"agent": kind, "pane_id": pane, "terminal_title_stripped": title, "cwd": cwd, "agent_session": {"value": sid}}


ROOTS = {k: os.path.realpath(p["root"]) for k, p in registry.PROJECTS.items()}
LIVE = [agent("wE:p2", "samvision", ROOTS["samvision"]), agent("wE:p4", "gauzemate", ROOTS["gauzemate"]),
        agent("wB:p1", "Claude Code", ROOTS["gauzemate"]), agent("wA:p1", "Claude Code", ROOTS["mfe"])]


@unittest.skipUnless(all(os.path.isdir(r) for r in ROOTS.values()), "needs the registered checkouts (jay-server)")
class Plan(unittest.TestCase):
    def setUp(self):
        # each test starts with no recorded coordinator bindings
        from ccd import coordid
        coordid.BINDINGS.unlink(missing_ok=True)

    def plan(self, *argv, agents=LIVE):
        return cct.plan(list(argv), agents_fn=lambda: agents)

    def test_renamed_coordinator_needs_adoption_then_attaches_whatever_its_title(self):
        from ccd import coordid
        gyst = agent("w9:p1", "Where did we stop last", ROOTS["gyst"], sid="4de6de1b-3cc5-4846-9382-3f5a361bec11")
        with self.assertRaisesRegex(cct.Refused, "Adopt it in Command Center"):
            self.plan("claude", "GYST", agents=LIVE + [gyst])
        coordid.adopt("gyst", ROOTS["gyst"], LIVE + [gyst], "4de6de1b-3cc5-4846-9382-3f5a361bec11")
        self.assertEqual(self.plan("claude", "GYST", agents=LIVE + [gyst])[1], ["herdr", "agent", "attach", "w9:p1"])
        renamed = dict(gyst, terminal_title_stripped="Health v3 night shift", pane_id="wF:p3")
        self.assertEqual(self.plan("claude", "GYST", agents=LIVE + [renamed])[1], ["herdr", "agent", "attach", "wF:p3"])

    def test_browser_and_native_use_the_same_resolver_as_ccd(self):
        from ccd import coordid
        for prefix, key in (("SV", "samvision"), ("GZ", "gauzemate")):
            r = coordid.resolve(key, ROOTS[key], LIVE)
            self.assertEqual(self.plan("claude", prefix)[1][-1], r["paneId"])

    def test_repo_paths_come_from_the_registry(self):
        for prefix, key in (("SV", "samvision"), ("GZ", "gauzemate"), ("MFE", "mfe"), ("CC", "commandcenter"),
                            ("GYST", "gyst")):
            exe, args, cwd, title = self.plan("repo", prefix)
            self.assertEqual(cwd, ROOTS[key])
            self.assertEqual(args[1:], ["-l"])
            self.assertTrue(title.startswith("Repo — "))
        self.assertEqual(self.plan("repo", "SV")[2], "/srv/server/apps/samvisionai")

    def test_claude_attaches_to_the_existing_coordinator(self):
        self.assertEqual(self.plan("claude", "SV")[1], ["herdr", "agent", "attach", "wE:p2"])
        self.assertEqual(self.plan("claude", "GZ")[1], ["herdr", "agent", "attach", "wE:p4"])
        self.assertNotIn("start", self.plan("claude", "SV")[1])

    def test_no_coordinator_is_an_error_never_a_new_session(self):
        with self.assertRaises(cct.Refused):
            self.plan("claude", "MFE")
        with self.assertRaises(cct.Refused):
            self.plan("claude", "SV", agents=[])
        with self.assertRaisesRegex(cct.Refused, "choose one"):  # two candidates: never guess
            self.plan("claude", "SV", agents=LIVE + [agent("wF:p1", "samvision", ROOTS["samvision"])])
        with self.assertRaises(cct.Refused):  # right title, wrong cwd
            self.plan("claude", "SV", agents=[agent("wE:p2", "samvision", "/tmp")])
        with self.assertRaises(cct.Refused):  # malformed pane id
            self.plan("claude", "SV", agents=[agent("wE:p2;id", "samvision", ROOTS["samvision"])])

    def test_everything_else_is_refused(self):
        for argv in ([], ["repo"], ["shell", "SV"], ["repo", "SV", "x"], ["repo", "sv"], ["repo", "XX"],
                     ["repo", "SV;id"], ["repo", "../etc"], ["repo", "/etc"], ["repo", "GM"], ["claude", "$(id)"],
                     ["server", "SV"], ["repo", "SV\n"]):
            with self.assertRaises(cct.Refused, msg=repr(argv)):
                self.plan(*argv)


class HerdrPathIsAbsolute(unittest.TestCase):
    def test_a_relative_path_entry_is_made_absolute_so_exec_after_chdir_works(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "bin"))
            exe = os.path.join(d, "bin", "herdr")
            with open(exe, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(exe, 0o755)
            old = os.getcwd()
            os.chdir(d)
            try:
                with mock.patch.dict(os.environ, {"PATH": "bin"}):
                    loader = importlib.machinery.SourceFileLoader("cc_terminal_rel", _PATH)
                    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("cc_terminal_rel", loader))
                    loader.exec_module(mod)
            finally:
                os.chdir(old)
            self.assertTrue(os.path.isabs(mod.HERDR))
            self.assertEqual(os.path.realpath(mod.HERDR), os.path.realpath(exe))
