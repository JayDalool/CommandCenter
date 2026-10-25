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
import sqlite3
import subprocess
import time
from pathlib import Path

from . import __version__, autonomy, coordid, coordinators, github, ledger, merge_policy, model, profiles, registry, sources
from . import pipeline as pipeline_mod
from . import workers as workers_mod
from . import inbox as inbox_mod
from . import audit as audit_mod
from . import identity as identity_mod
from . import nodekeys as nodekeys_mod
from . import broker as broker_mod
from . import meter as meter_mod
from . import budgets as budgets_mod
from . import onboarding as onboarding_mod
from . import herdr as herdr_mod
from . import importer
# A ticket key in an /api/tasks path, in any case (tasks._id_of upper-cases it), for the shadow identity record.
TICKET_PATH_RE = re.compile(r"/api/tasks/([A-Za-z][A-Za-z0-9-]{0,20}-\d{1,6})(?:/|$)")
from . import nightshift as nightshift_mod
from . import uitests as uitests_mod
from . import records as records_mod
from . import tasks as tasks_mod
from . import worktree_cleanup
from . import config as config_mod
from .config import AUTO_MERGE_STOP, STATE_DIR, public_project

log = logging.getLogger("ccd")

STRUCTURAL_EVENTS = {t.replace(".", "_") for t in herdr_mod.STRUCTURAL}
DISPATCH_VERBS = ("plan", "implement", "review", "verify", "continue", "stop")
# A legacy board ID (INDEX.md row, issue title) or a GitHub issue number. The
# prefixes come from the project registry, never from a literal list here.
TASK_ID_RE = re.compile(rf"^(?:{registry.board_id_pattern()}-\d{{1,5}}|#\d{{1,6}})$")
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
# The task check (Jay: "make sure the tasks in Command Center are the actual tasks left"). A fixed message to
# the project's coordinator; only the project key, the counts and the ticket list are filled in.
TASK_CHECK_TEMPLATE = (
    "Task check from Jay via command-center: {project}.\n"
    "We have been through a lot of design changes. Jay wants {project}'s task list in Command Center to be exactly "
    "the work that is left — no stale tasks, nothing missing. Check every open task below against the repo as it is "
    "now: the code, plans/, docs/ and every .md file that holds or used to hold tasks (INDEX.md, TODO, backlog, plan "
    "files). See them all with: python -m ccd.pipeline_cli tasks {project}\n"
    "1. A task that is done already, superseded by a later design, a duplicate or no longer wanted: propose it as "
    "stale (Jay decides Cancel or Keep; never cancel, close or edit a task yourself):\n"
    "   python -m ccd.pipeline_cli stale <KEY> --role coordinator --reason \"<why, naming the file or task that replaces it>\"\n"
    "2. Work still needed that is listed in a .md file but has no task here: add it (it lands in the Inbox):\n"
    "   python -m ccd.pipeline_cli add {project} --role coordinator --title \"…\" --note \"<source file:line>\"\n"
    "3. A task you cannot judge: ask Jay one clear question on it:\n"
    "   python -m ccd.pipeline_cli ask <KEY> --role coordinator --question \"…\"\n"
    "Copy no licensed data, records, addresses or secrets into a task, reason or question.\n"
    "This check changes no code: do not plan, start or implement anything, and do not edit, move or delete files.\n"
    "Not authorized by this message: merge, deploy, production, --apply, secrets, rule changes.\n"
    "A task waits for Jay only while it, or a task it is blocked by, has an open question or decision for him.\n"
    "When done, report in one line: {project} task check: <n> stale proposed, <n> added, <n> questions.\n"
    "Open tasks now ({n}):\n{tasks}"
)
# Go Live: Jay's one press to get a project's merged batch ready to deploy. ccd runs nothing itself and the message
# authorizes no deploy: the coordinator PREPARES (runbook steps, checks, rollback plan) and waits; Jay confirms the
# deploy himself in the coordinator's pane. A Command Center message never authorizes a deploy.
GO_LIVE_TEMPLATE = (
    "Go Live from Jay via command-center: PREPARE the deploy of {project}. Do not deploy yet.\n"
    "Jay pressed Go Live after reading the morning report. That press approved the live-deploy gate on: {approved}. "
    "It does not start a deploy: Jay will confirm the deploy himself in this pane once he has read your preparation.\n"
    "Prepare by this repository's deploy runbook (docs/deployment.md, or the runbook AGENTS.md / CLAUDE.md names). If "
    "the repository has no deploy runbook, stop and tell Jay; do not improvise one.\n"
    "1. Read the release candidate (the newest report in ~/command-center/night-shift/{project}/, or the PRs merged "
    "since the last deploy) and note the version live now: that is the rollback target.\n"
    "2. Write down, in order: the runbook steps you would run, any migrations (say if there are none), the "
    "pre-deploy checks (run the ones that touch nothing in production), the post-deploy checks and every TEST AFTER "
    "DEPLOY step, and the rollback plan with the failure that triggers it.\n"
    "3. Save it to ~/command-center/deploys/{project}/<YYYY-MM-DD-HHMM>-plan.md and summarise it here in at most "
    "10 lines.\n"
    "4. Then stop and wait for Jay. Not authorized by this message: deploying, running migrations, restarting "
    "services, merging, force-push, changing secrets or infrastructure config, any other project. Only after Jay "
    "confirms the deploy in this pane: deploy by the runbook, run its checks, roll back by the runbook right away if "
    "one fails, and record each ticket ({approved}): python -m ccd.pipeline_cli deployed <KEY> --role coordinator "
    "--env live --result pass|fail --evidence \"…\" (it is refused if the approval did not go through: tell Jay).\n"
    "Report in one line when the preparation is ready: {project} go-live plan ready — <commit> — <checks> — "
    "<rollback target>."
)

# The per-ticket deploy gate (GateCard "Approve live deploy", WorkPanel "Approve deploy"): the same rule as Go Live.
# The approval is a real live-deploy approval, but the message only asks Claude to PREPARE; Jay confirms the deploy
# in the task pane. Nothing in ccd enforces that wait: it rests on this text.
GATE_DEPLOY_TEMPLATE = (
    "Jay approved the live-deploy gate of {key} in Command Center: PREPARE its deploy. Do not deploy yet.\n"
    "Use this repository's deploy runbook (docs/deployment.md, or the runbook AGENTS.md / CLAUDE.md names). If there "
    "is none, stop and tell Jay. Write, in 10 lines or fewer: the steps, the migrations (or none), the pre-deploy "
    "checks that touch nothing in production, the post-deploy checks, and the rollback plan (the version live now "
    "and what failure triggers a rollback).\n"
    "Then stop and wait for Jay to confirm the deploy in this pane. Only after he confirms: deploy, verify it live, "
    "roll back if a check fails, and record it: python -m ccd.pipeline_cli deployed {key} --role coordinator "
    "--env live --result pass|fail --evidence \"…\""
)

# Merge: Jay's one press to merge a project's Ready-to-Merge PRs. ccd merges nothing itself; it approves exactly
# the reviewed, green heads listed and the coordinator merges them one at a time in that order.
MERGE_TEMPLATE = (
    "Merge from Jay via command-center: merge {project}'s ready PRs now, one at a time, in this order:\n"
    "{items}\n"
    "Jay approved exactly these PRs at exactly these heads. For each one, in order:\n"
    "1. Check: the PR is open, its head is still the approved head above, CI is green on that head, and GitHub "
    "can merge it into main without a new commit on the branch. If not — the head changed, CI is not green, there "
    "is a conflict, or GitHub wants the branch updated first — skip it and say why. Never rebase, update or push "
    "to the branch: a new head needs a new review.\n"
    "2. Merge it the way this repository merges (its existing convention, e.g. gh pr merge <n> --merge). Never "
    "--admin, never force.\n"
    "3. Wait for CI on main for that merge commit. If main goes red: stop merging this repository, say which merge "
    "broke main, and leave the rest for Jay. Do not revert unless this repository's workflow says to.\n"
    "After the last merge, verify main by this repository's own verification workflow and record each merged "
    "ticket: python -m ccd.pipeline_cli verify <KEY> --role verifier --result pass|fail --evidence \"…\".\n"
    "Authorized by this message: merging exactly the PRs and heads listed above. Not authorized: deploying or "
    "going live, pushing to main, force-push, --admin, editing any branch, merging anything else.\n"
    "Report in one line: {project} merge: <n> merged, <n> skipped (why), main CI <green|red>."
)

# Night shift: the same instructions as Claude's /night-shift skill (scripts/install-claude-commands.sh links
# ~/.claude/skills/night-shift to this folder). Only the project key is filled in.
NIGHT_SHIFT_FILE = Path(__file__).parent / "skills" / "night-shift" / "SKILL.md"


CAREFUL_FILE = NIGHT_SHIFT_FILE.with_name("careful.md")


def night_shift_text(project):
    """The /night-shift text for one project; a careful project (registry night: careful) gets careful.md too."""
    raw = NIGHT_SHIFT_FILE.read_text(encoding="utf-8")
    if raw.startswith("---"):
        raw = raw.split("---", 2)[2]
    lines = [ln for ln in raw.strip().splitlines() if not ln.startswith("Project key:")]
    text = "\n".join(lines)
    if registry.night_mode(project) == "careful":
        careful = [ln for ln in CAREFUL_FILE.read_text(encoding="utf-8").strip().splitlines()
                   if not ln.startswith("Applies to:")]
        text += "\n\n" + "\n".join(careful)
    return text.replace("<project>", project)


UI_TEST_FILE = NIGHT_SHIFT_FILE.parent.parent / "ui-test" / "SKILL.md"


def ui_test_text(project):
    """The /ui-test text for one project, with its fix mode (registry ui_fix: ask | auto)."""
    raw = UI_TEST_FILE.read_text(encoding="utf-8")
    if raw.startswith("---"):
        raw = raw.split("---", 2)[2]
    lines = [ln for ln in raw.strip().splitlines() if not ln.startswith("Project key:")]
    return "\n".join(lines).replace("<project>", project).replace("<fix_mode>", registry.ui_fix(project))


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
TASK_CHECK_LIST_MAX = 5000   # characters of the ticket list in the message; the rest: `pipeline_cli tasks`
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
    info["procs"], info["claudeCount"] = top_processes()
    return info, (idle, tot)


