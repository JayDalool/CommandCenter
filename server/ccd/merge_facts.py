"""What ccd reads from GitHub right before it merges (CC-057), as one `facts` dict for merge_policy.classify.

Every read is pinned to a commit SHA (the PR head and its base commit), so the answer cannot change under the
reviewed head. Any failure, a truncated tree, a paginated list or a file the contents API sends without text goes
into `errors` and the classifier refuses; nothing here ever reads a gap as an empty file. Blocking: run it in a
thread (`asyncio.to_thread`). `gh_json(args)` runs gh and returns parsed JSON or raises OSError/ValueError.
"""
import re
from urllib.parse import quote

from . import merge_policy

ISSUE_REF_RE = re.compile(r"(?<![\w/])#(\d{1,7})\b")
MAX_ISSUES = 10


def _mode_map(tree):
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise ValueError("no tree")
    return {e["path"]: e.get("mode") for e in tree["tree"] if isinstance(e, dict) and isinstance(e.get("path"), str)}


def fetch(gh_json, repo, number, head, files, project):
    """{modes, texts, truncated, errors, labels, labelsComplete} for the PR's `files` (the `gh pr view` list)."""
    facts = {"modes": {}, "texts": {}, "truncated": False, "errors": [], "labels": [], "labelsComplete": False}
    try:
        pull = gh_json(["gh", "api", f"repos/{repo}/pulls/{number}"])
        base_sha = ((pull.get("base") or {}).get("sha") or "")
        if (pull.get("head") or {}).get("sha") != head or not merge_policy.pipeline.SHA_RE.match(base_sha):
            raise ValueError("the PR head moved or has no base commit")
        labels = [str(x.get("name")) for x in pull.get("labels") or [] if isinstance(x, dict)]
        # Every Issue the PR body references: its labels count too (a risk label on the Issue stops the merge).
        issues = sorted(set(ISSUE_REF_RE.findall(str(pull.get("body") or ""))), key=int)
        if len(issues) > MAX_ISSUES:
            raise ValueError("too many referenced Issues to read")
        for n in issues:
            issue = gh_json(["gh", "api", f"repos/{repo}/issues/{n}"])
            if not isinstance(issue.get("labels"), list):
                raise ValueError(f"Issue #{n} labels unreadable")
            labels += [str(x.get("name")) for x in issue["labels"] if isinstance(x, dict)]
        facts.update(labels=labels, labelsComplete=True)
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
