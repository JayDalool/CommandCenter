"""The night shift's supervisor: keeps each project's coordinator working until its morning report says done.

The coordinator works by the /night-shift skill (skills/night-shift/SKILL.md). Claude stops when it thinks it
is finished, hits a pause or loses the thread; this module decides, once a minute and from facts only, whether
to remind it to continue:

  report "Status: complete"         → the shift ends (complete)
  coordinator working               → progress; nothing to do
  coordinator blocked               → it waits on a prompt for Jay; nothing to do
  idle ≥ IDLE_GRACE, last reminder ≥ NUDGE_GAP ago
     and progress since then        → remind it (one fixed sentence)
     and no progress after MAX_QUIET reminders in a row → the shift ends (no progress)

Progress is anything the coordinator did since the last reminder: seen working, its report rewritten, or a ticket
of the project changed. State lives in <night dir>/.state.json so a ccd restart resumes it.
"""
import json
import os
import re
import time
from pathlib import Path

from .config import LEGACY

# Where the coordinators write their morning reports (/night-shift skill) and the supervisor keeps its state.
NIGHT_DIR = Path(os.environ.get("CCD_NIGHT_DIR", LEGACY / "night-shift"))

IDLE_GRACE = 180       # s idle before a reminder: Claude often pauses briefly between steps
NUDGE_GAP = 600        # s between reminders
MAX_QUIET = 3          # reminders in a row with no progress → the shift ends
REPORT_MAX = 64 * 1024
STATUS_RE = re.compile(r"^\s*Status:\s*(working|complete)\b", re.IGNORECASE)
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

NUDGE_TEXT = (
    "Night shift continues (Command Center): your morning report still says Status: working. Take the next item "
    "by the /night-shift rules for {project}. If nothing is left that can move without Jay, make the report's first "
    "line Status: complete and stop."
)
END_TEXT = (
    "Jay ended the night shift for {project}. Finish the step you are on safely, update the morning report "
    "(Status: complete, with what is left), and stop."
)


def _now():
    return time.time()


class NightShift:
    def __init__(self, root):
        self.root = Path(root)
        self.state = self._load()

    # ---------- state ----------

    def _path(self):
        return self.root / ".state.json"

    def _load(self):
        try:
            data = json.loads(self._path().read_text())
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if KEY_RE.match(k) and isinstance(v, dict)} if isinstance(data, dict) else {}

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path().with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True))
        tmp.replace(self._path())

    def get(self, project):
        return dict(self.state.get(project) or {})

    def active(self, project):
        s = self.state.get(project) or {}
        return bool(s.get("startedAt")) and not s.get("endedAt")

    def start(self, project, now=None):
        now = now or _now()
        self.state[project] = {"startedAt": now, "endedAt": None, "endReason": None, "nudges": 0, "quiet": 0,
                               "lastNudgeAt": None, "idleSince": None, "progressAt": now,
                               "goLiveAt": (self.state.get(project) or {}).get("goLiveAt")}
        self.save()

    def end(self, project, reason, now=None):
        s = self.state.get(project)
        if not s or s.get("endedAt"):
            return False
        s.update(endedAt=now or _now(), endReason=reason)
        self.save()
        return True

    def went_live(self, project, now=None):
        self.state.setdefault(project, {})["goLiveAt"] = now or _now()
        self.save()

    # ---------- the morning report ----------

    def report(self, project):
        """The newest report for the project: {name, mtime, status, text} or None."""
        if not KEY_RE.match(project or ""):
            return None
        d = self.root / project
        try:
            files = [f for f in d.iterdir() if f.suffix == ".md" and f.is_file() and not f.is_symlink()]
        except OSError:
            return None
        if not files:
            return None
        f = max(files, key=lambda p: p.stat().st_mtime)
        try:
            with open(f, "rb") as fh:
                raw = fh.read(REPORT_MAX + 1)
        except OSError:
            return None
        text = raw[:REPORT_MAX].decode("utf-8", "replace")
        first = text.splitlines()[0] if text else ""
        m = STATUS_RE.match(first)
        return {"name": f.name, "mtime": f.stat().st_mtime, "status": m.group(1).lower() if m else None,
                "text": text + ("\n[…truncated]" if len(raw) > REPORT_MAX else "")}

    # ---------- the decision ----------

    def decide(self, project, status, activity_at=None, now=None):
        """One supervisor tick for an active project. status: the coordinator's herdr status (idle, done, working,
        blocked) or None when no coordinator is identified. Returns "nudge", "end:<reason>" or None."""
        now = now or _now()
        s = self.state.get(project)
        if not s or not s.get("startedAt") or s.get("endedAt"):
            return None
        rep = self.report(project)
        if rep and rep["status"] == "complete" and rep["mtime"] >= s["startedAt"]:
            self.end(project, "complete", now)
            return "end:complete"
        progress = max(x for x in (s.get("progressAt") or 0, activity_at or 0,
                                   rep["mtime"] if rep and rep["mtime"] >= s["startedAt"] else 0))
        changed = False
        if status == "working":
            progress = now
        if progress != s.get("progressAt"):
            s["progressAt"] = progress
            changed = True
        if status not in ("idle", "done"):
            if s.get("idleSince"):
                s["idleSince"] = None
                changed = True
            if changed:
                self.save()
            return None
        if not s.get("idleSince"):
            s["idleSince"] = now
            self.save()
            return None
        last = s.get("lastNudgeAt")
        if now - s["idleSince"] < IDLE_GRACE or (last and now - last < NUDGE_GAP):
            if changed:
                self.save()
            return None
        s["quiet"] = 0 if (not last or progress > last) else s.get("quiet", 0) + 1
        if s["quiet"] >= MAX_QUIET:
            s.update(endedAt=now, endReason=f"no progress after {MAX_QUIET} reminders")
            self.save()
            return "end:no progress"
        s.update(lastNudgeAt=now, nudges=s.get("nudges", 0) + 1, idleSince=None)
        self.save()
        return "nudge"
