"""Tickets: Command Center's own task system. Durable product data.

Lives in its own SQLite file (`tasks.db`), apart from `ccd.db`:

    ccd.db    operational: event log (pruned after 30 days), caches, alerts
    tasks.db  product: tickets, comments, relations, links, the audit trail

Losing ccd.db costs a little history; losing tasks.db loses Jay's work, so it
is never pruned, migrated only forward, and backed up as data.

Rules the schema enforces, not just the code:

  * a ticket key (SV-056) is allocated once from its project's counter and is
    never reused: tickets cannot be deleted (archive instead) and a ticket's
    project, number and key cannot change
  * every mutation writes a `ticket_events` row in the same transaction, so the
    history of a ticket can be rebuilt from its events alone
  * GitHub is an integration, not the model: a PR is a row in `ticket_links`
    (provider, kind, ref), so another forge can be added without touching
    tickets

One writer (the daemon's event loop). Reads are cheap enough to run per request.
"""
import json
import re
import sqlite3
import time

STATUSES = ("INBOX", "PROPOSED", "RESEARCHING", "READY_TO_IMPLEMENT", "IN_PROGRESS", "IN_REVIEW",
            "READY_TO_MERGE", "VERIFYING", "DONE")
OFF_PIPELINE = ("BLOCKED", "DENIED", "CANCELLED")
ALL_STATUSES = STATUSES + OFF_PIPELINE
CLOSED = ("DONE", "DENIED", "CANCELLED")
PRIORITIES = ("NO_PRIORITY", "URGENT", "HIGH", "MEDIUM", "LOW")
DEFAULT_TYPES = ("FEATURE", "BUG", "SECURITY", "INFRA", "DESIGN", "RESEARCH", "DOCS", "MAINTENANCE", "LEGAL",
                 "OWNER_ACTION")
ROLES = ("COORDINATOR", "PLANNER", "IMPLEMENTER", "REVIEWER", "VERIFIER")
FLAGS = ("needs_jay", "needs_legal", "needs_ui_review", "needs_deploy")
FLAG_LABEL = {"needs_jay": "needs:jay", "needs_legal": "needs:legal", "needs_ui_review": "needs:ui-review",
              "needs_deploy": "needs:deploy"}
RELATION_KINDS = ("blocks", "related", "duplicates")  # "blocked_by" is the inverse view of "blocks"
LINK_PROVIDERS = ("github", "legacy", "url")

# Fields a PATCH may change, and how each is checked. Everything else is read-only.
TEXT_FIELDS = {"title": 300, "description": 20000, "branch": 200}
DEFAULT_PREFIXES = {"samvision": "SV", "gauzemate": "GM", "gyst": "GYST", "mfe": "MFE", "commandcenter": "CC"}
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
KEY_RE = re.compile(r"^([A-Z][A-Z0-9]{1,5})-(\d{1,6})$")
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9:._/-]{0,39}$")
ACTOR_RE = re.compile(r"^(jay|system:[a-z0-9_-]{1,32}|agent:[a-z0-9_:-]{1,64})$")


class TaskError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _q(values):
    return ",".join(f"'{v}'" for v in values)


