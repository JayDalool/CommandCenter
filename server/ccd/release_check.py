"""Release check (CC-063): after scripts/go-live.sh restarts ccd, watch the new release for about 3 minutes and ALERT.

    python3 -I server/ccd/release_check.py --port 7777 --web-dir DIR --new-dir DIR/releases/<x> --steps-file F
        --log-file releases.jsonl --token-file F --from SHA --to SHA --web NAME --prev-web NAME
        [--old-pid N] [--herdr-ok true|false|unknown]

It changes nothing. Its only subprocess is `systemctl --user show ccd`; it never deploys, restarts, stops, rolls
back, switches git or web/current, runs pip or npm, or writes tasks.db. A wrong verdict costs one false or missed
alert, never a broken release (Jay's choice after #144 failed two Codex rounds on automatic rollback, Q197).

Run as a file, not as a module: it imports no ccd code, so a half-switched checkout cannot break the check itself.

Exit: 0 healthy, 3 failed, 4 inconclusive, 2 cannot run. Healthy prints one line; otherwise the alert (with the
rollback steps from go-live) goes to stdout and, once, to Jay's Messages as the project lead.
"""
import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time

GRACE_S, WINDOW_S, INTERVAL_S, SLACK_S = 30, 120, 10, 30   # hard deadline = grace + window + slack
REQ_BUDGET_S = 5
STREAK_TO_FAIL = 2      # one bad sample never fails a release alone
REASON_MAX = 200
NOTIFY_ATTEMPTS, NOTIFY_WINDOW_S = 3, 30
MAX_BODY = 16_000_000
EXIT = {"healthy": 0, "failed": 3, "inconclusive": 4}
CHECKS = ("api", "daemon", "ui")


def loopback_http(port, method, path, headers=None, body=None, timeout=REQ_BUDGET_S):
    """(status, bytes), or (None, b"") when nothing complete arrived within `timeout` seconds in total.

    Plain http.client to 127.0.0.1: no proxy from the environment and no redirects, so the ccd token can only ever
    reach loopback. The budget covers connect, headers AND body: http.client's own timeout is per recv, so a server
    trickling header bytes would stretch it (Codex r2 on #144). getresponse() cannot be interrupted from inside, so
    a timer closes the socket at the deadline, which makes the blocked recv return at once."""
    holder = {}
    done = threading.Event()

    def work():
        try:
            holder["r"] = _tracked_http(port, method, path, headers, body, timeout, holder)
        finally:
            done.set()
    t = threading.Thread(target=work, daemon=True)
    t.start()
    if not done.wait(timeout):
        conn = holder.get("conn")
        try:
            if conn is not None and conn.sock is not None:
                conn.sock.close()
        except OSError:
            pass
        done.wait(1)
        return None, b""
    return holder.get("r", (None, b""))


def _tracked_http(port, method, path, headers, body, timeout, holder):
    deadline = time.monotonic() + timeout
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    holder["conn"] = conn
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = b""
        while True:
            if time.monotonic() > deadline:
                return None, b""
            chunk = resp.read1(65536)
            if not chunk:
                return resp.status, data
            data += chunk
            if len(data) > MAX_BODY:
                return None, b""
    except (OSError, http.client.HTTPException, ValueError):
        return None, b""
    finally:
        conn.close()


def systemctl_show():
    """{ActiveState, MainPID, NRestarts} from the one subprocess this check runs; None when it cannot answer."""
    try:
        r = subprocess.run(["systemctl", "--user", "show", "ccd", "-p", "ActiveState", "-p", "MainPID",
                            "-p", "NRestarts"], capture_output=True, text=True, timeout=REQ_BUDGET_S)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    kv = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)

    def num(k):
        try:
            return int(kv.get(k, ""))
        except ValueError:
            return None
    return {"active": kv.get("ActiveState", ""), "pid": num("MainPID"), "restarts": num("NRestarts")}


def cut(text, n=REASON_MAX):
    return " ".join(str(text).split())[:n]


