"""Remove a DONE ticket's worktree, but only when nothing can be lost (CC-024).

ccd's git poll hands this module every DONE ticket that still has a recorded
worktree. A worktree is removed only when ALL of these hold; otherwise it is kept
and the first failing check is returned as the reason:

  1. the path is strictly inside /srv/server/worktrees/ or <project root>/.claude/worktrees/,
     and no component below those roots is a symlink
  2. git lists it as a linked worktree of the ticket's repo: not the main checkout, not locked
  3. the ticket's own branch is checked out there (a Claude Code `agent-*` worktree never matches)
  4. `git status` is empty: nothing modified, staged or untracked; no file hidden from status
     (skip-worktree, assume-unchanged); no merge/rebase in progress; no other worktree nested inside it
     and no `.git` entry or bare repository anywhere below it (git shows nothing inside those, and
     `worktree remove` would delete them with their uncommitted work)
  5. no commit of the worktree is missing from every remote (ccd never fetches, so a stale
     remote ref can only make this keep more), and none that only the worktree's own HEAD reflog or
     refs/worktree/* hold (those go with it)
  6. no herdr pane and no process has its working directory inside it, and herdr answered
     (a pane list ccd cannot see is a reason to wait)

The one thing that runs is `git -C <repo> worktree remove <path>`: never --force, never rm,
never a branch delete. Ignored files (node_modules, .venv) go with the directory; the branch and
its commits stay, so `git worktree add <path> <branch>` brings the work back.
"""
import os
import subprocess

WORKTREES_ROOT = "/srv/server/worktrees"
GIT_TIMEOUT = 30
SCAN_LIMIT = 200000  # folders visited when looking for a repository git cannot see
REMOVE_TIMEOUT = 300


def _env():
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", PAGER="cat", LC_ALL="C", GIT_OPTIONAL_LOCKS="0",
               GIT_EDITOR="false")
    return env


def _git(cwd, *args, timeout=GIT_TIMEOUT):
    """(exit code, stdout, last stderr line). A missing git or a timeout is a non-zero code.

    Output is bytes decoded with surrogateescape, so a file name that is not UTF-8 survives a round trip to
    os.walk and friends; the stderr line is decoded with replacement because it ends up in an event."""
    try:
        r = subprocess.run(["git", "-C", cwd, "-c", "core.quotepath=off", *args], capture_output=True,
                           timeout=timeout, env=_env(), stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "git took too long"
    err = r.stderr.decode("utf-8", "replace").strip().splitlines()
    return r.returncode, r.stdout.decode("utf-8", "surrogateescape"), (err[-1] if err else "")[:200]


def _inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def path_problem(repo, path, root=None):
    """Why `path` may not be removed by ccd, or None when it sits where ticket worktrees live."""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        return "its recorded path is not an absolute path"
    norm = os.path.normpath(path)
    for anchor, base in ((root or WORKTREES_ROOT,) * 2, (repo, os.path.join(repo, ".claude", "worktrees"))):
        if norm.startswith(base.rstrip("/") + "/"):
            break
    else:
        return "it is outside the worktree folders"
    # Every component from the anchor down must be a real directory entry, not a link.
    cur = anchor
    for part in norm[len(anchor.rstrip("/")):].split("/"):
        if not part:
            continue
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            return "its path goes through a symlink"
    if os.path.realpath(norm) != norm:
        return "its path goes through a symlink"
    return None


def list_worktrees(repo):
    """`git worktree list --porcelain` as [{path, branch, locked}], the main checkout first. None on error."""
    code, out, _ = _git(repo, "worktree", "list", "--porcelain")
    if code != 0:
        return None
    rows, cur = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "branch": None, "locked": False, "bare": False}
            rows.append(cur)
        elif cur is not None:
            if line.startswith("branch "):
                cur["branch"] = line[len("branch "):]
            elif line == "locked" or line.startswith("locked "):
                cur["locked"] = True
            elif line == "bare":
                cur["bare"] = True
    return rows


IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply",
               "sequencer")


