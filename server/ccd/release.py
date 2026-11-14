"""Live or not live, and release day (the shared flow contract §5).

Jay marks each project live or not (default not live) and sets one weekly release window for every live project
(default Wednesday 22:00 America/Winnipeg). On a live project a live deployment waits for its window: a change merged
before noon (local) on release day goes out in that day's window; one merged after noon waits a week. The deploy is
held until then (`deploy.heldUntil`), unless the ticket is risky and Jay approves it as urgent. A project that is not
live has no window and no banner. Nothing here deploys anything: who runs a deploy does not change.

Stored in <CCD_STATE_DIR>/release.json (0600), written atomically. Only Jay with Developer Unlock changes it.
"""
import datetime
import json
import os
import re
import tempfile
import zoneinfo

DEFAULT_WINDOW = {"weekday": 3, "time": "22:00", "tz": "America/Winnipeg"}   # weekday: 0 = Sunday … 6 = Saturday
WINDOW_HOURS = 2            # a held deploy may run from the window's start until this many hours after it
CUTOFF_HOUR = 12            # merged after noon (local) on release day waits a week
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class ReleaseError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _tz(window):
    return zoneinfo.ZoneInfo(window.get("tz") or DEFAULT_WINDOW["tz"])


def window_start(window, day):
    """The window's start on a local date (a datetime.date), as unix seconds."""
    hh, mm = (int(x) for x in window["time"].split(":"))
    return datetime.datetime(day.year, day.month, day.day, hh, mm, tzinfo=_tz(window)).timestamp()


def _release_days(window, after):
    """Local release dates from the one on or before `after`'s date onwards."""
    tz = _tz(window)
    d = datetime.datetime.fromtimestamp(after, tz).date()
    # Python: Monday = 0; the contract: Sunday = 0
    back = (d.isoweekday() % 7 - window["weekday"]) % 7
    d -= datetime.timedelta(days=back)
    while True:
        yield d
        d += datetime.timedelta(days=7)


def cutoff_of(window, day):
    tz = _tz(window)
    return datetime.datetime(day.year, day.month, day.day, CUTOFF_HOUR, 0, tzinfo=tz).timestamp()


def slot_for(window, merged_at):
    """(start, cutoff) of the window a change merged at `merged_at` goes out in: the first release day whose noon
    cutoff is at or after the merge."""
    for day in _release_days(window, merged_at):
        cut = cutoff_of(window, day)
        if merged_at <= cut:
            return window_start(window, day), cut


def next_window(window, now):
    """(start, cutoff) of the next window that has not ended yet."""
    for day in _release_days(window, now):
        start = window_start(window, day)
        if now < start + WINDOW_HOURS * 3600:
            return start, cutoff_of(window, day)


class Release:
    def __init__(self, path):
        self.path = str(path)
        self.data = {"window": dict(DEFAULT_WINDOW), "live": {}}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            w = raw.get("window") or {}
            if isinstance(w.get("weekday"), int) and 0 <= w["weekday"] <= 6 and TIME_RE.match(str(w.get("time"))):
                self.data["window"] = {"weekday": w["weekday"], "time": w["time"], "tz": DEFAULT_WINDOW["tz"]}
            self.data["live"] = {k: True for k, v in (raw.get("live") or {}).items()
                                 if isinstance(k, str) and KEY_RE.match(k) and v is True}
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self, data):
        """Write `data` to disk, then (only then) make it the settings in memory."""
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".release-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            self.data = data
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @property
    def window(self):
        return dict(self.data["window"])

    def live(self, project):
        return bool(self.data["live"].get(project))

    def set_live(self, project, live):
        if not isinstance(project, str) or not KEY_RE.match(project):
            raise ReleaseError(400, "unknown project")
        if not isinstance(live, bool):
            raise ReleaseError(400, "live must be true or false")
        data = json.loads(json.dumps(self.data))
        if live:
            data["live"][project] = True
        else:
            data["live"].pop(project, None)
        self._save(data)

    def set_window(self, weekday, time_):
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise ReleaseError(400, "weekday is 0 (Sunday) to 6 (Saturday)")
        if not isinstance(time_, str) or not TIME_RE.match(time_):
            raise ReleaseError(400, "time is HH:MM, 24-hour")
        data = json.loads(json.dumps(self.data))
        data["window"] = {"weekday": weekday, "time": time_, "tz": DEFAULT_WINDOW["tz"]}
        self._save(data)

    def public(self, projects, now):
        start, _ = next_window(self.window, now)
        # The merge cutoff still ahead: past noon on release day, that is next week's.
        cut = next(cutoff_of(self.window, d) for d in _release_days(self.window, now) if cutoff_of(self.window, d) > now)
        return {"window": dict(self.window, next=int(start), hours=WINDOW_HOURS), "cutoff": int(cut),
                "projects": {p: {"live": self.live(p)} for p in projects}}

    def hold(self, project, merged_at, now):
        """When a live deploy of a change merged at `merged_at` may run: None (now is fine), or the unix start of
        the window it waits for. A project that is not live is never held."""
        if not self.live(project):
            return None
        w = self.window
        if merged_at is None:          # nothing says when it was ready: any window that is open now will do
            start, _cut = next_window(w, now)
            return None if now >= start else start
        start, _cut = slot_for(w, merged_at)
        day = datetime.datetime.fromtimestamp(start, _tz(w)).date()
        while now >= start + WINDOW_HOURS * 3600:      # its window passed without a deploy: the next one
            day += datetime.timedelta(days=7)          # local dates, so a clock change never shifts the day
            start = window_start(w, day)
        return None if now >= start else start
