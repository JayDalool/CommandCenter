"""SQLite: the event log, alert acknowledgements, and last-good caches.

Operational metadata only. What goes in: event kinds, pane ids, project keys,
states, PR/issue numbers and titles, timestamps. What never goes in: secrets,
tokens, pane output, transcripts, blocked-agent question text (it could quote
property data), or anything from a project's files beyond checkbox counts.

One writer (the daemon's event loop), WAL mode, pruned by `prune()`.
"""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  at       REAL NOT NULL,
  source   TEXT NOT NULL,
  kind     TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info',
  project  TEXT,
  agent_id TEXT,
  ref      TEXT,
  text     TEXT NOT NULL DEFAULT '',
  data     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_at ON events(at);
CREATE TABLE IF NOT EXISTS kv (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
  id       TEXT PRIMARY KEY,
  severity TEXT NOT NULL,
  source   TEXT NOT NULL,
  project  TEXT,
  text     TEXT NOT NULL,
  first_at REAL NOT NULL,
  last_at  REAL NOT NULL,
  ack_at   REAL,
  active   INTEGER NOT NULL DEFAULT 1
);
"""

# Keys of `data` that may be persisted with an event. Anything else is dropped.
EVENT_DATA_KEYS = ("from", "to", "status", "number", "ci", "stage", "kind", "reason",
                   "error", "count", "connected", "pane_id", "agent", "name", "cwd_project",
                   # Messages (ccd/leadchat.py): which conversation and message, never its text
                   "conversation", "messageId", "delivery", "via", "author", "files", "overBudget")


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---------- events ----------

    def append(self, source, kind, text="", severity="info", project=None, agent_id=None, ref=None, data=None):
        clean = {k: v for k, v in (data or {}).items() if k in EVENT_DATA_KEYS}
        at = time.time()
        cur = self.db.execute(
            "INSERT INTO events(at, source, kind, severity, project, agent_id, ref, text, data) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (at, source, kind, severity, project, agent_id, ref, str(text)[:300], json.dumps(clean)))
        return {"seq": cur.lastrowid, "at": at, "source": source, "kind": kind, "severity": severity,
                "project": project, "agentId": agent_id, "ref": ref, "text": str(text)[:300], "data": clean}

    @staticmethod
    def _row(r):
        return {"seq": r[0], "at": r[1], "source": r[2], "kind": r[3], "severity": r[4], "project": r[5],
                "agentId": r[6], "ref": r[7], "text": r[8], "data": json.loads(r[9] or "{}")}

    def since(self, seq, limit=5000):
        rows = self.db.execute(
            "SELECT seq, at, source, kind, severity, project, agent_id, ref, text, data "
            "FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?", (int(seq), int(limit))).fetchall()
        return [self._row(r) for r in rows]

    def recent(self, limit=100, before=None, kind=None, project=None):
        q = ("SELECT seq, at, source, kind, severity, project, agent_id, ref, text, data FROM events WHERE 1=1")
        args = []
        if before is not None:
            q += " AND seq < ?"
            args.append(int(before))
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        if project:
            q += " AND project = ?"
            args.append(project)
        q += " ORDER BY seq DESC LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))
        return [self._row(r) for r in self.db.execute(q, args).fetchall()]

    def last_seq(self):
        return self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]

    def first_seq(self):
        return self.db.execute("SELECT COALESCE(MIN(seq), 0) FROM events").fetchone()[0]

    # ---------- kv ----------

    def put(self, key, value):
        self.db.execute("INSERT INTO kv(key, value, at) VALUES (?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, at=excluded.at",
                        (key, json.dumps(value), time.time()))

    def get(self, key, default=None):
        row = self.db.execute("SELECT value, at FROM kv WHERE key = ?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else (default, None)

    # ---------- alerts ----------

    def sync_alerts(self, current):
        """Upsert the alerts that are active now; mark the rest inactive.

        An alert that clears and later returns starts unacknowledged again.
        """
        now = time.time()
        ids = set()
        for a in current:
            ids.add(a["id"])
            row = self.db.execute("SELECT active FROM alerts WHERE id = ?", (a["id"],)).fetchone()
            if row is None:
                self.db.execute("INSERT INTO alerts(id, severity, source, project, text, first_at, last_at, active) "
                                "VALUES (?,?,?,?,?,?,?,1)",
                                (a["id"], a["severity"], a["source"], a.get("project"), a["text"][:200], now, now))
            elif row[0] == 0:
                self.db.execute("UPDATE alerts SET active=1, ack_at=NULL, first_at=?, last_at=?, text=?, severity=? "
                                "WHERE id=?", (now, now, a["text"][:200], a["severity"], a["id"]))
            else:
                self.db.execute("UPDATE alerts SET last_at=?, text=?, severity=? WHERE id=?",
                                (now, a["text"][:200], a["severity"], a["id"]))
        if ids:
            marks = ",".join("?" * len(ids))
            self.db.execute(f"UPDATE alerts SET active=0 WHERE active=1 AND id NOT IN ({marks})", tuple(ids))
        else:
            self.db.execute("UPDATE alerts SET active=0 WHERE active=1")

    def alerts(self, include_inactive=False):
        q = "SELECT id, severity, source, project, text, first_at, last_at, ack_at, active FROM alerts"
        if not include_inactive:
            q += " WHERE active=1"
        q += " ORDER BY first_at DESC"
        return [{"id": r[0], "severity": r[1], "source": r[2], "project": r[3], "text": r[4],
                 "since": r[5], "lastSeen": r[6], "ack": r[7] is not None, "ackAt": r[7], "active": bool(r[8])}
                for r in self.db.execute(q).fetchall()]

    def ack(self, alert_id):
        cur = self.db.execute("UPDATE alerts SET ack_at=? WHERE id=? AND active=1 AND ack_at IS NULL",
                              (time.time(), alert_id))
        if cur.rowcount:
            return True
        return self.db.execute("SELECT 1 FROM alerts WHERE id=? AND active=1", (alert_id,)).fetchone() is not None

    # ---------- housekeeping ----------

    def prune(self, retention_days=30, max_rows=200_000):
        cutoff = time.time() - retention_days * 86400
        n = self.db.execute("DELETE FROM events WHERE at < ?", (cutoff,)).rowcount
        over = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] - max_rows
        if over > 0:
            n += self.db.execute("DELETE FROM events WHERE seq IN (SELECT seq FROM events ORDER BY seq ASC LIMIT ?)",
                                 (over,)).rowcount
        self.db.execute("DELETE FROM alerts WHERE active=0 AND last_at < ?", (cutoff,))
        return n

    def size_bytes(self):
        page = self.db.execute("PRAGMA page_count").fetchone()[0]
        size = self.db.execute("PRAGMA page_size").fetchone()[0]
        return page * size
