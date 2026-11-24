"""Which reviewed PRs ccd may merge by itself (CC-025, docs/adr/0007-auto-merge-policy.md).

A pure classifier: it reads facts it is handed (the ticket, its recorded review, a fresh `gh pr view`) and
answers yes, no (with every reason) or "wait" (a state that is expected to change in minutes). It runs no
command, reads no file and holds no state, so every rule here can be tested with plain dicts.

Low-risk means ALL of (CC-057 widened this from Command Center tests and docs to small app code in four projects):

  1. every file is ADDED or MODIFIED, matches the project's allow list and no deny list. DENY always wins: dot paths,
     agent files, manifests, migrations, fixtures, vendored code, a name catch-all tested against EVERY path part
     (folders and file), and the project's own sensitive areas. Only tests and docs may be ADDED; app code only
     MODIFIED. Paths are ASCII, mode 100644 at base and head
  2. at most MAX_FILES files and MAX_LINES changed lines
  3. no needs:jay, needs:legal, UI or deploy flag, no SECURITY / LEGAL / DESIGN type, no plan-gate label, Jay has
     not asked to accept it (owner:accept), and the ticket is sized small, never risky before
  4. the recorded review APPROVEs, it covers the PR's head right now, it was recorded against this very PR,
     and the ticket has exactly one open linked PR
  5. the PR is open, not a draft, MERGEABLE, based on the project's base branch and from the same repository
  6. the project's named CI jobs are all SUCCESS as GitHub Actions check runs; no checks at all is not green
  7. the content rule: no allowed non-test file's text, at base or head, matches the project's import markers (the
     sign-in, database and permission layer); the PR and every Issue it references carry no risk label; screen
     files need a passed user check at the head

The daemon (ccd/daemon.py `_auto_merge`) does the rest: the two switches, the stop file, the merge itself.
"""
import base64
import re
from collections import namedtuple

from . import pipeline, registry

