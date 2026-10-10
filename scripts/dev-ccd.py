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
    scripts/dev-ccd.py --port 7789  a second preview beside a running one

From Windows: ssh -N -L 7788:127.0.0.1:7788 jay-server, then http://127.0.0.1:7788
Token: ssh jay-server cat command-center/dev/ccd.token | clip
"""
import argparse
import asyncio
import contextlib
import copy
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = Path(os.environ.get("CCD_DEV_DIR", Path.home() / "command-center" / "dev"))
# Parsed before anything imports ccd, because the port goes into the environment.
_ap = argparse.ArgumentParser(description="a development ccd; never the live one")
_ap.add_argument("--reseed", action="store_true", help="wipe the dev tasks.db first")
_ap.add_argument("--port", type=int, default=7788, help="loopback port (default 7788)")
ARGS = _ap.parse_args()
PORT = ARGS.port

# Point ccd at the dev directories BEFORE any ccd module is imported.
os.environ.update(CCD_STATE_DIR=str(DEV / "state"), CCD_DATA_DIR=str(DEV / "data"), CCD_HANDOFF=str(DEV / "handoff"),
                  CCD_TOKEN_FILE=str(DEV / "ccd.token"), CCD_CONFIG=str(DEV / "no-config.json"), CCD_PORT=str(PORT),
                  CCD_DEV_TOKEN_FILE=str(DEV / "developer.token"), CCD_SHARE_DIR=str(DEV / "share"))
for d in ("state", "data", "handoff"):
    (DEV / d).mkdir(parents=True, exist_ok=True, mode=0o700)
sys.path[:0] = [str(ROOT / "server")]

import uvicorn  # noqa: E402

from ccd import attachments, config, files, gitops, pty, registry, search, security  # noqa: E402
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
    return {"number": n, "title": title, "url": f"https://x/{n}", "isDraft": draft,  # url never trusted: ccd rebuilds it
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
        pr(26, "GZ-901: Contrast and touch target audit", "gz-901-contrast", review="CHANGES_REQUESTED", age=9),
        pr(25, "GZ-902: TASKS.md: mark PR 8, 9 and 10 merged", "gz-902-tasks", review="APPROVED", age=4)],
        "merged": [], "closed": [], "ci": [{"conclusion": "success", "status": "completed", "workflowName": "checks", "url": "", "createdAt": ""}]},
    "gyst": {"issues": [], "prs": [pr(31, "UI-11: Galaxy keyboard navigation", "ui-11-galaxy", draft=True, age=20)],
             "merged": [], "closed": [], "ci": [{"conclusion": "failure", "status": "completed", "workflowName": "checks", "url": "", "createdAt": ""}]},
    "mfe": {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []},
}


def github(project):
    return copy.deepcopy(GH[project["key"]])


# Local branches with commits ahead of the default branch, so the Development
# view has something real-shaped to show in the preview.
BRANCHES = {
    "samvision": {"sv-056-map-clusters": {"commits": 4, "head": "9c41ab2", "at": time.time() - 3600, "countOk": True},
                  "sv-042-rotate": {"commits": 2, "head": "2f10bd8", "at": time.time() - 18000, "countOk": True},
                  "sv-031-prune": {"commits": 7, "head": "71aa0c5", "at": time.time() - 216000, "countOk": True},
                  "follow-up-to-SV-056": {"commits": 11, "head": "badbadb", "at": time.time(), "countOk": True}},
    "gauzemate": {"gz-901-contrast": {"commits": 3, "head": "4dd9e71", "at": time.time() - 32400, "countOk": True},
                  "gz-904-scanner-retry": {"commits": 1, "head": "0ab77c3", "at": time.time() - 900, "countOk": True}},
    "gyst": {"ui-11-galaxy": {"commits": 5, "head": "cc0191f", "at": time.time() - 72000, "countOk": True}},
    "mfe": {},
}


def git():
    return ({k: [] for k in WORKTREES}, copy.deepcopy(WORKTREES), copy.deepcopy(BRANCHES))


def seed(ts):
    if ts.list(include_archived=True):
        return
    def mk(project, title, number=None, actor="jay", **f):
        t, _ = ts.create(project, title, actor, number=number, **{k: v for k, v in f.items() if k in ("status", "prefix")})
        rest = {k: v for k, v in f.items() if k not in ("status", "prefix")}
        if rest:
            ts.update(t["key"], rest, actor)
        return t["key"]
    mk("samvision", "Comparable sales map clusters", 56, status="IN_PROGRESS", priority="HIGH", type="FEATURE",
       assignee="role:IMPLEMENTER", labels=["map", "ui"], branch="sv-056-map-clusters",
       description="Cluster comparable sales on the map at low zoom.\n\n- cluster radius 60 px\n- click expands\n- keep the legend")
    mk("samvision", "Rotate postgres credentials on deploy", 42, status="IN_REVIEW", priority="URGENT", type="SECURITY",
       assignee="role:REVIEWER", needs_deploy=True, branch="sv-042-rotate")
    mk("samvision", "Prune agent worktrees script", 31, status="VERIFYING", priority="MEDIUM", type="INFRA", needs_jay=True,
       description="The prune script exists but has not run: 14 agent worktrees still exist. Jay runs it after reviewing the list.")
    mk("samvision", "Licensed data in git history", 14, status="BLOCKED", priority="URGENT", type="LEGAL", needs_legal=True,
       assignee="jay")
    mk("samvision", "Overview workspace refinement", 10, status="PROPOSED", priority="MEDIUM", type="DESIGN")
    mk("samvision", "Global quick-search research", 11, status="RESEARCHING", priority="LOW", type="RESEARCH", assignee="role:PLANNER")
    mk("samvision", "Net sheet rounding", 50, status="DONE", priority="MEDIUM", type="BUG")
    # GauzeMate's real history is GM-001…GM-014 (retired prefix) and its live prefix is GZ.
    # The preview shows one real history key (GM-004) beside clearly synthetic GZ-9xx keys,
    # so no preview number can be mistaken for a real GauzeMate ticket.
    mk("gauzemate", "Book Manitoba health-tech lawyer", 4, status="INBOX", type="OWNER_ACTION", assignee="jay", needs_jay=True,
       prefix="GM")
    mk("gauzemate", "Contrast and touch target audit", 901, status="IN_REVIEW", priority="MEDIUM", type="DESIGN", needs_ui_review=True)
    mk("gauzemate", "TASKS.md: mark PR 8, 9 and 10 merged", 902, status="READY_TO_IMPLEMENT", priority="LOW", type="DOCS")
    mk("gauzemate", "Barcode / QR scanner for a medication", 903, status="IN_PROGRESS", priority="HIGH", type="FEATURE",
       assignee="agent:gauzemate")
    mk("gauzemate", "Scanner retry on a blurred barcode", status="IN_PROGRESS", priority="MEDIUM", type="BUG",
       assignee="agent:gauzemate", branch="gz-904-scanner-retry")
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
    seed_control_room(ts)


def seed_ui_tests(root):
    """One finished UI test run for the preview (CommandCenter), so the report and Fix it / Skip can be tried."""
    import json as _json
    d = root / "commandcenter" / "2026-10-10-0930"
    if d.exists():
        return
    d.mkdir(parents=True)
    (d / "report.md").write_text("Status: complete\n\nFeatures tested: 3 (CC-031 dashboard, CC-033 merge ready, "
                                 "CC-034 night line)\nTest PR: #44 (ui-tests-2026-10-10)\n\n2 findings, see below.\n")
    (d / "findings.json").write_text(_json.dumps({"summary": {"features": 3, "passed": 9, "failed": 2}, "findings": [
        {"id": "F1", "severity": "major", "title": "Merge ready dialog keeps the old list after a merge",
         "feature": "CC-033 Merge ready", "steps": ["Open Merge ready", "Merge one project", "Look at the list"],
         "expected": "The merged PRs leave the list", "actual": "They stay until the dialog is reopened",
         "evidence": "tests/e2e/merge.spec.ts: 'list refreshes after merge'"},
        {"id": "F2", "severity": "minor", "title": "Night line text is cut at 375 px",
         "feature": "CC-034 Night line", "steps": ["Open the Dashboard at 375 px"], "expected": "Readable",
         "actual": "Ellipsis after 'Night shift run…'", "evidence": "tests/e2e/night.spec.ts"}]}))


def seed_control_room(ts):
    """The control room's own shapes: questions waiting, a blocker explained, a live deploy waiting, review rounds."""
    from ccd import registry
    # The fixtures build several tickets' states at once; waiting for Jay (no start while a ticket has his open
    # question) applies to the running preview, not to setting it up.
    registry.PIPELINE_DEFAULTS["jay_first"] = False
    try:
        _seed_control_room(ts)
    finally:
        registry.PIPELINE_DEFAULTS["jay_first"] = True


