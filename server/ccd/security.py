"""Who may talk to ccd, and what may leave it.

Loopback alone is not a trust boundary on this server: a second login user
(`minecraft-ai`, uid 1001) can reach 127.0.0.1:7777 like anyone else, and a
web page open in Jay's browser can aim requests at the tunnelled port. So:

  * Host must be 127.0.0.1:<port> or localhost:<port>  — defeats DNS rebinding
  * Origin, when a browser sends one, must be that same origin  — defeats CSRF
  * the one exception: tailnet addresses Jay names in config.json "remote_origins"
    (https://<machine>.<tailnet>.ts.net), for Tailscale Serve. ccd still listens
    on 127.0.0.1 only, and a request Tailscale marks as coming through Funnel
    (the public internet) is refused. See remote_origins() below.
  * every endpoint except /api/health needs the local token, in X-CCD-Token
    (or ?token= on the WebSocket, which browsers cannot give headers to)
  * actions additionally need Content-Type: application/json, which forces a
    CORS preflight that ccd never approves

The token is created on first start in ~/.config/command-center/ccd.token,
mode 0600, readable only by jay. It is never logged and never returned by the
API. The legacy board reads the file directly; the future Windows client gets
it over the same SSH connection that carries the tunnel.
"""
import hmac
import json
import os
import re
import secrets
from pathlib import Path


def load_or_create_token(path):
    path = Path(path)
    try:
        token = path.read_text().strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.chmod(path, 0o600)
    return token


def token_ok(expected, presented):
    return bool(presented) and hmac.compare_digest(str(expected), str(presented))


def allowed_hosts(port, remote=()):
    return {f"127.0.0.1:{port}", f"localhost:{port}"} | {o.removeprefix("https://") for o in remote}


def allowed_origins(port, remote=()):
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"} | set(remote)


# Remote access through Tailscale Serve (Jay, 2026-11-12, plan question B1: Tailscale now, a public tunnel later and
# separately). `tailscale serve` on jay-server forwards https://<machine>.<tailnet>.ts.net to 127.0.0.1:<port>, and only
# devices signed in to Jay's tailnet can reach that name. Each address is named exactly: https, a *.ts.net host name,
# no port, no path. Anything else (http, another domain, a wildcard) is refused and logged, never widened.
TAILNET_ORIGIN = re.compile(r"^https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\.ts\.net$")
# Tailscale adds this header to a request that arrived through Funnel, which publishes a Serve address to the internet.
# D-006 keeps ccd off the public internet, so such a request is refused even if Funnel is switched on by mistake.
FUNNEL_HEADER = "tailscale-funnel-request"


def remote_origins(raw):
    """(accepted, refused) from config.json's "remote_origins": a list of exact tailnet https origins."""
    items = raw if isinstance(raw, list) else [] if raw in (None, "") else [raw]
    ok, bad = [], []
    for item in items:
        o = item.strip().lower() if isinstance(item, str) else ""
        if TAILNET_ORIGIN.match(o):
            ok.append(o)
        else:
            bad.append(repr(item)[:120])
    return sorted(set(ok)), bad


# Patterns that look like credentials. Applied to pane tails before they leave
# ccd. This catches the common shapes; it cannot recognise licensed data,
# which is why tails are on demand, never stored, and token-gated.
_SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"xapp-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b(\s*[:=]\s*|\s+)(bearer\s+)?[^\s'\"]{6,}"),
    re.compile(r"(?i)postgres(?:ql)?://[^\s:@/]+:[^\s@/]+@"),
    re.compile(r"https://ntfy\.sh/[A-Za-z0-9_-]{6,}"),
]


def redact(text):
    """(clean_text, count_of_redactions)."""
    count = 0
    for pat in _SECRET_PATTERNS:
        text, n = pat.subn("[redacted]", text)
        count += n
    return text, count


def control_free(text):
    """Printable text only: no escape sequences can be typed into a pane."""
    return not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text or "")


