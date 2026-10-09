"""Which running Claude is a project's coordinator — the ONE resolver.

The browser Claude terminal and the native Windows one (both via scripts/cc-terminal),
the Workspace's coordinator status and the Agents page all ask `resolve()` and nothing
else. A terminal title is display metadata (Claude renames its conversation freely), so
identity comes from stronger evidence, strongest first:

  1. binding   the Claude session id recorded for this project (state file below). It
               survives a new pane id and any title; a pane that merely reuses the old
               pane id but runs another session never matches.
  2. label     herdr's agent name or pane label is the canonical coordinator name.
  3. title     the terminal title is exactly the canonical name (`claude -n <name>`).

Labels and titles only count for a Claude at the registered project root itself, never
one in a sub-directory or worktree. When nothing names the coordinator:

  found     exactly one Claude sits at the root: it is offered for ADOPTION, never
            attached to on cwd alone.
  multiple  more than one could be it: Jay picks one; nothing guesses.
  none      no Claude at the root.

Adoption binds an EXISTING session; nothing here starts, resumes or renames Claude.
A label or title match is recorded as a binding too, so a later rename cannot break it.
"""
import contextlib
import fcntl
import json
import os
import re
import tempfile
import time

from .config import STATE_DIR

BINDINGS = STATE_DIR / "coordinator-bindings.json"
PANE_RE = re.compile(r"^w[0-9A-Za-z]+:p[0-9]+$")
SESSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z:._-]{2,79}$")
# The one name each coordinator answers to. Default: the project key.
CANONICAL = {"commandcenter": "command-center"}
REVERIFY_S = 600   # a still-valid binding's verifiedAt is refreshed at most this often


def canonical_name(key):
    return CANONICAL.get(key, key)


def _names(key):
    return {canonical_name(key), key}


def _real(path):
    return os.path.realpath(path) if path else ""


def _under(path, root):
    return bool(path) and (path == root or path.startswith(root.rstrip("/") + "/"))


def normalize(entry):
    """One shape for a raw `herdr agent list` entry or a sources.panes_from row."""
    session = entry.get("agent_session")
    sid = (session.get("value") if isinstance(session, dict) else None) or entry.get("session_id") or ""
    # Where the agent itself runs: herdr's foreground cwd. A lane started in the root pane
    # and moved into a worktree keeps the pane cwd, so the pane cwd alone proves nothing.
    cwd = _real(entry.get("foreground_cwd") or entry.get("cwd"))
    return {
        "paneId": entry.get("pane_id") or "",
        "agent": entry.get("agent") or "",
        "sessionId": sid,
        "name": entry.get("name") or entry.get("agent_name") or "",
        "label": entry.get("label") or "",
        "title": (entry.get("terminal_title_stripped") or entry.get("title") or "").strip(),
        "status": entry.get("agent_status") or entry.get("status") or "unknown",
        "live": entry.get("live", True),
        "cwd": cwd,
    }


def _public(c):
    return {"paneId": c["paneId"], "sessionId": c["sessionId"], "title": c["title"], "status": c["status"]}


def resolve(key, root, entries, binding=None):
    """The coordinator of project `key` (registered root `root`) among live agents.

    Pure: `entries` are herdr agent rows, `binding` the recorded row for this project.
    Returns {state, paneId, sessionId, status, title, how, staleBinding, candidates}.
    `paneId` is set only when state == "ready".
    """
    root = _real(root)
    claude = [c for c in map(normalize, entries or [])
              if c["live"] and c["agent"] == "claude" and PANE_RE.match(c["paneId"]) and SESSION_RE.match(c["sessionId"])]
    at_root = [c for c in claude if c["cwd"] == root]
    out = {"state": "none", "paneId": None, "sessionId": None, "status": "offline", "title": "", "how": None,
           "staleBinding": False, "candidates": [_public(c) for c in at_root]}

    def ready(c, how):
        out.update(state="ready", paneId=c["paneId"], sessionId=c["sessionId"], status=c["status"],
                   title=c["title"], how=how)
        return out

    sid = (binding or {}).get("sessionId")
    if sid:
        bound = [c for c in claude if c["sessionId"] == sid and _under(c["cwd"], root)]
        if len(bound) == 1:
            return ready(bound[0], "binding")
        out["staleBinding"] = True

    names = _names(key)
    for how, pick in (("label", lambda c: c["name"] in names or c["label"] in names),
                      ("title", lambda c: c["title"] in names)):
        hits = [c for c in at_root if pick(c)]
        if len(hits) == 1:
            return ready(hits[0], how)
        if len(hits) > 1:
            out["state"] = "multiple"
            return out

    if len(at_root) == 1:
        c = at_root[0]
        out.update(state="found", sessionId=c["sessionId"], status=c["status"], title=c["title"])
    elif len(at_root) > 1:
        out["state"] = "multiple"
    return out


