#!/usr/bin/env python3
"""Live canary for ccd. Read-mostly; never touches herdr itself or any agent.

  ccd-canary.py check                 1 herdr == /api/state · 2 coordinators · 9 no secrets · 10 loopback only
  ccd-canary.py stop-start            3 stop ccd → agents survive · 4 restart → state reconstructs
  ccd-canary.py ws-listen SECONDS     5 print agent events as they arrive (run, then cause a change)
  ccd-canary.py replay SINCE          6 reconnect with ?since= and time the replay
  ccd-canary.py degrade               7 herdr unreachable · 8 GitHub unreachable (see below)
  ccd-canary.py measure SECONDS       RSS, idle CPU, latency, call rates, DB size

`degrade` stops the ccd unit, runs ccd in the foreground with
  CCD_HERDR_SOCKET -> a private unix-socket relay to the real herdr socket
                      (0700 directory, same user, never TCP), and
  GH_HOST=github.invalid so every gh call fails without touching gh's config,
then kills the relay to make herdr unreachable, brings it back, and finally
restarts the normal unit. herdr and every agent are untouched throughout.

Prints PASS/FAIL lines; exits 1 if anything failed.
"""
import asyncio
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:7777"
TOKEN = Path.home().joinpath(".config/command-center/ccd.token").read_text().strip()
HERDR = str(Path.home() / ".config/herdr/herdr.sock")
SERVER = Path(__file__).resolve().parents[1] / "server"
PY = str(SERVER / ".venv/bin/python")
FAILED = []


def ok(cond, label, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""), flush=True)
    if not cond:
        FAILED.append(label)
    return cond


def get(path, auth=True, timeout=10):
    headers = {"X-CCD-Token": TOKEN} if auth else {}
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=headers), timeout=timeout) as r:
        return json.loads(r.read())


def wait_health(timeout=40, need_gh=True):
    end = time.time() + timeout
    while time.time() < end:
        try:
            h = get("/api/health", auth=False, timeout=2)
            if h["ok"] and (not need_gh or all(v["asOf"] for v in h["gh"]["projects"].values())):
                return h
        except OSError:
            pass
        time.sleep(0.25)
    return None


def herdr_agents():
    out = subprocess.run(["herdr", "agent", "list"], capture_output=True, text=True, timeout=10).stdout
    return {a["pane_id"]: {"name": a.get("name"), "status": a["agent_status"], "session": a["agent_session"]["value"]}
            for a in json.loads(out)["result"]["agents"]}


def claude_pids():
    out = subprocess.run(["pgrep", "-a", "-x", "claude"], capture_output=True, text=True).stdout
    return {int(l.split()[0]): l.split(None, 1)[1] for l in out.splitlines() if l.strip()}


def ccd_pid():
    out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", "ccd.service"],
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() and int(out) > 0 else None


# ---------- check: 1, 2, 9, 10 ----------

