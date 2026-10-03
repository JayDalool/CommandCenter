#!/usr/bin/env python3
"""A development ccd on 127.0.0.1:7788 — never the live one.

    fake herdr   tests/fake_herdr.py, the real 0.9.3 wire protocol, fixture panes
    GitHub       canned PRs/issues (no gh calls)
    host         the real /proc and docker ps (read-only)
    tickets      a seeded tasks.db in the dev data dir
    UI           web/app/dist, same origin

State, data and token live in ~/command-center/dev/ (override CCD_DEV_DIR), so
nothing touches ~/command-center/state, the live ccd.db, tasks.db or ccd.token.

    scripts/dev-ccd.py              run (Ctrl+C to stop)
    scripts/dev-ccd.py --reseed     wipe the dev tasks.db first

From Windows: ssh -N -L 7788:127.0.0.1:7788 jay-server, then http://127.0.0.1:7788
Token: ssh jay-server cat command-center/dev/ccd.token | clip
"""
import argparse
import asyncio
import contextlib
import copy
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = Path(os.environ.get("CCD_DEV_DIR", Path.home() / "command-center" / "dev"))
PORT = 7788

# Point ccd at the dev directories BEFORE any ccd module is imported.
os.environ.update(CCD_STATE_DIR=str(DEV / "state"), CCD_DATA_DIR=str(DEV / "data"), CCD_HANDOFF=str(DEV / "handoff"),
                  CCD_TOKEN_FILE=str(DEV / "ccd.token"), CCD_CONFIG=str(DEV / "no-config.json"), CCD_PORT=str(PORT))
for d in ("state", "data", "handoff"):
    (DEV / d).mkdir(parents=True, exist_ok=True, mode=0o700)
sys.path[:0] = [str(ROOT / "server")]

import uvicorn  # noqa: E402

from ccd import config, security  # noqa: E402
from ccd.api import create_app  # noqa: E402
from ccd.daemon import Daemon, host_snapshot  # noqa: E402
from ccd.herdr import Herdr  # noqa: E402
from ccd.store import Store  # noqa: E402
from ccd.tasks import TaskStore  # noqa: E402
from tests.fake_herdr import FakeHerdr  # noqa: E402
from tests.helpers import PROJECTS, WORKTREES  # noqa: E402

assert config.HOST == "127.0.0.1"


def iso(hours_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours_ago * 3600))


def pr(n, title, branch, ci="SUCCESS", review=None, draft=False, mergeable="MERGEABLE", age=2):
    return {"number": n, "title": title, "url": f"https://github.com/JayDalool/x/pull/{n}", "isDraft": draft,
            "reviewDecision": review, "mergeable": mergeable, "headRefName": branch, "headRefOid": f"{n:04d}a3f9c21e",
            "updatedAt": iso(age), "labels": [], "statusCheckRollup": [{"state": ci}] if ci else []}


GH = {
    "samvision": {"issues": [], "prs": [
        pr(94, "SV-056: Comparable sales map clusters", "sv-056-map-clusters", ci="PENDING", age=1),
        pr(92, "SV-042: Rotate postgres credentials on deploy", "sv-042-rotate", review="APPROVED", age=5),
        pr(88, "SV-031: Prune agent worktrees script", "sv-031-prune", ci="FAILURE", age=60)],
        "merged": [{"number": 90, "title": "SV-050: Net sheet rounding", "url": "https://github.com/x/pull/90", "mergedAt": iso(3)}],
        "closed": [], "ci": [{"conclusion": "success", "status": "completed", "workflowName": "checks", "url": "", "createdAt": ""}]},
    "gauzemate": {"issues": [], "prs": [
        pr(26, "GM-020: Contrast and touch target audit", "gm-020-contrast", review="CHANGES_REQUESTED", age=9),
        pr(25, "GM-018: TASKS.md: mark PR 8, 9 and 10 merged", "gm-018-tasks", review="APPROVED", age=4)],
        "merged": [], "closed": [], "ci": [{"conclusion": "success", "status": "completed", "workflowName": "checks", "url": "", "createdAt": ""}]},
    "gyst": {"issues": [], "prs": [pr(31, "UI-11: Galaxy keyboard navigation", "ui-11-galaxy", draft=True, age=20)],
             "merged": [], "closed": [], "ci": [{"conclusion": "failure", "status": "completed", "workflowName": "checks", "url": "", "createdAt": ""}]},
    "mfe": {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []},
}


def github(project):
    return copy.deepcopy(GH[project["key"]])


def git():
    return ({k: [] for k in WORKTREES}, copy.deepcopy(WORKTREES))


