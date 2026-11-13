"""cc-milestone: a project lead's side of HQ milestones (ccd/hq.py).

    cc-milestone list  PROJECT [--json]
    cc-milestone add   PROJECT "title" [--due YYYY-MM-DD] [--note "…"]
    cc-milestone start PROJECT ID
    cc-milestone done  PROJECT ID

A lead adds and changes its own project's TECHNICAL milestones (set up the backend, ship the mobile layout).
Business milestones (contact the lawyer, email the client), removing and reordering are Jay's, in HQ. Talks to the
loopback ccd with this account's ccd token, as `agent:lead-<project>` (or $CCD_ACTOR). Exit 1 with ccd's one-line
reason when something is refused.
"""
import argparse
import json
import os
import re
import sys

from .pipeline_cli import call

PROJECT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MARK = {"todo": "[ ]", "doing": "[~]", "done": "[x]"}


def actor_for(project):
    return os.environ.get("CCD_ACTOR", "").strip() or f"agent:lead-{project}"


def _fail(res):
    print(f"cc-milestone: {res.get('error', res) if isinstance(res, dict) else res}", file=sys.stderr)
    return 1


def list_(project, as_json=False, out=None):
    out = out or sys.stdout
    code, res = call("GET", "/api/milestones", actor=actor_for(project))
    if code:
        return _fail(res)
    mine = (res.get("projects") or {}).get(project)
    if mine is None:
        return _fail({"error": f"no project {project}"})
    if as_json:
        json.dump(mine, out, indent=2)
        out.write("\n")
        return 0
    for track in ("technical", "business"):
        print(f"{track.capitalize()} milestones ({project}):", file=out)
        rows = mine.get(track) or []
        if not rows:
            print("  none yet", file=out)
        for m in rows:
            due = f"  due {m['due']}" if m.get("due") else ""
            print(f"  {MARK.get(m['state'], '[?]')} {m['id']}  {m['title']}{due}", file=out)
        print("", file=out)
    return 0


def add(project, title, due=None, note=None, out=None):
    out = out or sys.stdout
    body = {"track": "technical", "title": title}
    if due:
        body["due"] = due
    if note:
        body["note"] = note
    code, res = call("POST", f"/api/milestones/{project}", body, actor=actor_for(project))
    if code:
        return _fail(res)
    print(f"Added {res['milestone']['id']}: {res['milestone']['title']}", file=out)
    return 0


def set_state(project, mid, state, out=None):
    out = out or sys.stdout
    code, res = call("PATCH", f"/api/milestones/{project}/{mid}", {"state": state}, actor=actor_for(project))
    if code:
        return _fail(res)
    print(f"{mid} is now {state}.", file=out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cc-milestone", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="op", required=True)
    p = sub.add_parser("list")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("add")
    p.add_argument("project")
    p.add_argument("title")
    p.add_argument("--due")
    p.add_argument("--note")
    for op in ("start", "done"):
        p = sub.add_parser(op)
        p.add_argument("project")
        p.add_argument("id")
    a = ap.parse_args(argv)
    if not PROJECT_RE.match(a.project):
        ap.error("PROJECT is a project key (samvision, gyst, mfe, commandcenter, …)")
    try:
        if a.op == "list":
            return list_(a.project, a.json)
        if a.op == "add":
            return add(a.project, a.title, a.due, a.note)
        return set_state(a.project, a.id, "doing" if a.op == "start" else "done")
    except OSError as e:
        print(f"cc-milestone: cannot read this account's ccd token ({e.strerror}); run it as the user ccd runs as",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
