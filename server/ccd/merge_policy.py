"""Which reviewed PRs ccd may merge by itself (CC-025, docs/adr/0007-auto-merge-policy.md).

A pure classifier: it reads facts it is handed (the ticket, its recorded review, a fresh `gh pr view`) and
answers yes, no (with every reason) or "wait" (a state that is expected to change in minutes). It runs no
command, reads no file and holds no state, so every rule here can be tested with plain dicts.

Low-risk means ALL of:

  1. every file is ADDED or MODIFIED and matches the project's allowlist, which names file types as well as
     folders (a project with no allowlist never qualifies); the denylist wins over the allowlist, always, and
     covers any dot-folder or dot-file at any depth, `__pycache__`, and agent files (CLAUDE.md, CLAUDE.local.md,
     AGENTS.md, AGENTS.override.md, AGENT.md, GEMINI.md, SKILL.md) anywhere
  2. at most MAX_FILES files and MAX_LINES changed lines
  3. no needs:jay, needs:legal, UI or deploy flag, no SECURITY / LEGAL / DESIGN type, no plan-gate label, and
     Jay has not asked to accept it (owner:accept)
  4. the recorded review APPROVEs, it covers the PR's head right now, it was recorded against this very PR,
     and the ticket has exactly one open linked PR
  5. the PR is open, not a draft, MERGEABLE, based on `main` and from the same repository
  6. CI has nothing failing or pending. No checks at all is allowed (the PRs this allows are tests and docs;
     there is no PR workflow yet, CC-033) but it is reported as "no CI checks", never as "green".

A project whose team lead permissions are "Merge all" or higher (ccd/lead_authority.py, policy "lead") is classified
by `classify(..., policy="lead")`: rules 4 to 6 as above, rule 3 as lead_authority.jay_reasons (plus UI and DESIGN
work below "All"), and instead of rules 1 and 2 only the rails: no PR that touches agent rules, CI or the project's
protected paths (RAILS, PROJECT_RAILS) is merged on a lead's permission.

The daemon (ccd/daemon.py `_auto_merge`) does the rest: the switches, the stop file, the merge itself.
"""
import re
from collections import namedtuple

from . import lead_authority
from . import pipeline

# project key → glob patterns a changed file must match. No entry, no auto-merge.
ALLOW = {
    "commandcenter": ("server/tests/**/*.py", "web/app/tests/**/*.ts", "web/app/tests/**/*.tsx", "docs/**/*.md",
                      "README.md"),
}
# Never auto-merged, whatever else is true. A pattern without "/" matches the file name anywhere in the tree.
# Matching is case-insensitive here (the allowlist is case-sensitive), so Agents.md cannot sneak past.
DENY = (
    "server/ccd/**", "scripts/**", "launcher/**", ".github/**", "web/app/src/**", "plans/**", ".claude/**",
    "policy/**",   # Project Operating Profiles and Jay's decisions (D-007: no agent expands its own authority)
    "docs/SECURITY.md", "docs/adr/**",
    "AGENTS.md", "AGENTS.override.md", "AGENT.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", "SKILL.md",
    # lockfiles and manifests
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "*.lock",
    "requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "go.mod", "go.sum",
    "Cargo.toml", "tsconfig*.json", "vite.config.*",
)
# Never merged on a lead's permission, at any level (D-007: no agent changes its own or another agent's rules, and CI
# changes need Jay). A pattern without "/" matches the file name anywhere, case-insensitively.
RAILS = (".github/**", "**/.claude/**", "**/.codex/**", "**/.mcp.json", "AGENTS.md", "AGENTS.override.md", "AGENT.md",
         "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", "SKILL.md")