def seed(ts):
    if ts.list(include_archived=True):
        return
    def mk(project, title, number=None, actor="jay", **f):
        t, _ = ts.create(project, title, actor, number=number, **{k: v for k, v in f.items() if k in ("status",)})
        rest = {k: v for k, v in f.items() if k != "status"}
        if rest:
            ts.update(t["key"], rest, actor)
        return t["key"]
    mk("samvision", "Comparable sales map clusters", 56, status="IN_PROGRESS", priority="HIGH", type="FEATURE",
       assignee="role:IMPLEMENTER", labels=["map", "ui"], branch="sv-056-map-clusters",
       description="Cluster comparable sales on the map at low zoom.\n\n- cluster radius 60 px\n- click expands\n- keep the legend")
    mk("samvision", "Rotate postgres credentials on deploy", 42, status="IN_REVIEW", priority="URGENT", type="SECURITY",
       assignee="role:REVIEWER", needs_deploy=True)
    mk("samvision", "Prune agent worktrees script", 31, status="VERIFYING", priority="MEDIUM", type="INFRA", needs_jay=True,
       description="The prune script exists but has not run: 14 agent worktrees still exist. Jay runs it after reviewing the list.")
    mk("samvision", "Licensed data in git history", 14, status="BLOCKED", priority="URGENT", type="LEGAL", needs_legal=True,
       assignee="jay")
    mk("samvision", "Overview workspace refinement", 10, status="PROPOSED", priority="MEDIUM", type="DESIGN")
    mk("samvision", "Global quick-search research", 11, status="RESEARCHING", priority="LOW", type="RESEARCH", assignee="role:PLANNER")
    mk("samvision", "Net sheet rounding", 50, status="DONE", priority="MEDIUM", type="BUG")
    mk("gauzemate", "Contrast and touch target audit", 20, status="IN_REVIEW", priority="MEDIUM", type="DESIGN", needs_ui_review=True)
    mk("gauzemate", "TASKS.md: mark PR 8, 9 and 10 merged", 18, status="READY_TO_IMPLEMENT", priority="LOW", type="DOCS")
    mk("gauzemate", "Book Manitoba health-tech lawyer", 4, status="INBOX", type="OWNER_ACTION", assignee="jay", needs_jay=True)
    mk("gauzemate", "Barcode / QR scanner for a medication", 26, status="IN_PROGRESS", priority="HIGH", type="FEATURE",
       assignee="agent:gauzemate")
    mk("gyst", "Galaxy keyboard navigation", 11, status="IN_PROGRESS", priority="MEDIUM", type="FEATURE", assignee="role:IMPLEMENTER")
    mk("gyst", "Production foreign-key audit", None, status="PROPOSED", priority="HIGH", type="MAINTENANCE")
    mk("mfe", "Run prisma migrate deploy, then check a receipt total", None, status="INBOX", type="OWNER_ACTION", needs_jay=True,
       assignee="jay")
    cc1 = mk("commandcenter", "Tasks UI: list, detail, create, filters", status="IN_PROGRESS", priority="HIGH", type="FEATURE",
             assignee="role:IMPLEMENTER", labels=["p4b", "ui"])
    cc2 = mk("commandcenter", "Pipeline view and Needs Jay queue", status="READY_TO_IMPLEMENT", priority="HIGH", type="FEATURE",
             labels=["p4b"], parent=cc1)
    cc3 = mk("commandcenter", "Approve the task migration preview", status="INBOX", type="OWNER_ACTION", assignee="jay",
             needs_jay=True)
    mk("commandcenter", "Tauri desktop shell", status="PROPOSED", priority="LOW", type="RESEARCH", labels=["later"])
    ts.relate(cc2, "blocked_by", cc1)
    ts.relate("SV-031", "related", "SV-056")
    ts.relate(cc3, "blocked_by", cc2)
    ts.link("SV-056", "github", "pr", "JayDalool/SamVisionAI#94", "https://github.com/JayDalool/SamVisionAI/pull/94")
    ts.comment("SV-056", "Keep the cluster colours from the legend; no new palette.", "jay")
    ts.comment("SV-056", "Plan accepted. Implementing in worktree sv-056.", "agent:samvision")
    ts.update("SV-056", {"status": "IN_PROGRESS"}, "system:automation", trigger="dispatch 'implement' accepted by idle coordinator samvision")


async def main(reseed):
    if reseed and (DEV / "data" / "tasks.db").exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(DEV / "data" / "tasks.db") + suffix).unlink(missing_ok=True)
    fake = FakeHerdr()
    fake.add_agent("wE:pA", "/srv/server/worktrees/samvisionai/SV-056", name="sv-056-impl", status="working")
    fake.set_status("wE:p4", "blocked")
    fake.tails["wE:p4"] = ("Reading docs/LAWYER_QUESTIONS.md\n● The profile export would include the patient's initials.\n"
                           "Should I keep initials out of the export file? (y/n)")
    fake.tails["wE:p2"] = "✓ tests passed (212)\n● Waiting for SV-056 review\n> "
    # the extra lane pane needs a place in the layout
    lay = next(l for l in fake.snapshot["layouts"] if l["tab_id"] == "wE:t1")
    lay["panes"].append({"focused": False, "pane_id": "wE:pA", "rect": {"height": 20, "width": 17, "x": 70, "y": 20}})
    lay["panes"] = [p for p in lay["panes"] if p["pane_id"] != "wE:pC"]
    lay["zoomed"] = False
    await fake.start()

    cfg = config.load()
    cfg["projects"] = copy.deepcopy(PROJECTS)
    for p in cfg["projects"]:
        p.update(session=p["key"], ui_tests="docs/jay/UI_TESTS.md", actions="docs/jay/MY_ACTIONS.md", links=[], commands=[])
    cfg.update(github_seconds=60, host_seconds=30, git_seconds=600)
    store = Store(config.STATE_DIR / "ccd.db")
    tasks = TaskStore(config.DATA_DIR / "tasks.db", config.task_projects(cfg))
    seed(tasks)
    daemon = Daemon(cfg, store, Herdr(fake.path), github_fn=github, host_fn=host_snapshot, git_fn=git,
                    oom_fn=lambda: 0, tasks=tasks)
    token = security.load_or_create_token(config.TOKEN_PATH)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        daemon.start()
        yield
        await daemon.stop()

    app, _ = create_app(daemon, token, PORT, lifespan=lifespan)
    print(f"dev ccd on http://127.0.0.1:{PORT}  (token file: {config.TOKEN_PATH})", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_config=None, access_log=False,
                                           server_header=False, ws="websockets", lifespan="on"))
    try:
        await server.serve()
    finally:
        store.close()
        tasks.close()
        await fake.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reseed", action="store_true")
    asyncio.run(main(ap.parse_args().reseed))