# CC-057: what "low-risk" means per project. `free` files (tests, docs) may be ADDED or MODIFIED; `code` files only
# MODIFIED, because a new app file has no base text for the content rule and no existing auth wiring to compare
# (tech review H2). `tests` are the files exempt from the content rule (and only from it). Every pattern is anchored
# at the repository root; DENY wins over all of it (DENY is case-insensitive, the allow lists are not).
PROJECT = {
    "commandcenter": {
        "free": ("server/tests/**/*.py", "web/app/tests/**/*.ts", "web/app/tests/**/*.tsx", "docs/**/*.md", "README.md"),
        "code": (),
        "tests": ("server/tests/**", "web/app/tests/**"),
        # Every AGENTS.md protected path: no Command Center app code can auto-merge (D-007).
        "deny": ("server/ccd/**", "scripts/**", "launcher/**", "web/app/src/**", "plans/**", "policy/**",
                 "docs/SECURITY.md", "docs/adr/**", "AGENTS.md"),
        "markers": (),
    },
    "mfe": {
        "free": ("tests/**/*.ts", "docs/**/*.md", "README.md"),
        "code": ("components/**/*.tsx", "app/**/page.tsx", "app/**/*.css", "lib/utils.ts", "lib/money.ts",
                 "lib/use-is-hydrated.ts", "public/**/*.svg"),
        "tests": ("tests/**",),
        "deny": ("app/api/**", "app/auth/**", "app/invite/**", "app/household/**", "app/clients/**", "app/dashboard/**",
                 "app/expenses/**", "app/reports/**", "app/layout.tsx", "components/accountant-*", "services/**",
                 "uploads/**", "proxy.ts", "next.config.ts", "tests/fixtures/**"),
        "markers": (r"@/lib/(?:auth|db)\b", r"@prisma/client", r"next-auth",
                    r"""['"]\.{1,2}/[^'"\n]*\b(?:auth|db)(?:/[^'"\n]*)?['"]""",
                    r"\bprisma\.", r"\brequireHouseholdMember\b", r"\bgetSession\b", r"\bcan[A-Z]\w*\(", r"\bcookies\(",
                    # SVG that can run script (tech review L: svg is allowed, a scripted svg is not)
                    r"<script", r"\bon[a-z]+\s*=", r"javascript:", r"foreignObject"),
    },
    "gyst": {
        "free": ("**/*_test.go", "docs/**/*.md", "README.md"),
        "code": ("internal/handlers/*.go", "internal/services/*.go", "web/templates/*.html", "web/static/css/**",
                 "web/static/js/*.js"),
        "tests": ("**/*_test.go",),
        "deny": ("**/migrations/**", "**/models/**", "**/schema*", "**/auth/**", "**/crypto/**",
                 "internal/handlers/handlers.go", "internal/app/**", "internal/config/**", "internal/db/**",
                 "internal/authlimit/**", "internal/healthcoach/**", "internal/imageintake/**",
                 "internal/providers/**", "internal/repository/**", "cmd/**", "web/templates/layout.html",
                 "web/static/service-worker.js", "*health*", "*food*", "*coach*", "*nutrition*", "*training*",
                 "*weight*", "*water*", "*push*", "*galaxy*", "*client_ingress*", "*automation*", "*ai_settings*",
                 "*provider*", "*requestlog*", "*localpath*"),
        # .Repo. and func init( : same-package DB access that has no import to match (tech review H1)
        "markers": (r"lifeops-tracker/internal/(?:db|repository|config|authlimit|app)\b", r"database/sql",
                    r"net/http/cookiejar", r"\bsessionToken\b", r"\brequireAuth\b", r"\.sessions\b", r"\bsql\.Tx\b",
                    r"\.Exec\(", r"\.Query\(", r"\.Repo\.", r"\bfunc init\("),
    },
    "samvision": {
        "free": ("tests/**/*.py", "docs/**/*.md", "README.md"),
        "code": ("samvision/api/*.py", "samvision/api/templates/*.html", "samvision/api/static/*.js",
                 "samvision/api/static/app.css", "samvision/vehicle/*.py", "samvision/analytics/*.py"),
        "tests": ("tests/**",),
        "deny": ("samvision/cma/**", "samvision/comparables/**", "samvision/calibration/**", "samvision/evaluation/**",
                 "samvision/backtesting/**", "samvision/market/**", "samvision/ingestion/**", "samvision/storage/**",
                 "samvision/geo/**", "samvision/plan/**", "ml/**", "db/**", "utils/**", "pdf_uploads/**",
                 "parsed_csv/**", "*.geojson",
                 "samvision/api/{web,settings,app,db,jobs,worker,mailer,operators,service,ingestion,contract,"
                 "registration,ratelimit,observability}.py",
                 "samvision/api/templates/{_map,base_preline,error}.html",
                 "samvision/api/static/{market-map,subject-map,leaflet,htmx.min,preline}.*",
                 "samvision/api/static/fonts/**", "samvision/vehicle/{routing,live}.py",
                 "*valuation*", "*valuing*", "*ppsf*", "*offer*", "*pricing*", "*cma*", "*cme*", "*comparable*",
                 "*rental_plan*", "*market*", "*calibration*", "*sold*", "*explorer*", "*import*", "*advisor*"),
        "markers": (r"from\s+\.(?:auth|access|tenancy|db|registration|ratelimit|uploads)\b",
                    r"from\s+\.+\s+import\s+[^\n]*\b(?:auth|access|tenancy|db|registration|ratelimit|uploads)\b",
                    r"\bsamvision\.api\.(?:auth|access|tenancy|db|registration|ratelimit|uploads)\b",
                    r"\bsamvision\.(?:storage|ingestion|cma|market)\b", r"\bsqlalchemy\b", r"\btenant\b",
                    r"\bcurrent_user\b", r"\brequire_\w*", r"\bengine\b", r"\btext\(", r"\bL\.map\("),
    },
}
# MFE's lib/** is denied except these three files (a denylist cannot say "except", so denied() checks it).
LIB_ALLOWED_MFE = ("lib/utils.ts", "lib/money.ts", "lib/use-is-hydrated.ts")

