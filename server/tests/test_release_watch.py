"""CC-063: the release watch (server/ccd/release_watch.py) judges the release go-live.sh switched to and puts the
previous one back when it is bad.

Everything runs in temp directories against fakes: a fake systemctl/pip/migration_safety (Box.run), a fake ccd over
HTTP (Box.http, which enforces the same token rule as ccd), a virtual clock, and a REAL git repository so "HEAD is
detached at the previous commit" is checked against git itself. Nothing touches the live install, a real unit or the
real tasks.db. Box.forbidden collects any call a rollback must never make (fetch, deploy-web.sh, npm, pip download);
every test fails if it is not empty.
"""
import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ccd import release_watch as rw

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
TOKEN = "t" * 43
OLD_SCHEMA, NEW_SCHEMA = 14, 15


def git(cwd, *args, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


class Clock:
    """Virtual time: sleep() advances it and fires the events scheduled for the time passed."""

    def __init__(self):
        self.t, self.events = 0.0, []

    def now(self):
        return self.t

    def wall(self):
        return 1_790_000_000 + self.t

    def at(self, t, fn):
        self.events.append((t, fn))

    def sleep(self, s):
        self.t += s
        if self.t > 3 * 3600:      # a watch with no deadline must fail an assertion here, not spin for ever
            raise AssertionError("virtual time ran past 3 hours: the watch has no hard deadline")
        for ev in [e for e in self.events if e[0] <= self.t]:
            self.events.remove(ev)
            ev[1]()


class Box:
    """A throw-away "live install": git checkout, web releases, deploys dir, and the fake services around them."""

    def __init__(self, test):
        self.tmp = Path(tempfile.mkdtemp(prefix="release-watch-"))
        test.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.test = test
        self.clock = Clock()
        t = self.tmp
        self.repo = t / "repo"
        self.web = t / "web"
        self.data = t / "data"
        self.deploys = t / "deploys"
        self.watch = self.deploys / "watch" / "20261201T100000"
        self.token_file = t / "ccd.token"
        for d in (self.repo, self.web / "releases", self.data, self.watch):
            d.mkdir(parents=True)
        self.token_file.write_text(TOKEN + "\n")
        (self.data / "tasks.db").write_bytes(b"")
        # git: c1 is the previous release, c2 the new one (HEAD)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "server").mkdir()
        (self.repo / "server" / "requirements.txt").write_text("a==1\n")
        (self.repo / "clash.txt").write_text("tracked at c1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "c1")
        self.c1 = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "rm", "-q", "clash.txt")
        (self.repo / "server" / "requirements.txt").write_text("a==2\n")
        git(self.repo, "commit", "-q", "-am", "c2")
        self.c2 = git(self.repo, "rev-parse", "HEAD")
        self.schema_of = {self.c1: OLD_SCHEMA, self.c2: NEW_SCHEMA}
        # UI releases: current -> the new one
        self.old_web = self.release(f"20261101T000000Z-{self.c1[:7]}", "OLDOLD11")
        self.new_web = self.release(f"20261201T095500Z-{self.c2[:7]}", "NEWNEW22")
        os.symlink(f"releases/{self.new_web.name}", self.web / "current")
        # the fake services
        self.calls, self.forbidden, self.posts, self.starts = [], [], [], []
        self.health_pid, self.stop_fails = {}, False
        self.unit = {"active": "active", "restarts": 0, "pid": 100}
        self.running_sha = self.c2
        self.herdr_bad, self.herdr_up = set(), True   # shas whose ccd reports herdr not ok
        self.health = {}        # sha -> status code | None (no answer)
        self.state = {}         # sha -> status code
        self.db_version, self.db_held, self.downgrade_rc = NEW_SCHEMA, {}, 0
        self.pip_rc, self.post_script, self.on_stop, self.switches = 0, [], None, []
        self.check_lock = True
        self.serve_index = None     # bytes: what GET / answers, whatever current points at
        self.wheels(True)

    def release(self, name, asset_hash):
        d = self.web / "releases" / name
        (d / "assets").mkdir(parents=True)
        (d / "index.html").write_text(f'<!doctype html><script src="/assets/index-{asset_hash}.js"></script>')
        (d / "assets" / f"index-{asset_hash}.js").write_text("x")
        return d

    def wheels(self, ok):
        w = self.watch / "wheels"
        shutil.rmtree(w, ignore_errors=True)
        if ok:
            w.mkdir()
            (w / "old.txt").write_text("a==1\n")
            (w / "new.txt").write_text("a==2\n")

    def plan(self, **over):
        p = {"stamp": "20261201T100000", "unit": "cc-release-watch-20261201T100000", "from_sha": self.c1,
             "to_sha": self.c2, "prev_web": str(self.old_web), "new_web": str(self.new_web),
             "prev_schema": OLD_SCHEMA, "new_schema": NEW_SCHEMA, "herdr_ok_before": True, "pins_differ": False,
             "wheels_ok": True, "backup": str(self.tmp / "tasks.db.pre-main-x")}
        p.update(over)
        return p

    def watcher(self, plan=None, **plan_over):
        env = {"CCD_PORT": "7777", "CCD_WEB_DIR": str(self.web), "CCD_DATA_DIR": str(self.data),
               "CC_REPO": str(self.repo), "CCD_TOKEN_FILE": str(self.token_file),
               "CCD_HERDR_SOCKET": str(self.tmp / "herdr.sock")}
        cfg = rw.Config(env, str(self.watch))
        self.test.assertEqual(cfg.deploys_dir, str(self.deploys))
        return rw.Watcher(cfg, plan or self.plan(**plan_over), run=self.run, http=self.http, sleep=self.clock.sleep,
                          clock=self.clock.now, wall=self.clock.wall, herdr_up=lambda: self.herdr_up)

    # ---- fake systemctl / pip / python / git
    def run(self, argv, timeout=300, cwd=None):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        name = os.path.basename(argv[0])
        if name in ("npm", "npx", "deploy-web.sh") or "deploy-web.sh" in joined or \
                (name == "git" and "fetch" in argv) or (name == "pip" and "download" in argv) or \
                (name == "pip" and "--no-index" not in argv):
            self.forbidden.append(joined)
            return 1, "forbidden"
        if name == "systemctl":
            return self.systemctl(argv[2:])
        if name == "git":
            if "switch" in argv:
                self.switches.append(argv[-1])
            r = subprocess.run(argv, env=GIT_ENV, capture_output=True, text=True)
            return r.returncode, (r.stdout + r.stderr).strip()
        if name == "pip":
            return self.pip_rc, "pip failed" if self.pip_rc else ""
        if name == "python":
            if "-c" in argv:
                return 0, json.dumps({"current": self.db_version, "missing": [], "held": self.db_held})
            if "ccd.migration_safety" in argv:
                if self.downgrade_rc == 0:
                    self.db_version = int(argv[argv.index("--to") + 1])
                return self.downgrade_rc, "refused" if self.downgrade_rc else ""
        raise AssertionError(f"unexpected command {joined}")

    def systemctl(self, args):
        if args[0] == "show":
            u = self.unit
            return 0, f"ActiveState={u['active']}\nNRestarts={u['restarts']}\nMainPID={u['pid']}"
        if args[0] == "stop":
            if not self.stop_fails:
                self.unit["active"] = "inactive"
            if self.on_stop:
                self.on_stop()
            return 0, ""
        if args[0] == "start":
            self.unit.update(active="active", pid=self.unit["pid"] + 1, restarts=0)
            self.running_sha = git(self.repo, "rev-parse", "HEAD")
            self.starts.append((self.running_sha, self.live_web().name))
            return 0, ""
        raise AssertionError(args)

    def ccd_stopped_calls(self):
        return [c[2] for c in self.calls if c[0] == "systemctl" and c[2] in ("stop", "start")]

    # ---- fake ccd over HTTP; /api/* except health needs the token, as in ccd's Guard
    def http(self, method, path, headers=None, body=None, timeout=5):
        headers = headers or {}
        if method == "POST":
            self.posts.append({"path": path, "headers": dict(headers), "body": json.loads(body)})
            if self.check_lock:
                self.test.assertTrue(self.lock_free(), "the go-live lock was still held while notifying")
            self.test.assertFalse((self.deploys / "watch" / "active.json").exists())
            status = self.post_script.pop(0) if self.post_script else 200
            return status, b"{}"
        if self.unit["active"] != "active":
            return None, b""
        sha = self.running_sha
        if path != "/api/health" and path.startswith("/api/") and headers.get("X-CCD-Token") != TOKEN:
            return 401, b'{"ok": false}'
        if path == "/api/health":
            status = self.health.get(sha, 200)
            if status != 200:
                return status, b"{}"
            herdr_ok = sha not in self.herdr_bad
            return 200, json.dumps({"ok": herdr_ok, "herdr": {"ok": herdr_ok},
                                    "pid": self.health_pid.get(sha, self.unit["pid"]),
                                    "tasks": {"schemaVersion": self.schema_of[sha]}}).encode()
        if path == "/api/state":
            return self.state.get(sha, 200), b"{}"
        cur = (self.web / "current").resolve()
        if path == "/":
            return 200, self.serve_index or (cur / "index.html").read_bytes()
        f = cur / path.lstrip("/")
        return (200, f.read_bytes()) if f.is_file() else (404, b"")

    def lock_free(self):
        fd = os.open(self.deploys / ".go-live.lock", os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
        finally:
            os.close(fd)

    def result(self):
        return json.loads((self.watch / "result.json").read_text())

    def lines(self):
        p = self.deploys / "releases.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def head_detached(self):
        return subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=self.repo, env=GIT_ENV,
                              capture_output=True).returncode != 0

    def live_web(self):
        return (self.web / "current").resolve()


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.box = Box(self)
        self.addCleanup(lambda box=self.box: self.assertEqual(box.forbidden, [], "a rollback made a call it must never make"))
        self.addCleanup(self.assert_no_mixed_start, self.box)

    def assert_no_mixed_start(self, box):
        """ccd is only ever started on a whole release: old code with the old UI, or new code with the new UI."""
        whole = {(box.c1, box.old_web.name), (box.c2, box.new_web.name)}
        for sha, web in box.starts:
            if sha in box.schema_of and sha in (box.c1, box.c2):
                self.assertIn((sha, web), whole, "ccd was started on a mixed release")

    def go(self, **plan_over):
        w = self.box.watcher(**plan_over)
        return w.run_all()

    def assert_rolled_back(self, check):
        b = self.box
        r = b.result()
        self.assertEqual((r["result"], r["check"]), ("rolled_back", check), r)
        self.assertEqual(b.live_web(), b.old_web)
        self.assertEqual(b.head(), b.c1)
        self.assertTrue(b.head_detached())
        self.assertEqual(b.unit["active"], "active")
        self.assertEqual(b.running_sha, b.c1)
        return r

    # ---------------- c1 / c4: healthy leaves the new release live ----------------

    def test_c1_c4_healthy_release_is_left_alone_and_logged_once(self):
        b = self.box
        r = self.go()
        self.assertEqual(r["result"], "healthy")
        self.assertEqual(b.live_web(), b.new_web)
        self.assertEqual(b.head(), b.c2)
        self.assertEqual(b.ccd_stopped_calls(), [], "a healthy release must not stop or start ccd")
        self.assertEqual(b.posts, [], "nothing to tell Jay about a healthy release")
        (line,) = b.lines()
        self.assertEqual(line["result"], "healthy")
        self.assertEqual(line["checks"], {"api": "ok", "daemon": "ok", "ui": "ok"})
        self.assertEqual((line["from"], line["to"]), (b.c1, b.c2))
        self.assertEqual(json.loads((b.watch / "result.json").read_text())["result"], "healthy")

    def test_c1_each_check_fails_the_release(self):
        cases = {
            "api: /api/health 5xx": ("api", lambda b: b.health.update({b.c2: 503})),
            "api: /api/health times out": ("api", lambda b: b.health.update({b.c2: None})),
            "ui: an asset is missing": ("ui", lambda b: (b.new_web / "assets" / "index-NEWNEW22.js").unlink()),
            "ui: the old index is served": ("ui", lambda b: setattr(b, "serve_index", b.old_web.joinpath("index.html").read_bytes())),
            "daemon: /api/state 503 after the grace": ("daemon", lambda b: b.state.update({b.c2: 503})),
            "daemon: wrong schema": ("daemon", lambda b: b.schema_of.update({b.c2: 99})),
        }
        for name, (check, setup) in cases.items():
            with self.subTest(name):
                self.setUp()
                setup(self.box)
                self.go()
                self.assert_rolled_back(check)

    def test_c1_bad_samples_during_the_grace_do_not_count(self):
        b = self.box
        b.health[b.c2] = None                      # ccd is still starting ...
        b.clock.at(40, lambda: b.health.pop(b.c2))  # ... and answers before the 60 s grace ends
        self.assertEqual(self.go()["result"], "healthy")

    def test_a_single_bad_sample_is_not_a_failure(self):
        b = self.box
        b.clock.at(100, lambda: b.health.update({b.c2: 500}))
        b.clock.at(110, lambda: b.health.pop(b.c2))   # one 15 s sample falls in the gap
        self.assertEqual(self.go()["result"], "healthy")

    def test_a_401_or_403_is_a_probe_error_never_a_rollback_and_never_healthy(self):
        b = self.box
        orig = b.http
        b.http = lambda m, p, h=None, body=None, t=5: (403, b"") if m == "GET" and p == "/api/state" else orig(m, p, h, body, t)
        r = self.go()
        self.assertEqual(r["result"], "inconclusive", "a state that was never verified is not healthy")
        self.assertEqual(b.ccd_stopped_calls(), [], "and nothing is rolled back on probe errors")
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))
        self.assertEqual(len(b.posts), 1)
        self.assertIn("could not be verified", b.posts[0]["body"]["text"])

    def test_an_unreadable_token_is_inconclusive_not_healthy(self):
        b = self.box
        b.token_file.unlink()
        self.assertEqual(self.go()["result"], "inconclusive")
        self.assertEqual(b.ccd_stopped_calls(), [])

    # ---------------- hard deadline (virtual clock) ----------------

    HARD = 60 + 300 + 120 + 15      # grace + window + hard_extra + one sample

    def test_one_bad_sample_then_persistent_403_still_ends_with_a_verdict(self):
        b = self.box
        orig = b.http

        def http(m, p, h=None, body=None, t=5):
            if m == "GET" and b.clock.t >= 100 and p != "/api/health":
                return 403, b""
            return orig(m, p, h, body, t)
        b.http = http
        b.clock.at(95, lambda: b.health.update({b.c2: 500}))
        b.clock.at(102, lambda: b.health.pop(b.c2))      # one bad /api/health sample, then only probe errors
        r = self.go()
        self.assertEqual(r["result"], "inconclusive")
        self.assertLessEqual(b.clock.t, self.HARD)
        self.assertEqual(b.ccd_stopped_calls(), [])

    def test_repeated_pid_changes_cannot_extend_the_watch_for_ever(self):
        b = self.box
        for i in range(1, 60):
            b.clock.at(20 * i, lambda i=i: b.unit.update(pid=1000 + i))
        r = self.go()
        self.assertEqual(r["result"], "inconclusive")
        self.assertLessEqual(b.clock.t, self.HARD)

    # ---------------- the process that answers is the deployed one ----------------

    def test_old_code_still_answering_with_the_old_pid_is_not_healthy(self):
        b = self.box
        b.unit["pid"] = 200
        b.health_pid[b.c2] = 100        # same schema, the new UI, but the answer is the previous process
        self.go()
        self.assert_rolled_back("daemon")

    def test_the_process_from_before_the_restart_still_running_is_not_healthy(self):
        b = self.box
        self.go(old_pid=100)             # MainPID is still 100: the restart did not take
        self.assert_rolled_back("daemon")

    def test_a_crash_before_the_first_sample_shows_against_the_baseline_go_live_recorded(self):
        b = self.box
        b.unit["restarts"] = 1           # systemd already restarted it once since go-live's restart (baseline 0)
        self.go(base_restarts=0, base_pid=100)
        self.assert_rolled_back("crash")

    # ---------------- c1/c2 crash rules ----------------

    def test_crash_rules(self):
        b = self.box
        # a manual restart: pid changes, systemd resets NRestarts to 0 (the baseline was 5), and ccd is down for a
        # few samples while it starts. The re-baseline's new grace must cover those samples.
        b.unit["restarts"] = 5
        def restart():
            b.unit.update(pid=555, restarts=0)
            b.health[b.c2] = None
        b.clock.at(100, restart)
        b.clock.at(130, lambda: b.health.pop(b.c2))
        self.assertEqual(self.go()["result"], "healthy", "a manual restart is not a crash")

    def test_crash_nrestarts_above_the_baseline_rolls_back_at_once(self):
        b = self.box
        b.clock.at(100, lambda: b.unit.update(restarts=1))   # baseline 0 (the new ccd) -> 1
        self.go()
        self.assert_rolled_back("crash")

    def test_crash_unit_failed_twice_rolls_back(self):
        b = self.box
        b.clock.at(100, lambda: b.unit.update(active="failed"))
        self.go()
        self.assert_rolled_back("crash")

    def test_unit_failed_once_is_not_enough(self):
        b = self.box
        b.clock.at(100, lambda: b.unit.update(active="failed"))
        b.clock.at(110, lambda: b.unit.update(active="active"))
        self.assertEqual(self.go()["result"], "healthy")

    # ---------------- c2 herdr ----------------

    def test_herdr_socket_down_does_not_roll_back(self):
        b = self.box
        b.herdr_bad, b.herdr_up = {b.c2}, False
        self.assertEqual(self.go()["result"], "healthy")

    def test_herdr_not_ok_with_socket_up_twice_rolls_back(self):
        b = self.box
        b.herdr_bad, b.herdr_up = {b.c2}, True
        self.go()
        self.assert_rolled_back("daemon")

    def test_herdr_not_ok_is_ignored_when_it_was_not_ok_before(self):
        b = self.box
        b.herdr_bad, b.herdr_up = {b.c2}, True
        self.assertEqual(self.go(herdr_ok_before=False)["result"], "healthy")

    # ---------------- c2: the rollback itself ----------------

    def test_c2_rollback_order_and_schema_downgrade_from_the_new_checkout(self):
        b = self.box
        b.health[b.c2] = 500
        orig = b.run

        def spy(argv, timeout=300, cwd=None):
            if "ccd.migration_safety" in argv:
                self.assertEqual(b.head(), b.c2, "the downgrade must run with the NEW code, before the switch")
                self.assertEqual(Path(cwd), b.repo / "server")
                self.assertEqual(argv[argv.index("--to") + 1], str(OLD_SCHEMA))
                self.assertEqual(b.unit["active"], "inactive", "ccd must be stopped first")
            return orig(argv, timeout, cwd)
        b.run = spy
        self.go()
        self.assert_rolled_back("api")
        self.assertEqual(b.db_version, OLD_SCHEMA)
        calls = b.ccd_stopped_calls()
        self.assertEqual(calls, ["stop", "start"])
        seen = []
        for c in b.calls:
            if c[:3] == ["systemctl", "--user", "stop"]:
                seen.append("stop")
            elif "ccd.migration_safety" in c:
                seen.append("mig")
            elif c[0] == "git" and "switch" in c:
                seen.append("switch")
        self.assertEqual(seen, ["stop", "mig", "switch"])
        r = b.result()
        self.assertIn("failed api", r["message"])
        self.assertIn(b.old_web.name, r["message"])

    def test_c2_no_downgrade_when_the_schema_did_not_grow(self):
        b = self.box
        b.db_version = OLD_SCHEMA
        b.health[b.c2] = 500
        self.go()
        self.assert_rolled_back("api")
        self.assertFalse([c for c in b.calls if "ccd.migration_safety" in c])

    def test_pip_only_with_no_index_from_local_wheels_when_pins_differ(self):
        b = self.box
        b.health[b.c2] = 500
        self.go(pins_differ=True)
        self.assert_rolled_back("api")
        pips = [c for c in b.calls if os.path.basename(c[0]) == "pip"]
        self.assertEqual(len(pips), 1)
        self.assertIn("--no-index", pips[0])
        self.assertEqual(pips[0][pips[0].index("--find-links") + 1], str(b.watch / "wheels"))
        self.assertTrue(pips[0][-1].endswith("old.txt"))

    def test_no_pip_when_pins_are_the_same(self):
        b = self.box
        b.health[b.c2] = 500
        self.go()
        self.assertFalse([c for c in b.calls if os.path.basename(c[0]) == "pip"])

    # ---------------- c2 failure table: ccd ends started and answering, one alert, rollback_failed ----------------

    def assert_failed(self, step, answering=True):
        b = self.box
        r = b.result()
        self.assertEqual((r["result"], r["step"]), ("rollback_failed", step), r)
        self.assertEqual(b.unit["active"], "active", "ccd must be left started")
        if answering:   # (not where ccd is, by construction, still on the bad release)
            self.assertEqual(b.http("GET", "/api/health")[0], 200, "and answering")
        self.assertEqual(len(b.posts), 1, "one alert")
        self.assertIn(f"FAILED at {step}", b.posts[0]["body"]["text"])
        (line,) = b.lines()
        self.assertEqual((line["result"], line["step"]), ("rollback_failed", step))
        return r

    def test_failure_downgrade_refused_because_tables_hold_rows_changes_nothing(self):
        # Q182 option 1: stop, keep the new release running, tell Jay the recovery steps. No automatic restore.
        b = self.box
        b.state[b.c2] = 503
        b.db_held = {"ticket_flow": 3}
        self.go()
        self.assert_failed("downgrade")
        self.assertEqual(b.ccd_stopped_calls(), [], "nothing was switched and ccd was never stopped")
        self.assertEqual(b.live_web(), b.new_web)
        self.assertEqual(b.head(), b.c2)
        self.assertEqual(b.db_version, NEW_SCHEMA)
        text = b.posts[0]["body"]["text"]
        self.assertIn("hold rows", b.result()["reason"])
        self.assertIn("go-live-auto-rollback.md", text)
        self.assertIn(str(b.tmp / "tasks.db.pre-main-x"), text)

    def test_failure_downgrade_errors_after_stop_starts_ccd_on_the_new_release(self):
        b = self.box
        b.health[b.c2] = 500
        b.downgrade_rc = 1
        self.go()
        self.assert_failed("downgrade", answering=False)
        self.assertEqual(b.ccd_stopped_calls(), ["stop", "start"])
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))

    def test_failure_checkout_blocked_by_an_untracked_file_stays_on_target(self):
        b = self.box
        b.health[b.c2] = 500
        (b.repo / "clash.txt").write_text("untracked, in the way of c1\n")
        self.go()
        self.assert_failed("checkout", answering=False)
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))
        self.assertEqual(b.ccd_stopped_calls(), ["stop", "start"])

    def test_failure_pip_restores_the_whole_target_and_never_starts_old_code_on_the_new_ui(self):
        b = self.box
        b.health[b.c2] = 500
        b.pip_rc = 1
        orig = b.run

        def pip(argv, timeout=300, cwd=None):
            if os.path.basename(argv[0]) == "pip" and argv[-1].endswith("new.txt"):
                b.calls.append(list(argv))
                return 0, ""            # the target's pins come back from local wheels
            return orig(argv, timeout, cwd)
        b.run = pip
        self.go(pins_differ=True)
        self.assert_failed("pip", answering=False)
        self.assertEqual(b.switches, [b.c1, b.c2])
        self.assertEqual((b.head(), b.live_web(), b.running_sha), (b.c2, b.new_web, b.c2))
        self.assertEqual(b.starts, [(b.c2, b.new_web.name)], "ccd started once, on the whole target")
        pip_files = [c[-1].split("/")[-1] for c in b.calls if os.path.basename(c[0]) == "pip"]
        self.assertEqual(pip_files, ["old.txt", "new.txt"])

    def test_failure_link_switch_restores_the_target_not_a_mixed_release(self):
        b = self.box
        b.health[b.c2] = 500
        real, calls = os.symlink, []

        def flaky(src, dst, *a, **k):
            calls.append(src)
            if len(calls) == 1:
                raise OSError("read-only file system")
            return real(src, dst, *a, **k)
        with mock.patch("ccd.release_watch.os.symlink", flaky):
            self.go()
        self.assert_failed("link", answering=False)
        self.assertEqual((b.head(), b.live_web(), b.running_sha), (b.c2, b.new_web, b.c2))
        self.assertEqual(b.starts, [(b.c2, b.new_web.name)])

    def test_a_ui_deploy_running_refuses_before_the_stop(self):
        b = self.box
        b.health[b.c2] = 500
        fd = os.open(b.web / ".deploy.lock", os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.go()
        self.assertEqual(b.result()["step"], "precondition")
        self.assertEqual(b.ccd_stopped_calls(), [])

    def test_ccd_that_does_not_stop_means_nothing_is_switched(self):
        b = self.box
        b.health[b.c2] = 500
        b.stop_fails = True
        self.go()
        self.assertEqual(b.result()["step"], "stop")
        self.assertEqual(b.switches, [])
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))
        self.assertEqual(b.db_version, NEW_SCHEMA, "the DB was not downgraded under a running ccd")

    def test_failure_old_release_fails_verification_goes_back_to_the_target(self):
        b = self.box
        b.health[b.c2] = 500
        b.health[b.c1] = None                # the old release never answers
        orig = b.run

        def heal_on_target(argv, timeout=300, cwd=None):
            r = orig(argv, timeout, cwd)
            if os.path.basename(argv[0]) == "git" and argv[-1] == b.c2:
                b.health[b.c2] = 200         # what was running before runs again
            return r
        b.run = heal_on_target
        self.go(pins_differ=True)
        self.assert_failed("verify")
        pip_files = [c[-1].split("/")[-1] for c in b.calls if os.path.basename(c[0]) == "pip"]
        self.assertEqual(pip_files, ["old.txt", "new.txt"], "the target's pins are reinstalled from local wheels")
        self.assertEqual(b.switches, [b.c1, b.c2], "no third release")
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))
        self.assertEqual(b.running_sha, b.c2)

    def test_an_unexpected_error_still_leaves_ccd_started(self):
        b = self.box
        b.health[b.c2] = 500
        orig = b.run

        def boom(argv, timeout=300, cwd=None):
            if argv[0] == "git" and "switch" in argv:
                raise RuntimeError("disk on fire")
            return orig(argv, timeout, cwd)
        b.run = boom
        self.go()
        r = b.result()
        self.assertEqual((r["result"], r["step"]), ("rollback_failed", "error"))
        self.assertEqual(b.unit["active"], "active")

    # ---------------- c5: never deploys anything new; nothing to go back to -> stop and alert ----------------

    def assert_no_previous(self):
        b = self.box
        r = b.result()
        self.assertEqual(r["result"], "no_previous", r)
        self.assertEqual(b.ccd_stopped_calls(), [], "ccd untouched")
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))
        self.assertEqual(len(b.posts), 1)
        self.assertIn("no previous release", b.posts[0]["body"]["text"])
        (line,) = b.lines()
        self.assertEqual(line["result"], "no_previous")

    def test_c5_no_previous_web_dir(self):
        self.box.health[self.box.c2] = 500
        self.go(prev_web="")
        self.assert_no_previous()

    def test_c5_previous_dir_without_index(self):
        b = self.box
        b.health[b.c2] = 500
        (b.old_web / "index.html").unlink()
        self.go()
        self.assert_no_previous()

    def test_c5_previous_commit_unknown(self):
        self.box.health[self.box.c2] = 500
        self.go(from_sha="0" * 40)
        self.assert_no_previous()

    def test_c5_head_moved_mid_rollback_stops_switching_and_starts_ccd(self):
        b = self.box

        def move_head():
            git(b.repo, "commit", "-q", "--allow-empty", "-m", "someone else deployed")
            b.schema_of[b.head()] = NEW_SCHEMA
        b.on_stop = move_head
        b.health[b.c2] = 500
        self.go()
        self.assertEqual(b.result()["step"], "moved")
        self.assertEqual(b.switches, [], "no further switch")
        self.assertEqual(b.live_web(), b.new_web)
        self.assertEqual(b.unit["active"], "active")
        self.assertEqual(len(b.posts), 1)

    def test_c5_web_current_moved_before_the_stop_changes_nothing(self):
        b = self.box
        b.health[b.c2] = 500
        os.symlink(f"releases/{b.old_web.name}", b.web / "current.x")
        os.replace(b.web / "current.x", b.web / "current")   # a standalone deploy-web.sh switched it
        self.go()
        self.assertEqual(b.result()["step"], "moved")
        self.assertEqual(b.ccd_stopped_calls(), [])
        self.assertEqual(len(b.posts), 1)

    def test_c5_tracked_changes_in_the_checkout_refuse_before_the_stop(self):
        b = self.box
        b.health[b.c2] = 500
        (b.repo / "server" / "requirements.txt").write_text("edited\n")
        self.go()
        self.assertEqual(b.result()["step"], "precondition")
        self.assertEqual(b.ccd_stopped_calls(), [])

    def test_pins_differ_without_local_wheels_refuses_before_the_stop(self):
        b = self.box
        b.health[b.c2] = 500
        b.wheels(False)
        self.go(pins_differ=True)
        self.assertEqual(b.result()["step"], "precondition")
        self.assertEqual(b.ccd_stopped_calls(), [])

    def test_the_go_live_lock_held_means_no_switching_at_all(self):
        b = self.box
        b.health[b.c2] = 500
        fd = os.open(b.deploys / ".go-live.lock", os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        b.check_lock = False   # the test itself holds the lock here
        w = b.watcher()
        w.t.lock_wait = 3
        w.run_all()
        self.assertEqual(b.result()["step"], "lock")
        self.assertEqual(b.ccd_stopped_calls(), [])

    # ---------------- c3: Messages ----------------

    def test_c3_post_is_retried_while_ccd_is_down_and_sent_exactly_once(self):
        b = self.box
        b.health[b.c2] = 500
        b.post_script = [None, None, 502, 200]       # connection refused, refused, 5xx, then stored
        self.go()
        ok = [p for p in b.posts]
        self.assertEqual(len(ok), 4)
        for p in ok:
            self.assertEqual(p["headers"]["X-CCD-Actor"], "agent:lead-commandcenter")
            self.assertEqual(p["headers"]["X-CCD-Token"], TOKEN)
            self.assertEqual(p["path"], "/api/chat/commandcenter/messages")
            self.assertEqual(p["body"], ok[0]["body"])
        r = b.result()
        self.assertEqual((r["notified"], r["attempts"]), (True, 4))
        (line,) = b.lines()
        self.assertEqual((line["notified"], line["attempts"]), (True, 4))
        self.assertIn(f"live is now {b.old_web.name}", r["message"])
        self.assertIn(f"release {b.new_web.name}", r["message"])

    def test_c3_429_is_retried_and_403_404_stop_the_retry(self):
        for status, attempts, notified in ((429, 2, True), (403, 1, False), (404, 1, False)):
            with self.subTest(status=status):
                self.setUp()
                b = self.box
                b.health[b.c2] = 500
                b.post_script = [status, 200]
                self.go()
                self.assertEqual((len(b.posts), b.result()["notified"]), (attempts, notified))
                if not notified:
                    self.assertEqual(b.lines()[0]["notified"], False)

    def test_c3_gives_up_after_thirty_minutes(self):
        b = self.box
        b.health[b.c2] = 500
        b.post_script = [None] * 1000
        self.go()
        r = b.result()
        self.assertEqual(r["notified"], False)
        self.assertLess(b.clock.t, 360 + 1800 + 600 + 300)
        self.assertGreater(r["attempts"], 5)

    def test_result_is_written_before_the_alert_and_the_lock_is_released_first(self):
        b = self.box
        b.health[b.c2] = 500
        seen = {}
        orig = b.http

        def spy(method, path, headers=None, body=None, timeout=5):
            if method == "POST" and "result" not in seen:
                seen["result"] = json.loads((b.watch / "result.json").read_text())["result"]
                seen["lock_free"] = b.lock_free()
            return orig(method, path, headers, body, timeout)
        b.http = spy
        (b.deploys / "watch" / "active.json").write_text(json.dumps({"unit": b.plan()["unit"], "until": 1}))
        self.go()
        self.assertEqual(seen, {"result": "rolled_back", "lock_free": True})

    def test_healthy_never_posts(self):
        self.go()
        self.assertEqual(self.box.posts, [])


    # ---------------- no valid rollback target is never guessed ----------------

    def test_previous_ui_release_that_does_not_name_its_commit_is_no_previous(self):
        b = self.box
        b.health[b.c2] = 500
        for name, plan in (("dirty release", {"prev_web": str(b.web / "releases" / "x-dirty")}),
                           ("no commit recorded", {"from_sha": ""}),
                           ("commit is not the one the UI names", {"from_sha": b.c2})):
            with self.subTest(name):
                self.setUp()
                b = self.box
                b.health[b.c2] = 500
                if "prev_web" in plan:
                    d = b.web / "releases" / "x-dirty"
                    d.mkdir()
                    (d / "index.html").write_text("<x/>")
                    plan = {"prev_web": str(b.web / "releases" / f"20261101T000000Z-{b.c1[:7]}-dirty")}
                    shutil.copytree(b.old_web, plan["prev_web"])
                self.go(**plan)
                self.assert_no_previous()
                self.assertIn("no valid rollback target", b.result()["reason"] + b.result()["message"]
                              if "from_sha" in plan and not plan["from_sha"] or "prev_web" in plan else "no valid rollback target")

    # ---------------- recovery after the watcher dies mid-transaction ----------------

    def test_recover_undoes_an_interrupted_rollback_before_ccd_is_started(self):
        b = self.box
        git(b.repo, "switch", "-q", "--detach", b.c1)                  # the watcher died after the checkout ...
        b.unit["active"] = "inactive"                                    # ... with ccd stopped
        (b.watch / "journal.json").write_text(json.dumps({"state": "rolling_back"}))
        w = b.watcher()
        self.assertTrue(w.recover())
        self.assertEqual((b.head(), b.live_web()), (b.c2, b.new_web))
        self.assertEqual(b.starts, [(b.c2, b.new_web.name)], "started on the whole target, never on the half-done state")

    def test_recover_does_nothing_unless_a_rollback_was_cut_off(self):
        b = self.box
        for state in (None, "done", "rolled_back"):
            if state:
                (b.watch / "journal.json").write_text(json.dumps({"state": state}))
            self.assertFalse(b.watcher().recover())
        self.assertEqual(b.calls, [])

    def test_recover_leaves_ccd_to_a_go_live_that_holds_the_lock(self):
        b = self.box
        b.unit["active"] = "inactive"
        (b.watch / "journal.json").write_text(json.dumps({"state": "rolling_back"}))
        fd = os.open(b.deploys / ".go-live.lock", os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        w = b.watcher()
        w.t.lock_wait = 2
        self.assertFalse(w.recover())
        self.assertEqual(b.switches, [])

    def test_killed_between_steps_leaves_a_journal_that_recover_acts_on(self):
        # the watcher process is cut off right after the checkout: the journal says rolling_back
        b = self.box
        b.health[b.c2] = 500
        orig = b.run

        dead = []

        def die_after_checkout(argv, timeout=300, cwd=None):
            if dead:
                raise KeyboardInterrupt("the process is gone: nothing after the kill can run")
            r = orig(argv, timeout, cwd)
            if argv[0] == "git" and "switch" in argv and argv[-1] == b.c1:
                dead.append(1)
                raise KeyboardInterrupt("SIGKILL")
            return r
        b.run = die_after_checkout
        first = b.watcher()
        with self.assertRaises(KeyboardInterrupt):
            first.run_all()
        first._close_lock()        # the kernel drops a killed process's flocks
        first.drop_deploy_lock()
        self.assertEqual(b.head(), b.c1)
        self.assertEqual(json.loads((b.watch / "journal.json").read_text())["state"], "rolling_back")
        b.run = orig
        self.assertTrue(b.watcher().recover())
        self.assertEqual((b.head(), b.live_web(), b.running_sha), (b.c2, b.new_web, b.c2))

    # ---------------- the verdict is a snapshot taken under the lock ----------------

    def test_the_alert_describes_the_state_at_the_verdict_not_what_a_later_go_live_made_of_it(self):
        b = self.box
        b.health[b.c2] = 500
        orig = b.http
        seen = {}

        def http(method, path, headers=None, body=None, timeout=5):
            if method == "POST" and "line" not in seen:
                seen["line"] = b.lines()                      # the durable log line exists before Jay is told
                git(b.repo, "switch", "-q", "--detach", b.c2)  # a go-live gets in as soon as the lock is free
                os.symlink(f"releases/{b.new_web.name}", b.web / "x")
                os.replace(b.web / "x", b.web / "current")
            return orig(method, path, headers, body, timeout)
        b.http = http
        self.go()
        (line,) = seen["line"]
        self.assertEqual((line["result"], line["notified"]), ("rolled_back", None))
        self.assertIn(f"live is now {b.old_web.name} ({b.c1[:7]})", b.posts[0]["body"]["text"])
        self.assertEqual(b.result()["live"], {"web": b.old_web.name, "sha": b.c1})
        (final,) = b.lines()
        self.assertEqual((final["notified"], final["attempts"]), (True, 1))


class DirectTransport(unittest.TestCase):
    """The watcher's own HTTP client: loopback only, no proxy from the environment, no redirects."""

    def serve(self, handler_cls):
        import http.server
        import threading
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return srv

    def watcher(self, port):
        tmp = Path(tempfile.mkdtemp(prefix="release-watch-net-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "tok").write_text(TOKEN)
        cfg = rw.Config({"CCD_PORT": str(port), "CCD_WEB_DIR": str(tmp), "CCD_DATA_DIR": str(tmp),
                         "CC_REPO": str(tmp), "CCD_TOKEN_FILE": str(tmp / "tok"),
                         "CCD_HERDR_SOCKET": str(tmp / "s")}, str(tmp / "deploys" / "watch" / "x"))
        return rw.Watcher(cfg, {})

    def test_a_redirect_is_not_followed_so_the_token_goes_nowhere_else(self):
        import http.server
        got = []

        class Elsewhere(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                got.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            log_message = lambda *a: None
        other = self.serve(Elsewhere)

        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{other.server_port}/steal")
                self.end_headers()

            log_message = lambda *a: None
        ccd = self.serve(Redirect)
        st, _ = self.watcher(ccd.server_port).get("/api/state")
        self.assertEqual(st, 302)
        self.assertEqual(got, [], "the redirect target never saw a request")

    def test_the_proxy_environment_is_ignored(self):
        import http.server
        proxied = []

        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                proxied.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            log_message = lambda *a: None
        proxy = self.serve(Proxy)

        class Ccd(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204 if self.headers.get("X-CCD-Token") == TOKEN else 401)
                self.end_headers()

            log_message = lambda *a: None
        ccd = self.serve(Ccd)
        env = {"http_proxy": f"http://127.0.0.1:{proxy.server_port}", "HTTP_PROXY": f"http://127.0.0.1:{proxy.server_port}"}
        with mock.patch.dict(os.environ, env):
            st, _ = self.watcher(ccd.server_port).get("/api/state")
        self.assertEqual(st, 204)
        self.assertEqual(proxied, [])

    def test_a_trickling_answer_is_cut_off_by_the_overall_budget(self):
        import http.server
        import time as _t

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                for _ in range(100):
                    try:
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    except OSError:
                        return
                    _t.sleep(0.2)

            log_message = lambda *a: None
        srv = self.serve(Slow)
        w = self.watcher(srv.server_port)
        t0 = _t.monotonic()
        st, _ = w._http("GET", "/api/state", {}, None, 1)
        self.assertIsNone(st)
        self.assertLess(_t.monotonic() - t0, 4)


class ProbeAgainstRealGuard(unittest.TestCase):
    """The watcher's own transport against ccd's real Guard on a real socket: Host 127.0.0.1:PORT (set by the client
    itself), X-CCD-Token from the token file. Nothing is supplied by hand."""

    def test_probes_get_200_through_a_real_server(self):
        import threading
        import uvicorn
        from ccd.api import create_app

        tmp = Path(tempfile.mkdtemp(prefix="release-watch-guard-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "ui" / "assets").mkdir(parents=True)
        (tmp / "ui" / "index.html").write_text('<script src="/assets/index-AbCd1234.js"></script>')
        (tmp / "ui" / "assets" / "index-AbCd1234.js").write_text("x")
        (tmp / "ccd.token").write_text(TOKEN + "\n")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        daemon = mock.MagicMock()
        daemon.snap = {"x": 1}
        daemon.health.return_value = {"ok": True, "pid": 7, "herdr": {"ok": True}, "tasks": {"schemaVersion": 14}}
        daemon.state.return_value = {"ok": True}
        guarded, _app = create_app(daemon, TOKEN, port, ui=str(tmp / "ui"))
        server = uvicorn.Server(uvicorn.Config(guarded, host="127.0.0.1", port=port, log_level="warning",
                                               lifespan="off"))
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        self.addCleanup(th.join, 5)
        self.addCleanup(setattr, server, "should_exit", True)
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        self.assertTrue(server.started)
        cfg = rw.Config({"CCD_PORT": str(port), "CCD_WEB_DIR": str(tmp), "CCD_DATA_DIR": str(tmp), "CC_REPO": str(tmp),
                         "CCD_TOKEN_FILE": str(tmp / "ccd.token"), "CCD_HERDR_SOCKET": str(tmp / "s")},
                        str(tmp / "deploys" / "watch" / "x"))
        plan = {"herdr_ok_before": True, "new_schema": 14, "unit": "u"}
        w = rw.Watcher(cfg, plan, herdr_up=lambda: True)
        for path in ("/api/health", "/api/state", "/", "/assets/index-AbCd1234.js"):
            st, _ = w.get(path, token=path == "/api/state")
            self.assertEqual(st, 200, path)
        unit = {"active": "active", "restarts": 0, "pid": 7}
        s = w.sample((tmp / "ui" / "index.html").read_bytes(), 14, False, unit)
        self.assertEqual({k: s[k] for k in ("api", "daemon", "ui")}, {"api": "ok", "daemon": "ok", "ui": "ok"})
        # a wrong token is refused by the real Guard; the watcher calls that a probe error, not a failure
        (tmp / "ccd.token").write_text("w" * 43)
        w2 = rw.Watcher(cfg, plan, herdr_up=lambda: True)
        s = w2.sample((tmp / "ui" / "index.html").read_bytes(), 14, False, unit)
        self.assertEqual((s["daemon"], s["ui"]), ("probe", "ok"))   # the UI files are not behind the token


class HeldTablesSnippet(unittest.TestCase):
    """The pre-stop check runs against the REAL tasks module: new tables with rows are reported, empty ones are not."""

    def test_reports_rows_in_tables_a_migration_added(self):
        import sqlite3
        from ccd import tasks
        tmp = Path(tempfile.mkdtemp(prefix="release-watch-db-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db_path = tmp / "tasks.db"
        db = sqlite3.connect(db_path, isolation_level=None)
        tasks.migrate(db)
        server = str(Path(rw.__file__).resolve().parent.parent)

        def held():
            r = subprocess.run([sys.executable, "-I", "-c", rw.HELD_SNIPPET, server, str(db_path),
                                str(tasks.SCHEMA_VERSION - 1)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout.splitlines()[-1])
        info = held()
        self.assertEqual((info["current"], info["held"], info["missing"]), (tasks.SCHEMA_VERSION, {}, []))
        # foreign keys are off on a plain connection, so a row can stand without its ticket
        db.execute("INSERT INTO ticket_flow (ticket_id, size, updated_at) VALUES (1, 'small', 0)")
        db.close()
        info = held()
        self.assertEqual(info["held"], {"ticket_flow": 1})


if __name__ == "__main__":
    unittest.main()
