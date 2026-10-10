"""Shared test scaffolding: config, fake sources, waiting."""
import asyncio
import copy
import os
import tempfile
import time

PROJECTS = [
    {"key": "samvision", "name": "SamVision", "repo": "JayDalool/SamVisionAI", "path": "/srv/server/apps/samvisionai",
     "branch": "main", "model": "opus", "effort": "", "index": ""},
    {"key": "gyst", "name": "GYST", "repo": "JayDalool/gyst-lifeops", "path": "/srv/server/repos/gyst-lifeops",
     "branch": "master", "model": "opus", "effort": "", "index": ""},
    {"key": "mfe", "name": "MFE", "repo": "JayDalool/MyFamilyExpenses", "path": "/srv/server/repos/MyFamilyExpenses",
     "branch": "main", "model": "sonnet", "effort": "", "index": ""},
    {"key": "gauzemate", "name": "GauzeMate", "repo": "JayDalool/GauzeMate", "path": "/srv/server/repos/GauzeMate",
     "branch": "main", "model": "opus", "effort": "max", "index": ""},
]
WORKTREES = {
    "samvision": ["/srv/server/apps/samvisionai", "/srv/server/worktrees/samvisionai/SV-056"],
    "gyst": ["/srv/server/repos/gyst-lifeops"],
    "mfe": ["/srv/server/repos/MyFamilyExpenses"],
    "gauzemate": ["/srv/server/repos/GauzeMate"],
}


def cfg(**over):
    from ccd import config
    c = copy.deepcopy(config.DEFAULTS)
    c["projects"] = copy.deepcopy(PROJECTS)
    for p in c["projects"]:
        p.update(session=p["key"], ui_tests="docs/jay/UI_TESTS.md", actions="docs/jay/MY_ACTIONS.md",
                 links=[], commands=[])
    c.update(reconcile_seconds=0.4, github_seconds=3600, host_seconds=3600, git_seconds=3600,
             plans_dir=tempfile.mkdtemp(prefix="plans-"), worktree_cleanup=False)
    c.update(over)
    return c


def pr(number, title="a pr", ci="SUCCESS", review=None):
    return {"number": number, "title": title, "url": f"https://x/{number}", "isDraft": False, "reviewDecision": review,
            "headRefName": f"b{number}", "headRefOid": f"{number:07d}abc", "updatedAt": "2026-10-02T00:00:00Z",
            "labels": [], "statusCheckRollup": [{"state": ci}] if ci else []}


class FakeGitHub:
    def __init__(self):
        self.data = {p["key"]: {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []} for p in PROJECTS}
        self.data["gauzemate"]["prs"] = [pr(23), pr(25), pr(26)]
        self.fail = False
        self.calls = 0

    def __call__(self, project):
        self.calls += 1
        if self.fail:
            e = {"error": "gh: could not resolve host api.github.com"}
            return {k: e for k in ("issues", "prs", "merged", "closed", "ci")}
        return copy.deepcopy(self.data[project["key"]])


def fake_host(cfg_, prev_cpu=None):
    return ({"disk": 48, "containers_up": 17, "containers_total": 19, "down": [], "running": ["minecraft", "n8n"],
             "memTotal": 16 * 2**30, "memAvailable": 8 * 2**30, "memUsed": 8 * 2**30, "swapTotal": 12 * 2**30,
             "swapUsed": 3 * 2**30, "swapPct": 25.0, "load": [0.2, 0.2, 0.3], "cpuPct": 2.0, "cpus": 6,
             "uptimeS": 1000.0}, (0, 0))


def fake_git():
    return ({k: [] for k in WORKTREES}, copy.deepcopy(WORKTREES))


async def wait_for(cond, timeout=5.0, what="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        await asyncio.sleep(0.03)
    raise AssertionError(f"timed out waiting for {what}")


def wait_sync(cond, timeout=5.0, what="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.03)
    raise AssertionError(f"timed out waiting for {what}")


def new_db():
    return os.path.join(tempfile.mkdtemp(prefix="ccd-db-"), "ccd.db")