# Never auto-merged, whatever else is true, in every project. A pattern without "/" matches the file name anywhere in
# the tree. Matching is case-insensitive here, so Agents.md cannot sneak past.
COMMON_DENY = (
    ".github/**", ".claude/**",
    "AGENTS.md", "AGENTS.override.md", "AGENT.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", "SKILL.md",
    # manifests and lockfiles
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "*.lock",
    "package*.json", "requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "go.mod", "go.sum",
    "Cargo.toml", "tsconfig*.json", "*.config.*", "vite.config.*",
    "Dockerfile*", "docker-compose*", "Caddyfile", "Makefile",
    "**/migrations/**", "**/*.sql", "prisma/**",
    "**/fixtures/**", "data/**", "seeds/**", "backups/**", "*.csv", "*.pkl", "*.env*",
    "**/vendor/**", "*.min.js",
)
# A path part that CONTAINS any of these (case-insensitive) is never auto-merged. Tested against every folder and the
# file name, so app/login/page.tsx and app/(auth)/x/page.tsx are refused, not only auth.go (tech review round 2).
NAME_DENY = ("auth", "session", "password", "login", "logout", "signup", "sign-in", "oauth", "permission", "access",
             "role", "tenan", "household", "member", "invite", "account", "secret", "crypto", "token", "csrf",
             "payment", "billing", "stripe", "upload", "privacy", "retention", "delet", "reset", "verif", "locked",
             "settings", "middleware", "admin")
# Dynamic loading hides an import from the marker patterns, so it is a marker too.
COMMON_MARKERS = (r"\bimportlib\b", r"__import__", r"\bimport\s*\(", r"\brequire\s*\(")
# PR files that show on screen need a passed user check at the head (UI rule).
UI_FILES = ("*.html", "*.tsx", "*.css", "**/static/**")
# Labels on the PR or an Issue it references that stop auto-merge (GitHub risk labels of SamVision and GYST).
BAD_LABELS = ("risk:elevated", "risk:privileged", "risk:not-agent-eligible", "type:security", "security")
# Labels that make a security sign-off required besides BAD_LABELS (Jay #187).
SIGNOFF_LABELS = ("migration",)
OK_MODE = "100644"
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


def expand_braces(pattern):
    """`a/{b,c}.py` -> ['a/b.py', 'a/c.py'] (nested too). A brace with no partner stays a plain character.
    CC-057: _glob used to treat { } as literal, so every {a,b} deny matched nothing."""
    depth, start = 0, None
    for i, c in enumerate(pattern):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth:
            depth -= 1
            if depth == 0:
                inner, parts, level, last = pattern[start + 1:i], [], 0, 0
                for j, d in enumerate(inner):
                    level += (d == "{") - (d == "}")
                    if d == "," and level == 0:
                        parts.append(inner[last:j])
                        last = j + 1
                parts.append(inner[last:])
                out = []
                for part in parts:
                    out += expand_braces(pattern[:start] + part + pattern[i + 1:])
                return out
    return [pattern]


def _glob1(pattern):
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


def _glob(pattern):
    """A path glob as a regex: `**` crosses folders, `*` and `?` stay inside one, `{a,b}` is a choice."""
    return "(?:" + "|".join(_glob1(p) for p in expand_braces(pattern)) + ")"


def _compile(patterns, anywhere, flags=0):
    """`anywhere`: a pattern without "/" matches the file name at any depth (the denylist); otherwise every
    pattern is anchored at the repository root (the allowlist: README.md is the root README only)."""
    out = []
    for p in patterns:
        for q in expand_braces(p):
            out.append(re.compile((r"^(?:.*/)?" if anywhere and "/" not in q else "^") + _glob1(q) + "$", flags))
    return out


def _deny_of(project):
    return tuple(PROJECT.get(project, {}).get("deny") or ())


_COMMON = _compile(COMMON_DENY, True, re.IGNORECASE)
_DENY_P = {k: _compile(_deny_of(k), True, re.IGNORECASE) for k in PROJECT}
_FREE = {k: _compile(v["free"], False) for k, v in PROJECT.items()}
_CODE = {k: _compile(v["code"], False) for k, v in PROJECT.items()}
_TESTS = {k: _compile(v["tests"], False) for k, v in PROJECT.items()}
_UI = _compile(UI_FILES, True, re.IGNORECASE)
_MARKERS = {k: [re.compile(m) for m in COMMON_MARKERS + tuple(v["markers"])] for k, v in PROJECT.items()}
# Back-compat names (daemon/oracle read ALLOW to know which projects have a rule).
ALLOW = {k: tuple(v["free"]) + tuple(v["code"]) for k, v in PROJECT.items()}
DENY = tuple(COMMON_DENY) + _deny_of("commandcenter")