def check():
    print("1  herdr agent list vs /api/state")
    h = herdr_agents()
    st = get("/api/state")
    api = {a["id"]: {"name": a["agent_name"], "status": a["status"], "session": a["session_id"]} for a in st["agents"]}
    ok(set(h) == set(api), "same agent panes", f"herdr={sorted(h)} api={sorted(api)}")
    ok(all(h[k]["name"] == api[k]["name"] and h[k]["session"] == api[k]["session"] for k in h if k in api),
       "same names and Claude session ids")
    drift = {k: (h[k]["status"], api[k]["status"]) for k in h if k in api and h[k]["status"] != api[k]["status"]}
    ok(not drift, "same status", str(drift) if drift else "")

    print("2  samvision and gauzemate")
    by = {a["agent_name"]: a for a in st["agents"]}
    for name in ("samvision", "gauzemate"):
        a = by.get(name)
        ok(bool(a) and a["project"] == name and a["role"] == "coordinator",
           f"{name}: detected, project {name}, role coordinator",
           f"{a['id']} {a['status']}" if a else "missing")
        ok(st["coordinators"][name]["canonical"], f"{name}: canonical herdr name")

    print("9  no secrets or licensed data in the API")
    blobs = {"health": json.dumps(get("/api/health", auth=False)), "state": json.dumps(st),
             "activity": json.dumps(get("/api/activity?limit=1000"))}
    patterns = [r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_", r"sk-[A-Za-z0-9_-]{20,}",
                r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s'\",]{6,}",
                r"(?i)bearer\s+[A-Za-z0-9._-]{10,}", r"BEGIN [A-Z ]*PRIVATE KEY", r"postgres(ql)?://[^\s:@]+:[^\s@]+@",
                r"ntfy\.sh/"]
    for name, blob in blobs.items():
        hits = [p for p in patterns if re.search(p, blob)]
        ok(not hits and TOKEN not in blob, f"{name}: no credential-shaped values, no ccd token", ",".join(hits))
    legacy = json.loads(Path.home().joinpath("command-center/board/config.json").read_text())
    topic = (legacy.get("ntfy_url") or "").rsplit("/", 1)[-1]
    if topic and len(topic) > 4:
        ok(all(topic not in b for b in blobs.values()), "configured ntfy topic never served (value not printed)")
    ok("terminal_title" not in blobs["state"], "terminal titles excluded (they can quote a conversation)")
    addr = re.findall(r"\b\d{2,5} [A-Z][a-z]+ (?:St|Ave|Rd|Blvd|Dr|Cres|Way)\b", blobs["state"] + blobs["activity"])
    ok(not addr, "no street-address-shaped strings (heuristic)", ", ".join(addr[:3]))
    db = Path.home() / "command-center/state/ccd.db"
    dump = subprocess.run(["sqlite3", str(db), ".dump"], capture_output=True, text=True).stdout if shutil.which("sqlite3") else ""
    if not dump:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        dump = json.dumps([list(r) for t in ("events", "kv", "alerts") for r in con.execute(f"SELECT * FROM {t}")])
        con.close()
    hits = [p for p in patterns if re.search(p, dump)]
    ok(not hits and TOKEN not in dump, "SQLite log: no credential-shaped values", ",".join(hits))
    tail = get(f"/api/agents/{st['agents'][0]['id']}/tail?lines=5")
    ok("text" in tail and "redactions" in tail, "tail is served on demand with a redaction count",
       f"{tail.get('redactions')} redacted")
    ok(tail["text"][:40] not in dump if tail["text"].strip() else True, "tail text is not in the SQLite log")

    print("10 listening on loopback only")
    pid = ccd_pid()
    ss = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True).stdout
    mine = [l for l in ss.splitlines() if f"pid={pid}," in l]
    addrs = sorted({l.split()[3] for l in mine})
    ok(addrs == ["127.0.0.1:7777"], "ccd's only listener is 127.0.0.1:7777", ", ".join(addrs))
    ips = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    for ip in ips:
        if ":" in ip:
            continue
        s = socket.socket()
        s.settimeout(1)
        refused = s.connect_ex((ip, 7777)) != 0
        s.close()
        ok(refused, f"{ip}:7777 refuses connections")
    r = urllib.request.Request(BASE + "/api/state", headers={"X-CCD-Token": TOKEN, "Host": "evil.example:7777"})
    try:
        urllib.request.urlopen(r, timeout=5)
        ok(False, "foreign Host header refused")
    except urllib.error.HTTPError as e:
        ok(e.code == 403, "foreign Host header refused (DNS rebinding)", str(e.code))
    try:
        urllib.request.urlopen(urllib.request.Request(BASE + "/api/state"), timeout=5)
        ok(False, "no token → refused")
    except urllib.error.HTTPError as e:
        ok(e.code == 401, "no token → 401", str(e.code))


# ---------- stop-start: 3, 4 ----------

def stop_start():
    print("3  stop ccd → agents survive")
    before_h, before_c = herdr_agents(), claude_pids()
    st = get("/api/state")
    seq_before, gh_asof = st["latestSeq"], {k: v["asOf"] for k, v in st["sources"]["github"].items()}
    t0 = time.time()
    subprocess.run(["systemctl", "--user", "stop", "ccd.service"], check=True)
    stopped = subprocess.run(["systemctl", "--user", "is-active", "ccd.service"], capture_output=True, text=True).stdout.strip()
    ok(stopped in ("inactive", "failed"), "ccd stopped", stopped)
    s = socket.socket()
    ok(s.connect_ex(("127.0.0.1", 7777)) != 0, "port 7777 closed")
    s.close()
    after_h, after_c = herdr_agents(), claude_pids()
    ok(after_h == before_h, "herdr agent list unchanged (names, status, sessions)")
    ok(set(before_c) <= set(after_c), "every Claude process still running", f"{len(after_c)} claude pids")

    print("4  restart ccd → state reconstructs")
    subprocess.run(["systemctl", "--user", "start", "ccd.service"], check=True)
    h = wait_health(need_gh=False)
    ok(h is not None, "health ok after restart", f"{time.time() - t0:.1f}s from stop")
    st2 = get("/api/state")
    ok({a["id"] for a in st2["agents"]} == set(before_h), "same agents rebuilt from session.snapshot")
    ok(st2["latestSeq"] > seq_before, "event seq continues from the log", f"{seq_before} → {st2['latestSeq']}")
    ok(all(st2["sources"]["github"][k]["asOf"] for k in gh_asof), "GitHub data present at once (last-good from SQLite)")
    kinds = [e["kind"] for e in get(f"/api/activity?since={seq_before}")["events"]]
    ok("daemon.stopped" in kinds and "daemon.started" in kinds, "stop and start are both logged")


