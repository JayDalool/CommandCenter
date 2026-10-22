"""Fixture decisions: one or more cases for every class in the Phase 1 sweep table (findings doc, 2026-10-22), run
against the real profiles in policy/. Each case says what the agreed policy expects (auto, jay or refuse) and which
regression it guards, if any. The starting points that really are "auto" are included, so "never auto" checks
cannot pass vacuously.

Pure data plus `run()`; no I/O beyond reading policy/."""
from .. import autonomy, profiles

HEAD = "ab" * 20
OLD = "cd" * 20


def ready(**over):
    """A CommandCenter merge the target policy allows (tests-only change, CI passed, approved at the PR head, PR
    mergeable into main from this repository)."""
    x = {"project": "commandcenter", "type": "MAINTENANCE", "labels": [], "flags": [], "plan_accepted": True,
         "review_at_head": True, "review_head": HEAD, "pr_head": HEAD, "merged": False, "verified": None,
         "ci": "green", "ci_passed": True, "draft": False, "mergeable": "MERGEABLE", "base": "main",
         "cross_repo": False, "state": "OPEN", "files": [{"path": "server/tests/test_x.py", "changeType": "ADDED", "additions": 5, "deletions": 2}],
         "additions": 5, "deletions": 2}
    x.update(over)
    return x


def _f(*paths, change="MODIFIED"):
    return [{"path": p, "changeType": change, "additions": 1, "deletions": 0} for p in paths]


def _live_ok(**over):
    x = dict(env="live", merged=True, verified=True, no_migration=True, no_downtime=True,
             no_client_workflow_change=True)
    x.update(over)
    return ready(**x)


