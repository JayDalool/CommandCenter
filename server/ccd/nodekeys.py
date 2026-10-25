"""Worker node keys and signed requests — Phase 2 shadow step 2 (Jay, 2026-10-25). RECORDED ONLY.

Today a worker node proves itself with a bearer token (ccd/workers.py). Phase 2 adds a key that never leaves the node:
the node makes an Ed25519 keypair, sends the public key when it enrols, and signs each heartbeat. The key's
fingerprint is returned by enrol and by GET /api/workers only; Settings → Workers does not show it yet. So approving a
node does NOT approve its key: a key stays "not approved" (and every heartbeat says key_not_approved) until a later
change lets Jay compare the fingerprint in the UI and approve the key itself. Revoking a node revokes its key.

Every enrol and heartbeat is then checked and an observation is kept (`node_observations`, a hash chain of its own)
with the reasons Phase 2 enforcement would refuse it:

    unsigned          no X-CCD-Node-Signature header
    malformed         the header cannot be parsed
    no_key            the node has no key on record
    key_not_approved  its key is waiting for Jay
    bad_signature     the signature does not verify with the node's key
    stale_timestamp   the signed time is more than SKEW seconds from ccd's clock
    replayed_nonce    the nonce was already seen from this node within NONCE_TTL
    node_pending      a node Jay has not approved sent a heartbeat
    node_revoked      a revoked node sent a heartbeat
    bad_node_token    the node token was wrong (the request was already refused for that, as before)
    bad_key           an enrolment sent a public key that is not an Ed25519 key
    duplicate_key     an enrolment sent a key already recorded for a node (keys are never reused)
    node_has_key      an enrolment sent a new key for a node that still has a live one (the old key stays)

Nothing here refuses a request or changes its answer: `enforced` is always 0 (the table refuses anything else). It
runs only when config.json says "phase2_node_shadow": true.

The signed message (version 1), UTF-8, lines joined by "\\n":

    ccd-node-v1 / METHOD / path / node id / unix seconds / nonce / sha256(canonical JSON body)

where canonical JSON is json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True). The header is
`X-CCD-Node-Signature: v1 ts=<seconds> nonce=<16-64 url-safe chars> sig=<base64url signature>`.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time

try:        # only the shadow check needs it; ccd starts without it, with the check off (daemon.py)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    AVAILABLE = True
except ImportError:  # pragma: no cover — exercised by a test that hides the module
    InvalidSignature = serialization = Ed25519PrivateKey = Ed25519PublicKey = None
    AVAILABLE = False

VERSION = "ccd-node-v1"
HEADER = "x-ccd-node-signature"
SKEW = 60                   # seconds either way
NONCE_TTL = 600             # seconds a nonce is remembered
NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
SIG_RE = re.compile(r"v1 ts=(\d{1,12}) nonce=([A-Za-z0-9_-]{16,64}) sig=([A-Za-z0-9_-]{86})")
PUB_RE = re.compile(r"[A-Za-z0-9_-]{43}")
GENESIS = "0" * 64
REASONS = ("unsigned", "malformed", "no_key", "key_not_approved", "bad_signature", "stale_timestamp",
           "replayed_nonce", "node_pending", "node_revoked", "bad_node_token", "bad_key", "duplicate_key",
           "node_has_key")
OBS_COLUMNS = ("at", "node_id", "kind", "outcome", "key_fp", "signed", "verified", "skew", "would_refuse", "reasons",
               "enforced")


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(body):
    return json.dumps(body if body is not None else {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def message(method, path, node, ts, nonce, body):
    digest = hashlib.sha256(canonical(body).encode()).hexdigest()
    return "\n".join((VERSION, str(method).upper(), str(path), str(node), str(int(ts)), str(nonce), digest)).encode()


def public_key(text):
    """An Ed25519 public key from its 43-character base64url form, or None."""
    if not AVAILABLE or not isinstance(text, str) or not PUB_RE.fullmatch(text):
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(_b64d(text))
    except (ValueError, TypeError):
        return None


def key_fingerprint(text):
    """What Jay compares before approving: 16 hex characters of the key's SHA-256, in four groups."""
    h = hashlib.sha256(_b64d(text)).hexdigest()[:16]
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def sign_header(private_key, method, path, node, body, ts=None, nonce=None):
    """The X-CCD-Node-Signature value for one request (used by a node; and by tests)."""
    ts = int(time.time() if ts is None else ts)
    nonce = nonce or secrets.token_urlsafe(18)
    sig = private_key.sign(message(method, path, node, ts, nonce, body))
    return f"v1 ts={ts} nonce={nonce} sig={_b64e(sig)}"


def public_text(private_key):
    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64e(raw)


