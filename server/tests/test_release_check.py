"""ccd/release_check.py (CC-063): the alert-only release check. Fake clock, fake HTTP, fake systemctl: no sleeping."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ccd import release_check as rc

MODULE = Path(rc.__file__)
INDEX = b'<html><script src="/assets/app.js"></script><link href="/assets/app.css"></html>'


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class World:
    """What ccd looks like to the check; tests flip fields over time."""

    def __init__(self, clock, tmp):
        self.clock = clock
        self.new_dir = str(tmp)
        (tmp / "index.html").write_bytes(INDEX)
        self.api = (200, json.dumps({"pid": 500, "herdr": {"ok": True}}).encode())
        self.index = (200, INDEX)
        self.assets = {"/assets/app.js": 200, "/assets/app.css": 200}
        self.state = {"active": "active", "pid": 500, "restarts": 0}
        self.calls = []
        self.hang = False
        self.probe_cost = 0

    def http(self, method, path, headers, body, timeout):
        self.calls.append((method, path, timeout))
        if self.hang:
            self.clock.t += timeout
            return None, b""
        self.clock.t += self.probe_cost
        if path == "/api/health":
            return self.api
        if path == "/":
            return self.index
        return self.assets.get(path, 404), b""

    def unit(self, timeout=rc.REQ_BUDGET_S):
        self.calls.append(("systemctl", "show", timeout))
        if self.hang:
            self.clock.t += timeout
            return None
        self.clock.t += self.probe_cost
        return dict(self.state) if self.state else None

    def check(self, **kw):
        return rc.Check(http=self.http, unit=self.unit, new_dir=self.new_dir, clock=self.clock,
                        sleep=self.clock.sleep, **kw)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc-test-", dir=os.environ.get("TMPDIR")))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.clock = Clock()
        self.w = World(self.clock, self.tmp)

    def test_c1_healthy_after_grace_and_window_sampling_every_10s(self):
        chk = self.w.check(old_pid=400, herdr_ok=True)
        result, bad = chk.run()
        self.assertEqual((result, bad), ("healthy", {}))
        self.assertEqual(chk.samples, 16)              # t=0,10,...,150
        self.assertEqual(self.clock.t - 1000.0, 150)   # grace 30 + window 120, no longer
        paths = {c[1] for c in self.w.calls}
        self.assertTrue({"/api/health", "/", "/assets/app.js", "/assets/app.css", "show"} <= paths)
        self.assertTrue(all(s == 10 for s in self.clock.slept))

    def failing(self, mutate):
        mutate(self.w)
        return self.w.check(old_pid=400, herdr_ok=True).run()

    def test_c6_each_failing_check_is_named(self):
        cases = {
            "api": lambda w: setattr(w, "api", (500, b"")),
            "ui": lambda w: w.assets.update({"/assets/app.js": 404}),
            "ui2": lambda w: setattr(w, "index", (200, b"<html>the old release</html>")),
            "daemon": lambda w: w.state.update(active="inactive"),
            "daemon2": lambda w: w.state.update(pid=501),                      # health.pid != MainPID
            "daemon3": lambda w: w.state.update(pid=400),                      # still the old process
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                self.setUp()
                result, bad = self.failing(mutate)
                self.assertEqual(result, "failed")
                self.assertIn(name.rstrip("23"), bad)
        self.setUp()
        result, bad = self.failing(lambda w: w.state.update(pid=400))
        self.assertIn("pre-restart process", bad["daemon"])

    def test_pid_a_missing_pid_never_passes_as_none_equals_none(self):
        # Codex r3: a unit with no MainPID and a health document with no pid used to pass
        for name, mutate in {
            "no MainPID, no health pid": lambda w: (w.state.update(pid=None),
                                                   setattr(w, "api", (200, json.dumps({"herdr": {"ok": True}}).encode()))),
            "MainPID 0": lambda w: w.state.update(pid=0),
            "health without pid": lambda w: setattr(w, "api", (200, json.dumps({"herdr": {"ok": True}}).encode())),
            "health pid not a number": lambda w: setattr(w, "api", (200, json.dumps({"pid": "500"}).encode())),
        }.items():
            with self.subTest(name):
                self.setUp()
                result, bad = self.failing(mutate)
                self.assertEqual(result, "failed")
                self.assertIn("daemon", bad)

    def test_pid_changing_between_samples_is_inconclusive_not_healthy(self):
        # Codex r3: each sample matched its own MainPID, so two processes added up to one healthy run
        orig_api = self.w.api
        n = {"i": 0}
        orig_unit = self.w.unit

        def hop(timeout=5):
            n["i"] += 1
            s = orig_unit(timeout)
            if s and n["i"] > 5:
                s["pid"] = 600
                self.w.api = (200, json.dumps({"pid": 600, "herdr": {"ok": True}}).encode())
            return s
        chk = rc.Check(http=self.w.http, unit=hop, new_dir=self.w.new_dir, clock=self.clock, sleep=self.clock.sleep)
        result, bad = chk.run()
        self.assertEqual(result, "inconclusive")
        self.assertIn("changed during the check", bad["daemon"])
        self.assertIsNotNone(orig_api)

    def test_c6_crash_names_every_failure_of_that_sample(self):
        # Codex r3: the crash branch dropped the api and ui failures found in the same sample
        self.w.state.update(restarts=1)
        self.w.api = (500, b"")
        self.w.index = (200, b"old")
        result, bad = self.w.check().run()
        self.assertEqual(result, "failed")
        self.assertEqual(set(bad), {"api", "daemon", "ui"})
        self.assertIn("crashed", bad["daemon"])

    def test_c6_crash_fails_at_once_even_in_grace(self):
        result, bad = self.failing(lambda w: w.state.update(restarts=1))
        self.assertEqual(result, "failed")
        self.assertIn("crashed", bad["daemon"])
        self.assertLess(self.clock.t - 1000.0, 1)        # first sample: the baseline is 0, not the first read

    def test_c6_bad_samples_in_grace_do_not_count(self):
        bads = {"n": 0}
        orig = self.w.http

        def flaky(method, path, headers, body, timeout):
            if path == "/api/health" and self.clock.t - 1000 < 29:   # ccd still starting
                bads["n"] += 1
                return 503, b""
            return orig(method, path, headers, body, timeout)
        chk = rc.Check(http=flaky, unit=self.w.unit, new_dir=self.w.new_dir, clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(chk.run()[0], "healthy")
        self.assertGreaterEqual(bads["n"], 3)

    def test_c6_one_bad_sample_after_grace_never_fails(self):
        orig = self.w.http
        n = {"i": 0}

        def blip(method, path, headers, body, timeout):
            if path == "/api/health":
                n["i"] += 1
                if n["i"] == 8:
                    return 500, b""
            return orig(method, path, headers, body, timeout)
        chk = rc.Check(http=blip, unit=self.w.unit, new_dir=self.w.new_dir, clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(chk.run()[0], "healthy")

    def test_c6_alternating_samples_end_inconclusive_at_the_hard_deadline(self):
        orig = self.w.http
        n = {"i": 0}

        def alternate(method, path, headers, body, timeout):
            if path == "/api/health":
                n["i"] += 1
                if n["i"] > 5 and n["i"] % 2 == 0:
                    return 500, b""
            return orig(method, path, headers, body, timeout)
        chk = rc.Check(http=alternate, unit=self.w.unit, new_dir=self.w.new_dir, clock=self.clock, sleep=self.clock.sleep)
        result, bad = chk.run()
        self.assertEqual(result, "inconclusive")
        self.assertLessEqual(self.clock.t - 1000.0, rc.GRACE_S + rc.WINDOW_S + rc.SLACK_S + 5)

    def test_api_and_ui_failing_are_both_named(self):
        self.w.api = (500, b"")
        self.w.index = (404, b"")
        result, bad = self.w.check().run()
        self.assertEqual(result, "failed")
        self.assertEqual(set(bad), {"api", "ui"})
        text = rc.alert_text(result, bad, "releases/x", "a" * 40, "STEPS")
        self.assertIn("api", text)
        self.assertIn("ui", text)

    def test_herdr_not_judged_unless_it_was_up_before(self):
        self.w.api = (200, json.dumps({"pid": 500, "herdr": {"ok": False}}).encode())
        self.assertEqual(self.w.check(herdr_ok=None).run()[0], "healthy")
        self.setUp()
        self.w.api = (200, json.dumps({"pid": 500, "herdr": {"ok": False}}).encode())
        self.assertEqual(self.w.check(herdr_ok=True).run()[0], "failed")

    def test_deadline_hanging_http_and_systemctl_end_by_the_hard_deadline(self):
        self.w.hang = True
        chk = self.w.check()
        result, _ = chk.run()
        self.assertIn(result, ("failed", "inconclusive"))
        # Codex r3: no overrun at all (it used to allow 15 s); systemctl is capped like every request
        self.assertLessEqual(self.clock.t - 1000.0, rc.GRACE_S + rc.WINDOW_S + rc.SLACK_S)
        self.assertTrue(all(c[2] <= rc.REQ_BUDGET_S for c in self.w.calls))

    def test_deadline_a_sample_running_into_it_is_never_healthy(self):
        # Codex r3: a sample starting at 8 s with a 9 s deadline returned healthy at 13 s
        self.w.probe_cost = 1                 # 5 probes = 5 s a sample; the 2nd sample ends past the deadline
        chk = self.w.check(grace=0, window=0, interval=0, slack=9)
        result, _ = chk.run()
        self.assertEqual(result, "inconclusive")
        self.assertLessEqual(self.clock.t - 1000.0, 9)

    def test_deadline_no_probe_starts_once_time_is_up(self):
        self.w.probe_cost = 1
        chk = self.w.check(grace=0, window=0, interval=0, slack=9)
        chk.run()
        self.assertTrue(all(c[2] > 0 for c in self.w.calls))
        self.assertLessEqual(len(self.w.calls), 10)

    def test_deadline_request_budget_shrinks_to_time_left(self):
        chk = self.w.check()
        chk.deadline = chk.start + 2
        self.assertAlmostEqual(chk.budget(), 2)


class AlertTest(unittest.TestCase):
    def test_notify_retries_three_times_then_gives_up(self):
        clock = Clock()
        calls = []
        ok = rc.notify(lambda t: calls.append(t) or False, "x", clock=clock, sleep=clock.sleep)
        self.assertFalse(ok)
        self.assertEqual(len(calls), 3)
        self.assertLessEqual(clock.t - 1000, rc.NOTIFY_WINDOW_S)

    def test_notify_never_retries_an_ambiguous_post(self):
        # Codex r3: a POST that timed out may be stored; each POST makes a new message, so a retry shows it twice
        calls = []
        self.assertFalse(rc.notify(lambda t: calls.append(t) or None, "x"))
        self.assertEqual(len(calls), 1)

    def test_post_only_a_refused_connection_counts_as_unsent(self):
        seen = {}

        def post_with(status):
            http = lambda m, path, h, b, t: (status, b"")      # noqa: E731
            tmp = Path(tempfile.mkdtemp(prefix="rc-post-", dir=os.environ.get("TMPDIR")))
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
            (tmp / "t").write_text("x\n")
            return rc.make_post(1, str(tmp / "t"), "c", http)("hi")
        seen["ok"], seen["refused"], seen["timeout"], seen["500"] = (post_with(200), post_with(rc.NOT_SENT),
                                                                      post_with(None), post_with(500))
        self.assertEqual(seen, {"ok": True, "refused": False, "timeout": None, "500": None})

    def test_append_log_writes_the_whole_line_after_short_writes(self):
        tmp = Path(tempfile.mkdtemp(prefix="rc-log-", dir=os.environ.get("TMPDIR")))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        real = os.write
        os.write = lambda fd, data: real(fd, bytes(data)[:3])
        try:
            rc.append_log(str(tmp / "l.jsonl"), {"result": "healthy", "x": "y" * 40})
        finally:
            os.write = real
        self.assertEqual(json.loads((tmp / "l.jsonl").read_text())["x"], "y" * 40)

    def test_append_log_raises_when_nothing_can_be_written(self):
        tmp = Path(tempfile.mkdtemp(prefix="rc-log-", dir=os.environ.get("TMPDIR")))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        real = os.write
        os.write = lambda fd, data: 0
        try:
            with self.assertRaises(OSError):
                rc.append_log(str(tmp / "l.jsonl"), {"a": 1})
        finally:
            os.write = real

    def test_notify_stops_at_first_success(self):
        calls = []
        self.assertTrue(rc.notify(lambda t: calls.append(t) or True, "x"))
        self.assertEqual(len(calls), 1)


class Loopback(threading.Thread):
    """A tiny HTTP server on 127.0.0.1 with a scripted behaviour per request."""

    def __init__(self, behave):
        super().__init__(daemon=True)
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(5)
        self.port = self.s.getsockname()[1]
        self.behave, self.requests = behave, []

    def run(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = c.recv(4096)
                if not chunk:
                    return
                data += chunk
            self.requests.append(data)
            self.behave(c, data)
        except OSError:
            pass
        finally:
            c.close()


class HttpTest(unittest.TestCase):
    def serve(self, behave):
        srv = Loopback(behave)
        srv.start()
        self.addCleanup(srv.s.close)
        return srv

    def test_plain_answer(self):
        srv = self.serve(lambda c, req: c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"))
        self.assertEqual(rc.loopback_http(srv.port, "GET", "/x", {}, None, 3), (200, b"hi"))

    def test_header_trickle_ends_within_the_budget(self):
        def trickle(c, req):
            for b in b"HTTP/1.1 200 OK\r\nX-A: " + b"a" * 50:
                c.sendall(bytes([b]))
                time.sleep(0.2)
        srv = self.serve(trickle)
        t0 = time.monotonic()
        self.assertEqual(rc.loopback_http(srv.port, "GET", "/x", {}, None, 1), (None, b""))
        self.assertLess(time.monotonic() - t0, 1.5)   # the budget, with no extra second after it (Codex r3)

    def test_body_trickle_ends_within_the_budget(self):
        def trickle(c, req):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n")
            for _ in range(500):
                c.sendall(b"a")
                time.sleep(0.2)
        srv = self.serve(trickle)
        t0 = time.monotonic()
        self.assertEqual(rc.loopback_http(srv.port, "GET", "/x", {}, None, 1), (None, b""))
        self.assertLess(time.monotonic() - t0, 3)

    def test_redirect_is_not_followed_and_proxy_env_is_ignored(self):
        srv = self.serve(lambda c, req: c.sendall(
            b"HTTP/1.1 302 Found\r\nLocation: http://203.0.113.1/\r\nContent-Length: 0\r\n\r\n"))
        old = os.environ.get("HTTP_PROXY")
        os.environ["HTTP_PROXY"] = "http://203.0.113.9:3128"
        self.addCleanup(lambda: os.environ.pop("HTTP_PROXY", None) if old is None else os.environ.update(HTTP_PROXY=old))
        status, _ = rc.loopback_http(srv.port, "GET", "/x", {}, None, 2)
        self.assertEqual(status, 302)
        self.assertEqual(len(srv.requests), 1)   # one request, to the loopback server only


class CliTest(unittest.TestCase):
    """The file as go-live runs it: python3 -I release_check.py, against a loopback fake ccd and a systemctl shim."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc-cli-", dir=os.environ.get("TMPDIR")))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.web = self.tmp / "rel"
        self.web.mkdir()
        (self.web / "index.html").write_bytes(INDEX)
        self.steps = self.tmp / "steps.txt"
        self.steps.write_text("Rollback: follow docs/runbooks/tasks-db-v10-rollback.md\n")
        self.token = self.tmp / "token"
        self.token.write_text("s3cret-token-value\n")
        self.log = self.tmp / "deploys" / "releases.jsonl"
        self.markers = self.tmp / "markers"
        shim = self.tmp / "bin"
        shim.mkdir()
        (shim / "systemctl").write_text(
            f'#!/bin/sh\necho "$@" >> "{self.markers}"\n'
            'printf "ActiveState=active\\nMainPID=500\\nNRestarts=0\\n"\n')
        (shim / "systemctl").chmod(0o755)
        self.shim = shim
        self.posts = []

    def fake_ccd(self, health_ok=True, accept_post=True, ui_ok=True, silent_post=False):
        def behave(c, req):
            line = req.split(b"\r\n", 1)[0]
            if line.startswith(b"POST"):
                self.posts.append(req)
                if silent_post:
                    return   # stored (or not) but never answered: the caller cannot know
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}" if accept_post
                          else b"HTTP/1.1 500 X\r\nContent-Length: 0\r\n\r\n")
                return
            if b"/api/health" in line:
                body = json.dumps({"pid": 500, "herdr": {"ok": True}}).encode()
                code = b"200 OK" if health_ok else b"500 X"
            elif line.startswith(b"GET / "):
                body, code = (INDEX, b"200 OK") if ui_ok else (b"old", b"200 OK")
            else:
                body, code = b"x", b"200 OK"
            c.sendall(b"HTTP/1.1 " + code + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        srv = Loopback(behave)
        srv.start()
        self.addCleanup(srv.s.close)
        return srv

    def run_cli(self, srv, extra=(), env=None):
        e = {"PATH": f"{self.shim}:{os.environ['PATH']}", "HOME": str(self.tmp)}
        e.update(env or {})
        return subprocess.run(
            [sys.executable, "-I", str(MODULE), "--port", str(srv.port), "--new-dir", str(self.web),
             "--steps-file", str(self.steps), "--log-file", str(self.log), "--token-file", str(self.token),
             "--from", "a" * 40, "--to", "b" * 40, "--web", "releases/20261101-bbbbbbb",
             "--prev-web", "releases/20261001-aaaaaaa", "--grace", "0", "--window", "1", "--interval", "1",
             "--slack", "3", *extra],
            capture_output=True, text=True, env=e, timeout=60)

    def test_c1_healthy_cli_writes_one_log_line_and_posts_nothing(self):
        srv = self.fake_ccd()
        r = self.run_cli(srv, ["--old-pid", "400"])
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "release check: healthy"), r.stderr)
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual((entry["result"], entry["notified"], entry["to"]), ("healthy", False, "b" * 40))
        self.assertEqual(self.posts, [])

    def test_c7_failed_check_posts_one_message_as_the_lead_with_steps(self):
        srv = self.fake_ccd(health_ok=False)
        r = self.run_cli(srv)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(len(self.posts), 1)
        post = self.posts[0]
        self.assertIn(b"POST /api/chat/commandcenter/messages", post)
        self.assertIn(b"X-CCD-Actor: agent:lead-commandcenter", post)
        body = json.loads(post.split(b"\r\n\r\n", 1)[1])["text"]
        self.assertIn("Release check FAILED", body)
        self.assertIn("api", body)
        self.assertIn("bbbbbbb", body)
        self.assertIn("docs/runbooks/tasks-db-v10-rollback.md", body)
        self.assertNotIn("git switch", body)
        self.assertEqual(body.strip(), r.stdout.split("\n(not sent")[0].strip())   # pane and Messages say the same
        entry = json.loads(self.log.read_text())
        self.assertEqual((entry["result"], entry["check"], entry["notified"]), ("failed", "api", True))

    def test_c7_ccd_down_prints_in_the_pane_and_logs_notified_false(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                       # nothing listens
        t0 = time.monotonic()
        r = self.run_cli(type("S", (), {"port": port}), ["--grace", "0"])
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertLess(time.monotonic() - t0, 60)
        self.assertIn("Release check FAILED", r.stdout)
        self.assertIn("docs/runbooks/tasks-db-v10-rollback.md", r.stdout)
        self.assertFalse(json.loads(self.log.read_text())["notified"])

    def test_dup_an_unanswered_post_is_not_retried(self):
        srv = self.fake_ccd(health_ok=False, silent_post=True)
        r = self.run_cli(srv)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(len(self.posts), 1)
        self.assertIn("not retried", r.stdout)
        self.assertFalse(json.loads(self.log.read_text())["notified"])

    def test_log_a_lost_log_line_is_not_a_pass(self):
        # Codex r3: a failed log append still printed healthy and exited 0, with no release record
        self.log.parent.mkdir(parents=True)
        self.log.mkdir()                       # the log path is a directory: the append cannot work
        r = self.run_cli(self.fake_ccd(), ["--old-pid", "400"])
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("do not record deployed as pass", r.stdout)
        self.assertIn("could not write the release log", r.stderr)

    def test_log_a_lost_log_line_keeps_the_alert_and_its_exit_code(self):
        self.log.parent.mkdir(parents=True)
        self.log.mkdir()
        r = self.run_cli(self.fake_ccd(health_ok=False))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("Release check FAILED", r.stdout)

    def test_c9_only_systemctl_show_runs_and_the_token_never_leaks(self):
        srv = self.fake_ccd(health_ok=False)
        r = self.run_cli(srv)
        for line in self.markers.read_text().splitlines():
            self.assertTrue(line.startswith("--user show ccd"), line)
        secret = "s3cret-token-value"
        self.assertNotIn(secret, r.stdout + r.stderr + self.log.read_text())

    def test_missing_steps_file_cannot_run(self):
        self.steps.unlink()
        r = self.run_cli(self.fake_ccd())
        self.assertEqual(r.returncode, 2)

    def test_c9_source_imports_no_ccd_module_and_uses_subprocess_in_one_place(self):
        src = MODULE.read_text()
        self.assertFalse(re.search(r"^\s*(from|import)\s+(\.|ccd)", src, re.M))
        calls = re.findall(r"subprocess\.run\(\[(.*?)\]", src, re.S)
        self.assertEqual(len(calls), 1)
        self.assertIn('"systemctl", "--user", "show", "ccd"', calls[0])
        for banned in ("restart", "stop", "start", "pip", "npm", "git", "tasks.db", "ln"):
            self.assertNotIn(f'"{banned}"', calls[0])


class GoLiveTemplateTest(unittest.TestCase):
    def test_other_projects_still_roll_back_by_their_runbook_unless_it_waits_for_jay(self):
        from ccd import daemon
        text = daemon.GO_LIVE_TEMPLATE.format(project="sv", approved="SV-1")
        self.assertIn("roll back by the runbook right away if one fails", text.replace("\n", " "))
        # only a runbook that says its check alerts and rollback waits for Jay changes that
        self.assertIn("EXCEPT when the runbook says its release check only alerts and rollback waits for Jay", text)
        self.assertIn("never roll back yourself", text)
        self.assertIn("deployed <KEY> --role coordinator", text)


if __name__ == "__main__":
    unittest.main()
