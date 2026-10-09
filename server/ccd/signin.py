"""SSH sign-in: print a one-time Command Center sign-in code (or link) — run on jay-server, as jay.

    scripts/cc-session                      the code (what CommandCenter.exe reads over its SSH login)
    scripts/cc-session --url                http://127.0.0.1:7777/#/?signin=<code>  (paste into a browser)
    scripts/cc-session --port 7789 --dev-dir ~/command-center/dev-control-room --url    a preview

Why this is safe: only someone who can log in as jay can read the developer token (0600) that this
sends to ccd, so an SSH key login — which the Windows launcher already makes to open its tunnel —
is the proof. ccd answers with a code that is good once, for two minutes; the page trades it for
the ccd token and a Developer session, so Jay pastes nothing and unlocks nothing. The code is never
logged by ccd; the token never leaves the server in this exchange.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import config


def mint(port, token, dev_token, timeout=10):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/developer/handoff", method="POST",
                                 data=json.dumps({"token": dev_token}).encode(),
                                 headers={"Host": f"127.0.0.1:{port}", "X-CCD-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["code"]
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except ValueError:
            msg = f"HTTP {e.code}"
        raise SystemExit(f"cc-session: ccd refused: {msg}")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"cc-session: Command Center is not answering on 127.0.0.1:{port} ({getattr(e, 'reason', e)})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="cc-session", description="Print a one-time Command Center sign-in code.")
    p.add_argument("--port", type=int, default=config.PORT)
    p.add_argument("--dev-dir", help="a preview's directory (scripts/dev-ccd.py CCD_DEV_DIR)")
    p.add_argument("--url", action="store_true", help="print the whole sign-in link")
    a = p.parse_args(argv)
    tok_path, dev_path = config.TOKEN_PATH, config.DEV_TOKEN_PATH
    if a.dev_dir:
        d = Path(a.dev_dir).expanduser()
        tok_path, dev_path = d / "ccd.token", d / "developer.token"
    try:
        token, dev = tok_path.read_text().strip(), dev_path.read_text().strip()
    except OSError as e:
        raise SystemExit(f"cc-session: cannot read the token files ({e.strerror}: {e.filename})")
    code = mint(a.port, token, dev)
    print(f"http://127.0.0.1:{a.port}/#/?signin={code}" if a.url else code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
