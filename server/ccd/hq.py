"""HQ next (contracts.md sections 1 to 3): milestones per project, the overnight briefing, project logos.

    milestones  per project, two tracks: `technical` (set up the backend, ship the mobile layout) and `business`
                (real-life: contact the lawyer, send the email to the client). Notes, like Messages: Jay with normal
                sign-in writes both; a project's lead (`agent:lead-<project>`, as in Messages) may add and change
                its own project's technical milestones only, and never removes one. Each project has one revision
                number that every change moves, so a reorder from a stale list is refused (409).
    briefing    "what happened while I was away": counts and the newest highlights per project for a window, from
                ccd's event log, tasks.db (the same ticket events as notify's owner and technical summaries) and the
                usage meter. Read-only; it never guesses (no meter data is null, not 0).
    logos       one image per project: PNG, JPEG or WebP, at most 512 KB, typed from its bytes (never SVG). Stored
                outside every repository (SHARE_DIR/project-logos, 0700); served only as an attachment, so a browser
                never renders it from ccd's origin. HQ shows it from a blob:, like chat images.

Storage: its own SQLite file (DATA_DIR/hq.db, 0600). No existing table changes. Events carry ids, never titles or notes.
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import time

from . import chat as chat_mod
from .onboarding import SECRET_RE

TRACKS = ("technical", "business")
STATES = ("todo", "doing", "done")
TITLE_MAX = 140
NOTE_MAX = 500
PER_TRACK_MAX = 200
ID_RE = re.compile(r"^m_[0-9a-f]{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
LOGO_MAX = 512 * 1024
LOGO_TYPES = ("image/png", "image/jpeg", "image/webp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS milestones (
  id          TEXT PRIMARY KEY,
  project     TEXT NOT NULL,
  track       TEXT NOT NULL CHECK (track IN ('technical','business')),
  title       TEXT NOT NULL,
  state       TEXT NOT NULL CHECK (state IN ('todo','doing','done')),
  due         TEXT,
  note        TEXT,
  done_at     REAL,
  created_by  TEXT NOT NULL,
  position    INTEGER NOT NULL,
  created_at  REAL NOT NULL,
  updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS milestones_project ON milestones(project, track, position);
CREATE TABLE IF NOT EXISTS milestone_revisions (
  project   TEXT PRIMARY KEY,
  revision  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS project_logos (
  project     TEXT PRIMARY KEY,
  mime        TEXT NOT NULL,
  size        INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  updated_at  REAL NOT NULL,
  updated_by  TEXT NOT NULL
);
"""


class HqError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- validation ----------

def clean_title(value):
    if not isinstance(value, str):
        raise HqError(400, "title must be a string")
    text = " ".join(value.split())
    if not 1 <= len(text) <= TITLE_MAX:
        raise HqError(400, f"a milestone title is 1 to {TITLE_MAX} characters")
    _plain(text, "title")
    return text