# ---------- ws: 5, 6 ----------

async def _ws(path):
    import websockets
    return await websockets.connect(f"ws://127.0.0.1:7777{path}", additional_headers={"X-CCD-Token": TOKEN},
                                    open_timeout=5)


async def ws_listen(seconds):
    ws = await _ws("/api/events")
    hello = json.loads(await ws.recv())
    print(f"hello seq={hello['seq']}", flush=True)
    end = time.time() + seconds
    seen = 0
    try:
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.1, end - time.time())))
            except asyncio.TimeoutError:
                break
            if msg["type"] == "event" and msg["event"]["kind"].startswith("agent."):
                e = msg["event"]
                seen += 1
                print(f"{time.strftime('%H:%M:%S')} seq={e['seq']} {e['kind']} {e['agentId']} "
                      f"{e['data'].get('from')}→{e['data'].get('to')}", flush=True)
    finally:
        await ws.close()
    print(f"agent events received: {seen}")


async def replay(since):
    print("6  WS reconnect / replay")
    t0 = time.perf_counter()
    ws = await _ws(f"/api/events?since={since}")
    got = []
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if msg["type"] == "replay_done":
            break
        if msg["type"] == "events_lost":
            ok(False, "replay", "events_lost")
            return
        got.append(msg["event"])
    elapsed = (time.perf_counter() - t0) * 1000
    await ws.close()
    seqs = [e["seq"] for e in got]
    ok(bool(got), f"replayed {len(got)} events after seq {since}", ", ".join(e["kind"] for e in got[:6]))
    ok(seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "in order, no duplicates")
    ok(any(e["kind"] == "agent.state_changed" for e in got), "includes the agent state change")
    print(f"  reconnect + replay: {elapsed:.0f} ms")


# ---------- degrade: 7, 8 ----------

LIVE = set()  # relayed connections; a real herdr death closes all of them, so the relay must too


async def _relay(path):
    async def pipe(r, w):
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            w.close()

    async def handle(cr, cw):
        try:
            hr, hw = await asyncio.open_unix_connection(HERDR)
        except OSError:
            cw.close()
            return
        LIVE.update((cw, hw))
        try:
            await asyncio.gather(pipe(cr, hw), pipe(hr, cw))
        finally:
            LIVE.discard(cw)
            LIVE.discard(hw)

    return await asyncio.start_unix_server(handle, path=path)