def hidden_from_status(real):
    """Why `git status` cannot be trusted to show everything, or None.

    A tracked file flagged skip-worktree (sparse checkout) or assume-unchanged is never compared with the
    index, so an edit to it is invisible to status and to git's own check in `worktree remove`.
    `ls-files -v` marks those with `S` or a lowercase letter. An unfinished merge, cherry-pick, revert, rebase
    or bisect lives in the worktree's own git folder and is deleted with it, whatever status says."""
    code, out, err = _git(real, "ls-files", "-v", "-z")
    if code != 0:
        return f"git ls-files failed: {err}"
    for entry in out.split("\x00"):
        if entry and (entry[0] == "S" or entry[0].islower()):
            return "it has files hidden from git status (skip-worktree or assume-unchanged)"
    code, out, err = _git(real, "rev-parse", "--absolute-git-dir")
    if code != 0:
        return f"git rev-parse failed: {err}"
    gitdir = out.strip()
    if any(os.path.lexists(os.path.join(gitdir, name)) for name in IN_PROGRESS):
        return "a merge, rebase, cherry-pick, revert or bisect is in progress"
    return None


def unshared_commits(real):
    """Why a commit would be lost with this worktree's own git folder, or None.

    The worktree's HEAD reflog and its `refs/worktree/*` refs are deleted with it. Every commit named there
    must be reachable from a branch, tag or remote ref, which stay. A commit that only a branch reflog also
    names (an amend, reset or rebase on the branch) is skipped: that reflog is shared and stays."""
    code, out, err = _git(real, "reflog", "--format=%H", "HEAD")
    if code != 0:
        return f"git reflog failed: {err}"
    tips = set(out.split())
    code, out, err = _git(real, "for-each-ref", "--format=%(objectname) %(objecttype)", "refs/worktree/")
    if code != 0:
        return f"git for-each-ref failed: {err}"
    for line in out.splitlines():
        sha, _, kind = line.partition(" ")
        if kind != "commit":
            return "refs/worktree holds something that is not a commit"
        tips.add(sha)
    if not tips:
        return None
    code, out, err = _git(real, "log", "-g", "--branches", "--format=%H")
    if code != 0:
        return f"git reflog of the branches failed: {err}"
    tips -= set(out.split())
    tips = sorted(tips)
    for i in range(0, len(tips), 400):
        code, out, err = _git(real, "rev-list", "--ignore-missing", "-n", "1", *tips[i:i + 400],
                              "--not", "--branches", "--tags", "--remotes")
        if code != 0:
            return f"git rev-list failed: {err}"
        if out.strip():
            return "it has commits that only its own reflog or refs/worktree hold"
    return None


def hidden_repo(real):
    """Why part of the worktree may hold work git cannot see, or None. One walk of the whole tree.

    `git worktree remove` looks at tracked and untracked files but deletes the rest unseen, and git shows
    nothing inside a folder named `.git`. So the tree is walked (symlinks not followed) and ANY entry named
    `.git` (a folder, a gitfile, a symlink, in a tracked, untracked or ignored folder, however deep or empty
    its parent) keeps the worktree, as does any folder shaped like a bare repository (HEAD + objects/ + refs/).
    That covers a Claude Code subagent's worktree, a nested clone, a backup repo and a stray `.git` folder.
    The worktree's own `.git` gitfile at the top is expected and skipped. Plain files (node_modules, .venv)
    only cost walk time. A walk that cannot finish (unreadable folder, more than SCAN_LIMIT folders) keeps it."""
    seen = 0
    unreadable = []
    for here, dirs, files in os.walk(real, followlinks=False, onerror=unreadable.append):
        seen += 1
        names = set(dirs) | set(files)
        if ".git" in names and here != real:
            return "it holds a .git (a nested repository or worktree) inside"
        if "HEAD" in files and "objects" in dirs and "refs" in dirs:
            return "it holds a bare git repository inside"
        if seen > SCAN_LIMIT:
            return "it has too many folders to check for nested repositories"
    if unreadable:
        return "a folder could not be read, so nested repositories cannot be ruled out"
    return None


