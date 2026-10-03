"""Who may talk to ccd, and what may leave it.

Loopback alone is not a trust boundary on this server: a second login user
(`minecraft-ai`, uid 1001) can reach 127.0.0.1:7777 like anyone else, and a
web page open in Jay's browser can aim requests at the tunnelled port. So:

  * Host must be 127.0.0.1:<port> or localhost:<port>  — defeats DNS rebinding
  * Origin, when a browser sends one, must be that same origin  — defeats CSRF
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


def allowed_hosts(port):
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def allowed_origins(port):
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


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
