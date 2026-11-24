"""CC-063: watch the release go-live.sh just switched to, and put the previous one back if it is bad.

    python release_watch.py <watch dir>        (started by scripts/go-live.sh as the systemd user unit
                                                cc-release-watch-<stamp>; the watch dir holds plan.json)

Why this is its own unit and a copy, with no ccd imports: it must outlive the pane that ran go-live.sh (a Bash tool
call ends after 2 to 10 minutes), it must not die with the ccd it is judging, and it runs while the checkout it lives
in is switched under it, so bash/python never read a file that changes underneath them. Standard library only.

What it does, in order:
  1. takes the go-live lock (deploys/.go-live.lock) for the whole watch, so no second go-live starts;
  2. checks the new release every 15 s for 60 s grace + 5 min: API (/api/health), daemon (unit, schema, /api/state,
     herdr, crash rules), UI (GET / is the new index.html and every /assets/* it names answers 200). A check fails
     after 2 bad samples in a row; a crash (NRestarts above the baseline, or the unit failed/inactive twice) at once;
  3. on a failure puts back only what was live before: tasks.db (additive empty tables only), the checkout
     (git switch --detach), the pins (pip --no-index from wheels go-live.sh downloaded), web/current. It never
     fetches, builds, runs deploy-web.sh or npm, and never deploys a third release;
  4. always leaves ccd started, writes result.json at once, one line to releases.jsonl at the end, and tells Jay in
     Messages (retried for 30 minutes) as agent:lead-commandcenter.
Failure table: docs/runbooks/go-live-auto-rollback.md.
"""
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ACTOR = "agent:lead-commandcenter"   # Messages accepts an agent post only as that conversation's lead
CONVERSATION = "commandcenter"
RUNBOOK = "docs/runbooks/go-live-auto-rollback.md"

HEALTHY, ROLLED_BACK, ROLLBACK_FAILED, NO_PREVIOUS = "healthy", "rolled_back", "rollback_failed", "no_previous"


class Timing:
    interval = 15
    grace = 60              # the new ccd is still starting: bad samples do not count yet
    window = 300
    verify_grace = 60       # the same for the old release after a rollback
    verify_window = 120
    lock_wait = 30
    answer_wait = 60        # how long the old code gets to answer after a pip failure
    notify_total = 1800     # Messages retry budget
    backoff_first = 15
    backoff_cap = 300
    http_timeout = 5


class StepFailed(Exception):
    def __init__(self, step, why=""):
        super().__init__(f"{step}: {why}")
        self.step, self.why = step, why


# Run with the NEW checkout's code, read-only, before ccd is stopped: would the downgrade refuse? tasks.downgrade
# refuses when a table a migration added holds a row (CC-063: Q182 option 1, no automatic restore of those rows).
HELD_SNIPPET = r"""
import json, sqlite3, sys
sys.path.insert(0, sys.argv[1])
from ccd import tasks
db = sqlite3.connect("file:%s?mode=ro" % sys.argv[2], uri=True)
cur = db.execute("PRAGMA user_version").fetchone()[0]
target = int(sys.argv[3])
steps = list(range(cur, target, -1))
missing = [v for v in steps if v not in tasks.DOWNGRADES]
held = {}
for v in steps:
    for t in tasks.DOWNGRADES.get(v, ()):
        n = db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        if n:
            held[t] = n
print(json.dumps({"current": cur, "missing": missing, "held": held}))
"""


def _run(argv, timeout=300, cwd=None):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