def safe_path(path):
    """A repository-relative path with nothing odd in it, else False. ASCII only: a Cyrillic 'a' in auth.go must not
    slip past the name list (CC-057)."""
    if not isinstance(path, str) or not path or len(path) > 400 or path.startswith("/") or "\\" in path \
            or not path.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def hidden_part(path):
    """A dot-folder or dot-file anywhere in the path (.claude, .mcp.json, .codex, .env …) or a __pycache__ folder:
    agent configuration and build output, never auto-merged, whatever folder it sits in."""
    return any(part.startswith(".") or part == "__pycache__" for part in path.split("/"))


def name_hit(path):
    """The NAME_DENY word found in any folder or the file name of the path, else None."""
    for part in path.lower().split("/"):
        for word in NAME_DENY:
            if word in part:
                return word
    return None


def denied(path, project="commandcenter"):
    """DENY always wins: dot-paths, the common list, the name catch-all on every path part, the project's own list."""
    if hidden_part(path) or name_hit(path) or any(p.match(path) for p in _COMMON) \
            or any(p.match(path) for p in _DENY_P.get(project, ())):
        return True
    # MFE's lib/** is denied except three helpers.
    return project == "mfe" and path.lower().startswith("lib/") and path not in LIB_ALLOWED_MFE


def allowed(project, path):
    return free(project, path) or any(p.match(path) for p in _CODE.get(project, ()))


def free(project, path):
    """A tests or docs file: may be ADDED, not only MODIFIED."""
    return any(p.match(path) for p in _FREE.get(project, ()))


def is_test(project, path):
    return any(p.match(path) for p in _TESTS.get(project, ()))


def is_ui(path):
    return any(p.match(path) for p in _UI)


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def content_hits(project, text):
    """The marker patterns an allowed file's text matches (the content rule)."""
    return [m.pattern for m in _MARKERS.get(project, ()) if m.search(text)]


def facts_reasons(project, files, facts):
    """Rules that need what ccd read from GitHub at merge time (CC-057): the git mode of every changed path at base
    and head (symlink 120000, submodule 160000, executable 100755 refused; a truncated tree refuses), and the text of
    every allowed non-test file at base and head against the project's import markers. Missing, unreadable or
    truncated facts refuse: never read as empty."""
    if not isinstance(facts, dict) or facts.get("errors"):
        return ["ccd could not read the PR's file modes and text from GitHub"]
    reasons = []
    if facts.get("truncated"):
        reasons.append("GitHub's file tree was truncated")
    modes = facts.get("modes") if isinstance(facts.get("modes"), dict) else {}
    texts = facts.get("texts") if isinstance(facts.get("texts"), dict) else {}
    for f in files if isinstance(files, list) else []:
        path = f.get("path") if isinstance(f, dict) else None
        if not isinstance(path, str):
            continue
        added = f.get("changeType") == "ADDED"
        m = modes.get(path)
        if not isinstance(m, dict) or m.get("head") != OK_MODE or \
                (m.get("base") is not None if added else m.get("base") != OK_MODE):
            reasons.append(f"{path} is not a plain file at both base and head (symlink, submodule, executable or unread)")
            continue
        if is_test(project, path):
            continue    # tests folders are exempt from the content rule, and only from it
        t = texts.get(path)
        head_text = t.get("head") if isinstance(t, dict) else None
        base_text = t.get("base") if isinstance(t, dict) else None
        if not isinstance(head_text, str) or (not added and not isinstance(base_text, str)):
            reasons.append(f"{path}: its text at base or head could not be read")
            continue
        for side, text in (("head", head_text), ("base", base_text)):
            if isinstance(text, str) and content_hits(project, text):
                reasons.append(f"{path} touches the sign-in, database or permission layer ({side} text)")
                break
    return reasons


def file_reasons(project, files, additions=None, deletions=None, facts=None):
    """Why this change set is not low-risk (rules 1 and 2). [] when it is. With `facts` (the merge-time reads of
    modes and text) the mode and content rules run too; without them only the path rules do (the shadow engine)."""
    if project not in PROJECT:
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
        if denied(path, project):
            reasons.append(f"{path} is never auto-merged")
        elif not allowed(project, path):
            reasons.append(f"{path} is outside the low-risk paths")
        elif change == "ADDED" and not free(project, path):
            reasons.append(f"{path} is a new app file (only tests and docs may be added)")
    total = [_count(additions), _count(deletions)]
    if None in total:
        unknown = True
    else:
        lines = max(lines, total[0] + total[1])
    if unknown:
        reasons.append("the PR's line counts are unknown")
    elif lines > MAX_LINES:
        reasons.append(f"{lines} lines changed (limit {MAX_LINES})")
    if facts is not None and not reasons:
        reasons += facts_reasons(project, files, facts)
    seen = set()
    return [r for r in reasons if not (r in seen or seen.add(r))][:6]


