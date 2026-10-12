"""Workstation: real terminals, search, source control, explorer operations, race hardening."""
import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from starlette.websockets import WebSocketDisconnect

from ccd import attachments as attach_mod
from ccd import gitops, search, security
from ccd import pty as pty_mod
from ccd.files import FileError, Roots

from .test_api import AUTH, HOST, JSON, PORT, TOKEN, ApiBase

DEV_SECRET = "d" * 43
ORIGIN = f"http://127.0.0.1:{PORT}"


def git(root, *a):
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                   capture_output=True)


def make_repo():
    base = tempfile.mkdtemp(prefix="ws2-")
    root = os.path.join(base, "repo")
    os.makedirs(os.path.join(root, "src"))
    with open(os.path.join(root, "src", "a.py"), "w") as f:
        f.write("def needle():\n    return 1\n")
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write("# readme needle\n")
    os.makedirs(os.path.join(root, "node_modules", "x"))
    with open(os.path.join(root, "node_modules", "x", "i.js"), "w") as f:
        f.write("needle\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return base, root


# ---------- terminals ----------

class PtyUnit(unittest.TestCase):
    def test_session_names_resolve_only_through_the_registry(self):
        roots = {"SV": tempfile.mkdtemp()}
        self.assertEqual(pty_mod.session_cwd("repo:SV", roots), os.path.realpath(roots["SV"]))
        self.assertEqual(pty_mod.session_cwd("server", roots, home="/home/x"), "/home/x")
        for bad in ("repo:XX", "repo:../etc", "repo:", "/etc", "bash", "repo:SV/../..", "", None):
            with self.assertRaises(pty_mod.PtyError, msg=repr(bad)):
                pty_mod.session_cwd(bad, roots)

    def test_lifecycle_detach_keeps_running_close_kills_only_that_session(self):
        async def run():
            events = []
            roots = {"SV": tempfile.mkdtemp(), "GZ": tempfile.mkdtemp()}
            m = pty_mod.PtyManager(audit=lambda k, t, d: events.append((k, json.dumps(d))), roots=roots,
                                   shell="/bin/sh")
            a, created = await m.open("repo:SV", 100, 30)
            b, _ = await m.open("repo:GZ")
            self.assertTrue(created)
            self.assertIs((await m.open("repo:SV"))[0], a)  # one shell per name
            c, _ = m.attach(a)
            m.write(a, b"echo $PWD; echo hi-$((20+22))\n")
            out = b""
            deadline = time.monotonic() + 5
            while b"hi-42" not in out and time.monotonic() < deadline:
                try:
                    out += await asyncio.wait_for(c.queue.get(), 1) or b""
                except asyncio.TimeoutError:
                    pass
            self.assertIn(b"hi-42", out)
            self.assertIn(os.path.realpath(roots["SV"]).encode(), out)
            m.detach(a, c)  # the browser went away
            await asyncio.sleep(0.2)
            self.assertIn("repo:SV", m.sessions)  # still running
            os.kill(a.pid, 0)
            c2, replay = m.attach(a)
            self.assertIn(b"hi-42", replay)  # reconnect replays the ring buffer
            m.resize(a, 120, 40)
            await m.close("repo:SV")
            self.assertNotIn("repo:SV", m.sessions)
            with self.assertRaises(ProcessLookupError):
                os.kill(a.pid, 0)
            self.assertIn("repo:GZ", m.sessions)  # the other session is untouched
            os.kill(b.pid, 0)
            await m.close_all()
            kinds = [k for k, _ in events]
            for k in ("pty.session.created", "pty.attached", "pty.detached", "pty.session.closed"):
                self.assertIn(k, kinds)
            self.assertFalse(any("hi-42" in d or "echo" in d for _, d in events))  # never input or output
        asyncio.run(run())

    def test_slow_client_is_dropped_not_the_shell_and_ring_is_bounded(self):
        async def run():
            m = pty_mod.PtyManager(roots={"SV": tempfile.mkdtemp()}, shell="/bin/sh")
            s, _ = await m.open("repo:SV")
            asyncio.get_running_loop().remove_reader(s.fd)  # drive output by hand below
            c, _ = m.attach(s)
            c.queue = asyncio.Queue(1)
            c.queue.put_nowait(b"unread")
            r, w = os.pipe()
            real_fd, s.fd = s.fd, r
            for _ in range(6):  # > RING_BYTES of output with a viewer that never reads
                os.write(w, b"y" * 60000)
                m._on_output(s)
            s.fd = real_fd
            os.close(r)
            os.close(w)
            self.assertTrue(c.lost)
            self.assertLessEqual(len(s.ring), pty_mod.RING_BYTES)
            self.assertIn("repo:SV", m.sessions)  # the shell was never stalled or killed
            await m.close_all()
        asyncio.run(run())

    def test_input_limits(self):
        async def run():
            m = pty_mod.PtyManager(roots={"SV": tempfile.mkdtemp()}, shell="/bin/sh")
            s, _ = await m.open("repo:SV")
            with self.assertRaises(pty_mod.PtyError):
                m.write(s, b"x" * (pty_mod.INPUT_MAX + 1))
            await m.close_all()
        asyncio.run(run())


class _Fixture(ApiBase):
    def equip(self, daemon):
        self.base, self.root = make_repo()
        daemon.files = Roots({"samvision": self.root}, upload_max=4096)
        daemon.attachments = attach_mod.Attachments(os.path.join(self.base, "att.db"),
                                                    os.path.join(self.base, "blobs"), 4096)
        daemon.dev_gate = security.DeveloperGate(DEV_SECRET)
        daemon.search = search.Search(daemon.files)
        daemon.scm = gitops.SourceControl(daemon.files)
        daemon.ptys = pty_mod.PtyManager(roots={"SV": self.root}, home=self.base, shell="/bin/sh",
                                         audit=lambda k, t, d: daemon._event("pty", k, t, data=d))

    def tearDown(self):
        for s in list(self.daemon.ptys.sessions.values()):
            try:
                os.killpg(s.pid, 9)
            except ProcessLookupError:
                pass
        super().tearDown()
        self.daemon.attachments.close()
        shutil.rmtree(self.base)

    def dev(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV_SECRET}), headers=JSON)
        return r.json()["session"]



