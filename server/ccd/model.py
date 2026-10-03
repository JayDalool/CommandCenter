"""Turn raw sources into what the board shows: short, sorted, actionable."""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import coordinators, sources
from .config import HANDOFF_DIR, STATE_DIR

STAGE_LABEL = {
    "needs_jay": "needs you", "legal": "lawyer", "ui_review": "UI review", "deploy": "deploy",
    "working": "building", "review": "review", "ready": "up next", "blocked": "blocked", "backlog": "backlog",
}
INDEX_MAP = {
    "PROPOSED": "backlog", "RESEARCHING": "backlog", "READY_TO_IMPLEMENT": "ready",
    "IN_PROGRESS": "working", "IN_REVIEW": "review", "READY_TO_MERGE": "needs_jay",
    "VERIFYING": "ui_review", "BLOCKED": "blocked",
}
STAGE_ORDER = ["working", "needs_jay", "review", "ui_review", "deploy", "legal", "ready", "blocked", "backlog"]


def _age_h(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except (ValueError, AttributeError):
        return 0.0


def _labels(item):
    return [l["name"] if isinstance(l, dict) else l for l in item.get("labels", [])]


def stage_from_labels(labels):
    s = set(labels)
    for flag, stage in (("needs:legal", "legal"), ("needs:jay", "needs_jay"),
                        ("needs:ui-review", "ui_review"), ("needs:deploy", "deploy")):
        if flag in s:
            return stage
    for lab, stage in (("status:in-progress", "working"), ("status:review", "review"),
                       ("status:ready", "ready"), ("status:blocked", "blocked")):
        if lab in s:
            return stage
    return "backlog"


def ci_mark(rollup):
    if not rollup:
        return "–"
    states = [(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup]
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED") for s in states):
        return "✗"
    if any(s in ("", "PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", "WAITING") for s in states):
        return "…"
    return "✓"


def short(text, n=42):
    text = re.sub(r"^(?:SV|GYST-VN|MFE|GM)-\d+\s*[—:-]\s*", "", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def ref_of(title, number=None):
    m = re.search(r"\b((?:SV|GYST-VN|MFE|GM)-\d+)\b", title or "")
    return m.group(1) if m else (f"#{number}" if number else "")


def tasks_from_index(path):
    text = sources.read_text(path) or ""
    tasks = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not re.match(r"^[A-Z]+-\d+$", cells[0]):
            continue
        tid, title, _prio, status, dep = cells[:5]
        word = status.split()[0].rstrip("(").upper() if status else ""
        if word in ("DONE", "DENIED"):
            continue
        stage = INDEX_MAP.get(word, "backlog")
        low = (status + " " + dep).lower()
        if word == "BLOCKED" and "legal" in low:
            stage = "legal"
        if word == "VERIFYING" and ("needs jay" in low or "drill pending" in low):
            stage = "needs_jay"
        tasks.append({"ref": tid, "title": short(title.replace("`", "")), "stage": stage, "url": None, "flags": []})
    return tasks


def question_from(tail):
    """The agent's question: the last line with a '?', else the last real line."""
    lines = [l.strip(" │>❯›\t") for l in tail.splitlines()]
    lines = [l for l in lines if len(l) > 3]
    q = next((l for l in reversed(lines) if "?" in l), lines[-1] if lines else "")
    return q if len(q) <= 110 else q[:109] + "…"


def _blocked_since(panes):
    """Remember when each pane first showed as blocked, so 'stuck > N min' works."""
    path = STATE_DIR / "blocked_since.json"
    try:
        seen = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        seen = {}
    now = time.time()
    current = {p["pane_id"] for p in panes if p["status"] == "blocked"}
    seen = {k: v for k, v in seen.items() if k in current}
    for k in current:
        seen.setdefault(k, now)
    try:
        path.write_text(json.dumps(seen))
    except OSError:
        pass
    return {k: (now - v) / 60 for k, v in seen.items()}


def _under(cwd, root):
    """True when cwd is root or inside it, on a path boundary.

    Plain startswith made /srv/server/repos/gyst-lifeops-scratch look like a
    pane of gyst-lifeops.
    """
    if not cwd or not root:
        return False
    cwd, root = cwd.rstrip("/"), root.rstrip("/")
    return cwd == root or cwd.startswith(root + "/")


def _pane_project(pane, projects, worktrees=None):
    """Which project a pane belongs to, read from the flat snapshot.

    cwd decides, longest match first, with the project's git worktrees included
    because a lane agent runs outside the checkout. The workspace label is only
    a fallback: on this server every coordinator pane sits in one workspace
    called "Command Center", so a label-first rule mis-files all of them.
    """
    cwd = pane.get("cwd") or ""
    best, best_len = None, -1
    for p in projects:
        for root in [p.get("path")] + list((worktrees or {}).get(p["key"]) or []):
            if root and _under(cwd, root) and len(root) > best_len:
                best, best_len = p["key"], len(root)
    if best:
        return best
    label = (pane.get("workspace") or "").strip().lower()
    pane_label = (pane.get("label") or "").strip().lower()
    agent_name = (pane.get("agent_name") or "").strip().lower()
    for p in projects:
        session = str(p.get("session") or p["key"]).lower()
        if label in (p["key"], p["name"].strip().lower()) or session in (pane_label, agent_name):
            return p["key"]
    if label in ("command-center", "home") or _under(cwd, str(Path.home() / "command-center")):
        return "home"
    return None


def project_view(p, gh, panes, blocked_min, cfg):
    errors = [f"{k}: {v['error']}" for k, v in gh.items() if isinstance(v, dict) and "error" in v]
    ok = lambda v: v if isinstance(v, list) else []  # noqa: E731
    issues, prs, merged, closed, ci = (ok(gh[k]) for k in ("issues", "prs", "merged", "closed", "ci"))

    tasks = []
    for it in issues:
        labels = _labels(it)
        tasks.append({"ref": ref_of(it["title"], it["number"]), "title": short(it["title"]),
                      "stage": stage_from_labels(labels), "url": it.get("url"),
                      "flags": [l for l in labels if l.startswith("needs:")],
                      "you_do_it": "risk:not-agent-eligible" in labels and "status:ready" in labels,
                      "has_status": any(l.startswith("status:") for l in labels)})
    source = "issues"
    if p.get("index") and not any(t["has_status"] for t in tasks):
        idx = tasks_from_index(os.path.join(p["path"], p["index"]))
        if idx:
            tasks, source = idx, "INDEX.md"
    tasks.sort(key=lambda t: STAGE_ORDER.index(t["stage"]))

    pr_rows = []
    for pr in prs:
        mark = ci_mark(pr.get("statusCheckRollup"))
        ready = pr.get("reviewDecision") == "APPROVED" and mark in ("✓", "–") and not pr.get("isDraft")
        pr_rows.append({"number": pr["number"], "ref": ref_of(pr["title"]), "title": short(pr["title"], 38),
                        "ci": mark, "ready": ready, "draft": pr.get("isDraft"), "url": pr.get("url"),
                        "sha": (pr.get("headRefOid") or "")[:7], "age_h": _age_h(pr.get("updatedAt", "")),
                        "review": pr.get("reviewDecision"), "mergeable": pr.get("mergeable"),
                        "branch": pr.get("headRefName"), "updatedAt": pr.get("updatedAt")})

    my_panes = [x for x in panes if x["project"] == p["key"]]
    live_panes = sources.agent_panes(my_panes)
    team = []
    for pane in live_panes:
        team.append({"name": pane["agent_name"] or pane["label"] or pane["agent"] or pane["pane_id"],
                     "model": "", "status": pane["status"], "pane_id": pane["pane_id"],
                     "stuck_min": blocked_min.get(pane["pane_id"])})
    for a in sources.agent_models(p["path"]) if p["path"] else []:
        team.append({"name": a["name"].replace(p["key"] + "-", ""), "model": a["model"], "status": "via coordinator", "pane_id": None, "stuck_min": None})

    tests = {"ui": sources.checklist(os.path.join(p["path"], p["ui_tests"])) if p["path"] else sources.checklist(""),
             "actions": sources.checklist(os.path.join(p["path"], p["actions"])) if p["path"] else sources.checklist("")}

    cutoff = 48
    recent = [{"ref": f"#{m['number']}", "title": short(m["title"], 40), "url": m.get("url")}
              for m in merged if _age_h(m.get("mergedAt", "")) <= cutoff]
    recent += [{"ref": ref_of(c["title"], c["number"]), "title": short(c["title"], 40), "url": c.get("url")}
               for c in closed if _age_h(c.get("closedAt", "")) <= cutoff and c.get("stateReason") in ("COMPLETED", "completed")]

    main_ci = "–"
    if ci:
        run = ci[0]
        main_ci = {"success": "✓", "failure": "✗", "cancelled": "✗"}.get((run.get("conclusion") or "").lower(),
                                                                          "…" if run.get("status") != "completed" else "–")

    counts = {s: sum(1 for t in tasks if t["stage"] == s) for s in STAGE_LABEL}
    counts["prs"] = len(pr_rows)
    # Live agents only. This used to fall back to the GitHub "working" count, so
    # the board claimed agents were running when none were.
    counts["live"] = len(live_panes)
    counts["running"] = sum(1 for m in live_panes if m["status"] == "working")

    handoff = (sources.read_text(HANDOFF_DIR / f"{p['key']}.md") or "").strip().splitlines()[:3]

    view = {"key": p["key"], "name": p["name"], "repo": p["repo"], "path": p["path"], "source": source,
            "tasks": tasks, "prs": pr_rows, "recent": recent, "team": team, "panes": live_panes,
            "all_panes": my_panes, "tests": tests,
            "links": p["links"], "commands": p["commands"], "main_ci": main_ci, "counts": counts,
            "errors": errors, "handoff": handoff,
            "coordinator": coordinators.pane_for(p, panes)}
    view["summary"] = summary_line(view)
    return view


def summary_line(v):
    parts = []
    building = [t["ref"] for t in v["tasks"] if t["stage"] == "working"]
    if building:
        parts.append(f"{', '.join(building[:2])} building")
    waiting = sum(1 for pr in v["prs"] if not pr["ready"])
    if waiting:
        parts.append(f"{waiting} PR{'s' if waiting > 1 else ''} in review")
    ready = sum(1 for pr in v["prs"] if pr["ready"])
    if ready:
        parts.append(f"{ready} ready to merge")
    for stage, word in (("review", "in review"), ("ready", "up next")):
        n = sum(1 for t in v["tasks"] if t["stage"] == stage)
        if n and len(parts) < 3:
            parts.append(f"{n} {word}")
    if v["main_ci"] == "✗":
        parts.insert(0, "main CI red")
    return " · ".join(parts) or "quiet"


def collect(cfg):
    """Every slow source, fetched once. ccd caches these separately instead."""
    projects = cfg["projects"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        gh_futs = {p["key"]: pool.submit(sources.github, p) for p in projects}
        panes_fut = pool.submit(sources.herdr_panes)
        server_fut = pool.submit(sources.server, cfg)
        unpushed_futs = {p["key"]: pool.submit(sources.unpushed_branches, p["path"]) for p in projects if p["path"]}
        wt_futs = {p["key"]: pool.submit(sources.worktree_paths, p["path"]) for p in projects if p["path"]}
    panes_raw = panes_fut.result()
    return {
        "gh": {k: f.result() for k, f in gh_futs.items()},
        "panes": panes_raw if isinstance(panes_raw, list) else [],
        "herdr_error": panes_raw.get("error") if isinstance(panes_raw, dict) else None,
        "server": server_fut.result(),
        "unpushed": {k: f.result() for k, f in unpushed_futs.items()},
        "worktrees": {k: f.result() for k, f in wt_futs.items()},
    }


def derive(cfg, gh, panes, srv, unpushed, worktrees, blocked_min, herdr_error=None, tail_fn=None):
    """The board snapshot from already-fetched sources. No network, no git.

    `tail_fn(pane_id)` reads a blocked agent's last lines for its question; it
    is the only call here that leaves the process, and only for blocked agents.
    """
    projects = cfg["projects"]
    tail_fn = tail_fn or sources.pane_tail
    panes = [dict(p) for p in panes]
    for pane in panes:
        pane["project"] = _pane_project(pane, projects, worktrees)

    empty = {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []}
    views = [project_view(p, gh.get(p["key"]) or empty, panes, blocked_min, cfg) for p in projects]

    needs, stale, blocked = [], [], []
    for v in views:
        for pr in v["prs"]:
            if pr["ready"]:
                needs.append({"project": v["key"], "ref": f"#{pr['number']}", "text": f"merge · {pr['title']}",
                              "kind": "merge", "url": pr["url"], "sha": pr["sha"], "number": pr["number"]})
            elif pr["age_h"] > cfg["stale_pr_hours"]:
                stale.append({"project": v["key"], "text": f"PR #{pr['number']} idle {int(pr['age_h'] / 24)}d · {pr['title']}"})
        for t in v["tasks"]:
            if t["stage"] == "needs_jay":
                needs.append({"project": v["key"], "ref": t["ref"], "text": t["title"], "kind": "task", "url": t["url"]})
            elif t.get("you_do_it"):
                needs.append({"project": v["key"], "ref": t["ref"], "text": f"you do it · {t['title']}", "kind": "task", "url": t["url"]})
        if v["tests"]["actions"]["open"]:
            needs.append({"project": v["key"], "ref": "actions", "text": f"{v['tests']['actions']['open']} in My actions",
                          "kind": "actions", "url": None})
        if v["main_ci"] == "✗":
            needs.append({"project": v["key"], "ref": "CI", "text": "main is red", "kind": "ci", "url": None})
        for b in unpushed.get(v["key"]) or []:
            if b["age_h"] > 24:
                stale.append({"project": v["key"], "text": f"{b['branch']} not pushed · {int(b['age_h'] / 24)}d"})
        wt = max(0, len(worktrees.get(v["key"]) or []) - 1)  # the checkout itself is not a lane
        if wt > cfg["worktree_limit"]:
            stale.append({"project": v["key"], "text": f"{wt} worktrees (limit {cfg['worktree_limit']})"})
        for pane in v["panes"]:
            if pane["status"] == "blocked":
                q = question_from(tail_fn(pane["pane_id"]))
                blocked.append({"project": v["key"], "pane_id": pane["pane_id"],
                                "name": pane.get("agent_name") or pane["label"] or pane["pane_id"],
                                "question": q or "waiting for you", "stuck_min": blocked_min.get(pane["pane_id"], 0)})
    if srv.get("disk", 0) >= cfg["disk_warn_percent"]:
        stale.append({"project": "server", "text": f"disk {srv['disk']}%"})

    totals = {
        "needs": len(needs) + len(blocked),
        "prs": sum(v["counts"]["prs"] for v in views),
        "ui": sum(v["counts"]["ui_review"] + v["tests"]["ui"]["open"] for v in views),
        "deploy": sum(v["counts"]["deploy"] for v in views),
        "legal": sum(v["counts"]["legal"] for v in views),
        "running": sum(v["counts"]["running"] for v in views),
    }
    brief = ""
    bpath = STATE_DIR / "brief.txt"
    if bpath.exists() and datetime.fromtimestamp(bpath.stat().st_mtime).date() == datetime.now().date():
        brief = bpath.read_text().strip()

    live = sources.agent_panes(panes)
    return {"at": time.time(), "projects": views, "needs": needs, "blocked": blocked, "stale": stale,
            "server": srv, "totals": totals, "herdr_error": herdr_error, "brief": brief,
            "panes": panes, "agents": live,
            "home_panes": [x for x in live if x["project"] == "home"]}


def build(cfg):
    """collect + derive in one go: the legacy board's behaviour, kept for parity tests."""
    raw = collect(cfg)
    blocked_min = _blocked_since(raw["panes"])
    return derive(cfg, raw["gh"], raw["panes"], raw["server"], raw["unpushed"], raw["worktrees"],
                  blocked_min, herdr_error=raw["herdr_error"])
