"""Deterministic coordinator names.

Every project's coordinator answers to its project key — samvision, gauzemate,
gyst, mfe — on both layers that matter:

  herdr   `herdr agent rename <pane> <key>`, after which `herdr agent focus
          <key>` and `herdr agent prompt <key> …` reach it. Renaming an agent
          interrupts nothing, so this layer can be made canonical at any time.

  Claude  `claude -n <key>` sets the cross-session peer name that ListAgents
          shows and dispatch addresses. Without `-n`, Claude invents
          `<directory>-<two characters>` and dispatch cannot find the session.
          The name is fixed when the session starts, so a coordinator already
          running under an invented name keeps it until it is restarted.

Nothing here guesses a name from a prefix. `adopt` makes the herdr layer
canonical now and records the Claude peer alias of an already-running session
in state/coordinators.json so dispatch can still reach it; `rows` prints the
`-c` restart line that retires that alias with the conversation intact.
"""
import json
import os
import re
import stat
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import coordid, sources
from . import registry as project_registry
from .config import LEGACY, STATE_DIR

REGISTRY = STATE_DIR / "coordinators.json"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")  # herdr's rule for agent names


def canonical(project):
    """The one name this project's coordinator answers to."""
    return coordid.canonical_name(project["key"])


def root_of(project):
    """The registered checkout root: the registry's, else the config's path."""
    return (project_registry.PROJECTS.get(project["key"]) or {}).get("root") or project.get("path") or ""


def resolution(project, panes):
    """The shared resolver's verdict for this project (see coordid.py)."""
    return coordid.resolve_and_record(project["key"], root_of(project), sources.agent_panes(panes))


def public_resolution(r):
    """What may leave the daemon: never a terminal title (a title can quote anything)."""
    out = {k: r[k] for k in ("state", "paneId", "sessionId", "status", "how", "staleBinding")}
    out["candidates"] = [{k: c[k] for k in ("paneId", "sessionId", "status")} for c in r["candidates"]]
    return out


def valid(name):
    return bool(NAME_RE.match(name or ""))


