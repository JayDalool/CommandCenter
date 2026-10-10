"""Readable task records: ~/command-center/task-records/<PROJECT>/<KEY>/{task.md, workflow.md, files/}.

The structured truth is tasks.db (tickets, ticket_events, ticket_work, questions, evidence). These two
Markdown files are a rendering of it that a person can read without Command Center, kept in Command
Center-managed storage and NEVER written into a product repository (spec §23).

    task.md       stable task information: why, problem, requirements, plan, acceptance criteria
    workflow.md   the lifecycle with evidence: planning → implementation → review rounds → rework →
                  UI testing → verification → merge → deployment → closed, every backward move included
    files/        reserved for evidence files Jay or an agent keeps with the record (screenshots …)

Rendering is pure (`render_task`, `render_workflow`); `write` replaces both files atomically. Nothing
here runs a command or reads a repository.
"""
import os
import re
import tempfile
import time
from pathlib import Path

from .config import LEGACY

RECORDS_DIR = Path(os.environ.get("CCD_RECORDS_DIR", LEGACY / "task-records"))
KEY_SAFE = re.compile(r"^[A-Z][A-Z0-9-]{1,20}$")
PROJECT_SAFE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


def _ts(at):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at)) if at else "—"


def _section(description, names):
    """The text under `## <name>` (any of names) in a ticket description, else ''."""
    if not description:
        return ""
    lines = description.splitlines()
    out, on = [], False
    for line in lines:
        m = re.match(r"^#{1,3}\s+(.*?)\s*$", line)
        if m:
            on = m.group(1).strip().lower().rstrip(":") in names
            continue
        if on:
            out.append(line)
    return "\n".join(out).strip()


def dossier(ticket, work):
    """Why / problem / cause / requirements / plan / acceptance, manager-readable, from what was recorded.
    Prefers explicit `## Why` … sections in the description; falls back to the plan."""
    d = ticket.get("description") or ""
    plan = work.get("plan") or {}
    why = _section(d, {"why", "why we're doing this", "why we are doing this", "goal"})
    problem = _section(d, {"problem", "what is broken", "what's missing"})
    cause = _section(d, {"cause", "root cause"})
    acceptance = _section(d, {"acceptance criteria", "acceptance", "done when"})
    reqs = plan.get("requirements") or []
    if not why:
        # A description without sections is the why, in the author's words.
        why = d.strip() if d and not re.search(r"^#{1,3}\s", d, re.M) else (plan.get("summary") or "")
    crit = [re.sub(r"^\s*[-*]\s*(\[[ xX]\]\s*)?", "", line).strip() for line in acceptance.splitlines() if line.strip()]
    if not crit:
        crit = list(plan.get("tests") or []) or list(reqs)
    return {"why": why, "problem": problem, "cause": cause, "requirements": reqs,
            "plan": plan, "acceptance": crit, "done": ticket.get("status") == "DONE"}


def render_task(ticket, work):
    x = dossier(ticket, work)
    plan = x["plan"]
    out = [f"# {ticket['key']} — {ticket['title']}", "",
           f"Project: {ticket['project']} · Stage: {work.get('visibleStage') or ticket['status']} · "
           f"Priority: {ticket.get('priority') or '—'}", ""]

    def sec(title, body):
        out.extend([f"## {title}", "", body.strip() if body and body.strip() else "_Not recorded._", ""])
    sec("Why", x["why"])
    sec("Problem", x["problem"])
    sec("Cause", x["cause"])
    sec("Requirements", "\n".join(f"- {r}" for r in x["requirements"]))
    plan_lines = []
    if plan.get("summary"):
        plan_lines.append(plan["summary"])
    if plan.get("approach"):
        plan_lines += ["", plan["approach"]]
    if plan.get("affected"):
        plan_lines += ["", "Affected: " + ", ".join(plan["affected"])]
    if plan.get("risk"):
        plan_lines += ["", "Risk: " + plan["risk"]]
    sec(f"Plan ({work.get('planState') or 'none'})", "\n".join(plan_lines))
    mark = "x" if x["done"] else " "
    sec("Acceptance Criteria", "\n".join(f"- [{mark}] {c}" for c in x["acceptance"]))
    return "\n".join(out).rstrip() + "\n"


