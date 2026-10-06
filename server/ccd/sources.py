"""Raw data sources: GitHub (gh), local git checkouts, herdr, the server.

Every function returns plain data and never raises: failures come back as
{"error": "..."} so one broken source never blanks the board.

Set CCBOARD_FIXTURES=<dir> to read canned JSON instead of calling gh/herdr/
docker (used for testing).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

FIXTURES = os.environ.get("CCBOARD_FIXTURES")


# Subprocesses started, by program name. /api/health reports these so the
# gh/git budget is measured, not guessed.
CALLS = Counter()


def _run(args, timeout=25, cwd=None):
    CALLS[args[0]] += 1
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{args[0]} not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} timed out"


def _fixture(name):
    p = Path(FIXTURES) / name
    return json.loads(p.read_text()) if p.exists() else None


# ---------- GitHub ----------

# One GraphQL query per repository replaces the five `gh` calls the legacy
# board makes (issue list, pr list, merged, closed, run list). The result is
# reshaped into exactly what those five calls returned, so model.py is unchanged.
GITHUB_QUERY = """
query($owner: String!, $name: String!, $ref: String!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage }
      nodes { number title url updatedAt labels(first: 20) { nodes { name } } }
    }
    pullRequests(states: OPEN, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number title url isDraft reviewDecision mergeable headRefName headRefOid updatedAt
        labels(first: 20) { nodes { name } }
        commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      }
    }
    merged: pullRequests(states: MERGED, first: 30, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title url mergedAt mergeCommit { oid } }
    }
    closed: issues(states: CLOSED, first: 30, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title url closedAt stateReason }
    }
    ref(qualifiedName: $ref) {
      target { ... on Commit { oid url statusCheckRollup { state } } }
    }
  }
}
"""

def _labels_of(node):
    return [{"name": l["name"]} for l in ((node.get("labels") or {}).get("nodes") or []) if l]


def _rollup_list(state):
    """statusCheckRollup as the list ci_mark() expects; [] when there are no checks."""
    return [{"state": state}] if state else []


def _main_ci(ref):
    """The branch head's combined check state, in `gh run list` shape.

    Covers every check on the head commit, not just the last workflow run. A
    head commit with no checks at all renders as no data ("–").
    """
    target = (ref or {}).get("target") or {}
    state = ((target.get("statusCheckRollup") or {}).get("state") or "").upper()
    if not state:
        return []
    conclusion = {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure"}.get(state, "")
    status = "completed" if conclusion else "in_progress"
    return [{"conclusion": conclusion, "status": status, "workflowName": "checks",
             "url": target.get("url") or "", "createdAt": ""}]


def reshape(data):
    """GraphQL repository payload → the legacy five-key dict."""
    repo = (data or {}).get("data", {}).get("repository")
    if not repo:
        msg = ((data or {}).get("errors") or [{"message": "repository not found"}])[0].get("message", "")
        err = {"error": str(msg)[:160]}
        return {k: err for k in ("issues", "prs", "merged", "closed", "ci")}
    issues = [{"number": n["number"], "title": n["title"], "url": n["url"], "updatedAt": n["updatedAt"],
               "labels": _labels_of(n)} for n in repo["issues"]["nodes"]]
    prs = []
    for n in repo["pullRequests"]["nodes"]:
        commits = (n.get("commits") or {}).get("nodes") or []
        state = (((commits[0] if commits else {}).get("commit") or {}).get("statusCheckRollup") or {}).get("state")
        prs.append({"number": n["number"], "title": n["title"], "url": n["url"], "isDraft": n["isDraft"],
                    "reviewDecision": n.get("reviewDecision"), "mergeable": n.get("mergeable"),
                    "headRefName": n["headRefName"],
                    "headRefOid": n["headRefOid"], "updatedAt": n["updatedAt"], "labels": _labels_of(n),
                    "statusCheckRollup": _rollup_list(state)})
    return {
        "issues": issues,
        "prs": prs,
        "merged": [dict(n) for n in repo["merged"]["nodes"]],
        "closed": [dict(n) for n in repo["closed"]["nodes"]],
        "ci": _main_ci(repo.get("ref")),
        "truncated": bool(repo["issues"]["pageInfo"]["hasNextPage"]),
    }


def github(project):
    """Everything the board needs from one repository, in one `gh` call."""
    if FIXTURES:
        data = _fixture(f"{project['key']}.graphql.json")
        return reshape(data) if data is not None else reshape(None)
    owner, _, name = project["repo"].partition("/")
    code, out, err = _run(["gh", "api", "graphql", "-f", f"query={GITHUB_QUERY}",
                           "-f", f"owner={owner}", "-f", f"name={name}",
                           "-f", f"ref=refs/heads/{project['branch']}"])
    if code != 0:
        e = {"error": (err.strip().splitlines() or ["gh failed"])[-1][:160]}
        return {k: e for k in ("issues", "prs", "merged", "closed", "ci")}
    try:
        return reshape(json.loads(out or "{}"))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        bad = {"error": f"gh returned an unexpected shape: {type(e).__name__}"}
        return {k: bad for k in ("issues", "prs", "merged", "closed", "ci")}


# ---------- local checkout ----------

def read_text(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def checklist(path):
    """Open and done counts plus the first few open lines of a checkbox file."""
    text = read_text(path)
    if text is None:
        return {"exists": False, "open": 0, "done": 0, "items": []}
    open_items = [l.split("]", 1)[1].strip() for l in text.splitlines() if re.match(r"\s*[-*] \[ \]", l)]
    done = len([l for l in text.splitlines() if re.match(r"\s*[-*] \[[xX]\]", l)])
    return {"exists": True, "open": len(open_items), "done": done, "items": open_items[:8]}


def unpushed_branches(path):
    """Local branches with commits no remote has. Local refs only, no fetch.

    `git log --format=%S` tags every unpushed commit with the branch it was
    reached from, so one call answers for all branches. This used to run
    `rev-list --count` once per branch: 209 git subprocesses per board refresh
    on samvisionai alone, every 5 minutes from cron.
    """
    if FIXTURES:
        return _fixture(f"{Path(path).name}.unpushed.json") or []
    code, out, _ = _run(["git", "-C", path, "log", "--format=%S", "--branches", "--not", "--remotes"])
    if code != 0:
        return []
    counts = Counter(line.strip() for line in out.splitlines() if line.strip())
    if not counts:
        return []
    code, out, _ = _run(["git", "-C", path, "for-each-ref",
                         "--format=%(refname:short)|%(committerdate:unix)", "refs/heads"])
    when = {}
    if code == 0:
        for line in out.splitlines():
            name, _, ts = line.partition("|")
            if ts.strip().isdigit():
                when[name] = int(ts)
    now = time.time()
    # An unknown date means age 0, never a fabricated "not pushed for 20000 days".
    return [{"branch": b, "commits": n, "age_h": (now - when.get(b, now)) / 3600}
            for b, n in sorted(counts.items())]


def branch_heads(path):
    """branch → (unix committer date, short SHA). One call for every branch."""
    code, out, _ = _run(["git", "-C", path, "for-each-ref",
                         "--format=%(refname:short)|%(committerdate:unix)|%(objectname:short)", "refs/heads"])
    heads = {}
    if code != 0:
        return heads
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[1].strip().isdigit():
            heads[parts[0]] = (int(parts[1]), parts[2])
    return heads


def branches_ahead(path, base="main"):
    """Every local branch with commits the base branch does not have.

    The Development view answers "how much work exists for this ticket" from
    this: ticket → branch → commits. `git log --format=%S --branches --not
    <base>` tags each commit with the branch it was reached from, so one call
    counts them all (the same trick unpushed_branches uses — a count per branch
    would be one subprocess per branch, 200+ on samvisionai).
    """
    if FIXTURES:
        return _fixture(f"{Path(path).name}.branches.json") or {}
    # `base` comes from config.json. A value starting with "-" would reach git as
    # an option, so it is refused rather than passed through.
    if not re.match(r"^[A-Za-z0-9][\w./-]{0,100}$", base or ""):
        return {}
    code, out, _ = _run(["git", "-C", path, "log", "--format=%S", "--branches", "--not", base])
    if code != 0:
        # An unknown base (a repo on master, a fresh clone): report heads only,
        # never a fabricated commit count.
        counts = Counter()
    else:
        counts = Counter(line.strip() for line in out.splitlines() if line.strip())
    heads = branch_heads(path)
    out_rows = {}
    for b, (when, sha) in heads.items():
        if b == base:
            continue
        out_rows[b] = {"commits": counts.get(b, 0), "head": sha, "at": when,
                       "countOk": code == 0}
    return out_rows


def worktree_count(path):
    """Lane worktrees, not counting the checkout itself."""
    return max(0, len(worktree_paths(path)) - 1)


def agent_models(path):
    """Team from the repo's .claude/agents/*.md frontmatter (name, model)."""
    team = []
    for f in sorted(glob.glob(os.path.join(path, ".claude", "agents", "*.md"))):
        text = read_text(f) or ""
        m = re.match(r"---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        fm = dict(re.findall(r"^(\w[\w-]*):\s*(.+)$", m.group(1), re.M))
        team.append({"name": fm.get("name", Path(f).stem), "model": fm.get("model", "inherit").strip()})
    return team


# ---------- herdr ----------
#
# The snapshot is FLAT: `workspaces`, `tabs`, `panes` and `agents` are separate
# top-level lists, and `layouts` repeats every pane_id for geometry only.
# Walking the whole document (what this module used to do) therefore returned
# the same pane three or four times and never resolved a workspace label.

def herdr_snapshot():
    """The live session snapshot, parsed. {"error": ...} when herdr can't answer."""
    if FIXTURES:
        data = _fixture("herdr.snapshot.json")
        return data if data is not None else {"error": "no herdr.snapshot.json fixture"}
    code, out, err = _run(["herdr", "api", "snapshot"], timeout=8)
    if code != 0:
        return {"error": (err.strip().splitlines() or ["herdr not reachable"])[-1][:120]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": "herdr snapshot was not JSON"}


def snapshot_body(data):
    """The snapshot itself, whether it came bare or inside the CLI's envelope."""
    if not isinstance(data, dict):
        return {}
    result = data.get("result")
    if isinstance(result, dict) and isinstance(result.get("snapshot"), dict):
        return result["snapshot"]
    return data


# Fields worth carrying onto a board row. `panes` entries hold the pane label,
# `agents` entries the agent name and Claude session id; a pane in both lists
# gets the union, agent values last because that list is the live record.
_CARRY = ("agent_status", "cwd", "foreground_cwd", "label", "terminal_title_stripped",
          "tab_id", "workspace_id", "agent", "name", "agent_session")


def panes_from(snapshot):
    """One row per pane_id, from the flat `panes` and `agents` lists only.

    `live` is True for the panes herdr currently sees an agent in: that, not
    quad.json, is what "running" means on the board.
    """
    snap = snapshot_body(snapshot)
    ws_label = {w.get("workspace_id"): (w.get("label") or "")
                for w in snap.get("workspaces") or [] if isinstance(w, dict)}
    merged = {}
    for live, entries in ((False, snap.get("panes")), (True, snap.get("agents"))):
        for e in entries or []:
            if not isinstance(e, dict) or not e.get("pane_id"):
                continue
            row = merged.setdefault(e["pane_id"], {"live": False})
            for f in _CARRY:
                if e.get(f) not in (None, "", {}):
                    row[f] = e[f]
            row["live"] = row["live"] or live
    out = []
    for pane_id, r in merged.items():
        session = r.get("agent_session") if isinstance(r.get("agent_session"), dict) else {}
        out.append({
            "pane_id": pane_id,
            "status": r.get("agent_status") or "unknown",
            "live": r["live"],
            "agent": r.get("agent") or "",
            "agent_name": r.get("name") or "",
            "label": r.get("label") or "",
            "title": r.get("terminal_title_stripped") or "",
            "cwd": r.get("foreground_cwd") or r.get("cwd") or "",
            "workspace_id": r.get("workspace_id") or "",
            "workspace": ws_label.get(r.get("workspace_id"), ""),
            "tab_id": r.get("tab_id") or "",
            "session_id": session.get("value") or "",
        })
    out.sort(key=lambda p: p["pane_id"])
    return out


def layout_from(snapshot):
    """Workspaces, tabs and pane rectangles from the snapshot: geometry only.

    The Workspaces screen draws herdr's real split layout from this. No titles
    and no output: a terminal title can quote anything.
    """
    snap = snapshot_body(snapshot)
    workspaces = [{"id": w.get("workspace_id"), "label": w.get("label") or "", "number": w.get("number"),
                   "focused": bool(w.get("focused")), "activeTabId": w.get("active_tab_id")}
                  for w in snap.get("workspaces") or [] if isinstance(w, dict) and w.get("workspace_id")]
    workspaces.sort(key=lambda w: (w["number"] is None, w["number"] or 0))
    tabs = [{"id": t.get("tab_id"), "workspaceId": t.get("workspace_id"), "label": t.get("label") or "",
             "number": t.get("number"), "focused": bool(t.get("focused"))}
            for t in snap.get("tabs") or [] if isinstance(t, dict) and t.get("tab_id")]
    tabs.sort(key=lambda t: (t["number"] is None, t["number"] or 0))
    layouts = {}
    for l in snap.get("layouts") or []:
        if not isinstance(l, dict) or not l.get("tab_id"):
            continue
        area = l.get("area") or {}
        layouts[l["tab_id"]] = {
            "area": {"w": area.get("width", 0), "h": area.get("height", 0)},
            "zoomed": bool(l.get("zoomed")), "focusedPaneId": l.get("focused_pane_id"),
            "panes": [{"paneId": p.get("pane_id"), "focused": bool(p.get("focused")),
                       "rect": {"x": (p.get("rect") or {}).get("x", 0), "y": (p.get("rect") or {}).get("y", 0),
                                "w": (p.get("rect") or {}).get("width", 0), "h": (p.get("rect") or {}).get("height", 0)}}
                      for p in l.get("panes") or [] if isinstance(p, dict) and p.get("pane_id")],
        }
    return {"workspaces": workspaces, "tabs": tabs, "layouts": layouts}


def herdr_panes():
    """Every pane herdr knows about, de-duplicated. {"error": ...} on failure."""
    if FIXTURES:
        canned = _fixture("herdr.panes.json")
        if canned is not None:
            return canned
    snap = herdr_snapshot()
    if isinstance(snap, dict) and "error" in snap and "result" not in snap:
        return snap
    return panes_from(snap)


def agent_panes(panes):
    """The panes with a live agent in them, oldest pane id first."""
    return [p for p in panes if isinstance(p, dict) and p.get("live")]


def pane_tail(pane_id, lines=6):
    if FIXTURES:
        return (_fixture("herdr.tails.json") or {}).get(pane_id, "")
    code, out, _ = _run(["herdr", "pane", "read", pane_id, "--source", "recent", "--lines", str(lines)], timeout=6)
    return out if code == 0 else ""


def pane_type(pane_id, text, enter=False):
    """Put literal text in a pane. Without enter it waits for Jay to press it."""
    if FIXTURES:
        return True
    code, _, _ = _run(["herdr", "pane", "send-text", pane_id, text], timeout=6)
    if code != 0 or not enter:
        return code == 0
    code, _, _ = _run(["herdr", "pane", "send-keys", pane_id, "Enter"], timeout=6)
    return code == 0


def agent_focus(target):
    """Focus the pane hosting an agent, by herdr agent name or pane id.

    `herdr pane focus` takes --direction and cannot be given a pane id; calling
    it with one, as this board used to, is a usage error that always failed.
    """
    if FIXTURES:
        return True
    code, _, _ = _run(["herdr", "agent", "focus", target], timeout=6)
    return code == 0


def tab_focus(tab_id):
    """Bring a tab forward: how focus comes back to a pane with no agent in it."""
    if FIXTURES:
        return True
    code, _, _ = _run(["herdr", "tab", "focus", tab_id], timeout=6)
    return code == 0


def focus(pane_id):
    """Bring a pane into view: its agent when one lives there, else its tab."""
    if FIXTURES:
        return True
    if agent_focus(pane_id):
        return True
    row = next((p for p in panes_from(herdr_snapshot()) if p["pane_id"] == pane_id), None)
    return tab_focus(row["tab_id"]) if row and row["tab_id"] else False


def agent_rename(target, name):
    """Give a live agent a deterministic herdr name. Renaming interrupts nothing."""
    if FIXTURES:
        return True, ""
    code, _, err = _run(["herdr", "agent", "rename", target, name], timeout=6)
    return code == 0, (err.strip().splitlines() or [""])[-1][:120]


def worktree_paths(path):
    """Every worktree directory of a checkout, the main one first.

    Lane agents run in worktrees outside the checkout, so a pane's project
    can only be read from its cwd once these are known.
    """
    if FIXTURES:
        return _fixture(f"{Path(path).name}.worktree_paths.json") or [path]
    code, out, _ = _run(["git", "-C", path, "worktree", "list", "--porcelain"])
    if code != 0:
        return [path]
    found = [l[len("worktree "):].strip() for l in out.splitlines() if l.startswith("worktree ")]
    return found or [path]


# ---------- server ----------

def server(cfg):
    if FIXTURES:
        return _fixture("server.json") or {}
    total, used, _ = shutil.disk_usage("/")
    info: dict = {"disk": round(used * 100 / total)}
    code, out, _ = _run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.State}}"], timeout=8)
    if code == 0:
        rows = [l.split("|") for l in out.splitlines() if "|" in l]
        info["containers_up"] = sum(1 for _, s in rows if s == "running")
        info["containers_total"] = len(rows)
        info["down"] = [n for n, s in rows if s != "running"][:5]
        info["running"] = sorted(n for n, s in rows if s == "running")
        info["containers"] = [{"name": n, "state": s} for n, s in sorted(rows)][:60]
    if cfg.get("backup_status_glob"):
        files = glob.glob(cfg["backup_status_glob"])
        if files:
            info["backup_age_h"] = round((time.time() - max(os.path.getmtime(f) for f in files)) / 3600, 1)
    return info