# ---------- the binding file ----------

def load(path=None):
    try:
        data = json.loads((path or BINDINGS).read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _save(data, path=None):
    path = path or BINDINGS
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bindings.")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def _locked(path):
    """Serialise every read-modify-write of the bindings file: ccd's derive thread, its
    event loop (Adopt) and cc-terminal (another process) all write it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)   # closing releases the lock


def _row(key, root, session_id, pane_id, now):
    return {"canonical": canonical_name(key), "sessionId": session_id, "paneId": pane_id,
            "root": _real(root), "verifiedAt": int(now)}


def resolve_and_record(key, root, entries, path=None, now=None):
    """resolve() with this project's binding, recording a strong identification.

    The write happens under the lock and re-reads the file first: only this project's row
    changes, and only if nobody (an Adopt, cc-terminal) changed that row since it was read.
    """
    path = path or BINDINGS
    now = time.time() if now is None else now
    old = load(path).get(key)
    r = resolve(key, root, entries, old)
    if r["state"] == "ready":
        o = old or {}
        if (o.get("sessionId") != r["sessionId"] or o.get("paneId") != r["paneId"]
                or now - (o.get("verifiedAt") or 0) > REVERIFY_S):
            try:
                with _locked(path):
                    data = load(path)
                    if data.get(key) == old:
                        data[key] = _row(key, root, r["sessionId"], r["paneId"], now)
                        _save(data, path)
            except OSError:
                pass   # recording is an optimisation; the verdict stands
    return r


def adopt(key, root, entries, session_id, path=None, now=None):
    """Bind the EXISTING Claude `session_id` as `key`'s coordinator.

    Only a live Claude at the exact project root can be adopted. Returns the new
    resolution, or raises ValueError with a short reason.
    """
    path = path or BINDINGS
    if not isinstance(session_id, str) or not SESSION_RE.match(session_id):
        raise ValueError("not a Claude session id")
    r = resolve(key, root, entries)
    pick = next((c for c in r["candidates"] if c["sessionId"] == session_id), None)
    if not pick:
        raise ValueError("that Claude is not running at this project's root")
    now = time.time() if now is None else now
    try:
        with _locked(path):
            data = load(path)
            data[key] = _row(key, root, session_id, pick["paneId"], now)
            if not _save(data, path):
                raise OSError
    except OSError:
        raise ValueError("could not record the binding")
    return resolve(key, root, entries, data[key])


# ---------- task sessions (plans/COMMAND-CENTER-CONTROL-ROOM.md §8) ----------
#
# Every actively worked ticket has its own Claude task session, named after the key in lower case
# (sv-071): herdr's agent name or pane label, set when the session is started, so a conversation rename
# never loses it. Titles never count; coordinators are excluded. Nothing here starts one.

def task_names(key):
    k = str(key or "").strip()
    return {k.lower(), k.upper()} if k else set()


def task_session(key, entries, exclude=()):
    """{state: ready|multiple|none, paneId, sessionId, status} for ticket `key`'s task Claude session.

    Only herdr's agent name or pane label count — never the terminal title, which Claude renames freely —
    and a pane that is a project coordinator (`exclude`: its pane ids) is never a task session."""
    names = task_names(key)
    skip = set(exclude or ())
    claude = [c for c in map(normalize, entries or [])
              if c["live"] and c["agent"] == "claude" and PANE_RE.match(c["paneId"]) and c["paneId"] not in skip]
    hits = [c for c in claude if c["name"] in names or c["label"] in names]
    if len(hits) == 1:
        c = hits[0]
        return {"state": "ready", "paneId": c["paneId"], "sessionId": c["sessionId"], "status": c["status"]}
    return {"state": "multiple" if hits else "none", "paneId": None, "sessionId": None, "status": "offline",
            "candidates": [_public(c) for c in hits]}


def coordinator_panes(entries, roots, bindings=None):
    """Pane ids that resolve as any project's coordinator (never a task session). `roots`: {key: root}."""
    bindings = load() if bindings is None else bindings
    out = set()
    for key, root in roots.items():
        if root:
            r = resolve(key, root, entries, bindings.get(key))
            if r.get("paneId"):
                out.add(r["paneId"])
    return out