def registry():
    """Claude peer aliases recorded for coordinators not yet restarted."""
    try:
        data = json.loads(REGISTRY.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember(key, peer, note=""):
    """Record that <key>'s coordinator currently answers to the peer name <peer>."""
    data = registry()
    if peer and peer != key:
        data[key] = {"peer": peer, "note": note, "at": time.time()}
    else:
        data.pop(key, None)
    try:
        REGISTRY.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def peer_name(key):
    """The name dispatch should address today: canonical unless an alias is on file."""
    row = registry().get(key)
    return (row or {}).get("peer") or key


def start_command(project, path=None, shell_quote=None):
    """Start or continue this project's coordinator under its canonical name."""
    import shlex

    quote = shell_quote or shlex.quote
    name = canonical(project)
    model = project.get("model", "opus")
    effort = f" --effort {project['effort']}" if project.get("effort") else ""
    flags = f"-n {name} --rc {name} --model {model}{effort}"
    cd = f"cd {quote(path or project['path'])}"
    return f"{cd} && (claude -c {flags} || claude {flags})"


def restart_command(project):
    """What Jay runs in the coordinator's own pane to adopt the canonical name.

    `-c` continues the same conversation, so nothing in it is lost; the session
    only has to be idle at the moment it is restarted.
    """
    name = canonical(project)
    model = project.get("model", "opus")
    effort = f" --effort {project['effort']}" if project.get("effort") else ""
    return f"claude -c -n {name} --rc {name} --model {model}{effort}"


def pane_for(project, panes, r=None):
    """The live pane of this project's coordinator, only when the resolver is sure."""
    r = r or resolution(project, panes)
    if r["state"] != "ready":
        return None
    return next((p for p in panes if isinstance(p, dict) and p.get("pane_id") == r["paneId"]), None)


def adopt(cfg, panes):
    """Make the herdr layer canonical. Returns one row per project."""
    out = []
    for p in cfg["projects"]:
        name = canonical(p)
        pane = pane_for(p, panes)
        if not pane:
            out.append({"key": p["key"], "canonical": name, "pane_id": None,
                        "renamed": False, "detail": "no live coordinator"})
            continue
        if pane.get("agent_name") == name:
            out.append({"key": p["key"], "canonical": name, "pane_id": pane["pane_id"],
                        "renamed": False, "detail": "already named"})
            continue
        ok, err = sources.agent_rename(pane["pane_id"], name)
        out.append({"key": p["key"], "canonical": name, "pane_id": pane["pane_id"],
                    "renamed": ok, "detail": "renamed" if ok else (err or "rename failed")})
    return out


def rows(cfg, panes):
    """What `board coordinators` prints: name state per project, and the fix."""
    aliases = registry()
    out = []
    for p in cfg["projects"]:
        name = canonical(p)
        pane = pane_for(p, panes)
        alias = (aliases.get(p["key"]) or {}).get("peer") or ""
        out.append({
            "key": p["key"],
            "name": p["name"],
            "canonical": name,
            "pane_id": pane["pane_id"] if pane else None,
            "status": pane["status"] if pane else "offline",
            "herdr_name": (pane or {}).get("agent_name") or "",
            "herdr_ok": bool(pane) and pane.get("agent_name") == name,
            "peer": alias or name,
            "peer_ok": not alias,
            "restart": restart_command(p),
        })
    return out


def report(cfg, panes):
    lines = []
    for r in rows(cfg, panes):
        if not r["pane_id"]:
            lines.append(f"  –  {r['canonical']}: no coordinator running")
            continue
        herdr = "✓" if r["herdr_ok"] else f"✗ herdr name {r['herdr_name'] or 'unset'}"
        if r["peer_ok"]:
            lines.append(f"  ✓  {r['canonical']}: {r['pane_id']} {r['status']} · herdr {herdr} · dispatch name canonical")
        else:
            lines.append(f"  !  {r['canonical']}: {r['pane_id']} {r['status']} · herdr {herdr} · "
                         f"dispatch still addresses {r['peer']}")
            lines.append(f"       retire the alias when it is idle: {r['restart']}")
    return "\n".join(lines) or "  no projects configured"


# ---------- Fresh session (CC-070) ----------
#
# Jay's two presses: the first asks the idle lead to record where each ticket stands and to write a ready file;
# the second, once the file says ready, sends /clear and one opening line. Both texts are fixed: only the project
# key and the ready-file path (both built here from the registry and the clock) are filled in, never Jay's words and
# never anything read from the file.

READY_DIR = Path(os.environ.get("CCD_LEAD_READY_DIR", LEGACY / "lead-handoffs"))
READY_MAX = 256                                  # only the first line is ever read
READY_RE = re.compile(r"^\s*Status:\s*ready\s*$", re.IGNORECASE)

# Evidence notes, never `handoff`: Pipeline.handoff replaces the developer's handoff wholesale (pipeline.py), so a
# lead's daily notes written that way would hide it (CC-070).
PREP_TEXT = (
    "Fresh session prep from Jay via command-center ({project}). Take no new work. For each ticket of {project} "
    "you hold, record where it stands with `python -m ccd.pipeline_cli evidence KEY --role coordinator --kind note "
    "--note \"...\"` run from the Command Center server folder; never use `pipeline_cli handoff` for this, it replaces "
    "the developer's handoff. Make sure no subagent or background job of yours is still running. Then, as your last "
    "step, run `mkdir -p` for the folder of {path} and write that file: first line exactly `Status: ready`, then a "
    "short list of where each ticket stands and what comes next. After writing it take no new work and stop; Jay "
    "clears this session next."
)
OPEN_TEXT = (
    "Fresh session for {project} (Jay, via command-center). Read docs/flow/seats/lead.md in the Command Center repo, "
    "run `python -m ccd.pipeline_cli tasks {project}` from its server folder, and read yesterday's notes in {path}. "
    "Then continue as {project}'s lead."
)


def ready_path(key, day=None):
    """<READY_DIR>/<key>/<YYYY-MM-DD>.md, fixed when the notes request is sent so a midnight rollover cannot move it.
    America/Winnipeg explicitly: the path must not depend on the host's zone (CC-070)."""
    day = day or datetime.now(ZoneInfo("America/Winnipeg")).strftime("%Y-%m-%d")
    return str(READY_DIR / key / f"{day}.md")


def prep_text(project, path):
    return PREP_TEXT.format(project=project["key"], path=path)


def open_text(project, path):
    return OPEN_TEXT.format(project=project["key"], path=path)


def read_ready(path):
    """(ready, mtime) for the lead's ready file. The path must be <READY_DIR>/<key>/<file>. The chain is opened one
    directory at a time without following links (READY_DIR itself, then the project folder, then the file, each
    relative to the previous descriptor), so a swapped directory cannot redirect the read. The file must be regular;
    only its first 256 bytes are read, a first line that reaches that limit is rejected, and only a yes or no leaves."""
    p = Path(path)
    if p.parent.parent != READY_DIR or not NAME_RE.match(p.parent.name) or "/" in p.name or p.name in ("", ".", ".."):
        return False, 0.0
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    base = key_fd = fd = None
    try:
        base = os.open(str(READY_DIR), flags)
        key_fd = os.open(p.parent.name, flags, dir_fd=base)
        fd = os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=key_fd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return False, 0.0
        raw = os.read(fd, READY_MAX)
    except OSError:
        return False, 0.0
    finally:
        for f in (fd, key_fd, base):
            if f is not None:
                os.close(f)
    if b"\n" not in raw and len(raw) >= READY_MAX:
        return False, 0.0              # the first line has no verified end
    first = raw.decode("utf-8", "replace").splitlines()[0] if raw else ""
    return bool(READY_RE.match(first)), st.st_mtime
