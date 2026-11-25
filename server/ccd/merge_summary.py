"""The three-line summary in a merge DM (CC-057 c8): what changed, what it achieved, which sensitive areas it touched.

Pure and display-only: it formats facts the caller already read and never decides or authorises a merge. A GitHub
read that failed, or that is for another head than the DM shows, is said in the text ("files could not be read at this
head"), so Jay sees the gap instead of an empty list that looks safe."""
import fnmatch

MAX_PATHS = 6
UNREAD = "files could not be read at this head; check the PR"


def sensitive_paths(files, patterns):
    """Changed paths that match any pattern. fnmatch's `*` also crosses `/`, so this over-reports (a `**/x/**` rule
    also matches `src/x/a/b.py`, and a rule with a leading `**/` matches at the repo root too): a longer list only
    makes Jay look closer, a shorter one could hide a sensitive file."""
    out = []
    for f in files:
        for pat in patterns:
            if fnmatch.fnmatchcase(f, pat) or (pat.startswith("**/") and fnmatch.fnmatchcase(f, pat[3:])):
                out.append(f)
                break
    return out


def achieved(criteria, head):
    """'criteria 5/6 passed at this head, c8 open': a pass counts only when it was recorded at this head."""
    crit = [c for c in criteria or [] if isinstance(c, dict)]
    if not crit:
        return "no acceptance criteria recorded"
    ok = [c for c in crit if c.get("state") == "pass" and c.get("head") == head]
    rest = [str(c.get("id")) + (" failed" if c.get("state") == "fail" else " open") for c in crit if c not in ok]
    return f"criteria {len(ok)}/{len(crit)} passed at this head" + (", " + ", ".join(rest) if rest else "")


def lines(*, title, done, criteria, head, pr_facts, patterns, security):
    """`pr_facts` is {files, additions, deletions} read at `head`, or None when the read failed or was for another
    head. `security` is 'required, present', 'required, missing' or 'not required'."""
    if pr_facts is None:
        size = UNREAD
    else:
        size = f"{len(pr_facts['files'])} files, +{pr_facts['additions']}/-{pr_facts['deletions']}"
    changed = f"*Changed:* {title or 'linked PR'} ({size})"
    if done:
        changed += f" · {done}"
    if pr_facts is None:
        sens = UNREAD
    else:
        hits = sensitive_paths(pr_facts["files"], patterns)
        sens = (", ".join(hits[:MAX_PATHS]) + (f" and {len(hits) - MAX_PATHS} more" if len(hits) > MAX_PATHS else "")
                if hits else "none of the protected or personal-data paths")
    return [changed[:600], f"*Achieved:* {achieved(criteria, head)}",
            f"*Sensitive:* {sens} · security sign-off: {security}"]