# Timeline kinds → the workflow section they belong to.
_SECTION = {
    "pipeline.plan": "Planning", "pipeline.plan_accepted": "Planning", "pipeline.replan": "Planning",
    "pipeline.started": "Implementation", "pipeline.rework": "Rework", "pipeline.writer": "Implementation",
    "pipeline.review": "Review", "pipeline.review_stale": "Review", "pipeline.ready_to_merge": "Review",
    "pipeline.not_ready": "Review", "pipeline.verified": "Verification", "pipeline.merged": "Merge",
    "pipeline.unreviewed_merge": "Merge", "pipeline.auto_merge_held": "Merge", "pipeline.auto_merged": "Merge",
    "pipeline.auto_merge_failed": "Merge", "pipeline.deploy_requested": "Deployment",
    "pipeline.deploy_approved": "Deployment", "pipeline.deployed": "Deployment", "pipeline.done": "Closed",
    "pipeline.released": "Closed", "pipeline.questions": "Questions", "pipeline.answered": "Questions",
    "pipeline.blocked": "Blocked", "pipeline.gate_opened": "Gates", "pipeline.gate_confirmed": "Gates",
    "pipeline.evidence": "Evidence", "pipeline.finding": "Review", "pipeline.handoff": "Handoff",
}


def path_of(ticket, work):
    """The ordered walk of the ticket through the stages, backward moves included (from the audit trail)."""
    steps = []
    for e in ticket.get("timeline") or []:
        if e.get("field") == "status" and e.get("to"):
            steps.append((e["at"], e.get("from") or "—", e["to"], e.get("trigger") or ""))
    return steps