def clean_note(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise HqError(400, "note must be a string or null")
    text = value.replace("\r\n", "\n").strip()
    if len(text) > NOTE_MAX:
        raise HqError(400, f"a note is at most {NOTE_MAX} characters")
    _plain(text, "note")
    return text or None


def _plain(text, what):
    if not all(chat_mod.ok_text_char(c) for c in text):
        raise HqError(400, f"{what} cannot hold control characters")
    if SECRET_RE.search(text):
        raise HqError(400, f"this {what} looks like a password, token or key; never put credentials in a milestone")


def clean_due(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise HqError(400, "due is YYYY-MM-DD or null")
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise HqError(400, "due is not a real date")
    return value


def clean_track(value):
    if value not in TRACKS:
        raise HqError(400, "track is technical or business")
    return value


def clean_state(value):
    if value not in STATES:
        raise HqError(400, "state is todo, doing or done")
    return value


def sniff_logo(head):
    """The logo's type from its first bytes, or None. PNG, JPEG and WebP only (chat.IMAGE_MAGIC without GIF)."""
    for magic, mime in chat_mod.IMAGE_MAGIC:
        if head.startswith(magic) and mime in LOGO_TYPES:
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


# ---------- store ----------

class HqStore:
    """Milestones and logo metadata (DATA_DIR/hq.db) and the logo blobs (SHARE_DIR/project-logos)."""

    def __init__(self, db_path, logo_dir, clock=time.time):
        self.clock = clock
        db_path = str(db_path)
        fresh = not os.path.exists(db_path)
        self.db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        if fresh:
            os.chmod(db_path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.logo_dir = str(logo_dir)
        os.makedirs(self.logo_dir, mode=0o700, exist_ok=True)
        st = os.lstat(self.logo_dir)
        if not stat.S_ISDIR(st.st_mode):
            raise OSError(f"{self.logo_dir} is not a folder")
        os.chmod(self.logo_dir, 0o700)

    def close(self):
        self.db.close()

    # ----- milestones -----

    @staticmethod
    def _row(r):
        return {"id": r[0], "title": r[1], "state": r[2], "due": r[3], "note": r[4], "doneAt": r[5], "by": r[6]}

    _COLS = "id, title, state, due, note, done_at, created_by"

    def revision(self, project):
        row = self.db.execute("SELECT revision FROM milestone_revisions WHERE project=?", (project,)).fetchone()
        return row[0] if row else 0

    def _bump(self, project):
        self.db.execute("INSERT INTO milestone_revisions(project, revision) VALUES (?, 1) "
                        "ON CONFLICT(project) DO UPDATE SET revision = revision + 1", (project,))
        return self.revision(project)

    def track(self, project, track):
        return [self._row(r) for r in self.db.execute(
            f"SELECT {self._COLS} FROM milestones WHERE project=? AND track=? ORDER BY position, created_at",
            (project, track))]

    def all(self, projects):
        return {p: {"technical": self.track(p, "technical"), "business": self.track(p, "business"),
                    "revision": self.revision(p)} for p in projects}

    def get(self, project, mid):
        if not isinstance(mid, str) or not ID_RE.match(mid):
            raise HqError(404, "no such milestone")
        row = self.db.execute(f"SELECT {self._COLS}, track FROM milestones WHERE project=? AND id=?",
                              (project, mid)).fetchone()
        if not row:
            raise HqError(404, "no such milestone")
        return dict(self._row(row), track=row[7])

    def add(self, project, track, title, due, note, actor):
        now = self.clock()
        mid = "m_" + secrets.token_hex(6)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            n, top = self.db.execute("SELECT COUNT(*), COALESCE(MAX(position), -1) FROM milestones "
                                     "WHERE project=? AND track=?", (project, track)).fetchone()
            if n >= PER_TRACK_MAX:
                raise HqError(409, f"at most {PER_TRACK_MAX} {track} milestones per project")
            self.db.execute("INSERT INTO milestones(id, project, track, title, state, due, note, done_at, created_by, "
                            "position, created_at, updated_at) VALUES (?,?,?,?,'todo',?,?,NULL,?,?,?,?)",
                            (mid, project, track, title, due, note, actor, top + 1, now, now))
            rev = self._bump(project)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return dict(self.get(project, mid)), rev

    def update(self, project, mid, fields):
        """fields: any of title, state, due, note (already clean). Returns (milestone with track, previous state,
        revision)."""
        now = self.clock()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.get(project, mid)
            sets, args = [], []
            for col in ("title", "state", "due", "note"):
                if col in fields:
                    sets.append(f"{col}=?")
                    args.append(fields[col])
            if "state" in fields and fields["state"] != cur["state"]:
                sets.append("done_at=?")
                args.append(now if fields["state"] == "done" else None)
            sets.append("updated_at=?")
            args += [now, project, mid]
            self.db.execute(f"UPDATE milestones SET {', '.join(sets)} WHERE project=? AND id=?", args)
            rev = self._bump(project)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(project, mid), cur["state"], rev

    def remove(self, project, mid):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.get(project, mid)
            self.db.execute("DELETE FROM milestones WHERE project=? AND id=?", (project, mid))
            rev = self._bump(project)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return cur, rev

    def reorder(self, project, track, ids, revision):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if revision != self.revision(project):
                raise HqError(409, "the milestones changed since you loaded them; reload and try again")
            have = [m["id"] for m in self.track(project, track)]
            if len(ids) != len(have) or set(ids) != set(have):
                raise HqError(400, f"ids must list every {track} milestone of {project} exactly once")
            for pos, mid in enumerate(ids):
                self.db.execute("UPDATE milestones SET position=? WHERE project=? AND id=?", (pos, project, mid))
            rev = self._bump(project)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return rev

    # ----- logos -----

    def _logo_path(self, project):
        if not PROJECT_RE.match(project):
            raise HqError(404, "no such project")
        return os.path.join(self.logo_dir, project)

    def logos(self):
        return {r[0]: {"mime": r[1], "sha256": r[2], "updatedAt": r[3]} for r in self.db.execute(
            "SELECT project, mime, sha256, updated_at FROM project_logos ORDER BY project")}

    def logo_meta(self, project):
        row = self.db.execute("SELECT mime, size, sha256, updated_at FROM project_logos WHERE project=?",
                              (project,)).fetchone()
        return {"mime": row[0], "size": row[1], "sha256": row[2], "updatedAt": row[3]} if row else None

    async def put_logo(self, project, chunks, actor, length=None):
        if length is not None and length > LOGO_MAX:
            raise HqError(413, "a logo is at most 512 KB")
        path = self._logo_path(project)
        data = bytearray()
        async for chunk in chunks:
            data += chunk
            if len(data) > LOGO_MAX:
                raise HqError(413, "a logo is at most 512 KB")
        mime = sniff_logo(bytes(data[:16]))
        if mime is None:
            raise HqError(415, "a logo is a PNG, JPEG or WebP image (read from its bytes; never SVG)")
        sha = hashlib.sha256(data).hexdigest()
        tmp = os.path.join(self.logo_dir, f".{project}.{secrets.token_hex(6)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        now = self.clock()
        self.db.execute("INSERT INTO project_logos(project, mime, size, sha256, updated_at, updated_by) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT(project) DO UPDATE SET mime=excluded.mime, "
                        "size=excluded.size, sha256=excluded.sha256, updated_at=excluded.updated_at, "
                        "updated_by=excluded.updated_by", (project, mime, len(data), sha, now, actor))
        return {"ok": True, "mime": mime, "sha256": sha, "updatedAt": now}

    def open_logo(self, project):
        """(fd, meta) for reading, or HqError 404. The fd is opened without following links."""
        meta = self.logo_meta(project)
        if meta is None:
            raise HqError(404, "this project has no logo")
        try:
            fd = os.open(self._logo_path(project), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            raise HqError(404, "this project has no logo")
        size = os.fstat(fd).st_size
        return fd, dict(meta, size=size)

    def remove_logo(self, project):
        path = self._logo_path(project)
        had = self.db.execute("DELETE FROM project_logos WHERE project=?", (project,)).rowcount
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return bool(had)


# ---------- briefing ----------

BRIEFING_DEFAULT = 12 * 3600
HIGHLIGHTS_MAX = 8
# Pipeline steps worth a line in the briefing (task.pipeline events, by their data.kind), and the short label a client
# project's highlight carries instead of ccd's wording.
PIPELINE_HIGHLIGHTS = {
    "pipeline.merged": "merged", "pipeline.auto_merged": "merged", "pipeline.deployed": "deployed",
    "pipeline.done": "done", "pipeline.gate_opened": "waiting on you", "pipeline.questions": "questions for you",
    "pipeline.answered": "answered", "pipeline.blocked": "blocked", "pipeline.auto_merge_failed": "merge failed",
    "pipeline.deploy_requested": "deploy waiting on you", "pipeline.replan": "back to planning",
}
EVENT_HIGHLIGHTS = {"pr.opened": "PR opened", "pr.closed": "PR closed", "pr.ci_changed": "checks failing",
                    "ci.main_changed": "main checks changed", "chat.reply": "lead replied",
                    "milestone.done": "milestone done"}
FAILING = "✗"


def _empty_counts():
    return {"merged": 0, "done": 0, "failedChecks": 0, "opened": 0, "questionsAsked": 0, "questionsAnswered": 0,
            "deploys": 0, "needsYou": 0}


class HqDaemon:
    """Daemon mixin: the HTTP-facing side of milestones, briefing and logos. `self.hq` is an HqStore (set by
    __main__; None = off, 503)."""

    hq = None

    def _need_hq(self, project=None):
        from .daemon import ActionError
        if self.hq is None:
            raise ActionError(503, "milestones and logos are not configured")
        if project is not None and self._project(project) is None:
            raise ActionError(404, "no such project")

    @staticmethod
    def _hq(fn, *a, **kw):
        from .daemon import ActionError
        try:
            return fn(*a, **kw)
        except HqError as e:
            raise ActionError(e.status, e.message)

    # ----- milestones -----

    def _milestone_writer(self, project, actor, track, verb):
        """jay writes both tracks. The project's own lead (agent:lead-<project>) adds and changes technical ones."""
        from .daemon import ActionError
        if actor == "jay":
            return
        if actor == f"agent:lead-{project}" and verb in ("add", "change") and track == "technical":
            return
        if actor == f"agent:lead-{project}":
            raise ActionError(403, "a lead adds and changes its own project's technical milestones only; "
                                   "business milestones, removing and reordering are Jay's")
        raise ActionError(403, f"only Jay or agent:lead-{project} writes {project}'s milestones")

    def _milestone_event(self, kind, project, m, track, state=None):
        word = kind.split(".", 1)[1]
        self._event("milestones", kind, f"{project}: {track} milestone {word}", project=project,
                    data={"id": m["id"] if m else None, "track": track, "state": state})

    def milestones_state(self):
        self._need_hq()
        return {"projects": self.hq.all([p["key"] for p in self._projects()])}

    def milestone_add(self, project, body, actor):
        from .daemon import ActionError
        self._need_hq(project)
        track = self._hq(clean_track, body.get("track"))
        self._milestone_writer(project, actor, track, "add")
        title = self._hq(clean_title, body.get("title"))
        due = self._hq(clean_due, body.get("due"))
        note = self._hq(clean_note, body.get("note"))
        unknown = set(body) - {"track", "title", "due", "note"}
        if unknown:
            raise ActionError(400, f"unknown field: {sorted(unknown)[0]}")
        m, rev = self._hq(self.hq.add, project, track, title, due, note, actor)
        self._milestone_event("milestone.added", project, m, track, m["state"])
        m.pop("track", None)
        return {"milestone": m, "revision": rev}

    def milestone_update(self, project, mid, body, actor):
        from .daemon import ActionError
        self._need_hq(project)
        cur = self._hq(self.hq.get, project, mid)
        self._milestone_writer(project, actor, cur["track"], "change")
        unknown = set(body) - {"title", "state", "due", "note"}
        if unknown:
            raise ActionError(400, f"unknown field: {sorted(unknown)[0]}")
        fields = {}
        if "title" in body:
            fields["title"] = self._hq(clean_title, body["title"])
        if "state" in body:
            fields["state"] = self._hq(clean_state, body["state"])
        if "due" in body:
            fields["due"] = self._hq(clean_due, body["due"])
        if "note" in body:
            fields["note"] = self._hq(clean_note, body["note"])
        if not fields:
            raise ActionError(400, "nothing to change: send title, state, due or note")
        m, before, rev = self._hq(self.hq.update, project, mid, fields)
        done = m["state"] == "done" and before != "done"
        self._milestone_event("milestone.done" if done else "milestone.changed", project, m, m["track"], m["state"])
        m.pop("track", None)
        return {"milestone": m, "revision": rev}

    def milestone_remove(self, project, mid, actor):
        self._need_hq(project)
        cur = self._hq(self.hq.get, project, mid)
        self._milestone_writer(project, actor, cur["track"], "remove")
        m, rev = self._hq(self.hq.remove, project, mid)
        self._milestone_event("milestone.removed", project, m, m["track"], m["state"])
        return {"ok": True, "revision": rev}

    def milestone_order(self, project, body, actor):
        from .daemon import ActionError
        self._need_hq(project)
        track = self._hq(clean_track, body.get("track"))
        self._milestone_writer(project, actor, track, "order")
        ids, rev = body.get("ids"), body.get("revision")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) > PER_TRACK_MAX:
            raise ActionError(400, "ids must be a list of milestone ids")
        if not isinstance(rev, int) or isinstance(rev, bool):
            raise ActionError(400, "revision must be the number GET /api/milestones gave")
        new = self._hq(self.hq.reorder, project, track, ids, rev)
        self._milestone_event("milestone.changed", project, None, track)
        return {"revision": new}

    # ----- logos -----

    async def logo_put(self, project, chunks, actor, length=None):
        from .daemon import ActionError
        self._need_hq(project)
        try:
            out = await self.hq.put_logo(project, chunks, actor, length=length)
        except HqError as e:
            raise ActionError(e.status, e.message)
        self._event("hq", "logo.changed", f"{project}: logo changed", project=project)
        return out

    def logo_open(self, project):
        self._need_hq(project)
        return self._hq(self.hq.open_logo, project)

    def logo_remove(self, project):
        from .daemon import ActionError
        self._need_hq(project)
        if not self._hq(self.hq.remove_logo, project):
            raise ActionError(404, "this project has no logo")
        self._event("hq", "logo.removed", f"{project}: logo removed", project=project)
        return {"ok": True}

    def logos_state(self):
        self._need_hq()
        return self.hq.logos()

    # ----- briefing -----

    def briefing(self, since=None, now=None):
        """GET /api/briefing. The window is [since, now); since defaults to 12 hours ago and is clamped to the event
        log's retention (nothing older is kept to count)."""
        now = time.time() if now is None else now
        keep = int((self.cfg or {}).get("retention_days") or 30) * 86400
        since = now - BRIEFING_DEFAULT if since is None else since
        since = min(max(since, now - keep), now)
        projects = self._projects()
        keys = [p["key"] for p in projects]
        counts = {k: _empty_counts() for k in keys}
        highlights = {k: [] for k in keys}

        # Tickets (tasks.db): the same pipeline events as notify's summaries, plus questions asked and answered.
        tasks = getattr(self, "tasks", None)
        if tasks is not None:
            seen = {}
            for proj, key, kind, field, to in tasks.db.execute(
                    "SELECT t.project, t.key, e.kind, e.field, e.to_value FROM ticket_events e "
                    "JOIN tickets t ON t.id=e.ticket_id WHERE e.at >= ? AND e.at < ? AND (e.kind IN "
                    "('pipeline.merged','pipeline.auto_merged','pipeline.deployed','pipeline.done') "
                    "OR (e.field='status' AND e.to_value='DONE'))", (since, now)):
                if proj not in counts:
                    continue
                what = {"pipeline.merged": "merged", "pipeline.auto_merged": "merged",
                        "pipeline.deployed": "deploys"}.get(kind, "done")
                seen.setdefault((proj, what), set()).add(key)
            for (proj, what), ks in seen.items():
                counts[proj][what] = len(ks)
            for proj, asked, answered in tasks.db.execute(
                    "SELECT t.project, SUM(q.asked_at >= ? AND q.asked_at < ?), "
                    "SUM(q.answered_at IS NOT NULL AND q.answered_at >= ? AND q.answered_at < ?) "
                    "FROM ticket_questions q JOIN tickets t ON t.id=q.ticket_id "
                    "WHERE (q.asked_at >= ? AND q.asked_at < ?) OR (q.answered_at >= ? AND q.answered_at < ?) "
                    "GROUP BY t.project", (since, now) * 4):
                if proj in counts:
                    counts[proj]["questionsAsked"] = asked or 0
                    counts[proj]["questionsAnswered"] = answered or 0

        # The event log (ccd.db): PRs opened, checks that went red, and the highlights.
        for _seq, at, kind, proj, ref, text, data in self.store.db.execute(
                "SELECT seq, at, kind, project, ref, text, data FROM events WHERE at >= ? AND at < ? AND "
                "project IS NOT NULL AND kind IN ('task.pipeline','pr.opened','pr.closed','pr.ci_changed',"
                "'ci.main_changed','chat.reply','milestone.done') ORDER BY seq DESC LIMIT 20000", (since, now)):
            if proj not in counts:
                continue
            try:
                data = json.loads(data or "{}")
            except ValueError:
                data = {}
            if kind == "pr.opened":
                counts[proj]["opened"] += 1
            failing = kind in ("pr.ci_changed", "ci.main_changed") and data.get("to") == FAILING
            if failing:
                counts[proj]["failedChecks"] += 1
            if kind == "task.pipeline":
                label = PIPELINE_HIGHLIGHTS.get(data.get("kind"))
                hkind = data.get("kind")
            elif kind == "pr.ci_changed":
                label, hkind = (EVENT_HIGHLIGHTS[kind] if failing else None), kind
            else:
                label, hkind = EVENT_HIGHLIGHTS.get(kind), kind
            if label is None or len(highlights[proj]) >= HIGHLIGHTS_MAX:
                continue
            highlights[proj].append({"at": at, "kind": hkind, "text": text, "ref": ref, "_label": label})

        # Now: what waits on Jay, main checks, and spend in the window.
        st = self.state()
        for n in list(st.get("needs") or []) + list(st.get("blocked") or []):
            if n.get("project") in counts:
                counts[n["project"]]["needsYou"] += 1
        main = {v.get("key"): v.get("main_ci") for v in st.get("projects") or []}
        spend = self._briefing_spend(since, now)
        clients = set(self._client_projects())

        out, totals = [], _empty_counts()
        for p in projects:
            k = p["key"]
            hl = []
            for h in highlights[k]:
                label = h.pop("_label")
                if k in clients:
                    h["text"] = f"{h['ref'] or k} · {label}"
                hl.append(h)
            mark = main.get(k)
            row = {"key": k, "name": p.get("name") or k, **counts[k],
                   "mainChecks": "passing" if mark == "✓" else "failing" if mark == FAILING else "unknown",
                   "spendUsd": spend.get(k) if spend is not None else None, "highlights": hl}
            for c in totals:
                totals[c] += counts[k][c]
            out.append(row)
        happened = any(totals[c] for c in totals if c != "needsYou") or any(r["highlights"] for r in out)
        return {"since": since, "until": now, "totals": totals, "projects": out, "quiet": not happened}

    def _client_projects(self):
        n = getattr(self, "notifier", None)
        if n is not None:
            return list(n.conf.get("client_projects") or [])
        ncfg = ((self.cfg or {}).get("notify") or {}).get("slack") or {}
        return list(ncfg.get("client_projects") or ["gauzemate"])

    def _briefing_spend(self, since, now):
        """{project: USD} measured in the window, or None when the meter has never read a log (no data is not 0).
        A project whose replies in the window are all unpriced is None too."""
        meter = getattr(self, "meter", None)
        if meter is None or getattr(self, "meter_read_at", None) is None:
            return None
        out = {}
        for proj, cost, priced in meter.db.execute(
                "SELECT project, SUM(cost_usd), SUM(cost_usd IS NOT NULL) FROM usage_records WHERE at >= ? AND at < ? "
                "AND source != 'reported' AND project IS NOT NULL GROUP BY project", (since, now)):
            out[proj] = round(cost, 4) if priced else None
        return {p["key"]: out.get(p["key"], 0.0) for p in self._projects()}
