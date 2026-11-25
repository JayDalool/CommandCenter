"""What ccd reads from GitHub right before it merges (CC-057), as one `facts` dict for merge_policy.classify.

Every read is pinned to a commit SHA (the PR head and its base commit), so the answer cannot change under the
reviewed head. Any failure, a truncated tree, a paginated list or a file the contents API sends without text goes
into `errors` and the classifier refuses; nothing here ever reads a gap as an empty file. Blocking: run it in a
thread (`asyncio.to_thread`). `gh_json(args)` runs gh and returns parsed JSON or raises OSError/ValueError.
"""
import re
from urllib.parse import quote

from . import merge_policy

# CC-057 round 2: every approved reference source, not only "#N" in the body. A full Issue or PR URL, a qualified
# owner/repo#N and the GitHub-linked closing issues all carry labels that count; one that cannot be read refuses.
URL_REF_RE = re.compile(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100})/(?:issues|pull)/(\d{1,7})\b")
QUAL_REF_RE = re.compile(r"(?<![\w/.:-])([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100})#(\d{1,7})\b")
BARE_REF_RE = re.compile(r"(?<![\w/.-])#(\d{1,7})\b")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
MAX_ISSUES = 10
MAX_COMMITS = 20
# The compare API's file status, in the `gh pr view` changeType words merge_policy reads (CC-057 round 3).
CHANGE_TYPES = {"added": "ADDED", "modified": "MODIFIED", "removed": "DELETED", "renamed": "RENAMED",
                "copied": "COPIED", "changed": "CHANGED", "unchanged": "UNCHANGED"}


def _linked_slug(x):
    """owner/repo of one `closingIssuesReferences` entry. gh exports repository {name, owner {login}} (CC-057 round 3:
    gh 2.98 api/export_pr.go has no nameWithOwner there); a missing or malformed one refuses, never falls back to
    the PR's own repository, which would read another Issue's labels."""
    repo = x.get("repository") if isinstance(x, dict) else None
    owner = (repo.get("owner") or {}).get("login") if isinstance(repo, dict) and isinstance(repo.get("owner"), dict) else None
    name = repo.get("name") if isinstance(repo, dict) else None
    slug = f"{owner}/{name}" if isinstance(owner, str) and isinstance(name, str) else ""
    if not SLUG_RE.match(slug) or not isinstance(x.get("number"), int) or isinstance(x.get("number"), bool):
        raise ValueError("a linked issue could not be read")
    url = x.get("url")
    if url is not None and url != f"https://github.com/{slug}/issues/{x['number']}":
        raise ValueError("a linked issue's URL does not match its repository")
    return slug


def references(repo, body, linked=(), ticket_refs=()):
    """{(owner/repo, number)} the PR points at: its body (URL, qualified, bare), GitHub's linked closing issues
    (`linked`: [{number, url, repository: {name, owner: {login}}}]) and the ticket's own GitHub links."""
    text = str(body or "")
    out = {(m.group(1), int(m.group(2))) for m in URL_REF_RE.finditer(text)}
    text = URL_REF_RE.sub(" ", text)
    out |= {(m.group(1), int(m.group(2))) for m in QUAL_REF_RE.finditer(text)}
    text = QUAL_REF_RE.sub(" ", text)
    out |= {(repo, int(n)) for n in BARE_REF_RE.findall(text)}
    if not isinstance(linked, (list, tuple)):
        raise ValueError("the linked issues could not be read")
    for x in linked:
        out.add((_linked_slug(x), x["number"]))
    for ref in ticket_refs:
        slug, _, num = str(ref).rpartition("#")
        if not num.isdigit():
            raise ValueError("a ticket link could not be read")
        out.add((slug or repo, int(num)))
    return out


def _labels(obj, what):
    """The label names of a PR or Issue read. A missing list or a label without a string name refuses (CC-057 round 3):
    a partial answer must never count as 'no risk label'."""
    labels = obj.get("labels") if isinstance(obj, dict) else None
    if not isinstance(labels, list) or not all(isinstance(x, dict) and isinstance(x.get("name"), str) for x in labels):
        raise ValueError(f"{what} labels unreadable")
    return [x["name"] for x in labels]


