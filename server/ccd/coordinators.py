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
import re
import time

from . import sources
from .config import STATE_DIR

REGISTRY = STATE_DIR / "coordinators.json"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")  # herdr's rule for agent names


def canonical(project):
    """The one name this project's coordinator answers to."""
    return project["key"]


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


def pane_for(project, panes):
    """The live agent pane that is this project's coordinator, if one is running.

    The coordinator is the live agent whose cwd is the checkout root itself; a
    lane agent sits in a worktree, so it never wins this.
    """
    mine = [p for p in sources.agent_panes(panes) if p.get("project") == project["key"]]
    if not mine:
        return None
    exact = [p for p in mine if p.get("cwd") == project.get("path")]
    named = [p for p in mine if p.get("agent_name") == canonical(project)]
    return (named or exact or mine)[0]


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
