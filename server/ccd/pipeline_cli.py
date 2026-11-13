"""How a pipeline agent records a stage result in Command Center.

    python -m ccd.pipeline_cli work     SV-056
    python -m ccd.pipeline_cli plan     SV-056 --role planner  --plan-file plan.json
    python -m ccd.pipeline_cli start    SV-056 --role coordinator --branch SV-056-x --worktree /srv/…/SV-056
    python -m ccd.pipeline_cli review   SV-056 --role reviewer --session <fresh reviewer session> --verdict APPROVE --head <sha> [--findings-file f.json]
    python -m ccd.pipeline_cli verify   SV-056 --role verifier --result pass --evidence "…"
    python -m ccd.pipeline_cli handoff  SV-056 --role coordinator --done … --next … [--decisions …] [--blockers …]
    python -m ccd.pipeline_cli block    SV-056 --role coordinator --reason "…" [--what … --why … --action … --impact … --technical …]
    python -m ccd.pipeline_cli role     SV-056 --role implementer --model sonnet --session sv-056
    python -m ccd.pipeline_cli finding  SV-056 --role reviewer --scope out --category perf --summary "…"
    python -m ccd.pipeline_cli ask      SV-056 --role coordinator --question "Same layout on mobile?" --question "…"
    python -m ccd.pipeline_cli ask      SV-056 --role coordinator --question "Export format?" --option CSV --option XLSX \
                                        --option Both --recommend 2 --why "clients open it in Excel"
    python -m ccd.pipeline_cli replan   SV-056 --role coordinator --reason "the answer changes the auth model"
    python -m ccd.pipeline_cli rework   SV-056 --role coordinator --reason "buttons overlap on narrow screens"
    python -m ccd.pipeline_cli evidence SV-056 --role verifier --kind screenshot --ref mobile-375.png [--note …]
    python -m ccd.pipeline_cli writer   SV-056 --role coordinator --owner claude [--checkpoint-file cp.json]
    python -m ccd.pipeline_cli deploy-request SV-056 --role coordinator --env live --what "…" --verification "…"
    python -m ccd.pipeline_cli deployed SV-056 --role coordinator --env live --result pass --evidence "…"
    python -m ccd.pipeline_cli stale    SV-056 --role coordinator --reason "superseded by SV-071 (plans/x.md)"
    python -m ccd.pipeline_cli tasks    samvision                  the project's open tasks (the task check)
    python -m ccd.pipeline_cli add      samvision --role coordinator --title "…" --note "plans/x.md:12" [--label night-finding]

The task check: `stale` asks Jay "Cancel it / Keep it" (only his answer cancels anything); `add` puts a
missing task in the project's Inbox.
Questions wait for Jay without ending the task session; his answers come back into the same session (or, when
no task session is running, to the project's lead in Messages).
A decision question has 2 or 3 --option values, and one of them recommended: --recommend N (1 = the first --option)
with --why "one line". Jay sees your recommendation first, plus "Something else" and "Talk it through".
A live deployment waits for Jay's approval (`deployed --env live` is refused until he gives it).

It talks to the loopback ccd (127.0.0.1:7777) with the ccd token this account already
holds, and records every write as `agent:<role>`. It cannot close an owner gate:
`confirm` needs Jay with Developer Unlock, in the UI. Prints the ticket's work state
as JSON; exit 1 with ccd's one-line reason when a step is refused.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import config

ROLES = ("coordinator", "planner", "implementer", "reviewer", "verifier")


def call(method, path, body=None, actor=None, port=None, token=None):
    port = port or int(os.environ.get("CCD_PORT", "7777"))
    token = token or config.TOKEN_PATH.read_text().strip()
    headers = {"Host": f"127.0.0.1:{port}", "X-CCD-Token": token, "Content-Type": "application/json"}
    if actor:
        headers["X-CCD-Actor"] = actor
    actor_token = _actor_token()
    if actor_token:
        headers["X-CCD-Actor-Token"] = actor_token
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 0, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return 1, json.loads(e.read() or b"{}")
        except ValueError:
            return 1, {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError) as e:
        return 1, {"error": f"Command Center is not reachable on 127.0.0.1:{port} ({getattr(e, 'reason', e)})"}


def _actor_token():
    """This caller's identity token (Phase 2, recorded only): $CCD_ACTOR_TOKEN, else the file named by
    $CCD_ACTOR_TOKEN_FILE. Missing or unreadable means none is sent; nothing is refused either way."""
    tok = os.environ.get("CCD_ACTOR_TOKEN", "").strip()
    if not tok and os.environ.get("CCD_ACTOR_TOKEN_FILE"):
        try:
            with open(os.environ["CCD_ACTOR_TOKEN_FILE"], encoding="utf-8") as f:
                tok = f.read().strip()
        except OSError:
            tok = ""
    return tok if tok and len(tok) <= 100 and tok.isascii() and tok.isprintable() else ""


def _json_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _questions(p, a):
    """--question …, or ONE --question with its --option list and an optional --recommend N --why …"""
    qs = a.question or []
    if not a.option:
        if a.recommend is not None:
            p.error("--recommend needs --option values")
        return qs
    if len(qs) != 1:
        p.error("--option belongs to exactly one --question (use --questions-file for several)")
    q = {"text": qs[0], "kind": "choice", "options": a.option}
    if a.recommend is not None:
        if not 1 <= a.recommend <= len(a.option):
            p.error(f"--recommend is 1–{len(a.option)}")
        q.update(recommended=a.recommend - 1, why=a.why)
    return [q]


def build(argv):
    p = argparse.ArgumentParser(prog="ccd.pipeline_cli", description="Record a ticket pipeline step in Command Center.")
    p.add_argument("op", choices=("work", "plan", "start", "review", "verify", "handoff", "block", "role", "finding",
                                  "ask", "replan", "rework", "evidence", "writer", "deploy-request", "deployed", "stale",
                                  "tasks", "add"))
    p.add_argument("key")
    p.add_argument("--role", choices=ROLES)
    p.add_argument("--model")
    p.add_argument("--session")
    p.add_argument("--plan-file")
    p.add_argument("--branch")
    p.add_argument("--worktree")
    p.add_argument("--verdict", choices=("APPROVE", "REQUEST_CHANGES"))
    p.add_argument("--head")
    p.add_argument("--findings-file")
    p.add_argument("--result", choices=("pass", "fail"))
    p.add_argument("--evidence")
    for f in ("done", "decisions", "next", "blockers", "reason", "summary", "category"):
        p.add_argument(f"--{f}")
    p.add_argument("--question", action="append")
    p.add_argument("--questions-file")
    p.add_argument("--option", action="append", help="an option for the one --question (2–8)")
    p.add_argument("--recommend", type=int, help="which --option you recommend, 1 = the first")
    p.add_argument("--kind")
    p.add_argument("--ref")
    p.add_argument("--note")
    p.add_argument("--stage")
    p.add_argument("--owner", choices=("claude", "codex", "jay", "none"))
    p.add_argument("--checkpoint-file")
    p.add_argument("--env", choices=("live", "preview", "dev"))
    p.add_argument("--what")
    p.add_argument("--verification")
    for f in ("why", "action", "impact", "technical"):
        p.add_argument(f"--{f}")
    p.add_argument("--title")
    p.add_argument("--label", choices=("task-check", "night-finding", "ui-finding"), default="task-check")
    p.add_argument("--scope", choices=("in", "out"), default="in")
    p.add_argument("--source", choices=("review", "owner", "verifier"), default="review")
    a = p.parse_args(argv)
    key = urllib.parse.quote(a.key, safe="")
    if a.op not in ("work", "tasks") and not a.role:
        p.error("--role is required: every write is recorded as agent:<role>")
    meta = {k: v for k, v in (("model", a.model), ("session", a.session)) if v}
    body = {
        "plan": lambda: {"plan": _json_file(a.plan_file) if a.plan_file else None, **meta},
        "start": lambda: {"branch": a.branch, "worktree": a.worktree, **meta},
        "review": lambda: {"verdict": a.verdict, "head": a.head,
                           "findings": _json_file(a.findings_file) if a.findings_file else [], **meta},
        "verify": lambda: {"result": a.result, "evidence": a.evidence, **meta},
        "handoff": lambda: {k: getattr(a, k) for k in ("done", "decisions", "next", "blockers") if getattr(a, k)},
        "block": lambda: {"reason": a.reason, **{k: getattr(a, k) for k in ("what", "why", "action", "impact", "technical")
                                                   if getattr(a, k)}},
        "role": lambda: {"role": a.role, **meta},
        "finding": lambda: {"finding": {"scope": a.scope, "category": a.category, "summary": a.summary},
                            "source": a.source},
        "ask": lambda: {"questions": _json_file(a.questions_file) if a.questions_file else _questions(p, a)},
        "replan": lambda: {"reason": a.reason},
        "rework": lambda: {"reason": a.reason},
        "evidence": lambda: {"kind": a.kind, "ref": a.ref, "note": a.note, **({"stage": a.stage} if a.stage else {})},
        "writer": lambda: {"owner": a.owner, "checkpoint": _json_file(a.checkpoint_file) if a.checkpoint_file else None},
        "deploy-request": lambda: {"env": a.env, "what": a.what, "verification": a.verification},
        "deployed": lambda: {"env": a.env, "result": a.result, "evidence": a.evidence},
        "stale": lambda: {"reason": a.reason},
    }
    if a.op == "work":
        return "GET", f"/api/tasks/{key}/work", None, None
    if a.op == "tasks":
        return "GET", f"/api/tasks?project={key}", None, None
    if a.op == "add":
        if not a.title:
            p.error("--title is required")
        by = {"night-finding": "the night shift", "ui-finding": "a UI test run"}.get(a.label, "the task check")
        desc = f"Added by {by}. Evidence / source: {a.note}" if a.note else f"Added by {by}."
        return "POST", "/api/tasks", {"project": a.key, "title": a.title, "description": desc,
                                      "labels": [a.label]}, f"agent:{a.role}"
    return "POST", f"/api/tasks/{key}/work/{a.op}", body[a.op](), f"agent:{a.role}"


def main(argv=None):
    method, path, body, actor = build(sys.argv[1:] if argv is None else argv)
    code, out = call(method, path, body, actor)
    if code:
        sys.stderr.write(f"refused: {out.get('error') or out}\n")
        return 1
    if method == "GET" and path.startswith("/api/tasks?"):   # tasks: one line per open ticket
        project = urllib.parse.parse_qs(path.split("?", 1)[1]).get("project", [""])[0]
        why = (out.get("paused") or {}).get(project)
        if why:
            print(f"PAUSED: {why}. Do no work on this project: no planning, coding, reviews or merges.")
            return 0
        for t in sorted(out.get("tickets") or [], key=lambda t: t.get("number") or 0):
            if t.get("status") not in ("DONE", "DENIED", "CANCELLED"):
                print(f"{t['key']}\t{t['status']}\t{t['title']}")
        return 0
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
