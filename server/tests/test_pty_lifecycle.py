"""PTY session lifecycle (CC-010): the scope is stopped on every end path, a closing session is
never handed back, an older grace timer cannot release early. Fake /bin/sh shells; systemd is
never involved (own_scope cannot be exercised here), so _stop_scope is checked by mocking the
subprocess call and asserting the exact argv."""
import asyncio
import os
import signal
import tempfile
import time
import unittest
from unittest import mock

from ccd import pty as pty_mod


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: os.rmdir(self.tmp))

    def manager(self):
        return pty_mod.PtyManager(roots={"TT": self.tmp}, home=self.tmp, shell="/bin/sh",
                                  env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})

    async def until(self, cond, secs=5):
        end = time.monotonic() + secs
        while not cond() and time.monotonic() < end:
            await asyncio.sleep(0.05)
        self.assertTrue(cond())

    def test_stop_scope_runs_exactly_systemctl_user_stop_no_block_for_its_own_unit(self):
        async def run():
            m = self.manager()
            s, _ = await m.open("repo:TT")
            s.unit = "cc-pty-repo-TT-abc123"
            calls = []

            class P:
                async def wait(self): return 0

            async def fake(*argv, **kw):
                calls.append(argv)
                return P()
            with mock.patch("asyncio.create_subprocess_exec", fake):
                await m._stop_scope(s)
                await m._stop_scope(s)  # idempotent: one stop per session
            self.assertEqual(calls, [("systemctl", "--user", "stop", "--no-block", "cc-pty-repo-TT-abc123.scope")])
            s.unit = None
            await m.close_all()
        asyncio.run(run())

    def test_stop_scope_without_a_unit_runs_nothing(self):
        async def run():
            m = self.manager()
            s, _ = await m.open("repo:TT")
            with mock.patch("asyncio.create_subprocess_exec", side_effect=AssertionError("must not run")):
                await m._stop_scope(s)
            await m.close_all()
        asyncio.run(run())

    def test_stop_scope_timeout_kills_and_reaps_the_systemctl_child(self):
        async def run():
            m = self.manager()
            s, _ = await m.open("repo:TT")
            s.unit = "cc-pty-repo-TT-dead00"
            ev = {"killed": False, "waits": 0}

            class P:
                def kill(self): ev["killed"] = True
                async def wait(self):
                    ev["waits"] += 1
                    if not ev["killed"]:
                        await asyncio.sleep(60)
                    return -9

            async def fake(*a, **k): return P()
            real_wait_for = asyncio.wait_for

            async def quick(aw, timeout):
                return await real_wait_for(aw, 0.1 if timeout == 5 else timeout)
            with mock.patch("asyncio.create_subprocess_exec", fake), mock.patch("asyncio.wait_for", quick):
                await m._stop_scope(s)
            self.assertTrue(ev["killed"])
            self.assertEqual(ev["waits"], 2)  # waited, killed, waited again (reaped)
            s.unit = None
            await m.close_all()
        asyncio.run(run())

    def test_a_shell_that_exits_by_itself_stops_its_scope(self):
        async def run():
            m = self.manager()
            stopped = []

            async def rec(s): stopped.append(s.name)
            m._stop_scope = rec
            s, _ = await m.open("repo:TT")
            s.unit = "cc-pty-repo-TT-x"
            m.write(s, b"exit\n")
            await self.until(lambda: s.ended)
            await self.until(lambda: stopped)
            self.assertEqual(stopped, ["repo:TT"])
        asyncio.run(run())

    def test_explicit_close_stops_the_scope_once(self):
        async def run():
            m = self.manager()
            s, _ = await m.open("repo:TT")
            s.unit = "cc-pty-repo-TT-y"
            calls = []

            class P:
                async def wait(self): return 0

            async def fake(*argv, **kw):
                calls.append(argv)
                return P()
            with mock.patch("asyncio.create_subprocess_exec", fake):
                await m.close("repo:TT")
                await asyncio.sleep(0.2)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][-1], "cc-pty-repo-TT-y.scope")
        asyncio.run(run())

    def test_an_older_grace_timer_cannot_release_after_a_re_detach(self):
        async def run():
            m = self.manager()
            m.claude_grace = 10.0
            s, _ = await m.open("repo:TT")
            s.detached_at = time.time()        # a re-detach just now; the first detach's timer fires
            m._release_if_unwatched(s)
            await asyncio.sleep(0.2)
            self.assertFalse(s.ended)
            self.assertIsNone(s.closing)
            s.detached_at = time.time() - 11   # genuinely unwatched for the whole grace
            m._release_if_unwatched(s)
            await self.until(lambda: s.ended)
        asyncio.run(run())

    def test_open_never_returns_a_closing_session(self):
        async def run():
            m = self.manager()
            old, _ = await m.open("repo:TT")
            old.closing = "closed"
            asyncio.get_running_loop().call_later(0.3, m._ended, old)
            new, created = await m.open("repo:TT")
            self.assertTrue(created)
            self.assertIsNot(new, old)
            self.assertTrue(old.ended)
            try:
                os.killpg(old.pid, signal.SIGKILL)
                os.waitpid(old.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            await m.close_all()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