def top_processes(limit=8, proc="/proc"):
    """Largest processes by resident memory: pid, short name (comm), MB, and how many are `claude`.

    comm only — never the command line, which can carry tokens or paths to data.
    """
    rows, claude = [], 0
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    try:
        pids = [d for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return [], None
    for pid in pids:
        try:
            name = Path(proc, pid, "comm").read_text().strip()
            rss = int(Path(proc, pid, "statm").read_text().split()[1]) * page
        except (OSError, ValueError, IndexError):
            continue
        if name == "claude":
            claude += 1
        rows.append({"pid": int(pid), "name": name[:32], "rssMB": round(rss / 2**20)})
    rows.sort(key=lambda r: r["rssMB"], reverse=True)
    return rows[:limit], claude


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
    def __init__(self, cfg, store, herdr, *, github_fn=None, host_fn=None, git_fn=None, oom_fn=None, tasks=None,
                 gh_cli=None, policy=None):
        self.cfg = cfg
        self.store = store
        # Project Operating Profiles (policy/): read once at start. Read-only here; the registry still drives
        # behaviour. A broken or drifting profile raises an alert, never stops ccd.
        self.policy = policy if policy is not None else profiles.load()
        self.herdr = herdr
        self.tasks = tasks  # TaskStore, durable product data (tasks.db); None = task system off
        self.pipeline = pipeline_mod.Pipeline(tasks) if tasks is not None else None
        # Auto-merge (CC-025): the config switch is read once, here. `gh_cli(args) -> (code, stdout, stderr)` is the
        # only way ccd writes to GitHub; tests give it a fake. The stop file is checked before every merge.
        self.auto_merge_on = cfg.get("auto_merge") is True
        if self.pipeline is not None:
            self.pipeline.auto_merge = self.auto_merge_on
        self.gh_cli = gh_cli or sources._run
        self.auto_merge_stop = AUTO_MERGE_STOP
        self._am_busy = False
        self._am_next = {}    # ticket key → time.monotonic() before which it is not looked at again
        # ticket key → (review stamp, time.monotonic() when it first had to wait): the 30-minute pending clock.
        # Memory only, on purpose: a restart merely delays the gate by up to 30 minutes, it never merges earlier.
        # An entry is dropped when its ticket leaves the candidates (e.g. back to review) or its stamp changes.
        self._am_waiting = {}
        # Autonomy Engine, SHADOW MODE (D-008): records what the target policy would have done next to what ccd did.
        # Nothing reads it to act. `_shadow_pr`: ticket key → (head, the `gh pr view` auto-merge just read), so the
        # engine sees the changed files of a PR ccd merged or held; it is never used for anything else.
        self.shadow = autonomy.Shadow(tasks.db) if getattr(tasks, "db", None) is not None else None
        self._shadow_pr = {}
        # Decision + Approval records (PR 4): a mirror of today's gates and answered questions. Gates still decide.
        self.ledger = ledger.Ledger(tasks.db) if getattr(tasks, "db", None) is not None else None
        # Worker nodes (PR 5): the model and enrolment only. Nothing is scheduled on a node yet (Phase 2).
        # Phase 2 shadow step 2 (Jay 2026-10-25): node keys and signed heartbeats, recorded only. Off unless config.json
        # says "phase2_node_shadow": true; read once, here. Revoking a node revokes its key; approving does not
        # approve it (the UI does not show the key fingerprint yet).
        self.node_shadow_on = isinstance(cfg, dict) and cfg.get("phase2_node_shadow") is True
        if self.node_shadow_on and not nodekeys_mod.AVAILABLE:
            log.warning(json.dumps({"msg": "phase2_node_shadow is on but the cryptography package is missing; "
                                           "the node shadow check stays off"}))
            self.node_shadow_on = False
        self.node_keys = nodekeys_mod.NodeKeys(tasks.db) if getattr(tasks, "db", None) is not None else None
        self.workers = workers_mod.Workers(tasks.db, version=__version__, keys=self.node_keys) \
            if getattr(tasks, "db", None) is not None else None
        # Needs You v2 (PR 6): what v2 knows about each queue item. Read-only.
        self.inbox = inbox_mod.Inbox(tasks.db) if getattr(tasks, "db", None) is not None else None
        # PR 7: who did what (audit trail + per-agent actor tokens) and what it used (token metering). All three
        # record; none refuses a request or stops work. Identity enforcement and budget limits are Phase 2.
        has_db = getattr(tasks, "db", None) is not None
        self.audit = audit_mod.Audit(tasks.db) if has_db else None
        self.actor_tokens = identity_mod.ActorTokens(tasks.db) if has_db else None
        meter_cfg = (cfg.get("meter") or {}) if isinstance(cfg, dict) else {}
        self.meter = meter_mod.Meter(tasks.db, roots=meter_cfg.get("roots"), attribute=self._meter_attribute) \
            if has_db and meter_cfg.get("enabled", True) else None
        self.meter_read_at = None   # last successful meter pass (time.time()); None until the first one
        # Onboarding groundwork (D-024 proposed; Jay 2026-10-23): agent registration records, drafts, validation,
        # reads and the shadow budget report (D-033). Off unless config.json says "onboarding_groundwork": true; read
        # once, here. Records only: it grants no permission, issues no credential and starts no agent.
        self.onboarding_on = isinstance(cfg, dict) and cfg.get("onboarding_groundwork") is True
        # Phase 2 shadow identity record (Jay 2026-10-25). Off unless config.json says "phase2_identity_shadow": true;
        # read once, here. Records only: it never refuses a write.
        self.identity_shadow_on = isinstance(cfg, dict) and cfg.get("phase2_identity_shadow") is True
        # Phase 2 shadow step 3 (Jay 2026-10-25): the Capability Broker, recorded only (ccd/broker.py). Off unless
        # config.json says "phase2_broker_shadow": true; read once, here. It never refuses or changes an action.
        self.broker_shadow_on = isinstance(cfg, dict) and cfg.get("phase2_broker_shadow") is True
        self.broker = broker_mod.Shadow(tasks.db) if has_db else None
        self.onboarding = onboarding_mod.Onboarding(tasks.db, enabled=self.onboarding_on) if has_db else None
        self._auto_seen = {}  # project -> GitHub asOf already run through ticket automation
        self.github_fn = github_fn or sources.github
        self.host_fn = host_fn or host_snapshot
        self.git_fn = git_fn or self._git_collect
        self.oom_fn = oom_fn or oom_kills_24h
        self.started = _now()
        self.subscribers = set()
        self._loops = []
        self._stopping = False
        self.ptys = None          # pty.PtyManager, set by __main__
        self.records_dir = None   # where task records are written; None = off (tests, previews)
        self.night = None         # nightshift.NightShift (reports + supervisor state); set by __main__
        self.uitests = None       # uitests.UiTests (UI test runs and Jay's decisions); set by __main__
        self._activity = {}       # project → when one of its tickets last changed (night-shift progress)
        self._record_timers = {}
        self._closing = set()
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
        (branches, _) = store.get("git:branches", {})
        self.git = {"unpushed": unpushed or {}, "worktrees": worktrees or {}, "branches": branches or {},
                    "asOf": git_at, "error": None}
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
                 self.housekeeping_loop, self.night_loop, self.meter_loop]
        self._loops = [asyncio.create_task(fn(), name=fn.__name__) for fn in loops]
        self._event("daemon", "daemon.started", f"ccd {__version__} started", data={"pid": os.getpid()})
        self._log_merge_policy()
        self._log_policy()
        self._ledger_start()
        self._workers_start()
        self._log_onboarding()
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
        if source == "tasks" and kw.get("project"):
            self._activity[kw["project"]] = _now()
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
            except Exception as e:  # noqa: BLE001 — like every other loop: one failure must not end herdr watching
                if not isinstance(e, (OSError, ConnectionError, herdr_mod.HerdrError, asyncio.TimeoutError,
                                      json.JSONDecodeError, ValueError)):
                    # ccd's own failure (e.g. ccd.db full), not herdr's: keep the traceback, show it in health
                    log.exception("herdr loop error")
                try:
                    self._herdr_down(e)  # sets herdr_state first; its event write can fail the same way
                except Exception:  # noqa: BLE001
                    log.exception("could not record herdr down")
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
        unpushed, worktrees, branches = {}, {}, {}
        for p in self.cfg["projects"]:
            if p.get("path"):
                unpushed[p["key"]] = sources.unpushed_branches(p["path"])
                worktrees[p["key"]] = sources.worktree_paths(p["path"])
                branches[p["key"]] = sources.branches_ahead(p["path"], p.get("branch") or "main")
        return unpushed, worktrees, branches

    async def poll_git_once(self):
        got = await asyncio.to_thread(self.git_fn)
        unpushed, worktrees, branches = got if len(got) == 3 else (got[0], got[1], {})
        self.git.update(unpushed=unpushed, worktrees=worktrees, branches=branches, asOf=_now(), error=None)
        self.store.put("git:unpushed", unpushed)
        self.store.put("git:worktrees", worktrees)
        self.store.put("git:branches", branches)
        if self.panes:  # before herdr's first answer there is nothing to re-place, and the
            # remembered agent set from the last run must survive until it is compared.
            self.panes = self._attribute(self.panes)
            self._prev_agents = self._agent_digest(self.panes)
        self._dirty.set()
        try:
            await self.clean_worktrees()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — cleanup is optional; the poll above already succeeded
            log.warning(json.dumps({"msg": "worktree cleanup crashed", "error": repr(e)[:200]}))

    async def clean_worktrees(self):
        """After the git poll: remove each DONE ticket's worktree that is clean and fully pushed.
        All checks and the one `git worktree remove` live in worktree_cleanup.py; this only feeds it
        the ticket rows and herdr's pane directories (None while herdr is down) and records the outcome.
        A kept worktree is recorded once per reason, not every poll."""
        if self.pipeline is None or not self.cfg.get("worktree_cleanup", True):
            return
        items = []
        for key, project, branch, path in self.pipeline.done_worktrees():
            items.append((key, project, registry.root_of(project), branch, path))
        if not items:
            return
        ready = self.herdr_state["connected"] and self.herdr_state["lastSnapshotAt"] is not None
        cwds = [p.get("cwd") or "" for p in self.panes] if ready else None
        results = await asyncio.to_thread(worktree_cleanup.run, items, cwds)
        kept, _ = self.store.get("git:wt_kept", {})
        kept = dict(kept or {})
        seen = {key for key, *_ in items}
        changed = False
        for key, project, path, outcome, reason in results:
            if outcome == "removed":
                self._broker("worktree.remove", project, f"{key}: {path}")
                kept.pop(key, None)
                changed = True
                gone = os.path.normpath(path)
                for k, paths in list(self.git["worktrees"].items()):
                    self.git["worktrees"][k] = [x for x in paths or [] if os.path.normpath(x) != gone]
                self.store.put("git:worktrees", self.git["worktrees"])
                self._event("tasks", "task.pipeline", f"{key} worktree removed: {path}", project=project, ref=key,
                            data={"kind": "pipeline.worktree_removed"})
            elif kept.get(key) != reason:
                kept[key] = reason
                changed = True
                self._event("tasks", "task.pipeline", f"{key} worktree kept: {reason}", project=project, ref=key,
                            data={"kind": "pipeline.worktree_kept", "reason": reason})
        for key in [k for k in kept if k not in seen]:
            del kept[key]
            changed = True
        if changed:
            self.store.put("git:wt_kept", kept)
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
        await self._auto_merge()
        self._workers_beat()
        snap["seq"] = self.seq if quiet else snap_seq
        self.snap = snap

    def _decorate(self, snap):
        """Public shape: agent roles, canonical coordinators, source freshness."""
        coord = {}
        views = {v["key"]: v for v in snap.get("projects") or []}
        for p in self.cfg["projects"]:
            r = (views.get(p["key"]) or {}).get("coordinatorState") or coordinators.public_resolution(
                coordinators.resolution(p, snap["panes"]))
            coord[p["key"]] = {"name": coordinators.canonical(p), "paneId": r["paneId"],
                               "status": r["status"] if r["state"] == "ready" else "offline",
                               "canonical": r["state"] == "ready", "state": r["state"], "how": r["how"],
                               "candidates": r["candidates"]}
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
        snap["worktrees"] = {k: list(v or []) for k, v in (self.git["worktrees"] or {}).items()}
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
        problems = self.policy.problems()
        if problems:
            out.append({"id": "policy:problems", "severity": "warn", "source": "policy", "project": None,
                        "text": f"policy: {len(problems)} problem(s) — {problems[0]}"})
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

    # ---------- night shift supervisor (nightshift.py) ----------

    NIGHT_TICK = 60

    async def night_loop(self):
        while not self._stopping:
            await asyncio.sleep(self.NIGHT_TICK)
            try:
                await self.night_tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — the supervisor must never take ccd down
                log.warning(json.dumps({"msg": "night shift tick failed", "error": repr(e)[:200]}))

    async def night_tick(self):
        """Remind each idle night-shift coordinator to continue, or end its shift (nightshift.NightShift.decide)."""
        if self.night is None:
            return
        for proj in self._projects():
            key = proj["key"]
            if not self.night.active(key):
                continue
            if registry.paused(key):
                self.night.end(key, "paused by Jay")
                continue
            # With herdr down there is no status: only "complete" and the morning cutoff can act, never a reminder.
            r = coordinators.resolution(proj, self.panes) if self.herdr_state["ok"] else {"state": "none"}
            status = r.get("status") if r["state"] == "ready" else None
            action = self.night.decide(key, status, self._activity.get(key))
            if action == "nudge":
                try:
                    agent = await self._fresh_agent(r["paneId"])
                    if agent["status"] in ("idle", "done"):   # busy or blocked now: nothing sent, nothing counted
                        # "idle" only means ready for input, not that the input box is empty: agent.prompt pastes
                        # and presses Enter, so a half-typed draft of Jay's would be submitted. Read the pane's
                        # text (never stored or logged) and send only when the input line is plainly empty;
                        # a draft, or a screen we cannot parse, means skip (best effort, not counted).
                        screen = await self.herdr.read_tail(agent["pane_id"], 40)
                        if nightshift_mod.input_is_empty(screen["text"]) is not True:
                            self.night.skipped(key, "input line not empty or not recognised")
                            continue
                        self._broker("pane.input", key, f"night-shift nudge -> pane {agent['pane_id']}")
                        await self.herdr.prompt(agent["pane_id"], self.night.nudge_text(key))
                        self.night.nudged(key)               # counted only once it was delivered
                        self._event("action", "action.night_shift", f"night shift reminder → {coordinators.canonical(proj)}",
                                    project=key, agent_id=agent["pane_id"], data={"kind": "night_shift_nudge"})
                except (ActionError, OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
                    log.warning(json.dumps({"msg": "night shift reminder failed", "project": key, "error": str(e)[:160]}))
            elif action and action.startswith("end:"):
                why = self.night.get(key).get("endReason") or action[4:]
                self._event("action", "action.night_shift", f"{key} night shift ended: {why}", project=key,
                            data={"kind": "night_shift_ended", "reason": why})

    def night_state(self):
        """Every project's night shift: state, coordinator, the newest morning report."""
        out = {}
        for proj in self._projects():
            key = proj["key"]
            r = coordinators.resolution(proj, self.panes) if self.herdr_state["ok"] else {"state": "none"}
            st = self.night.get(key) if self.night else {}
            out[key] = {"active": bool(self.night and self.night.active(key)), "paused": registry.paused(key),
                        "mode": registry.night_mode(key), **{k: st.get(k) for k in (
                "startedAt", "endedAt", "endReason", "nudges", "cutoffAt", "goLiveAt")},
                "coordinator": {"name": coordinators.canonical(proj), "state": r["state"],
                                "status": r.get("status") if r["state"] == "ready" else None},
                "report": self.night.report(key) if self.night else None,
                "goLive": self.go_live_review(key)}
        return {"projects": out}

    async def act_night_end(self, project, actor="jay", developer=False):
        """Jay ends a project's night shift: no more reminders, and the coordinator is told to stop safely."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: ending the night shift sends a message to Claude")
        proj = self._project(project)
        if proj is None:
            raise ActionError(404, "unknown project")
        if self.night is None or not self.night.end(project, "ended by Jay"):
            raise ActionError(409, f"{project} has no night shift running")
        self._event("action", "action.night_shift", f"{project} night shift ended by Jay", project=project,
                    data={"kind": "night_shift_ended", "reason": "ended by Jay"})
        told = False
        if self.herdr_state["ok"]:
            r = coordinators.resolution(proj, self.panes)
            if r["state"] == "ready":
                try:
                    agent = await self._fresh_agent(r["paneId"])
                    # The message only, never Esc: an interrupt can leave a half-finished repository operation.
                    if agent["status"] != "blocked":
                        self._broker("pane.input", project, f"night-shift end -> pane {agent['pane_id']}")
                        await self.herdr.prompt(agent["pane_id"], nightshift_mod.END_TEXT.format(project=project))
                        told = True
                except (ActionError, OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
                    log.warning(json.dumps({"msg": "night shift end message failed", "error": str(e)[:160]}))
        return {"ok": True, "project": project, "told": told}

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

    def _announce(self, ticket, changes, teardown=True):
        """One ops event per change, so live clients refresh the ticket. The audit trail is in tasks.db.
        `teardown`: a close ends the task's sessions (pipeline steps, Jay with Developer Unlock); a plain edit
        with the ordinary token only records that they were left running."""
        if changes:
            self._record_soon(ticket["key"])
        for c in changes:
            if c["field"] == "status" and c["to"] in tasks_mod.CLOSED and c["from"] not in tasks_mod.CLOSED:
                self._closed_soon(ticket["key"], teardown)
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

    def _with_work(self, tickets):
        """Each ticket with the work facts the control room shows in lists: open gate, open questions,
        deploy state and the visible stage (pipeline.visible_stage)."""
        marks = self.pipeline.compact(t["id"] for t in tickets) if self.pipeline is not None else {}
        for t in tickets:
            m = marks.get(t["id"]) or {"gate": None, "gateReason": None, "openQuestions": 0, "deploy": None}
            t.update(gate=m["gate"], gateReason=m["gateReason"], openQuestions=m["openQuestions"], deploy=m["deploy"])
            t["visibleStage"] = pipeline_mod.visible_stage(t, m)
        return tickets

    def task_list(self, project=None, include_archived=False):
        ts = self._need_tasks()
        return {"tickets": self._with_work(ts.list(project=project, include_archived=include_archived)),
                "projects": ts.projects(), "meta": dict(ts.meta(), visibleStages=list(pipeline_mod.VISIBLE_STAGES)),
                "paused": {p["key"]: registry.paused(p["key"]) for p in self._projects() if registry.paused(p["key"])},
                "seq": self.seq}

    def task_get(self, key):
        return self._with_work([self._wrap(self._need_tasks().get, key)])[0]

    # ---------- development traceability ----------

    CI_WORD = {"\u2713": "PASS", "\u2717": "FAIL", "\u2026": "PENDING", "\u2013": "NONE"}
    DEV_STAGES = ("branch", "commits", "pr", "ci", "review", "merge", "verify", "deploy")

    def _pr_index(self, project_key):
        """PR number → one flat record, open PRs and recently merged ones alike."""
        g = self.gh.get(project_key) or {}
        data = g.get("data") or {}
        slug = next((p.get("repo") for p in self.cfg["projects"] if p["key"] == project_key), None) \
            or registry.github_of(project_key)
        out = {}
        for pr in data.get("prs") if isinstance(data.get("prs"), list) else []:
            if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
                continue  # one odd row must not 500 the whole view
            rollup = pr.get("statusCheckRollup")
            out[pr["number"]] = {
                "number": pr["number"], "state": "DRAFT" if pr.get("isDraft") else "OPEN",
                "url": github.pr_url(slug, pr["number"]), "title": pr.get("title"), "branch": pr.get("headRefName"),
                "ci": self.CI_WORD.get(model.ci_mark(rollup), "NONE"),
                "review": pr.get("reviewDecision") or "PENDING",
                "mergedAt": None, "asOf": g.get("asOf"),
            }
        for pr in data.get("merged") if isinstance(data.get("merged"), list) else []:
            if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
                continue
            prev = out.get(pr["number"]) or {}
            out[pr["number"]] = {**prev, "number": pr["number"], "state": "MERGED", "url": github.pr_url(slug, pr["number"]),
                                 "title": pr.get("title"), "mergedAt": pr.get("mergedAt"),
                                 "ci": prev.get("ci", "NONE"), "review": prev.get("review", "PENDING"),
                                 "branch": prev.get("branch"), "asOf": g.get("asOf")}
        return out

    def _branch_for(self, ticket, branches):
        """The ticket's branch, by strong evidence only.

        1. `ticket.branch` — set by hand or from a linked PR's head branch
        2. a local branch whose leading segment IS the key (SV-056-x, claude/SV-056)

        A key merely mentioned inside a branch name ("fix-after-SV-056") is not
        evidence and is ignored. Returns None rather than a guess.
        """
        named = ticket.get("branch")
        if named:
            row = branches.get(named) or {}
            return {"name": named, "evidence": "ticket branch", "exists": bool(row),
                    "commits": row.get("commits"), "head": row.get("head"), "at": row.get("at"),
                    "countOk": row.get("countOk", False)}
        key = ticket["key"]
        for name, row in sorted(branches.items()):
            if self.tasks.pr_keys("", name) == [key]:
                return {"name": name, "evidence": "branch named for the ticket", "exists": True,
                        "commits": row.get("commits"), "head": row.get("head"), "at": row.get("at"),
                        "countOk": row.get("countOk", False)}
        return None

    def development(self, project=None):
        """Ticket → branch → commits → PR → CI → review → merge → verify → deploy.

        Every association is evidence ccd can point at: the ticket's own branch,
        a branch whose leading segment is the key, or a PR linked to the ticket
        (which the automation only links when the key LEADS its title or branch).
        Nothing is inferred from a key mentioned in passing, and `deploy` is
        always unknown because ccd observes no deployments.
        """
        ts = self._need_tasks()
        tickets = ts.list(project=project)
        links = ts.links_by_key("github", "pr")
        prs_by_project = {}
        rows = []
        recorded = self.pipeline.recorded(t["id"] for t in tickets) if self.pipeline is not None else {}
        for t in tickets:
            if t["project"] not in prs_by_project:
                prs_by_project[t["project"]] = self._pr_index(t["project"])
            prs = prs_by_project[t["project"]]
            branches = (self.git.get("branches") or {}).get(t["project"]) or {}
            branch = self._branch_for(t, branches)
            linked = []
            for link in links.get(t["key"]) or []:
                num = link["ref"].rsplit("#", 1)[-1]
                rec = prs.get(int(num)) if num.isdigit() else None
                linked.append(rec or {"number": int(num) if num.isdigit() else None, "state": "UNKNOWN",
                                      "url": github.pr_ref_url(link["ref"]), "title": link["title"], "ci": "NONE",
                                      "review": "PENDING", "mergedAt": None, "branch": None, "asOf": None})
            pr = linked[0] if linked else None
            merged = bool(pr and pr["state"] == "MERGED")
            if merged:
                merge = "MERGED"
            elif t["status"] == "READY_TO_MERGE":
                merge = "WAITING FOR JAY"
            elif t["status"] == "BLOCKED":
                merge = "BLOCKED"
            else:
                merge = None
            verify = {"VERIFYING": "PENDING", "DONE": "DONE"}.get(t["status"])
            active = t["status"] in ("IN_PROGRESS", "IN_REVIEW", "READY_TO_MERGE", "VERIFYING")
            if not (branch or pr or active):
                continue
            rows.append({
                "key": t["key"], "project": t["project"], "title": t["title"], "status": t["status"],
                "priority": t["priority"], "assignee": t["assignee"], "flags": t["flags"],
                "updatedAt": t["updatedAt"],
                "branch": branch, "prs": linked, "pr": pr,
                "commits": (branch or {}).get("commits"),
                "ci": pr["ci"] if pr else None,
                "review": pr["review"] if pr else None,
                "merge": merge, "verify": verify, "deploy": None,
                "roles": (recorded.get(t["id"]) or {}).get("roles") or {},
                "pipelineReview": (recorded.get(t["id"]) or {}).get("review"),
            })
        rows.sort(key=lambda r: (-tasks_mod.STATUSES.index(r["status"]) if r["status"] in tasks_mod.STATUSES else 0,
                                 r["key"]))
        return {"rows": rows, "seq": self.seq, "gitAsOf": self.git.get("asOf"),
                "stages": list(self.DEV_STAGES),
                "notes": ["Associations use strong evidence only: the ticket's branch, a branch whose leading "
                          "segment is the key, or a PR linked to the ticket. A key mentioned in passing is not "
                          "an association.",
                          "deploy is always unknown: ccd observes no deployments."]}

    BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}$")

    def dev_commits(self, key, limit=50):
        """The commits on a ticket's branch that its base branch lacks: sha, subject, author, time, URL.
        Read-only `git log` in the registered checkout; nothing is fetched."""
        return self.dev_commits_run(self.dev_commits_plan(key, limit))

    def dev_commits_plan(self, key, limit=50):
        dev = self.development()
        row = next((r for r in dev["rows"] if r["key"] == str(key).upper()), None)
        if not row:
            raise ActionError(404, f"no development activity for {key}")
        branch = (row.get("branch") or {}).get("name") or ((row.get("pr") or {}).get("branch"))
        root = registry.root_of(row["project"])
        cfgp = next((p for p in self.cfg["projects"] if p["key"] == row["project"]), {})
        base = cfgp.get("branch") or "main"
        slug = cfgp.get("repo") or registry.github_of(row["project"])
        out = {"key": row["key"], "branch": branch, "base": base, "commits": [],
               "branchUrl": github.branch_url(slug, branch) if branch else None}
        return {"out": out, "root": root, "slug": slug, "limit": int(limit)}

    def dev_commits_run(self, plan):
        out, root, slug, limit = plan["out"], plan["root"], plan["slug"], plan["limit"]
        branch, base = out["branch"], out["base"]
        if not branch or not root or not self.BRANCH_RE.match(branch) or not self.BRANCH_RE.match(base):
            return out
        try:
            r = subprocess.run(["git", "-C", root, "log", f"--max-count={int(limit)}", "--no-color",
                                "--format=%H%x1f%s%x1f%an%x1f%at", f"refs/heads/{base}..refs/heads/{branch}", "--"],
                               capture_output=True, text=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired):
            out["error"] = "git log failed"
            return out
        if r.returncode != 0:
            out["error"] = "branch not found locally"
            return out
        for line in r.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            sha, subject, author, at = parts
            out["commits"].append({"sha": sha, "short": sha[:7], "message": subject[:300], "author": author[:100],
                                   "at": int(at) if at.isdigit() else None, "url": github.commit_url(slug, sha)})
        return out

    def workspace_projects(self):
        """Every registered project the Workspace can open: identity, root, branch, coordinator.
        Roots come from the registry only."""
        views = {v["key"]: v for v in (self.snap or {}).get("projects") or []}
        out = []
        for key, reg in sorted(registry.PROJECTS.items()):
            root = reg.get("root")
            branch = None
            if root and os.path.isdir(root):
                try:
                    r = subprocess.run(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                       text=True, timeout=3, check=False)
                    branch = r.stdout.strip() if r.returncode == 0 else None
                except (OSError, subprocess.TimeoutExpired):
                    branch = None
            coord = (views.get(key) or {}).get("coordinator") or None
            state = (views.get(key) or {}).get("coordinatorState") or None
            out.append({"key": key, "name": reg["name"], "prefix": reg["prefix"], "root": root,
                        "exists": bool(root and os.path.isdir(root)), "branch": branch,
                        "github": github.identity(reg.get("github") or ""),
                        "coordinator": {"id": coord.get("pane_id"), "name": coord.get("agent_name") or coord.get("label"),
                                        "status": coord.get("status"), "cwd": coord.get("cwd")} if coord else None,
                        # ready | found (adopt) | multiple (pick one) | none — from the one resolver
                        "coordinatorState": {k: state[k] for k in ("state", "how", "candidates")} if state else
                                            {"state": "none", "how": None, "candidates": []}})
        return {"projects": out}

    def task_context(self, key):
        ctx = self._wrap(self._need_tasks().context, key)
        t = ctx["ticket"]
        coord = (self.snap or {}).get("coordinators", {}).get(t["project"]) if self.snap else None
        ctx["coordinator"] = coord
        if self.pipeline is not None:
            w = self.pipeline.work(t["key"])
            extra = []
            for q in w["questions"]:
                extra.append(f"question: {q['text']} → {q['answer']}" if q["answer"] else f"open question: {q['text']}")
            cp = w.get("checkpoint")
            if cp:
                extra.append(f"checkpoint ({cp.get('frm') or '—'} → {cp.get('to')}): commit {cp.get('commit') or '—'}; "
                             f"remaining: {cp.get('remaining') or '—'}")
            if w.get("writer"):
                extra.append(f"worktree writer: {w['writer']}")
            if extra:
                ctx["brief"] += "\n\n" + "\n".join(extra)
            ctx["session"] = self.task_session(t["key"])
            # So the Task Room's Claude pane can attach (coordid.task_session matches the herdr name only).
            ctx["brief"] += (f"\n\nTask session: work {t['key']} in its own Claude session whose herdr pane is named "
                             f"{t['key'].lower()} (e.g. herdr pane rename to {t['key'].lower()}); Command Center's Task "
                             f"Room attaches to that name. Ask Jay questions with python -m ccd.pipeline_cli ask "
                             f"{t['key']} --role coordinator --question \"…\" — his answers come back into that session.")
            held = self.pipeline.held(t["key"])
            if held:
                ctx["brief"] += (f"\n\nWaits for Jay: open question(s) or decision(s) on "
                                 f"{', '.join(sorted({h['ref'] for h in held}))[:200]}. Do not start implementing "
                                 f"{t['key']} until he has answered; take another task meanwhile.")
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
        if actor != "jay":
            self._not_paused(str(body.get("project") or ""), "agent work")
        ticket, changes = self._wrap(ts.create, str(body.get("project") or ""), body.get("title"), actor, **fields)
        self._task_event("task.created", ticket, f"created · {ticket['title']}", {"status": ticket["status"]})
        return self._with_work([ticket])[0]

    # What decides a pipeline ticket's gates and stage. On a ticket in the pipeline these move
    # only through pipeline steps — or by Jay with Developer Unlock, as an explicit override.
    GATE_FIELDS = {"labels", "type", "flags", "archived"} | set(tasks_mod.FLAGS)

    def task_update(self, key, body, actor="jay", developer=False):
        if isinstance(body, dict) and self.pipeline is not None and self.tasks.exists(key):
            w = self._wrap(self.pipeline.work, key)
            owner = actor == "jay" and developer
            # The same rule as Pipeline.participating(): a plan, a recorded review, or an open gate.
            if self.pipeline.participating(key) or w["gate"]:
                if "status" in body and not owner:
                    raise ActionError(409, f"{w['key']} is in the pipeline: its status moves through pipeline steps "
                                           f"(or Jay with Developer Unlock)")
                # What decides a gate (labels, type, flags, archive) is fixed once a ticket is in the
                # pipeline — not only while a gate is open — or a flag could be dropped before its gate.
                if set(body) & self.GATE_FIELDS and not owner:
                    raise ActionError(409, f"{w['key']} is in the pipeline: its labels, type, flags and archive "
                                           f"change only with Jay's Developer Unlock")
        ticket, changes = self._wrap(self._need_tasks().update, key, body, actor)
        self._announce(ticket, changes, teardown=actor == "jay" and developer)
        return self._with_work([ticket])[0]

    # ---------- the ticket pipeline (plans/TICKET-PIPELINE-V1.md) ----------

    PIPELINE_OPS = ("plan", "start", "review", "verify", "confirm", "handoff", "block", "role", "finding",
                    "ask", "replan", "rework", "evidence", "writer", "deploy-request", "deployed", "stale")

    def task_work(self, key):
        self._need_tasks()
        w = self._wrap(self.pipeline.work, key)
        w["session"] = self.task_session(w["key"])
        w["project"] = self.tasks.get(w["key"])["project"]
        return w

    def _open_prs(self, ticket):
        """The ticket's linked PRs that the last GitHub poll saw open, as pipeline PR states."""
        g = (self.gh.get(ticket["project"]) or {}).get("data") or {}
        refs = {link["ref"] for link in ticket.get("links") or [] if link.get("provider") == "github" and link.get("kind") == "pr"}
        repo = next((p.get("repo") for p in self.cfg["projects"] if p["key"] == ticket["project"]), None) \
            or registry.github_of(ticket["project"])
        out = []
        for pr in g.get("prs") if isinstance(g.get("prs"), list) else []:
            ref = f"{repo}#{pr.get('number')}"
            if ref in refs:
                ci = model.ci_mark(pr.get("statusCheckRollup"))
                out.append({"ref": ref, "head": pr.get("headRefOid") or "", "ciGreen": ci in ("✓", "–"),
                            "ciNone": ci == "–", "draft": bool(pr.get("isDraft"))})
        return out

    def _pr_state(self, ticket):
        prs = self._open_prs(ticket)
        return prs[0] if len(prs) == 1 else None

    def task_work_op(self, key, op, body, actor="jay", developer=False):
        """One pipeline step. Owner gates (confirm) need Jay with Developer Unlock; the rest any token holder,
        recorded under the actor it states (X-CCD-Actor: agent:<role>)."""
        self._need_tasks()
        if op not in self.PIPELINE_OPS:
            raise ActionError(404, f"unknown pipeline step {op}")
        if actor != "jay" and self.tasks.exists(key):
            self._not_paused(self.tasks.get(key)["project"], "agent work")
        if not isinstance(body, dict):
            raise ActionError(400, "body must be an object")
        pl = self.pipeline
        meta = {"model": body.get("model"), "session": body.get("session")}
        if "usage" in body:
            self._meter_report(key, op, actor, body)
        if op == "plan":
            r = self._wrap(pl.plan, key, body.get("plan"), actor, **meta)
        elif op == "start":
            r = self._wrap(pl.start, key, body.get("branch"), body.get("worktree"), actor, **meta)
        elif op == "review":
            t = self._wrap(self.tasks.get, key)
            if len(self._open_prs(t)) > 1:
                raise ActionError(409, f"{t['key']} has several open PRs linked; one PR per ticket review")
            r = self._wrap(pl.review, key, body.get("verdict"), body.get("head"), actor, body.get("findings") or [],
                           pr=self._pr_state(t), **meta)
        elif op == "verify":
            r = self._wrap(pl.verify, key, body.get("result"), body.get("evidence"), actor, **meta)
        elif op == "confirm":
            if not developer:
                raise ActionError(403, "Developer Unlock required")
            # A live-deploy approval from the ticket's gate is marked "jay:gate": the message asks Claude to
            # PREPARE and wait for Jay in the pane (GATE_DEPLOY_TEMPLATE), like Go Live.
            r = self._wrap(pl.confirm, key, body.get("gate"), actor,
                           "gate" if body.get("gate") == "deploy" else None)
        elif op == "handoff":
            r = self._wrap(pl.handoff, key, body, actor)
        elif op == "block":
            explain = body.get("explain") if isinstance(body.get("explain"), dict) else \
                {k: body.get(k) for k in pl.EXPLAIN if body.get(k)}
            r = self._wrap(pl.block, key, body.get("reason"), actor, explain or None)
        elif op == "role":
            r = self._wrap(pl.role, key, body.get("role"), actor, **meta)
        elif op == "finding":
            r = self._wrap(pl.finding, key, body.get("finding"), actor, body.get("source") or "review")
        elif op == "ask":
            r = self._wrap(pl.ask, key, body.get("questions"), actor)
        elif op == "replan":
            r = self._wrap(pl.replan, key, body.get("reason"), actor)
        elif op == "rework":
            r = self._wrap(pl.rework, key, body.get("reason"), actor,
                           open_prs=self._open_prs(self._wrap(self.tasks.get, key)))
        elif op == "evidence":
            r = self._wrap(pl.evidence, key, body.get("kind"), body.get("ref"), body.get("note"), actor, body.get("stage"))
        elif op == "writer":
            r = self._wrap(pl.writer, key, body.get("owner"), actor, body.get("checkpoint"))
        elif op == "stale":
            r = self._wrap(pl.stale, key, body.get("reason"), actor)
        elif op == "deploy-request":
            self._broker_ticket("deploy.request", key, body.get("env"))
            r = self._wrap(pl.deploy_request, key, body.get("env"), body.get("what"), body.get("verification"), actor)
        else:
            self._broker_ticket("deploy.record", key, body.get("env"))
            r = self._wrap(pl.deployed, key, body.get("env"), body.get("result"), body.get("evidence"), actor)
        self._pipeline_result(*r)
        return self.task_work(key)

    # What the task Claude session is told after a step that changes its course. Best effort: an
    # idle session gets it at once; otherwise the step stands and the UI offers to resend.
    def _nudge_text(self, key, op, body, work):
        if op == "rework":
            return (f"Jay sent {key} back to implementation: {body.get('reason')}. Fix it in this session (same "
                    f"worktree), then push the fix; ccd moves it back to review on the new head.")
        if op == "replan":
            return (f"Jay moved {key} back to planning: {body.get('reason')}. Re-plan with Opus, record the revised plan "
                    f"and acceptance criteria (python -m ccd.pipeline_cli plan {key} …), and continue only after it is accepted.")
        if op == "confirm" and body.get("gate") == "deploy" and (work.get("deploy") or {}).get("approvedAt"):
            return GATE_DEPLOY_TEMPLATE.format(key=key)
        if op == "confirm" and body.get("gate") == "failure":
            return f"Jay cleared the blocker on {key}. Continue from {work.get('stage') or 'the blocked stage'}."
        if op == "confirm" and body.get("gate") == "plan":
            return f"Jay approved the plan for {key}. Start implementation."
        if op == "writer" and body.get("owner") == "claude" and isinstance(body.get("checkpoint"), dict):
            # A FIXED line: the checkpoint's free text is never typed into Claude; Claude reads it as data.
            return (f"You now own the {key} worktree. Read the handover checkpoint with "
                    f"`python -m ccd.pipeline_cli work {key}` and resume from the current state; do not restart the "
                    f"implementation.")
        return None

    async def task_work_op_async(self, key, op, body, actor="jay", developer=False):
        work = self.task_work_op(key, op, body, actor, developer)
        # Jay's steps reach Claude only with Developer Unlock (typing into Claude is a developer action). The one
        # agent-initiated delivery is a writer handover WITH a checkpoint: one fixed sentence (no free text), to
        # the task session only.
        text = self._nudge_text(work["key"], op, body or {}, work) \
            if (actor == "jay" and developer) or op == "writer" else None
        if text:
            delivered, reason = await self._nudge_task(work["key"], text)
            work = dict(work, nudge={"delivered": delivered, "reason": reason})
        return work

    def task_session(self, key):
        """The ticket's task Claude session, from the one resolver (coordid.task_session). A pane that is any
        project's coordinator is never one, whatever it is named."""
        snap = self.snap or {}
        coords = {c.get("paneId") for c in (snap.get("coordinators") or {}).values() if c.get("paneId")}
        coords |= {a.get("pane_id") or a.get("id") for a in snap.get("agents") or [] if a.get("role") == "coordinator"}
        return coordid.task_session(key, self.panes, exclude=coords)

    async def _nudge_task(self, key, text):
        """Tell the EXISTING task Claude session something. Never starts, resumes or duplicates one."""
        r = self.task_session(key)
        if r["state"] != "ready":
            return False, ("no task Claude session is running for " + key if r["state"] == "none"
                           else f"several Claude sessions are named {key.lower()}")
        try:
            await self.act_prompt(r["paneId"], text)
        except ActionError as e:
            return False, e.message
        return True, None

    async def task_answers(self, key, body, actor="jay", developer=False):
        """Jay answers Claude's questions. When the last open one is answered, the SAME task Claude session
        is resumed with the answers (and the scope guard); a scope change sends the ticket back to planning."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: answering sends your answers to Claude")
        if not isinstance(body, dict):
            raise ActionError(400, "body must be an object")
        answers = body.get("answers") or []
        scope = bool(body.get("scopeChange"))
        pl = self.pipeline
        before = {q["id"]: q for q in self.task_work(key)["questions"]}
        if answers:
            self._pipeline_result(*self._wrap(pl.answer, key, answers, actor))
        # The task check: Jay's answer to a stale proposal. "Cancel it" cancels the ticket (and ends its
        # sessions); "Keep it" keeps it. Neither is typed into any Claude session.
        stale = [a for a in answers if isinstance(a, dict) and (before.get(a.get("id")) or {}).get("purpose") == "stale"]
        if stale:
            q = before[stale[0]["id"]]
            reason = q["text"].split(" — ", 1)[-1]
            if str(stale[0].get("answer") or "").strip() == pipeline_mod.STALE_OPTIONS[0]:
                self.task_comment(key, f"Cancelled in the task check. Claude's reason: {reason}", actor)
                self.task_update(key, {"status": "CANCELLED"}, actor, developer=True)
                return {"work": self.task_work(key), "complete": True, "delivered": False, "cancelled": True,
                        "reason": "cancelled in the task check"}
            self.task_comment(key, f"Kept in the task check (Claude had proposed it as stale: {reason})", actor)
            if len(stale) == len(answers):
                return {"work": self.task_work(key), "complete": True, "delivered": False, "cancelled": False,
                        "reason": "kept in the task check"}
        work = self.task_work(key)
        if work["openQuestions"]:
            return {"work": work, "complete": False, "delivered": False,
                    "reason": f"{work['openQuestions']} question(s) still open"}
        answered = [q for q in work["questions"] if q["answer"] is not None and q.get("purpose") != "stale"]
        if not answered:
            raise ActionError(409, f"{work['key']} has no questions to answer")
        replanned = False
        if scope and work["status"] != "RESEARCHING":
            self._pipeline_result(*self._wrap(pl.replan, key, "Jay's answers change the approved scope", actor))
            replanned = True
        latest = max(q["batch"] for q in answered)
        lines = [f"Jay answered your questions on {work['key']}:", ""]
        for i, q in enumerate([q for q in answered if q["batch"] == latest], 1):
            lines += [f"{i}. {q['text']}", f"   → {q['answer']}", ""]
        if replanned:
            lines.append(f"Jay marked these answers as changing the approved scope. {work['key']} is back in Planning: "
                         f"re-plan with Opus, record the revised plan and acceptance criteria "
                         f"(python -m ccd.pipeline_cli plan {work['key']} …), and continue implementation only after "
                         f"the revised plan is accepted.")
        else:
            lines.append(f"Before continuing: if any answer materially changes the approved scope, architecture, security, "
                         f"data model, permissions/auth or major UX direction, move the ticket back to planning "
                         f"(python -m ccd.pipeline_cli replan {work['key']} --role coordinator --reason \"…\"), re-plan with "
                         f"Opus and update the plan and acceptance criteria. Otherwise continue in this session.")
        text = "\n".join(lines)
        if len(text) > 7900:
            text = text[:7880] + "\n[…truncated]"
        delivered, reason = await self._nudge_task(work["key"], text)
        if delivered:
            self._event("tasks", "task.pipeline", f"{work['key']} answers delivered to its Claude session",
                        project=work.get("project") or self.tasks.get(key)["project"], ref=work["key"],
                        data={"kind": "pipeline.answers_delivered"})
        return {"work": self.task_work(key), "complete": True, "delivered": delivered, "reason": reason,
                "replanned": replanned}

    def task_record(self, key):
        """task.md and workflow.md as rendered now (and written, when records are on)."""
        t = self._wrap(self._need_tasks().get, key)
        w = self.task_work(key)
        out = {"key": t["key"], "taskMd": records_mod.render_task(t, w), "workflowMd": records_mod.render_workflow(t, w),
               "dir": None}
        if self.records_dir:
            try:
                out["dir"] = str(records_mod.write(t, w, self.records_dir))
            except (OSError, ValueError) as e:
                log.warning(json.dumps({"msg": "task record not written", "key": t["key"], "error": repr(e)[:200]}))
        return out

    def _record_soon(self, key, delay=2.0):
        """Rewrite a ticket's Markdown record shortly after it changed (coalesced per ticket)."""
        if not self.records_dir or key in self._record_timers:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def run():
            self._record_timers.pop(key, None)
            try:
                self.task_record(key)
            except Exception as e:  # noqa: BLE001 — a record must never break a ticket write
                log.warning(json.dumps({"msg": "task record failed", "key": key, "error": repr(e)[:200]}))
        self._record_timers[key] = loop.call_later(delay, run)

    def _closed_soon(self, key, teardown=True):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if key in self._closing:
            return
        self._closing.add(key)
        task = loop.create_task(self.on_task_closed(key, teardown))
        task.add_done_callback(lambda _t: self._closing.discard(key))

    # A ticket usually closes because its own session just ran `pipeline_cli verify`/`deployed`, so it is still
    # "working" at that moment: wait for it to go idle (bounded) before asking it to /exit.
    EXIT_WAIT_S = 30.0
    EXIT_TRIES = 20

    async def _exit_when_idle(self, key):
        for i in range(self.EXIT_TRIES + 1):
            t = self.tasks.get(key)
            if t["status"] not in tasks_mod.CLOSED:
                return f"{key.lower()} left running (the ticket reopened)"
            r = self.task_session(key)
            if r["state"] != "ready":
                return None if i == 0 else f"{key.lower()} ended"
            if r["status"] in ("idle", "done"):
                ok, why = await self._nudge_task(key, "/exit")
                return f"{key.lower()} ended (/exit)" if ok else f"{key.lower()} still running: {why}"
            if i < self.EXIT_TRIES:
                await asyncio.sleep(self.EXIT_WAIT_S)
        return f"{key.lower()} is {r['status']}; left running"

    async def on_task_closed(self, key, teardown=True):
        """A ticket became DONE / DENIED / CANCELLED: end its temporary sessions, keep every record.

          1. its Task Room terminals (claude:/repo:/codex:<KEY>) close — the claude: one is only the attach client
          2. its task Claude session (named after the key) is asked to /exit when idle; a working or
             blocked one is left running and reported (never killed)
          3. the worktree's writer is released; the worktree itself is never deleted here
          4. the final task.md / workflow.md are written
        The project coordinator is never touched."""
        # Runs as its own task (_closed_soon), which copied the context of the request that closed the ticket: what
        # it does later is ccd acting on its own, so the Broker record must not credit that request (task-local).
        broker_mod.REQUEST.set(None)
        names, claude = [], None
        if not teardown:
            claude = "left running: closed without Developer Unlock"
        else:
            try:
                names = await self.ptys.close_task(key) if self.ptys is not None else []
            except Exception as e:  # noqa: BLE001
                log.warning(json.dumps({"msg": "closing task terminals failed", "key": key, "error": repr(e)[:200]}))
            claude = await self._exit_when_idle(key)
        if claude and ("still running" in claude or "left running" in claude):
            t = self.tasks.get(key)
            self._event("tasks", "task.pipeline", f"{key} closed, but its Claude session is still running", severity="warn",
                        project=t["project"], ref=key, data={"kind": "pipeline.session_left"})
        try:
            self._pipeline_result(*self.pipeline.release(key, {"ptys": names, "claude": claude}))
        except tasks_mod.TaskError:
            pass
        if self.records_dir:
            try:
                self.task_record(key)
            except Exception as e:  # noqa: BLE001
                log.warning(json.dumps({"msg": "final task record failed", "key": key, "error": repr(e)[:200]}))

    def task_cwd(self, key):
        """(project root, worktree|None) for a Task Room terminal. The worktree counts only when it is a
        known git worktree of that project (from ccd's git poll) or inside the project root."""
        from .pty import PtyError
        if self.tasks is None or not self.tasks.exists(key):
            raise PtyError(404, f"no ticket {key}")
        t = self.tasks.get(key)
        root = registry.root_of(t["project"])
        if not root:
            raise PtyError(404, f"{t['project']} has no registered checkout")
        w = self.pipeline.work(key)
        wt = w.get("worktree")
        if wt and os.path.isdir(wt):
            real = os.path.realpath(wt)
            known = {os.path.realpath(x) for x in (self.git.get("worktrees") or {}).get(t["project"]) or []}
            rroot = os.path.realpath(root)
            if real in known or real == rroot or real.startswith(rroot.rstrip("/") + "/"):
                return root, real
        return root, None

    def _pipeline_result(self, ticket, changes, events):
        """Announce one pipeline step (an agent's or the GitHub poll's): status changes, then its events.
        An owner gate or a block is owner attention; ordinary transitions are info."""
        self._announce(ticket, changes)
        for kind, text, _data in events:
            self._event("tasks", "task.pipeline", f"{ticket['key']} {text}"[:300], project=ticket["project"],
                        ref=ticket["key"], data={"kind": kind},
                        severity="action" if kind in ("pipeline.gate_opened", "pipeline.blocked",
                                                      "pipeline.unreviewed_merge", "pipeline.questions",
                                                      "pipeline.deploy_requested", "pipeline.replan",
                                                      "pipeline.auto_merge_held", "pipeline.auto_merged",
                                                      "pipeline.auto_merge_failed") else "info")
        if events:
            self._record_soon(ticket["key"])
            self._shadow_record(ticket, events)
            self._ledger_record(ticket, events)
            self._audit_system(ticket, events)

    def _shadow_record(self, ticket, events):
        """Autonomy Engine, shadow mode: for each decision in this step (plan accepted or gated, merged by ccd or
        gated, deploy requested), what the agreed target policy would have done. Recorded only; never raises,
        never changes the step. A failure here is a log line."""
        if self.shadow is None:
            return
        try:
            decided = autonomy.observed(events)
            if not decided:
                return
            key, project = ticket["key"], ticket["project"]
            t = self.tasks.get(key)
            w = self.pipeline.work(key)
            ci = next((d.get("ci") for k, _x, d in events if k == "pipeline.ready_to_merge" and isinstance(d, dict)), None)
            tid = self.tasks._id_of(key)
            for action, outcome, extra in decided:
                more = dict(extra)
                if action == "deploy" and self._shadow_deploy_seen(tid):
                    continue    # one deploy decision per deployment: the needs:deploy gate, then the request
                if action == "merge":
                    more.setdefault("ci", ci)
                    pr = self._shadow_pr.get(key)
                    if pr and pr.get("headRefOid") == w["review"]["head"]:   # only the PR ccd read at the reviewed head
                        rollup = pr.get("statusCheckRollup")
                        more.update(files=pr.get("files"), additions=pr.get("additions"),
                                    deletions=pr.get("deletions"), ci=merge_policy.ci_state(rollup),
                                    ci_passed=autonomy.ci_passed(rollup), draft=pr.get("isDraft"),
                                    mergeable=pr.get("mergeable"), base=pr.get("baseRefName"),
                                    cross_repo=pr.get("isCrossRepository"), pr_head=pr.get("headRefOid"),
                                    state=pr.get("state"))
                facts = autonomy.facts_of(t, w, more)
                verdict = autonomy.evaluate(action, self.policy.profile(project), facts)
                self.shadow.record(tid, project, action, outcome, verdict, facts,
                                   self.policy.fingerprint)
            self._shadow_pr.pop(key, None)
        except Exception as e:  # noqa: BLE001 — shadow mode must never affect what ccd does
            log.warning(json.dumps({"msg": "autonomy shadow skipped a decision", "key": ticket.get("key"),
                                    "error": repr(e)[:200]}))

    def _shadow_deploy_seen(self, tid):
        """A deploy decision is already recorded for this ticket since its last deployment."""
        last = self.tasks.db.execute("SELECT MAX(at) FROM ticket_events WHERE ticket_id=? AND kind IN ('pipeline.deployed', 'pipeline.blocked')",
                                     (tid,)).fetchone()[0] or 0
        return self.tasks.db.execute("SELECT 1 FROM autonomy_shadow WHERE ticket_id=? AND action='deploy' AND at > ?",
                                     (tid, last)).fetchone() is not None

    def _workers_start(self):
        """The server registers itself as a worker node (it is ccd's own host). Never stops ccd starting."""
        if self.workers is None:
            return
        try:
            caps = workers_mod.server_caps()
            self.workers.register_server(__version__, caps)
            self._event("security", "worker.server", f"server node registered: {', '.join(caps['tools']) or 'no tools'}",
                        data={"tools": caps["tools"], "repos": caps["repos"]})
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "server worker registration skipped", "error": repr(e)[:200]}))

    def _workers_beat(self):
        if self.workers is None:
            return
        try:
            self.workers.server_heartbeat()
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "server worker heartbeat skipped", "error": repr(e)[:200]}))

    def _need_workers(self):
        if self.workers is None:
            raise ActionError(503, "the task system is not enabled")
        return self.workers

    def _worker_call(self, fn, *a):
        try:
            return fn(*a)
        except workers_mod.WorkerError as e:
            raise ActionError(e.status, e.message) from None
        except sqlite3.DatabaseError as e:         # a refused write (schema CHECK, busy database): a clear 409, not a 500
            log.warning(json.dumps({"msg": "worker change refused by the database", "error": repr(e)[:200]}))
            raise ActionError(409, "the worker record refused that change; reload and try again") from None

    def inbox_state(self):
        """GET /api/inbox: per Needs-You item, its pending Approval, the shadow engine's verdict and precedents for
        open questions. The queue itself is state.needs, unchanged. Read-only; a failure here never breaks it."""
        empty = {"available": False, "items": {}, "orphans": [], "counts": {}}
        if self.inbox is None:
            return empty
        try:
            return dict(inbox_mod.plain(self.inbox.enrich(self.state().get("needs") or [])), available=True)
        except Exception as e:  # noqa: BLE001 — the inbox is an overlay; the queue never depends on it
            log.warning(json.dumps({"msg": "inbox overlay failed", "error": repr(e)[:200]}))
            return dict(empty, error="the Needs You details could not be read")

    def workers_state(self):
        if self.workers is None:
            return {"available": False, "nodes": [], "events": []}
        nodes = self.workers.list()
        out = {"available": True, "nodes": nodes, "events": self.workers.events(), "onlineFor": workers_mod.ONLINE_FOR}
        if not (self.node_shadow_on and self.node_keys is not None):
            return out                                       # with the switch off, exactly the answer from before v12
        out["nodeShadow"] = True
        try:
            keys = self.node_keys.keys()
            for n in nodes:
                k = keys.get(n["id"])
                n["key"] = {"fingerprint": k["fingerprint"], "approved": k["approved"]} if k else None
            out["shadow"] = dict(self.node_keys.summary(), chain=self.node_keys.verify(), errors=self.node_keys.errors)
        except Exception as e:  # noqa: BLE001 — the shadow record is an overlay; the node list never depends on it
            log.warning(json.dumps({"msg": "node shadow summary failed", "error": repr(e)[:200]}))
            out["shadow"] = {"error": "the node shadow record could not be read", "enforced": False}
        return out

    def worker_enrol(self, body, actor):
        w = self._need_workers()
        out = self._worker_call(w.enrol, body.get("id"), body.get("kind"), body.get("capabilities"),
                                body.get("version"), actor)
        if self.node_shadow_on and self.node_keys is not None:
            out.update(self._node_enrol_shadow(out["id"], body.get("publicKey"), actor))
        self._event("security", "worker.enrolled", f"worker node {out['id']} asked to join; waiting for Jay",
                    severity="action", data={"node": out["id"]})
        return out

    def worker_heartbeat(self, node, token, body, signature=None, method="POST", path="/api/workers/heartbeat"):
        """A node's heartbeat. With phase2_node_shadow on, its signature is also checked and recorded; the answer is
        exactly what it would be without the check."""
        w = self._need_workers()
        status = 500
        try:
            out = self._worker_call(w.heartbeat, node, token, body.get("capabilities"), body.get("version"))
            status = 200
            return out
        except ActionError as e:
            status = e.status
            raise
        finally:
            if self.node_shadow_on and self.node_keys is not None:
                try:
                    result = self.node_keys.check(node, method, path, signature, body, w.state(node),
                                                  token_ok=status not in (401,))
                    self.node_keys.observe(node, "heartbeat", status, result)
                except Exception:  # noqa: BLE001 — the shadow check never touches the heartbeat
                    self.node_keys.errors += 1

    def _node_enrol_shadow(self, node, public_key, actor):
        """Record the key a new node sent (Phase 2 shadow). Never refuses the enrolment."""
        try:
            fp, problem = self.node_keys.add(node, public_key, actor) if public_key is not None else (None, "no_key")
            reasons = [problem] if problem else []
            self.node_keys.observe(node, "enrol", 200, {"signed": False, "verified": False, "keyFingerprint": fp,
                                                        "reasons": reasons})
            return {"keyFingerprint": fp} if fp else {}
        except Exception:  # noqa: BLE001
            self.node_keys.errors += 1
            return {}

    def act_worker(self, op, node, actor="jay", developer=False, reason=""):
        """Jay approves or revokes a worker node. Jay AND Developer Unlock: a node will later run agent work."""
        if actor != "jay" or not developer:
            raise ActionError(403, f"Developer Unlock required: {op} a worker node")
        w = self._need_workers()
        out = self._worker_call(w.approve, node, actor) if op == "approve" else \
            self._worker_call(w.revoke, node, actor, reason)
        self._event("security", f"worker.{'approved' if op == 'approve' else 'revoked'}",
                    f"Jay {'approved' if op == 'approve' else 'revoked'} worker node {node}", data={"node": node})
        return out

    # ---------- onboarding groundwork (D-024 proposed) and shadow budgets (D-033) ----------

    def _log_onboarding(self):
        """Startup: say so when the groundwork is on. Off (the default) logs nothing, so ccd looks as it did."""
        if self.onboarding is not None and self.onboarding_on:
            self._event("security", "onboarding.groundwork",
                        "onboarding groundwork is on: records, drafts and reads only; nothing is granted, started or "
                        "enforced", data={"status": "on"})

    def _need_onboarding(self):
        if self.onboarding is None or not self.onboarding_on:
            raise ActionError(404, onboarding_mod.OFF_MESSAGE)
        return self.onboarding

    def _onboarding_call(self, fn, *a):
        try:
            return fn(*a)
        except onboarding_mod.OnboardingError as e:
            raise ActionError(e.status, e.message) from None
        except sqlite3.DatabaseError as e:        # a schema CHECK or trigger refused it: a clear 409, not a 500
            log.warning(json.dumps({"msg": "onboarding change refused by the database", "error": repr(e)[:200]}))
            raise ActionError(409, "the onboarding record refused that change; reload and try again") from None

    def onboarding_state(self):
        return self._onboarding_call(self._need_onboarding().summary)

    def onboarding_agents(self):
        return {"agents": self._onboarding_call(self._need_onboarding().agents)}

    def onboarding_agent(self, agent_id):
        return self._onboarding_call(self._need_onboarding().agent, agent_id)

    def onboarding_drafts(self, state=None):
        return {"drafts": self._onboarding_call(self._need_onboarding().drafts, state)}

    def onboarding_draft(self, draft_id):
        return self._onboarding_call(self._need_onboarding().draft, draft_id)

    def onboarding_events(self, limit=100):
        return {"events": self._onboarding_call(self._need_onboarding().events, None, limit)}

    def onboarding_validate(self, kind, body):
        """Read-only for anyone with ccd's token: what a draft's problems are. Stores nothing."""
        return self._onboarding_call(self._need_onboarding().validate, kind, body)

    def onboarding_budgets(self):
        """D-033 in shadow: which budgets would alert or hold now. Holds nothing."""
        o = self._need_onboarding()
        company = (self.cfg.get("budgets") or {}).get("company") if isinstance(self.cfg.get("budgets"), dict) else None
        return budgets_mod.report(self.tasks.db, time.time(), company, self._profile_budgets(),
                                  self._onboarding_call(o.agent_budgets), meter_at=self.meter_read_at)

    def act_onboarding(self, op, actor="jay", developer=False, **kw):
        """Jay writes an onboarding record. Jay AND Developer Unlock, and only while the groundwork flag is on (404
        otherwise, before anything else is looked at). Nothing written here grants, issues or starts anything."""
        o = self._need_onboarding()
        if actor != "jay" or not developer:
            raise ActionError(403, f"Developer Unlock required: {op} an onboarding record")
        if op == "create":
            return self._onboarding_call(o.create_draft, kw.get("kind"), kw.get("body"), actor)
        if op == "update":
            return self._onboarding_call(o.update_draft, kw.get("id"), kw.get("body"), kw.get("revision"), actor)
        if op == "discard":
            return self._onboarding_call(o.discard_draft, kw.get("id"), actor, kw.get("reason") or "")
        if op == "register":
            out = self._onboarding_call(o.register_agent, kw.get("id"), kw.get("revision"), kw.get("acknowledge"), actor)
            self._event("security", "onboarding.registered",
                        f"Jay registered {out['id']}: a record only, with no credential and nothing started",
                        data={"agent": out["id"]})
            return out
        if op == "retire":
            out = self._onboarding_call(o.retire_agent, kw.get("id"), actor, kw.get("reason") or "")
            self._event("security", "onboarding.retired", f"Jay retired {out['id']}; its ID is never reused",
                        data={"agent": out["id"]})
            return out
        raise ActionError(400, f"unknown onboarding action {op}")

    # ---------- audit trail, actor identity, metering (PR 7) ----------

    # ---------- Capability Broker, shadow (Phase 2 step 3) ----------

    def _broker(self, verb, project=None, target="", approval=None):
        """Record what the Broker would decide for this action. Called just before the action happens; never raises,
        never refuses, never changes the action. Does nothing while phase2_broker_shadow is off."""
        if not self.broker_shadow_on or self.broker is None:
            return
        try:
            req = broker_mod.REQUEST.get()
            if req is None:
                who, dev = broker_mod.system_who(), False
            else:
                tok = req.get("token")
                hit = self.actor_tokens.lookup(tok) if tok and self.actor_tokens else None
                dev = bool(req.get("developer"))
                who = identity_mod.resolve(req.get("asserted"), dev, hit, project)
            if project is None:
                profile = None
            elif registry.paused(project):
                profile = "paused"
            else:
                profile = "ok" if self.policy.profile(project) is not None else "missing"
            facts = dict(approval or {}, developer=dev)
            self.broker.observe(verb, project, target, who, broker_mod.check(verb, who, project, profile, facts))
        except Exception:  # noqa: BLE001 — the shadow record must never touch the action
            if self.broker is not None:
                self.broker.errors += 1

    def _broker_ticket(self, verb, key, env):
        """_broker for a pipeline deploy step on ticket `key`; the approval term reads the ticket's deploy approval."""
        if not self.broker_shadow_on:
            return
        try:
            project = self.tasks.get(key)["project"] if self.tasks.exists(key) else None
            approved = bool(((self.pipeline.work(key) or {}).get("deploy") or {}).get("approvedAt")) if project else False
        except Exception:  # noqa: BLE001
            project, approved = None, False
        self._broker(verb, project, f"{str(key)[:20]} env={str(env)[:20]}", {"deployApproved": approved})

    def _broker_engine_merge(self, project, ticket, work, pr):
        """The Autonomy Engine's merge verdict for the PR ccd is about to merge, for the Broker's approval term. Read
        only; None when it cannot be worked out."""
        if not self.broker_shadow_on:
            return None
        try:
            rollup = pr.get("statusCheckRollup")
            facts = autonomy.facts_of(ticket, work, {
                "files": pr.get("files"), "additions": pr.get("additions"), "deletions": pr.get("deletions"),
                "ci": merge_policy.ci_state(rollup), "ci_passed": autonomy.ci_passed(rollup), "draft": pr.get("isDraft"),
                "mergeable": pr.get("mergeable"), "base": pr.get("baseRefName"),
                "cross_repo": pr.get("isCrossRepository"), "pr_head": pr.get("headRefOid"), "state": pr.get("state")})
            return autonomy.evaluate("merge", self.policy.profile(project), facts).get("outcome")
        except Exception:  # noqa: BLE001
            return None

    def broker_state(self, full=False, limit=50):
        """GET /api/broker: what the Broker would have decided. Read-only."""
        if self.broker is None:
            return {"available": False, "brokerShadow": self.broker_shadow_on}
        try:
            return {"available": True, "brokerShadow": self.broker_shadow_on, "summary": self.broker.summary(),
                    "chain": self.broker.verify(full=full), "recent": self.broker.recent(limit),
                    "errors": self.broker.errors, "terms": list(broker_mod.TERMS), "enforced": False}
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "broker shadow read failed", "error": repr(e)[:200]}))
            return {"available": True, "brokerShadow": self.broker_shadow_on, "error": "the Broker record could not "
                    "be read", "errors": self.broker.errors, "enforced": False}

    def audit_write(self, method, path, status, claimed, body, developer, actor_token, asserted=None):
        """AuditTrail (api.py) after every write that passed Guard. `developer`: whether the request's Developer
        Unlock session was live when it arrived (so a lock is still credited to it). `asserted`: the raw X-CCD-Actor
        header (None when missing), for the Phase 2 shadow record. Records; never raises, never refuses."""
        if self.audit is None:
            return
        try:
            hit = self.actor_tokens.lookup(actor_token) if actor_token and self.actor_tokens else None
            asserted = asserted or None
            who = identity_mod.identify(claimed, bool(developer), hit["actor"] if hit else None,
                                        header_missing=asserted is None)
            shadow = None
            if self.identity_shadow_on:
                try:                 # a shadow-record failure must never cost the audit row
                    shadow = identity_mod.resolve(asserted, bool(developer), hit, self._write_project(path, body))
                except Exception:  # noqa: BLE001
                    self.audit.identity_errors += 1
            self.audit.record(actor=who["actor"], verified=who["verified"], via=who["via"],
                              token_actor=who["tokenActor"], method=method, path=path, status=status, body=body,
                              summary="actor token names a different actor" if who["mismatch"] else
                              audit_mod.SERVICE_NO_HEADER if who["via"] == "token" and not who["verified"] else "",
                              profile_hash=getattr(self.policy, "fingerprint", None), identity=shadow)
        except Exception as e:  # noqa: BLE001 — the audit trail is a record; it must never break a write
            log.warning(json.dumps({"msg": "audit write skipped", "path": str(path)[:100], "error": repr(e)[:200]}))

    def _audit_system(self, ticket, events):
        """What ccd itself did to a ticket in one pipeline step (gates opened, auto-merges, blocks), as system:ccd."""
        if self.audit is None:
            return
        try:
            for kind, text, _data in events:
                self.audit.record(actor="system:ccd", verified=True, via="system", method="EVENT", path=str(kind),
                                  status=0, project=ticket.get("project"), ref=ticket.get("key"), summary=text,
                                  profile_hash=getattr(self.policy, "fingerprint", None))
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "audit (system) skipped", "key": ticket.get("key"), "error": repr(e)[:200]}))

    def audit_state(self, actor=None, verified=None, limit=100, full=False):
        if self.audit is None:
            return {"available": False, "events": [], "summary": {}, "chain": {}}
        return {"available": True, "events": self.audit.list(actor, verified, limit), "summary": self.audit.summary(),
                "chain": self.audit.verify(full=full), "identity": self.audit.identity_summary(),
                "identityChain": self.audit.verify_identity(full=full),
                "identityErrors": self.audit.identity_errors, "identityShadow": self.identity_shadow_on}

    def _write_project(self, path, body):
        """The project a write touches, for the shadow record: the project of the ticket the path names (any case, as
        ccd accepts it), else the body's `project` when the path names no ticket. None when neither names one. A body
        `project` never overrides the ticket actually written."""
        m = TICKET_PATH_RE.search(path or "")
        if m:
            if self.tasks is None:
                return None
            key = m.group(1).upper()
            row = self.tasks.db.execute("SELECT project FROM tickets WHERE key=?", (key,)).fetchone()
            if row is None:          # a key minted under a retired prefix (GM-014 → its project)
                row = self.tasks.db.execute("SELECT project FROM task_project_aliases WHERE prefix=?",
                                            (key.rsplit("-", 1)[0],)).fetchone()
            return row[0] if row else None
        if isinstance(body, dict) and isinstance(body.get("project"), str) \
                and identity_mod.PROJECT_RE.fullmatch(body["project"]):
            return body["project"]
        return None

    def actors_state(self):
        if self.actor_tokens is None:
            return {"available": False, "tokens": []}
        return {"available": True, "tokens": self.actor_tokens.list(), "header": "X-CCD-Actor-Token"}

    def act_actor_token(self, op, body, actor="jay", developer=False):
        """Jay issues or revokes an agent's actor token. Jay AND Developer Unlock: a token vouches for an agent."""
        if actor != "jay" or not developer:
            raise ActionError(403, f"Developer Unlock required: {op} an actor token")
        if self.actor_tokens is None:
            raise ActionError(503, "the task system is not enabled")
        try:
            if op == "issue":
                out = self.actor_tokens.issue(body.get("actor"), actor, body.get("ttlDays"), body.get("note") or "",
                                              project=body.get("project"))
                self._event("security", "actor_token.issued", f"Jay issued a {out['kind']} token for {out['actor']} "
                            f"({out['fingerprint']})", data={"actor": out["actor"], "id": out["id"],
                                                             "kind": out["kind"], "project": out["project"]})
                return out
            tid = body.get("id")
            if not isinstance(tid, int) or isinstance(tid, bool) or not -2 ** 62 < tid < 2 ** 62:
                raise ActionError(400, "id must be a number")
            out = self.actor_tokens.revoke(tid, actor)
            self._event("security", "actor_token.revoked", f"Jay revoked actor token {tid} ({out['actor']})",
                        data={"id": tid})
            return out
        except identity_mod.IdentityError as e:
            raise ActionError(e.status, e.message) from None

    def _meter_attribute(self, cwd, branch):
        """(project, ticket key) for a transcript's working directory and branch. A ticket's own worktree wins;
        then a ticket key in the branch or directory name that exists in that project."""
        if not cwd and not branch:
            return None, None
        project = model._pane_project({"cwd": cwd or ""}, self.cfg["projects"], (self.git or {}).get("worktrees")) \
            if cwd else None
        db = self.tasks.db
        if cwd:
            real = os.path.realpath(cwd)
            for r, proj, key in self._meter_worktrees():
                if real == r or real.startswith(r.rstrip("/") + "/"):
                    return proj, key
        for text in (branch or "", os.path.basename(cwd or "")):
            for m in meter_mod.KEY_IN_TEXT.finditer(text):
                row = db.execute("SELECT key, project FROM tickets WHERE key = ? COLLATE NOCASE", (m.group(1),)).fetchone()
                if row and (project is None or row[1] == project):
                    return row[1], row[0]
        return project, None

    def _meter_worktrees(self, ttl=60):
        """Ticket worktrees as (realpath, project, key), longest first, resolved at most once a minute."""
        now = time.monotonic()
        cached = getattr(self, "_mwt", None)
        if cached and now - cached[0] < ttl:
            return cached[1]
        rows = [(os.path.realpath(wt), proj, key) for key, proj, wt in self.tasks.db.execute(
            "SELECT t.key, t.project, w.worktree FROM ticket_work w JOIN tickets t ON t.id = w.ticket_id "
            "WHERE w.worktree IS NOT NULL")]
        rows.sort(key=lambda x: -len(x[0]))
        self._mwt = (now, rows)
        return rows

    def _meter_report(self, key, op, actor, body):
        """A work step's own `usage` (optional). Recorded as reported; never fails the step."""
        if self.meter is None:
            return
        try:
            u = body.get("usage")
            t = self.tasks.get(key) if self.tasks.exists(key) else {}
            ref = u.get("ref") if isinstance(u, dict) and isinstance(u.get("ref"), str) else \
                f"{key}:{op}:{body.get('session') or ''}:{time.time()}"
            self.meter.report(ref, t.get("project"), t.get("key"), actor, u)
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "usage report skipped", "key": str(key)[:40], "error": repr(e)[:200]}))

    METER_EVERY = 300

    async def meter_loop(self):
        """Read new usage from the agents' session logs every few minutes. Files are read off the event loop;
        rows are written on it (tasks.db is one connection)."""
        await asyncio.sleep(60)
        while not self._stopping and self.meter is not None:
            try:
                plan = self.meter.plan()
                results = await asyncio.to_thread(self.meter.read, plan)
                n = self.meter.store(results)
                self.meter_read_at = time.time()          # budgets treat spend as Unknown when this is old (D-024 cl. 17)
                if n:
                    log.info(json.dumps({"msg": "usage metered", "rows": n}))
            except Exception as e:  # noqa: BLE001 — metering is a record; it never affects anything else
                log.warning(json.dumps({"msg": "usage scan failed", "error": repr(e)[:200]}))
            await asyncio.sleep(self.METER_EVERY)

    def _profile_budgets(self):
        """project key → its profile's [target.budget], for valid profiles that set one."""
        budgets = {}
        for key, rec in (getattr(self.policy, "profiles", None) or {}).items():
            b = ((rec.get("profile") or {}).get("target") or {}).get("budget") if rec.get("valid", True) else None
            if isinstance(b, dict) and b:
                budgets[key] = b
        return budgets

    def usage_state(self, days=14):
        if self.meter is None:
            return {"available": False}
        budgets = self._profile_budgets()
        return dict(self.meter.summary(days, budgets), available=True,
                    note="Estimate at Anthropic list prices; subscription plans are not billed per token. "
                         "Codex usage is counted in tokens only. Budgets are shown, not enforced.")

    def _ledger_start(self):
        """At start: Jay's policy decisions become Decision records; every open gate gets its pending Approval."""
        if self.ledger is None:
            return
        try:
            seeded = self.ledger.seed_policy(self.policy)
            rows = self.tasks.db.execute(
                "SELECT t.id, t.project, t.key, t.status, t.archived FROM tickets t WHERE t.id IN ("
                "SELECT ticket_id FROM ticket_work WHERE gate IS NOT NULL UNION "
                "SELECT ticket_id FROM approvals WHERE state IN ('pending', 'approved'))").fetchall()
            backfilled = self.ledger.reconcile(
                [(tid, project, key, self.pipeline.work(key), bool(archived) or status in pipeline_mod.CLOSED_STATUSES)
                 for tid, project, key, status, archived in rows], self.policy.fingerprint)
            if seeded or backfilled:
                self._event("tasks", "ledger.start", f"recorded {seeded} policy decision(s) and {backfilled} open gate(s)",
                            data={"decisions": seeded, "approvals": backfilled})
        except Exception as e:  # noqa: BLE001 — the ledger is a record; it must never stop ccd starting
            log.warning(json.dumps({"msg": "ledger start skipped", "error": repr(e)[:200]}))

    def _ledger_record(self, ticket, events):
        """Mirror one pipeline step into Approval and Decision records. Never raises, never changes the step."""
        if self.ledger is None:
            return
        try:
            key = ticket["key"]
            tid = self.tasks._id_of(key)
            if not self.ledger.needs_look(tid, events):
                return
            status, archived = self.tasks.db.execute("SELECT status, archived FROM tickets WHERE id=?", (tid,)).fetchone()
            self.ledger.observe(tid, ticket["project"], key, self.pipeline.work(key), events, self.policy.fingerprint,
                                closed=bool(archived) or status in pipeline_mod.CLOSED_STATUSES)
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "ledger skipped a step", "key": ticket.get("key"), "error": repr(e)[:200]}))

    def ledger_state(self, project=None, state=None, limit=100):
        """GET /api/decisions: Decision and Approval records. Read-only."""
        if self.ledger is None:
            return {"available": False, "decisions": [], "approvals": [], "counts": {}}
        return {"available": True, "decisions": self.ledger.decisions(project, limit),
                "approvals": self.ledger.approvals(state, limit, project), "counts": self.ledger.counts(project)}

    def autonomy_state(self):
        """GET /api/autonomy: the shadow record's summary. Read-only."""
        if self.shadow is None:
            return {"mode": "shadow", "engine": autonomy.ENGINE_VERSION, "total": 0, "agree": 0, "disagree": 0,
                    "counts": {}, "missing": {}, "disagreements": [], "available": False}
        return dict(self.shadow.summary(), available=True, policy=self.policy.fingerprint)

    def task_comment(self, key, body, actor="jay"):
        ticket = self._wrap(self._need_tasks().comment, key, body, actor)
        self._task_event("task.commented", ticket, "note added", {"count": len(ticket["comments"])})
        return self._with_work([ticket])[0]

    def task_relate(self, key, kind, target, remove=False, actor="jay"):
        ticket, changed = self._wrap(self._need_tasks().relate, key, kind, target, actor, remove)
        if changed:
            other = self._wrap(self._need_tasks().get, target)
            for t in (ticket, other):
                self._task_event("task.updated", t, "relations changed", {"kind": "relations"})
        return self._with_work([ticket])[0]

    def task_link(self, key, body, actor="jay"):
        ticket, changed = self._wrap(self._need_tasks().link, key, str(body.get("provider") or "github"),
                                     str(body.get("kind") or "pr"), body.get("ref"), body.get("url"),
                                     body.get("title"), actor, None, bool(body.get("remove")))
        if changed:
            self._task_event("task.updated", ticket, f"{'unlinked' if body.get('remove') else 'linked'} "
                             f"{body.get('kind') or 'pr'} {body.get('ref')}", {"kind": "links"})
        return self._with_work([ticket])[0]

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

        Jay wins: if the last status change was a manual edit (no trigger recorded)
        moving the ticket away from `to`, automation does not move it back. A pipeline
        step (rework, review, ...) always records a trigger, so it is not an override.
        Actor system:automation, trigger recorded with the change.
        """
        t = self.tasks.get(key)
        if t["status"] not in frm:
            return t
        last = self.tasks.last_status_event(key)
        if last and not last["actor"].startswith("system:") and last["trigger"] is None and last["from"] == to:
            return t
        ticket, changes = self.tasks.update(key, {"status": to}, "system:automation", trigger=trigger)
        self._announce(ticket, changes)
        return ticket

    def _ticket_automation(self):
        """GitHub → tickets, only on deterministic triggers.

          open PR whose title or branch LEADS with a key (same project) → link it, set branch
          ...ticket READY_TO_IMPLEMENT or IN_PROGRESS                      → IN_REVIEW
          linked PR approved, no failing or pending check ("–": no checks at all, said as such), not draft,
          ticket IN_REVIEW                                                 → READY_TO_MERGE
          linked PR no longer ready, ticket READY_TO_MERGE                 → IN_REVIEW
          linked PR merged (found by link, not title), IN_REVIEW/READY_TO_MERGE → VERIFYING

        A merge moves a ticket once; a reopened ticket waits for a new merge. GitHub keeps listing a merged PR,
        so the move is skipped when automation already made it for that PR (a status event with trigger
        "PR #n merged"), or when the pipeline already recorded that merge. Known gap: a by-hand move to
        VERIFYING leaves no automation event, so an old merge can still fire after a later reopen.

        Once per fresh GitHub poll per project. Never closes a ticket
        (VERIFYING → DONE is a verifier's or Jay's call) and never undoes a
        status Jay set by hand.
        """
        if self.tasks is None:
            return
        prefixes = self.tasks.key_prefixes()  # a retired prefix still owns its old keys
        for p in self.cfg["projects"]:
            g = self.gh.get(p["key"]) or {}
            if g.get("error") or not g.get("data") or self._auto_seen.get(p["key"]) == g.get("asOf"):
                continue
            self._auto_seen[p["key"]] = g.get("asOf")
            data = g["data"]

            def mine(k):
                return prefixes.get(k.rsplit("-", 1)[0]) == p["key"] and self.tasks.exists(k)

            for pr in data.get("prs") if isinstance(data.get("prs"), list) else []:
                try:
                    n = pr["number"]
                    ref = f"{p['repo']}#{n}"
                    keys = [k for k in self.tasks.pr_keys(pr.get("title", ""), pr.get("headRefName", "")) if mine(k)]
                    keys += [k for k in self.tasks.keys_linked("github", "pr", ref) if k not in keys]
                    ci = model.ci_mark(pr.get("statusCheckRollup"))
                    ready = pr.get("reviewDecision") == "APPROVED" and ci in ("✓", "–") and not pr.get("isDraft")
                    # What the pipeline needs to tie a recorded review to this PR's current head.
                    # "–" (no checks configured) counts as ready, as for GitHub approvals above, but the
                    # pipeline says "no CI checks" for it, never "green" (ciNone).
                    pr_state = {"ref": ref, "head": pr.get("headRefOid") or "", "ciGreen": ci in ("✓", "–"),
                                "ciNone": ci == "–", "draft": bool(pr.get("isDraft"))}
                    for k in keys:
                        if not self.tasks.has_link(k, "github", "pr", ref):
                            t, _ = self.tasks.link(k, "github", "pr", ref, github.pr_ref_url(ref), pr.get("title"),
                                                   "system:automation", trigger=f"PR #{n} title or branch leads with {k}")
                            self._task_event("task.updated", t, f"linked PR #{n}", {"kind": "links"})
                        t = self.tasks.get(k)
                        if not t["branch"] and pr.get("headRefName"):
                            t, ch = self.tasks.update(k, {"branch": pr["headRefName"]}, "system:automation",
                                                      trigger=f"PR #{n} head branch")
                            self._announce(t, ch)
                        # A pipeline ticket reaches review only through `start` (branch, worktree, lane):
                        # a PR opened before start waits; the next poll after start moves it.
                        frm = ("IN_PROGRESS",) if self.pipeline.participating(k) else ("READY_TO_IMPLEMENT", "IN_PROGRESS")
                        if not self.pipeline.participating(k):
                            self._auto(k, frm, "IN_REVIEW", f"PR #{n} is open")
                        elif self.pipeline.new_head(k, pr_state):
                            # After a rework the ticket returns to review only on a PR or head that neither the
                            # review nor the rework (its recorded open PRs) has seen.
                            sha = pr_state["head"][:7]
                            why = (f"PR #{n} new head {sha} after rework" if self.pipeline.rework_prs(k) is not None
                                   else f"PR #{n} new head {sha}" if self.pipeline.review_head(k)
                                   else f"PR #{n} is open")
                            self._auto(k, frm, "IN_REVIEW", why)
                        if self.pipeline.participating(k):
                            # A pipeline ticket: only its recorded review, tied to this PR's head, decides.
                            self._pipeline_result(*self.pipeline.sync_pr(k, pr_state))
                        elif ready:
                            self._auto(k, ("IN_REVIEW",), "READY_TO_MERGE",
                                       f"PR #{n} approved, {'no CI checks' if ci == '–' else 'checks green'}, not draft")
                        else:
                            self._auto(k, ("READY_TO_MERGE",), "IN_REVIEW",
                                       f"PR #{n} no longer approved with green checks")
                except Exception as e:  # noqa: BLE001 — one odd PR must not fail the snapshot
                    log.warning(json.dumps({"msg": "ticket automation skipped a PR", "error": repr(e)[:200]}))
            for m in data.get("merged") if isinstance(data.get("merged"), list) else []:
                try:
                    ref = f"{p['repo']}#{m['number']}"
                    why = f"PR #{m['number']} merged"
                    for k in self.tasks.keys_linked("github", "pr", ref):
                        # A merge moves a ticket once. GitHub keeps listing a merged PR for a while, so after a
                        # reopen or rework the old merge must not send the ticket on to VERIFYING again.
                        if self.tasks.moved_by(k, "VERIFYING", why) or (
                                self.pipeline.participating(k) and self.pipeline.merged_pr(k) == ref):
                            continue
                        self._auto(k, ("IN_REVIEW", "READY_TO_MERGE"), "VERIFYING", why)
                        if self.pipeline.participating(k):
                            self._pipeline_result(*self.pipeline.merged(k, ref, ((m.get("mergeCommit") or {}).get("oid"))))
                except Exception as e:  # noqa: BLE001
                    log.warning(json.dumps({"msg": "ticket automation skipped a merge", "error": repr(e)[:200]}))

    # ---------- auto-merge (CC-025, docs/adr/0007-auto-merge-policy.md) ----------

    AUTO_MERGE_WAIT_LIMIT = 30 * 60   # seconds a PR may stay pending (CI running, mergeability unknown) before a gate

    AUTO_MERGE_FIELDS = ("state,isDraft,mergeable,baseRefName,headRefOid,isCrossRepository,files,additions,deletions,"
                         "statusCheckRollup")

    def _auto_merge_projects(self):
        """Registry projects whose merge policy is low-risk AND that have an allowlist: the only ones ccd merges for."""
        return [k for k in registry.PROJECTS
                if pipeline_mod.policy({"project": k}, k)["merge"] == "low-risk" and merge_policy.ALLOW.get(k)]

    def _log_merge_policy(self):
        """Startup: whether ccd may merge anything, as a security event (the audit trail of the first GitHub write)."""
        self._event("security", "merge.policy", self._merge_policy_text(), data={"status": self._merge_policy_state()})

    def _log_policy(self):
        """Startup: which policy files ccd read (their combined SHA-256) and whether any is broken or drifts."""
        n = len(self.policy.problems())
        self._event("security", "policy.loaded",
                    f"policy {self.policy.fingerprint[:12]}: {len(self.policy.profiles)} project profiles, "
                    f"{len(self.policy.decisions)} decisions" + (f", {n} problem(s)" if n else ""),
                    data={"status": "problems" if n else "ok", "count": n})

    def _merge_policy_state(self):
        return "enabled" if self.auto_merge_on and self._auto_merge_projects() else "disabled"

    def _merge_policy_text(self):
        projects = ", ".join(self._auto_merge_projects()) or "none"
        stopped = " (stop file present)" if self._auto_merge_stopped() else ""
        return (f"auto-merge {'ON' if self.auto_merge_on else 'OFF'} (config auto_merge); "
                f"low-risk projects in the registry: {projects}{stopped}")

    def _auto_merge_stopped(self):
        """The kill switch: the stop file exists. Anything but "does not exist" counts as stopped."""
        try:
            return Path(self.auto_merge_stop).exists()
        except OSError:
            return True

    def _gh_json(self, args):
        code, out, err = self.gh_cli(args)
        if code != 0:
            raise OSError((err.strip().splitlines() or ["gh failed"])[-1][:160])
        return json.loads(out)

    async def _auto_merge(self):
        """Merge the reviewed PRs of low-risk projects that the classifier accepts. Runs after _ticket_automation.

        Needs BOTH switches (config `auto_merge` true, registry merge "low-risk") and no stop file. For each
        READY_TO_MERGE ticket with no gate: a fresh `gh pr view`, merge_policy.classify, then either the merge
        (`gh pr merge N --repo R --merge --match-head-commit <reviewed head>`: GitHub refuses it if the head moved) or
        a merge gate in Needs Jay with the reason. gh runs in a worker thread, so the event loop never waits on it.
        A hold or a failure is final for that head (Pipeline.merge_candidates): never retried, never --admin.
        """
        if self.tasks is None or not self.auto_merge_on or self._am_busy:
            return
        self._am_busy = True
        try:
            todo = [(p, self.pipeline.merge_candidates(p)) for p in self._auto_merge_projects()]
            live = {k for _, keys in todo for k in keys}
            for key in [k for k in self._am_waiting if k not in live]:
                del self._am_waiting[key]    # left READY_TO_MERGE (or was decided): a return starts a new clock
            for key in [k for k in self._shadow_pr if k not in live]:
                del self._shadow_pr[key]
            for project, keys in todo:
                for key in keys:
                    if self._auto_merge_stopped() or self._stopping:
                        return
                    try:
                        await self._auto_merge_one(project, key)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001 — one ticket must not stop the others or the derive
                        log.warning(json.dumps({"msg": "auto-merge skipped a ticket", "key": key, "error": repr(e)[:200]}))
        finally:
            self._am_busy = False

    async def _auto_merge_one(self, project, key):
        if self._am_next.get(key, 0) > time.monotonic():
            return
        repo = registry.github_of(project)
        t = self.tasks.get(key)
        w = self.pipeline.work(key)
        rv = w["review"]
        head = rv["head"]
        open_prs = [p["ref"] for p in self._open_prs(t)]
        pr_ref = rv["pr"] if rv.get("pr") and rv["pr"].rpartition("#")[0] == repo else (open_prs[0] if len(open_prs) == 1 else None)
        number = (pr_ref or "").rpartition("#")[2]
        if not number.isdigit():
            self._auto_merge_hold(t, head, "no single open PR to merge was found for this ticket")
            return
        try:
            pr = await asyncio.to_thread(self._gh_json, ["gh", "pr", "view", number, "--repo", repo,
                                                         "--json", self.AUTO_MERGE_FIELDS])
        except (OSError, ValueError) as e:   # gh or GitHub is down: look again in a few minutes, change nothing
            self._am_next[key] = time.monotonic() + 300
            self._event("tasks", "task.pipeline", f"{key} auto-merge could not read PR #{number}: {e}"[:300], severity="warn",
                        project=project, ref=key, data={"kind": "pipeline.auto_merge_unreadable"})
            return
        if not isinstance(pr, dict) or pr.get("state") == "MERGED":
            return    # merged already (by Jay, or by us a moment ago): the GitHub poll moves the ticket
        if pr.get("headRefOid") != head:   # a newer head: the GitHub poll sends the ticket back to review; nothing to hold
            self._am_next[key] = time.monotonic() + 60
            return
        self._shadow_pr[key] = pr    # shadow mode only: the engine reads the changed files of the reviewed head from it
        d = merge_policy.classify(project, t, w, pr, pr_ref, open_prs, pipeline_mod.policy(t, project)["merge"])
        if d.wait:
            stamp = self._review_stamp(w)
            since = self._am_waiting.setdefault(key, (stamp, time.monotonic()))
            if since[0] != stamp:
                since = self._am_waiting[key] = (stamp, time.monotonic())
            if time.monotonic() - since[1] > self.AUTO_MERGE_WAIT_LIMIT:
                self._am_waiting.pop(key, None)
                self._auto_merge_hold(t, head, f"{'; '.join(d.reasons[:2])} for over "
                                               f"{self.AUTO_MERGE_WAIT_LIMIT // 60} minutes")
                return
            self._am_next[key] = time.monotonic() + 60
            return
        self._am_waiting.pop(key, None)
        if not d.ok:
            self._auto_merge_hold(t, head, "; ".join(d.reasons[:3]))
            return
        # Everything above awaited: re-read the ticket, re-check it, then the kill switch, then merge, with no await
        # between. A label or flag added while `gh pr view` ran (a `ui` label, needs:jay) holds the merge here.
        t2 = self.tasks.get(key)
        w2 = self.pipeline.work(key)
        if t2["status"] != "READY_TO_MERGE" or w2["gate"] or w2["review"]["head"] != head \
                or w2["review"]["verdict"] != "APPROVE":
            return
        late = merge_policy.ticket_reasons(t2, w2)
        if late:
            self._auto_merge_hold(t2, head, "; ".join(late[:3]))
            return
        if self._auto_merge_stopped():
            return
        self._broker("pr.merge", project, f"{pr_ref} @ {head[:12]} ({key})",
                     {"engine": self._broker_engine_merge(project, t2, w2, pr)})
        code, out, err = await asyncio.to_thread(self.gh_cli, ["gh", "pr", "merge", number, "--repo", repo, "--merge",
                                                              "--match-head-commit", head])
        if code != 0:
            why = (err.strip().splitlines() or ["gh pr merge failed"])[-1][:200]
            self._auto_merge_hold(t, head, f"gh could not merge it: {why}", failed=True)
            return
        self._event("security", "merge.auto", f"ccd merged {pr_ref} for {key} at {head[:7]} ({'no CI checks' if d.ci == 'none' else 'CI green'})",
                    project=project, ref=key, data={"number": int(number), "ci": d.ci})
        self._pipeline_result(*self.pipeline.auto_merged(key, head, pr_ref, d.ci))

    @staticmethod
    def _review_stamp(w):
        """What the pending clock is for: the reviewed head, its PR and when the reviewer was recorded. A new
        review (even at the same head) or a new head starts a new clock."""
        rv = w["review"]
        return (rv.get("head"), rv.get("pr"), ((w.get("roles") or {}).get("reviewer") or {}).get("at"))

    def _auto_merge_hold(self, ticket, head, reason, failed=False):
        """Open the merge gate with the reason (once per head) and tell the owner queue."""
        ticket, changes, events = self.pipeline.hold_merge(ticket["key"], head, reason, failed)
        if events:
            self._event("security", "merge.auto", f"ccd {'could not merge' if failed else 'held'} {ticket['key']}: {reason}"[:300],
                        project=ticket["project"], ref=ticket["key"], data={"reason": reason[:200]})
        self._pipeline_result(ticket, changes, events)

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
            gates = self.pipeline.needs()
            gated = {g["ref"] for g in gates}
            # A pipeline gate is the one item for its ticket; a flag on the same ticket would repeat it.
            ticket_needs = gates + [n for n in self.tasks.needs() if n["ref"] not in gated]
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
            "gates": self.pipeline.gate_counts() if self.pipeline is not None else {"open": 0, "last": 0},
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
        # ccd's own credentials have no recognisable shape; redact their exact values.
        for secret in getattr(self, "secret_values", ()) or ():
            if secret and secret in text:
                n += text.count(secret)
                text = text.replace(secret, "[redacted]")
        return {"agentId": agent["pane_id"], "name": agent.get("agent_name") or None, "lines": lines,
                "text": text, "redactions": n, "truncated": got["truncated"]}

    # ---------- actions (the whole list; nothing else exists) ----------

    def _throttle(self, key, seconds=1.0):
        now = _now()
        if now - self._last_action.get(key, 0) < seconds:
            raise ActionError(429, "too many requests for this target; wait a second")
        self._last_action[key] = now

    async def adopt_coordinator(self, project, session_id):
        """Bind an EXISTING Claude at the project root as its coordinator (Workspace → Adopt).

        Nothing is started, resumed, renamed or typed into; only the binding file changes."""
        proj = self._project(project)
        if not proj:
            raise ActionError(404, "unknown project")
        if not self.herdr_state["ok"]:
            raise ActionError(503, "herdr unreachable")
        self._throttle(f"adopt:{project}", 2.0)
        await self.resync("action")
        try:
            r = coordid.adopt(project, coordinators.root_of(proj), sources.agent_panes(self.panes), session_id)
        except ValueError as e:
            raise ActionError(409, str(e))
        self._event("action", "action.adopt", f"{coordinators.canonical(proj)} coordinator adopted",
                    project=project, agent_id=r["paneId"])
        await self.resync("action")
        return {"ok": True, "coordinator": coordinators.public_resolution(r)}

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
        self._broker("pane.input", agent.get("project"), f"answer -> pane {pid}")
        try:
            await self.herdr.send_answer(pid, text)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            self._event("action", "action.failed", f"answer to {pid} failed", severity="warn", agent_id=pid,
                        data={"kind": "answer", "error": str(e)[:160]})
            raise ActionError(502, f"herdr refused: {e}")
        return {"ok": True, "agentId": pid}

    PROMPT_RE = re.compile(r"^[^\x00-\x08\x0b-\x1f\x7f]{1,8000}$")
    KEYS = {"esc": "esc", "enter": "Enter"}

    async def act_prompt(self, ident, text):
        """Send Jay's message to an idle Claude pane (herdr agent.prompt). Developer-only at the API.
        herdr refuses a blocked agent (answer it instead) and a working one would interleave, so
        both are refused here. The text is not stored, only its length."""
        if not isinstance(text, str) or not self.PROMPT_RE.match(text) or not text.strip():
            raise ActionError(400, "message must be 1–8000 printable characters")
        self._throttle(f"prompt:{ident}")
        agent = await self._fresh_agent(ident)
        if agent["status"] == "blocked":
            raise ActionError(409, "the agent is waiting on a question; answer it instead")
        if agent["status"] == "working":
            raise ActionError(409, "the agent is working; wait until it is idle, or interrupt it first")
        pid = agent["pane_id"]
        self._event("action", "action.prompt", f"message sent to {agent.get('agent_name') or pid}",
                    project=agent.get("project"), agent_id=pid, data={"count": len(text)})
        self._broker("pane.input", agent.get("project"), f"prompt -> pane {pid}")
        try:
            await self.herdr.prompt(pid, text)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            raise ActionError(502, f"herdr refused: {e}")
        return {"ok": True, "agentId": pid}

    async def act_key(self, ident, key):
        """One whitelisted key into a Claude pane: esc (interrupt) or enter."""
        k = self.KEYS.get(str(key or "").lower())
        if not k:
            raise ActionError(400, "key must be esc or enter")
        self._throttle(f"key:{ident}", 0.3)
        agent = await self._fresh_agent(ident)
        pid = agent["pane_id"]
        self._event("action", "action.key", f"{k} sent to {agent.get('agent_name') or pid}",
                    project=agent.get("project"), agent_id=pid, data={"key": k})
        self._broker("pane.input", agent.get("project"), f"key {k} -> pane {pid}")
        try:
            await self.herdr.call("pane.send_keys", {"pane_id": pid, "keys": [k]})
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
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

    def task_check_text(self, project):
        """The task-check message for `project`, with its open tickets (and how many there are)."""
        ts = self._need_tasks()
        open_ = sorted((t for t in ts.list(project=project) if t["status"] not in tasks_mod.CLOSED),
                       key=lambda t: t["number"])
        lines, used = [], 0
        for t in open_:
            title = CONTROL_RE.sub(" ", str(t["title"])).strip()[:100]
            line = f"- {t['key']} [{t['status']}] {title}"
            if used + len(line) > TASK_CHECK_LIST_MAX:
                lines.append(f"- … {len(open_) - len(lines)} more: python -m ccd.pipeline_cli tasks {project}")
                break
            lines.append(line)
            used += len(line) + 1
        return TASK_CHECK_TEMPLATE.format(project=project, n=len(open_), tasks="\n".join(lines) or "- (none)"), len(open_)

    def _projects(self):
        """Every project Jay works in: the polled ones plus ticket-only ones (config task_projects, e.g. commandcenter)."""
        return config_mod.task_projects(self.cfg)

    def _project(self, key):
        return next((p for p in self._projects() if p["key"] == key), None)

    @staticmethod
    def _not_paused(project, what="work"):
        why = registry.paused(project)
        if why:
            raise ActionError(409, f"{project} is paused ({why}); no {what} until Jay resumes it")

    async def _to_coordinator(self, project, what, text, data):
        """One fixed message from Jay to the project's idle coordinator Claude (task check, night shift)."""
        proj = self._project(project)
        if proj is None:
            raise ActionError(404, "unknown project")
        self._throttle(f"{what}:{project}", 5.0)
        if not self.herdr_state["ok"]:
            raise ActionError(503, "herdr unreachable")
        await self.resync("action")
        name = coordinators.canonical(proj)
        r = coordinators.resolution(proj, self.panes)
        if r["state"] != "ready":
            raise ActionError(409, f"{project}'s coordinator Claude is not identified ({r['state']}); open its Project "
                                   f"Console and adopt it, or use Copy prompt")
        agent = await self._fresh_agent(r["paneId"])
        if agent["status"] not in ("idle", "done"):
            raise ActionError(409, f"{name} is {agent['status']}; the {what.replace('-', ' ')} goes only to an idle coordinator")
        self._event("action", f"action.{what.replace('-', '_')}", f"{what.replace('-', ' ')} → {name}", project=project,
                    agent_id=agent["pane_id"], data={"kind": what.replace("-", "_"), **data})
        self._broker("pane.input", project, f"{what} -> coordinator pane {agent['pane_id']}")
        try:
            await self.herdr.prompt(agent["pane_id"], text)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            self._event("action", "action.failed", f"{what.replace('-', ' ')} to {name} failed", severity="warn",
                        project=project, data={"kind": what.replace("-", "_"), "error": str(e)[:160]})
            raise ActionError(502, f"herdr refused: {e}")
        return name

    async def act_night_shift(self, project, actor="jay", developer=False, copy=False):
        """Night shift: the project's idle coordinator works its open tasks under the pipeline until morning —
        plan, implement, review, merge where no gate is open, verify; never deploy (skills/night-shift/SKILL.md). Jay with
        Developer Unlock. With copy, nothing is sent: the message comes back to paste by hand."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: the night shift sends a message to Claude")
        self._need_tasks()
        if self._project(project) is None:
            raise ActionError(404, "unknown project")
        self._not_paused(project, "night shift")
        text = night_shift_text(project)
        if copy:
            return {"ok": True, "project": project, "coordinator": None, "text": text}
        name = await self._to_coordinator(project, "night-shift", text, {})
        if self.night is not None:
            self.night.start(project)
        return {"ok": True, "project": project, "coordinator": name}

    async def act_ui_test(self, project, actor="jay", developer=False, copy=False):
        """A UI test run, when Jay asks: the project's idle coordinator tests the UI features merged since its last
        run with Playwright, keeps the tests, and reports findings for Jay to decide (skills/ui-test/SKILL.md)."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: a UI test run sends a message to Claude")
        self._need_tasks()
        if self._project(project) is None:
            raise ActionError(404, "unknown project")
        self._not_paused(project, "UI test run")
        text = ui_test_text(project)
        if copy:
            return {"ok": True, "project": project, "coordinator": None, "text": text}
        name = await self._to_coordinator(project, "ui-test", text, {})
        return {"ok": True, "project": project, "coordinator": name}

    def ui_tests_state(self):
        """Every project's latest UI test run (report, findings with Jay's decisions), its fix mode, recent runs."""
        out = {}
        for p in self._projects():
            key = p["key"]
            out[key] = {"paused": registry.paused(key), "fixMode": registry.ui_fix(key),
                        "runs": self.uitests.runs(key)[:10] if self.uitests else [],
                        "latest": self.uitests.latest(key) if self.uitests else None}
        return {"projects": out}

    UI_PRIORITY = {"showstopper": "URGENT", "major": "HIGH", "minor": "LOW"}

    def act_ui_decide(self, project, run, finding, decision, actor="jay", developer=False):
        """Jay's decision on one UI test finding. fix: a BUG ticket labelled ui-finding enters the pipeline (the night
        shift or the coordinator plans and fixes it, under the repo's merge rules); skip: recorded."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: deciding a UI finding")
        if self.uitests is None:
            raise ActionError(503, "UI test runs are not configured")
        if self._project(project) is None:
            raise ActionError(404, "unknown project")
        if decision not in uitests_mod.DECISIONS:
            raise ActionError(400, "decision must be fix or skip")
        r = self.uitests.run(project, str(run or ""))
        f = next((x for x in (r or {}).get("findings") or [] if x["id"] == finding), None)
        if f is None:
            raise ActionError(404, f"no finding {finding} in {project}'s run {run}")
        if f["decision"]:
            raise ActionError(409, f"{finding} is already decided: {f['decision']['decision']}")
        ticket = None
        if decision == "fix":
            if registry.paused(project):
                raise ActionError(409, f"{project} is paused; resume it before fixing")
            lines = [f"From the UI test run {run} ({f['id']}, {f['severity']}).", ""]
            if f["feature"]:
                lines.append(f"Feature: {f['feature']}")
            if f["steps"]:
                lines += ["", "Steps:"] + [f"{i}. {x}" for i, x in enumerate(f["steps"], 1)]
            lines += ["", f"Expected: {f['expected'] or '—'}", f"Actual: {f['actual'] or '—'}"]
            if f["evidence"]:
                lines.append(f"Evidence: {f['evidence']}")
            lines += ["", "Jay chose: fix it. When fixed, the test marked expected-to-fail for this finding must pass."]
            t = self.task_create({"project": project, "title": f"UI: {f['title']}"[:200], "description": "\n".join(lines),
                                  "type": "BUG", "priority": self.UI_PRIORITY[f["severity"]], "labels": ["ui-finding"]},
                                 actor)
            ticket = t["key"]
        d = self.uitests.decide(project, run, finding, decision, ticket)
        self._event("tasks", "task.ui_finding", f"{project} {finding}: {decision}" + (f" → {ticket}" if ticket else ""),
                    project=project, ref=ticket, data={"kind": "ui_finding", "run": run, "decision": decision})
        return {"ok": True, "finding": finding, **d}

    def merge_batch(self, project, keys=None):
        """The project's Ready-to-Merge tickets Jay can merge now, in merge order, and the ones that cannot.

        Mergeable: READY_TO_MERGE, an APPROVE recorded for a head, and the last GitHub poll sees exactly that
        PR open at that head, green and not a draft. Order: a ticket another one is blocked by goes first, then
        oldest PR first. Returns (ready [{key, title, pr, head, gate}], skipped [{key, reason}])."""
        ts = self._need_tasks()
        wanted = {str(k).upper() for k in keys} if keys else None
        ready, skipped = [], []
        for row in ts.list(project=project):
            if row["status"] != "READY_TO_MERGE" or (wanted is not None and row["key"] not in wanted):
                continue
            t = ts.get(row["key"])
            w = self.pipeline.work(t["key"])
            rv = w["review"]
            prs = {p["ref"]: p for p in self._open_prs(t)}
            ref = rv.get("pr") or (next(iter(prs)) if len(prs) == 1 else None)
            pr = prs.get(ref) if ref else None
            # A convenience press, never a bypass: an open gate other than the merge gate itself (plan, UI,
            # deploy, failure) keeps the ticket out, exactly as it would keep it out of a merge by hand.
            reason = ("an open " + str(w["gate"]) + " gate" if w["gate"] not in (None, "merge")
                      else "no approved review" if rv["verdict"] != "APPROVE" or not rv["head"]
                      else "its PR is not open (or several are linked)" if not pr
                      else "the PR head changed since the review" if pr["head"] != rv["head"]
                      else "CI is not green" if not pr["ciGreen"]
                      else "the PR is a draft" if pr["draft"] else None)
            if reason:
                skipped.append({"key": t["key"], "reason": reason})
                continue
            title = CONTROL_RE.sub(" ", str(t["title"])).strip()[:90]
            ready.append({"key": t["key"], "title": title, "pr": ref, "head": rv["head"], "gate": w["gate"],
                          "blockedBy": t.get("blockedBy") or []})
        if wanted:
            found = {r["key"] for r in ready} | {s_["key"] for s_ in skipped}
            skipped += [{"key": k, "reason": "not Ready to Merge"} for k in sorted(wanted - found)]

        def pr_no(r):
            try:
                return int(str(r["pr"]).rsplit("#", 1)[1])
            except (IndexError, ValueError):
                return 10 ** 9
        ready.sort(key=pr_no)
        ordered, placed = [], set()
        keys_ready = {r["key"] for r in ready}

        def place(r, seen=()):
            if r["key"] in placed or r["key"] in seen:
                return
            for b in r["blockedBy"]:
                if b in keys_ready:
                    place(next(x for x in ready if x["key"] == b), seen + (r["key"],))
            placed.add(r["key"])
            ordered.append(r)
        for r in ready:
            place(r)
        return [{k: v for k, v in r.items() if k != "blockedBy"} for r in ordered], skipped

    async def act_merge(self, project, items=None, actor="jay", developer=False):
        """Merge: Jay approves exactly the (ticket, head) pairs the confirm box listed (`items`) that are still
        mergeable at those very heads (merge_batch), and asks the project's idle coordinator to merge them one at a
        time in that order (MERGE_TEMPLATE). ccd merges nothing itself.

        Like Go Live: every check that can refuse (403/404/409/400) runs before the message; after it, a ticket that
        cannot be approved (its head or gate moved during the send) is reported in `errors` and never undoes the
        others. A ticket whose head or readiness changed since the box was shown is skipped, never approved."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: Merge approves and merges pull requests")
        self._need_tasks()
        if self._project(project) is None:
            raise ActionError(404, "unknown project")
        self._not_paused(project, "merge")
        if not isinstance(items, list) or not items or len(items) > 50 or not all(
                isinstance(i, dict) and isinstance(i.get("key"), str) and TICKET_KEY_RE.match(i["key"].upper())
                and isinstance(i.get("head"), str) and pipeline_mod.SHA_RE.match(i["head"]) for i in items):
            raise ActionError(400, "items must be the [{key, head}] pairs the confirm box listed")
        shown = {i["key"].upper(): i["head"] for i in items}
        listed, skipped = self.merge_batch(project, list(shown))
        ready = [r for r in listed if r["head"] == shown.get(r["key"])]
        skipped += [{"key": r["key"], "reason": "its PR head changed since you looked; open Merge ready again"}
                    for r in listed if r["head"] != shown.get(r["key"])]
        if not ready:
            why = "; ".join(f"{x['key']}: {x['reason']}" for x in skipped)[:300]
            raise ActionError(409, f"{project} has nothing ready to merge" + (f" ({why})" if why else ""))
        lines = "\n".join(f"{i}. {r['key']} — {r['pr']} — head {r['head'][:12]} — {r['title']}"
                           for i, r in enumerate(ready, 1))
        text = MERGE_TEMPLATE.format(project=project, items=lines)
        for r in ready:
            self._broker("pr.merge", project, f"{r['pr']} @ {r['head'][:12]} ({r['key']}; Merge, by the coordinator)")
        name = await self._to_coordinator(project, "merge", text, {"keys": [r["key"] for r in ready]})
        errors = []
        for r in ready:
            if r["gate"] != "merge":
                continue
            # Jay's authorisation, recorded for this exact head (merge:<sha>) — only if the review still covers it.
            if self.pipeline.review_head(r["key"]) != r["head"]:
                errors.append({"key": r["key"], "error": "its reviewed head changed while the message was sent; "
                                                        "not approved"})
                continue
            try:
                self._pipeline_result(*self._wrap(self.pipeline.confirm, r["key"], "merge", actor))
            except ActionError as e:
                errors.append({"key": r["key"], "error": e.message})
        return {"ok": True, "project": project, "coordinator": name,
                "merging": [{k: r[k] for k in ("key", "pr", "head")} for r in ready], "skipped": skipped,
                "errors": errors}

    async def act_go_live(self, project, actor="jay", developer=False, keys=None):
        """Go Live: Jay approves the live-deploy gates the confirm box showed (`keys`) that are still open, and asks
        the project's idle coordinator to PREPARE the deploy by the repository's runbook and wait
        (GO_LIVE_TEMPLATE). Jay confirms the deploy himself in the coordinator's pane. ccd runs no deploy itself."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: Go Live approves live deploys and messages Claude")
        self._need_tasks()
        if not any(p["key"] == project for p in self.cfg["projects"]):
            raise ActionError(404, "unknown project")
        self._not_paused(project, "deploy")
        if not isinstance(keys, list) or len(keys) > 200 or not all(
                isinstance(k, str) and re.fullmatch(r"[A-Za-z]{1,8}-\d{1,6}", k) for k in keys):
            raise ActionError(400, "keys must be the list of ticket keys the confirm box showed")
        shown = [k.upper() for k in dict.fromkeys(keys)]
        blocked = self._go_live_blocked(project)
        if blocked:
            raise ActionError(409, blocked)
        # Approve only what Jay saw AND is still open: a gate that opened after the page loaded stays open for him.
        open_now = [a["key"] for a in self.go_live_review(project)["approves"]]
        pending = [k for k in shown if k in open_now]
        skipped = [{"key": k, "reason": "its live-deploy gate is no longer open"} for k in shown if k not in open_now]
        text = GO_LIVE_TEMPLATE.format(project=project, approved=", ".join(pending) or "none")
        self._broker("go_live.approve", project, ("Go Live: " + (", ".join(pending) or "none"))[:200])
        # The coordinator must be reachable before anything is approved: no approval without the message. Every
        # check that can refuse (409) runs before it; after it, a ticket that cannot be approved (its gate moved
        # since the page loaded) is reported in `errors` and never undoes the others.
        name = await self._to_coordinator(project, "go-live", text, {"approved": pending})
        approved, errors = [], []
        for key in pending:
            try:
                self._pipeline_result(*self._wrap(self.pipeline.confirm, key, "deploy", actor, "go-live"))
                approved.append(key)
            except Exception as e:  # noqa: BLE001 — one ticket must not stop the others
                errors.append({"key": key, "error": str(e)[:160]})
        if self.night is not None:
            self.night.went_live(project, approved)
        return {"ok": True, "project": project, "coordinator": name, "approved": approved, "skipped": skipped,
                "errors": errors}

    def go_live_review(self, project):
        """What Go Live would approve in `project` (tickets whose live-deploy gate is open), and what Jay should
        look at first: tickets merged into main (VERIFYING) that are not verified, or still wait for a UI review.
        Go Live prepares the deploy of main as it is, so those ride along."""
        out = {"approves": [], "warnings": []}
        if self.tasks is None or self.pipeline is None:
            return out
        open_ = sorted((t for t in self.tasks.list(project=project) if t["status"] not in tasks_mod.CLOSED),
                       key=lambda t: t["number"])
        marks = self.pipeline.compact(t["id"] for t in open_)
        for t in open_:
            m = marks.get(t["id"]) or {}
            row = {"key": t["key"], "title": CONTROL_RE.sub(" ", str(t["title"])).strip()[:100]}
            if m.get("gate") == "deploy":
                out["approves"].append(row)
            if t["status"] == "VERIFYING":
                if m.get("gate") == "ui":
                    out["warnings"].append(dict(row, reason="UI review still open"))
                elif (m.get("verification") or {}).get("result") != "pass":
                    out["warnings"].append(dict(row, reason="merged, not verified"))
        return out

    GO_LIVE_GAP = 1800            # s: no second Go Live this soon after the first
    GO_LIVE_OPEN_MAX = 12 * 3600  # s: an unfinished Go Live blocks the next one for at most this long

    def _go_live_blocked(self, project):
        """Why Go Live must not run now (409 text), or None: a night shift is running, or a Go Live was sent
        recently, or is unfinished (a ticket it approved is not recorded deployed yet)."""
        if self.night is None:
            return None
        if self.night.active(project):
            return f"{project}'s night shift is still running; end it first"
        st = self.night.get(project)
        at = st.get("goLiveAt")
        age = _now() - at if at else None
        if age is None or age >= self.GO_LIVE_OPEN_MAX:
            return None
        if age < self.GO_LIVE_GAP:
            return f"Go Live was sent for {project} {int(age // 60)} min ago; let the coordinator finish"
        for key in st.get("goLiveKeys") or []:
            try:
                t = self.tasks.get(key)
                d = self.pipeline.work(key).get("deploy") or {}
            except tasks_mod.TaskError:
                continue
            if t["status"] not in tasks_mod.CLOSED and d.get("approvedAt") and not d.get("result"):
                return f"the last Go Live for {project} is unfinished: {key} is approved but not recorded deployed yet"
        return None

    async def act_task_check(self, project, actor="jay", developer=False, copy=False):
        """Ask the project's coordinator Claude to check its open tasks against the repo (TASK_CHECK_TEMPLATE).
        Jay with Developer Unlock (it types into Claude). Never into a busy or blocked coordinator. With copy,
        nothing is sent: the message comes back for Jay to paste into any Claude in that repo."""
        if actor != "jay" or not developer:
            raise ActionError(403, "Developer Unlock required: the task check sends a message to Claude")
        self._need_tasks()
        proj = self._project(project)
        if proj is None:
            raise ActionError(404, "unknown project")
        self._not_paused(project, "task check")
        if copy:
            text, n = self.task_check_text(project)
            return {"ok": True, "project": project, "coordinator": None, "openTasks": n, "text": text}
        text, n = self.task_check_text(project)
        name = await self._to_coordinator(project, "task-check", text, {"count": n})
        return {"ok": True, "project": project, "coordinator": name, "openTasks": n}

    async def act_dispatch(self, project, task, verb, note=""):
        """Send one task to a coordinator, under the dispatch skill's rules.

        Coordinators only (lanes are the coordinator's call), canonical name
        only, never into a busy or blocked agent, and the message carries the
        skill's non-authorisation preamble word for word.
        """
        allowed = set(self.cfg.get("dispatch_projects") or ("samvision", "gauzemate"))
        proj = self._project(project)
        if proj is None:
            raise ActionError(404, "unknown project")
        if project not in allowed:
            raise ActionError(409, f"{project} has no coordinator; tasks go to a lane (see the dispatch skill)")
        self._not_paused(project, "dispatch")
        if verb not in DISPATCH_VERBS:
            raise ActionError(400, f"verb must be one of {', '.join(DISPATCH_VERBS)}")
        is_ticket = isinstance(task, str) and self.tasks is not None and bool(TICKET_KEY_RE.match(task)) \
            and self.tasks.exists(task)
        if not isinstance(task, str) or not (TASK_ID_RE.match(task) or is_ticket):
            raise ActionError(400, f"taskId must look like {registry.prefix_of('samvision')}-056, GYST-VN-009 or "
                                   f"#42, or be an existing ticket key")
        if is_ticket and self.tasks.get(task)["project"] != project:
            raise ActionError(409, f"{task} belongs to another project")
        if not isinstance(note, str) or not NOTE_RE.match(note):
            raise ActionError(400, "note must be printable, one line, at most 500 characters")
        self._throttle(f"dispatch:{project}", 5.0)
        name = coordinators.canonical(proj)
        # The one resolver decides which Claude is the coordinator (a session binding, not a name).
        if not self.herdr_state["ok"]:
            raise ActionError(503, "herdr unreachable")
        await self.resync("action")
        r = coordinators.resolution(proj, self.panes)
        if r["state"] != "ready":
            raise ActionError(409, f"{project}'s coordinator is not identified ({r['state']}); adopt it in Workspace")
        agent = await self._fresh_agent(r["paneId"])
        if agent["status"] not in ("idle", "done"):
            raise ActionError(409, f"{name} is {agent['status']}; dispatch only goes to an idle coordinator")
        plan = self._plan_for(task) or "none – plan it first per your workflow"
        text = DISPATCH_TEMPLATE.format(verb=verb, task=task, plan=plan, note=note.replace('"', "'"))
        self._event("action", "action.dispatch", f"{verb} {task} → {name}", project=project, agent_id=agent["pane_id"],
                    ref=task, data={"kind": verb})
        self._broker("pane.input", project, f"dispatch {verb} {task} -> coordinator pane {agent['pane_id']}")
        try:
            await self.herdr.prompt(agent["pane_id"], text)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            self._event("action", "action.failed", f"dispatch to {name} failed", severity="warn",
                        project=project, data={"kind": "dispatch", "error": str(e)[:160]})
            raise ActionError(502, f"herdr refused: {e}")
        if is_ticket:
            rule = DISPATCH_TRANSITIONS.get(verb)
            t = self.tasks.get(task)
            self._task_event("task.updated", t, f"dispatched: {verb} → {name}", {"kind": "dispatch"})
            # A pipeline ticket moves only through its own steps (start records branch, worktree, lane).
            if rule and not self.pipeline.participating(task):
                self._auto(task, rule[0], rule[1], f"dispatch '{verb}' accepted by idle coordinator {name}")
        return {"ok": True, "coordinator": name, "task": task, "verb": verb, "plan": plan}
