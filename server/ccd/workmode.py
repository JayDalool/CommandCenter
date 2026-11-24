"""Work mode: keep a project's lead working its open tickets, day and night (Jay, 2026-11-15).

Without it a lead acts only when someone messages it, so a ticket can wait a day with nobody in its seat. Jay
switches work mode on per project (Settings › Operating profiles, PUT /api/work-mode/projects/{key} with
Developer Unlock); every project starts off. Once a minute, for each project that is on, ccd decides from facts
only whether to remind its idle lead that tickets can move without Jay, and names the next ones:

  project paused, night shift running, budget on hold      → nothing (the night shift has its own reminders)
  no ticket can move without Jay                           → nothing
  lead not identified, working or blocked                  → nothing
  idle < IDLE_GRACE, or the last reminder < NUDGE_GAP ago  → nothing
  DAY_MAX reminders already today (local day)              → nothing until tomorrow
  REST_AFTER reminders in a row with no ticket change      → rest REST_S, then remind again
  otherwise                                                → remind: one fixed text plus the next tickets

A ticket "can move" when it is open, not blocked, not waiting on Jay (an open question or a gate), not at merge
(Jay merges), not Jay's own action or a lawyer's question, not flagged needs-Jay while still in intake (the board shows
it as Jay's), and nobody holds its seat (or the ticket has gone stale). The order is priority, then the earliest due
date, then the later stage (finish before start), then the oldest. A release-stage ticket is named for verifying only. The reminder grants nothing: the lead follows its
repository's rules and the flow, and every plan, merge and deploy gate still waits for Jay.

Stored in <CCD_STATE_DIR>/work-mode.json (0600), written atomically. Only the on/off switch is Jay's; the rest is
the supervisor's bookkeeping, so a ccd restart resumes where it was.
"""
import datetime
import json
import math
import os
import re
import tempfile
import time
import zoneinfo

IDLE_GRACE = 180        # s idle before a reminder: Claude often pauses briefly between steps
NUDGE_GAP = 600         # s between reminders
REST_AFTER = 3          # reminders in a row with no ticket change → rest
REST_S = 2 * 3600       # how long a rest lasts
DAY_MAX = 36            # reminders per project per local day, whatever happens in between
SHOW = 3                # tickets named in one reminder
TZ = zoneinfo.ZoneInfo("America/Winnipeg")
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

PRIORITY_RANK = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}     # NO_PRIORITY and anything else: last
STAGE_ORDER = ("intake", "investigate", "techReview", "build", "userCheck", "codeReview", "release", "blockerTriage")
STAGE_LABEL = {"intake": "intake", "investigate": "investigate", "techReview": "technical review", "build": "build",
               "userCheck": "user check", "codeReview": "code review", "release": "release, verify only",
               "blockerTriage": "blocked, record the next action"}
CLOSED = ("DONE", "DENIED", "CANCELLED")

REMINDER = (
    "Work mode (Command Center): {project} has tickets that can move without Jay. Next: {tickets}. "
    "Take them in this order by your repository's rules and the flow: record each step with pipeline_cli, "
    "fill an empty seat per FLOW.md, and never merge or deploy. If a ticket needs Jay, ask him "
    "(pipeline_cli ask, with options) or block it, then take the next one. For a blocked ticket needing triage, "
    "record the next action in a handoff, rework an in-scope fix, re-plan changed scope, or ask Jay to decide."
)


class WorkModeError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _now():
    return time.time()


def _day(at):
    return datetime.datetime.fromtimestamp(at, TZ).date().isoformat()


def movable(rows):
    """The tickets the lead can move without Jay, in the order to take them. `rows`: dicts with key, status, type,
    flags, priority, dueAt, number, stage, holder, waitingOn, stale (flow.view's fields plus the ticket's)."""
    out = []
    for r in rows:
        if r.get("status") in CLOSED:
            continue
        flags = {f.replace(":", "_").replace("-", "_") for f in r.get("flags") or ()}     # as pipeline.policy
        if r.get("type") == "OWNER_ACTION" or "needs_legal" in flags:
            continue                                    # Jay's own to-do; a lawyer's question (as the night shift)
        if r.get("status") == "BLOCKED":
            if r.get("needsBlockerTriage"):
                out.append(dict(r, stage="blockerTriage"))
            continue
        if r.get("waitingOn") == "jay" or r.get("stage") not in STAGE_ORDER:
            continue                                    # merge is Jay's; done has nothing left
        if "needs_jay" in flags and r.get("status") in ("INBOX", "PROPOSED"):
            continue                                    # the board shows it as Jay's until it is past intake
        if r.get("holder") and not r.get("stale"):
            continue                                    # somebody is in the seat and still recording steps
        out.append(r)
    due = lambda r: r["dueAt"] if isinstance(r.get("dueAt"), (int, float)) else math.inf   # noqa: E731
    return sorted(out, key=lambda r: (PRIORITY_RANK.get(r.get("priority"), 4), due(r),
                                      -STAGE_ORDER.index(r["stage"]), r.get("number") or 0))


def describe(r, now):
    """One ticket in a reminder: key, stage, and the priority and due date when set. Never its title."""
    bits = [STAGE_LABEL.get(r["stage"], r["stage"])]
    if r.get("priority") in PRIORITY_RANK:
        bits.append(r["priority"].lower())
    if isinstance(r.get("dueAt"), (int, float)):
        d = datetime.datetime.fromtimestamp(r["dueAt"], TZ)
        # By the Winnipeg calendar day, as HQ shows it: a date stored at midnight is not overdue on its own day.
        bits.append(("overdue since " if _day(r["dueAt"]) < _day(now) else "due ") + f"{d:%a} {d.day} {d:%b}")
    return f"{r['key']} ({', '.join(bits)})"