def parse(header):
    """(ts, nonce, signature bytes) or None."""
    m = SIG_RE.fullmatch(header.strip()) if isinstance(header, str) else None
    if not m:
        return None
    try:
        sig = _b64d(m.group(3))
    except (ValueError, TypeError):
        return None
    return int(m.group(1)), m.group(2), sig


class NodeKeys:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock
        self._good = (0, GENESIS, 0)
        self._broken = None
        self.errors = 0          # observations skipped because they could not be written

    # ---------- keys ----------

    def add(self, node, text, by):
        """Record a node's public key at enrolment, not approved. Returns (fingerprint, None), or (None, reason) for
        a bad key, a key already recorded (keys are never reused, revoked ones included), or a node that still has a
        live key."""
        if public_key(text) is None:
            return None, "bad_key"
        fp = key_fingerprint(text)
        if self.key(node) is not None:
            return None, "node_has_key"
        try:
            self.db.execute("INSERT INTO node_keys (node_id, public_key, key_fp, added_at, added_by) VALUES (?,?,?,?,?)",
                            (node, text, fp, self.clock(), by))
        except sqlite3.IntegrityError:
            return None, "duplicate_key"
        return fp, None

    def approve(self, node):
        """Approve a node's waiting key. Not called yet: it needs a UI where Jay compares the fingerprint first."""
        self.db.execute("UPDATE node_keys SET approved_at=?, approved_by='jay' WHERE node_id=? AND revoked_at IS NULL "
                        "AND approved_at IS NULL", (self.clock(), node))

    def revoke(self, node):
        self.db.execute("UPDATE node_keys SET revoked_at=? WHERE node_id=? AND revoked_at IS NULL", (self.clock(), node))

    def key(self, node):
        r = self.db.execute("SELECT public_key, key_fp, approved_at FROM node_keys WHERE node_id=? AND revoked_at IS NULL",
                            (node,)).fetchone()
        return {"publicKey": r[0], "fingerprint": r[1], "approved": r[2] is not None} if r else None

    def keys(self):
        return {r[0]: {"fingerprint": r[1], "approved": r[2] is not None}
                for r in self.db.execute("SELECT node_id, key_fp, approved_at FROM node_keys WHERE revoked_at IS NULL")}

    # ---------- the shadow check ----------

    def check(self, node, method, path, header, body, state, token_ok=True):
        """What Phase 2 would say about one heartbeat. `state`: the node's stored status (pending|active|revoked) or
        None. Never raises. Records the nonce so a replay is seen."""
        reasons, signed, verified, skew = [], header is not None and header != "", False, None
        k = self.key(node) if state is not None else None
        if not token_ok:
            reasons.append("bad_node_token")
        if state == "pending":
            reasons.append("node_pending")
        elif state == "revoked":
            reasons.append("node_revoked")
        if not signed:
            reasons.append("unsigned")
        parsed = parse(header) if signed else None
        if signed and parsed is None:
            reasons.append("malformed")
        if k is None:
            reasons.append("no_key")
        elif not k["approved"]:
            reasons.append("key_not_approved")
        if parsed:
            ts, nonce, sig = parsed
            now = self.clock()
            skew = round(now - ts, 3)
            if abs(skew) > SKEW:
                reasons.append("stale_timestamp")
            if k is not None:
                try:
                    public_key(k["publicKey"]).verify(sig, message(method, path, node, ts, nonce, body))
                    verified = True
                except (InvalidSignature, ValueError, TypeError, AttributeError):
                    reasons.append("bad_signature")
            if verified and self._seen(node, nonce, now):
                reasons.append("replayed_nonce")
        return {"signed": signed, "verified": verified, "skew": skew, "keyFingerprint": k["fingerprint"] if k else None,
                "reasons": reasons, "wouldRefuse": bool(reasons), "enforced": False}

    def _seen(self, node, nonce, now):
        """Was this nonce already used by this node within NONCE_TTL? Remembers it either way."""
        self.db.execute("DELETE FROM node_nonces WHERE seen_at < ?", (now - NONCE_TTL,))
        cur = self.db.execute("INSERT OR IGNORE INTO node_nonces (node_id, nonce, seen_at) VALUES (?,?,?)",
                              (node, nonce, now))
        return cur.rowcount == 0

    def observe(self, node, kind, outcome, result):
        """Append one observation (its own hash chain). Never raises: a failure is counted in `errors`."""
        try:
            reasons = [r for r in result.get("reasons") or [] if r in REASONS]
            row = {"at": self.clock(), "node_id": re.sub(r"[^a-z0-9-]", "?", str(node or ""))[:40] or "?",
                   "kind": kind, "outcome": int(outcome), "key_fp": result.get("keyFingerprint"),
                   "signed": 1 if result.get("signed") else 0, "verified": 1 if result.get("verified") else 0,
                   "skew": result.get("skew"), "would_refuse": 1 if reasons else 0, "reasons": json.dumps(reasons),
                   "enforced": 0}
            own = not self.db.in_transaction
            self.db.execute("BEGIN IMMEDIATE" if own else "SAVEPOINT node_obs")
            try:
                prev = self.db.execute("SELECT sha FROM node_observations ORDER BY id DESC LIMIT 1").fetchone()
                prev_sha = prev[0] if prev else GENESIS
                sha = hashlib.sha256((prev_sha + _canon(row)).encode()).hexdigest()
                self.db.execute(f"INSERT INTO node_observations ({', '.join(OBS_COLUMNS)}, prev_sha, sha) VALUES "
                                f"({', '.join('?' * (len(OBS_COLUMNS) + 2))})",
                                (*[row[c] for c in OBS_COLUMNS], prev_sha, sha))
                self.db.execute("COMMIT" if own else "RELEASE node_obs")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK" if own else "ROLLBACK TO node_obs")
                    if not own:
                        self.db.execute("RELEASE node_obs")
                raise
        except Exception:  # noqa: BLE001 — a shadow record must never break the request
            self.errors += 1

    def verify(self, full=False):
        """Walk the observation chain: {ok, checked, brokenAt, full}."""
        if not full and self._broken is not None:
            return {"ok": False, "checked": self._good[2], "brokenAt": self._broken, "full": False}
        start, prev, n = (0, GENESIS, 0) if full else self._good
        if start and self.db.execute("SELECT 1 FROM node_observations WHERE id=? AND sha=?",
                                     (start, prev)).fetchone() is None:
            start, prev, n = 0, GENESIS, 0
        for r in self.db.execute(f"SELECT id, {', '.join(OBS_COLUMNS)}, prev_sha, sha FROM node_observations "
                                 f"WHERE id > ? ORDER BY id", (start,)):
            row = dict(zip(OBS_COLUMNS, r[1:1 + len(OBS_COLUMNS)]))
            if r[-2] != prev or hashlib.sha256((prev + _canon(row)).encode()).hexdigest() != r[-1]:
                self._broken = r[0]
                return {"ok": False, "checked": n, "brokenAt": r[0], "full": full}
            prev, n, start = r[-1], n + 1, r[0]
        self._good, self._broken = (start, prev, n), None
        return {"ok": True, "checked": n, "brokenAt": None, "full": full}

    def summary(self, since=None):
        """Per node: observations, would-refuse count and reasons, in the window (default 30 days)."""
        since = since if since is not None else self.clock() - 30 * 86400
        nodes, total, refuse = {}, 0, 0
        for node, would, reasons, n in self.db.execute(
                "SELECT node_id, would_refuse, reasons, COUNT(*) FROM node_observations WHERE at >= ? "
                "GROUP BY node_id, would_refuse, reasons", (since,)):
            d = nodes.setdefault(node, {"total": 0, "wouldRefuse": 0, "byReason": {}})
            d["total"] += n
            total += n
            if would:
                d["wouldRefuse"] += n
                refuse += n
            for reason in json.loads(reasons or "[]"):
                d["byReason"][reason] = d["byReason"].get(reason, 0) + n
        return {"since": since, "total": total, "wouldRefuse": refuse, "nodes": nodes, "enforced": False}