class DeveloperGate:
    """The second, higher credential: Developer Unlock.

    The ordinary ccd token reads and steers metadata. Changing a repository
    file, uploading, removing an attachment — anything that writes Jay's code or
    files — needs Developer Unlock: the browser presents the secret in
    ~/.config/command-center/developer.token (0600) once, to /api/developer/unlock,
    and receives a random session id. The secret itself is never stored by the UI,
    never returned, never logged. Five wrong secrets in five minutes lock unlocking
    for the rest of those five minutes. Wrong sign-in codes are refused, never
    counted: anyone local can call redeem, and a 256-bit, one-time, 120 s code
    needs no rate limit.

    Three kinds of session (contract §6, Jay 2026-11-14: "make Developer Unlock last"):
      plain     a typed unlock: 8 h in all, 2 h idle (unchanged)
      ssh       SSH sign-in (`scripts/cc-session`): 12 h, no shorter idle limit (unchanged)
      remember  a typed unlock with "Remember this device": 30 days, no idle limit. The live terminal and file
                writes still need the secret typed within the last 8 h (FRESH): a stolen remembered session id
                can approve and steer for a month, but cannot open a shell or write code past one working day.

    Sessions survive a ccd restart. The disk file (0600, under ccd's data dir) holds, per session, only an HMAC of
    its id keyed with the developer secret, never the id and never the secret. So the file alone cannot be turned
    into a session, an entry written by someone without the secret matches nothing, and changing developer.token
    ends every session. Limits come from the kind, never from the file: an edited file cannot make a session
    last longer than its kind allows, and each row carries an HMAC over its kind, times, id and label, so an edited
    row is dropped. A clock that goes backwards ends the sessions it would otherwise stretch. Lock, "Lock all devices" and expiry remove entries from memory and disk.
    """
    TTL = 8 * 3600
    IDLE = 2 * 3600
    # A session minted through SSH sign-in (`scripts/cc-session`, run over Jay's own SSH key login by the
    # Windows launcher) lasts the working day: the SSH key is the stronger proof, and the launcher mints a
    # fresh one at every start. Lock and closing the browser session still end it.
    SSH_TTL = 12 * 3600
    SSH_IDLE = 12 * 3600
    REMEMBER_TTL = 30 * 86400
    # The live terminal (PTY) and file writes: a remembered session must have had the secret typed this recently.
    # Plain and SSH sessions are never older than their own TTL, so for them this changes nothing.
    FRESH = 8 * 3600
    FAIL_WINDOW = 300
    FAIL_LIMIT = 5
    CODE_TTL = 120          # a sign-in code is good for two minutes, once
    SAVE_EVERY = 60         # "last used" reaches the disk at most this often; lock/unlock/expiry at once
    LABEL_MAX = 64
    FILE_VERSION = 1

    def __init__(self, secret, clock=None, path=None):
        import time as _time
        self.secret = secret
        # Wall-clock time: a session's age has to mean the same thing after a restart.
        self.clock = clock or _time.time
        self.path = Path(path) if path else None
        self.sessions = {}  # HMAC of the session id → {id, kind, made, used, proved, label}
        self.codes = {}     # one-time sign-in code → (session id, created); memory only, never on disk
        self.fails = []
        self.save_error = None
        self._saved_at = None
        self._load()

    # ---- limits ----

    def _limits(self, kind):
        """(ttl, idle or None) for a kind. Taken from the class, never from the file."""
        if kind == "remember":
            return self.REMEMBER_TTL, None
        if kind == "ssh":
            return self.SSH_TTL, self.SSH_IDLE
        return self.TTL, self.IDLE

    def _left(self, rec, now):
        # The wall clock went back (or a time is from the future): the session's age can't be trusted, so it ends.
        if max(rec["made"], rec["used"], rec["proved"]) > now + 60:
            return 0
        ttl, idle = self._limits(rec["kind"])
        left = ttl - (now - rec["made"])
        if idle is not None:
            left = min(left, idle - (now - rec["used"]))
        return left

    def _fresh_left(self, rec, now):
        """Seconds the terminal and file writes stay open to this session without typing the secret again."""
        left = self._left(rec, now)
        if rec["kind"] == "remember":
            left = min(left, self.FRESH - (now - rec["proved"]))
        return left

    def _key(self, sid):
        return hmac.new(str(self.secret).encode(), b"ccd-developer-session\0" + sid.encode(), "sha256").hexdigest()

    def _file_check(self):
        """Ties the file to this developer.token without holding it: an HMAC of a fixed string."""
        return hmac.new(str(self.secret).encode(), b"ccd-developer-sessions-file", "sha256").hexdigest()

    def _row_mac(self, key, rec):
        """Binds a saved row's kind, times, id and label to its key: an edited row is dropped, not believed."""
        raw = json.dumps([key, rec["id"], rec["kind"], float(rec["made"]), float(rec["used"]), float(rec["proved"]),
                          rec["label"]])
        return hmac.new(str(self.secret).encode(), b"ccd-developer-row\0" + raw.encode(), "sha256").hexdigest()

    def _find(self, sid):
        """(key, record) for a live session id, else (None, None). Prunes nothing."""
        if not isinstance(sid, str) or not sid:
            return None, None
        key = self._key(sid)
        rec = self.sessions.get(key)
        if rec is None or self._left(rec, self.clock()) <= 0:
            return None, None
        return key, rec

    def _prune(self, now):
        dead = [k for k, r in self.sessions.items() if self._left(r, now) <= 0]
        for k in dead:
            del self.sessions[k]
        return bool(dead)

    @classmethod
    def clean_label(cls, label):
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", label if isinstance(label, str) else "")
        return re.sub(r"\s+", " ", text).strip()[:cls.LABEL_MAX].strip() or "Browser"

    # ---- the disk file ----

    def _load(self):
        if self.path is None:
            return
        try:
            st = os.stat(self.path)
            if st.st_mode & 0o077 or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
                # Not ours alone: trust nothing in it. The next save replaces it with a 0600 file.
                self.save_error = "developer session file had loose permissions; ignored"
                return
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self.save_error = "developer session file unreadable; ignored"
            return
        now = self.clock()
        ok = isinstance(data, dict) and data.get("version") == self.FILE_VERSION and isinstance(data.get("check"), str) \
            and hmac.compare_digest(data["check"], self._file_check())
        # Written under another developer.token: every entry in it is dead, so none is listed or kept.
        rows = data.get("sessions") if ok else None
        for r in rows if isinstance(rows, list) else []:
            try:
                key, kind = r["key"], r["kind"]
                made, used, proved = float(r["made"]), float(r["used"]), float(r["proved"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key)) or kind not in ("plain", "ssh", "remember"):
                continue
            # A time from the future (an edited file, or a clock set back) is not believed: it could stretch a limit.
            if max(made, used, proved) > now + 60 or not made <= used or not made <= proved:
                continue
            rid = r.get("id")
            if not (isinstance(rid, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,32}", rid)):
                continue
            rec = {"id": rid, "kind": kind, "made": made, "used": used, "proved": proved,
                   "label": self.clean_label(r.get("label"))}
            mac = r.get("mac")
            if not isinstance(mac, str) or not hmac.compare_digest(mac, self._row_mac(key, rec)):
                continue
            if self._left(rec, now) > 0:
                self.sessions[key] = rec

    def _save(self, force=True):
        if self.path is None:
            return
        now = self.clock()
        if not force and self._saved_at is not None and now - self._saved_at < self.SAVE_EVERY:
            return
        rows = [{"key": k, **r, "mac": self._row_mac(k, r)} for k, r in self.sessions.items()]
        raw = json.dumps({"version": self.FILE_VERSION, "check": self._file_check(), "sessions": rows},
                         separators=(",", ":"))
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = self.path.with_name(f".{self.path.name}.{secrets.token_hex(6)}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            tmp = None
            self._saved_at = now
            self.save_error = None
        except OSError as e:
            # Sessions keep working from memory; they just would not survive a restart.
            self.save_error = f"could not save developer sessions: {e.__class__.__name__}"
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ---- unlocking ----

    def _failed(self, now):
        self.fails = [t for t in self.fails if now - t < self.FAIL_WINDOW]
        return len(self.fails) >= self.FAIL_LIMIT

    def _secret_ok(self, presented, now):
        if self._failed(now):
            return "too many wrong attempts; wait five minutes"
        if not isinstance(presented, str) or not token_ok(self.secret, presented.strip()):
            self.fails.append(now)
            return "that is not the developer token"
        return None

    def _mint(self, kind, label, now):
        sid = secrets.token_urlsafe(32)
        self.sessions[self._key(sid)] = {"id": secrets.token_urlsafe(9), "kind": kind, "made": now, "used": now,
                                         "proved": now, "label": self.clean_label(label)}
        return sid

    def unlock(self, presented, remember=False, label=None, current=None):
        """The secret → a session id. `remember`: a 30-day session for this device. `current`: the session the
        browser already holds; typing the secret again on a live one re-proves it in place (the terminal and file
        writes open again for FRESH) instead of adding a second entry to the device list."""
        now = self.clock()
        problem = self._secret_ok(presented, now)
        if problem:
            return None, problem
        self._prune(now)
        key, rec = self._find(current)
        if rec is not None and (remember or rec["kind"] == "remember"):
            if remember != (rec["kind"] == "remember"):
                rec["made"] = now               # a change of kind starts that kind's clock
            rec.update(kind="remember" if remember else "plain", used=now, proved=now)
            if label is not None:
                rec["label"] = self.clean_label(label)
            self._save()
            return current, None
        if rec is not None:
            del self.sessions[key]               # same device, new plain session: do not leave the old one behind
        sid = self._mint("remember" if remember else "plain", label, now)
        self._save()
        return sid, None

    def handoff(self, presented, label=None):
        """SSH sign-in: the developer secret (read by `cc-session` on the server, as jay) → a day-long
        session and a one-time code the browser redeems. Returns (code, problem)."""
        now = self.clock()
        problem = self._secret_ok(presented, now)
        if problem:
            return None, problem
        self._prune(now)
        sid = self._mint("ssh", label or "SSH sign-in", now)
        self._save()
        self.codes = {c: v for c, v in self.codes.items() if now - v[1] <= self.CODE_TTL}
        code = secrets.token_urlsafe(32)
        self.codes[code] = (sid, now)
        return code, None

    def redeem(self, code):
        """A one-time code → its session id, once, within CODE_TTL. A wrong code is refused with the same
        message every time and is never counted: redeem takes no ccd token, so counting guesses would let
        any local user lock Jay out of unlock and handoff."""
        now = self.clock()
        hit = None
        if isinstance(code, str) and code:
            for c in list(self.codes):
                if hmac.compare_digest(c, code):
                    hit = self.codes.pop(c)
                    break
        if not hit or now - hit[1] > self.CODE_TTL or self._find(hit[0])[1] is None:
            return None, "that sign-in link has expired or was already used; start Command Center again"
        return hit[0], None

    # ---- checking ----

    def check(self, sid, fresh=False):
        """Is `sid` a live session? Refreshes its idle timer. `fresh`: also require the secret typed within FRESH
        (the live terminal and file writes); a remembered session past that is refused without being touched."""
        if not isinstance(sid, str) or not sid:
            return False
        now = self.clock()
        pruned = self._prune(now)
        key, rec = self._find(sid)
        if rec is None or (fresh and self._fresh_left(rec, now) <= 0):
            if pruned:
                self._save()
            return False
        rec["used"] = now
        self._save(force=pruned)
        return True

    def needs_reentry(self, sid):
        """A live session that may not open the terminal or write files until the secret is typed again."""
        _, rec = self._find(sid)
        return rec is not None and self._fresh_left(rec, self.clock()) <= 0

    def peek(self, sid):
        """Read-only: live or not, without refreshing the idle timer (identity records use it)."""
        return self._find(sid)[1] is not None

    def expires_in(self, sid, fresh=False):
        _, rec = self._find(sid)
        if rec is None:
            return None
        now = self.clock()
        return max(0, (self._fresh_left if fresh else self._left)(rec, now))

    def describe(self, sid):
        """What the browser is told about its own session, or None."""
        _, rec = self._find(sid)
        if rec is None:
            return None
        now = self.clock()
        ttl, idle = self._limits(rec["kind"])
        return {"expiresIn": max(0, self._left(rec, now)), "remembered": rec["kind"] == "remember",
                "kind": rec["kind"], "idleLimit": idle, "reenterIn": max(0, self._fresh_left(rec, now))}

    def devices(self, sid=None):
        """Every live session, newest use first: what Settings shows. Never a session id or a key."""
        now = self.clock()
        if self._prune(now):
            self._save()
        mine = self._key(sid) if isinstance(sid, str) and sid else None
        out = [{"id": r["id"], "label": r["label"], "kind": r["kind"], "remembered": r["kind"] == "remember",
                "createdAt": int(r["made"]), "lastUsedAt": int(r["used"]),
                "expiresAt": int(now + max(0, self._left(r, now))),
                "current": k == mine}
               for k, r in self.sessions.items()]
        return sorted(out, key=lambda d: -d["lastUsedAt"])

    # ---- locking ----

    def lock(self, sid):
        if isinstance(sid, str) and sid and self.sessions.pop(self._key(sid), None) is not None:
            self._save()

    def lock_all(self):
        """End every session on every device, and every unredeemed sign-in code. Returns how many ended."""
        n = len(self.sessions)
        self.sessions.clear()
        self.codes.clear()
        self._save()
        return n
