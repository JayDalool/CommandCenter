"""The night shift's supervisor: keeps each project's coordinator working until its morning report says done.

The coordinator works by the /night-shift skill (skills/night-shift/SKILL.md). Claude stops when it thinks it
is finished, hits a pause or loses the thread; this module decides, once a minute and from facts only, whether
to remind it to continue:

  report "Status: complete"         → the shift ends (complete)
  morning cutoff (default 07:00)    → the shift ends (morning cutoff); nothing is typed into the pane
  coordinator working or blocked    → nothing to do (blocked: it waits on a prompt for Jay)
  idle ≥ IDLE_GRACE, last reminder ≥ NUDGE_GAP ago
     and MAX_NUDGES reminders sent  → the shift ends (reminder limit)
     and no progress after MAX_QUIET reminders in a row → the shift ends (no progress)
     otherwise                      → remind it (one fixed sentence; counted only once it was delivered)

Hard stops: MAX_NUDGES reminders per shift and the morning cutoff, whatever the coordinator does in between.
Progress is only a change of a ticket of the project or a rewrite of the morning report: "seen working" is not
progress, so a coordinator that works after every reminder without changing anything still runs out.
State lives in <night dir>/.state.json so a ccd restart resumes it.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import LEGACY

# Where the coordinators write their morning reports (/night-shift skill) and the supervisor keeps its state.
NIGHT_DIR = Path(os.environ.get("CCD_NIGHT_DIR", LEGACY / "night-shift"))

IDLE_GRACE = 180       # s idle before a reminder: Claude often pauses briefly between steps
NUDGE_GAP = 600        # s between reminders
MAX_QUIET = 3          # reminders in a row with no progress → the shift ends
MAX_NUDGES = 6         # reminders in one shift, whatever happens in between → the shift ends
CUTOFF_DEFAULT = "07:00"   # local time: no reminder after it, the shift ends (CCD_NIGHT_CUTOFF=HH:MM)
REPORT_MAX = 64 * 1024
STATUS_RE = re.compile(r"^\s*Status:\s*(working|complete)\b", re.IGNORECASE)
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
REPORT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")   # the skill's <YYYY-MM-DD>.md: other notes in the folder (PR reviews…) are not reports
CUTOFF_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

NUDGE_WITH_REPORT = (
    "Night shift continues (Command Center): your morning report still says Status: working. Take the next item "
    "by the /night-shift rules for {project}. If nothing is left that can move without Jay, make the report's first "
    "line Status: complete and stop."
)
NUDGE_NO_REPORT = (
    "Night shift continues (Command Center): there is no morning report for this shift yet. Take the next item "
    "by the /night-shift rules for {project} and write the report as the skill says, first line Status: working. "
    "If nothing can move without Jay, write it with Status: complete and stop."
)
END_TEXT = (
    "Jay ended the night shift for {project}. Finish the step you are on safely, update the morning report "
    "(Status: complete, with what is left), and stop."
)


def _now():
    return time.time()


BOX_CHARS = set("─━│┃╭╮╯╰┌┐└┘ \t")
PROMPT_RE = re.compile(r"^\s*(?:[│┃]\s*)?(?:>|❯)(?:\s+(.*?))?\s*(?:[│┃])?\s*$")


# Claude Code's stand-ins for a paste or an image in the input box. Their styling was never captured, so a prompt
# holding one is always a draft, faint or not (CC-053).
PLACEHOLDER_RE = re.compile(r"\[(?:Pasted text|Image|\.\.\.Truncated text) #\d")

# CC-053 (Jay's re-plan): in a colour-coded read the input line counts as empty only when it is byte-for-byte one of
# two known shapes. Two Codex rounds found a new colour code that made typed text look faint each time, so nothing
# here parses or reasons about colour parameters: a different render simply does not match and fails safe (nothing
# sent, the message stays queued). SUGGESTION is herdr's serialisation of Claude Code's grey suggested prompt as
# captured live (herdr 0.9.3 format=ansi): glyph, NBSP, reset, faint on, the hint as one run, reset. The hint class
# excludes ESC and C0/C1 controls, so the pattern is linear and cannot swallow another escape.
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SUGGESTION_RE = re.compile(
    "\u276f[ \u00a0]\x1b\\[0m\x1b\\[2m(?P<hint>[^\x00-\x1f\x7f-\x9f]+)\x1b\\[0m[ \u00a0]*")
_EMPTY_PROMPT_RE = re.compile("\u276f[ \u00a0]*")


def _last_prompt(lines):
    """Index of the last prompt line (matched on `lines` as given), or None. Shared with CC-070's draft check."""
    return next((i for i in range(len(lines) - 1, -1, -1) if PROMPT_RE.match(lines[i])), None)


