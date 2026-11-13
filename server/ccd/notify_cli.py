"""Switch Slack and ntfy on or off, and check them, from jay-server (as jay).

    python -m ccd.notify_cli status
    python -m ccd.notify_cli on  slack|ntfy|both
    python -m ccd.notify_cli off slack|ntfy|both
    python -m ccd.notify_cli quiet 22:00 07:00
    python -m ccd.notify_cli scope answers|answers_low_risk
    python -m ccd.notify_cli test        one test DM and one test push
    python -m ccd.notify_cli summary     post the owner's and technical summaries now

Changing anything is Jay's: it unlocks Developer Mode with ~/.config/command-center/developer.token (readable by
jay only) for this one call, exactly as the browser does, and locks again. Nothing is printed but ccd's answer,
which never holds a token or the ntfy URL.
"""
import json
import sys

from . import config
from .pipeline_cli import call


def _dev():
    code, r = call("POST", "/api/developer/unlock", {"token": config.DEV_TOKEN_PATH.read_text().strip()})
    if code or not r.get("session"):
        sys.exit(f"Developer Unlock refused: {r.get('error')}")
    return r["session"]


def _jay(method, path, body=None):
    import os
    import urllib.error
    import urllib.request
    sid = _dev()
    port = int(os.environ.get("CCD_PORT", "7777"))
    token = config.TOKEN_PATH.read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body or {}).encode(),
                                 headers={"Host": f"127.0.0.1:{port}", "X-CCD-Token": token,
                                          "X-CCD-Developer": sid, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(json.loads(e.read() or b"{}").get("error") or f"HTTP {e.code}")
    finally:
        try:
            req2 = urllib.request.Request(f"http://127.0.0.1:{port}/api/developer/lock", method="POST", data=b"{}",
                                          headers={"Host": f"127.0.0.1:{port}", "X-CCD-Token": token,
                                                   "X-CCD-Developer": sid, "Content-Type": "application/json"})
            urllib.request.urlopen(req2, timeout=10).read()
        except Exception:  # noqa: BLE001 — the session expires on its own
            pass


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    if cmd == "status":
        code, r = call("GET", "/api/notify")
        print(json.dumps(r, indent=2))
        return code
    if cmd in ("on", "off") and len(a) == 2 and a[1] in ("slack", "ntfy", "both"):
        which = ["slack", "ntfy"] if a[1] == "both" else [a[1]]
        r = _jay("PUT", "/api/notify", {w: cmd == "on" for w in which})
    elif cmd == "quiet" and len(a) == 3:
        r = _jay("PUT", "/api/notify", {"quietStart": a[1], "quietEnd": a[2]})
    elif cmd == "scope" and len(a) == 2:
        r = _jay("PUT", "/api/notify", {"replyScope": a[1]})
    elif cmd == "test":
        r = _jay("POST", "/api/notify/test")
    elif cmd == "summary":
        r = _jay("POST", "/api/notify/summary")
    else:
        print(__doc__)
        return 2
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
