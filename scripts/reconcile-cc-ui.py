#!/usr/bin/env python3
"""reconcile-cc-ui.py — apply the old Command Center UI tickets' verdicts (spec §30) to the live ticket DB.

    scripts/reconcile-cc-ui.py            dry run: prints each ticket, its status and what would change
    scripts/reconcile-cc-ui.py --apply    does it (run the dry run first)

The verdicts are the ones in plans/COMMAND-CENTER-CONTROL-ROOM.md (appendix, "Old Command Center UI
tickets"). Every ticket gets a note saying where its requirement lives now, so nothing is silently lost:

    superseded   a note, then CANCELLED if it is still open (its requirement is met by the control room)
    carried      a note only; the ticket and its status stay as they are
    satisfied    a note only (it closes through its own pipeline steps)
    reliability  untouched — real reliability work stays separate

It talks to the live ccd on 127.0.0.1:7777 as Jay, with the ccd token and a Developer session (needed to move
a pipeline ticket's status). Run it on jay-server as jay. Tickets that do not exist are skipped.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "server"))
from ccd import config  # noqa: E402

CLOSED = {"DONE", "DENIED", "CANCELLED"}
SPEC = "plans/COMMAND-CENTER-CONTROL-ROOM.md (appendix)"
VERDICTS = [
    ("CC-021", "superseded", "the gate cards and questions in the Workspace task detail and the Task Manager detail"),
    ("CC-018", "superseded", "Task Room / Project Console tool toggles (Claude, Codex, Project, Server)"),
    ("CC-015", "superseded", "the Dashboard project panels, which open the project in the Workspace; Projects is under Settings → Diagnostics"),
    ("CC-026", "satisfied", "Development (Settings → Diagnostics) and the task detail's Plan tab, 'Who works on it'"),
    ("CC-017", "carried", "the Project Console's Claude pane, which uses the same coordinator resolver"),
    ("CC-014", "carried", "the Files screen (Explorer, Source control, Search)"),
    ("CC-013", "carried", "the Files screen editor"),
    ("CC-004", "carried", "the Files screen, Source control"),
    ("CC-003", "carried", "the Files screen (Ctrl+P, Ctrl+Shift+F)"),
    ("CC-011", "carried", "the Project Console Claude pane's ⋯ menu and the Files terminal dock (Windows Terminal)"),
    ("CC-012", "carried", "the Project Console Claude pane (one writable attach; Windows Terminal hand-off)"),
    ("CC-002", "carried", "the Project and Server panes of every Task Room and Project Console"),
    ("CC-008", "carried", "the Task Manager"),
]


def call(method, path, body=None, token=None, dev=None, port=None):
    port = port or config.PORT
    h = {"Host": f"127.0.0.1:{port}", "X-CCD-Token": token, "Content-Type": "application/json"}
    if dev:
        h["X-CCD-Developer"] = dev
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    ap.add_argument("--port", type=int, default=config.PORT)
    a = ap.parse_args(argv)
    token = config.TOKEN_PATH.read_text().strip()
    dev = None
    if a.apply:
        code, out = call("POST", "/api/developer/unlock", {"token": config.DEV_TOKEN_PATH.read_text().strip()},
                         token, port=a.port)
        if code != 200:
            raise SystemExit(f"Developer unlock refused: {out.get('error')}")
        dev = out["session"]
    print("APPLY" if a.apply else "DRY RUN (nothing is changed; add --apply)")
    for key, verdict, where in VERDICTS:
        code, t = call("GET", f"/api/tasks/{key}", token=token, port=a.port)
        if code == 404:
            print(f"  {key:7} —            not in the ticket database; skipped")
            continue
        if code != 200:
            print(f"  {key:7} error {code}: {t.get('error')}")
            continue
        status = t["status"]
        note = (f"Control room redesign ({SPEC}): {verdict}. Its requirement now lives in {where}."
                if verdict != "superseded" else
                f"Superseded by the control room redesign ({SPEC}). Its requirement is met by {where}.")
        cancel = verdict == "superseded" and status not in CLOSED
        plan = "note + CANCELLED" if cancel else "note"
        print(f"  {key:7} {status:18} {verdict:11} → {plan}: {t['title'][:60]}")
        if not a.apply:
            continue
        if any(c["body"] == note for c in t.get("comments") or []):
            print("          (note already there)")
        else:
            c, out = call("POST", f"/api/tasks/{key}/comments", {"body": note}, token, dev, a.port)
            if c != 200:
                print(f"          note failed: {out.get('error')}")
                continue
        if cancel:
            c, out = call("PATCH", f"/api/tasks/{key}", {"status": "CANCELLED"}, token, dev, a.port)
            print(f"          {'CANCELLED' if c == 200 else 'status change failed: ' + str(out.get('error'))}")
    print("  CC-010, CC-027: reliability work — left as they are.")
    if dev:
        call("POST", "/api/developer/lock", {}, token, dev, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
