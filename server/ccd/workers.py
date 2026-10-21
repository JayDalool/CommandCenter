"""Worker nodes (v2 Phase 1, PR 5; docs/COMMANDCENTER_V2_DISCOVERY.md §9).

A WorkerNode is a machine that can run agent work: the server ccd runs on, Jay's laptop (WSL), later a GPU box or
a cloud runner. This module is the MODEL and its enrolment only. Nothing is scheduled on a node yet: jobs, leases
and the reaper come in Phase 2. Today's execution (herdr panes on the server) is unchanged.

    server        registers itself when ccd starts (it is ccd's own host) and heartbeats from ccd's loop
    other nodes   enrol (POST /api/workers/enrol, with ccd's token) → "pending"; ccd mints a node token and keeps
                  only its SHA-256; the node is unusable until Jay approves it (Jay + Developer Unlock); it
                  heartbeats with its token; Jay can revoke it, which is final for that token

Every change is a `worker_events` row (append-only). A node can never approve itself: `approved_by` can only be
`jay` (schema CHECK). Status shown: pending | online | offline | revoked (online = heartbeat within ONLINE_FOR).
"""
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import time

from . import registry

KINDS = ("server", "laptop", "gpu", "cloud")
NODE_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ONLINE_FOR = 120          # seconds since the last heartbeat that still count as online
HEARTBEAT_EVERY = 30      # the server node's own heartbeat interval
TOOLS = ("git", "gh", "claude", "codex", "node", "python3", "docker")
CAP_KEYS = {"os": 40, "arch": 20, "tools": None, "repos": None, "labels": None}
SERVER_ID = "server"


class WorkerError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def clean_caps(raw):
    """A node's advertised capabilities, as a small plain dict. Unknown keys are dropped; lists are capped."""
    if not isinstance(raw, dict):
        raise WorkerError(400, "capabilities must be an object")
    out = {}
    for k, limit in CAP_KEYS.items():
        v = raw.get(k)
        if v is None:
            continue
        if limit:   # short text
            if not isinstance(v, str) or len(v) > limit:
                raise WorkerError(400, f"capabilities.{k} must be text of at most {limit} characters")
            out[k] = v
        else:       # list of short slugs
            if not isinstance(v, list) or len(v) > 40 or not all(isinstance(x, str) and re.match(r"^[A-Za-z0-9._:/-]{1,64}$", x) for x in v):
                raise WorkerError(400, f"capabilities.{k} must be a list of at most 40 short names")
            out[k] = sorted(set(v))
    return out


def server_caps():
    """What the server node has: OS, architecture, the tools on PATH and the registered repos checked out here."""
    return {"os": platform.system().lower()[:40], "arch": platform.machine()[:20],
            "tools": sorted(t for t in TOOLS if shutil.which(t)),
            "repos": sorted(k for k in registry.PROJECTS if (registry.root_of(k) and os.path.isdir(registry.root_of(k))))}