def reminder_text(project, rows, now=None):
    now = _now() if now is None else now
    return REMINDER.format(project=project, tickets="; then ".join(describe(r, now) for r in rows[:SHOW]))


class WorkMode:
    def __init__(self, path):
        self.path = str(path)
        self.on = {}        # project → {"at", "by"} while it is on
        self.state = {}     # project → supervisor bookkeeping
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            self.on = {k: {"at": v.get("at"), "by": v.get("by")} for k, v in (raw.get("on") or {}).items()
                       if isinstance(k, str) and KEY_RE.match(k) and isinstance(v, dict)}
            self.state = {k: v for k, v in (raw.get("state") or {}).items()
                          if isinstance(k, str) and KEY_RE.match(k) and isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self):
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".work-mode-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"on": self.on, "state": self.state}, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------- Jay's switch ----------

    def active(self, project):
        return project in self.on

    def set(self, project, on, by="jay", now=None):
        """Switch a project on or off. Switching on starts fresh (no rest, no idle time), except today's reminder
        count: DAY_MAX is per local day, whatever the switch did in between."""
        if not isinstance(project, str) or not KEY_RE.match(project):
            raise WorkModeError(400, "unknown project")
        if not isinstance(on, bool):
            raise WorkModeError(400, "on must be true or false")
        now = _now() if now is None else now
        old = self.state.get(project) or {}
        day = {k: old[k] for k in ("day", "dayCount") if old.get("day") == _day(now) and k in old}
        if on:
            if project not in self.on:
                self.on[project] = {"at": now, "by": by}
                self.state[project] = day
        else:
            self.on.pop(project, None)
            self.state[project] = day
            if not day:
                self.state.pop(project)
        self._save()

    def get(self, project):
        return dict(self.state.get(project) or {})

    # ---------- the decision ----------

    def decide(self, project, status, activity_at, can_move, now=None):
        """One tick for a project that is on and may be reminded (not paused, no night shift, no budget hold).
        status: the lead's herdr status (idle, done, working, blocked) or None when no lead is identified.
        can_move: how many tickets can move without Jay. Returns "nudge" or None, and keeps `why` for the screen.
        "nudge" only says one is due: the caller sends it and then calls nudged()."""
        now = _now() if now is None else now
        if project not in self.on:
            return None
        s = self.state.setdefault(project, {})
        before = dict(s)
        progress = max(s.get("progressAt") or 0, activity_at or 0)
        s["progressAt"] = progress
        if s.get("restUntil") and progress > (s.get("lastNudgeAt") or 0):
            s["restUntil"] = None                      # a ticket moved: the rest is over
            s["quiet"] = 0
        action = None
        if not can_move:
            s["why"], s["idleSince"] = "nothing can move without Jay", None
        elif status not in ("idle", "done"):
            s["why"] = "no lead" if status is None else ("lead waiting for Jay" if status == "blocked" else "lead working")
            s["idleSince"] = None
        elif not s.get("idleSince"):
            s["idleSince"], s["why"] = now, "lead idle"
        elif s.get("restUntil") and now < s["restUntil"]:
            s["why"] = "resting: no ticket moved after the last reminders"
        elif s.get("day") == _day(now) and (s.get("dayCount") or 0) >= DAY_MAX:
            s["why"] = f"{DAY_MAX} reminders today; again tomorrow"
        elif now - s["idleSince"] < IDLE_GRACE or (s.get("lastNudgeAt") and now - s["lastNudgeAt"] < NUDGE_GAP):
            s["why"] = "lead idle"
        elif self._quiet(s, progress) >= REST_AFTER:
            s.update(restUntil=now + REST_S, restedAt=now, quiet=0,
                     why="resting: no ticket moved after the last reminders")
            action = "rest"
        else:
            action = "nudge"
        if s != before:
            self._save()
        return action

    @staticmethod
    def _quiet(s, progress):
        """Reminders in a row with no ticket change since the last rest, counting the one about to be sent."""
        last = s.get("lastNudgeAt")
        if not last or progress > last or last < (s.get("restedAt") or 0):
            return 0
        return (s.get("quiet") or 0) + 1

    def note(self, project, why):
        """Why nothing was sent this tick (paused, night shift, budget hold, a draft in the input line…). Counts
        nothing; an idle lead's grace starts again once the reason is gone."""
        s = self.state.get(project)
        if s is not None and project in self.on and s.get("why") != why:
            s.update(why=why, idleSince=None)
            self._save()

    def nudged(self, project, now=None):
        """A reminder reached the idle lead: count it."""
        now = _now() if now is None else now
        s = self.state.get(project)
        if s is None or project not in self.on:
            return
        today = _day(now)
        count = (s.get("dayCount") or 0) + 1 if s.get("day") == today else 1
        s.update(quiet=self._quiet(s, s.get("progressAt") or 0), lastNudgeAt=now, idleSince=None, day=today,
                 dayCount=count, why="reminded")
        self._save()

    def public(self, project, now=None):
        """What the screen shows for one project."""
        now = _now() if now is None else now
        s = self.state.get(project) or {}
        on = self.on.get(project)
        return {"on": bool(on), "since": on["at"] if on else None, "why": s.get("why") if on else None,
                "lastReminderAt": s.get("lastNudgeAt") if on else None,
                "remindersToday": (s.get("dayCount") or 0) if on and s.get("day") == _day(now) else 0,
                "restUntil": s.get("restUntil") if on and s.get("restUntil") and s["restUntil"] > now else None}
