"""Verified actor identity — groundwork (v2 Phase 1, PR 7) and Phase 2 shadow step 1 (typed tokens, resolvedActor).

Today every /api write names its actor with `X-CCD-Actor`, which is self-asserted: anything holding ccd's token can
claim to be `jay`, and a write with no header at all is filed under `jay`. This module records how far each claim can
be trusted, without refusing anything:

    developer   the request carries a valid Developer Unlock session (only Jay can unlock) → verified `jay`
    token       the request carries `X-CCD-Actor-Token`, a typed identity token Jay issued → verified as its subject
    none        nothing backs the claim → unverified (the write still happens, exactly as before)

Identity tokens (Phase 2, docs/COMMANDCENTER_V2_DISCOVERY.md "Phase 2 preparation decisions") are typed by prefix so
a leaked one is recognisable: `cca_a_` for an agent (`agent:<name>`), `cca_s_` for a service (`svc:<name>`). A token
may be bound to one project. Jay issues them with Developer Unlock; each is shown once (ccd keeps its SHA-256),
expires, and can be revoked. Tokens issued before Phase 2 (`cca_` + 43 characters, table `actor_tokens`) still
verify; they are listed with negative ids and revoked by that negative id.

`resolve()` is the Phase 2 shadow record: who the request PROVES to be (`resolvedActor`), next to what it ASSERTED
(`assertedActor`, None when the header is missing) and the reasons Phase 2 enforcement would refuse it. The recorded
`actor` never changes, and nothing here refuses a request: `enforced` is always False (the database refuses anything
else).
"""
import hashlib
import hmac
import re
import secrets
import time

ACTOR_RE = re.compile(r"agent:[a-z0-9_:-]{1,64}")
SERVICE_RE = re.compile(r"svc:[a-z0-9_-]{1,64}")
PROJECT_RE = re.compile(r"[a-z0-9-]{1,40}")
HEADER = "x-ccd-actor-token"
DEFAULT_TTL_DAYS = 30
MAX_TTL_DAYS = 365
PREFIX = {"agent": "cca_a_", "service": "cca_s_"}
KIND_OF_PREFIX = {v: k for k, v in PREFIX.items()}
# A pre-Phase-2 token: "cca_" + token_urlsafe(32), which is 43 characters of [A-Za-z0-9_-].
LEGACY_RE = re.compile(r"cca_[A-Za-z0-9_-]{43}")
# A typed token: its prefix + token_urlsafe(32). Length tells the two apart (49 vs 47), so a legacy token whose random
# part happens to start "a_" or "s_" is still read as legacy.
TYPED_RE = re.compile(r"cca_[as]_[A-Za-z0-9_-]{43}")


class IdentityError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def fingerprint(token_sha):
    return f"{token_sha[:4]}-{token_sha[4:8]}" if token_sha else None


def kind_of(subject):
    """'agent' or 'service' for a subject a token may be issued to, else None (Jay is never a token subject)."""
    if isinstance(subject, str) and ACTOR_RE.fullmatch(subject):
        return "agent"
    if isinstance(subject, str) and SERVICE_RE.fullmatch(subject):
        return "service"
    return None


