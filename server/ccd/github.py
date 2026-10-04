"""One GitHub identity per project, and every GitHub URL built from it.

ccd never trusts a URL string it was handed (a config file, a fixture, a stored
link) to point at GitHub. It knows `owner/repo` for each project and builds the
repository, pull request, commit, branch and Actions URLs from that alone, on
https://github.com. A remote that does not normalise to a plain github.com
`owner/repo` is no identity at all: the UI then shows the name without a link
rather than a link to somewhere else.
"""
import re
import subprocess
from urllib.parse import quote

HOST = "https://github.com"
# GitHub's own rules: owner 1-39 of [A-Za-z0-9-], repo 1-100 of [A-Za-z0-9._-].
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

_REMOTES = (
    re.compile(r"^git@github\.com:(?P<o>[^/\s]+)/(?P<r>[^/\s]+?)(?:\.git)?/?$"),
    re.compile(r"^ssh://git@github\.com(?::22)?/(?P<o>[^/\s]+)/(?P<r>[^/\s]+?)(?:\.git)?/?$"),
    re.compile(r"^https://(?:[^@/\s]+@)?github\.com/(?P<o>[^/\s]+)/(?P<r>[^/\s]+?)(?:\.git)?/?$"),
    re.compile(r"^(?P<o>[^/\s:@]+)/(?P<r>[^/\s:@]+?)(?:\.git)?$"),  # already owner/repo
)


def normalize(remote):
    """'owner/repo' from an SSH, HTTPS or bare remote on github.com, else None."""
    text = (remote or "").strip()
    for pat in _REMOTES:
        m = pat.match(text)
        if m:
            owner, repo = m.group("o"), m.group("r")
            if OWNER_RE.match(owner) and REPO_RE.match(repo) and repo not in (".", ".."):
                return f"{owner}/{repo}"
            return None
    return None


def repo_url(slug):
    return f"{HOST}/{slug}" if normalize(slug) == slug else None


def pr_url(slug, number):
    base = repo_url(slug)
    if not base or not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        return None
    return f"{base}/pull/{number}"


def issue_url(slug, number):
    base = repo_url(slug)
    if not base or not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        return None
    return f"{base}/issues/{number}"


def commit_url(slug, sha):
    base = repo_url(slug)
    return f"{base}/commit/{sha.lower()}" if base and isinstance(sha, str) and SHA_RE.match(sha) else None


def branch_url(slug, branch):
    base = repo_url(slug)
    if not base or not branch or not isinstance(branch, str) or any(c in branch for c in "\x00 ~^:?*[\\"):
        return None
    return f"{base}/tree/{quote(branch, safe='/')}"


def actions_url(slug):
    base = repo_url(slug)
    return f"{base}/actions" if base else None


def identity(slug):
    """The public shape: {owner, repo, slug, url} or None."""
    s = normalize(slug)
    if not s or s != slug:
        return None
    owner, repo = s.split("/")
    return {"owner": owner, "repo": repo, "slug": s, "url": repo_url(s)}


def pr_ref_url(ref):
    """'owner/repo#12' → the canonical PR URL, else None."""
    slug, _, num = (ref or "").rpartition("#")
    return pr_url(slug, int(num)) if num.isdigit() else None


def link_url(provider, kind, ref, given=None):
    """The URL a ticket link may carry. A GitHub PR link's URL is rebuilt from its
    ref; any other link keeps its given URL only if it is plain https."""
    if provider == "github" and kind == "pr":
        return pr_ref_url(ref)
    if isinstance(given, str) and re.match(r"^https://[A-Za-z0-9.-]+(?:/[^\s]*)?$", given):
        return given
    return None


def origin_of(path, timeout=5):
    """The normalised `origin` remote of a checkout, or None. Read-only, no network."""
    try:
        out = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return normalize(out.stdout) if out.returncode == 0 else None