class PtyApi(_Fixture):
    def connect(self, name, protocols, headers=None):
        h = dict(HOST, origin=ORIGIN)
        h.update(headers or {})
        return self.client.websocket_connect(f"/api/pty/{name}?cols=80&rows=24", subprotocols=protocols, headers=h)

    def refused(self, name, protocols, headers=None):
        with self.assertRaises(WebSocketDisconnect) as e:
            with self.connect(name, protocols, headers) as ws:
                ws.receive_text()  # raises on close, whether ccd refused before or after accept
        return e.exception.code

    def test_ccd_token_alone_cannot_open_a_terminal(self):
        self.assertEqual(self.refused("server", ["ccd.v1", f"ccd-token.{TOKEN}"]), 4403)
        self.assertEqual(self.refused("server", ["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{TOKEN}"]), 4403)
        self.assertEqual(self.daemon.ptys.sessions, {})

    def test_claude_terminal_needs_the_same_gates(self):
        self.assertEqual(self.refused("claude:SV", ["ccd.v1", f"ccd-token.{TOKEN}"]), 4403)
        sid = self.dev()
        p = ["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{sid}"]
        self.assertEqual(self.refused("claude:SV", p, {"origin": "http://evil.example"}), 4403)
        self.assertEqual(self.refused("claude:SV", p, {"host": "evil.example:7777"}), 4403)
        self.assertEqual(self.refused("claude:XX", p), 4404)
        self.assertNotIn("claude:SV", self.daemon.ptys.sessions)

    def test_expired_developer_session_is_told_after_accept(self):
        # A close before accept reaches a browser as a failed handshake (1006); past the Guard, ccd
        # accepts first so the tab sees 4403 "Developer Unlock required" and can ask Jay to unlock.
        with self.connect("server", ["ccd.v1", f"ccd-token.{TOKEN}", "ccd-dev.gone"]) as ws:
            with self.assertRaises(WebSocketDisconnect) as e:
                ws.receive_text()
        self.assertEqual((e.exception.code, e.exception.reason), (4403, "Developer Unlock required"))
        sid = self.dev()
        with self.connect("claude:XX", ["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{sid}"]) as ws:
            with self.assertRaises(WebSocketDisconnect) as e:
                ws.receive_text()
        self.assertEqual(e.exception.code, 4404)
        self.assertEqual(self.daemon.ptys.sessions, {})

    def test_guard_failures_are_refused_before_accept(self):
        sid = self.dev()
        for protocols, headers in ((["ccd.v1", f"ccd-dev.{sid}"], None),
                                   (["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{sid}"], {"origin": "http://evil.example"})):
            with self.assertRaises(WebSocketDisconnect):
                self.connect("server", protocols, headers).__enter__()

    def test_developer_session_without_ccd_token_refused(self):
        sid = self.dev()
        self.assertEqual(self.refused("server", ["ccd.v1", f"ccd-dev.{sid}"]), 4401)

    def test_wrong_origin_host_and_missing_origin_refused(self):
        sid = self.dev()
        p = ["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{sid}"]
        self.assertEqual(self.refused("server", p, {"origin": "http://evil.example"}), 4403)
        self.assertEqual(self.refused("server", p, {"host": "evil.example:7777"}), 4403)
        with self.assertRaises(WebSocketDisconnect) as e:
            with self.client.websocket_connect("/api/pty/server", subprotocols=p, headers=HOST) as ws:
                ws.receive()
        self.assertEqual(e.exception.code, 4403)
        self.assertEqual(self.daemon.ptys.sessions, {})

    def test_arbitrary_cwd_and_unregistered_projects_refused(self):
        sid = self.dev()
        p = ["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{sid}"]
        for name, code in (("repo:XX", 4404), ("bash", 4400), ("repo:..", 4400), ("repo:SV-999", 4404),
                           ("codex:..", 4400), ("codex:../x", None), ("%2Fetc", None)):
            got = self.refused(name, p)
            if code is None:
                self.assertIn(got, (1000, 4400, 4404), name)  # no such route: never a shell
            else:
                self.assertEqual(got, code, name)
        self.assertEqual(self.daemon.ptys.sessions, {})

    def test_terminal_round_trip_disconnect_and_explicit_close(self):
        sid = self.dev()
        p = ["ccd.v1", f"ccd-token.{TOKEN}", f"ccd-dev.{sid}"]
        def pane_writes():
            return [c for c in self.fake.calls if c[0] in ("pane.send_text", "pane.send_keys", "agent.prompt",
                                                            "pane.close", "pane.split", "agent.focus")]
        herdr_writes_before = len(pane_writes())
        with self.connect("repo:SV", p) as ws:
            hello = ws.receive_json()
            self.assertEqual((hello["t"], hello["cwd"]), ("hello", os.path.realpath(self.root)))
            ws.send_text(json.dumps({"t": "r", "c": 100, "r": 30}))
            ws.send_text(json.dumps({"t": "i", "d": "echo got-$((6*7))\n"}))
            out = b""
            deadline = time.monotonic() + 5
            while b"got-42" not in out and time.monotonic() < deadline:
                m = ws.receive()
                out += m.get("bytes") or b""
            self.assertIn(b"got-42", out)
        # browser gone: the shell lives on
        time.sleep(0.3)
        s = self.daemon.ptys.sessions.get("repo:SV")
        self.assertIsNotNone(s)
        os.kill(s.pid, 0)
        listed = self.get("/api/pty").json()["sessions"]
        self.assertEqual([x["name"] for x in listed], ["repo:SV"])
        # ordinary token cannot close it
        self.assertEqual(self.client.post("/api/pty/close", content='{"name":"repo:SV"}', headers=JSON).status_code, 403)
        dev = dict(JSON, **{"x-ccd-developer": sid})
        r = self.client.post("/api/pty/close", content='{"name":"repo:SV"}', headers=dev)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("repo:SV", self.daemon.ptys.sessions)
        self.assertEqual(len(pane_writes()), herdr_writes_before)  # no herdr pane or agent was touched
        kinds = [e["kind"] for e in self.get("/api/activity?limit=50").json()["events"]]
        self.assertIn("pty.session.created", kinds)
        self.assertIn("pty.session.closed", kinds)
        text = self.get("/api/activity?limit=50").text
        self.assertNotIn("got-", text)