def text_of_contents(payload):
    """The text of a GitHub contents-API answer, or None when it has none (over 1 MB the API sends no content, a
    directory or symlink has another type). None refuses; it never reads as an empty file."""
    if not isinstance(payload, dict) or payload.get("type") != "file" or payload.get("encoding") != "base64" \
            or not isinstance(payload.get("content"), str):
        return None
    try:
        return base64.b64decode(payload["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def required_checks(project, rollup):
    """(state, reasons) of the project's named CI jobs in a `statusCheckRollup`. Only a GitHub Actions check run
    counts (a CheckRun with a workflow): a commit status or another app's check named like a job cannot satisfy it
    (tech review M1). state: "green" | "pending" | "failing" | "missing"."""
    names = registry.checks_of(project)
    if not names:
        return "missing", [f"{project} has no required CI checks registered"]
    runs = [c for c in rollup if isinstance(c, dict)] if isinstance(rollup, list) else []
    missing, pending, bad = [], [], []
    for name in names:
        mine = [c for c in runs if c.get("name") == name and c.get("__typename") == "CheckRun" and c.get("workflowName")]
        if not mine:
            missing.append(name)
            continue
        for c in mine:
            st = str(c.get("conclusion") or c.get("status") or "").upper()
            if st == "SUCCESS":
                continue        # a skipped or neutral job did not run the checks: only SUCCESS counts
            (pending if st in _PENDING else bad).append(name)
    if bad:
        return "failing", [f"required CI check {n} is not SUCCESS" for n in sorted(set(bad))]
    if missing:
        return "missing", [f"required CI check {n} is missing" for n in missing]
    if pending:
        return "pending", ["CI is still running"]
    return "green", []


def label_reasons(labels):
    """Why the labels of the PR and the Issues it references stop an auto-merge."""
    hit = sorted({str(x).strip().lower() for x in labels or ()} & set(BAD_LABELS))
    return [f"a risk label is set: {', '.join(hit)}"] if hit else []


def security_required(project, ticket, files, labels, facts=None):
    """Whether a recorded security sign-off at the head is needed before the merge question (Jay #187): the type is
    SECURITY, a security, migration or GitHub risk label is present, or the PR hits any sensitive DENY, the name
    list or a content marker. Each trigger alone makes it required."""
    if (ticket or {}).get("type") == "SECURITY":
        return True
    low = {str(x).strip().lower() for x in labels or ()} | {str(x).strip().lower() for x in (ticket or {}).get("labels") or ()}
    if low & (set(BAD_LABELS) | set(SIGNOFF_LABELS)):
        return True
    for f in files if isinstance(files, list) else []:
        path = f.get("path") if isinstance(f, dict) else None
        if not safe_path(path) or denied(path, project):
            return True
    return bool(facts_reasons(project, files, facts)) if isinstance(facts, dict) and not facts.get("errors") else False


def size_reasons(size):
    """Rule: SMALL APP CODE needs a ticket sized small, stored and effective, never risky before (size history,
    tech reviewer raises, a risky ancestor). `size` is Pipeline.merge_size_facts."""
    if not isinstance(size, dict):
        return ["the ticket's size history is unknown"]
    out = []
    if size.get("stored") != "small" or size.get("effective") != "small":
        out.append("the ticket is not sized small")
    if size.get("everRisky"):
        out.append("the ticket was sized risky at some point")
    if size.get("raised"):
        out.append("the technical reviewer raised the ticket's size")
    if size.get("parentRisky"):
        out.append("the ticket's parent is risky")
    return out


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


def classify(project, ticket, work, pr, pr_ref, open_prs, policy="low-risk", facts=None):
    """Decide one READY_TO_MERGE ticket.

    project   the registry key (picks the allowlist)
    ticket    tasks.get(): status, type, flags, labels, project
    work      pipeline.work(): review {verdict, head, pr}, gate, confirmed
    pr        a fresh `gh pr view --json state,isDraft,mergeable,baseRefName,headRefOid,isCrossRepository,files,
              additions,deletions,statusCheckRollup`
    pr_ref    "owner/repo#N" of the PR in `pr`
    open_prs  the refs of the ticket's open linked PRs (it must have exactly one, this one)
    facts     what the daemon read fresh from GitHub and the ticket at merge time (CC-057): modes, texts, truncated,
              errors (merge_facts.fetch), labels, labelsComplete, size (Pipeline.merge_size_facts). None refuses:
              the classifier never guesses a fact it was not given.
    """
    reasons = []
    wait = []
    if policy != "low-risk":
        return Decision(False, ["the project's merge policy is not low-risk"], False, "unknown")
    pr = pr if isinstance(pr, dict) else {}
    work = work or {}
    rv = work.get("review") or {}

    if ticket.get("status") != "READY_TO_MERGE":
        reasons.append(f"the ticket is {ticket.get('status')}, not READY_TO_MERGE")
    if work.get("gate"):
        reasons.append(f"a {work['gate']} gate is open")
    reasons += ticket_reasons(ticket, work)

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
    base = registry.base_of(project)
    if not base or pr.get("baseRefName") != base:
        reasons.append(f"the PR is based on {pr.get('baseRefName') or '?'}, not {base or 'a registered branch'}")
    if pr.get("isCrossRepository") is not False:
        reasons.append("the PR comes from another repository")

    ci = ci_state(pr.get("statusCheckRollup"))
    if ci == "failing":
        reasons.append("a CI check is failing")
    elif ci == "unknown":
        reasons.append("a CI check is in a state ccd does not recognise")
    # CC-057: a green rollup is not enough; the project's named Actions jobs must each be SUCCESS at the head, and no
    # checks at all is not green (every project runs CI on pull requests now).
    named, why = required_checks(project, pr.get("statusCheckRollup"))
    if named == "pending":
        wait.append("CI is still running")
    elif named != "green" and ci != "failing":
        reasons += why
    if named == "missing" and ci in ("green", "none"):
        ci = ci if ci == "none" else "unknown"      # a green rollup that lacks the named jobs is not green
    elif named == "pending":
        ci = "pending"
    # A pending check outside the required names (web-e2e, a third party) still waits, and is never called green.
    if ci == "pending" and "CI is still running" not in wait:
        wait.append("CI is still running")

    facts = facts if isinstance(facts, dict) else None
    reasons += file_reasons(project, pr.get("files"), pr.get("additions"), pr.get("deletions"), facts)
    if facts is None:
        reasons.append("ccd has not read the PR's labels, file modes and text")
    else:
        if not facts.get("labelsComplete"):
            reasons.append("the PR's and its Issues' labels could not all be read")
        reasons += label_reasons(facts.get("labels"))
        # CC-057 round 2: the base branch the files were judged against comes from the same pinned read as the head
        # and must be the registered one, and the same as the PR view said.
        fbase = facts.get("base")
        if not isinstance(fbase, dict) or fbase.get("ref") != base or fbase.get("ref") != pr.get("baseRefName"):
            reasons.append("the PR's base branch is not the one the files were judged against")
        if facts.get("head") != head:
            reasons.append("the facts were read at another head")
        # A denied path in ANY commit of the PR refuses, even when the net diff is clean (the merge commit brings
        # every commit into the base branch's history).
        hist = facts.get("history")
        if not isinstance(hist, list):
            reasons.append("the PR's commit history could not be inspected")
        else:
            for hp in hist:
                if not safe_path(hp) or denied(hp, project):
                    reasons.append(f"a commit of the PR touched {hp if safe_path(hp) else 'an unusable path'}, "
                                   "which is never auto-merged")
                    break
        # The security sign-off: required unless the daemon said it is not, and then it must exist at this head.
        if facts.get("securityRequired") is not False and not facts.get("securitySignoff"):
            reasons.append("the change needs a security sign-off at this head")
        reasons += size_reasons(facts.get("size"))
        for f in pr.get("files") if isinstance(pr.get("files"), list) else []:
            path = f.get("path") if isinstance(f, dict) else None
            if safe_path(path) and is_ui(path):
                uc = (work or {}).get("userCheck") or {}
                if uc.get("result") != "pass" or uc.get("head") != head:
                    reasons.append(f"{path} is a screen file and has no passed user check at this head")
                    break
    if reasons:
        return Decision(False, list(dict.fromkeys(reasons)), False, ci)
    return Decision(not wait, wait, bool(wait), ci)