class Config:
    """Paths and ports, read from the unit's environment (go-live.sh passes each one explicitly)."""

    def __init__(self, env, watch_dir):
        need = ("CCD_PORT", "CCD_WEB_DIR", "CCD_DATA_DIR", "CC_REPO", "CCD_TOKEN_FILE", "CCD_HERDR_SOCKET")
        missing = [k for k in need if not env.get(k)]
        if missing:
            raise SystemExit("release_watch: missing environment " + ", ".join(missing))
        self.port = int(env["CCD_PORT"])
        self.web_dir = env["CCD_WEB_DIR"]
        self.data_dir = env["CCD_DATA_DIR"]
        self.repo = env["CC_REPO"]
        self.token_file = env["CCD_TOKEN_FILE"]
        self.herdr_socket = env["CCD_HERDR_SOCKET"]
        self.watch_dir = watch_dir
        self.deploys_dir = os.path.dirname(os.path.dirname(os.path.abspath(watch_dir)))


class Watcher:
    def __init__(self, cfg, plan, timing=None, run=None, http=None, sleep=time.sleep, clock=time.monotonic,
                 wall=time.time, herdr_up=None):
        self.cfg, self.plan = cfg, plan
        self.t = timing or Timing()
        self.run = run or _run
        self._http = http or self._urllib_http
        self.sleep, self.clock, self.wall = sleep, clock, wall
        self._herdr_up = herdr_up or self._socket_accepts
        self.python = os.path.join(cfg.repo, "server", ".venv", "bin", "python")
        self.pip = os.path.join(cfg.repo, "server", ".venv", "bin", "pip")
        self.db = os.path.join(cfg.data_dir, "tasks.db")
        self.wheels = os.path.join(cfg.watch_dir, "wheels")
        self.checks, self.restarts, self.detail = {}, 0, {}
        self._lock_fd = None
        self._token = None

    # ---------- plumbing ----------

    def log(self, msg):
        line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime(self.wall())) + msg
        try:
            with open(os.path.join(self.cfg.watch_dir, "watch.log"), "a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _read_token(self):
        if self._token is None:
            with open(self.cfg.token_file) as f:
                self._token = f.read().strip()
        return self._token

    def _urllib_http(self, method, path, headers=None, body=None, timeout=5):
        """(status, bytes); (None, b"") when nothing answered. urllib sends Host: 127.0.0.1:<port>, which is
        exactly what ccd's Guard allows."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.cfg.port}{path}", data=body, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (OSError, ValueError):
            return None, b""

    def get(self, path, token=True):
        headers = {}
        if token:
            try:
                headers["X-CCD-Token"] = self._read_token()
            except OSError:
                return 401, b""   # cannot read the token: a probe error, never evidence against the release
        return self._http("GET", path, headers, None, self.t.http_timeout)

    @staticmethod
    def _socket_accepts_path(path):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(1)
        try:
            s.connect(path)
            return True
        except OSError:
            return False
        finally:
            s.close()

    def _socket_accepts(self):
        return self._socket_accepts_path(self.cfg.herdr_socket)

    def systemctl(self, *args):
        return self.run(["systemctl", "--user", *args], 60)

    def unit_state(self):
        rc, out = self.systemctl("show", "ccd", "-p", "ActiveState", "-p", "NRestarts", "-p", "MainPID")
        kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        def num(k):
            try:
                return int(kv.get(k, ""))
            except ValueError:
                return None
        return {"active": kv.get("ActiveState", ""), "restarts": num("NRestarts"), "pid": num("MainPID")}

    def git(self, *args, timeout=120):
        return self.run(["git", "-C", self.cfg.repo, *args], timeout)

    # ---------- the checks ----------

    def sample(self, expect_index, expect_schema, in_grace, unit):
        """One round of the three checks. Each is 'ok', 'bad' or 'probe' (the watcher could not ask: a 401/403 or an
        unreadable token says nothing about the release, so it never counts against it)."""
        out = {"detail": {}}
        st, body = self.get("/api/health", token=False)
        health = None
        if st == 200:
            try:
                health = json.loads(body)
            except ValueError:
                pass
        out["api"] = "ok" if health is not None else ("probe" if st in (401, 403) else "bad")
        if out["api"] == "bad":
            out["detail"]["api"] = f"/api/health answered {st}"

        daemon, why = "ok", ""
        if unit["active"] != "active":
            daemon, why = "bad", f"unit is {unit['active'] or 'unknown'}"
        elif health is not None:
            seen = (health.get("tasks") or {}).get("schemaVersion")
            if expect_schema is not None and seen != expect_schema:
                daemon, why = "bad", f"schema v{seen}, expected v{expect_schema}"
            elif (health.get("herdr") or {}).get("ok") is False and self.plan.get("herdr_ok_before") is True \
                    and self._herdr_up():
                # herdr is not part of a release: only count it when it was fine before and its socket is up now
                daemon, why = "bad", "herdr reports not ok while its socket is up"
        if daemon == "ok" and not in_grace:
            st, _ = self.get("/api/state")
            if st in (401, 403):
                daemon = "probe"
            elif st != 200:
                daemon, why = "bad", f"/api/state answered {st}"
        out["daemon"] = daemon
        if why:
            out["detail"]["daemon"] = why

        ui, why = "ok", ""
        st, body = self.get("/")
        if st in (401, 403):
            ui = "probe"
        elif st != 200 or body != expect_index:
            ui, why = "bad", "GET / is not the expected index.html" if st == 200 else f"GET / answered {st}"
        else:
            for a in sorted(set(re.findall(rb'(?:src|href)="(/assets/[^"]+)"', body))):
                ast, _ = self.get(a.decode(), token=False)
                if ast in (401, 403):
                    ui = "probe"
                elif ast != 200:
                    ui, why = "bad", f"{a.decode()} answered {ast}"
                    break
        out["ui"] = ui
        if why:
            out["detail"]["ui"] = why
        return out

    def observe(self, grace, window, expect_index, expect_schema):
        """None when the release stays healthy for grace + window, else the name of the failing check
        (api, daemon, ui or crash). Crash rules look at systemd's NRestarts from a baseline taken now, from the NEW
        ccd after go-live's own restart (systemd resets NRestarts to 0 on a manual restart, so an older baseline
        would hide a crash loop)."""
        t0 = self.clock()
        grace_until, end = t0 + grace, t0 + grace + window
        base = self.unit_state()
        streak = {"api": 0, "daemon": 0, "ui": 0}
        down = 0
        self.detail = {}
        while True:
            now = self.clock()
            u = self.unit_state()
            if u["restarts"] is not None and base["restarts"] is not None and u["restarts"] > base["restarts"]:
                self.detail["crash"] = f"ccd restarted by systemd ({base['restarts']} -> {u['restarts']})"
                self.restarts = u["restarts"]
                return "crash"
            if u["pid"] and base["pid"] and u["pid"] != base["pid"]:
                # Someone restarted ccd by hand (NRestarts did not rise): not a crash. Start over with a new grace.
                self.log(f"ccd pid {base['pid']} -> {u['pid']} without a systemd restart: re-baselined")
                base, grace_until = u, now + self.t.verify_grace
                end = max(end, grace_until + 2 * self.t.interval)
                streak = dict.fromkeys(streak, 0)
                down = 0
            if u["active"] in ("failed", "inactive"):
                down += 1
                if down >= 2:
                    self.detail["crash"] = f"ccd unit is {u['active']}"
                    return "crash"
            else:
                down = 0
            in_grace = now < grace_until
            s = self.sample(expect_index, expect_schema, in_grace, u)
            self.checks = {k: s[k] for k in ("api", "daemon", "ui")}
            self.restarts = u["restarts"] or 0
            for k in streak:
                if s[k] == "ok":
                    streak[k] = 0
                elif s[k] == "bad" and not in_grace:
                    streak[k] += 1
                    self.detail[k] = s["detail"].get(k, "")
                    if streak[k] >= 2:
                        return k
            if now >= end and not any(streak.values()):
                return None
            self.sleep(self.t.interval)

    def _index(self, web_dir):
        try:
            with open(os.path.join(web_dir, "index.html"), "rb") as f:
                return f.read()
        except OSError:
            return None

    # ---------- the rollback ----------

    def current_web(self):
        try:
            return os.path.realpath(os.path.join(self.cfg.web_dir, "current"))
        except OSError:
            return ""

    def live_now(self):
        rc, sha = self.git("rev-parse", "HEAD")
        return os.path.basename(self.current_web()), sha if rc == 0 else "unknown"

    def pins_differ(self):
        return bool(self.plan.get("pins_differ"))

    def preconditions(self):
        """Everything that can be checked before ccd is stopped. A miss changes nothing (ccd keeps running the new
        release) and returns (result, step, why); None means go."""
        p = self.plan
        prev = p.get("prev_web") or ""
        if not prev or prev == p["new_web"] or self._index(prev) is None:
            return NO_PREVIOUS, None, "no previous UI release with an index.html to go back to"
        rc, _ = self.git("cat-file", "-e", f"{p.get('from_sha') or 'x'}^{{commit}}")
        if rc != 0:
            return NO_PREVIOUS, None, "the previous commit is not in the checkout"
        rc, out = self.git("status", "--porcelain", "--untracked-files=no")
        if rc != 0 or out:
            return ROLLBACK_FAILED, "precondition", "tracked files in the checkout have changes"
        moved = self.moved()
        if moved:
            return ROLLBACK_FAILED, "moved", moved
        if self.pins_differ() and not (os.path.isfile(os.path.join(self.wheels, "old.txt"))
                                       and os.path.isfile(os.path.join(self.wheels, "new.txt"))
                                       and p.get("wheels_ok")):
            return ROLLBACK_FAILED, "precondition", "requirements differ but no local wheels were downloaded"
        prev_schema = p.get("prev_schema")
        if prev_schema is not None and os.path.isfile(self.db):
            rc, out = self.run([self.python, "-I", "-c", HELD_SNIPPET, os.path.join(self.cfg.repo, "server"),
                                self.db, str(prev_schema)], 60)
            try:
                info = json.loads(out.splitlines()[-1])
            except (ValueError, IndexError):
                return ROLLBACK_FAILED, "downgrade", f"could not read the database schema: {out[-200:]}"
            self.grew = info["current"] > prev_schema
            if info["missing"] or info["held"]:
                held = ", ".join(f"{t} ({n} rows)" for t, n in info["held"].items())
                return ROLLBACK_FAILED, "downgrade", (
                    f"the new release's tables hold rows ({held}); no automatic restore" if held else
                    f"migration v{info['missing'][0]} has no in-place downgrade")
        return None

    grew = False

    def moved(self):
        rc, head = self.git("rev-parse", "HEAD")
        if rc != 0 or head != self.plan["to_sha"]:
            return "the checkout is no longer at the release being rolled back"
        if self.current_web() != self.plan["new_web"]:
            return "web/current is no longer the release being rolled back"
        return ""

    def switch_link(self, target):
        """ln -sfn + mv -T, under deploy-web.sh's own lock so a UI deploy cannot interleave."""
        base = self.cfg.web_dir
        fd = os.open(os.path.join(base, ".deploy.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            for _ in range(10):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    self.sleep(1)
            else:
                raise StepFailed("link", ".deploy.lock is held (deploy-web.sh is running)")
            tmp = os.path.join(base, "current.next")
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            os.symlink(f"releases/{os.path.basename(target)}", tmp)
            os.replace(tmp, os.path.join(base, "current"))
        except OSError as e:
            raise StepFailed("link", str(e))
        finally:
            os.close(fd)

    def pip_from(self, name):
        # --no-index: a rollback never touches the network (CC-063); the wheels were downloaded during go-live.
        rc, out = self.run([self.pip, "install", "-q", "--no-index", "--find-links", self.wheels, "-r",
                            os.path.join(self.wheels, name)], 600)
        return rc, out

    def fall_back_to_target(self):
        """The old release did not come up: put the release that was running back (not a third one). Best effort;
        ccd is started afterwards whatever happened."""
        self.log("falling back to the release that was live a moment ago")
        self.systemctl("stop", "ccd")
        for what, fn in (
            ("checkout", lambda: self.git("switch", "-q", "--detach", self.plan["to_sha"])[0]),
            ("pip", lambda: self.pip_from("new.txt")[0] if self.pins_differ() else 0),
            ("link", lambda: self.switch_link(self.plan["new_web"])),
        ):
            try:
                if fn():
                    self.log(f"fallback {what} failed")
            except StepFailed as e:
                self.log(f"fallback {what} failed: {e.why}")
        self.systemctl("start", "ccd")

    def wait_answer(self, seconds):
        end = self.clock() + seconds
        while True:
            st, _ = self.get("/api/health", token=False)
            if st == 200:
                return True
            if self.clock() >= end:
                return False
            self.sleep(2)

    def roll_back(self):
        """(result, step, why). Stops ccd only after every precondition passed; starts it again on every path."""
        pre = self.preconditions()
        if pre:
            return pre
        p = self.plan
        self.systemctl("stop", "ccd")
        started = False
        try:
            if self.grew:
                rc, out = self.run([self.python, "-m", "ccd.migration_safety", "rollback", "--db", self.db, "--to",
                                    str(p["prev_schema"]), "--backup-dir",
                                    os.path.join(self.cfg.watch_dir, "db-backup")],
                                   300, cwd=os.path.join(self.cfg.repo, "server"))
                if rc != 0:
                    raise StepFailed("downgrade", out[-300:])
            moved = self.moved()
            if moved:
                raise StepFailed("moved", moved)
            rc, out = self.git("switch", "-q", "--detach", p["from_sha"])
            if rc != 0:
                raise StepFailed("checkout", out[-300:])
            if self.pins_differ():
                rc, out = self.pip_from("old.txt")
                if rc != 0:
                    self.systemctl("start", "ccd")
                    started = True
                    if self.wait_answer(self.t.answer_wait):
                        raise StepFailed("pip", "old pins did not install; ccd runs the previous code anyway")
                    self.fall_back_to_target()
                    raise StepFailed("pip", "old pins did not install and the previous code did not answer")
            try:
                self.switch_link(p["prev_web"])
            except StepFailed:
                self.systemctl("start", "ccd")
                started = True
                raise
            self.systemctl("start", "ccd")
            started = True
            bad = self.observe(self.t.verify_grace, self.t.verify_window, self._index(p["prev_web"]),
                               p.get("prev_schema"))
            if bad:
                self.fall_back_to_target()
                raise StepFailed("verify", f"the previous release failed {bad}")
            return ROLLED_BACK, None, ""
        except StepFailed as e:
            return ROLLBACK_FAILED, e.step, e.why
        finally:
            if not started:
                # Restart=always does not restart a stopped unit: ccd must never be left down by this script.
                self.systemctl("start", "ccd")

    # ---------- result, lock, Messages ----------

    def _write_json(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    def short(self, sha):
        return (sha or "")[:7]

    def alert_text(self, result, step, why, check):
        p = self.plan
        new = f"{os.path.basename(p['new_web'])} ({self.short(p['to_sha'])})"
        name, sha = self.live_now()
        if result == ROLLED_BACK:
            return f"Rollback: release {new} failed {check}; live is now {name} ({self.short(sha)})."
        if result == NO_PREVIOUS:
            return (f"Rollback: release {new} failed {check}; there is no previous release to go back to, "
                    f"so nothing was changed ({why}). Live is still {new}.")
        text = (f"Rollback FAILED at {step}: release {new} failed {check}; live is now {name} ({self.short(sha)}). "
                f"{why}. ")
        if step == "downgrade":
            text += (f"ccd was left running on the new release; the database backup is {p.get('backup') or 'in '
                     '~/command-center/backups'}. ")
        return text + f"Recovery steps: {RUNBOOK}"

    def acquire_lock(self):
        os.makedirs(self.cfg.deploys_dir, exist_ok=True)
        fd = os.open(os.path.join(self.cfg.deploys_dir, ".go-live.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        end = self.clock() + self.t.lock_wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_fd = fd
                return True
            except OSError:
                if self.clock() >= end:
                    os.close(fd)
                    return False
                self.sleep(1)

    def release_lock(self):
        # Once the verdict is final: a fix release must not wait for the 30-minute Messages retry.
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        path = os.path.join(self.cfg.deploys_dir, "watch", "active.json")
        try:
            with open(path) as f:
                if json.load(f).get("unit") == self.plan.get("unit"):
                    os.unlink(path)
        except (OSError, ValueError):
            pass

    def notify(self, text):
        """(notified, attempts). One Messages line as the lead; 2xx stops, 4xx other than 408/429 stops with
        notified=false, everything else (ccd down, 429, 5xx) is retried with backoff for 30 minutes."""
        body = json.dumps({"text": text}).encode()
        spent, delay, attempts = 0, self.t.backoff_first, 0
        while True:
            attempts += 1
            try:
                headers = {"X-CCD-Token": self._read_token(), "X-CCD-Actor": ACTOR,
                           "Content-Type": "application/json"}
            except OSError as e:
                self.log(f"cannot read the ccd token: {e}")
                return False, attempts
            st, _ = self._http("POST", f"/api/chat/{CONVERSATION}/messages", headers, body, self.t.http_timeout)
            if st is not None and 200 <= st < 300:
                return True, attempts
            if st is not None and 400 <= st < 500 and st not in (408, 429):
                self.log(f"Messages refused the post ({st}); not retrying")
                return False, attempts
            if spent + delay > self.t.notify_total:
                return False, attempts
            self.sleep(delay)
            spent += delay
            delay = min(delay * 2, self.t.backoff_cap)

    def finish(self, result, step, why, check):
        p = self.plan
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.wall())), "from": p.get("from_sha"),
               "to": p["to_sha"], "checks": self.checks, "restarts": self.restarts, "result": result, "step": step,
               "check": check, "reason": why, "notified": None, "attempts": 0}
        res_path = os.path.join(self.cfg.watch_dir, "result.json")
        self._write_json(res_path, rec)            # go-live.sh is polling for this file
        self.release_lock()
        if result != HEALTHY:
            text = self.alert_text(result, step, why, check)
            rec["message"] = text
            rec["notified"], rec["attempts"] = self.notify(text)
            self._write_json(res_path, rec)
        with open(os.path.join(self.cfg.deploys_dir, "releases.jsonl"), "a") as f:
            f.write(json.dumps({k: rec[k] for k in ("at", "from", "to", "checks", "restarts", "result", "step",
                                                    "notified", "attempts")}) + "\n")
        return rec

    def run_all(self):
        p = self.plan
        check, result, step, why = None, HEALTHY, None, ""
        if not self.acquire_lock():
            # A go-live is still mid-deploy: never switch under it.
            result, step, why, check = ROLLBACK_FAILED, "lock", "the go-live lock is held by another run", "none"
        else:
            try:
                check = self.observe(self.t.grace, self.t.window, self._index(p["new_web"]), p.get("new_schema"))
                if check:
                    first = self.detail.get(check, "")   # the verify pass below overwrites self.detail
                    self.log(f"release failed {check}: {first}; rolling back")
                    result, step, why = self.roll_back()
                    why = why or first
                else:
                    self.log("release healthy")
            except Exception as e:   # noqa: BLE001 - whatever happens, ccd must end up started
                self.systemctl("start", "ccd")
                result, step, why = ROLLBACK_FAILED, "error", f"{type(e).__name__}: {e}"
                check = check or "error"
        return self.finish(result, step, why, check or "none")


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: release_watch.py <watch dir>")
    watch_dir = os.path.abspath(argv[1])
    with open(os.path.join(watch_dir, "plan.json")) as f:
        plan = json.load(f)
    Watcher(Config(os.environ, watch_dir), plan).run_all()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