def _mode_map(tree):
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise ValueError("no tree")
    return {e["path"]: e.get("mode") for e in tree["tree"] if isinstance(e, dict) and isinstance(e.get("path"), str)}


def compare(gh_json, repo, base_sha, head):
    """(files, commit SHAs) of the ONE comparison base_sha...head (CC-057 round 3). Both ends are commit SHAs, so the
    answer is immutable: the changed files, the line counts and the commit list all come from the same pair, never
    from the mutable `gh pr view` or the PR-number commits list. The last commit must be the head, and a list GitHub
    cut short (more than 300 files, a commit count it did not send in full) refuses."""
    c = gh_json(["gh", "api", f"repos/{repo}/compare/{base_sha}...{head}?per_page=100"])
    if not isinstance(c, dict) or c.get("status") not in ("ahead", "diverged"):
        raise ValueError("the PR's comparison with its base is not ahead of it")
    commits = c.get("commits")
    if not isinstance(commits, list) or not commits or len(commits) > MAX_COMMITS \
            or c.get("total_commits") != len(commits):
        raise ValueError("the PR's commit list is empty, cut short or too long to inspect")
    shas = [(x or {}).get("sha") if isinstance(x, dict) else None for x in commits]
    if not all(isinstance(s, str) and merge_policy.pipeline.SHA_RE.match(s) for s in shas):
        raise ValueError("a commit has no SHA")
    if shas[-1] != head:
        raise ValueError("the compared commits do not end at the reviewed head")
    raw = c.get("files")
    if not isinstance(raw, list) or not raw or len(raw) >= 300:
        raise ValueError("the PR's file list is missing or cut off")
    files = []
    for x in raw:
        if not isinstance(x, dict) or not isinstance(x.get("filename"), str) or x.get("status") not in CHANGE_TYPES \
                or not all(isinstance(x.get(k), int) and not isinstance(x.get(k), bool) for k in ("additions", "deletions")):
            raise ValueError("a compared file could not be read")
        files.append({"path": x["filename"], "changeType": CHANGE_TYPES[x["status"]],
                      "additions": x["additions"], "deletions": x["deletions"]})
    return files, shas


def history_paths(gh_json, repo, shas):
    """Every path any of these commits touched, including renames' old names (a denied path in an intermediate commit
    reaches the base branch with a merge commit even when the net diff is clean). `shas` come from compare(), so the
    commit set is bound to the evaluated base/head pair; each detail read is addressed by SHA and must say so."""
    paths = set()
    for sha in shas:
        detail = gh_json(["gh", "api", f"repos/{repo}/commits/{sha}"])
        if not isinstance(detail, dict) or detail.get("sha") != sha:
            raise ValueError("a commit read does not match its SHA")
        files = detail.get("files")
        if not isinstance(files, list) or len(files) >= 300:
            raise ValueError("a commit's file list is missing or cut off")
        for x in files:
            if not isinstance(x, dict) or not isinstance(x.get("filename"), str):
                raise ValueError("a commit file has no name")
            paths.add(x["filename"])
            if x.get("previous_filename"):
                paths.add(str(x["previous_filename"]))
    return sorted(paths)