def _seed_control_room(ts):
    from ccd.pipeline import Pipeline
    pl = Pipeline(ts, max_lanes=9)
    head = "5" * 40

    def mk(project, number, title, description="", **f):
        t, _ = ts.create(project, title, "jay", number=number, description=description, **f)
        return t["key"]
    k = mk("samvision", 71, "Valuation Layout Improvements", "## Why\nImprove the valuation layout for a better user "
           "experience and clarity.\n\n## Acceptance criteria\n- [ ] Layout works on all screen sizes\n- [ ] No breaking changes\n"
           "- [ ] Passes UI/UX review\n- [ ] Tests pass (frontend + integration)", priority="HIGH", type="FEATURE")
    pl.plan(k, {"summary": "Rework the valuation layout", "requirements": ["Analyze current layout issues",
            "Design improved layout options", "Implement selected approach", "Test across device sizes",
            "Get user feedback and iterate"], "approach": "Two layout options, Jay picks one."}, "agent:planner", model="opus")
    pl.start(k, f"{k}-valuation-layout", f"/srv/server/worktrees/samvisionai/{k}", "agent:coordinator", model="sonnet", session="sv-071")
    pl.ask(k, [{"text": "Which layout option do you prefer?", "options": ["Option A — side-by-side comps", "Option B — stacked cards"]},
               {"text": "Should we keep the current color scheme?", "kind": "yesno"},
               "Any specific user groups to prioritize?"], "agent:coordinator")
    k = mk("samvision", 74, "Comparable photos carousel", type="FEATURE")
    pl.plan(k, {"summary": "Carousel for comp photos"}, "agent:planner", model="opus")
    pl.start(k, f"{k}-carousel", f"/srv/server/worktrees/samvisionai/{k}", "agent:coordinator", model="sonnet")
    ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #118 is open")
    pl.review(k, "REQUEST_CHANGES", head, "agent:reviewer", findings=[{"summary": "Swipe does not work on iOS Safari"}], model="opus")
    pl.rework(k, "swipe on iOS Safari", "agent:coordinator")
    ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #118 updated")
    k = mk("samvision", 79, "Mortgage calculator rounding", type="BUG")
    pl.plan(k, {"summary": "Round at the end, not per step"}, "agent:planner", model="opus")
    pl.start(k, f"{k}-rounding", f"/srv/server/worktrees/samvisionai/{k}", "agent:coordinator", model="sonnet")
    pl.block(k, "mobile UI test failed", "agent:verifier", {
        "what": "The feature passed code review, but the final mobile UI test found that the action buttons overlap on narrow screens.",
        "why": "Merging now would solve desktop but create a visible mobile regression.",
        "action": "Fix the mobile layout and rerun UI verification.", "impact": "Small. The current implementation can remain.",
        "technical": "playwright tests/ui/calculator.spec.ts:42 — expected #actions not to overlap #summary at 375px"})
    k = mk("commandcenter", 31, "Control room dashboard", type="FEATURE")
    pl.plan(k, {"summary": "Manager panels per project"}, "agent:planner", model="opus")
    pl.start(k, f"{k}-dashboard", f"/srv/server/worktrees/cc/{k}", "agent:coordinator", model="sonnet")
    ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #21 is open")
    pl.review(k, "APPROVE", head, "agent:reviewer", session="review-1", model="opus",
              pr={"ref": "JayDalool/CommandCenter#21", "head": head, "ciGreen": True, "draft": False})
    ts.update(k, {"status": "VERIFYING"}, "system:automation", trigger="PR #21 merged")
    pl.merged(k, "JayDalool/CommandCenter#21", "6" * 40)
    pl.deploy_request(k, "live", "The new Dashboard and Workspace for Command Center", "Fresh review approved 5555555; "
                      "UI tests 14/14; verifier pass on the preview", "agent:coordinator")
    k = mk("gyst", 24, "Galaxy UI assets", type="DESIGN", labels=["ui"])
    pl.plan(k, {"summary": "Icon concepts for the galaxy view"}, "agent:planner", model="opus")
    pl.start(k, f"{k}-assets", f"/srv/server/worktrees/gyst/{k}", "agent:coordinator", model="sonnet")
    ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #33 is open")
    pl.review(k, "APPROVE", head, "agent:reviewer", session="review-1", pr={"ref": "JayDalool/gyst-lifeops#33", "head": head, "ciGreen": True, "draft": False})
    k = mk("mfe", 18, "Receipt totals by category", type="FEATURE")
    pl.plan(k, {"summary": "Totals per category"}, "agent:planner", model="opus")
    k = mk("samvision", 52, "Old valuation PDF export")             # the task check: proposed as stale
    pl.stale(k, "superseded by SV-071's new valuation layout (plans/valuation-layout.md)", "agent:coordinator")