def _under_prompt_ok(lines, at):
    """True when only blanks and box borders follow the prompt line before the next border; False on any other
    text (a multi-line draft, a paste placeholder, a leftover escape byte)."""
    for k in range(at + 1, len(lines)):
        if PLACEHOLDER_RE.search(lines[k]):
            return False
        rest = lines[k].strip().strip("│┃").strip()
        if not rest:
            continue
        return all(c in BOX_CHARS for c in rest)   # the box's bottom border: nothing was typed inside
    return True


_BORDER_CHARS = set("─━╭╮╯╰┌┐└┘")


def _above_prompt_ok(clean, at, prompt_empty):
    """CC-053 (security review, Jay's Q229): the box is more than its last `>` line. Walk up from the last prompt to the
    box's top border: every earlier prompt line must itself be empty, and (once a border proves it is inside the box)
    any other text is a continuation line of a draft. So a draft followed by a line that is just `>` is a draft."""
    seen_text = False
    for k in range(at - 1, -1, -1):
        rest = clean[k].strip().strip("│┃").strip()
        if not rest:
            continue
        if all(c in BOX_CHARS for c in rest) and any(c in _BORDER_CHARS for c in rest):
            return not seen_text
        if PROMPT_RE.match(clean[k]):
            if not prompt_empty(k):
                return False
        else:
            seen_text = True
    return True


async def input_still_empty(herdr, pane_id):
    """Fresh read of the pane for the moment before a send (CC-053). herdr has no conditional send, so the check and
    the paste cannot be atomic; reading again right before `agent.prompt` shrinks the gap to milliseconds."""
    screen = await herdr.read_tail(pane_id, 40, ansi=True)
    return input_is_empty(screen["text"]) is True


def _ansi_prompt_is_empty(raw_line):
    if _EMPTY_PROMPT_RE.fullmatch(raw_line):
        return True
    m = _SUGGESTION_RE.fullmatch(raw_line)
    if m is None:
        return False
    hint = m.group("hint")
    return bool(hint.strip()) and not PLACEHOLDER_RE.search(hint)


def input_is_empty(text):
    """Is Claude Code's input line empty? From the pane's text only, so best effort. True only when the LAST prompt
    line (`>` or `❯`, optionally inside a box) is empty or shows the dim `Try "…"` placeholder and nothing but box
    borders or blanks follow it before the next border. False when it holds text (or a further line of a draft).
    None when no prompt line can be parsed: the caller treats None like False and sends nothing.

    A read WITH colour codes (herdr format=ansi, CC-053) counts as empty only for a bare prompt or the exact grey
    suggestion shape (see _SUGGESTION_RE); any other content on the prompt line is a draft. A read without codes
    behaves exactly as before."""
    lines = str(text or "").splitlines()[-60:]
    if not any("\x1b" in ln for ln in lines):
        at = _last_prompt(lines)
        if at is None:
            return None
        typed = (PROMPT_RE.match(lines[at]).group(1) or "").strip()
        if typed and not typed.startswith('Try "'):
            return False
        def plain_empty(k):
            t = (PROMPT_RE.match(lines[k]).group(1) or "").strip()
            return not t or t.startswith('Try "')
        return _above_prompt_ok(lines, at, plain_empty) and _under_prompt_ok(lines, at)
    clean = [_CSI_RE.sub("", ln) for ln in lines]   # only to locate the prompt and read the lines under it
    # Tech review (CC-053): a non-CSI escape (ESC(B, an OSC, a truncated CSI) left anywhere could hide the real prompt
    # line from the locate step so an earlier bare prompt reads empty over a typed draft. Uncertain: send nothing.
    if any("\x1b" in ln for ln in clean):
        return None
    at = _last_prompt(clean)
    if at is None:
        return None
    if not _ansi_prompt_is_empty(lines[at]):
        return False
    return _above_prompt_ok(clean, at, lambda k: _ansi_prompt_is_empty(lines[k])) and _under_prompt_ok(clean, at)


def cutoff_after(started, hhmm=CUTOFF_DEFAULT):
    """The first local HH:MM strictly after `started` (epoch s): the shift's morning cutoff."""
    m = CUTOFF_RE.match(str(hhmm or "")) or CUTOFF_RE.match(CUTOFF_DEFAULT)
    d = datetime.fromtimestamp(started)
    c = d.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    if c <= d:
        c += timedelta(days=1)
    return c.timestamp()


