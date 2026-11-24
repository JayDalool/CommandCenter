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
MAX_ISSUES = 10
MAX_COMMITS = 20


def references(repo, body, linked=(), ticket_refs=()):
    """{(owner/repo, number)} the PR points at: its body (URL, qualified, bare), GitHub's linked closing issues
    (`linked`: [{number, repository: {nameWithOwner}}]) and the ticket's own GitHub links (`ticket_refs`)."""
    text = str(body or "")
    out = {(m.group(1), int(m.group(2))) for m in URL_REF_RE.finditer(text)}
    text = URL_REF_RE.sub(" ", text)
    out |= {(m.group(1), int(m.group(2))) for m in QUAL_REF_RE.finditer(text)}
    text = QUAL_REF_RE.sub(" ", text)
    out |= {(repo, int(n)) for n in BARE_REF_RE.findall(text)}
    for x in linked if isinstance(linked, (list, tuple)) else ():
        r = ((x or {}).get("repository") or {}).get("nameWithOwner") or repo
        if not isinstance(x, dict) or not isinstance(x.get("number"), int):
            raise ValueError("a linked issue could not be read")
        out.add((r, x["number"]))
    for ref in ticket_refs:
        slug, _, num = str(ref).rpartition("#")
        if not num.isdigit():
            raise ValueError("a ticket link could not be read")
        out.add((slug or repo, int(num)))
    return out


def _mode_map(tree):
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise ValueError("no tree")
    return {e["path"]: e.get("mode") for e in tree["tree"] if isinstance(e, dict) and isinstance(e.get("path"), str)}


def history_paths(gh_json, repo, number):
    """Every path any commit of the PR touched, including renames' old names (a denied path in an intermediate commit
    reaches the base branch with a merge commit even when the net diff is clean). A PR with too many commits, a
    paginated list or a commit whose file list is cut off refuses."""
    commits = gh_json(["gh", "api", f"repos/{repo}/pulls/{number}/commits?per_page=100"])
    if not isinstance(commits, list) or not commits or len(commits) > MAX_COMMITS:
        raise ValueError("the PR's commit list is empty or too long to inspect")
    paths = set()
    for c in commits:
        sha = (c or {}).get("sha") if isinstance(c, dict) else None
        if not isinstance(sha, str) or not merge_policy.pipeline.SHA_RE.match(sha):
            raise ValueError("a commit has no SHA")
        detail = gh_json(["gh", "api", f"repos/{repo}/commits/{sha}"])
        files = detail.get("files") if isinstance(detail, dict) else None
        if not isinstance(files, list) or len(files) >= 300:
            raise ValueError("a commit's file list is missing or cut off")
        for x in files:
            if not isinstance(x, dict) or not isinstance(x.get("filename"), str):
                raise ValueError("a commit file has no name")
            paths.add(x["filename"])
            if x.get("previous_filename"):
                paths.add(str(x["previous_filename"]))
    return sorted(paths)


def fetch(gh_json, repo, number, head, files, project, ticket_refs=()):
    """{modes, texts, truncated, errors, labels, labelsComplete, base{ref,sha}, head, history} for the PR's `files`
    (the `gh pr view` list). Base ref and SHA come from the same pinned read as the head (a base retarget with the
    same head changes them); verify() compares them again right before the merge."""
    facts = {"modes": {}, "texts": {}, "truncated": False, "errors": [], "labels": [], "labelsComplete": False,
             "base": None, "head": head, "history": None}
    try:
        pull = gh_json(["gh", "api", f"repos/{repo}/pulls/{number}"])
        base_sha = ((pull.get("base") or {}).get("sha") or "")
        base_ref = (pull.get("base") or {}).get("ref")
        if (pull.get("head") or {}).get("sha") != head or not merge_policy.pipeline.SHA_RE.match(base_sha) \
                or not isinstance(base_ref, str):
            raise ValueError("the PR head moved or has no base commit")
        facts["base"] = {"ref": base_ref, "sha": base_sha}
        labels = [str(x.get("name")) for x in pull.get("labels") or [] if isinstance(x, dict)]
        linked = gh_json(["gh", "pr", "view", str(number), "--repo", repo, "--json", "closingIssuesReferences"])
        refs = references(repo, pull.get("body"), (linked or {}).get("closingIssuesReferences") or [], ticket_refs)
        if len(refs) > MAX_ISSUES:
            raise ValueError("too many referenced Issues to read")
        for slug, n in sorted(refs):
            issue = gh_json(["gh", "api", f"repos/{slug}/issues/{n}"])
            if not isinstance(issue.get("labels"), list):
                raise ValueError(f"Issue #{n} labels unreadable")
            labels += [str(x.get("name")) for x in issue["labels"] if isinstance(x, dict)]
        facts.update(labels=labels, labelsComplete=True)
        facts["history"] = history_paths(gh_json, repo, number)
        trees = {side: gh_json(["gh", "api", f"repos/{repo}/git/trees/{sha}?recursive=1"])
                 for side, sha in (("base", base_sha), ("head", head))}
        facts["truncated"] = any(t.get("truncated") is not False for t in trees.values())
        modes = {side: _mode_map(t) for side, t in trees.items()}
        for f in files if isinstance(files, list) else []:
            path = f.get("path") if isinstance(f, dict) else None
            if isinstance(path, str):
                facts["modes"][path] = {"base": modes["base"].get(path), "head": modes["head"].get(path)}
        # The content rule reads the text of every changed non-test file at base and head (an ADDED file has no base).
        shas = {"base": base_sha, "head": head}
        for f in files if isinstance(files, list) else []:
            path = f.get("path") if isinstance(f, dict) else None
            if not merge_policy.safe_path(path) or merge_policy.is_test(project, path):
                continue
            entry = facts["texts"].setdefault(path, {})
            for side in ("head",) if f.get("changeType") == "ADDED" else ("base", "head"):
                payload = gh_json(["gh", "api", f"repos/{repo}/contents/{quote(path)}?ref={shas[side]}"])
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