def processes_inside(path, proc="/proc"):
    """True when any process's working directory is inside `path`. Processes we cannot read are skipped."""
    try:
        pids = [d for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return None  # cannot look: the caller keeps the worktree
    for pid in pids:
        try:
            cwd = os.readlink(os.path.join(proc, pid, "cwd"))
        except OSError:
            continue
        if _inside(cwd, path):
            return True
    return False


def blocker(repo, path, branch, pane_cwds, *, root=None, proc="/proc"):
    """The first reason this worktree must stay, or None when it is safe to remove.

    `pane_cwds` is every herdr pane's working directory, or None when herdr is not connected."""
    if not branch:
        return "the ticket has no recorded branch"
    why = path_problem(repo, path, root)
    if why:
        return why
    rows = list_worktrees(repo)
    if rows is None:
        return "git could not list the repo's worktrees"
    real = os.path.realpath(path)
    mine = next((r for r in rows if os.path.realpath(r["path"]) == real), None)
    if mine is None:
        return "it is not a registered worktree of the repo"
    if rows[0] is mine or mine.get("bare"):
        return "it is the main checkout"
    if mine["locked"]:
        return "it is locked"
    if any(r is not mine and _inside(os.path.realpath(r["path"]), real) for r in rows):
        return "another worktree is nested inside it"
    if mine["branch"] != f"refs/heads/{branch}":
        return f"{branch} is not the branch checked out there"
    why = _cheap(real, path, pane_cwds, proc)
    if why:
        return why
    # The whole-tree walk is the slow one, so it comes after every cheap check (it must not repeat on
    # each poll while a pane is open). The cheap ones then run once more right before the caller removes.
    why = hidden_repo(real)
    if why:
        return why
    return _cheap(real, path, pane_cwds, proc)


def _cheap(real, path, pane_cwds, proc):
    """The quick checks of a worktree's contents and users, run before and again after the slow walk."""
    code, out, err = _git(real, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none")
    if code != 0:
        return f"git status failed: {err}"
    if out.strip():
        return "it has changed or untracked files"
    why = hidden_from_status(real)
    if why:
        return why
    code, out, err = _git(real, "rev-list", "HEAD", "--not", "--remotes", "-n", "1")
    if code != 0:
        return f"git rev-list failed: {err}"
    if out.strip():
        return "it has commits that are on no remote"
    why = unshared_commits(real)
    if why:
        return why
    if pane_cwds is None:
        return "herdr is not connected, so open panes cannot be checked"
    for cwd in pane_cwds:
        if cwd and (_inside(cwd, real) or _inside(cwd, path)):
            return "a herdr pane is open inside it"
    found = processes_inside(real, proc)
    if found is None:
        return "running processes could not be checked"
    if found:
        return "a process is running inside it"
    return None


def remove(repo, path):
    """`git worktree remove <path>`, nothing else. (ok, error text)."""
    code, _, err = _git(repo, "worktree", "remove", os.path.normpath(path), timeout=REMOVE_TIMEOUT)
    return code == 0, err


def run(items, pane_cwds, *, root=None, proc="/proc"):
    """items: [(key, project, repo, branch, path)] → [(key, project, path, "removed"|"kept", reason)].

    Paths that no longer exist produce nothing (already gone). Blocking: call it in a thread."""
    out = []
    for key, project, repo, branch, path in items:
        if not isinstance(path, str) or not os.path.lexists(path):
            continue
        if not repo or not os.path.isdir(repo):
            out.append((key, project, path, "kept", "the project has no checkout on this server"))
            continue
        try:
            why = blocker(repo, path, branch, pane_cwds, root=root, proc=proc)
            if why is None:
                ok, err = remove(repo, path)
                if ok:
                    out.append((key, project, path, "removed", None))
                    continue
                why = f"git refused to remove it: {err}"
        except Exception as e:  # noqa: BLE001 — one ticket's failure must not stop the others or lose their results
            why = f"the checks failed with {type(e).__name__}"
        out.append((key, project, path, "kept", why))
    return out