# Forward-only migrations. Each runs in one transaction with its version bump,
# so a crash leaves the database at the previous version, never half-applied.
MIGRATIONS = [
    (1, f"""
CREATE TABLE task_projects (
  key         TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  prefix      TEXT NOT NULL UNIQUE,
  next_number INTEGER NOT NULL DEFAULT 1 CHECK (next_number >= 1),
  created_at  REAL NOT NULL
);
CREATE TABLE ticket_types (
  name     TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tickets (
  id               INTEGER PRIMARY KEY,
  project          TEXT NOT NULL REFERENCES task_projects(key),
  number           INTEGER NOT NULL CHECK (number >= 1),
  key              TEXT NOT NULL UNIQUE,
  title            TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
  description      TEXT NOT NULL DEFAULT '',
  status           TEXT NOT NULL CHECK (status IN ({_q(ALL_STATUSES)})),
  priority         TEXT NOT NULL DEFAULT 'NO_PRIORITY' CHECK (priority IN ({_q(PRIORITIES)})),
  type             TEXT REFERENCES ticket_types(name),
  creator          TEXT NOT NULL,
  assignee_kind    TEXT CHECK (assignee_kind IN ('jay', 'role', 'agent')),
  assignee_ref     TEXT,
  agent_role       TEXT CHECK (agent_role IS NULL OR agent_role IN ({_q(ROLES)})),
  agent_pane_id    TEXT,
  agent_session_id TEXT,
  parent_id        INTEGER REFERENCES tickets(id),
  branch           TEXT,
  cycle_id         INTEGER,            -- reserved for a future Cycle; unused in V1
  created_at       REAL NOT NULL,
  updated_at       REAL NOT NULL,
  started_at       REAL,
  completed_at     REAL,
  due_at           REAL,
  estimate         REAL,
  needs_jay        INTEGER NOT NULL DEFAULT 0 CHECK (needs_jay IN (0, 1)),
  needs_legal      INTEGER NOT NULL DEFAULT 0 CHECK (needs_legal IN (0, 1)),
  needs_ui_review  INTEGER NOT NULL DEFAULT 0 CHECK (needs_ui_review IN (0, 1)),
  needs_deploy     INTEGER NOT NULL DEFAULT 0 CHECK (needs_deploy IN (0, 1)),
  archived         INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
  UNIQUE (project, number),
  CHECK ((assignee_kind IS NULL) = (assignee_ref IS NULL)),
  CHECK (parent_id IS NULL OR parent_id != id)
);
CREATE INDEX tickets_project_status ON tickets(project, status);
CREATE INDEX tickets_parent ON tickets(parent_id);
CREATE INDEX tickets_updated ON tickets(updated_at);
CREATE TRIGGER tickets_never_deleted BEFORE DELETE ON tickets
  BEGIN SELECT RAISE(ABORT, 'tickets are archived, never deleted'); END;
CREATE TRIGGER tickets_identity_fixed BEFORE UPDATE OF project, number, key ON tickets
  WHEN NEW.project != OLD.project OR NEW.number != OLD.number OR NEW.key != OLD.key
  BEGIN SELECT RAISE(ABORT, 'a ticket key never changes'); END;
CREATE TRIGGER task_projects_counter_forward BEFORE UPDATE OF next_number, prefix ON task_projects
  WHEN NEW.next_number < OLD.next_number OR NEW.prefix != OLD.prefix
  BEGIN SELECT RAISE(ABORT, 'ticket numbers are never recycled'); END;

CREATE TABLE ticket_labels (
  ticket_id INTEGER NOT NULL REFERENCES tickets(id),
  label     TEXT NOT NULL,
  PRIMARY KEY (ticket_id, label)
);
CREATE TABLE ticket_relations (
  id         INTEGER PRIMARY KEY,
  src_id     INTEGER NOT NULL REFERENCES tickets(id),
  dst_id     INTEGER NOT NULL REFERENCES tickets(id),
  kind       TEXT NOT NULL CHECK (kind IN ({_q(RELATION_KINDS)})),
  created_at REAL NOT NULL,
  UNIQUE (src_id, dst_id, kind),
  CHECK (src_id != dst_id)
);
CREATE INDEX ticket_relations_dst ON ticket_relations(dst_id);
CREATE TABLE ticket_comments (
  id         INTEGER PRIMARY KEY,
  ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
  author     TEXT NOT NULL,
  body       TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 20000),
  created_at REAL NOT NULL
);
CREATE INDEX ticket_comments_ticket ON ticket_comments(ticket_id, id);
CREATE TABLE ticket_links (
  id         INTEGER PRIMARY KEY,
  ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
  provider   TEXT NOT NULL,
  kind       TEXT NOT NULL,
  ref        TEXT NOT NULL,
  url        TEXT,
  title      TEXT,
  created_at REAL NOT NULL,
  created_by TEXT NOT NULL,
  UNIQUE (ticket_id, provider, kind, ref)
);
CREATE INDEX ticket_links_ref ON ticket_links(provider, kind, ref);
CREATE TABLE ticket_events (
  id         INTEGER PRIMARY KEY,
  ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
  at         REAL NOT NULL,
  actor      TEXT NOT NULL,
  kind       TEXT NOT NULL,
  field      TEXT,
  from_value TEXT,
  to_value   TEXT,
  trigger    TEXT,
  data       TEXT NOT NULL DEFAULT '{{}}'
);
CREATE INDEX ticket_events_ticket ON ticket_events(ticket_id, id);
CREATE TRIGGER ticket_events_append_only_u BEFORE UPDATE ON ticket_events
  BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only'); END;
CREATE TRIGGER ticket_events_append_only_d BEFORE DELETE ON ticket_events
  BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only'); END;
"""),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def migrate(db):
    """Apply every migration newer than the file's user_version. Returns the versions applied."""
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"tasks.db is schema v{current}, newer than this ccd (v{SCHEMA_VERSION}); refusing to run")
    applied = []
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        db.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        applied.append(version)
    return applied


def _now():
    return time.time()


def _actor(actor):
    actor = str(actor or "")
    if not ACTOR_RE.match(actor):
        raise TaskError(400, "actor must be jay, system:<name> or agent:<name>")
    return actor


def _printable(text, limit, field, multiline=False):
    if not isinstance(text, str):
        raise TaskError(400, f"{field} must be text")
    bad = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]" if multiline else r"[\x00-\x1f\x7f]"
    if re.search(bad, text):
        raise TaskError(400, f"{field} has control characters")
    if len(text) > limit:
        raise TaskError(400, f"{field} is longer than {limit} characters")
    return text