# ---------- search, source control, explorer ----------

class Workstation(_Fixture):
    def devh(self):
        return dict(JSON, **{"x-ccd-developer": self.dev()})

    def post(self, path, body, headers=None):
        return self.client.post(path, content=json.dumps(body), headers=headers or JSON)

    def test_search_files_and_text_exclude_noise_and_secrets(self):
        with open(os.path.join(self.root, "secret.pem"), "w") as f:
            f.write("needle\n")
        r0 = self.get("/api/search/files?project=samvision")
        self.assertEqual(r0.status_code, 200, r0.text)
        files = r0.json()["files"]
        self.assertIn("src/a.py", files)
        self.assertFalse([f for f in files if f.startswith("node_modules") or f.startswith(".git/") or f.endswith(".pem")])
        r = self.get("/api/search/text?project=samvision&q=needle").json()
        paths = {m["path"] for m in r["matches"]}
        self.assertEqual(paths, {"src/a.py", "README.md"})
        self.assertEqual(self.get("/api/search/text?project=samvision&q=").status_code, 400)
        self.assertEqual(self.get("/api/search/text?project=/etc&q=x").status_code, 404)

    def test_source_control_status_diff_stage_commit_branch(self):
        with open(os.path.join(self.root, "src", "a.py"), "a") as f:
            f.write("# changed\n")
        with open(os.path.join(self.root, "new.txt"), "w") as f:
            f.write("new\n")
        st = self.get("/api/scm/status?project=samvision").json()
        self.assertEqual(st["branch"]["head"], "main")
        self.assertEqual([r["path"] for r in st["unstaged"]], ["src/a.py"])
        self.assertEqual([r["path"] for r in st["untracked"]], ["new.txt"])
        d = self.get("/api/scm/diff?project=samvision&path=src/a.py").json()
        self.assertIn("+# changed", d["diff"])
        self.assertIn("+new", self.get("/api/scm/diff?project=samvision&path=new.txt").json()["diff"])
        self.assertEqual(self.get("/api/scm/diff?project=samvision&path=../x").status_code, 400)
        # ordinary token cannot stage
        self.assertEqual(self.post("/api/scm/stage", {"project": "samvision", "paths": ["new.txt"]}).status_code, 403)
        h = self.devh()
        self.assertEqual(self.post("/api/scm/stage-all", {"project": "samvision"}, h).status_code, 200)
        st = self.get("/api/scm/status?project=samvision").json()
        self.assertEqual(sorted(r["path"] for r in st["staged"]), ["new.txt", "src/a.py"])
        self.assertEqual(self.post("/api/scm/unstage", {"project": "samvision", "paths": ["new.txt"]}, h).status_code, 200)
        r = self.post("/api/scm/commit", {"project": "samvision", "message": "m", "files": ["new.txt", "src/a.py"]}, h)
        self.assertEqual(r.status_code, 409)  # what Jay saw is not what is staged
        r = self.post("/api/scm/commit", {"project": "samvision", "message": "", "files": ["src/a.py"]}, h)
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/scm/commit", {"project": "samvision", "message": "change a", "files": ["src/a.py"]}, h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.post("/api/scm/discard", {"project": "samvision", "path": "new.txt"}, h).status_code, 400)
        self.assertEqual(self.post("/api/scm/discard", {"project": "samvision", "path": "new.txt", "confirm": True},
                                   h).status_code, 200)
        self.assertFalse(os.path.exists(os.path.join(self.root, "new.txt")))
        t = self.client.post("/api/tasks", content=json.dumps({"project": "samvision", "title": "Valuation view!"}),
                             headers=JSON).json()
        sug = self.get(f"/api/scm/ticket-branch?ticket={t['key']}").json()
        self.assertEqual(sug["suggested"], f"{t['key']}-valuation-view")
        for bad in ("-x", "a..b", "a b", "x.lock", ""):
            self.assertEqual(self.post("/api/scm/branch", {"project": "samvision", "name": bad}, h).status_code, 400, bad)
        r = self.post("/api/scm/branch", {"project": "samvision", "name": sug["suggested"], "ticket": t["key"]}, h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.get("/api/scm/status?project=samvision").json()["branch"]["head"], sug["suggested"])
        self.assertEqual(self.get(f"/api/tasks/{t['key']}").json()["branch"], sug["suggested"])
        self.assertEqual(self.post("/api/scm/branch", {"project": "samvision", "name": sug["suggested"]}, h).status_code, 409)

    def test_stage_all_never_sweeps_in_secret_files(self):
        with open(os.path.join(self.root, "server.pem"), "w") as f:
            f.write("k\n")
        with open(os.path.join(self.root, "ok.txt"), "w") as f:
            f.write("k\n")
        self.post("/api/scm/stage-all", {"project": "samvision"}, self.devh())
        staged = [r["path"] for r in self.get("/api/scm/status?project=samvision").json()["staged"]]
        self.assertEqual(staged, ["ok.txt"])
        self.assertEqual(self.get("/api/scm/diff?project=samvision&path=server.pem").status_code, 403)

    def test_explorer_operations(self):
        h = self.devh()
        self.assertEqual(self.post("/api/files/mkdir", {"project": "samvision", "dir": "src", "name": "pkg"}).status_code, 403)
        self.assertEqual(self.post("/api/files/mkdir", {"project": "samvision", "dir": "src", "name": "pkg"}, h).status_code, 200)
        self.assertEqual(self.post("/api/files/mkdir", {"project": "samvision", "dir": "src", "name": "pkg"}, h).status_code, 409)
        self.assertEqual(self.post("/api/files/mkdir", {"project": "samvision", "dir": "", "name": ".git"}, h).status_code, 403)
        r = self.post("/api/files/duplicate", {"project": "samvision", "path": "src/a.py"}, h)
        self.assertEqual(r.json()["name"], "a copy.py")
        self.assertEqual(self.post("/api/files/rename", {"project": "samvision", "path": "src/a copy.py", "name": "b.py"}, h).status_code, 200)
        self.assertEqual(self.post("/api/files/rename", {"project": "samvision", "path": "src/b.py", "name": "a.py"}, h).status_code, 409)
        self.assertEqual(self.post("/api/files/rename", {"project": "samvision", "path": "src/b.py", "name": "../b.py"}, h).status_code, 400)
        self.assertEqual(self.post("/api/files/remove", {"project": "samvision", "path": "src/b.py"}, h).status_code, 200)
        self.assertFalse(os.path.exists(os.path.join(self.root, "src", "b.py")))
        os.makedirs(os.path.join(self.root, "keep", ".ssh"))
        self.assertEqual(self.post("/api/files/remove", {"project": "samvision", "path": "keep"}, h).status_code, 403)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "keep", ".ssh")))
        self.assertEqual(self.post("/api/files/remove", {"project": "samvision", "path": ".git"}, h).status_code, 403)
        self.assertEqual(self.post("/api/files/remove", {"project": "samvision", "path": ""}, h).status_code, 400)
        outside = os.path.join(self.base, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "victim"), "w") as f:
            f.write("x")
        os.symlink(outside, os.path.join(self.root, "link"))
        self.assertEqual(self.post("/api/files/remove", {"project": "samvision", "path": "link/victim"}, h).status_code, 403)
        self.assertEqual(self.post("/api/files/remove", {"project": "samvision", "path": "link"}, h).status_code, 200)
        self.assertTrue(os.path.exists(os.path.join(outside, "victim")))  # the link went, never its target