def render_workflow(ticket, work):
    roles = work.get("roles") or {}

    def who(role):
        r = roles.get(role) or {}
        return " · ".join(x for x in (r.get("model"), r.get("session")) if x) or "—"
    out = [f"# Workflow — {ticket['key']}", "",
           f"Current stage: **{work.get('visibleStage') or ticket['status']}** (status `{ticket['status']}`)", ""]

    out += ["## Path", ""]
    steps = path_of(ticket, work)
    if steps:
        out += [f"- {_ts(at)} · {frm} → **{to}**" + (f" — {why}" if why else "") for at, frm, to, why in steps]
    else:
        out.append("_No stage changes recorded yet._")
    out.append("")

    out += ["## Planning", "", f"Model: {who('planner')}", f"Result: {work.get('planState') or 'none'}"]
    if (work.get("plan") or {}).get("summary"):
        out.append(f"Plan: {work['plan']['summary']}")
    out.append("")

    out += ["## Implementation", "", f"Model: {who('implementer')}", f"Branch: {ticket.get('branch') or '—'}",
            f"Worktree: {work.get('worktree') or '—'}", f"Writer: {work.get('writer') or '—'}"]
    cp = work.get("checkpoint")
    if cp:
        out += [f"Checkpoint ({cp.get('frm') or '—'} → {cp.get('to')}, {_ts(cp.get('at'))}): "
                f"commit {cp.get('commit') or '—'}; remaining: {cp.get('remaining') or '—'}"]
    out.append("")

    # Review rounds: one per recorded review event, with that round's findings.
    findings = work.get("findings") or []
    rounds = [e for e in ticket.get("timeline") or [] if e.get("kind") == "pipeline.review"]
    for i, e in enumerate(rounds, 1):
        d = e.get("data") or {}
        head = d.get("head") or ""
        out += [f"## Review round {i}", "", f"Result: {'PASS' if d.get('verdict') == 'APPROVE' else 'CHANGES REQUESTED'}"
                f" at `{head[:12]}` ({_ts(e['at'])})", f"Reviewer: {who('reviewer') if i == len(rounds) else '—'}"]
        mine = [f for f in findings if f.get("head") == head and f.get("source") == "review"]
        if mine:
            out.append("Findings:")
            out += [f"- [{f['scope']} scope · {f['category']}] {f['summary']}" for f in mine]
        out.append("")
    for e in ticket.get("timeline") or []:
        if e.get("kind") == "pipeline.rework":
            out += ["## Rework", "", f"{_ts(e['at'])} — {e.get('trigger') or ''}", ""]
        if e.get("kind") == "pipeline.replan":
            out += ["## Re-plan", "", f"{_ts(e['at'])} — {e.get('trigger') or ''}", ""]

    qs = work.get("questions") or []
    if qs:
        out += ["## Questions for Jay", ""]
        for q in qs:
            out.append(f"- {q['text']}")
            out.append(f"  - answer: {q['answer']} ({_ts(q.get('answeredAt'))})" if q.get("answer") else "  - _unanswered_")
        out.append("")

    ev = work.get("evidence") or []
    ui = [e for e in ev if e["kind"] in ("screenshot", "image")]
    out += ["## UI Testing", "", f"Result: {'owner check open' if work.get('gate') == 'ui' else ('done' if ui else '—')}"]
    if ui:
        out.append("Evidence:")
        out += [f"- {e['kind']}: {e['ref']}" + (f" — {e['note']}" if e.get("note") else "") for e in ui]
    out.append("")

    v = work.get("verification")
    out += ["## Verification", "", f"Model: {who('verifier')}",
            f"Result: {(v or {}).get('result', '—').upper() if v else '—'}"]
    if v:
        out.append(f"Evidence: {v.get('evidence')}")
    out.append("")

    m = work.get("merge")
    out += ["## Merge", "", f"{m['pr']} merged at `{(m.get('sha') or '')[:12]}` ({_ts(m.get('at'))})" if m else "—", ""]

    d = work.get("deploy")
    out += ["## Deployment", ""]
    if d:
        out += [f"Environment: {d.get('env')}", f"What goes live: {d.get('what')}",
                f"Requested: {_ts(d.get('requestedAt'))} · Approved: {_ts(d.get('approvedAt'))}",
                f"Result: {(d.get('result') or 'pending').upper()}" + (f" — {d.get('evidence')}" if d.get("evidence") else "")]
    else:
        out.append("—")
    out.append("")

    other = [e for e in ev if e["kind"] not in ("screenshot", "image")]
    if other:
        out += ["## Evidence", ""]
        out += [f"- {_ts(e['at'])} · {e['stage'] or '—'} · {e['kind']}: {e['ref']}"
                + (f" — {e['note']}" if e.get("note") else "") for e in other]
        out.append("")

    b = work.get("blocked")
    if b:
        out += ["## Blocked", "", f"{b.get('stage')}: {b.get('reason')} ({_ts(b.get('at'))})", ""]

    closed = ticket.get("status") in ("DONE", "DENIED", "CANCELLED")
    rel = work.get("released")
    out += ["## Closed", "", f"{ticket['status']} at {_ts(ticket.get('completedAt'))}" if closed else "—"]
    if rel:
        out.append(f"Released: {', '.join(rel.get('ptys') or []) or 'no terminals'}; "
                   f"task Claude: {rel.get('claude') or 'none running'}")
    out.append("")
    return "\n".join(out).rstrip() + "\n"


def record_dir(ticket, root=None):
    project, key = ticket["project"], ticket["key"]
    if not PROJECT_SAFE.match(project or "") or not KEY_SAFE.match(key or ""):
        raise ValueError("unsafe project or key for a record path")
    return Path(root or RECORDS_DIR) / project / key


def _atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write(ticket, work, root=None):
    """Render and atomically replace task.md and workflow.md. Returns the record directory."""
    d = record_dir(ticket, root)
    (d / "files").mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic(d / "task.md", render_task(ticket, work))
    _atomic(d / "workflow.md", render_workflow(ticket, work))
    return d