# (id, area, class, action, project, facts, expected outcome, regression)
CASES = [
    # starting points that are auto
    ("B-01", "Baseline", "Allowlisted CommandCenter merge", "merge", "commandcenter", ready(), "auto", None),
    ("B-02", "Baseline", "Preview deploy", "deploy", "commandcenter", ready(env="preview"), "auto", None),
    ("B-03", "Baseline", "Low-risk CommandCenter plan", "plan", "commandcenter", ready(), "auto", None),
    # hard boundaries
    ("HB-01", "Hard boundaries", "Policy or profile change (policy/**)", "merge", "commandcenter",
     ready(files=_f("policy/projects/commandcenter.toml")), "jay", "L-01"),
    ("HB-02", "Hard boundaries", "Security code, engine, broker", "merge", "commandcenter",
     ready(files=_f("server/ccd/security.py", "server/ccd/autonomy.py")), "jay", "L-01"),
    ("HB-03", "Hard boundaries", "identity.py, audit.py, workers.py, scripts/**", "merge", "commandcenter",
     ready(files=_f("server/ccd/identity.py", "scripts/go-live.sh")), "jay", "L-01"),
    ("HB-04", "Hard boundaries", "Credentials or secrets", "merge", "commandcenter",
     ready(labels=["secrets"]), "jay", "U-07"),
    ("HB-05", "Hard boundaries", "Destructive production data, irreversible, paid", "plan", "commandcenter",
     ready(labels=["destructive"]), "jay", "U-07"),
    ("HB-06", "Hard boundaries", "Destructive production data, irreversible, paid", "merge", "commandcenter",
     ready(labels=["Paid"]), "jay", "U-07"),
    ("HB-07", "Hard boundaries", "Legal or compliance", "merge", "commandcenter",
     ready(labels=["LEGAL"]), "jay", "L-03"),
    ("HB-08", "Hard boundaries", "Legal or compliance", "plan", "commandcenter",
     ready(flags=["Needs_Legal"]), "jay", "L-03"),
    ("HB-09", "Hard boundaries", "Agent permissions", "merge", "commandcenter",
     ready(files=_f(".claude/settings.json")), "jay", "L-01"),
    ("HB-10", "Hard boundaries", "Major client-facing redesign", "plan", "samvision",
     ready(project="samvision", labels=["ui"]), "jay", None),
    ("HB-11", "Hard boundaries", "Major client-facing redesign", "plan", "commandcenter",
     ready(files=_f("web/app/src/App.tsx"), labels=["architecture"]), "jay", "Q-01"),
    ("HB-12", "Hard boundaries", "Unreadable labels", "merge", "commandcenter",
     ready(labels="secrets"), "jay", "U-07"),
    # merge
    ("M-01", "Merge", "Red, pending, unknown CI or no checks", "merge", "commandcenter", ready(ci="red"), "jay", None),
    ("M-02", "Merge", "Red, pending, unknown CI or no checks", "merge", "commandcenter", ready(ci="none"), "jay", None),
    ("M-03", "Merge", "Red, pending, unknown CI or no checks", "merge", "commandcenter", ready(ci=None), "jay", None),
    ("M-04", "Merge", "All checks skipped", "merge", "commandcenter", ready(ci_passed=False), "jay", "U-08"),
    ("M-05", "Merge", "Missing review", "merge", "commandcenter", ready(review_at_head=False), "jay", None),
    ("M-06", "Merge", "Stale review head", "merge", "commandcenter", ready(review_head=OLD), "jay", "U-05"),
    ("M-07", "Merge", "Stale review head", "merge", "commandcenter", ready(pr_head=None), "jay", "U-05"),
    ("M-08", "Merge", "Draft, conflicting, wrong base, fork", "merge", "commandcenter", ready(draft=True), "jay", "U-01"),
    ("M-09", "Merge", "Draft, conflicting, wrong base, fork", "merge", "commandcenter",
     ready(mergeable="CONFLICTING"), "jay", "U-02"),
    ("M-10", "Merge", "Draft, conflicting, wrong base, fork", "merge", "commandcenter", ready(base="release"), "jay", "U-03"),
    ("M-11", "Merge", "Draft, conflicting, wrong base, fork", "merge", "commandcenter", ready(cross_repo=True), "jay", "U-04"),
    ("M-12", "Merge", "Draft, conflicting, wrong base, fork", "merge", "commandcenter", ready(mergeable=None), "jay", "U-02"),
    ("M-24", "Merge", "Draft, conflicting, wrong base, fork", "merge", "commandcenter", ready(state="CLOSED"), "jay", None),
    ("M-25", "Merge", "Missing labels, flags or type", "merge", "commandcenter", ready(labels=None), "jay", None),
    ("M-26", "Merge", "Missing labels, flags or type", "merge", "commandcenter",
     {k: v for k, v in ready().items() if k != "type"}, "jay", None),
    ("M-13", "Merge", "Unknown or odd changed files", "merge", "commandcenter", ready(files=None), "jay", None),
    ("M-14", "Merge", "Unknown or odd changed files", "merge", "commandcenter", ready(files=[]), "jay", None),
    ("M-15", "Merge", "Unknown or odd changed files", "merge", "commandcenter",
     ready(files=_f(*[f"server/tests/t{i}.py" for i in range(100)])), "jay", None),
    ("M-16", "Merge", "Unknown or odd changed files", "merge", "commandcenter",
     ready(files=_f("server/tests/test_x.py", change="RENAMED")), "jay", None),
    ("M-17", "Merge", "Unknown or odd changed files", "merge", "commandcenter",
     ready(files=_f("../server/ccd/security.py")), "jay", None),
    ("M-18", "Merge", "Unknown risk; risk:low label on a non-allowlisted file", "merge", "commandcenter",
     ready(files=_f("README.txt"), labels=["risk:low"]), "jay", None),
    ("M-19", "Merge", "Paused project", "merge", "gauzemate", ready(project="gauzemate"), "refuse", None),
    ("M-20", "Merge", "Controlled production", "merge", "samvision", ready(project="samvision"), "jay", None),
    ("M-21", "Merge", "Controlled production", "merge", "mfe", ready(project="mfe"), "jay", None),
    ("M-22", "Merge", "GYST, any file", "merge", "gyst", ready(project="gyst"), "jay", "L-02"),
    ("M-23", "Merge", "Missing required plan facts", "merge", "samvision",
     ready(project="samvision", plan_accepted=False), "jay", None),
    # deploy
    ("D-01", "Deploy", "Live, CommandCenter/GYST", "deploy", "commandcenter", _live_ok(), "jay", "L-05"),
    ("D-02", "Deploy", "Live, CommandCenter/GYST", "deploy", "gyst", _live_ok(project="gyst"), "jay", "L-05"),
    ("D-03", "Deploy", "Live, SamVision/MFE", "deploy", "samvision", _live_ok(project="samvision"), "jay", None),
    ("D-04", "Deploy", "Live, SamVision/MFE", "deploy", "mfe", _live_ok(project="mfe"), "jay", None),
    ("D-05", "Deploy", "env None", "deploy", "commandcenter", ready(env=None), "jay", None),
    ("D-06", "Deploy", "env prod, production, Live, empty", "deploy", "commandcenter", ready(env="prod"), "jay", "U-06"),
    ("D-07", "Deploy", "env prod, production, Live, empty", "deploy", "commandcenter", ready(env="production"), "jay", "U-06"),
    ("D-08", "Deploy", "env prod, production, Live, empty", "deploy", "commandcenter", ready(env=""), "jay", "U-06"),
    ("D-09", "Deploy", "env prod, production, Live, empty", "deploy", "commandcenter", ready(env="Live"), "jay", "U-06"),
    ("D-10", "Deploy", "env preview/dev", "deploy", "commandcenter", ready(env="dev"), "auto", "U-06"),
    ("D-11", "Deploy", "Migration, downtime, client workflow, missing rollback", "deploy", "samvision",
     _live_ok(project="samvision", no_migration=False), "jay", "L-05"),
    ("D-12", "Deploy", "Paused project", "deploy", "gauzemate", ready(project="gauzemate", env="preview"), "refuse", None),
    # plan
    ("P-01", "Plan", "GYST, SamVision, MFE with missing facts", "plan", "gyst", ready(project="gyst", files=None), "jay", None),
    ("P-02", "Plan", "GYST, SamVision, MFE with missing facts", "plan", "samvision",
     ready(project="samvision", files=None), "jay", None),
    ("P-03", "Plan", "GYST, SamVision, MFE with missing facts", "plan", "mfe", ready(project="mfe", files=None), "jay", None),
    ("P-04", "Plan", "CommandCenter high-risk", "plan", "commandcenter", ready(labels=["security"]), "jay", "Q-01"),
    ("P-05", "Plan", "CommandCenter high-risk", "plan", "commandcenter", ready(files=None), "jay", "Q-01"),
    # project state
    ("S-01", "Project state", "Invalid or missing profile, unknown project", "merge", "nope", ready(project="nope"), "jay", None),
    ("S-02", "Project state", "Restricted / laptop-only mode", "merge", "example-restricted",
     ready(project="example-restricted"), "jay", "L-04"),
    ("S-03", "Project state", "Unknown action, non-dict facts", "release", "commandcenter", ready(), "jay", None),
    ("S-04", "Project state", "Unknown action, non-dict facts", "merge", "commandcenter", "not a dict", "jay", None),
]

# The sweep classes every replay or fixture run must cover (gate row 12). Identity, workers and approvals are
# records that cannot produce a verdict; their own suites cover them.
CLASSES = sorted({c[2] for c in CASES})


def profile_for(policy, project):
    if project in policy.profiles:
        return policy.profile(project)
    rec = policy.examples.get(project)
    return rec["profile"] if rec and rec.get("valid") else None


def run(policy=None):
    """[{id, area, class, action, project, expected, regression, verdict, facts}] for every case."""
    policy = policy or profiles.load()
    out = []
    for cid, area, cls, action, project, facts, expected, reg in CASES:
        out.append({"id": cid, "source": "fixture", "area": area, "class": cls, "action": action,
                    "project": project, "expected": expected, "regression": reg, "facts": facts,
                    "profile": profile_for(policy, project),
                    "verdict": autonomy.evaluate(action, profile_for(policy, project), facts)})
    return out