def _canon(row):
    return json.dumps([row[c] for c in OBS_COLUMNS], separators=(",", ":"), default=str)


# ---------- on the node: make a keypair ----------

def init(directory):
    """Make an Ed25519 keypair in `directory` (created 0700): node.key (PKCS#8 PEM, 0600) and node.pub. Refuses to
    overwrite. Returns (public key text, fingerprint)."""
    if not AVAILABLE:
        raise RuntimeError("the cryptography package is not installed")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    priv_path, pub_path = os.path.join(directory, "node.key"), os.path.join(directory, "node.pub")
    if os.path.exists(priv_path) or os.path.exists(pub_path):
        raise FileExistsError(f"a node key already exists in {directory}")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    text = public_text(key)
    with open(pub_path, "x", encoding="ascii") as f:
        f.write(text + "\n")
    return text, key_fingerprint(text)


def load(directory):
    if not AVAILABLE:
        raise RuntimeError("the cryptography package is not installed")
    with open(os.path.join(directory, "node.key"), "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def main(argv=None):
    p = argparse.ArgumentParser(prog="ccd.nodekeys", description="A worker node's Ed25519 key (Phase 2, shadow).")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="make the node's keypair; prints the public key and its fingerprint")
    i.add_argument("--dir", required=True, help="a directory only the node agent's user can read")
    s = sub.add_parser("show", help="print the public key and fingerprint of an existing keypair")
    s.add_argument("--dir", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "init":
            text, fp = init(a.dir)
        else:
            text = public_text(load(a.dir))
            fp = key_fingerprint(text)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"publicKey: {text}\nfingerprint: {fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