def fetch(gh_json, repo, number, head, project, ticket_refs=()):
    """{files, additions, deletions, modes, texts, truncated, errors, labels, labelsComplete, base{ref,sha}, head,
    history}. The base commit comes from the same read that confirms the head; the files, line counts and history
    come from the one pinned comparison of that pair (compare()), so nothing mixes two comparisons. verify()
    re-reads the pair right before the merge."""
    facts = {"files": None, "additions": None, "deletions": None, "modes": {}, "texts": {}, "truncated": False,
             "errors": [], "labels": [], "labelsComplete": False, "base": None, "head": head, "history": None}
    try:
        pull = gh_json(["gh", "api", f"repos/{repo}/pulls/{number}"])
        base_sha = ((pull.get("base") or {}).get("sha") or "")
        base_ref = (pull.get("base") or {}).get("ref")
        if (pull.get("head") or {}).get("sha") != head or not merge_policy.pipeline.SHA_RE.match(base_sha) \
                or not isinstance(base_ref, str):
            raise ValueError("the PR head moved or has no base commit")
        facts["base"] = {"ref": base_ref, "sha": base_sha}
        labels = _labels(pull, "the PR's")
        linked = gh_json(["gh", "pr", "view", str(number), "--repo", repo, "--json", "closingIssuesReferences"])
        if not isinstance(linked, dict) or not isinstance(linked.get("closingIssuesReferences"), list):
            raise ValueError("the linked issues could not be read")
        refs = references(repo, pull.get("body"), linked["closingIssuesReferences"], ticket_refs)
        if len(refs) > MAX_ISSUES:
            raise ValueError("too many referenced Issues to read")
        for slug, n in sorted(refs):
            labels += _labels(gh_json(["gh", "api", f"repos/{slug}/issues/{n}"]), f"Issue {slug}#{n}")
        facts.update(labels=labels, labelsComplete=True)
        files, shas = compare(gh_json, repo, base_sha, head)
        facts.update(files=files, additions=sum(x["additions"] for x in files),
                     deletions=sum(x["deletions"] for x in files))
        facts["history"] = history_paths(gh_json, repo, shas)
        trees = {side: gh_json(["gh", "api", f"repos/{repo}/git/trees/{sha}?recursive=1"])
                 for side, sha in (("base", base_sha), ("head", head))}
        facts["truncated"] = any(t.get("truncated") is not False for t in trees.values())
        modes = {side: _mode_map(t) for side, t in trees.items()}
        for f in files:
            facts["modes"][f["path"]] = {"base": modes["base"].get(f["path"]), "head": modes["head"].get(f["path"])}
        # The content rule reads the text of every changed non-test file at base and head (an ADDED file has no base).
        sides = {"base": base_sha, "head": head}
        for f in files:
            path = f["path"]
            if not merge_policy.safe_path(path) or merge_policy.is_test(project, path):
                continue
            entry = facts["texts"].setdefault(path, {})
            for side in ("head",) if f["changeType"] == "ADDED" else ("base", "head"):
                payload = gh_json(["gh", "api", f"repos/{repo}/contents/{quote(path)}?ref={sides[side]}"])
                entry[side] = merge_policy.text_of_contents(payload)
    except (OSError, ValueError, AttributeError, TypeError, KeyError) as e:
        facts["errors"].append(str(e)[:160] or type(e).__name__)
    return facts


def verify(gh_json, repo, number, facts):
    """Right before the merge: the PR still has the evaluated head, the evaluated base branch and the base commit the
    diff was judged against. A retarget with the same head changes the base (`gh pr merge --match-head-commit` guards
    only the head), so the merge waits and the next pass judges the new pair. Returns "" when it holds, else why."""
    try:
        pull = gh_json(["gh", "api", f"repos/{repo}/pulls/{number}"])
        base = pull.get("base") or {}
        want = facts.get("base") or {}
        if (pull.get("head") or {}).get("sha") != facts.get("head"):
            return "the PR head moved"
        if base.get("ref") != want.get("ref") or base.get("sha") != want.get("sha"):
            return "the PR's base branch or base commit changed"
    except (OSError, ValueError, AttributeError, TypeError):
        return "the PR could not be re-read"
    return ""


def landed(gh_json, repo, number, facts):
    """Right after the merge: whether it went into the evaluated base branch. GitHub's merge call takes a head
    precondition but no base one (CC-057 round 3), so a retarget in the moment between verify() and the write cannot
    be refused; it is caught here and raised to Jay instead. Returns "" when it landed as evaluated, else why."""
    try:
        pull = gh_json(["gh", "api", f"repos/{repo}/pulls/{number}"])
        ref = (pull.get("base") or {}).get("ref")
        if pull.get("merged") is not True:
            return "GitHub does not show the PR as merged"
        if ref != (facts.get("base") or {}).get("ref"):
            return f"the PR was merged into {str(ref)[:60]!r}, not the evaluated {(facts.get('base') or {}).get('ref')!r}"
    except (OSError, ValueError, AttributeError, TypeError):
        return "the merged PR could not be re-read to confirm its base branch"
    return ""