class ActorTokens:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock

    def issue(self, actor, by, ttl_days=DEFAULT_TTL_DAYS, note="", project=None):
        """A typed identity token for an agent or a service. Returned ONCE. Only Jay issues; never for `jay` (Jay is
        verified by Developer Unlock). `project`: optional binding to one project key (recorded and checked in the
        shadow record; it refuses nothing yet)."""
        if by != "jay":
            raise IdentityError(403, "only Jay issues actor tokens")
        kind = kind_of(actor)
        if kind is None:
            raise IdentityError(400, "actor must be agent:<name> or svc:<name> (Jay is verified by Developer Unlock, "
                                     "not a token)")
        if project is not None and (not isinstance(project, str) or not PROJECT_RE.fullmatch(project)):
            raise IdentityError(400, "project must be a project key")
        try:
            ttl = float(ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS)
        except (TypeError, ValueError):
            raise IdentityError(400, "ttlDays must be a number") from None
        if not 0 < ttl <= MAX_TTL_DAYS:
            raise IdentityError(400, f"ttlDays must be between 1 and {MAX_TTL_DAYS}")
        note = re.sub(r"[\x00-\x1f\x7f]+", " ", str(note or ""))[:200]
        token = PREFIX[kind] + secrets.token_urlsafe(32)
        now = self.clock()
        with self.db:
            cur = self.db.execute("INSERT INTO identity_tokens (kind, subject, project, token_sha, issued_at, issued_by, "
                                  "expires_at, note) VALUES (?,?,?,?,?,?,?,?)",
                                  (kind, actor, project, _sha(token), now, "jay", now + ttl * 86400, note))
        return {"id": cur.lastrowid, "actor": actor, "kind": kind, "project": project, "token": token,
                "fingerprint": fingerprint(_sha(token)), "expiresAt": now + ttl * 86400}

    def revoke(self, tid, by):
        """Revoke one token. A positive id is a typed token; a negative id is a pre-Phase-2 token (as list() shows)."""
        if by != "jay":
            raise IdentityError(403, "only Jay revokes actor tokens")
        table = "actor_tokens" if tid < 0 else "identity_tokens"
        row = self.db.execute(f"SELECT revoked_at FROM {table} WHERE id=?", (abs(tid),)).fetchone()
        if row is None or tid == 0:
            raise IdentityError(404, f"no actor token {tid}")
        if row[0] is not None:
            raise IdentityError(409, "already revoked")
        with self.db:
            self.db.execute(f"UPDATE {table} SET revoked_at=? WHERE id=?", (self.clock(), abs(tid)))
        return self.get(tid)

    def lookup(self, token):
        """What a presented token proves: {actor, kind, project, fingerprint, legacy}, or None (unknown, expired,
        revoked, or malformed). Never raises."""
        if not isinstance(token, str) or len(token) > 100:
            return None
        legacy = LEGACY_RE.fullmatch(token) is not None
        kind = None if legacy or not TYPED_RE.fullmatch(token) else KIND_OF_PREFIX[token[:6]]
        if kind is None and not legacy:
            return None
        sha = _sha(token)
        try:
            if legacy:
                row = self.db.execute("SELECT actor, 'agent', NULL, token_sha, expires_at, revoked_at FROM actor_tokens "
                                      "WHERE token_sha=?", (sha,)).fetchone()
            else:
                row = self.db.execute("SELECT subject, kind, project, token_sha, expires_at, revoked_at "
                                      "FROM identity_tokens WHERE token_sha=? AND kind=?", (sha, kind)).fetchone()
        except Exception:  # noqa: BLE001 — identity is a record; an unreadable store means "not verified"
            return None
        if row is None or not hmac.compare_digest(row[3], sha) or row[5] is not None or row[4] <= self.clock():
            return None
        return {"actor": row[0], "kind": row[1], "project": row[2], "fingerprint": fingerprint(sha), "legacy": legacy}

    def verify(self, token):
        """The subject a presented token proves, or None."""
        hit = self.lookup(token)
        return hit["actor"] if hit else None

    def get(self, tid):
        """One token as list() shows it, however old (list() keeps only the newest 200 of each table)."""
        hit = next((t for t in self.list() if t["id"] == tid), None)
        if hit is not None or not isinstance(tid, int) or tid == 0:
            return hit
        now = self.clock()
        if tid < 0:
            r = self.db.execute("SELECT id, actor, token_sha, issued_at, expires_at, revoked_at, note FROM actor_tokens "
                                "WHERE id=?", (-tid,)).fetchone()
            row = r and {"id": -r[0], "actor": r[1], "kind": "agent", "project": None, "fingerprint": fingerprint(r[2]),
                         "issuedAt": r[3], "expiresAt": r[4], "revokedAt": r[5], "note": r[6], "legacy": True}
        else:
            r = self.db.execute("SELECT id, kind, subject, project, token_sha, issued_at, expires_at, revoked_at, note "
                                "FROM identity_tokens WHERE id=?", (tid,)).fetchone()
            row = r and {"id": r[0], "actor": r[2], "kind": r[1], "project": r[3], "fingerprint": fingerprint(r[4]),
                         "issuedAt": r[5], "expiresAt": r[6], "revokedAt": r[7], "note": r[8], "legacy": False}
        if not row:
            return None
        row["status"] = "revoked" if row["revokedAt"] is not None else "expired" if row["expiresAt"] <= now else "active"
        return row

    def list(self):
        now = self.clock()

        def status(expires, revoked):
            return "revoked" if revoked is not None else "expired" if expires <= now else "active"
        typed = [{"id": r[0], "actor": r[2], "kind": r[1], "project": r[3], "fingerprint": fingerprint(r[4]),
                  "issuedAt": r[5], "expiresAt": r[6], "revokedAt": r[7], "note": r[8], "legacy": False,
                  "status": status(r[6], r[7])}
                 for r in self.db.execute("SELECT id, kind, subject, project, token_sha, issued_at, expires_at, "
                                          "revoked_at, note FROM identity_tokens ORDER BY id DESC LIMIT 200")]
        legacy = [{"id": -r[0], "actor": r[1], "kind": "agent", "project": None, "fingerprint": fingerprint(r[2]),
                   "issuedAt": r[3], "expiresAt": r[4], "revokedAt": r[5], "note": r[6], "legacy": True,
                   "status": status(r[4], r[5])}
                  for r in self.db.execute("SELECT id, actor, token_sha, issued_at, expires_at, revoked_at, note "
                                           "FROM actor_tokens ORDER BY id DESC LIMIT 200")]
        return typed + legacy