def degrade():
    d = tempfile.mkdtemp(prefix="ccd-canary-")
    os.chmod(d, 0o700)
    relay_path = os.path.join(d, "herdr.sock")
    loop = asyncio.new_event_loop()
    import threading
    state = {}

    def run_relay():
        asyncio.set_event_loop(loop)
        state["server"] = loop.run_until_complete(_relay(relay_path))
        loop.run_forever()

    t = threading.Thread(target=run_relay, daemon=True)
    t.start()
    while not os.path.exists(relay_path):
        time.sleep(0.05)
    subprocess.run(["systemctl", "--user", "stop", "ccd.service"], check=True)
    env = dict(os.environ, CCD_HERDR_SOCKET=relay_path, GH_HOST="github.invalid")
    proc = subprocess.Popen([PY, "-m", "ccd"], cwd=str(SERVER), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        h = wait_health(need_gh=False)
        print("8  GitHub unreachable keeps last-good state")
        st = get("/api/state")
        end = time.time() + 30
        while time.time() < end:
            st = get("/api/state")
            if all(v["error"] for v in st["sources"]["github"].values()):
                break
            time.sleep(0.5)
        errs = {k: v["error"] for k, v in st["sources"]["github"].items()}
        ok(all(errs.values()), "every repo reports its GitHub error", next(iter(errs.values()))[:70])
        ok(all(v["asOf"] for v in st["sources"]["github"].values()), "last-good timestamps kept")
        prs = sum(len(v["prs"]) for v in st["projects"])
        ok(prs > 0, f"PRs still shown from last-good data ({prs})")
        ok(any("showing data as of" in " ".join(v.get("errors", [])) for v in st["projects"]),
           "each project says its data is stale and from when")
        ok(get("/api/health", auth=False)["gh"]["ok"] is False, "health reports gh not ok")

        print("7  herdr unreachable degrades cleanly")
        agents_before = {a["id"] for a in st["agents"]}
        hh = get("/api/health", auth=False)
        def herdr_dies():
            state["server"].close()
            for w in list(LIVE):
                w.close()
        loop.call_soon_threadsafe(herdr_dies)
        os.unlink(relay_path)
        # existing relayed connections die with their peer side closed
        end = time.time() + 15
        while time.time() < end:
            hh = get("/api/health", auth=False)
            if not hh["herdr"]["ok"]:
                break
            time.sleep(0.25)
        ok(not hh["herdr"]["ok"], "health: herdr not ok", (hh["herdr"]["error"] or "")[:60])
        time.sleep(1)
        st = get("/api/state")
        ok({a["id"] for a in st["agents"]} == agents_before, "last known agents still listed")
        ok({a["status"] for a in st["agents"]} == {"unknown"}, "their state shown as unknown, not guessed")
        ok((st["herdr_error"] or "").startswith("herdr unreachable"), "header text: herdr unreachable")
        ok(any(a["id"] == "daemon:herdr" for a in st["alerts"]), "alert raised")
        ok(sum(len(v["prs"]) for v in st["projects"]) > 0, "GitHub-side data still served")
        ok(herdr_agents().keys() == agents_before, "real herdr and its agents untouched")
        state["server"] = asyncio.run_coroutine_threadsafe(_relay(relay_path), loop).result(5)
        end = time.time() + 40
        while time.time() < end:
            if get("/api/health", auth=False)["herdr"]["ok"]:
                break
            time.sleep(0.25)
        ok(get("/api/health", auth=False)["herdr"]["ok"], "herdr back → recovered without a restart")
    finally:
        proc.terminate()
        proc.wait(10)
        loop.call_soon_threadsafe(loop.stop)
        subprocess.run(["systemctl", "--user", "start", "ccd.service"], check=True)
        wait_health(need_gh=False)
        shutil.rmtree(d, ignore_errors=True)
        print("  normal ccd unit restarted")


# ---------- measure ----------

def measure(seconds):
    pid = ccd_pid()

    def cpu_ticks():
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])

    def rss_kb():
        for l in Path(f"/proc/{pid}/status").read_text().splitlines():
            if l.startswith("VmRSS:"):
                return int(l.split()[1])

    h0, t0, c0 = get("/api/health", auth=False), time.time(), cpu_ticks()
    lat = {"health": [], "state": []}
    for _ in range(40):
        for name, path, auth in (("health", "/api/health", False), ("state", "/api/state", True)):
            s = time.perf_counter()
            get(path, auth=auth)
            lat[name].append((time.perf_counter() - s) * 1000)
    c_after_lat = cpu_ticks()
    time.sleep(max(0, seconds - (time.time() - t0)))
    h1, t1, c1 = get("/api/health", auth=False), time.time(), cpu_ticks()
    hz = os.sysconf("SC_CLK_TCK")
    idle_cpu = 100.0 * ((c1 - c_after_lat) / hz) / (t1 - t0 - 0.0)
    hours = (t1 - t0) / 3600
    calls = {k: (h1["calls"].get(k, 0) - h0["calls"].get(k, 0)) / hours for k in set(h1["calls"]) | set(h0["calls"])}
    mem_cur = subprocess.run(["systemctl", "--user", "show", "-p", "MemoryCurrent", "--value", "ccd.service"],
                             capture_output=True, text=True).stdout.strip()
    db = Path.home() / "command-center/state/ccd.db"
    print(json.dumps({
        "window_s": round(t1 - t0),
        "rss_mb": round(rss_kb() / 1024, 1),
        "cgroup_memory_mb": round(int(mem_cur) / 2**20, 1) if mem_cur.isdigit() else None,
        "idle_cpu_pct": round(idle_cpu, 2),
        "latency_ms": {k: {"p50": round(statistics.median(v), 1), "p95": round(sorted(v)[int(len(v) * .95) - 1], 1)}
                       for k, v in lat.items()},
        "calls_per_hour_observed": {k: round(v) for k, v in sorted(calls.items())},
        "db_bytes": h1["dbBytes"], "db_file_bytes": db.stat().st_size,
        "events": h1["seq"],
    }, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        check()
    elif cmd == "stop-start":
        stop_start()
    elif cmd == "ws-listen":
        asyncio.run(ws_listen(float(sys.argv[2])))
    elif cmd == "replay":
        asyncio.run(replay(int(sys.argv[2])))
    elif cmd == "degrade":
        degrade()
    elif cmd == "measure":
        measure(float(sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(2)
    if FAILED:
        print(f"\nFAILED: {len(FAILED)}")
        sys.exit(1)
