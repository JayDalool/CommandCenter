"""Verified actor identity — groundwork (v2 Phase 1, PR 7; docs/COMMANDCENTER_V2_DISCOVERY.md §9, Phase 1 item 6).

Today every /api write names its actor with `X-CCD-Actor`, which is self-asserted: anything holding ccd's token can
claim to be `jay`. This module records how far each claim can be trusted, without refusing anything yet:

    developer   the request carries a valid Developer Unlock session (only Jay can unlock) → verified `jay`
    token       the request carries `X-CCD-Actor-Token`, a per-actor token Jay issued → verified as that agent
    none        nothing backs the claim → unverified (the write still happens, exactly as before)

An actor token is for an agent (`agent:<name>`), is issued only by Jay with Developer Unlock, is shown once (ccd keeps
its SHA-256), expires, and can be revoked. A token that names a different actor than `X-CCD-Actor` is recorded as a
mismatch. Enforcing "X-CCD-Actor must match its token" is Phase 2; the audit trail measures what it would refuse.
"""
import hashlib
import hmac
import re
import secrets
import time

ACTOR_RE = re.compile(r"agent:[a-z0-9_:-]{1,64}")
HEADER = "x-ccd-actor-token"
DEFAULT_TTL_DAYS = 30
MAX_TTL_DAYS = 365


class IdentityError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def fingerprint(token_sha):
    return f"{token_sha[:4]}-{token_sha[4:8]}" if token_sha else None


class ActorTokens:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock

    def issue(self, actor, by, ttl_days=DEFAULT_TTL_DAYS, note=""):
        """A per-actor token for an agent. Returned ONCE. Only Jay issues; never for `jay` (Jay uses Unlock)."""
        if by != "jay":
            raise IdentityError(403, "only Jay issues actor tokens")
        if not isinstance(actor, str) or not ACTOR_RE.fullmatch(actor):
            raise IdentityError(400, "actor must be agent:<name> (Jay is verified by Developer Unlock, not a token)")
        try:
            ttl = float(ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS)
        except (TypeError, ValueError):
            raise IdentityError(400, "ttlDays must be a number") from None
        if not 0 < ttl <= MAX_TTL_DAYS:
            raise IdentityError(400, f"ttlDays must be between 1 and {MAX_TTL_DAYS}")
        note = re.sub(r"[\x00-\x1f\x7f]+", " ", str(note or ""))[:200]
        token = "cca_" + secrets.token_urlsafe(32)
        now = self.clock()
        with self.db:
            cur = self.db.execute("INSERT INTO actor_tokens (actor, token_sha, issued_at, issued_by, expires_at, note) "
                                  "VALUES (?,?,?,?,?,?)", (actor, _sha(token), now, "jay", now + ttl * 86400, note))
        return {"id": cur.lastrowid, "actor": actor, "token": token, "fingerprint": fingerprint(_sha(token)),
                "expiresAt": now + ttl * 86400}

    def revoke(self, tid, by):
        if by != "jay":
            raise IdentityError(403, "only Jay revokes actor tokens")
        row = self.db.execute("SELECT revoked_at FROM actor_tokens WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise IdentityError(404, f"no actor token {tid}")
        if row[0] is not None:
            raise IdentityError(409, "already revoked")
        with self.db:
            self.db.execute("UPDATE actor_tokens SET revoked_at=? WHERE id=?", (self.clock(), tid))
        return self.get(tid)

    def verify(self, token):
        """The agent a presented token proves, or None (unknown, expired, revoked, or malformed)."""
        if not isinstance(token, str) or not token.startswith("cca_") or len(token) > 100:
            return None
        sha = _sha(token)
        row = self.db.execute("SELECT actor, token_sha, expires_at, revoked_at FROM actor_tokens WHERE token_sha=?",
                              (sha,)).fetchone()
        if row is None or not hmac.compare_digest(row[1], sha) or row[3] is not None or row[2] <= self.clock():
            return None
        return row[0]

    def get(self, tid):
        return next((t for t in self.list() if t["id"] == tid), None)

    def list(self):
        now = self.clock()
        return [{"id": r[0], "actor": r[1], "fingerprint": fingerprint(r[2]), "issuedAt": r[3], "expiresAt": r[4],
                 "revokedAt": r[5], "note": r[6],
                 "status": "revoked" if r[5] is not None else "expired" if r[4] <= now else "active"}
                for r in self.db.execute("SELECT id, actor, token_sha, issued_at, expires_at, revoked_at, note "
                                         "FROM actor_tokens ORDER BY id DESC LIMIT 200")]


def identify(claimed, developer, token_actor):
    """How far a write's actor claim can be trusted. `token_actor` is ActorTokens.verify(...) of the presented
    header (None when absent or invalid). Never raises and never changes who the write is recorded as."""
    if developer and claimed == "jay":
        return {"actor": claimed, "verified": True, "via": "developer", "tokenActor": None, "mismatch": False}
    if token_actor:
        return {"actor": claimed, "verified": token_actor == claimed, "via": "token", "tokenActor": token_actor,
                "mismatch": token_actor != claimed}
    return {"actor": claimed, "verified": False, "via": "none", "tokenActor": None, "mismatch": False}


def developer_session_valid(gate, sid):
    """Is `sid` a live Developer Unlock session? Read-only: unlike DeveloperGate.check it neither refreshes the idle
    timer nor prunes, so recording who made a write never keeps a session alive (security.py is left unchanged)."""
    if gate is None or not isinstance(sid, str) or not sid:
        return False
    try:
        now = gate.clock()
        for k, (made, used, ttl, idle) in list(gate.sessions.items()):
            if hmac.compare_digest(k, sid):
                return now - made <= ttl and now - used <= idle
    except Exception:  # noqa: BLE001 — identity is a record; a gate it can't read means "not verified"
        return False
    return False