def identify(claimed, developer, token_actor, header_missing=False):
    """How far a write's actor claim can be trusted. `token_actor` is ActorTokens.verify(...) of the presented
    header (None when absent or invalid). `header_missing`: no X-CCD-Actor was sent (so `claimed` is the default
    `jay`). Never raises and never changes who the write is recorded as."""
    if developer and claimed == "jay":
        return {"actor": claimed, "verified": True, "via": "developer", "tokenActor": None, "mismatch": False}
    if token_actor and header_missing and kind_of(token_actor) == "service":
        # A service sends no X-CCD-Actor (it accepts only jay or agent:<name>); its token is its claim. The row's
        # actor stays the default, and is not verified as `jay`.
        return {"actor": claimed, "verified": False, "via": "token", "tokenActor": token_actor, "mismatch": False}
    if token_actor:
        return {"actor": claimed, "verified": token_actor == claimed, "via": "token", "tokenActor": token_actor,
                "mismatch": token_actor != claimed}
    return {"actor": claimed, "verified": False, "via": "none", "tokenActor": None, "mismatch": False}


REASONS = ("missing_header", "unverified", "asserted_mismatch", "jay_without_unlock", "project_mismatch")


def resolve(asserted, developer, token_hit, project=None):
    """The Phase 2 shadow record for one write. `asserted`: the raw X-CCD-Actor header (None when missing).
    `developer`: a live Developer Unlock session. `token_hit`: ActorTokens.lookup(...) of the presented token (None
    when absent or invalid). `project`: the project the write touches: the project of the ticket the path
    names, else the body's `project` (daemon._write_project); None when neither names one, and then no project_mismatch.

    Returns {assertedActor, resolvedActor, via, tokenKind, tokenFingerprint, tokenProject, wouldRefuse, reasons,
    enforced}. resolvedActor is "jay" only with Developer Unlock, a token's subject with a valid token, else
    "unknown". Never raises, never refuses: `enforced` is always False."""
    if developer:
        resolved, via = "jay", "developer"
    elif token_hit:
        resolved, via = token_hit["actor"], "token"
    else:
        resolved, via = "unknown", "none"
    asserted = asserted or None            # an empty header is a missing one
    service = via == "token" and token_hit.get("kind") == "service"
    # What ccd records today when the header is missing is `jay`; a service sends none (X-CCD-Actor accepts only jay
    # or agent:<name>), so for a service token the token itself is the claim.
    effective = asserted or (resolved if service else "jay")
    reasons = []
    if asserted is None and resolved != "jay" and not service:
        reasons.append("missing_header")
    if resolved == "unknown":
        reasons.append("unverified")
    elif effective != resolved:
        reasons.append("asserted_mismatch")
    if effective == "jay" and not developer:
        reasons.append("jay_without_unlock")
    bound = token_hit.get("project") if token_hit and via == "token" else None
    if bound and project and bound != project:
        reasons.append("project_mismatch")
    return {"assertedActor": asserted, "resolvedActor": resolved, "via": via,
            "tokenKind": token_hit["kind"] if token_hit and via == "token" else None,
            "tokenFingerprint": token_hit["fingerprint"] if token_hit and via == "token" else None,
            "tokenProject": bound, "wouldRefuse": bool(reasons), "reasons": reasons, "enforced": False}


def developer_session_valid(gate, sid):
    """Is `sid` a live Developer Unlock session? Read-only: unlike DeveloperGate.check it neither refreshes the idle
    timer nor prunes, so recording who made a write never keeps a session alive."""
    if gate is None or not isinstance(sid, str) or not sid:
        return False
    try:
        return bool(gate.peek(sid))
    except Exception:  # noqa: BLE001 — identity is a record; a gate it can't read means "not verified"
        return False
