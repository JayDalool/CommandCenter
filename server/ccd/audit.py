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

Phase 2 shadow step 1 adds one `identity_observations` row per recorded write (ccd/identity.py resolve()): the actor
the request asserted, the actor it proves, and why Phase 2 enforcement would refuse it. It is written in the same
transaction as its audit row, names that row's sha, and is a hash chain of its own (`verify_identity()` walks it). It never
changes the audit row and never refuses anything: `enforced` is always 0.
"""
import hashlib
import json
import re
import time

GENESIS = "0" * 64
KEY_RE = re.compile(r"/api/tasks/([A-Z][A-Z0-9-]{0,20}-\d{1,6})(?:/|$)")
OBS_COLUMNS = ("audit_id", "audit_sha", "asserted_actor", "resolved_actor", "via", "token_kind", "token_fp",
               "token_project", "would_refuse", "reasons", "enforced")
COLUMNS = ("at", "actor", "verified", "via", "token_actor", "method", "path", "status", "project", "ref", "body_sha",
           "body_keys", "summary", "profile_hash")


def _canon(row):
    return json.dumps([row[c] for c in COLUMNS], separators=(",", ":"), default=str)


def _canon_obs(row):
    return json.dumps([row[c] for c in OBS_COLUMNS], separators=(",", ":"), default=str)


def _clean(v, n=80):
    return None if v is None else re.sub(r"[\x00-\x1f\x7f]+", " ", str(v))[:n]


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
        self._broken = None            # the first broken row a walk found; reported until a full walk passes
        self._obs_good = (0, GENESIS, 0)
        self._obs_broken = None
        self.identity_errors = 0       # shadow records skipped because they could not be written

    def record(self, *, actor, verified, via, method, path, status, token_actor=None, project=None, ref=None,
               body=None, summary="", profile_hash=None, identity=None):
        """Append one audit row. `identity`: identity.resolve(...) for this write (Phase 2 shadow record), written in
        the same transaction as an identity_observations row; None for system rows."""
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
            cur = self.db.execute(f"INSERT INTO audit_events ({', '.join(COLUMNS)}, prev_sha, sha) VALUES "
                                  f"({', '.join('?' * (len(COLUMNS) + 2))})", (*[row[c] for c in COLUMNS], prev_sha, sha))
            if identity is not None:
                # A bad shadow record must never cost the audit row itself.
                self.db.execute("SAVEPOINT audit_identity")
                try:
                    self._observe(cur.lastrowid, sha, identity)
                    self.db.execute("RELEASE audit_identity")
                except Exception:  # noqa: BLE001
                    self.db.execute("ROLLBACK TO audit_identity")
                    self.db.execute("RELEASE audit_identity")
                    self.identity_errors += 1
            self.db.execute("COMMIT" if own else "RELEASE audit_record")
        except BaseException:
            if self.db.in_transaction:     # SQLite may already have rolled it all back (disk full, I/O)
                self.db.execute("ROLLBACK" if own else "ROLLBACK TO audit_record")
                if not own:
                    self.db.execute("RELEASE audit_record")
            raise
        return sha

    def _observe(self, audit_id, audit_sha, who):
        reasons = [r for r in who.get("reasons") or [] if isinstance(r, str)][:10]
        obs = {"audit_id": audit_id, "audit_sha": audit_sha, "asserted_actor": _clean(who.get("assertedActor")),
               "resolved_actor": _clean(who.get("resolvedActor") or "unknown"), "via": who.get("via") or "none",
               "token_kind": who.get("tokenKind"), "token_fp": _clean(who.get("tokenFingerprint"), 20),
               "token_project": _clean(who.get("tokenProject"), 40), "would_refuse": 1 if reasons else 0,
               "reasons": json.dumps(reasons), "enforced": 0}
        prev = self.db.execute("SELECT sha FROM identity_observations ORDER BY audit_id DESC LIMIT 1").fetchone()
        prev_sha = prev[0] if prev else GENESIS
        sha = hashlib.sha256((prev_sha + _canon_obs(obs)).encode()).hexdigest()
        self.db.execute(f"INSERT INTO identity_observations ({', '.join(OBS_COLUMNS)}, prev_sha, sha) VALUES "
                        f"({', '.join('?' * (len(OBS_COLUMNS) + 2))})", (*[obs[c] for c in OBS_COLUMNS], prev_sha, sha))

    def verify_identity(self, full=False):
        """Walk the identity_observations chain, and check each row still names its audit row's sha.
        {ok, checked, brokenAt, full}, like verify()."""
        if not full and self._obs_broken is not None:
            return {"ok": False, "checked": self._obs_good[2], "brokenAt": self._obs_broken, "full": False}
        start_id, prev, n = (0, GENESIS, 0) if full else self._obs_good
        if start_id and self.db.execute("SELECT 1 FROM identity_observations WHERE audit_id=? AND sha=?",
                                        (start_id, prev)).fetchone() is None:
            start_id, prev, n = 0, GENESIS, 0
        for r in self.db.execute(f"SELECT o.{', o.'.join(OBS_COLUMNS)}, o.prev_sha, o.sha, a.sha "
                                 f"FROM identity_observations o LEFT JOIN audit_events a ON a.id = o.audit_id "
                                 f"WHERE o.audit_id > ? ORDER BY o.audit_id", (start_id,)):
            row = dict(zip(OBS_COLUMNS, r[:len(OBS_COLUMNS)]))
            prev_sha, sha, audit_sha = r[-3], r[-2], r[-1]
            if prev_sha != prev or audit_sha != row["audit_sha"] \
                    or hashlib.sha256((prev + _canon_obs(row)).encode()).hexdigest() != sha:
                self._obs_broken = row["audit_id"]
                return {"ok": False, "checked": n, "brokenAt": row["audit_id"], "full": full}
            prev, n, start_id = sha, n + 1, row["audit_id"]
        self._obs_good, self._obs_broken = (start_id, prev, n), None
        return {"ok": True, "checked": n, "brokenAt": None, "full": full}

    def identity_summary(self, since=None):
        """Phase 2 shadow: what enforcing verified identity would refuse, by reason and by resolved actor."""
        since = since if since is not None else self.clock() - 30 * 86400
        total, refuse, by_reason, by_resolved, missing = 0, 0, {}, {}, 0
        for resolved, asserted, would, reasons, n in self.db.execute(
                "SELECT o.resolved_actor, o.asserted_actor IS NULL, o.would_refuse, o.reasons, COUNT(*) "
                "FROM identity_observations o JOIN audit_events a ON a.id = o.audit_id WHERE a.at >= ? "
                "GROUP BY o.resolved_actor, o.asserted_actor IS NULL, o.would_refuse, o.reasons", (since,)):
            total += n
            refuse += n if would else 0
            missing += n if asserted else 0
            by_resolved[resolved] = by_resolved.get(resolved, 0) + n
            for reason in json.loads(reasons or "[]"):
                by_reason[reason] = by_reason.get(reason, 0) + n
        return {"since": since, "total": total, "wouldRefuse": refuse, "missingHeader": missing,
                "byReason": by_reason, "byResolved": by_resolved, "enforced": False}

    def observations(self, ids):
        """identity_observations rows for these audit ids, as {audit id: record}."""
        ids = [int(i) for i in ids][:500]
        if not ids:
            return {}
        out = {}
        for r in self.db.execute(f"SELECT {', '.join(OBS_COLUMNS)} FROM identity_observations WHERE audit_id IN "
                                 f"({', '.join('?' * len(ids))})", ids):
            d = dict(zip(OBS_COLUMNS, r))
            out[d["audit_id"]] = {"assertedActor": d["asserted_actor"], "resolvedActor": d["resolved_actor"],
                                  "via": d["via"], "tokenKind": d["token_kind"], "tokenFingerprint": d["token_fp"],
                                  "tokenProject": d["token_project"], "wouldRefuse": bool(d["would_refuse"]),
                                  "reasons": json.loads(d["reasons"] or "[]"), "enforced": False}
        return out

    def verify(self, full=False):
        """Walk the chain. By default only rows added since the last intact walk (cheap enough to run on every look);
        `full` walks from the first row, which also catches an edit to rows already checked. {ok, checked, brokenAt,
        full}. Once any walk finds a break it is reported on every look until a full walk passes again."""
        if not full and self._broken is not None:
            return {"ok": False, "checked": self._good[2], "brokenAt": self._broken, "full": False}
        start_id, prev, n = (0, GENESIS, 0) if full else self._good
        if start_id and self.db.execute("SELECT 1 FROM audit_events WHERE id=? AND sha=?", (start_id, prev)).fetchone() \
                is None:
            start_id, prev, n = 0, GENESIS, 0       # the row we stopped at is gone or changed: walk it all
        for r in self.db.execute(f"SELECT id, {', '.join(COLUMNS)}, prev_sha, sha FROM audit_events WHERE id > ? "
                                 f"ORDER BY id", (start_id,)):
            row = dict(zip(COLUMNS, r[1:1 + len(COLUMNS)]))
            prev_sha, sha = r[-2], r[-1]
            if prev_sha != prev or hashlib.sha256((prev + _canon(row)).encode()).hexdigest() != sha:
                self._broken = r[0]
                return {"ok": False, "checked": n, "brokenAt": r[0], "full": full}
            prev, n, start_id = sha, n + 1, r[0]
        self._good, self._broken = (start_id, prev, n), None
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
        obs = self.observations([e["id"] for e in out])
        for e in out:
            e["identity"] = obs.get(e["id"])
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
