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
    and receives a random session id that lives only in ccd's memory and the
    tab's memory. The secret itself is never stored by the UI, never returned,
    never logged. Sessions end on lock, after IDLE seconds unused, after TTL
    seconds regardless, and on any ccd restart. Five wrong secrets in five
    minutes lock unlocking for the rest of those five minutes. Wrong sign-in
    codes are refused, never counted: anyone local can call redeem, and a
    256-bit, one-time, 120 s code needs no rate limit.
    """
    TTL = 8 * 3600
    IDLE = 2 * 3600
    # A session minted through SSH sign-in (`scripts/cc-session`, run over Jay's own SSH key login by the
    # Windows launcher) lasts the working day: the SSH key is the stronger proof, and the launcher mints a
    # fresh one at every start. Lock, a ccd restart and closing the browser session still end it.
    SSH_TTL = 12 * 3600
    SSH_IDLE = 12 * 3600
    FAIL_WINDOW = 300
    FAIL_LIMIT = 5
    CODE_TTL = 120          # a sign-in code is good for two minutes, once

    def __init__(self, secret, clock=None):
        import time as _time
        self.secret = secret
        self.clock = clock or _time.monotonic
        self.sessions = {}  # id → (created, last_used, ttl, idle)
        self.codes = {}     # one-time sign-in code → (session id, created)
        self.fails = []

    def _failed(self, now):
        self.fails = [t for t in self.fails if now - t < self.FAIL_WINDOW]
        return len(self.fails) >= self.FAIL_LIMIT

    def unlock(self, presented, ttl=None, idle=None):
        now = self.clock()
        if self._failed(now):
            return None, "too many wrong attempts; wait five minutes"
        if not isinstance(presented, str) or not token_ok(self.secret, presented.strip()):
            self.fails.append(now)
            return None, "that is not the developer token"
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = (now, now, ttl or self.TTL, idle or self.IDLE)
        return sid, None

    def handoff(self, presented):
        """SSH sign-in: the developer secret (read by `cc-session` on the server, as jay) → a day-long
        session and a one-time code the browser redeems. Returns (code, problem)."""
        sid, problem = self.unlock(presented, self.SSH_TTL, self.SSH_IDLE)
        if not sid:
            return None, problem
        now = self.clock()
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
        if not hit or now - hit[1] > self.CODE_TTL or hit[0] not in self.sessions:
            return None, "that sign-in link has expired or was already used; start Command Center again"
        return hit[0], None

    def check(self, sid):
        if not isinstance(sid, str) or not sid:
            return False
        now = self.clock()
        for k, (made, used, ttl, idle) in list(self.sessions.items()):
            if now - made > ttl or now - used > idle:
                del self.sessions[k]
        for k in self.sessions:
            if hmac.compare_digest(k, sid):
                made, _, ttl, idle = self.sessions[k]
                self.sessions[k] = (made, now, ttl, idle)
                return True
        return False

    def expires_in(self, sid):
        hit = self.sessions.get(sid) if isinstance(sid, str) else None
        if not hit:
            return None
        now = self.clock()
        made, used, ttl, idle = hit
        return max(0, min(ttl - (now - made), idle - (now - used)))

    def lock(self, sid):
        self.sessions.pop(sid, None) if isinstance(sid, str) else None