class Check:
    """One watch. Every outside effect is a parameter, so tests run it on a fake clock with no sleeping."""

    def __init__(self, *, http, unit, new_dir, old_pid=None, herdr_ok=None, clock=time.monotonic, sleep=time.sleep,
                 grace=GRACE_S, window=WINDOW_S, interval=INTERVAL_S, slack=SLACK_S):
        self.http, self.unit, self.new_dir = http, unit, new_dir
        self.old_pid, self.herdr_ok = old_pid, herdr_ok
        self.clock, self.sleep = clock, sleep
        self.grace, self.window, self.interval = grace, window, interval
        self.start = clock()
        self.deadline = self.start + grace + window + slack   # monotonic: a wall-clock jump cannot stretch it
        self.samples = 0
        self.streak = dict.fromkeys(CHECKS, 0)
        self.ok_streak = 0
        self.last = {}

    def left(self):
        return self.deadline - self.clock()

    def budget(self):
        return max(0.1, min(REQ_BUDGET_S, self.left()))

    def get(self, path):
        return self.http("GET", path, {}, None, self.budget())

    # ---- the three checks; each returns a reason string, or "" when it is fine ----
    def check_api(self):
        status, body = self.get("/api/health")
        self.health = None
        if status != 200:
            return "GET /api/health gave " + ("no answer" if status is None else f"HTTP {status}")
        try:
            h = json.loads(body)
        except ValueError:
            return "/api/health did not return JSON"
        if not isinstance(h, dict):
            return "/api/health did not return a JSON object"
        self.health = h
        return ""

    def check_daemon(self, state):
        if state is None:
            return "systemctl could not report the ccd unit"
        if state["active"] != "active":
            return f"the ccd unit is {state['active'] or 'unknown'}, not active"
        pid = state["pid"]
        if self.old_pid and pid == self.old_pid:
            return f"ccd is still the pre-restart process (pid {pid})"
        h = self.health
        if h is not None:
            if h.get("pid") != pid:
                return f"/api/health pid {h.get('pid')} is not the unit's MainPID {pid}"
            # herdr is not part of a release: judged only if it was healthy before the restart.
            herdr = h.get("herdr") if isinstance(h.get("herdr"), dict) else {}
            if self.herdr_ok is True and herdr.get("ok") is not True:
                return "herdr was connected before the restart and is not now"
        return ""

    def check_ui(self):
        try:
            with open(os.path.join(self.new_dir, "index.html"), "rb") as f:
                want = f.read()
        except OSError:
            return "the new release has no readable index.html"
        status, body = self.get("/")
        if status is None:
            return "GET / gave no answer"
        if status != 200:
            return f"GET / gave HTTP {status}"
        if body != want:
            return "GET / is not the new release's index.html"
        for asset in sorted(set(re.findall(rb"""(?:src|href)=["'](/assets/[^"'?#]+)""", want))):
            status, _ = self.get(asset.decode("ascii", "replace"))
            if status != 200:
                return f"{asset.decode('ascii', 'replace')} gave " + ("no answer" if status is None else f"HTTP {status}")
        return ""

    def sample(self):
        """One pass over the three checks -> ({check: reason}, crashed_reason)."""
        self.samples += 1
        bad = {}
        api = self.check_api()
        if api:
            bad["api"] = api
        state = self.unit()
        crash = ""
        # An explicit restart resets NRestarts to 0, so any rise is systemd restarting a crashed ccd. The baseline is
        # 0, never the first read: a crash before the first read must not be absorbed (tech review).
        if state and state["restarts"] and state["restarts"] > 0:
            crash = f"ccd crashed and was restarted by systemd (NRestarts {state['restarts']})"
        daemon = crash or self.check_daemon(state)
        if daemon:
            bad["daemon"] = daemon
        ui = self.check_ui()
        if ui:
            bad["ui"] = ui
        return bad, crash

    def run(self):
        """-> (result, {check: reason}). Ends by the hard deadline on every path."""
        while True:
            if self.left() <= 0:
                return "inconclusive", {"-": "no steady verdict before the deadline: " + cut(self.describe())}
            bad, crash = self.sample()
            elapsed = self.clock() - self.start
            counting = elapsed >= self.grace      # bad samples in the grace period do not count
            for c in CHECKS:
                self.streak[c] = self.streak[c] + 1 if (c in bad and counting) else 0
            self.last = bad
            self.ok_streak = 0 if bad else self.ok_streak + 1
            if crash:
                return "failed", {"daemon": crash}
            failed = {c: bad[c] for c in CHECKS if c in bad and self.streak[c] >= STREAK_TO_FAIL}
            if failed:
                return "failed", failed
            # Two clean samples in a row, like two bad ones to fail: alternating samples never settle (CC-063).
            if elapsed >= self.grace + self.window and self.ok_streak >= STREAK_TO_FAIL:
                return "healthy", {}
            if self.left() <= 0:
                continue
            self.sleep(max(0, min(self.interval, self.left())))

    def describe(self):
        return "; ".join(f"{c}: {r}" for c, r in self.last.items()) or "samples kept alternating"