def parse_assignee(value):
    """'jay' | 'role:IMPLEMENTER' | 'agent:<name or pane id>' | None → (kind, ref)."""
    if value in (None, ""):
        return None, None
    if not isinstance(value, str):
        raise TaskError(400, "assignee must be jay, role:<ROLE>, agent:<name> or null")
    if value == "jay":
        return "jay", "jay"
    kind, _, ref = value.partition(":")
    if kind == "role" and ref in ROLES:
        return "role", ref
    if kind == "agent" and re.match(r"^[A-Za-z0-9_:.-]{1,64}$", ref or ""):
        return "agent", ref
    raise TaskError(400, f"assignee must be jay, role:<{'|'.join(ROLES)}>, agent:<name> or null")


def assignee_str(kind, ref):
    if kind is None:
        return None
    return "jay" if kind == "jay" else f"{kind}:{ref}"


class TaskStore:
    def __init__(self, path, projects=()):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")  # product data: durability over speed
        self.db.execute("PRAGMA foreign_keys=ON")
        self.applied = migrate(self.db)
        self.last_change = None
        self._seed_types()
        self.sync_projects(projects)

    def close(self):
        self.db.close()

    # ---------- projects and types ----------

    def _seed_types(self):
        for i, t in enumerate(DEFAULT_TYPES):
            self.db.execute("INSERT OR IGNORE INTO ticket_types(name, position) VALUES (?, ?)", (t, i))

    def sync_projects(self, projects):
        """Register projects. An existing project's prefix never changes (keys depend on it)."""
        for p in projects:
            key = p["key"]
            prefix = (p.get("prefix") or DEFAULT_PREFIXES.get(key) or re.sub(r"[^A-Z0-9]", "", key.upper())[:6])
            if not PREFIX_RE.match(prefix):
                raise ValueError(f"bad ticket prefix {prefix!r} for {key}")
            self.db.execute("INSERT OR IGNORE INTO task_projects(key, name, prefix, created_at) VALUES (?,?,?,?)",
                            (key, p.get("name") or key, prefix, _now()))

    def projects(self):
        rows = self.db.execute("SELECT key, name, prefix, next_number FROM task_projects ORDER BY key").fetchall()
        return [{"key": r[0], "name": r[1], "prefix": r[2], "nextNumber": r[3]} for r in rows]

    def types(self):
        return [r[0] for r in self.db.execute("SELECT name FROM ticket_types WHERE archived=0 ORDER BY position")]

    def prefixes(self):
        return {r[0]: r[1] for r in self.db.execute("SELECT prefix, key FROM task_projects")}

    def meta(self):
        return {"statuses": list(STATUSES), "offPipeline": list(OFF_PIPELINE), "priorities": list(PRIORITIES),
                "types": self.types(), "roles": list(ROLES), "flags": list(FLAGS),
                "relationKinds": list(RELATION_KINDS) + ["blocked_by"], "schemaVersion": SCHEMA_VERSION}

    # ---------- reading ----------

    _COLS = ("id, project, number, key, title, description, status, priority, type, creator, assignee_kind, "
             "assignee_ref, agent_role, agent_pane_id, agent_session_id, parent_id, branch, created_at, updated_at, "
             "started_at, completed_at, due_at, estimate, needs_jay, needs_legal, needs_ui_review, needs_deploy, "
             "archived")

    def _row(self, r, keys_by_id=None):
        t = dict(zip([c.strip() for c in self._COLS.split(",")], r))
        parent_key = None
        if t["parent_id"]:
            parent_key = (keys_by_id or {}).get(t["parent_id"]) or self._key_of(t["parent_id"])
        return {
            "id": t["id"], "key": t["key"], "project": t["project"], "number": t["number"],
            "title": t["title"], "description": t["description"], "status": t["status"],
            "priority": t["priority"], "type": t["type"], "creator": t["creator"],
            "assignee": assignee_str(t["assignee_kind"], t["assignee_ref"]),
            "agentRole": t["agent_role"], "agentPaneId": t["agent_pane_id"], "agentSessionId": t["agent_session_id"],
            "parent": parent_key, "branch": t["branch"],
            "createdAt": t["created_at"], "updatedAt": t["updated_at"], "startedAt": t["started_at"],
            "completedAt": t["completed_at"], "dueAt": t["due_at"], "estimate": t["estimate"],
            "flags": [f for f in FLAGS if t[f]], "archived": bool(t["archived"]),
        }

    def _key_of(self, ticket_id):
        row = self.db.execute("SELECT key FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return row[0] if row else None

    def _id_of(self, key):
        row = self.db.execute("SELECT id FROM tickets WHERE key=?", (str(key or "").upper(),)).fetchone()
        if not row:
            raise TaskError(404, f"no ticket {key}")
        return row[0]

    def exists(self, key):
        return self.db.execute("SELECT 1 FROM tickets WHERE key=?", (str(key or "").upper(),)).fetchone() is not None

    def list(self, project=None, include_archived=False):
        """Every ticket, compact: what the table, board and filters need. No descriptions."""
        q = f"SELECT {self._COLS} FROM tickets WHERE 1=1"
        args = []
        if project:
            q += " AND project=?"
            args.append(project)
        if not include_archived:
            q += " AND archived=0"
        rows = self.db.execute(q + " ORDER BY updated_at DESC", args).fetchall()
        keys_by_id = dict(self.db.execute("SELECT id, key FROM tickets").fetchall())
        labels, links, rel, subs = self._labels_all(), self._links_all(), self._relations_all(), self._subtask_counts()
        out = []
        for r in rows:
            t = self._row(r, keys_by_id)
            t.pop("description")
            tid = t["id"]
            t["labels"] = labels.get(tid, [])
            t["links"] = links.get(tid, [])
            pr = next((l for l in reversed(t["links"]) if l["kind"] == "pr"), None)
            t["prNumber"], t["prUrl"] = (pr["number"], pr["url"]) if pr else (None, None)
            t["blockedBy"] = [keys_by_id[s] for s, d, k in rel if k == "blocks" and d == tid]
            t["blocks"] = [keys_by_id[d] for s, d, k in rel if k == "blocks" and s == tid]
            t["subtasks"] = subs.get(tid, {"total": 0, "done": 0})
            out.append(t)
        return out

    def _labels_all(self):
        out = {}
        for tid, label in self.db.execute("SELECT ticket_id, label FROM ticket_labels ORDER BY label"):
            out.setdefault(tid, []).append(label)
        return out

    @staticmethod
    def _link(r):
        provider, kind, ref, url, title, at, by = r
        num = None
        if kind == "pr" and "#" in ref:
            tail = ref.rsplit("#", 1)[1]
            num = int(tail) if tail.isdigit() else None
        return {"provider": provider, "kind": kind, "ref": ref, "url": url, "title": title, "number": num,
                "createdAt": at, "createdBy": by}

    def _links_all(self):
        out = {}
        for r in self.db.execute("SELECT ticket_id, provider, kind, ref, url, title, created_at, created_by "
                                 "FROM ticket_links ORDER BY id"):
            out.setdefault(r[0], []).append(self._link(r[1:]))
        return out

    def _relations_all(self):
        return self.db.execute("SELECT src_id, dst_id, kind FROM ticket_relations").fetchall()

    def _subtask_counts(self):
        out = {}
        for pid, status in self.db.execute("SELECT parent_id, status FROM tickets WHERE parent_id IS NOT NULL "
                                           "AND archived=0"):
            c = out.setdefault(pid, {"total": 0, "done": 0})
            c["total"] += 1
            c["done"] += status in CLOSED
        return out

    def get(self, key):
        """One ticket with everything: relations, subtasks, links, comments and its timeline."""
        tid = self._id_of(key)
        t = self._row(self.db.execute(f"SELECT {self._COLS} FROM tickets WHERE id=?", (tid,)).fetchone())
        t["labels"] = [r[0] for r in self.db.execute("SELECT label FROM ticket_labels WHERE ticket_id=? ORDER BY label",
                                                     (tid,))]
        t["links"] = [self._link(r) for r in self.db.execute(
            "SELECT provider, kind, ref, url, title, created_at, created_by FROM ticket_links WHERE ticket_id=? "
            "ORDER BY id", (tid,))]
        pr = next((l for l in reversed(t["links"]) if l["kind"] == "pr"), None)
        t["prNumber"], t["prUrl"] = (pr["number"], pr["url"]) if pr else (None, None)
        rel = {"blocks": [], "blocked_by": [], "related": [], "duplicates": [], "duplicated_by": []}
        for s, d, kind, k_s, k_d, t_s, t_d, st_s, st_d in self.db.execute(
                "SELECT r.src_id, r.dst_id, r.kind, a.key, b.key, a.title, b.title, a.status, b.status "
                "FROM ticket_relations r JOIN tickets a ON a.id=r.src_id JOIN tickets b ON b.id=r.dst_id "
                "WHERE r.src_id=? OR r.dst_id=? ORDER BY r.id", (tid, tid)):
            outgoing = s == tid
            other = {"key": k_d if outgoing else k_s, "title": t_d if outgoing else t_s,
                     "status": st_d if outgoing else st_s}
            if kind == "blocks":
                rel["blocks" if outgoing else "blocked_by"].append(other)
            elif kind == "duplicates":
                rel["duplicates" if outgoing else "duplicated_by"].append(other)
            else:
                rel["related"].append(other)
        t["relations"] = rel
        t["blocks"] = [r["key"] for r in rel["blocks"]]
        t["blockedBy"] = [r["key"] for r in rel["blocked_by"]]
        t["subtaskList"] = [{"key": r[0], "title": r[1], "status": r[2], "assignee": assignee_str(r[3], r[4])}
                            for r in self.db.execute(
                                "SELECT key, title, status, assignee_kind, assignee_ref FROM tickets "
                                "WHERE parent_id=? AND archived=0 ORDER BY number", (tid,))]
        t["subtasks"] = {"total": len(t["subtaskList"]),
                         "done": sum(1 for s in t["subtaskList"] if s["status"] in CLOSED)}
        t["comments"] = [{"id": r[0], "author": r[1], "body": r[2], "at": r[3]} for r in self.db.execute(
            "SELECT id, author, body, created_at FROM ticket_comments WHERE ticket_id=? ORDER BY id", (tid,))]
        t["timeline"] = self.timeline(tid)
        return t

    def timeline(self, tid, limit=500):
        return [{"id": r[0], "at": r[1], "actor": r[2], "kind": r[3], "field": r[4], "from": r[5], "to": r[6],
                 "trigger": r[7], "data": json.loads(r[8] or "{}")}
                for r in self.db.execute(
                    "SELECT id, at, actor, kind, field, from_value, to_value, trigger, data FROM ticket_events "
                    "WHERE ticket_id=? ORDER BY id LIMIT ?", (tid, limit))]

    def needs(self):
        """Open tickets that wait on Jay: any needs flag, or assigned to Jay and not closed."""
        rows = self.db.execute(
            "SELECT key, project, title, status, needs_jay, needs_legal, needs_ui_review, needs_deploy, "
            "assignee_kind, updated_at FROM tickets WHERE archived=0 AND status NOT IN ('DONE','DENIED','CANCELLED') "
            "AND (needs_jay=1 OR needs_legal=1 OR needs_ui_review=1 OR needs_deploy=1) ORDER BY updated_at").fetchall()
        out = []
        for key, project, title, status, nj, nl, nu, nd, _ak, at in rows:
            flags = [f for f, on in zip(FLAGS, (nj, nl, nu, nd)) if on]
            out.append({"project": project, "ref": key, "text": title, "kind": "ticket", "url": None,
                        "flags": flags, "status": status, "since": at})
        return out

    def counts(self):
        rows = self.db.execute("SELECT status, COUNT(*) FROM tickets WHERE archived=0 GROUP BY status").fetchall()
        return {s: n for s, n in rows}

    def find_keys(self, text):
        """Ticket keys named in free text (a PR title or branch), restricted to known prefixes."""
        prefixes = self.prefixes()
        if not prefixes or not text:
            return []
        pat = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, prefixes), key=len, reverse=True)) +
                         r")-(\d{1,6})(?![0-9])", re.I)
        seen = []
        for m in pat.finditer(text):
            key = f"{m.group(1).upper()}-{int(m.group(2)):03d}"  # CC-12 and CC-012 are one ticket
            if key not in seen:
                seen.append(key)
        return seen

    # ---------- writing ----------

    def _audit(self, tid, actor, kind, field=None, frm=None, to=None, trigger=None, data=None, at=None):
        def s(v):
            return None if v is None else (v if isinstance(v, str) else json.dumps(v))
        self.db.execute("INSERT INTO ticket_events(ticket_id, at, actor, kind, field, from_value, to_value, trigger, "
                        "data) VALUES (?,?,?,?,?,?,?,?,?)",
                        (tid, at or _now(), actor, kind, field, s(frm), s(to), trigger, json.dumps(data or {})))

    def _touch(self, tid, at):
        self.db.execute("UPDATE tickets SET updated_at=? WHERE id=?", (at, tid))
        self.last_change = at

    def _project(self, key):
        row = self.db.execute("SELECT key, prefix, next_number FROM task_projects WHERE key=?", (key,)).fetchone()
        if not row:
            raise TaskError(404, f"unknown project {key}")
        return row

    def create(self, project, title, actor="jay", *, number=None, **fields):
        """A new ticket. Only project and title are required; the key comes from the project counter.

        `number` is for the reviewed import only: it keeps an existing ID (SV-056)
        and moves the counter past it, so nothing is ever renumbered or reused.
        """
        actor = _actor(actor)
        title = _printable(str(title or "").strip(), TEXT_FIELDS["title"], "title")
        if not title:
            raise TaskError(400, "title is required")
        status = fields.pop("status", None) or "INBOX"
        if status not in ALL_STATUSES:
            raise TaskError(400, f"status must be one of {', '.join(ALL_STATUSES)}")
        at = _now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            pkey, prefix, nxt = self._project(project)
            if number is not None:
                number = int(number)
                if number < 1 or self.db.execute("SELECT 1 FROM tickets WHERE project=? AND number=?",
                                                  (pkey, number)).fetchone():
                    raise TaskError(409, f"{prefix}-{number:03d} already exists")
            else:
                number = nxt
            key = f"{prefix}-{number:03d}"
            self.db.execute("UPDATE task_projects SET next_number=MAX(next_number, ?) WHERE key=?", (number + 1, pkey))
            cur = self.db.execute(
                "INSERT INTO tickets(project, number, key, title, status, creator, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (pkey, number, key, title, status, actor, at, at))
            tid = cur.lastrowid
            self._audit(tid, actor, "created", to=key, data={"title": title, "status": status}, at=at)
            changes = self._apply(tid, fields, actor, at) if fields else []
            if status in ("IN_PROGRESS",):
                self.db.execute("UPDATE tickets SET started_at=? WHERE id=?", (at, tid))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.last_change = at
        return self.get(key), changes

    def update(self, key, fields, actor="jay", trigger=None):
        """Change fields. Each real change is one audit row; a no-op writes nothing."""
        actor = _actor(actor)
        if not isinstance(fields, dict) or not fields:
            raise TaskError(400, "nothing to change")
        at = _now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            tid = self._id_of(key)
            changes = self._apply(tid, fields, actor, at, trigger=trigger)
            if changes:
                self._touch(tid, at)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(key), changes

    def _apply(self, tid, fields, actor, at, trigger=None):
        cur: dict = dict(zip(("status", "priority", "type", "assignee_kind", "assignee_ref", "agent_role", "agent_pane_id",
                        "agent_session_id", "parent_id", "branch", "title", "description", "due_at", "estimate",
                        "archived", "started_at") + FLAGS,
                       self.db.execute("SELECT status, priority, type, assignee_kind, assignee_ref, agent_role, "
                                       "agent_pane_id, agent_session_id, parent_id, branch, title, description, "
                                       "due_at, estimate, archived, started_at, " + ", ".join(FLAGS) +
                                       " FROM tickets WHERE id=?", (tid,)).fetchone()))
        sets, changes = {}, []

        def change(field, column, old, new, kind="updated"):
            if old == new:
                return
            sets[column] = new
            changes.append({"field": field, "from": old, "to": new})
            self._audit(tid, actor, kind, field=field, frm=old, to=new, trigger=trigger, at=at)

        known = {"title", "description", "status", "priority", "type", "assignee", "agentRole", "agentPaneId",
                 "agentSessionId", "parent", "branch", "dueAt", "estimate", "archived", "labels", "flags"} | set(FLAGS)
        unknown = set(fields) - known
        if unknown:
            raise TaskError(400, f"cannot change {', '.join(sorted(unknown))}")

        for f, limit in TEXT_FIELDS.items():
            if f in fields:
                v = fields[f]
                if f == "branch" and v in (None, ""):
                    change(f, f, cur[f], None)
                    continue
                v = _printable(str(v if v is not None else ""), limit, f, multiline=(f == "description"))
                if f == "title":
                    v = v.strip()
                    if not v:
                        raise TaskError(400, "title cannot be empty")
                change(f, f, cur[f], v, kind="updated")
        if "status" in fields:
            st = fields["status"]
            if st not in ALL_STATUSES:
                raise TaskError(400, f"status must be one of {', '.join(ALL_STATUSES)}")
            if st != cur["status"]:
                change("status", "status", cur["status"], st, kind="status")
                if st == "IN_PROGRESS" and not cur["started_at"]:
                    sets["started_at"] = at
                sets["completed_at"] = at if st in CLOSED else None
        if "priority" in fields:
            if fields["priority"] not in PRIORITIES:
                raise TaskError(400, f"priority must be one of {', '.join(PRIORITIES)}")
            change("priority", "priority", cur["priority"], fields["priority"])
        if "type" in fields:
            t = fields["type"] or None
            if t is not None and t not in self.types():
                raise TaskError(400, f"type must be one of {', '.join(self.types())}")
            change("type", "type", cur["type"], t)
        if "assignee" in fields:
            kind, ref = parse_assignee(fields["assignee"])
            old = assignee_str(cur["assignee_kind"], cur["assignee_ref"])
            new = assignee_str(kind, ref)
            if old != new:
                sets["assignee_kind"], sets["assignee_ref"] = kind, ref
                changes.append({"field": "assignee", "from": old, "to": new})
                self._audit(tid, actor, "assigned", field="assignee", frm=old, to=new, trigger=trigger, at=at)
        if "agentRole" in fields:
            r = fields["agentRole"] or None
            if r is not None and r not in ROLES:
                raise TaskError(400, f"agentRole must be one of {', '.join(ROLES)}")
            change("agentRole", "agent_role", cur["agent_role"], r)
        for f, col in (("agentPaneId", "agent_pane_id"), ("agentSessionId", "agent_session_id")):
            if f in fields:
                v = fields[f] or None
                if v is not None and not re.match(r"^[A-Za-z0-9_:.-]{1,80}$", str(v)):
                    raise TaskError(400, f"{f} is not a pane or session id")
                change(f, col, cur[col], v)
        if "parent" in fields:
            pid = None
            if fields["parent"]:
                pid = self._id_of(fields["parent"])
                if pid == tid:
                    raise TaskError(400, "a ticket cannot be its own parent")
                # no cycles: walk up from the new parent
                seen, walk = set(), pid
                while walk:
                    if walk == tid:
                        raise TaskError(400, "that would make a parent loop")
                    if walk in seen:
                        break
                    seen.add(walk)
                    walk = self.db.execute("SELECT parent_id FROM tickets WHERE id=?", (walk,)).fetchone()[0]
            if pid != cur["parent_id"]:
                old_k = self._key_of(cur["parent_id"]) if cur["parent_id"] else None
                new_k = self._key_of(pid) if pid else None
                sets["parent_id"] = pid
                changes.append({"field": "parent", "from": old_k, "to": new_k})
                self._audit(tid, actor, "parent", field="parent", frm=old_k, to=new_k, trigger=trigger, at=at)
        for f, col in (("dueAt", "due_at"), ("estimate", "estimate")):
            if f in fields:
                v = fields[f]
                if v is not None and not isinstance(v, (int, float)):
                    raise TaskError(400, f"{f} must be a number or null")
                change(f, col, cur[col], v)
        if "archived" in fields:
            change("archived", "archived", bool(cur["archived"]), bool(fields["archived"]), kind="archived")
            if "archived" in sets:
                sets["archived"] = int(sets["archived"])
        flag_values = dict(fields.get("flags") or {}) if isinstance(fields.get("flags"), dict) else {}
        if "flags" in fields and not isinstance(fields["flags"], dict):
            raise TaskError(400, "flags must be an object like {\"needs_jay\": true}")
        for f in FLAGS:
            if f in fields:
                flag_values[f] = fields[f]
        for f, v in flag_values.items():
            if f not in FLAGS:
                raise TaskError(400, f"unknown flag {f}")
            change(f, f, bool(cur[f]), bool(v), kind="flag")
            if f in sets:
                sets[f] = int(sets[f])
        if "labels" in fields:
            labels = fields["labels"]
            if not isinstance(labels, list) or not all(isinstance(l, str) and LABEL_RE.match(l) for l in labels):
                raise TaskError(400, "labels are lowercase words: a-z 0-9 : . _ / -, at most 40 characters")
            old = {r[0] for r in self.db.execute("SELECT label FROM ticket_labels WHERE ticket_id=?", (tid,))}
            new = set(labels)
            for l in sorted(new - old):
                self.db.execute("INSERT INTO ticket_labels(ticket_id, label) VALUES (?,?)", (tid, l))
                self._audit(tid, actor, "label_added", field="labels", to=l, trigger=trigger, at=at)
            for l in sorted(old - new):
                self.db.execute("DELETE FROM ticket_labels WHERE ticket_id=? AND label=?", (tid, l))
                self._audit(tid, actor, "label_removed", field="labels", frm=l, trigger=trigger, at=at)
            if new != old:
                changes.append({"field": "labels", "from": sorted(old), "to": sorted(new)})
        if sets:
            cols = ", ".join(f"{c}=?" for c in sets)
            self.db.execute(f"UPDATE tickets SET {cols} WHERE id=?", (*sets.values(), tid))
        return changes

    def comment(self, key, body, actor="jay"):
        actor = _actor(actor)
        body = _printable(str(body or "").strip(), 20000, "comment", multiline=True)
        if not body:
            raise TaskError(400, "comment is empty")
        at = _now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            tid = self._id_of(key)
            cur = self.db.execute("INSERT INTO ticket_comments(ticket_id, author, body, created_at) VALUES (?,?,?,?)",
                                  (tid, actor, body, at))
            self._audit(tid, actor, "commented", data={"commentId": cur.lastrowid, "length": len(body)}, at=at)
            self._touch(tid, at)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(key)

    def relate(self, key, kind, target, actor="jay", remove=False):
        """blocks / blocked_by / related / duplicates between two tickets. Simple edges, no graph engine."""
        actor = _actor(actor)
        if kind not in RELATION_KINDS + ("blocked_by",):
            raise TaskError(400, f"kind must be one of {', '.join(RELATION_KINDS + ('blocked_by',))}")
        at = _now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            a, b = self._id_of(key), self._id_of(target)
            if a == b:
                raise TaskError(400, "a ticket cannot relate to itself")
            src, dst, stored = (b, a, "blocks") if kind == "blocked_by" else (a, b, kind)
            if stored == "related" and src > dst:
                src, dst = dst, src  # symmetric: one row whichever side adds it
            exists = self.db.execute("SELECT id FROM ticket_relations WHERE src_id=? AND dst_id=? AND kind=?",
                                     (src, dst, stored)).fetchone()
            changed = False
            if remove and exists:
                self.db.execute("DELETE FROM ticket_relations WHERE id=?", (exists[0],))
                changed = True
            elif not remove and not exists:
                if stored == "blocks" and self.db.execute(
                        "SELECT 1 FROM ticket_relations WHERE src_id=? AND dst_id=? AND kind='blocks'",
                        (dst, src)).fetchone():
                    raise TaskError(409, "these tickets already block each other the other way")
                self.db.execute("INSERT INTO ticket_relations(src_id, dst_id, kind, created_at) VALUES (?,?,?,?)",
                                (src, dst, stored, at))
                changed = True
            if changed:
                other = str(target).upper()
                verb = "relation_removed" if remove else "relation_added"
                self._audit(a, actor, verb, field=kind, to=None if remove else other, frm=other if remove else None,
                            at=at)
                self._audit(b, actor, verb, field=_inverse(kind), to=None if remove else key.upper(),
                            frm=key.upper() if remove else None, at=at)
                self._touch(a, at)
                self._touch(b, at)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(key), changed

    def link(self, key, provider, kind, ref, url=None, title=None, actor="jay", trigger=None, remove=False):
        """Attach an external record (a PR, a legacy issue, a URL). Idempotent."""
        actor = _actor(actor)
        if provider not in LINK_PROVIDERS:
            raise TaskError(400, f"provider must be one of {', '.join(LINK_PROVIDERS)}")
        if kind not in ("pr", "issue", "legacy_id", "commit", "url"):
            raise TaskError(400, "kind must be pr, issue, legacy_id, commit or url")
        ref = _printable(str(ref or "").strip(), 300, "ref")
        if not ref:
            raise TaskError(400, "ref is required")
        if url is not None:
            url = _printable(str(url), 500, "url")
            if url and not re.match(r"^https?://", url):
                raise TaskError(400, "url must be http(s)")
        if title is not None:
            title = _printable(str(title), 300, "title")
        at = _now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            tid = self._id_of(key)
            row = self.db.execute("SELECT id FROM ticket_links WHERE ticket_id=? AND provider=? AND kind=? AND ref=?",
                                  (tid, provider, kind, ref)).fetchone()
            changed = False
            if remove and row:
                self.db.execute("DELETE FROM ticket_links WHERE id=?", (row[0],))
                self._audit(tid, actor, "unlinked", field=kind, frm=ref, trigger=trigger, data={"provider": provider},
                            at=at)
                changed = True
            elif not remove and not row:
                self.db.execute("INSERT INTO ticket_links(ticket_id, provider, kind, ref, url, title, created_at, "
                                "created_by) VALUES (?,?,?,?,?,?,?,?)", (tid, provider, kind, ref, url, title, at, actor))
                self._audit(tid, actor, "linked", field=kind, to=ref, trigger=trigger,
                            data={"provider": provider, "url": url}, at=at)
                changed = True
            if changed:
                self._touch(tid, at)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(key), changed

    def has_link(self, key, provider, kind, ref):
        return self.db.execute(
            "SELECT 1 FROM ticket_links l JOIN tickets t ON t.id=l.ticket_id WHERE t.key=? AND l.provider=? "
            "AND l.kind=? AND l.ref=?", (key, provider, kind, ref)).fetchone() is not None

    def context(self, key):
        """Everything an agent needs to start on a ticket, as data and as a short brief."""
        t = self.get(key)
        parent = self.get(t["parent"]) if t["parent"] else None
        lines = [f"{t['key']} · {t['title']}",
                 f"project {t['project']} · status {t['status']} · priority {t['priority']}"
                 f"{' · type ' + t['type'] if t['type'] else ''}"
                 f"{' · assignee ' + t['assignee'] if t['assignee'] else ''}"]
        if t["flags"]:
            lines.append("flags: " + ", ".join(FLAG_LABEL[f] for f in t["flags"]))
        if parent:
            lines.append(f"parent: {parent['key']} {parent['title']} ({parent['status']})")
        if t["branch"]:
            lines.append(f"branch: {t['branch']}")
        for l in t["links"]:
            lines.append(f"link: {l['provider']} {l['kind']} {l['ref']}{' ' + l['url'] if l['url'] else ''}")
        for label, items in (("blocked by", t["relations"]["blocked_by"]), ("blocks", t["relations"]["blocks"]),
                             ("related", t["relations"]["related"])):
            if items:
                lines.append(f"{label}: " + ", ".join(f"{i['key']} ({i['status']})" for i in items))
        if t["subtaskList"]:
            lines.append("subtasks: " + ", ".join(f"{s['key']} ({s['status']})" for s in t["subtaskList"]))
        if t["description"]:
            lines += ["", t["description"]]
        if t["comments"]:
            lines += ["", "notes:"] + [f"- {c['author']}: {c['body']}" for c in t["comments"][-10:]]
        lines += ["", "Not authorized by this ticket: merge, deploy, production, --apply, secrets, rule changes."]
        return {"ticket": t, "parent": parent and {k: parent[k] for k in ("key", "title", "status")},
                "brief": "\n".join(lines)}


def _inverse(kind):
    return {"blocks": "blocked_by", "blocked_by": "blocks"}.get(kind, kind)
