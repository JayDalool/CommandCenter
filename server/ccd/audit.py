"""The global audit trail (v2 Phase 1, PR 7; docs/COMMANDCENTER_V2_DISCOVERY.md Phase 1 item 6).

One append-only `audit_events` row for every write that reaches ccd's API (and for what ccd itself does to a ticket's
pipeline, as `system:ccd`), with the identity behind it (ccd/identity.py: verified by Developer Unlock, by an actor
token, or not at all) and the policy fingerprint in force.

What is kept: who claimed to act, how far that is verified, method, path, response status, project and ticket when
the path or body names them, the top-level body keys and the SHA-256 of the body. What is never kept: the body itself
(answers, notes and file contents can hold anything).

Each row carries `sha = sha256(prev_sha + row)`, so the trail is a hash chain: editing or removing any row except the
newest breaks every later link, which `verify()` reports. The triggers already refuse UPDATE and DELETE; the chain covers
someone editing the database file directly.
"""
import hashlib
import json
import re
import time

GENESIS = "0" * 64
KEY_RE = re.compile(r"/api/tasks/([A-Z][A-Z0-9-]{0,20}-\d{1,6})(?:/|$)")
COLUMNS = ("at", "actor", "verified", "via", "token_actor", "method", "path", "status", "project", "ref", "body_sha",
           "body_keys", "summary", "profile_hash")


def _canon(row):
    return json.dumps([row[c] for c in COLUMNS], separators=(",", ":"), default=str)


def body_digest(body):
    if body is None:
        return None, []
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    keys = sorted(str(k)[:40] for k in body)[:30] if isinstance(body, dict) else []
    return hashlib.sha256(raw.encode()).hexdigest(), keys


class Audit:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock
        self._good = (0, GENESIS, 0)   # (last id, its sha, rows) already walked and found intact

    def record(self, *, actor, verified, via, method, path, status, token_actor=None, project=None, ref=None,
               body=None, summary="", profile_hash=None):
        sha_body, keys = body_digest(body)
        if ref is None:
            m = KEY_RE.search(path or "")
            ref = m.group(1) if m else None
        if project is None and isinstance(body, dict) and isinstance(body.get("project"), str):
            project = body["project"][:40]
        row = {"at": self.clock(), "actor": re.sub(r"[\x00-\x1f\x7f]+", " ", str(actor))[:80], "verified": 1 if verified else 0, "via": via,
               "token_actor": token_actor, "method": str(method)[:10], "path": str(path)[:300], "status": int(status),
               "project": project, "ref": ref, "body_sha": sha_body, "body_keys": json.dumps(keys),
               "summary": re.sub(r"[\x00-\x1f\x7f]+", " ", str(summary or ""))[:300], "profile_hash": profile_hash}
        # The chain needs the previous row and the insert in one transaction.
        own = not self.db.in_transaction
        self.db.execute("BEGIN IMMEDIATE" if own else "SAVEPOINT audit_record")
        try:
            prev = self.db.execute("SELECT sha FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
            prev_sha = prev[0] if prev else GENESIS
            sha = hashlib.sha256((prev_sha + _canon(row)).encode()).hexdigest()
            self.db.execute(f"INSERT INTO audit_events ({', '.join(COLUMNS)}, prev_sha, sha) VALUES "
                            f"({', '.join('?' * (len(COLUMNS) + 2))})", (*[row[c] for c in COLUMNS], prev_sha, sha))
            self.db.execute("COMMIT" if own else "RELEASE audit_record")
        except BaseException:
            if self.db.in_transaction:     # SQLite may already have rolled it all back (disk full, I/O)
                self.db.execute("ROLLBACK" if own else "ROLLBACK TO audit_record")
                if not own:
                    self.db.execute("RELEASE audit_record")
            raise
        return sha

    def verify(self, full=False):
        """Walk the chain. By default only rows added since the last intact walk (cheap enough to run on every look);
        `full` walks from the first row, which also catches an edit to rows already checked. {ok, checked, brokenAt,
        full}. A broken chain is never remembered as good, so it keeps being reported."""
        start_id, prev, n = (0, GENESIS, 0) if full else self._good
        for r in self.db.execute(f"SELECT id, {', '.join(COLUMNS)}, prev_sha, sha FROM audit_events WHERE id > ? "
                                 f"ORDER BY id", (start_id,)):
            row = dict(zip(COLUMNS, r[1:1 + len(COLUMNS)]))
            prev_sha, sha = r[-2], r[-1]
            if prev_sha != prev or hashlib.sha256((prev + _canon(row)).encode()).hexdigest() != sha:
                return {"ok": False, "checked": n, "brokenAt": r[0], "full": full}
            prev, n, start_id = sha, n + 1, r[0]
        self._good = (start_id, prev, n)
        return {"ok": True, "checked": n, "brokenAt": None, "full": full}

    def list(self, actor=None, verified=None, limit=100):
        q = f"SELECT id, {', '.join(COLUMNS)} FROM audit_events"
        where, args = [], []
        if actor:
            where.append("actor = ?")
            args.append(actor)
        if verified is not None:
            where.append("verified = ?")
            args.append(1 if verified else 0)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        out = []
        for r in self.db.execute(q, args):
            d = dict(zip(("id",) + COLUMNS, r))
            out.append({"id": d["id"], "at": d["at"], "actor": d["actor"], "verified": bool(d["verified"]),
                        "via": d["via"], "tokenActor": d["token_actor"], "method": d["method"], "path": d["path"],
                        "status": d["status"], "project": d["project"], "ref": d["ref"],
                        "bodyKeys": json.loads(d["body_keys"] or "[]"), "summary": d["summary"],
                        "profileHash": d["profile_hash"]})
        return out

    def summary(self, since=None):
        """What enforcing verified identity would mean, measured: writes by how they were verified, writes that
        claim Jay without Developer Unlock, and token/claim mismatches."""
        since = since if since is not None else self.clock() - 30 * 86400
        rows = self.db.execute(
            "SELECT via, verified, actor, token_actor, COUNT(*) FROM audit_events WHERE at >= ? "
            "GROUP BY via, verified, actor, token_actor", (since,)).fetchall()
        by_via, unverified_jay, mismatch, agents_unverified, total, refuse = {}, 0, 0, 0, 0, 0
        for via, verified, actor, token_actor, n in rows:
            total += n
            by_via[via] = by_via.get(via, 0) + n
            if actor == "jay" and not verified and via != "system":
                unverified_jay += n
            if token_actor and token_actor != actor:
                mismatch += n
            if actor.startswith("agent:") and not verified:
                agents_unverified += n
            if not verified and via != "system":
                refuse += n
        return {"since": since, "total": total, "byVia": by_via, "unverifiedJay": unverified_jay,
                "agentUnverified": agents_unverified, "mismatch": mismatch,
                "wouldRefuse": refuse}