class RaceHardening(unittest.TestCase):
    """A folder swapped for a symlink AFTER validation must not let a write escape the root."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="race-")
        self.root = os.path.join(self.base, "repo")
        self.outside = os.path.join(self.base, "outside")
        os.makedirs(os.path.join(self.root, "sub"))
        os.makedirs(self.outside)
        self.r = Roots({"p": self.root})
        real_resolve = self.r.resolve

        def racing_resolve(*a, **kw):
            out = real_resolve(*a, **kw)
            sub = os.path.join(self.root, "sub")
            if os.path.isdir(sub) and not os.path.islink(sub):
                shutil.rmtree(sub)
                os.symlink(self.outside, sub)  # the attacker's swap, between check and use
            return out
        self.r.resolve = racing_resolve

    def tearDown(self):
        shutil.rmtree(self.base)

    def test_save_cannot_follow_a_swapped_folder(self):
        with self.assertRaises(FileError) as e:
            self.r.save("p", "sub/x.txt", "pwned", None)
        self.assertEqual(e.exception.status, 403)
        self.assertEqual(os.listdir(self.outside), [])

    def test_upload_cannot_follow_a_swapped_folder(self):
        async def chunks():
            yield b"pwned"
        with self.assertRaises(FileError):
            asyncio.run(self.r.upload("p", "sub", "x.txt", chunks()))
        self.assertEqual(os.listdir(self.outside), [])

    def test_mkdir_and_remove_cannot_follow_a_swapped_folder(self):
        with self.assertRaises(FileError):
            self.r.mkdir("p", "sub", "d")
        os.makedirs(os.path.join(self.outside, "victim"))
        shutil.rmtree(os.path.join(self.root, "sub")) if not os.path.islink(os.path.join(self.root, "sub")) else \
            os.unlink(os.path.join(self.root, "sub"))
        os.makedirs(os.path.join(self.root, "sub"))
        with self.assertRaises(FileError):
            self.r.delete("p", "sub/victim")
        self.assertTrue(os.path.isdir(os.path.join(self.outside, "victim")))


class SecurityFixes(_Fixture):
    def test_regex_search_without_ripgrep_is_refused_and_plain_search_is_linear(self):
        if search._rg():
            self.skipTest("ripgrep installed: regex runs in a killable subprocess")
        r = self.get("/api/search/text?project=samvision&q=(a%7Ca)*b&regex=1")
        self.assertEqual(r.status_code, 400)
        with open(os.path.join(self.root, "long.txt"), "w") as f:
            f.write("a" * 2_000_000 + "\n")
        t0 = time.monotonic()
        r = self.get("/api/search/text?project=samvision&q=aaaa")
        self.assertEqual(r.status_code, 200)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertLessEqual(len(r.json()["matches"][0]["ranges"]), 10)

    def test_source_control_refuses_folders(self):
        os.makedirs(os.path.join(self.root, "conf"))
        with open(os.path.join(self.root, "conf", "secrets.json"), "w") as f:
            f.write("{}")
        self.assertEqual(self.get("/api/scm/diff?project=samvision&path=conf").status_code, 400)
        h = dict(JSON, **{"x-ccd-developer": self.dev()})
        r = self.client.post("/api/scm/stage", content=json.dumps({"project": "samvision", "paths": ["conf"]}), headers=h)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.get("/api/scm/status?project=samvision").json()["staged"], [])


class PtyFdIsolation(unittest.TestCase):
    def test_a_shell_never_inherits_another_terminals_master(self):
        async def run():
            m = pty_mod.PtyManager(roots={"SV": tempfile.mkdtemp(), "GZ": tempfile.mkdtemp()}, shell="/bin/sh")
            a, _ = await m.open("repo:SV")
            b, _ = await m.open("repo:GZ")
            def fds():
                out = {}
                for x in os.listdir(f"/proc/{b.pid}/fd"):
                    with contextlib.suppress(FileNotFoundError):   # closed between listdir and readlink
                        out[x] = os.readlink(f"/proc/{b.pid}/fd/{x}")
                return out

            def extra(links):
                return [v for k, v in links.items() if int(k) > 2 and not (v.startswith("/dev/pts/") or v == "/dev/tty")]

            # The login shell holds /etc/profile open while it sources it, so poll until that is done
            # rather than guess a delay. A leaked master never closes, so it still fails below.
            deadline = time.monotonic() + 10
            links = fds()
            while extra(links) and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
                links = fds()
            # its own tty (/dev/pts/N) may appear more than once (dash keeps a copy); a master never may
            self.assertFalse([v for v in links.values() if "ptmx" in v], links)
            self.assertFalse(extra(links), links)
            self.assertFalse(os.get_inheritable(a.fd))
            await m.close_all()
        asyncio.run(run())


class DeletedFolderSecrets(_Fixture):
    def test_a_deleted_tracked_folder_is_still_a_folder(self):
        os.makedirs(os.path.join(self.root, "conf"))
        with open(os.path.join(self.root, "conf", "secrets.json"), "w") as f:
            f.write('{"k": "TOPSECRET"}')
        with open(os.path.join(self.root, "conf", "a.txt"), "w") as f:
            f.write("a")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "conf")
        shutil.rmtree(os.path.join(self.root, "conf"))
        r = self.get("/api/scm/diff?project=samvision&path=conf")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("TOPSECRET", r.text)
        git(self.root, "rm", "-r", "-q", "--cached", "conf")
        r = self.get("/api/scm/diff?project=samvision&path=conf&staged=1")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("TOPSECRET", r.text)
        h = dict(JSON, **{"x-ccd-developer": self.dev()})
        for op, body in (("stage", {"paths": ["conf"]}), ("unstage", {"paths": ["conf"]}),
                         ("discard", {"path": "conf", "confirm": True})):
            r = self.client.post(f"/api/scm/{op}", content=json.dumps({"project": "samvision", **body}), headers=h)
            self.assertEqual(r.status_code, 400, op)
        # a single deleted file is still fine
        self.assertEqual(self.get("/api/scm/diff?project=samvision&path=README.md").status_code, 200)


class CoordinatorAdopt(_Fixture):
    """Workspace → Claude → Adopt: binds an EXISTING Claude; Developer only; touches no pane."""
    GYST = "/srv/server/repos/gyst-lifeops"

    def setUp(self):
        from ccd import coordid
        coordid.BINDINGS.unlink(missing_ok=True)
        super().setUp()

    def state(self, key):
        p = next(x for x in self.get("/api/workspace/projects").json()["projects"] if x["key"] == key)
        return p["coordinatorState"], p["coordinator"]

    def test_renamed_claude_is_found_then_adopted_and_survives_a_rename(self):
        from ccd import coordid
        self.fake.add_agent("w9:p1", self.GYST)               # title "x": not canonical
        self.settle()
        st, coord = self.state("gyst")
        self.assertEqual(st["state"], "found")
        self.assertIsNone(coord)
        self.assertEqual([c["sessionId"] for c in st["candidates"]], ["s-w9:p1"])
        self.assertNotIn("title", json.dumps(st))             # titles never leave the daemon
        writes = lambda: [c for c in self.fake.calls if c[0] in (  # noqa: E731
            "pane.send_text", "pane.send_keys", "agent.prompt", "agent.rename", "pane.close", "pane.split")]
        before = len(writes())
        body = json.dumps({"project": "gyst", "sessionId": "s-w9:p1"})
        self.assertEqual(self.client.post("/api/coordinators/adopt", content=body, headers=JSON).status_code, 403)
        dev = dict(JSON, **{"x-ccd-developer": self.dev()})
        for bad in ({"project": "gyst", "sessionId": "s-wE:p2"}, {"project": "gyst", "sessionId": "nope nope"},
                    {"project": "nope", "sessionId": "s-w9:p1"}, {"project": "gyst"}):
            self.assertIn(self.client.post("/api/coordinators/adopt", content=json.dumps(bad), headers=dev).status_code,
                          (404, 409), bad)
            time.sleep(2.1)                                    # adopt is throttled per project
        r = self.client.post("/api/coordinators/adopt", content=body, headers=dev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["coordinator"]["state"], r.json()["coordinator"]["paneId"]), ("ready", "w9:p1"))
        self.settle()
        st, coord = self.state("gyst")
        self.assertEqual((st["state"], st["how"], coord["id"]), ("ready", "binding", "w9:p1"))
        self.assertEqual(coordid.load()["gyst"]["sessionId"], "s-w9:p1")
        self.assertEqual(len(writes()), before)                # nothing typed, renamed or started
        kinds = [e["kind"] for e in self.get("/api/activity?limit=50").json()["events"]]
        self.assertIn("action.adopt", kinds)