# A project's own protected paths (its profile's target self_protection, policy/projects/<key>.toml; a test keeps
# them equal). Command Center's are its rails and its own code: Jay approves every change there (AGENTS.md).
PROJECT_RAILS = {
    "commandcenter": ("server/ccd/**", "scripts/**", "launcher/**", "policy/**", "web/app/src/**"),
}
LEAD_CHANGES = ("ADDED", "MODIFIED", "DELETED")
LEAD_MAX_FILES = 99     # `gh pr view --json files` lists at most 100: a PR at the limit may have more Jay never saw
MAX_FILES = 10
MAX_LINES = 300
GOOD_CHANGES = ("ADDED", "MODIFIED")
BAD_TYPES = ("SECURITY", "LEGAL", "DESIGN")

# Check states, as `gh` reports them for check runs (conclusion/status) and commit statuses (state).
_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_PENDING = {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", "WAITING", "REQUESTED", ""}

Decision = namedtuple("Decision", "ok reasons wait ci")
# ok:      every rule holds
# reasons: why not (empty when ok); each a short sentence for the Needs Jay gate
# wait:    the only things in the way are expected to change by themselves (CI still running, GitHub still
#          computing mergeability). The daemon looks again later instead of opening a gate.
# ci:      "none" | "green" | "pending" | "failing" | "unknown"


def _glob(pattern):
    """A path glob as a regex: `**` crosses folders, `*` and `?` stay inside one."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _compile(patterns, anywhere, flags=0):
    """`anywhere`: a pattern without "/" matches the file name at any depth (the denylist); otherwise every
    pattern is anchored at the repository root (the allowlist: README.md is the root README only)."""
    return [re.compile((r"^(?:.*/)?" if anywhere and "/" not in p else "^") + _glob(p) + "$", flags) for p in patterns]


_DENY = _compile(DENY, True, re.IGNORECASE)
_RAILS = _compile(RAILS, True, re.IGNORECASE)
_PROJECT_RAILS = {k: _compile(v, False, re.IGNORECASE) for k, v in PROJECT_RAILS.items()}
_ALLOW = {k: _compile(v, False) for k, v in ALLOW.items()}


def safe_path(path):
    """A repository-relative path with nothing odd in it, else False."""
    if not isinstance(path, str) or not path or len(path) > 400 or path.startswith("/") or "\\" in path \
            or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def hidden_part(path):
    """A dot-folder or dot-file anywhere in the path (.claude, .mcp.json, .codex, .env …) or a __pycache__ folder:
    agent configuration and build output, never auto-merged, whatever folder it sits in."""
    return any(part.startswith(".") or part == "__pycache__" for part in path.split("/"))


def denied(path):
    return hidden_part(path) or any(p.match(path) for p in _DENY)


def allowed(project, path):
    return any(p.match(path) for p in _ALLOW.get(project, ()))


def rail(project, path):
    return any(p.match(path) for p in _RAILS) or any(p.match(path) for p in _PROJECT_RAILS.get(project, ()))


def lead_file_reasons(project, files):
    """Why a lead may not merge this change set: it touches a rail, or the file list cannot be trusted. []: it may."""
    if not isinstance(files, list) or not files:
        return ["the PR lists no changed files"]
    if len(files) > LEAD_MAX_FILES:
        return [f"{len(files)} files changed: GitHub may not have listed them all"]
    reasons = []
    for f in files:
        path = f.get("path") if isinstance(f, dict) else None
        if not safe_path(path):
            reasons.append("a changed file has an unusable path")
        elif f.get("changeType") not in LEAD_CHANGES:
            # gh lists a rename by its new name only: renaming .github/workflows/ci.yml away would pass the rail
            # check and remove CI. Only added, modified and deleted files, whose one path is the whole change.
            reasons.append(f"{path} is {str(f.get('changeType') or 'of unknown change type').lower()} "
                           "(only added, modified or deleted files)")
        elif rail(project, path):
            reasons.append(f"{path} is a protected path only Jay merges")
    seen = set()
    return [r for r in reasons if not (r in seen or seen.add(r))][:6]


def lead_ticket_reasons(ticket, work, authority):
    """Why the ticket's merge stays Jay's on a lead's permission (rule 3 for policy "lead")."""
    authority = authority or {}
    level = authority.get("level")
    out = lead_authority.jay_reasons(ticket, authority.get("keepSensitive") is not False,
                                     (work or {}).get("confirmed") or ())
    if not lead_authority.grants(level, "ui"):
        if ticket.get("type") == "DESIGN":
            out.append("the ticket type is DESIGN")
        flags = {f.replace(":", "_").replace("-", "_") for f in ticket.get("flags") or []}
        if "needs_ui_review" in flags or "ui" in (ticket.get("labels") or []):
            out.append("the ticket needs a UI acceptance")
    return out


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def file_reasons(project, files, additions=None, deletions=None):
    """Why this change set is not low-risk (rules 1 and 2). [] when it is."""
    if not _ALLOW.get(project):
        return [f"{project} has no auto-merge allowlist"]
    if not isinstance(files, list) or not files:
        return ["the PR lists no changed files"]
    reasons = []
    if len(files) > MAX_FILES:
        reasons.append(f"{len(files)} files changed (limit {MAX_FILES})")
    lines = 0
    unknown = False
    for f in files if len(files) <= MAX_FILES else files[:MAX_FILES]:
        path = f.get("path") if isinstance(f, dict) else None
        adds, dels = (_count(f.get("additions")), _count(f.get("deletions"))) if isinstance(f, dict) else (None, None)
        if adds is None or dels is None:
            unknown = True
        else:
            lines += adds + dels
        if not safe_path(path):
            reasons.append("a changed file has an unusable path")
            continue
        change = f.get("changeType")
        if change not in GOOD_CHANGES:
            reasons.append(f"{path} is {str(change or 'of unknown change type').lower()} (only added or modified files)")
        if denied(path):
            reasons.append(f"{path} is never auto-merged")
        elif not allowed(project, path):
            reasons.append(f"{path} is outside the low-risk paths")
    total = [_count(additions), _count(deletions)]
    if None in total:
        unknown = True
    else:
        lines = max(lines, total[0] + total[1])
    if unknown:
        reasons.append("the PR's line counts are unknown")
    elif lines > MAX_LINES:
        reasons.append(f"{lines} lines changed (limit {MAX_LINES})")
    seen = set()
    return [r for r in reasons if not (r in seen or seen.add(r))][:6]


def ci_state(rollup):
    """'none' (no checks at all) | 'green' | 'pending' | 'failing' | 'unknown', from `statusCheckRollup`."""
    if not rollup:
        return "none"
    if not isinstance(rollup, list):
        return "unknown"
    states = [str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() if isinstance(c, dict) else "?"
              for c in rollup]
    if any(s not in _OK and s not in _PENDING for s in states):
        return "failing" if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED",
                                      "STARTUP_FAILURE", "STALE") for s in states) else "unknown"
    return "pending" if any(s in _PENDING for s in states) else "green"


