"""How a lead reads and answers Jay's messages (Command Center Messages).

    cc-inbox [CONVERSATION] [--peek] [--json]
        Jay's unread messages, oldest first, then marked read. Files he attached are saved under
        ~/.cache/command-center/chat/<conversation>/ and their paths printed, so you can open them.
    cc-reply [CONVERSATION] "your answer" [--file PATH ...] [--reply-to ID]
        Your answer to Jay. --file sends an image (PNG, JPEG, GIF, WebP), a PDF or a Markdown/text file.

CONVERSATION is your project's key (samvision, gyst, mfe, commandcenter, …) or `cto`. Left out, it is the project
whose registered folder you are in. Talks to the loopback ccd with this account's ccd token, as
`agent:lead-<conversation>` (or $CCD_ACTOR). Exit 1 with ccd's one-line reason when something is refused.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, registry
from .pipeline_cli import _actor_token, call

CONV_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
CACHE = os.path.expanduser("~/.cache/command-center/chat")


def conversation_here(cwd=None):
    cwd = os.path.realpath(cwd or os.getcwd())
    best = None
    for key, p in registry.PROJECTS.items():
        root = p.get("root")
        if not root:
            continue
        root = os.path.realpath(root)
        if cwd == root or cwd.startswith(root.rstrip("/") + "/"):
            if best is None or len(root) > len(best[1]):
                best = (key, root)
    return best[0] if best else None


def actor_for(conv):
    env = os.environ.get("CCD_ACTOR", "").strip()
    if env:
        return env
    return "agent:cto" if conv == "cto" else f"agent:lead-{conv}"


def _raw(method, path, data=None, ctype=None, actor=None):
    port = int(os.environ.get("CCD_PORT", "7777"))
    headers = {"Host": f"127.0.0.1:{port}", "X-CCD-Token": config.TOKEN_PATH.read_text().strip()}
    if actor:
        headers["X-CCD-Actor"] = actor
    tok = _actor_token()
    if tok:
        headers["X-CCD-Actor-Token"] = tok
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return 0, r.read()
    except urllib.error.HTTPError as e:
        body = e.read() or b"{}"
        try:
            return 1, json.loads(body).get("error", f"HTTP {e.code}")
        except ValueError:
            return 1, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return 1, f"Command Center is not reachable on 127.0.0.1:{port} ({getattr(e, 'reason', e)})"


def _safe_name(name):
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(str(name)))[:120].strip(" .") or "file"
    return name


def save_files(conv, msg, actor):
    """Download each file of a message into the cache. Returns [(file row, path or None, error)]."""
    out = []
    folder = os.path.join(CACHE, conv)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    for f in msg.get("files") or []:
        path = os.path.join(folder, f"{msg['id']}-{f['id'][:8]}-{_safe_name(f['name'])}")
        code, data = _raw("GET", f"/api/chat/files/{f['id']}", actor=actor)
        if code:
            out.append((f, None, data))
            continue
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        out.append((f, path, None))
    return out


def _when(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _size(n):
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


def inbox(conv, peek=False, as_json=False, out=sys.stdout):
    actor = actor_for(conv)
    code, res = call("GET", f"/api/chat/{conv}/inbox" + ("?peek=1" if peek else ""), actor=actor)
    if code:
        print(f"cc-inbox: {res.get('error', res)}", file=sys.stderr)
        return 1
    msgs = res.get("messages") or []
    saved = {m["id"]: save_files(conv, m, actor) for m in msgs}
    if as_json:
        for m in msgs:
            for f, path, err in saved[m["id"]]:
                f["savedTo"], f["error"] = path, err
        json.dump(res, out, indent=2)
        out.write("\n")
        return 0
    if not msgs:
        print(f"No unread messages from Jay in {conv}.", file=out)
        return 0
    print(f"{len(msgs)} unread message(s) from Jay in {conv}, oldest first:\n", file=out)
    for m in msgs:
        via = " · from Slack" if m.get("via") == "slack" else ""
        print(f"#{m['id']} · {_when(m['at'])}{via}", file=out)
        if m.get("text"):
            print(m["text"], file=out)
        for f, path, err in saved[m["id"]]:
            where = f"saved to {path}" if path else f"could not be saved: {err}"
            print(f"  [file] {f['name']} ({f['mime']}, {_size(f['size'])}) {where}", file=out)
        print("", file=out)
    print(f'Answer with: cc-reply {conv} "…" [--file PATH] [--reply-to ID]', file=out)
    return 0


def reply(conv, text, files=(), reply_to=None, out=sys.stdout):
    actor = actor_for(conv)
    ids = []
    for path in files or ():
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            print(f"cc-reply: cannot read {path}: {e.strerror}", file=sys.stderr)
            return 1
        q = urllib.parse.urlencode({"conversation": conv, "name": os.path.basename(path)})
        code, res = _raw("POST", f"/api/chat/files?{q}", data, "application/octet-stream", actor)
        if code:
            print(f"cc-reply: {os.path.basename(path)}: {res}", file=sys.stderr)
            return 1
        ids.append(json.loads(res)["file"]["id"])
    body = {"text": text or "", "files": ids}
    if reply_to is not None:
        body["replyTo"] = reply_to
    code, res = call("POST", f"/api/chat/{conv}/messages", body, actor=actor)
    if code:
        print(f"cc-reply: {res.get('error', res)}", file=sys.stderr)
        return 1
    print(f"Sent to Jay as #{res['message']['id']} ({conv}).", file=out)
    return 0


def main(argv=None, prog=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    prog = prog or os.path.basename(sys.argv[0])
    mode = "reply" if prog.endswith("reply") else "inbox" if prog.endswith("inbox") else None
    if mode is None:
        if not argv or argv[0] not in ("inbox", "reply"):
            print(__doc__, file=sys.stderr)
            return 2
        mode, argv = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"cc-{mode}", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if mode == "inbox":
        ap.add_argument("conversation", nargs="?")
        ap.add_argument("--peek", action="store_true", help="show without marking read")
        ap.add_argument("--json", action="store_true")
        a = ap.parse_args(argv)
    else:
        ap.add_argument("args", nargs="+", metavar="[CONVERSATION] TEXT")
        ap.add_argument("--file", action="append", default=[])
        ap.add_argument("--reply-to", type=int)
        a = ap.parse_args(argv)
        if len(a.args) > 2:
            ap.error("put your answer in quotes")
        a.conversation, a.text = (a.args if len(a.args) == 2 else (None, a.args[0]))
    conv = a.conversation or conversation_here()
    if not conv or not CONV_RE.match(conv):
        print(f"cc-{mode}: name the conversation (your project key, or cto); this folder is not a registered "
              f"project", file=sys.stderr)
        return 2
    try:
        if mode == "inbox":
            return inbox(conv, a.peek, a.json)
        return reply(conv, a.text, a.file, a.reply_to)
    except OSError as e:
        print(f"cc-{mode}: cannot read this account's ccd token ({e.strerror}); run it as the user ccd runs as",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