class Workers:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock
        self._last_beat = 0.0

    def _event(self, node, kind, actor, data=None):
        self.db.execute("INSERT INTO worker_events (node_id, at, kind, actor, data) VALUES (?,?,?,?,?)",
                        (node, self.clock(), kind, actor, json.dumps(data or {})[:2000]))

    def _row(self, node):
        return self.db.execute("SELECT id, status, token_sha FROM worker_nodes WHERE id=?", (node,)).fetchone()

    # ---------- the server node ----------

    def register_server(self, version, caps=None):
        """ccd's own host. Active from the start: it is where ccd already runs. Idempotent; refreshes caps/version."""
        caps = caps if caps is not None else server_caps()
        now = self.clock()
        with self.db:
            if self._row(SERVER_ID) is None:
                self.db.execute(
                    "INSERT INTO worker_nodes (id, kind, owner, status, capabilities, version, enrolled_at, enrolled_by, "
                    "approved_at, approved_by, last_heartbeat) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (SERVER_ID, "server", "jay", "active", json.dumps(caps), str(version)[:40], now, "system:ccd",
                     now, "jay", now))
                self._event(SERVER_ID, "registered", "system:ccd", {"caps": caps, "version": str(version)[:40]})
            else:
                self.db.execute("UPDATE worker_nodes SET capabilities=?, version=?, last_heartbeat=? WHERE id=? "
                                "AND status='active'", (json.dumps(caps), str(version)[:40], now, SERVER_ID))
        self._last_beat = now

    def server_heartbeat(self):
        """From ccd's loop; at most every HEARTBEAT_EVERY seconds."""
        now = self.clock()
        if now - self._last_beat < HEARTBEAT_EVERY:
            return False
        with self.db:
            self.db.execute("UPDATE worker_nodes SET last_heartbeat=? WHERE id=? AND status='active'", (now, SERVER_ID))
        self._last_beat = now
        return True

    # ---------- other nodes ----------

    def enrol(self, node, kind, caps, version, actor):
        """A new node asks to join. Returns its token ONCE (only the hash is kept). Pending until Jay approves."""
        if not isinstance(node, str) or not NODE_RE.match(node) or node == SERVER_ID:
            raise WorkerError(400, "id must be a short lower-case name (letters, digits, hyphens), not 'server'")
        if kind not in KINDS or kind == "server":
            raise WorkerError(400, "kind must be laptop, gpu or cloud")
        caps = clean_caps(caps or {})
        version = str(version or "")[:40]
        if self._row(node) is not None:
            raise WorkerError(409, f"a node called {node} already exists (revoked names are not reused)")
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute(
                "INSERT INTO worker_nodes (id, kind, owner, status, capabilities, version, enrolled_at, enrolled_by, "
                "token_sha) VALUES (?,?,?,?,?,?,?,?,?)",
                (node, kind, "jay", "pending", json.dumps(caps), version, self.clock(), actor, _sha(token)))
            self._event(node, "enrolled", actor, {"kind": kind, "caps": caps, "version": version})
        return {"id": node, "status": "pending", "token": token}

    def _authenticate(self, node, token):
        row = self._row(node) if isinstance(node, str) else None
        if row is None or not row[2] or not isinstance(token, str) \
                or not hmac.compare_digest(row[2], _sha(token)):
            raise WorkerError(401, "unknown node or wrong node token")
        if row[1] == "revoked":
            raise WorkerError(403, f"{node} was revoked")
        return row

    def heartbeat(self, node, token, caps=None, version=None):
        row = self._authenticate(node, token)
        sets, args = ["last_heartbeat=?"], [self.clock()]
        if caps is not None:
            sets.append("capabilities=?")
            args.append(json.dumps(clean_caps(caps)))
        if version is not None:
            sets.append("version=?")
            args.append(str(version)[:40])
        with self.db:
            self.db.execute(f"UPDATE worker_nodes SET {', '.join(sets)} WHERE id=?", (*args, node))
        return {"id": node, "status": row[1]}

    def approve(self, node, actor):
        if actor != "jay":
            raise WorkerError(403, "only Jay approves a worker node")
        row = self._row(node)
        if row is None:
            raise WorkerError(404, f"no node {node}")
        if row[1] != "pending":
            raise WorkerError(409, f"{node} is {row[1]}, not pending")
        with self.db:
            self.db.execute("UPDATE worker_nodes SET status='active', approved_at=?, approved_by='jay' WHERE id=?",
                            (self.clock(), node))
            self._event(node, "approved", "jay")
        return self.node(node)

    def revoke(self, node, actor, reason=""):
        if actor != "jay":
            raise WorkerError(403, "only Jay revokes a worker node")
        row = self._row(node)
        if row is None:
            raise WorkerError(404, f"no node {node}")
        if node == SERVER_ID:
            raise WorkerError(409, "the server node is ccd's own host; it cannot be revoked")
        if row[1] == "revoked":
            raise WorkerError(409, f"{node} is already revoked")
        reason = re.sub(r"[\x00-\x1f\x7f]+", " ", str(reason or ""))[:200]
        with self.db:
            self.db.execute("UPDATE worker_nodes SET status='revoked', revoked_at=? WHERE id=?", (self.clock(), node))
            self._event(node, "revoked", "jay", {"reason": reason})
        return self.node(node)

    # ---------- read ----------

    def node(self, node):
        return next((n for n in self.list() if n["id"] == node), None)

    def list(self):
        now = self.clock()
        out = []
        for r in self.db.execute("SELECT id, kind, owner, status, capabilities, version, enrolled_at, enrolled_by, "
                                 "approved_at, approved_by, last_heartbeat, revoked_at FROM worker_nodes "
                                 "ORDER BY (id = 'server') DESC, id").fetchall():
            beat = r[10]
            shown = r[3] if r[3] in ("pending", "revoked") else \
                ("online" if beat is not None and now - beat <= ONLINE_FOR else "offline")
            out.append({"id": r[0], "kind": r[1], "owner": r[2], "status": shown, "state": r[3],
                        "capabilities": json.loads(r[4] or "{}"), "version": r[5], "enrolledAt": r[6],
                        "enrolledBy": r[7], "approvedAt": r[8], "approvedBy": r[9], "lastHeartbeat": beat,
                        "revokedAt": r[11]})
        return out

    def events(self, limit=50):
        return [{"node": r[0], "at": r[1], "kind": r[2], "actor": r[3], "data": json.loads(r[4] or "{}")}
                for r in self.db.execute("SELECT node_id, at, kind, actor, data FROM worker_events ORDER BY id DESC "
                                         "LIMIT ?", (max(1, min(int(limit), 500)),))]