def ticket_reasons(ticket, work):
    """Why the ticket itself is not low-risk (rule 3)."""
    out = []
    flags = {f.replace(":", "_").replace("-", "_") for f in ticket.get("flags") or []}
    for flag, name in (("needs_jay", "needs Jay"), ("needs_legal", "needs legal"), ("needs_ui_review", "needs UI review"),
                       ("needs_deploy", "needs a deploy")):
        if flag in flags:
            out.append(f"the ticket is flagged {name}")
    if ticket.get("type") in BAD_TYPES:
        out.append(f"the ticket type is {ticket['type']}")
    if "ui" in (ticket.get("labels") or []):
        out.append("the ticket has the ui label")
    labels = sorted(set(ticket.get("labels") or []) & pipeline.PLAN_GATE_LABELS)
    if labels:
        out.append("the ticket has plan-gate labels: " + ", ".join(labels))
    if "owner:accept" in ((work or {}).get("confirmed") or []):
        out.append("Jay asked to accept this ticket's merge himself")
    return out


def classify(project, ticket, work, pr, pr_ref, open_prs, policy="low-risk", authority=None):
    """Decide one READY_TO_MERGE ticket.

    project   the registry key (picks the allowlist)
    ticket    tasks.get(): status, type, flags, labels, project
    work      pipeline.work(): review {verdict, head, pr}, gate, confirmed
    pr        a fresh `gh pr view --json state,isDraft,mergeable,baseRefName,headRefOid,isCrossRepository,files,
              additions,deletions,statusCheckRollup`
    pr_ref    "owner/repo#N" of the PR in `pr`
    open_prs  the refs of the ticket's open linked PRs (it must have exactly one, this one)
    policy    "low-risk", or "lead" (team lead permissions at "Merge all" or higher)
    authority with policy "lead": {"level", "keepSensitive"} from lead_authority
    """
    reasons = []
    wait = []
    lead = policy == pipeline.LEAD_MERGE
    if policy != "low-risk" and not lead:
        return Decision(False, ["the project's merge policy is not low-risk"], False, "unknown")
    if lead and not lead_authority.grants((authority or {}).get("level"), "merge"):
        return Decision(False, ["the lead's permissions do not include merging"], False, "unknown")
    pr = pr if isinstance(pr, dict) else {}
    work = work or {}
    rv = work.get("review") or {}

    if ticket.get("status") != "READY_TO_MERGE":
        reasons.append(f"the ticket is {ticket.get('status')}, not READY_TO_MERGE")
    if work.get("gate"):
        reasons.append(f"a {work['gate']} gate is open")
    reasons += lead_ticket_reasons(ticket, work, authority) if lead else ticket_reasons(ticket, work)

    head = pr.get("headRefOid")
    if rv.get("verdict") != "APPROVE":
        reasons.append("there is no recorded APPROVE review")
    elif not pipeline.SHA_RE.match(str(rv.get("head") or "")):
        reasons.append("the recorded review has no full commit SHA")
    elif rv.get("head") != head:
        reasons.append(f"the PR head {str(head or '?')[:7]} is not the reviewed head {rv['head'][:7]}")
    if not rv.get("pr"):
        reasons.append("the review was not recorded against a PR")
    elif rv.get("pr") != pr_ref:
        reasons.append(f"the review was recorded against {rv['pr']}, not {pr_ref}")
    if list(open_prs or []) != [pr_ref]:
        reasons.append(f"the ticket has {len(list(open_prs or []))} open linked PRs (it needs exactly this one)")

    if pr.get("state") != "OPEN":
        reasons.append(f"the PR is {str(pr.get('state') or 'in an unknown state').lower()}, not open")
    if pr.get("isDraft") is not False:
        reasons.append("the PR is a draft")
    mergeable = pr.get("mergeable")
    if mergeable == "UNKNOWN":
        wait.append("GitHub has not worked out mergeability yet")
    elif mergeable != "MERGEABLE":
        reasons.append(f"the PR is {str(mergeable or 'of unknown mergeability').lower()}, not mergeable")
    if pr.get("baseRefName") != "main":
        reasons.append(f"the PR is based on {pr.get('baseRefName') or '?'}, not main")
    if pr.get("isCrossRepository") is not False:
        reasons.append("the PR comes from another repository")

    ci = ci_state(pr.get("statusCheckRollup"))
    if ci == "failing":
        reasons.append("a CI check is failing")
    elif ci == "unknown":
        reasons.append("a CI check is in a state ccd does not recognise")
    elif ci == "pending":
        wait.append("CI is still running")

    reasons += lead_file_reasons(project, pr.get("files")) if lead else \
        file_reasons(project, pr.get("files"), pr.get("additions"), pr.get("deletions"))
    if reasons:
        return Decision(False, reasons, False, ci)
    return Decision(not wait, wait, bool(wait), ci)
