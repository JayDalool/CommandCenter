"""The daemon: caches every source, derives one state, publishes what changed.

    herdr  events.subscribe (push) + session.snapshot (bootstrap, every
           reconnect, and every `reconcile_seconds`)        → agents
    gh     one GraphQL call per repo, every `github_seconds` → PRs, tasks, CI
    git    unpushed branches + worktrees, every `git_seconds`
    host   /proc + docker ps + disk, every `host_seconds`; OOM every 10 min

Every source keeps its last good value. A failing source marks itself in
`sources` and in /api/health, and never blanks what it supplied before.

ccd owns no agent. If it stops, nothing in herdr notices; when it starts, it
rebuilds everything from session.snapshot, GitHub and its own SQLite log, and
emits events for whatever changed while it was down.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from . import __version__, coordinators, model, sources
from . import herdr as herdr_mod
from . import importer
from . import tasks as tasks_mod
from .config import STATE_DIR, public_project

log = logging.getLogger("ccd")

STRUCTURAL_EVENTS = {t.replace(".", "_") for t in herdr_mod.STRUCTURAL}
DISPATCH_VERBS = ("plan", "implement", "review", "verify", "continue", "stop")
TASK_ID_RE = re.compile(r"^(?:(?:SV|GYST-VN|MFE|GM)-\d{1,5}|#\d{1,6})$")
# A ticket key from tasks.db (CC-012, GYST-021) is also a valid dispatch target,
# but only when that ticket exists; the shape alone is not enough.
TICKET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}-\d{1,6}$")
# Automatic ticket transitions. Each has one deterministic trigger; nothing is inferred.
CREATE_FIELDS = {"description", "status", "priority", "type", "assignee", "agentRole", "parent", "branch", "labels",
                 "flags", "dueAt", "estimate"} | set(tasks_mod.FLAGS)
DISPATCH_TRANSITIONS = {"plan": (("INBOX", "PROPOSED"), "RESEARCHING"),
                        "implement": (("READY_TO_IMPLEMENT",), "IN_PROGRESS")}
ANSWER_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,2000}$")
NOTE_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,500}$")
# The dispatch skill's message, verbatim apart from the filled-in fields.
DISPATCH_TEMPLATE = (
    "Dispatch from Jay via command-center: {verb} {task}.\n"
    "Plan: {plan}.\n"
    "Jay said: \"{note}\"\n"
    "Not authorized by this message: merge, deploy, production, --apply, secrets, rule changes. Ask Jay in your pane.\n"
    "Need a visible lane? Message command-center: \"lane <task> <plan or prompt file>\".\n"
    "Report each stage change to command-center in one line: <task> <stage> <PR/issue> <Jay action>."
)
# Agent fields that may leave ccd. Terminal titles are deliberately absent:
# Claude titles its terminal after the conversation, which can quote anything.
AGENT_FIELDS = ("pane_id", "status", "live", "agent", "agent_name", "label", "cwd", "workspace_id",
                "workspace", "tab_id", "session_id", "project")


class ActionError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _now():
    return time.time()


def _read_proc(path):
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def host_snapshot(cfg, prev_cpu=None):
    """Host vitals. /proc for memory, load and CPU; sources.server for disk and docker."""
    info = sources.server(cfg)
    mem = {}
    for line in _read_proc("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if v.strip().split():
            mem[k] = int(v.strip().split()[0]) * 1024
    total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
    stotal, sfree = mem.get("SwapTotal", 0), mem.get("SwapFree", 0)
    load = [float(x) for x in (_read_proc("/proc/loadavg").split()[:3] or [0, 0, 0])]
    cpu_line = (_read_proc("/proc/stat").splitlines() or ["cpu 0"])[0].split()[1:]
    nums = [int(x) for x in cpu_line] if cpu_line else [0]
    idle, tot = (nums[3] + (nums[4] if len(nums) > 4 else 0)) if len(nums) > 3 else 0, sum(nums)
    cpu_pct = None
    if prev_cpu and tot > prev_cpu[1]:
        cpu_pct = round(100.0 * (1 - (idle - prev_cpu[0]) / (tot - prev_cpu[1])), 1)
    up = _read_proc("/proc/uptime").split()
    info.update({
        "memTotal": total, "memAvailable": avail, "memUsed": max(0, total - avail),
        "swapTotal": stotal, "swapUsed": max(0, stotal - sfree),
        "swapPct": round(100.0 * (stotal - sfree) / stotal, 1) if stotal else 0.0,
        "load": load, "cpuPct": cpu_pct, "cpus": os.cpu_count(),
        "uptimeS": float(up[0]) if up else None,
    })
    return info, (idle, tot)


def oom_kills_24h():
    """Kernel OOM kills in the last 24 hours, or None if the journal can't be read."""
    sources.CALLS["journalctl"] += 1
    try:
        r = subprocess.run(["journalctl", "-k", "--since", "24 hours ago", "-q", "--no-pager"],
                           capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return sum(1 for l in r.stdout.splitlines() if "Out of memory: Killed process" in l)


class Daemon:
    def __init__(self, cfg, store, herdr, *, github_fn=None, host_fn=None, git_fn=None, oom_fn=None, tasks=None):
        self.cfg = cfg
        self.store = store
        self.herdr = herdr
        self.tasks = tasks  # TaskStore, durable product data (tasks.db); None = task system off
        self._auto_seen = {}  # project -> GitHub asOf already run through ticket automation
        self.github_fn = github_fn or sources.github
        self.host_fn = host_fn or host_snapshot
        self.git_fn = git_fn or self._git_collect
        self.oom_fn = oom_fn or oom_kills_24h
        self.started = _now()
        self.subscribers = set()
        self._loops = []
        self._stopping = False
        self._dirty = asyncio.Event()
        self._git_now = asyncio.Event()
        self._last_action = {}

        self.panes = []
        self.layout = {"workspaces": [], "tabs": [], "layouts": {}}
        self.herdr_state = {"ok": False, "connected": False, "error": "starting", "protocol": None,
                            "lastSnapshotAt": None, "lastEventAt": None, "reconnects": 0, "resyncs": 0,
                            "eventsReceived": 0, "warning": None}
        gh_cache = {}
        for p in cfg["projects"]:
            data, at = store.get(f"gh:{p['key']}")
            gh_cache[p["key"]] = {"data": data, "asOf": at, "error": None if data else "not fetched yet",
                                  "lastAttempt": None}
        self.gh = gh_cache
        (unpushed, _), (worktrees, git_at) = store.get("git:unpushed", {}), store.get("git:worktrees", {})
        self.git = {"unpushed": unpushed or {}, "worktrees": worktrees or {}, "asOf": git_at, "error": None}
        host_data, host_at = store.get("host:last", {})
        self.host = {"data": host_data or {}, "asOf": host_at, "error": None, "oom24h": None,
                     "ooms_at": None, "running": set(host_data.get("running", []) if host_data else [])}
        self._prev_cpu = None
        blocked, _ = store.get("blocked_since", {})
        self.blocked_since = blocked or {}
        prev_agents, _ = store.get("agents:last", {})
        self._prev_agents = prev_agents or {}
        digest, _ = store.get("derived:last", None)
        self._prev_digest = digest
        self._prev_alert_ids = {a["id"] for a in store.alerts()}
        self.snap = None
        self.alerts = store.alerts()

    # ---------- lifecycle ----------

    def start(self):
        loops = [self.herdr_loop, self.github_loop, self.git_loop, self.host_loop, self.derive_loop,
                 self.housekeeping_loop]
        self._loops = [asyncio.create_task(fn(), name=fn.__name__) for fn in loops]
        self._event("daemon", "daemon.started", f"ccd {__version__} started", data={"pid": os.getpid()})
        self._dirty.set()

    async def stop(self):
        self._stopping = True
        for t in self._loops:
            t.cancel()
        await asyncio.gather(*self._loops, return_exceptions=True)
        self._event("daemon", "daemon.stopped", "ccd stopped")

    # ---------- events ----------

    @property
    def seq(self):
        return self.store.last_seq()

    def subscribe(self, maxsize=1000):
        q = asyncio.Queue(maxsize=maxsize)
        q.lost = False
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    def _event(self, source, kind, text="", **kw):
        ev = self.store.append(source, kind, text, **kw)
        for q in list(self.subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                q.lost = True  # the WS handler tells the client to refetch /api/state
                while not q.empty():
                    q.get_nowait()
        return ev

    # ---------- herdr ----------

    def _agent_digest(self, panes):
        return {p["pane_id"]: {"status": p["status"], "name": p.get("agent_name") or "",
                               "project": p.get("project")} for p in sources.agent_panes(panes)}

    def _attribute(self, panes):
        wt = self.git["worktrees"]
        for p in panes:
            p["project"] = model._pane_project(p, self.cfg["projects"], wt)
            if p.get("live") and p["project"] is None and p.get("cwd"):
                self._git_now.set()  # an agent in a directory we can't place: maybe a new worktree
        return panes

    def set_panes(self, panes, reason):
        panes = self._attribute([dict(p) for p in panes])
        new = self._agent_digest(panes)
        old = self._prev_agents
        now = _now()
        for pid, a in new.items():
            label = a["name"] or pid
            if pid not in old:
                self._event("herdr", "agent.started", f"{label} started", project=a["project"], agent_id=pid,
                            data={"to": a["status"], "name": a["name"], "reason": reason})
            elif old[pid]["status"] != a["status"]:
                self._status_event(pid, a, old[pid]["status"], a["status"], reason)
            if a["status"] == "blocked":
                self.blocked_since.setdefault(pid, now)
            else:
                self.blocked_since.pop(pid, None)
        for pid, a in old.items():
            if pid not in new:
                self._event("herdr", "agent.exited", f"{a.get('name') or pid} exited", project=a.get("project"),
                            agent_id=pid, data={"from": a.get("status"), "name": a.get("name"), "reason": reason})
                self.blocked_since.pop(pid, None)
        self.panes = panes
        self._prev_agents = new
        self.store.put("agents:last", new)
        self.store.put("blocked_since", self.blocked_since)
        self._dirty.set()

    def _status_event(self, pid, a, frm, to, reason):
        label = a["name"] or pid
        if to == "blocked":
            # The question text stays out of the log: it can quote anything.
            self._event("herdr", "agent.blocked", f"{label} is waiting for you", severity="warn",
                        project=a["project"], agent_id=pid, data={"from": frm, "to": to, "reason": reason})
        else:
            self._event("herdr", "agent.state_changed", f"{label} {frm} → {to}", project=a["project"],
                        agent_id=pid, data={"from": frm, "to": to, "reason": reason})

    def apply_status(self, pane_id, status):
        """A pane_agent_status_changed event: update in place, then let a resync confirm."""
        if not pane_id or not status:
            return
        for p in self.panes:
            if p["pane_id"] == pane_id and p.get("live"):
                if p["status"] != status:
                    p["status"] = status
                    self.set_panes(self.panes, "event")
                return

    async def resync(self, reason):
        snap = await self.herdr.snapshot()
        self.herdr_state["lastSnapshotAt"] = _now()
        self.herdr_state["resyncs"] += 1
        self.layout = sources.layout_from(snap)
        self.set_panes(sources.panes_from(snap), reason)

    def _herdr_up(self):
        if not self.herdr_state["connected"]:
            self._event("herdr", "daemon.herdr_connected", "herdr connected",
                        data={"connected": True, "count": self.herdr_state["reconnects"]})
        self.herdr_state.update(ok=True, connected=True, error=None)
        self._dirty.set()

    def _herdr_down(self, err):
        was = self.herdr_state["connected"] or self.herdr_state["error"] == "starting"
        self.herdr_state.update(ok=False, connected=False, error=str(err)[:200] or type(err).__name__)
        if was:
            self._event("herdr", "daemon.herdr_lost", f"herdr unreachable: {self.herdr_state['error']}",
                        severity="warn", data={"connected": False, "error": self.herdr_state["error"]})
            log.warning(json.dumps({"msg": "herdr lost", "error": self.herdr_state["error"]}))
        self._dirty.set()

    def agent_ids(self):
        return {p["pane_id"] for p in sources.agent_panes(self.panes)}

    async def herdr_loop(self):
        backoff = 1.0
        reconcile = float(self.cfg["reconcile_seconds"])
        while not self._stopping:
            writer = None
            try:
                pong = await self.herdr.ping()
                self.herdr_state["protocol"] = pong.get("protocol")
                mismatch = pong.get("protocol") != herdr_mod.PROTOCOL
                self.herdr_state["warning"] = (
                    f"herdr protocol {pong.get('protocol')} != {herdr_mod.PROTOCOL}: "
                    "events ignored, snapshot polling only" if mismatch else None)
                await self.resync("connect")
                if mismatch:
                    self._herdr_up()
                    await asyncio.sleep(reconcile)
                    continue
                watched = self.agent_ids()
                reader, writer = await self.herdr.subscribe(herdr_mod.subscriptions_for(watched))
                self._herdr_up()
                backoff = 1.0
                last_reconcile, resync_due = _now(), None
                while not self._stopping:
                    now = _now()
                    wait = reconcile - (now - last_reconcile)
                    if resync_due is not None:
                        wait = min(wait, resync_due - now)
                    try:
                        line = await asyncio.wait_for(reader.readline(), max(0.05, wait))
                    except asyncio.TimeoutError:
                        line = None
                    else:
                        if not line:
                            raise herdr_mod.HerdrError("herdr closed the subscription", "closed")
                    now = _now()
                    if line:
                        ev = herdr_mod.parse_event(line)
                        if ev:
                            name, data = ev
                            self.herdr_state["lastEventAt"] = now
                            self.herdr_state["eventsReceived"] += 1
                            if name == "pane_agent_status_changed":
                                self.apply_status(data.get("pane_id"), data.get("agent_status"))
                                resync_due = resync_due or now + 0.3
                            elif name in STRUCTURAL_EVENTS:
                                resync_due = resync_due or now + 0.3
                    if (resync_due is not None and now >= resync_due) or now - last_reconcile >= reconcile:
                        await self.resync("event" if resync_due is not None else "reconcile")
                        resync_due = None
                        if now - last_reconcile >= reconcile:
                            last_reconcile = now
                        if self.agent_ids() != watched:
                            break  # new or gone agents: reopen with the right subscription list
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionError, herdr_mod.HerdrError, asyncio.TimeoutError,
                    json.JSONDecodeError, ValueError) as e:
                self._herdr_down(e)
                self.herdr_state["reconnects"] += 1
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if writer is not None:
                    writer.close()

    # ---------- GitHub ----------

    async def poll_github_once(self):
        for p in self.cfg["projects"]:
            key = p["key"]
            entry = self.gh[key]
            entry["lastAttempt"] = _now()
            result = await asyncio.to_thread(self.github_fn, p)
            failed = [v["error"] for v in result.values() if isinstance(v, dict) and "error" in v]
            if failed:
                first_failure = entry["error"] is None
                entry["error"] = failed[0]
                if first_failure:
                    self._event("github", "daemon.github_failed", f"{key}: GitHub unreachable, keeping last good data",
                                severity="warn", project=key, data={"error": failed[0][:160]})
                continue
            if entry["error"] and entry["data"] is not None:
                self._event("github", "daemon.github_recovered", f"{key}: GitHub back", project=key)
            entry.update(data=result, asOf=_now(), error=None)
            self.store.put(f"gh:{key}", result)
        self._dirty.set()

    async def github_loop(self):
        while not self._stopping:
            try:
                await self.poll_github_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — one bad poll must not kill the loop
                log.warning(json.dumps({"msg": "github poll crashed", "error": repr(e)[:200]}))
            await asyncio.sleep(float(self.cfg["github_seconds"]))

    # ---------- git ----------

    def _git_collect(self):
        unpushed, worktrees = {}, {}
        for p in self.cfg["projects"]:
            if p.get("path"):
                unpushed[p["key"]] = sources.unpushed_branches(p["path"])
                worktrees[p["key"]] = sources.worktree_paths(p["path"])
        return unpushed, worktrees

    async def poll_git_once(self):
        unpushed, worktrees = await asyncio.to_thread(self.git_fn)
        self.git.update(unpushed=unpushed, worktrees=worktrees, asOf=_now(), error=None)
        self.store.put("git:unpushed", unpushed)
        self.store.put("git:worktrees", worktrees)
        if self.panes:  # before herdr's first answer there is nothing to re-place, and the
            # remembered agent set from the last run must survive until it is compared.
            self.panes = self._attribute(self.panes)
            self._prev_agents = self._agent_digest(self.panes)
        self._dirty.set()

    async def git_loop(self):
        last_ondemand = 0.0
        while not self._stopping:
            try:
                await self.poll_git_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.git["error"] = repr(e)[:200]
            self._git_now.clear()
            try:
                await asyncio.wait_for(self._git_now.wait(), float(self.cfg["git_seconds"]))
                # An unplaceable agent asked for a refresh; at most once a minute.
                wait = 60 - (_now() - last_ondemand)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_ondemand = _now()
            except asyncio.TimeoutError:
                pass

    # ---------- host ----------

    async def poll_host_once(self, with_oom=False):
        data, self._prev_cpu = await asyncio.to_thread(self.host_fn, self.cfg, self._prev_cpu)
        running = set(data.get("running") or [])
        if self.host["running"]:
            for name in sorted(self.host["running"] - running):
                self._event("host", "host.container_down", f"container {name} stopped", severity="warn",
                            data={"name": name})
        self.host["running"] = running
        if with_oom:
            n = await asyncio.to_thread(self.oom_fn)
            if n is not None:
                if self.host["oom24h"] is not None and n > self.host["oom24h"]:
                    self._event("host", "host.oom_kill", f"{n - self.host['oom24h']} new OOM kill(s)",
                                severity="warn", data={"count": n})
                self.host["oom24h"], self.host["ooms_at"] = n, _now()
        data["oomKills24h"] = self.host["oom24h"]
        self.host.update(data=data, asOf=_now(), error=None)
        self.store.put("host:last", dict(data, running=sorted(running)))
        self._dirty.set()

    async def host_loop(self):
        last_oom = 0.0
        while not self._stopping:
            try:
                oom = _now() - last_oom >= 600
                await self.poll_host_once(with_oom=oom)
                if oom:
                    last_oom = _now()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.host["error"] = repr(e)[:200]
            await asyncio.sleep(float(self.cfg["host_seconds"]))

    # ---------- derive ----------

    def _gh_data(self):
        return {k: v["data"] for k, v in self.gh.items() if v["data"] is not None}

    def _herdr_error(self):
        if self.herdr_state["ok"]:
            return None
        return f"herdr unreachable: {self.herdr_state['error']}" if self.herdr_state["error"] else "herdr unreachable"

    async def _tails_for_blocked(self, panes):
        tails = {}
        for p in sources.agent_panes(panes):
            if p["status"] == "blocked" and self.herdr_state["ok"]:
                try:
                    tails[p["pane_id"]] = (await self.herdr.read_tail(p["pane_id"], 8))["text"]
                except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError):
                    tails[p["pane_id"]] = ""
        return tails

    async def rederive(self):
        # Every event up to here is reflected in what follows. A client that
        # bootstraps from this state and replays from snap_seq loses nothing;
        # events raised during the derive itself may replay twice, harmlessly.
        snap_seq = self.seq
        panes = self.panes
        if not self.herdr_state["ok"]:
            # Keep the last known agents, but say plainly that their state is unknown.
            panes = [dict(p, status="unknown") if p.get("live") else dict(p) for p in panes]
        now = _now()
        blocked_min = {k: (now - v) / 60 for k, v in self.blocked_since.items()}
        tails = await self._tails_for_blocked(panes)
        from .security import redact
        snap = await asyncio.to_thread(
            model.derive, self.cfg, self._gh_data(), panes, self.host["data"] or {},
            self.git["unpushed"], self.git["worktrees"], blocked_min, self._herdr_error(),
            lambda pid: redact(tails.get(pid, ""))[0])
        quiet = self.seq == snap_seq  # nobody logged anything while we awaited
        self._decorate(snap)
        self._diff_and_alert(snap)    # synchronous: what it logs IS this snapshot
        self._ticket_automation()
        snap["seq"] = self.seq if quiet else snap_seq
        self.snap = snap

    def _decorate(self, snap):
        """Public shape: agent roles, canonical coordinators, source freshness."""
        coord = {}
        for p in self.cfg["projects"]:
            pane = coordinators.pane_for(p, snap["panes"])
            coord[p["key"]] = {"name": coordinators.canonical(p), "paneId": pane["pane_id"] if pane else None,
                               "status": pane["status"] if pane else "offline",
                               "canonical": bool(pane) and pane.get("agent_name") == coordinators.canonical(p)}
        coord_panes = {c["paneId"] for c in coord.values() if c["paneId"]}
        now = _now()

        def agent(p):
            a = {k: p.get(k) for k in AGENT_FIELDS}
            a["id"] = p["pane_id"]
            a["role"] = ("coordinator" if p["pane_id"] in coord_panes else
                         "lane" if p.get("project") not in (None, "home") else
                         "command-center" if p.get("project") == "home" else "other")
            since = self.blocked_since.get(p["pane_id"])
            a["blockedSinceMs"] = int(since * 1000) if since else None
            a["blockedForMin"] = round((now - since) / 60, 1) if since else None
            a["context"] = None  # owner decision 10: rendered as "—" until transcripts are in scope
            return a

        live = [agent(p) for p in sources.agent_panes(snap["panes"])]
        snap["agents"] = live
        snap["home_panes"] = [a for a in live if a["project"] == "home"]
        snap["panes"] = [{k: p.get(k) for k in AGENT_FIELDS} for p in snap["panes"]]
        for v in snap["projects"]:
            v["panes"] = [agent(p) for p in v["panes"]]
            v["all_panes"] = [{k: p.get(k) for k in AGENT_FIELDS} for p in v.get("all_panes", [])]
            v["team"] = [dict(t) for t in v["team"]]
            if v.get("coordinator"):
                v["coordinator"] = agent(v["coordinator"])
            g = self.gh.get(v["key"], {})
            v["github"] = {"asOf": g.get("asOf"), "error": g.get("error")}
            if g.get("error") and g.get("data") is not None:
                v["errors"] = [f"GitHub: {g['error']} (showing data as of {time.strftime('%H:%M', time.localtime(g['asOf']))})"]
        snap["coordinators"] = coord
        snap["workspaces"] = self._workspaces(snap["panes"], live)
        snap["host"] = dict(self.host["data"] or {}, asOf=self.host["asOf"])
        snap["host"].pop("running", None)
        snap["projectsConfig"] = [public_project(p) for p in self.cfg["projects"]]
        snap["sources"] = {
            "herdr": {k: self.herdr_state[k] for k in ("ok", "connected", "error", "protocol", "lastSnapshotAt",
                                                       "lastEventAt", "warning")},
            "github": {k: {"asOf": v["asOf"], "error": v["error"]} for k, v in self.gh.items()},
            "git": {"asOf": self.git["asOf"], "error": self.git["error"]},
            "host": {"asOf": self.host["asOf"], "error": self.host["error"]},
        }

    def _digest(self, snap):
        return {
            # Which projects had real GitHub data behind this snapshot. Diffing a
            # project against a baseline taken before GitHub answered would
            # report every open PR and task as brand new.
            "gh_ready": sorted(k for k, v in self.gh.items() if v["data"] is not None),
            "tasks": {f"{v['key']}:{t['ref']}": t["stage"] for v in snap["projects"] for t in v["tasks"]},
            "prs": {f"{v['key']}#{pr['number']}": pr["ci"] for v in snap["projects"] for pr in v["prs"]},
            "main_ci": {v["key"]: v["main_ci"] for v in snap["projects"]},
            "needs": sorted(f"{n['project']}:{n['kind']}:{n['ref']}" for n in snap["needs"]),
        }

    def _diff_and_alert(self, snap):
        d = self._digest(snap)
        old = self._prev_digest
        ready = set(d["gh_ready"]) & set((old or {}).get("gh_ready") or [])

        def comparable(key):
            return key.split(":", 1)[0].split("#", 1)[0] in ready

        if old is not None and ready:
            for ref, stage in d["tasks"].items():
                if comparable(ref) and ref in old["tasks"] and old["tasks"][ref] != stage:
                    proj = ref.split(":", 1)[0]
                    self._event("github", "task.stage_changed", f"{ref.split(':', 1)[1]} {old['tasks'][ref]} → {stage}",
                                project=proj, ref=ref.split(":", 1)[1], data={"from": old["tasks"][ref], "to": stage})
            for ref, ci in d["prs"].items():
                proj, num = ref.split("#")
                if not comparable(ref):
                    continue
                if ref not in old["prs"]:
                    self._event("github", "pr.opened", f"PR #{num} opened", project=proj, ref=f"#{num}",
                                data={"number": int(num), "ci": ci})
                elif old["prs"][ref] != ci:
                    self._event("github", "pr.ci_changed", f"PR #{num} checks {old['prs'][ref]} → {ci}",
                                severity="warn" if ci == "✗" else "info", project=proj, ref=f"#{num}",
                                data={"number": int(num), "from": old["prs"][ref], "to": ci})
            for ref in old["prs"]:
                if ref not in d["prs"] and comparable(ref):
                    proj, num = ref.split("#")
                    if self.gh.get(proj, {}).get("error") is None:
                        self._event("github", "pr.closed", f"PR #{num} closed or merged", project=proj,
                                    ref=f"#{num}", data={"number": int(num)})
            for proj, mark in d["main_ci"].items():
                if proj in ready and old["main_ci"].get(proj) not in (None, mark):
                    self._event("github", "ci.main_changed", f"{proj} main checks {old['main_ci'][proj]} → {mark}",
                                severity="warn" if mark == "✗" else "info", project=proj,
                                data={"from": old["main_ci"][proj], "to": mark})
            for key in sorted(set(d["needs"]) - set(old["needs"])):
                if not comparable(key):
                    continue
                proj, kind, ref = key.split(":", 2)
                self._event("derive", "jay.action_required", f"{proj}: {kind} {ref}", severity="action",
                            project=proj, ref=ref, data={"kind": kind})
        self._prev_digest = d
        self.store.put("derived:last", d)

        alerts = self._compute_alerts(snap)
        ids = {a["id"] for a in alerts}
        for a in alerts:
            if a["id"] not in self._prev_alert_ids:
                self._event("alerts", "alert.raised", a["text"], severity=a["severity"], project=a.get("project"),
                            ref=a["id"])
        for gone in self._prev_alert_ids - ids:
            self._event("alerts", "alert.cleared", gone, ref=gone)
        self._prev_alert_ids = ids
        self.store.sync_alerts(alerts)
        self.alerts = self.store.alerts()
        snap["alerts"] = self.alerts

    def _compute_alerts(self, snap):
        out = []
        for b in snap["blocked"]:
            out.append({"id": f"blocked:{b['pane_id']}", "severity": "warn", "source": "herdr",
                        "project": b["project"], "text": f"{b['name']} is waiting for you"})
        for n in snap["needs"]:
            if n["kind"] == "merge":
                out.append({"id": f"merge:{n['project']}:{n['number']}:{n['sha']}", "severity": "action",
                            "source": "github", "project": n["project"], "text": f"{n['project']} PR {n['ref']} ready to merge"})
            elif n["kind"] == "ci":
                out.append({"id": f"ci:{n['project']}", "severity": "warn", "source": "github",
                            "project": n["project"], "text": f"{n['project']} main checks failing"})
        h = self.host["data"] or {}
        if h.get("disk", 0) >= self.cfg["disk_warn_percent"]:
            out.append({"id": "host:disk", "severity": "warn", "source": "host", "project": None,
                        "text": f"disk {h['disk']}%"})
        if h.get("swapPct", 0) >= self.cfg["swap_warn_percent"]:
            out.append({"id": "host:swap", "severity": "warn", "source": "host", "project": None,
                        "text": f"swap {h['swapPct']}% used"})
        if self.host["oom24h"]:
            out.append({"id": "host:oom", "severity": "warn", "source": "host", "project": None,
                        "text": f"{self.host['oom24h']} OOM kill(s) in the last 24 h"})
        if not self.herdr_state["ok"] and self.herdr_state["error"] != "starting":
            out.append({"id": "daemon:herdr", "severity": "warn", "source": "daemon", "project": None,
                        "text": self._herdr_error()})
        for k, v in self.gh.items():
            if v["error"] and v["error"] != "not fetched yet" and (v["asOf"] is None or _now() - v["asOf"] > 600):
                out.append({"id": f"daemon:github:{k}", "severity": "warn", "source": "daemon", "project": k,
                            "text": f"{k}: GitHub failing for over 10 min"})
        return out

    async def derive_loop(self):
        while not self._stopping:
            await self._dirty.wait()
            await asyncio.sleep(0.2)  # coalesce bursts from several sources
            self._dirty.clear()
            try:
                await self.rederive()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("derive failed")
                self._event("daemon", "daemon.derive_failed", repr(e)[:200], severity="warn")

    async def housekeeping_loop(self):
        while not self._stopping:
            try:
                n = await asyncio.to_thread(self.store.prune, int(self.cfg["retention_days"]))
                if n:
                    log.info(json.dumps({"msg": "pruned events", "count": n}))
            except Exception as e:  # noqa: BLE001
                log.warning(json.dumps({"msg": "prune failed", "error": repr(e)[:200]}))
            await asyncio.sleep(86400)

    # ---------- workspaces (herdr layout, read-only) ----------

    def _workspaces(self, panes, agents):
        """herdr's workspaces → tabs → panes with geometry, for the Workspaces screen.

        Geometry and identity only. Terminal titles stay out (they can quote
        anything); pane output is never part of state.
        """
        by_pane = {p["pane_id"]: p for p in panes}
        role = {a["id"]: a["role"] for a in agents}
        out = []
        for w in self.layout.get("workspaces") or []:
            tabs = []
            projects = []
            for t in (x for x in self.layout.get("tabs") or [] if x["workspaceId"] == w["id"]):
                lay = (self.layout.get("layouts") or {}).get(t["id"]) or {}
                cells = []
                for c in lay.get("panes") or []:
                    p = by_pane.get(c["paneId"], {})
                    if p.get("project"):
                        projects.append(p["project"])
                    cells.append({"id": c["paneId"], "rect": c["rect"], "focused": c["focused"],
                                  "live": bool(p.get("live")), "agentName": p.get("agent_name") or None,
                                  "agent": p.get("agent") or None, "label": p.get("label") or None,
                                  "status": p.get("status") if p.get("live") else None,
                                  "role": role.get(c["paneId"]), "project": p.get("project"), "cwd": p.get("cwd") or None})
                tabs.append({"id": t["id"], "label": t["label"], "number": t["number"], "focused": t["focused"],
                             "zoomed": bool(lay.get("zoomed")), "focusedPaneId": lay.get("focusedPaneId"),
                             "area": lay.get("area") or {"w": 0, "h": 0}, "panes": cells})
            main = max(set(projects), key=projects.count) if projects else None
            out.append({"id": w["id"], "label": w["label"], "number": w["number"], "focused": w["focused"],
                        "activeTabId": w["activeTabId"], "project": main, "tabs": tabs})
        return out

    # ---------- tickets ----------

    def _task_event(self, kind, ticket, text, data=None):
        self._event("tasks", kind, f"{ticket['key']} {text}"[:300], project=ticket["project"], ref=ticket["key"],
                    severity="action" if kind == "task.updated" and (data or {}).get("kind") in tasks_mod.FLAGS
                    and (data or {}).get("to") is True else "info", data=data or {})

    def _announce(self, ticket, changes):
        """One ops event per change, so live clients refresh the ticket. The audit trail is in tasks.db."""
        for c in changes:
            f = c["field"]
            if f in ("description", "title"):
                self._task_event("task.updated", ticket, f"{f} edited", {"kind": f})
            elif f == "labels":
                self._task_event("task.updated", ticket, "labels changed", {"kind": f})
            else:
                frm = c["from"] if not isinstance(c["from"], (list, dict)) else None
                to = c["to"] if not isinstance(c["to"], (list, dict)) else None
                self._task_event("task.updated", ticket, f"{f} {frm if frm not in (None, '') else '—'} → "
                                 f"{to if to not in (None, '') else '—'}", {"kind": f, "from": frm, "to": to})

    def _need_tasks(self):
        if self.tasks is None:
            raise ActionError(503, "the task system is not enabled")
        return self.tasks

    def _wrap(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except tasks_mod.TaskError as e:
            raise ActionError(e.status, e.message)
        except (ValueError, TypeError) as e:
            raise ActionError(400, f"bad value: {str(e)[:120]}")

    def task_list(self, project=None, include_archived=False):
        ts = self._need_tasks()
        return {"tickets": ts.list(project=project, include_archived=include_archived), "projects": ts.projects(),
                "meta": ts.meta(), "seq": self.seq}

    def task_get(self, key):
        return self._wrap(self._need_tasks().get, key)

    def task_context(self, key):
        ctx = self._wrap(self._need_tasks().context, key)
        t = ctx["ticket"]
        coord = (self.snap or {}).get("coordinators", {}).get(t["project"]) if self.snap else None
        ctx["coordinator"] = coord
        ctx["dispatchable"] = bool(coord) and t["project"] in set(
            self.cfg.get("dispatch_projects") or ("samvision", "gauzemate"))
        return ctx

    def task_create(self, body, actor="jay"):
        ts = self._need_tasks()
        if not isinstance(body, dict):
            raise ActionError(400, "body must be an object")
        # Only ticket fields. `number` (import-only) and anything else are refused, not passed on.
        extra = set(body) - {"project", "title"} - CREATE_FIELDS
        if extra:
            raise ActionError(400, f"cannot set {', '.join(sorted(extra))} on create")
        fields = {k: v for k, v in body.items() if k in CREATE_FIELDS}
        ticket, changes = self._wrap(ts.create, str(body.get("project") or ""), body.get("title"), actor, **fields)
        self._task_event("task.created", ticket, f"created · {ticket['title']}", {"status": ticket["status"]})
        return ticket

    def task_update(self, key, body, actor="jay"):
        ticket, changes = self._wrap(self._need_tasks().update, key, body, actor)
        self._announce(ticket, changes)
        return ticket

    def task_comment(self, key, body, actor="jay"):
        ticket = self._wrap(self._need_tasks().comment, key, body, actor)
        self._task_event("task.commented", ticket, "note added", {"count": len(ticket["comments"])})
        return ticket

    def task_relate(self, key, kind, target, remove=False, actor="jay"):
        ticket, changed = self._wrap(self._need_tasks().relate, key, kind, target, actor, remove)
        if changed:
            other = self._wrap(self._need_tasks().get, target)
            for t in (ticket, other):
                self._task_event("task.updated", t, "relations changed", {"kind": "relations"})
        return ticket

    def task_link(self, key, body, actor="jay"):
        ticket, changed = self._wrap(self._need_tasks().link, key, str(body.get("provider") or "github"),
                                     str(body.get("kind") or "pr"), body.get("ref"), body.get("url"),
                                     body.get("title"), actor, None, bool(body.get("remove")))
        if changed:
            self._task_event("task.updated", ticket, f"{'unlinked' if body.get('remove') else 'linked'} "
                             f"{body.get('kind') or 'pr'} {body.get('ref')}", {"kind": "links"})
        return ticket

    def task_import_preview(self):
        """Runs in a worker thread, on its own read-only connection to tasks.db."""
        reader = self._need_tasks().reader()
        try:
            return importer.preview(self.cfg["projects"], self._gh_data(), reader)
        finally:
            if reader is not self.tasks:
                reader.close()

    def _auto(self, key, frm, to, trigger):
        """One automatic status move, if the ticket is still in `frm` and Jay has not overridden it.

        Jay wins: if the last status change was a human moving the ticket away
        from `to`, automation does not move it back. Actor system:automation,
        trigger recorded with the change.
        """
        t = self.tasks.get(key)
        if t["status"] not in frm:
            return t
        last = self.tasks.last_status_event(key)
        if last and not last["actor"].startswith("system:") and last["from"] == to:
            return t
        ticket, changes = self.tasks.update(key, {"status": to}, "system:automation", trigger=trigger)
        self._announce(ticket, changes)
        return ticket

    def _ticket_automation(self):
        """GitHub → tickets, only on deterministic triggers.

          open PR whose title or branch LEADS with a key (same project) → link it, set branch
          ...ticket READY_TO_IMPLEMENT or IN_PROGRESS                      → IN_REVIEW
          linked PR approved, checks green, not draft, ticket IN_REVIEW    → READY_TO_MERGE
          linked PR no longer ready, ticket READY_TO_MERGE                 → IN_REVIEW
          linked PR merged (found by link, not title), IN_REVIEW/READY_TO_MERGE → VERIFYING

        Once per fresh GitHub poll per project. Never closes a ticket
        (VERIFYING → DONE is a verifier's or Jay's call) and never undoes a
        status Jay set by hand.
        """
        if self.tasks is None:
            return
        prefixes = self.tasks.prefixes()
        for p in self.cfg["projects"]:
            g = self.gh.get(p["key"]) or {}
            if g.get("error") or not g.get("data") or self._auto_seen.get(p["key"]) == g.get("asOf"):
                continue
            self._auto_seen[p["key"]] = g.get("asOf")
            data = g["data"]

            def mine(k):
                return prefixes.get(k.split("-")[0]) == p["key"] and self.tasks.exists(k)

            for pr in data.get("prs") if isinstance(data.get("prs"), list) else []:
                try:
                    n = pr["number"]
                    ref = f"{p['repo']}#{n}"
                    keys = [k for k in self.tasks.pr_keys(pr.get("title", ""), pr.get("headRefName", "")) if mine(k)]
                    keys += [k for k in self.tasks.keys_linked("github", "pr", ref) if k not in keys]
                    ci = model.ci_mark(pr.get("statusCheckRollup"))
                    ready = pr.get("reviewDecision") == "APPROVED" and ci in ("✓", "–") and not pr.get("isDraft")
                    for k in keys:
                        if not self.tasks.has_link(k, "github", "pr", ref):
                            t, _ = self.tasks.link(k, "github", "pr", ref, pr.get("url"), pr.get("title"),
                                                   "system:automation", trigger=f"PR #{n} title or branch leads with {k}")
                            self._task_event("task.updated", t, f"linked PR #{n}", {"kind": "links"})
                        t = self.tasks.get(k)
                        if not t["branch"] and pr.get("headRefName"):
                            t, ch = self.tasks.update(k, {"branch": pr["headRefName"]}, "system:automation",
                                                      trigger=f"PR #{n} head branch")
                            self._announce(t, ch)
                        self._auto(k, ("READY_TO_IMPLEMENT", "IN_PROGRESS"), "IN_REVIEW", f"PR #{n} is open")
                        if ready:
                            self._auto(k, ("IN_REVIEW",), "READY_TO_MERGE", f"PR #{n} approved, checks green, not draft")
                        else:
                            self._auto(k, ("READY_TO_MERGE",), "IN_REVIEW",
                                       f"PR #{n} no longer approved with green checks")
                except Exception as e:  # noqa: BLE001 — one odd PR must not fail the snapshot
                    log.warning(json.dumps({"msg": "ticket automation skipped a PR", "error": repr(e)[:200]}))
            for m in data.get("merged") if isinstance(data.get("merged"), list) else []:
                try:
                    ref = f"{p['repo']}#{m['number']}"
                    for k in self.tasks.keys_linked("github", "pr", ref):
                        self._auto(k, ("IN_REVIEW", "READY_TO_MERGE"), "VERIFYING", f"PR #{m['number']} merged")
                except Exception as e:  # noqa: BLE001
                    log.warning(json.dumps({"msg": "ticket automation skipped a merge", "error": repr(e)[:200]}))

    # ---------- read API ----------

    def state(self):
        snap = dict(self.snap or {})
        # `seq` is the log position this state reflects, not the newest event:
        # replaying WS events from it is what keeps a client exact.
        snap.setdefault("seq", 0)
        snap.update(latestSeq=self.seq, version=__version__, health=self.health(short=True))
        snap.setdefault("alerts", self.alerts)
        if self.tasks is not None:
            # Ticket flags (needs:jay, needs:legal, …) join the one Needs-Jay queue.
            # Read live from tasks.db, so a flag shows the moment it is set.
            ticket_needs = self.tasks.needs()
            snap["needs"] = list(snap.get("needs") or []) + ticket_needs
            totals = dict(snap.get("totals") or {})
            totals["needs"] = totals.get("needs", 0) + len(ticket_needs)
            totals["tickets"] = self.tasks.counts()
            snap["totals"] = totals
            srcs = dict(snap.get("sources") or {})
            srcs["tasks"] = {"ok": True, "asOf": self.tasks.last_change, "error": None}
            snap["sources"] = srcs
        return snap

    def health(self, short=False):
        gh_ok = all(v["error"] is None for v in self.gh.values()) if self.gh else False
        h = {
            "ok": bool(self.herdr_state["ok"] and self.snap is not None),
            "herdr": {k: self.herdr_state[k] for k in ("ok", "connected", "error", "protocol", "lastSnapshotAt",
                                                       "lastEventAt", "reconnects", "resyncs", "eventsReceived",
                                                       "warning")},
            "gh": {"ok": gh_ok, "projects": {k: {"asOf": v["asOf"], "error": v["error"]} for k, v in self.gh.items()}},
            "git": {"asOf": self.git["asOf"], "error": self.git["error"]},
            "host": {"asOf": self.host["asOf"], "error": self.host["error"]},
            "tasks": {"enabled": self.tasks is not None,
                      "schemaVersion": tasks_mod.SCHEMA_VERSION if self.tasks is not None else None},
            "seq": self.seq,
            "uptimeS": round(_now() - self.started, 1),
            "version": __version__,
        }
        if not short:
            h["pid"] = os.getpid()
            h["subscribers"] = len(self.subscribers)
            h["calls"] = dict(sources.CALLS)
            h["dbBytes"] = self.store.size_bytes()
            h["lastPollAges"] = {
                "herdrSnapshot": round(_now() - self.herdr_state["lastSnapshotAt"], 1) if self.herdr_state["lastSnapshotAt"] else None,
                "github": {k: round(_now() - v["asOf"], 1) if v["asOf"] else None for k, v in self.gh.items()},
                "git": round(_now() - self.git["asOf"], 1) if self.git["asOf"] else None,
                "host": round(_now() - self.host["asOf"], 1) if self.host["asOf"] else None,
            }
        return h

    def find_agent(self, ident):
        for p in sources.agent_panes(self.panes):
            if ident in (p["pane_id"], p.get("agent_name")):
                return p
        return None

    async def tail(self, ident, lines):
        from .security import redact
        agent = self.find_agent(ident)
        if not agent:
            raise ActionError(404, "no such live agent")
        if not self.herdr_state["ok"]:
            raise ActionError(503, "herdr unreachable")
        lines = max(1, min(int(lines), 200))
        got = await self.herdr.read_tail(agent["pane_id"], lines)
        text, n = redact(got["text"])
        return {"agentId": agent["pane_id"], "name": agent.get("agent_name") or None, "lines": lines,
                "text": text, "redactions": n, "truncated": got["truncated"]}

    # ---------- actions (the whole list; nothing else exists) ----------

    def _throttle(self, key, seconds=1.0):
        now = _now()
        if now - self._last_action.get(key, 0) < seconds:
            raise ActionError(429, "too many requests for this target; wait a second")
        self._last_action[key] = now

    async def _fresh_agent(self, ident):
        if not self.herdr_state["ok"]:
            raise ActionError(503, "herdr unreachable")
        await self.resync("action")  # act on herdr's state now, not on a cached one
        agent = self.find_agent(ident)
        if not agent:
            raise ActionError(404, "no such live agent")
        return agent

    async def act_answer(self, ident, text):
        if not isinstance(text, str) or not ANSWER_RE.match(text):
            raise ActionError(400, "answer must be 1–2000 printable characters on one line")
        self._throttle(f"answer:{ident}")
        agent = await self._fresh_agent(ident)
        if agent["status"] != "blocked":
            raise ActionError(409, f"agent is {agent['status']}, not blocked; nothing to answer")
        pid = agent["pane_id"]
        # Audit first. The answer's text is not stored, only its length.
        self._event("action", "action.answer", f"answer sent to {agent.get('agent_name') or pid}",
                    project=agent.get("project"), agent_id=pid, data={"count": len(text)})
        try:
            await self.herdr.send_answer(pid, text)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            self._event("action", "action.failed", f"answer to {pid} failed", severity="warn", agent_id=pid,
                        data={"kind": "answer", "error": str(e)[:160]})
            raise ActionError(502, f"herdr refused: {e}")
        return {"ok": True, "agentId": pid}

    async def act_focus_layout(self, workspace_id=None, tab_id=None):
        """Bring a herdr workspace or tab forward in Jay's attached herdr client. Changes no layout."""
        target = tab_id or workspace_id
        if not isinstance(target, str) or not re.match(r"^[A-Za-z0-9]{1,8}(:t[A-Za-z0-9]{1,8})?$", target):
            raise ActionError(400, "workspaceId or tabId required")
        self._throttle(f"focus:{target}", 0.3)
        if not self.herdr_state["ok"]:
            raise ActionError(503, "herdr unreachable")
        await self.resync("action")
        known = {w["id"] for w in self.layout.get("workspaces") or []} | {t["id"] for t in self.layout.get("tabs") or []}
        if target not in known:
            raise ActionError(404, "no such workspace or tab")
        self._event("action", "action.focus", f"focus {'tab' if tab_id else 'workspace'} {target}", ref=target)
        try:
            if tab_id:
                await self.herdr.focus_tab(tab_id)
            else:
                await self.herdr.focus_workspace(workspace_id)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            raise ActionError(502, f"herdr refused: {e}")
        return {"ok": True, "target": target}

    async def act_focus(self, ident):
        self._throttle(f"focus:{ident}", 0.3)
        agent = await self._fresh_agent(ident)
        pid = agent["pane_id"]
        self._event("action", "action.focus", f"focus {agent.get('agent_name') or pid}",
                    project=agent.get("project"), agent_id=pid)
        try:
            await self.herdr.focus(pid)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            raise ActionError(502, f"herdr refused: {e}")
        return {"ok": True, "agentId": pid}

    async def act_ack(self, alert_id):
        if not isinstance(alert_id, str) or not alert_id or len(alert_id) > 200:
            raise ActionError(400, "alertId required")
        if not self.store.ack(alert_id):
            raise ActionError(404, "no such active alert")
        self._event("action", "action.ack", f"alert acknowledged: {alert_id}", ref=alert_id)
        self.alerts = self.store.alerts()
        if self.snap is not None:
            self.snap["alerts"] = self.alerts
        return {"ok": True, "alertId": alert_id}

    def _plan_for(self, task):
        plans = Path(self.cfg.get("plans_dir") or (STATE_DIR.parent / "plans"))
        if task.startswith("#"):
            return None
        for f in sorted(plans.glob(f"{task}*")) if plans.exists() else []:
            if f.is_file():
                return str(f.resolve())
        return None

    async def act_dispatch(self, project, task, verb, note=""):
        """Send one task to a coordinator, under the dispatch skill's rules.

        Coordinators only (lanes are the coordinator's call), canonical name
        only, never into a busy or blocked agent, and the message carries the
        skill's non-authorisation preamble word for word.
        """
        allowed = set(self.cfg.get("dispatch_projects") or ("samvision", "gauzemate"))
        proj = next((p for p in self.cfg["projects"] if p["key"] == project), None)
        if proj is None:
            raise ActionError(404, "unknown project")
        if project not in allowed:
            raise ActionError(409, f"{project} has no coordinator; tasks go to a lane (see the dispatch skill)")
        if verb not in DISPATCH_VERBS:
            raise ActionError(400, f"verb must be one of {', '.join(DISPATCH_VERBS)}")
        is_ticket = isinstance(task, str) and self.tasks is not None and bool(TICKET_KEY_RE.match(task)) \
            and self.tasks.exists(task)
        if not isinstance(task, str) or not (TASK_ID_RE.match(task) or is_ticket):
            raise ActionError(400, "taskId must look like SV-056, GYST-VN-009, MFE-3, GM-12 or #42, "
                                   "or be an existing ticket key")
        if is_ticket and self.tasks.get(task)["project"] != project:
            raise ActionError(409, f"{task} belongs to another project")
        if not isinstance(note, str) or not NOTE_RE.match(note):
            raise ActionError(400, "note must be printable, one line, at most 500 characters")
        self._throttle(f"dispatch:{project}", 5.0)
        name = coordinators.canonical(proj)
        agent = await self._fresh_agent(name)
        if agent.get("agent_name") != name:
            raise ActionError(409, f"{project}'s coordinator is not running under its canonical name")
        if agent["status"] not in ("idle", "done"):
            raise ActionError(409, f"{name} is {agent['status']}; dispatch only goes to an idle coordinator")
        plan = self._plan_for(task) or "none – plan it first per your workflow"
        text = DISPATCH_TEMPLATE.format(verb=verb, task=task, plan=plan, note=note.replace('"', "'"))
        self._event("action", "action.dispatch", f"{verb} {task} → {name}", project=project, agent_id=agent["pane_id"],
                    ref=task, data={"kind": verb})
        try:
            await self.herdr.prompt(name, text)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            self._event("action", "action.failed", f"dispatch to {name} failed", severity="warn",
                        project=project, data={"kind": "dispatch", "error": str(e)[:160]})
            raise ActionError(502, f"herdr refused: {e}")
        if is_ticket:
            rule = DISPATCH_TRANSITIONS.get(verb)
            t = self.tasks.get(task)
            self._task_event("task.updated", t, f"dispatched: {verb} → {name}", {"kind": "dispatch"})
            if rule:
                self._auto(task, rule[0], rule[1], f"dispatch '{verb}' accepted by idle coordinator {name}")
        return {"ok": True, "coordinator": name, "task": task, "verb": verb, "plan": plan}
