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
_SGR_EXTENDED = {"38", "48", "58"}     # colour introducers: their sub-parameters are not attributes


def _sgr_faint(params, faint):
    """Faint state after one SGR sequence. FAILS CLOSED (CC-053 review P1): anything incomplete, non-numeric or not
    a recognised colour form raises ValueError, so the whole screen reads as unparseable (None, nothing sent). Never
    return the old faint state past a parameter we could not place: after an unfinished 38;2;10 the typed words that
    follow would otherwise still count as faint, and a draft would read as empty."""
    items = params.split(";")
    i = 0
    while i < len(items):
        item = items[i]
        head = item.split(":")[0]
        if head != "" and not head.isdigit():
            raise ValueError("bad SGR parameter")
        if head in _SGR_EXTENDED:
            if ":" in item:                     # colon form: 38:5:n, 38:2:r:g:b or 38:2:cs:r:g:b, every part a number
                parts = item.split(":")[1:]
                want = {"5": (2,), "2": (4, 5)}.get(parts[0] if parts else "")
                # the colour-space slot (second part of the 5-part form) may be empty; every colour value must be a number
                values = parts[2:] if len(parts) == 5 else parts[1:]
                if want is None or len(parts) not in want or not all(x.isdigit() for x in values) \
                        or not (parts[1] == "" or parts[1].isdigit()):
                    raise ValueError("bad colon colour")
                i += 1
                continue
            nxt = items[i + 1] if i + 1 < len(items) else ""
            need = {"5": 1, "2": 3}.get(nxt)    # numbers that must follow the 5 or the 2: n, or r;g;b
            if need is None:
                raise ValueError("unknown colour form")
            vals = items[i + 2:i + 2 + need]
            if len(vals) != need or not all(v.isdigit() for v in vals):
                raise ValueError("incomplete colour")
            i += 2 + need                       # that 2 inside 38;2;... is not "faint"
            continue
        if head in ("", "0", "22"):
            faint = False
        elif head == "2" and ":" not in item:
            faint = True
        i += 1
    return faint


def _screen_line(line):
    """(text with colour codes removed, the same text minus every character drawn faint). Raises ValueError on any
    escape that is truncated, unterminated, malformed or not one we know (CC-053 review P1: fail closed, the caller
    then reads None and sends nothing). One pass, no backtracking. CC-053: Claude Code draws its suggested prompt
    in SGR 2 (faint), which a colour-stripped read cannot tell from text Jay typed."""
    plain, bright = [], []
    faint = False
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch != "\x1b":
            plain.append(ch)
            if not faint:
                bright.append(ch)
            i += 1
            continue
        if i + 1 >= n:
            raise ValueError("truncated escape")
        kind = line[i + 1]
        if kind == "[":                         # CSI: parameter bytes 0x30-0x3f, then one final byte 0x40-0x7e
            j = i + 2
            while j < n and "0" <= line[j] <= "?":
                j += 1
            if j >= n or not "@" <= line[j] <= "~":
                raise ValueError("truncated or malformed CSI")
            if line[j] != "m":
                raise ValueError("unrecognised CSI")   # only colours are expected; any other control is uncertainty
            faint = _sgr_faint(line[i + 2:j], faint)
            i = j + 1
        elif kind == "]":                       # OSC: up to BEL or ESC \
            j = i + 2
            while j < n and line[j] != "\x07" and not (line[j] == "\x1b" and line[j + 1:j + 2] == "\\"):
                j += 1
            if j >= n:
                raise ValueError("unterminated OSC")
            i = j + 1 if line[j] == "\x07" else j + 2
        else:
            raise ValueError("unrecognised escape")
    return "".join(plain), "".join(bright)


def input_is_empty(text):
    """Is Claude Code's input line empty? From the pane's text only, so best effort. True only when the LAST prompt
    line (`>` or `❯`, optionally inside a box) is empty or shows the dim `Try "…"` placeholder and nothing but box
    borders or blanks follow it before the next border. False when it holds text (or a further line of a draft).
    None when no prompt line can be parsed: the caller treats None like False and sends nothing.

    Given a read WITH colour codes (herdr format=ansi), text drawn faint, Claude Code's grey suggested prompt, counts
    as empty (CC-053); anything not faint is a draft. Without codes the text behaves exactly as before."""
    try:
        screen = [_screen_line(ln) for ln in str(text or "").splitlines()[-60:]]
    except ValueError:
        return None                             # garbled escapes: send nothing
    plain = [p for p, _ in screen]
    bright = [b for _, b in screen]
    at = next((i for i in range(len(plain) - 1, -1, -1) if PROMPT_RE.match(plain[i])), None)
    if at is None:
        return None
    m = PROMPT_RE.match(bright[at])
    if m is None:
        return False                            # dropping faint text broke the line's shape: not one we know
    typed = (m.group(1) or "").strip()
    if typed and not typed.startswith('Try "'):
        return False
    if PLACEHOLDER_RE.search(plain[at]):
        return False                            # a paste or image stand-in is a draft whatever its colour
    for k in range(at + 1, len(bright)):
        if PLACEHOLDER_RE.search(plain[k]):
            return False
        rest = bright[k].strip().strip("│┃").strip()
        if not rest:
            continue
        if all(c in BOX_CHARS for c in rest):
            return True          # the box's bottom border: nothing was typed inside
        return False             # text under the prompt before any border: a multi-line draft
    return True


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
