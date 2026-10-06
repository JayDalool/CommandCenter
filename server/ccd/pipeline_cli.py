"""How a pipeline agent records a stage result in Command Center.

    python -m ccd.pipeline_cli work     SV-056
    python -m ccd.pipeline_cli plan     SV-056 --role planner  --plan-file plan.json
    python -m ccd.pipeline_cli start    SV-056 --role coordinator --branch SV-056-x --worktree /srv/…/SV-056
    python -m ccd.pipeline_cli review   SV-056 --role reviewer --verdict APPROVE --head <sha> [--findings-file f.json]
    python -m ccd.pipeline_cli verify   SV-056 --role verifier --result pass --evidence "…"
    python -m ccd.pipeline_cli handoff  SV-056 --role coordinator --done … --next … [--decisions …] [--blockers …]
    python -m ccd.pipeline_cli block    SV-056 --role coordinator --reason "…"
    python -m ccd.pipeline_cli role     SV-056 --role implementer --model sonnet --session sv-056
    python -m ccd.pipeline_cli finding  SV-056 --role reviewer --scope out --category perf --summary "…"

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
import urllib.request

from . import config

ROLES = ("coordinator", "planner", "implementer", "reviewer", "verifier")


def call(method, path, body=None, actor=None, port=None, token=None):
    port = port or int(os.environ.get("CCD_PORT", "7777"))
    token = token or config.TOKEN_PATH.read_text().strip()
    headers = {"Host": f"127.0.0.1:{port}", "X-CCD-Token": token, "Content-Type": "application/json"}
    if actor:
        headers["X-CCD-Actor"] = actor
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


def _json_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build(argv):
    p = argparse.ArgumentParser(prog="ccd.pipeline_cli", description="Record a ticket pipeline step in Command Center.")
    p.add_argument("op", choices=("work", "plan", "start", "review", "verify", "handoff", "block", "role", "finding"))
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
    p.add_argument("--scope", choices=("in", "out"), default="in")
    p.add_argument("--source", choices=("review", "owner", "verifier"), default="review")
    a = p.parse_args(argv)
    if a.op != "work" and not a.role:
        p.error("--role is required: every write is recorded as agent:<role>")
    meta = {k: v for k, v in (("model", a.model), ("session", a.session)) if v}
    body = {
        "plan": lambda: {"plan": _json_file(a.plan_file) if a.plan_file else None, **meta},
        "start": lambda: {"branch": a.branch, "worktree": a.worktree, **meta},
        "review": lambda: {"verdict": a.verdict, "head": a.head,
                           "findings": _json_file(a.findings_file) if a.findings_file else [], **meta},
        "verify": lambda: {"result": a.result, "evidence": a.evidence, **meta},
        "handoff": lambda: {k: getattr(a, k) for k in ("done", "decisions", "next", "blockers") if getattr(a, k)},
        "block": lambda: {"reason": a.reason},
        "role": lambda: {"role": a.role, **meta},
        "finding": lambda: {"finding": {"scope": a.scope, "category": a.category, "summary": a.summary},
                            "source": a.source},
    }
    if a.op == "work":
        return "GET", f"/api/tasks/{a.key}/work", None, None
    return "POST", f"/api/tasks/{a.key}/work/{a.op}", body[a.op](), f"agent:{a.role}"


def main(argv=None):
    method, path, body, actor = build(sys.argv[1:] if argv is None else argv)
    code, out = call(method, path, body, actor)
    if code:
        sys.stderr.write(f"refused: {out.get('error') or out}\n")
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