# ---- alert, log, notify ----
def alert_text(result, bad, to, to_sha, steps):
    what = "; ".join(f"{c}: {r}" for c, r in bad.items())
    head = ("Release check FAILED" if result == "failed" else "Release check INCONCLUSIVE")
    kind = ("failed " + ", ".join(c for c in bad if c != "-")) if result == "failed" else "gave no steady verdict"
    return (f"{head}: {to} ({to_sha[:7]}) {kind}: {cut(what, 600)}. "
            "Nothing was changed; the new release is still live.\n" + steps.strip())


def append_log(path, entry):
    """One O_APPEND write: two writers cannot interleave inside a line."""
    data = (json.dumps(entry, separators=(",", ":")) + "\n").encode()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def notify(post, text, clock=time.monotonic, sleep=time.sleep):
    """Up to 3 attempts within 30 s; True when Messages took it. When ccd is down this is False and the pane is
    the only place Jay sees it (Jay chose that, Q208)."""
    end = clock() + NOTIFY_WINDOW_S
    for i in range(NOTIFY_ATTEMPTS):
        if post(text):
            return True
        if i < NOTIFY_ATTEMPTS - 1:
            if clock() + 5 >= end:
                break
            sleep(5)
    return False


def make_post(port, token_file, conv, http):
    def post(text):
        try:
            with open(token_file) as f:
                token = f.read().strip()
        except OSError:
            return False
        headers = {"Host": f"127.0.0.1:{port}", "X-CCD-Token": token, "X-CCD-Actor": f"agent:lead-{conv}",
                   "Content-Type": "application/json"}
        status, _ = http("POST", f"/api/chat/{conv}/messages", headers, json.dumps({"text": text}).encode(),
                         REQ_BUDGET_S)
        return status is not None and 200 <= status < 300
    return post


def main(argv=None):
    p = argparse.ArgumentParser(prog="release_check")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--new-dir", required=True, help="the new UI release directory (holds index.html)")
    p.add_argument("--steps-file", required=True, help="the rollback steps go-live wrote; shown in the alert")
    p.add_argument("--log-file", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--conversation", default="commandcenter")
    p.add_argument("--from", dest="from_sha", default="")
    p.add_argument("--to", dest="to_sha", required=True)
    p.add_argument("--web", default="")
    p.add_argument("--prev-web", default="")
    p.add_argument("--old-pid", type=int, default=0)
    p.add_argument("--herdr-ok", choices=("true", "false", "unknown"), default="unknown")
    # Test-only timings; go-live never passes them.
    for name, default in (("grace", GRACE_S), ("window", WINDOW_S), ("interval", INTERVAL_S), ("slack", SLACK_S)):
        p.add_argument(f"--{name}", type=float, default=default, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        with open(a.steps_file) as f:
            steps = f.read()
    except OSError as e:
        print(f"release check cannot run: {e.strerror}", file=sys.stderr)
        return 2
    http = lambda m, path, h, b, t: loopback_http(a.port, m, path, h, b, t)  # noqa: E731
    chk = Check(http=http, unit=systemctl_show, new_dir=a.new_dir, old_pid=a.old_pid or None,
                herdr_ok={"true": True, "false": False}.get(a.herdr_ok),
                grace=a.grace, window=a.window, interval=a.interval, slack=a.slack)
    result, bad = chk.run()
    notified = False
    text = ""
    if result != "healthy":
        text = alert_text(result, bad, a.web or os.path.basename(a.new_dir), a.to_sha, steps)
        notified = notify(make_post(a.port, a.token_file, a.conversation, http), text)
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "from": a.from_sha, "to": a.to_sha, "web": a.web,
             "prevWeb": a.prev_web, "result": result, "check": ",".join(c for c in bad if c != "-"),
             "reason": cut("; ".join(bad.values())), "samples": chk.samples, "notified": notified}
    try:
        append_log(a.log_file, entry)
    except OSError as e:
        print(f"release check: could not write the release log: {e.strerror}", file=sys.stderr)
    if result == "healthy":
        print("release check: healthy")
    else:
        print(text)
        if not notified:
            print("(not sent to Messages: ccd did not take it; it is logged as notified=false)")
    return EXIT[result]


if __name__ == "__main__":
    sys.exit(main())