class NightShift:
    def __init__(self, root, cutoff=None):
        self.root = Path(root)
        self.cutoff = cutoff or os.environ.get("CCD_NIGHT_CUTOFF") or CUTOFF_DEFAULT
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
                               "cutoffAt": cutoff_after(now, self.cutoff),
                               "goLiveAt": (self.state.get(project) or {}).get("goLiveAt"),
                               "goLiveKeys": (self.state.get(project) or {}).get("goLiveKeys") or []}
        self.save()

    def end(self, project, reason, now=None):
        s = self.state.get(project)
        if not s or s.get("endedAt"):
            return False
        s.update(endedAt=now or _now(), endReason=reason)
        self.save()
        return True

    def went_live(self, project, keys=(), now=None):
        """Go Live was sent for these ticket keys (the Go Live guard reads it back)."""
        self.state.setdefault(project, {}).update(goLiveAt=now or _now(), goLiveKeys=list(keys))
        self.save()

    def nudge_text(self, project):
        """The reminder, true to what exists: a report written in this shift, or none yet."""
        s, rep = self.state.get(project) or {}, self.report(project)
        fresh = bool(rep and rep["mtime"] >= (s.get("startedAt") or 0))
        return (NUDGE_WITH_REPORT if fresh else NUDGE_NO_REPORT).format(project=project)

    # ---------- the morning report ----------

    def report(self, project):
        """The newest <YYYY-MM-DD>.md report for the project: {name, mtime, status, text} or None."""
        if not KEY_RE.match(project or ""):
            return None
        d = self.root / project
        found = []
        try:
            for f in d.iterdir():
                try:   # a report can vanish between the listing and the stat: skip it
                    if REPORT_NAME_RE.match(f.name) and not f.is_symlink() and f.is_file():
                        found.append((f.stat().st_mtime, f))
                except OSError:
                    continue
        except OSError:
            return None
        for _, f in sorted(found, key=lambda x: x[0], reverse=True):
            try:
                with open(f, "rb") as fh:
                    raw = fh.read(REPORT_MAX + 1)
                    mtime = os.fstat(fh.fileno()).st_mtime
            except OSError:
                continue   # gone or unreadable now: the next newest one
            text = raw[:REPORT_MAX].decode("utf-8", "replace")
            first = text.splitlines()[0] if text else ""
            m = STATUS_RE.match(first)
            return {"name": f.name, "mtime": mtime, "status": m.group(1).lower() if m else None,
                    "text": text + ("\n[…truncated]" if len(raw) > REPORT_MAX else "")}
        return None

    # ---------- the decision ----------

    def decide(self, project, status, activity_at=None, now=None):
        """One supervisor tick for an active project. status: the coordinator's herdr status (idle, done, working,
        blocked) or None when no coordinator is identified. Returns "nudge", "end:<reason>" or None.
        "nudge" only says one is due: the caller sends it and then calls nudged() — a reminder that was not
        delivered, or found the coordinator busy, is not counted."""
        now = now or _now()
        s = self.state.get(project)
        if not s or not s.get("startedAt") or s.get("endedAt"):
            return None
        rep = self.report(project)
        if rep and rep["status"] == "complete" and rep["mtime"] >= s["startedAt"]:
            self.end(project, "complete", now)
            return "end:complete"
        cutoff = s.get("cutoffAt") or cutoff_after(s["startedAt"], self.cutoff)
        if now >= cutoff:
            self.end(project, "morning cutoff", now)
            return "end:morning cutoff"
        progress = max(s.get("progressAt") or 0, activity_at or 0,
                       rep["mtime"] if rep and rep["mtime"] >= s["startedAt"] else 0)
        changed = progress != s.get("progressAt")
        s["progressAt"] = progress
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
        if s.get("nudges", 0) >= MAX_NUDGES:
            self.end(project, f"reminder limit ({MAX_NUDGES})", now)
            return "end:reminder limit"
        if self._quiet(s, progress) >= MAX_QUIET:
            self.end(project, f"no progress after {MAX_QUIET} reminders", now)
            return "end:no progress"
        if changed:
            self.save()
        return "nudge"

    @staticmethod
    def _quiet(s, progress):
        last = s.get("lastNudgeAt")
        return 0 if (not last or progress > last) else s.get("quiet", 0) + 1

    def skipped(self, project, reason, now=None):
        """A due reminder was held back (the input line was not empty). Not counted; the state keeps the last reason."""
        s = self.state.get(project)
        if s and not s.get("endedAt") and s.get("lastSkip") != reason:
            s["lastSkip"] = reason
            s["lastSkipAt"] = now or _now()
            self.save()

    def nudged(self, project, now=None):
        """A reminder reached an idle coordinator: count it."""
        now = now or _now()
        s = self.state.get(project)
        if not s or s.get("endedAt"):
            return
        s.pop("lastSkip", None)
        s.update(quiet=self._quiet(s, s.get("progressAt") or 0), lastNudgeAt=now, nudges=s.get("nudges", 0) + 1,
                 idleSince=None)
        self.save()