async def main(reseed):
    if reseed and (DEV / "data" / "tasks.db").exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(DEV / "data" / "tasks.db") + suffix).unlink(missing_ok=True)
    fake = FakeHerdr()
    fake.add_agent("wE:pA", "/srv/server/worktrees/samvisionai/SV-056", name="sv-056-impl", status="working")
    fake.add_agent("wE:p9", "/srv/server/apps/samvisionai", name="sv-071", status="idle")   # SV-071's task session
    fake.set_status("wE:p4", "blocked")
    fake.tails["wE:p4"] = ("Reading docs/LAWYER_QUESTIONS.md\n● The profile export would include the patient's initials.\n"
                           "Should I keep initials out of the export file? (y/n)")
    fake.tails["wE:p2"] = "✓ tests passed (212)\n● Waiting for SV-056 review\n> "
    # the extra lane pane needs a place in the layout
    lay = next(l for l in fake.snapshot["layouts"] if l["tab_id"] == "wE:t1")
    lay["panes"].append({"focused": False, "pane_id": "wE:pA", "rect": {"height": 20, "width": 17, "x": 70, "y": 20}})
    lay["panes"].append({"focused": False, "pane_id": "wE:p9", "rect": {"height": 10, "width": 17, "x": 70, "y": 40}})
    lay["panes"] = [p for p in lay["panes"] if p["pane_id"] != "wE:pC"]
    lay["zoomed"] = False
    await fake.start()

    cfg = config.load()
    cfg["projects"] = copy.deepcopy(PROJECTS)
    for p in cfg["projects"]:
        p.update(session=p["key"], ui_tests="docs/jay/UI_TESTS.md", actions="docs/jay/MY_ACTIONS.md", links=[], commands=[])
    cfg.update(github_seconds=60, host_seconds=30, git_seconds=600, worktree_cleanup=False)  # the dev ccd never removes directories
    store = Store(config.STATE_DIR / "ccd.db")
    tasks = TaskStore(config.DATA_DIR / "tasks.db", config.task_projects(cfg))
    seed(tasks)
    daemon = Daemon(cfg, store, Herdr(fake.path), github_fn=github, host_fn=host_snapshot, git_fn=git,
                    oom_fn=lambda: 0, tasks=tasks)
    token = security.load_or_create_token(config.TOKEN_PATH)
    # The preview's Workspace edits a SANDBOX copy per project, never the real checkouts.
    sandbox = {}
    for key in registry.PROJECTS:
        root = DEV / "sandbox" / key
        if not root.exists():
            (root / "src").mkdir(parents=True)
            (root / "docs").mkdir()
            (root / "README.md").write_text(f"# {registry.name_of(key)} (preview sandbox)\n\nEdit me.\n")
            (root / "src" / "main.py").write_text("def hello(name):\n    return f'hello {name}'\n")
            (root / ".env").write_text("NOT_A_REAL_SECRET=1\n")
            (root / ".env.example").write_text("NOT_A_REAL_SECRET=\n")
        sandbox[key] = str(root)
    daemon.files = files.Roots(sandbox)
    daemon.attachments = attachments.Attachments(config.DATA_DIR / "attachments.db", config.ATTACH_DIR,
                                                 50 * 1024 * 1024)
    daemon.dev_gate = security.DeveloperGate(security.load_or_create_token(config.DEV_TOKEN_PATH))
    daemon.dev_token_hint = str(config.DEV_TOKEN_PATH).replace(str(Path.home()), "~", 1)
    daemon.launcher_dir = Path.home() / ".local" / "share" / "command-center" / "launcher"
    for key, root in sandbox.items():  # a git repo per sandbox, so Source Control has something to show
        if not (Path(root) / ".git").exists():
            subprocess.run(["git", "-C", root, "init", "-q", "-b", "main"], check=False)
            subprocess.run(["git", "-C", root, "add", "-A"], check=False)
            subprocess.run(["git", "-C", root, "-c", "user.name=preview", "-c", "user.email=preview@localhost",
                            "commit", "-q", "-m", "preview sandbox"], check=False)
    daemon.search = search.Search(daemon.files)
    daemon.scm = gitops.SourceControl(daemon.files)
    # Repo shells open in the SANDBOX copies; the server shell is a real shell in $HOME.
    daemon.ptys = pty.PtyManager(audit=lambda kind, text, data: daemon._event("pty", kind, text, data=data),
                                 roots={registry.prefix_of(k): r for k, r in sandbox.items()},
                                 own_scope=not os.environ.get("CCD_DEV_NO_SCOPE"),
                                 task=lambda key: (sandbox[tasks.get(key)["project"]], None))
    daemon.records_dir = DEV / "task-records"
    from ccd import nightshift, uitests
    daemon.night = nightshift.NightShift(DEV / "night-shift")
    daemon.uitests = uitests.UiTests(DEV / "ui-tests")
    seed_ui_tests(DEV / "ui-tests")

    @contextlib.asynccontextmanager
    async def lifespan(app):
        daemon.start()
        yield
        await daemon.ptys.close_all()
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
    asyncio.run(main(ARGS.reseed))
