"""Browser Claude terminal: a PTY running the shared helper `scripts/cc-terminal claude <PREFIX>`,
which attaches (`herdr agent attach <pane>`) to the EXISTING coordinator. Never a Claude process.

A fake `herdr` on PATH stands in for the real one: `agent list` returns coordinators, `agent attach`
echoes what it was given and then mirrors input, and a separate long-running process plays the
coordinator so the tests can prove closing/killing the attach side never touches it.
"""
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from ccd import pty as pty_mod
from ccd import registry

ROOTS = {k: os.path.realpath(p["root"]) for k, p in registry.PROJECTS.items()}
HAVE_ROOTS = all(os.path.isdir(r) for r in ROOTS.values())

FAKE_HERDR = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    agents = json.loads(os.environ["FAKE_AGENTS"])
    if sys.argv[1:3] == ["agent", "list"]:
        print(json.dumps({"result": {"agents": agents}}))
    elif sys.argv[1:3] == ["agent", "attach"]:
        print("ATTACHED " + sys.argv[3], flush=True)
        for line in sys.stdin:
            print("CLAUDE-GOT " + line.strip(), flush=True)
    else:
        print("unexpected " + " ".join(sys.argv[1:]), flush=True)
        sys.exit(9)
''')


def agent(pane, title, root, session):
    return {"agent": "claude", "pane_id": pane, "terminal_title_stripped": title, "cwd": root,
            "agent_session": {"value": session}}


@unittest.skipUnless(HAVE_ROOTS, "needs the registered checkouts (jay-server)")
class ClaudeAttachPty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="claudepty-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "herdr"), "w") as f:
            f.write(FAKE_HERDR)
        os.chmod(os.path.join(self.bin, "herdr"), 0o755)
        # The "coordinator": a process the attach side must never touch.
        self.coordinator = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        self.agents = [agent("wE:p2", "samvision", ROOTS["samvision"], "sess-sv"),
                       agent("wE:p4", "gauzemate", ROOTS["gauzemate"], "sess-gz")]

    def tearDown(self):
        self.coordinator.kill()
        self.coordinator.wait()
        shutil.rmtree(self.tmp)

    def manager(self, agents=None):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_AGENTS": json.dumps(self.agents if agents is None else agents)}
        m = pty_mod.PtyManager(env=env, shell="/bin/sh")
        # FAKE_AGENTS must reach the helper: _child_env keeps only a fixed list, so extend it here.
        orig = m._child_env
        m._child_env = lambda cwd: {**orig(cwd), "FAKE_AGENTS": env["FAKE_AGENTS"]}
        return m

    async def read_until(self, client, needle, seconds=6):
        out = b""
        deadline = time.monotonic() + seconds
        while needle not in out and time.monotonic() < deadline:
            try:
                chunk = await asyncio.wait_for(client.queue.get(), 0.5)
            except asyncio.TimeoutError:
                continue
            if chunk is None:
                break
            out += chunk
        return out

    def test_sv_and_gz_attach_to_their_existing_coordinators(self):
        async def run():
            m = self.manager()
            for name, pane in (("claude:SV", b"wE:p2"), ("claude:GZ", b"wE:p4")):
                s, created = await m.open(name)
                self.assertTrue(created)
                self.assertEqual(s.cwd, ROOTS["samvision" if name.endswith("SV") else "gauzemate"])
                c, _ = m.attach(s)
                out = await self.read_until(c, b"ATTACHED")
                self.assertIn(b"ATTACHED " + pane, out)
            await m.close_all()
        asyncio.run(run())

    def test_input_reaches_the_attached_terminal_and_resize_works(self):
        async def run():
            m = self.manager()
            s, _ = await m.open("claude:SV", 100, 30)
            c, _ = m.attach(s)
            await self.read_until(c, b"ATTACHED")
            m.resize(s, 132, 40)
            m.write(s, b"Reply exactly: CANARY\n")
            out = await self.read_until(c, b"CLAUDE-GOT")
            self.assertIn(b"CLAUDE-GOT Reply exactly: CANARY", out)
            await m.close_all()
        asyncio.run(run())

    def test_disconnect_reconnect_and_close_never_touch_the_coordinator(self):
        async def run():
            m = self.manager()
            s, _ = await m.open("claude:SV")
            c, _ = m.attach(s)
            await self.read_until(c, b"ATTACHED")
            m.detach(s, c)                                  # browser closed
            await asyncio.sleep(0.3)
            self.assertIn("claude:SV", m.sessions)          # the attach client is still there
            c2, replay = m.attach(s)                        # browser came back
            self.assertIn(b"ATTACHED wE:p2", replay)
            self.assertIs((await m.open("claude:SV"))[0], s)  # one attach client per project, shared
            await m.close("claude:SV")                      # CLOSE CLAUDE TERMINAL
            self.assertNotIn("claude:SV", m.sessions)
            self.assertIsNone(self.coordinator.poll())      # Claude itself untouched
            os.kill(self.coordinator.pid, 0)
        asyncio.run(run())

    def test_no_coordinator_or_ambiguous_refuses_and_starts_nothing(self):
        async def run():
            for agents, needle in (([], b"no running"),
                                   (self.agents + [agent("wF:p1", "samvision", ROOTS["samvision"], "x")], b"refusing to guess")):
                m = self.manager(agents)
                s, _ = await m.open("claude:SV")
                c, _ = m.attach(s)
                out = await self.read_until(c, needle)
                self.assertIn(needle, out)
                self.assertNotIn(b"ATTACHED", out)
                await m.close_all()
            m = self.manager()
            s, _ = await m.open("claude:MFE")                # MFE has no coordinator
            c, _ = m.attach(s)
            self.assertIn(b"no running mfe coordinator", await self.read_until(c, b"no running"))
            await m.close_all()
        asyncio.run(run())

    def test_the_browser_cannot_name_a_pane_command_or_path(self):
        for bad in ("claude:wE:p2", "claude:sv", "claude:XX", "claude:../x", "claude:SV;id", "claude:SV claude",
                    "claude:", "claude", "herdr agent attach wE:p2", "claude:GM"):
            with self.assertRaises(pty_mod.PtyError, msg=bad):
                pty_mod.session_cwd(bad)

    def test_the_spawned_command_is_the_shared_helper_and_nothing_else(self):
        m = pty_mod.PtyManager(shell="/bin/sh")
        seen = {}

        def fake_forkpty():
            raise RuntimeError("stop")
        real = os.forkpty
        try:
            os.forkpty = fake_forkpty
            orig_env = m._child_env

            def spy(cwd):
                seen["cwd"] = cwd
                return orig_env(cwd)
            m._child_env = spy
            with self.assertRaises(RuntimeError):
                m._spawn("claude:SV", ROOTS["samvision"], 80, 24)
        finally:
            os.forkpty = real
        self.assertTrue(m.cc_terminal.endswith(os.path.join("scripts", "cc-terminal")))
        self.assertTrue(os.access(m.cc_terminal, os.X_OK))
        self.assertEqual(seen["cwd"], ROOTS["samvision"])
