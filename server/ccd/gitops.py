"""Source control for the Workspace: status, diff, stage, unstage, discard, commit, branch.

Runs plain `git` in a registered root only, with no pager, no prompts and a
timeout. Paths from the browser go through files.split_rel and the protected-
name rules before they reach git, and are passed after `--` with
:(literal) pathspecs, so a path can never be read as an option or a glob.

What is deliberately not here: push, pull, fetch, reset, rebase, checkout of
another branch over local changes, force anything, history rewriting, hooks
bypass (--no-verify), config changes. A commit is a normal `git commit`.
"""
import asyncio
import contextlib
import os
import re

from .files import FileError, is_protected_name, split_rel

TIMEOUT = 20.0
DIFF_MAX = 512 * 1024
DIFF_FILE_MAX = 10 * 1024 * 1024  # git diff loads the whole file (both sides) into its own memory
ERR_MAX = 64 * 1024
BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)(?!.*@\{)(?!.*\.lock$)(?!.*/$)[A-Za-z0-9._/-]{1,120}$")
STATUS_WORD = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "typechange",
               "U": "conflict", "?": "untracked"}


def _env():
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", PAGER="cat", LC_ALL="C", GIT_OPTIONAL_LOCKS="0",
               GIT_EDITOR="false")
    return env


async def git(root, *args, input_bytes=None, ok=(0,), limit=DIFF_MAX):
    """Run git; return (stdout up to `limit` bytes, truncated). Output is read in chunks and git is
    stopped once it passes the limit, so a huge diff or status never sits whole in ccd's memory
    (ccd and its git children share one MemoryMax cgroup)."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", root, "-c", "core.quotepath=off", "-c", "color.ui=false", *args, env=_env(),
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = bytearray(), bytearray()

    async def feed():
        if input_bytes is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.write(input_bytes)
                await proc.stdin.drain()
            proc.stdin.close()

    async def read_out():
        while len(out) <= limit:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                return False
            out.extend(chunk)
        return True

    async def read_err():
        while chunk := await proc.stderr.read(65536):
            if len(err) < ERR_MAX:
                err.extend(chunk[:ERR_MAX - len(err)])

    async def run():
        _, cut = await asyncio.gather(feed(), read_out())
        if not cut:
            await proc.wait()
        return cut

    errs = asyncio.ensure_future(read_err())
    truncated = None  # None: timed out (or cancelled); True: we stopped git at the limit
    try:
        truncated = await asyncio.wait_for(run(), TIMEOUT)
    except asyncio.TimeoutError:
        pass
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()
        await errs
    if truncated is None:
        raise FileError(504, "git took too long")
    if not truncated and proc.returncode not in ok:
        msg = err.decode("utf-8", "replace").strip().splitlines()
        raise FileError(409, (msg[-1] if msg else f"git exited {proc.returncode}")[:300])
    return bytes(out[:limit]), truncated


def _path(rel):
    parts = split_rel(rel)
    if not parts:
        raise FileError(400, "bad path")
    if any(p.lower() == ".git" or is_protected_name(p) for p in parts):
        raise FileError(403, "protected file", protected=True)
    return "/".join(parts)


def _spec(path):
    return f":(literal){path}"


class SourceControl:
    def __init__(self, roots):
        self.roots = roots  # files.Roots
        self._lock = asyncio.Lock()

    async def _file(self, key, rel):
        """One FILE path (it may no longer exist: a deletion). A folder is refused: a folder
        pathspec would reach protected files inside it, for diff, stage or discard alike. A
        folder deleted from disk but still tracked is a folder too, so git itself is asked what
        the pathspec matches — in the index, in HEAD and on disk — and it must be this path alone."""
        path = _path(rel)
        root = self.roots.root(key)
        if os.path.isdir(os.path.join(root, path)):
            raise FileError(400, "source control acts on single files; pick a file, not a folder")
        spec = _spec(path)
        listed = set()
        out, _ = await git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", spec,
                           limit=1024 * 1024)
        listed |= {p for p in out.decode("utf-8", "replace").split("\x00") if p}
        out, _ = await git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", spec, ok=(0, 128),
                           limit=1024 * 1024)
        listed |= {p for p in out.decode("utf-8", "replace").split("\x00") if p}
        if listed - {path}:
            raise FileError(400, "source control acts on single files; that path is a folder")
        return path

    async def status(self, key):
        root = self.roots.root(key)
        out, _ = await git(root, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all",
                           limit=4 * 1024 * 1024)
        branch = {"head": None, "upstream": None, "ahead": 0, "behind": 0, "oid": None}
        staged, unstaged, untracked, conflicts = [], [], [], []
        items = out.decode("utf-8", "replace").split("\x00")
        i = 0
        while i < len(items):
            line = items[i]
            i += 1
            if not line:
                continue
            if line.startswith("# branch.head "):
                branch["head"] = line[14:]
            elif line.startswith("# branch.oid "):
                branch["oid"] = line[13:]
            elif line.startswith("# branch.upstream "):
                branch["upstream"] = line[18:]
            elif line.startswith("# branch.ab "):
                m = re.match(r"# branch.ab \+(\d+) -(\d+)", line)
                if m:
                    branch["ahead"], branch["behind"] = int(m.group(1)), int(m.group(2))
            elif line[0] in "12":
                f = line.split(" ")
                xy = f[1]
                if line[0] == "1":
                    path = line.split(" ", 8)[8]
                    orig = None
                else:
                    path = line.split(" ", 9)[9]
                    orig = items[i]
                    i += 1
                row = {"path": path, "orig": orig, "protected": any(is_protected_name(p) for p in path.split("/"))}
                if xy[0] != ".":
                    staged.append({**row, "code": xy[0], "status": STATUS_WORD.get(xy[0], xy[0])})
                if xy[1] != ".":
                    unstaged.append({**row, "code": xy[1], "status": STATUS_WORD.get(xy[1], xy[1])})
            elif line[0] == "u":
                path = line.split(" ", 10)[10]
                conflicts.append({"path": path, "code": "U", "status": "conflict", "orig": None,
                                  "protected": any(is_protected_name(p) for p in path.split("/"))})
            elif line[0] == "?":
                path = line[2:]
                untracked.append({"path": path, "code": "?", "status": "untracked", "orig": None,
                                  "protected": any(is_protected_name(p) for p in path.split("/"))})
        return {"project": key, "branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked,
                "conflicts": conflicts,
                "clean": not (staged or unstaged or untracked or conflicts)}

    async def _largest(self, key, root, path):
        """Largest size of this path on disk, in the index and in HEAD (bytes, 0 if absent)."""
        sizes = [0]
        try:
            _, full, _ = self.roots.resolve(key, path)
            if os.path.isfile(full) and not os.path.islink(os.path.join(root, path)):
                sizes.append(os.path.getsize(full))
        except (FileError, OSError):
            pass
        out, _ = await git(root, "ls-files", "-s", "-z", "--", _spec(path))
        for entry in out.split(b"\x00"):
            if entry:  # "<mode> <sha> <stage>\t<path>"
                sha = entry.split(b" ")[1].decode()
                size, _ = await git(root, "cat-file", "-s", sha)
                sizes.append(int(size or 0))
        out, _ = await git(root, "ls-tree", "-l", "-z", "HEAD", "--", _spec(path), ok=(0, 128))
        for entry in out.split(b"\x00"):
            if entry:  # "<mode> blob <sha> <size>\t<path>"
                size = entry.split(b"\t")[0].split()[-1]
                sizes.append(int(size) if size.isdigit() else 0)
        return max(sizes)

    async def diff(self, key, rel, staged=False):
        root = self.roots.root(key)
        path = await self._file(key, rel)
        size = await self._largest(key, root, path)
        if size > DIFF_FILE_MAX:
            # git diff would load the whole file into memory inside ccd's cgroup; show nothing instead
            return {"project": key, "path": path, "staged": staged, "diff": "", "truncated": False, "binary": False,
                    "tooLarge": size}
        args = ["diff", "--no-ext-diff", "--no-color", "--find-renames"]
        if staged:
            args.append("--cached")
        out, truncated = await git(root, *args, "--", _spec(path))
        text = out.decode("utf-8", "replace")
        if not text and not staged:
            # untracked: show the whole file as added (git diff --no-index exits 1 when different)
            try:
                _, full, _ = self.roots.resolve(key, path)  # inside the root, after symlinks
            except FileError:
                full = None
            if full and os.path.isfile(full) and not os.path.islink(os.path.join(root, path)):
                out, truncated = await git(root, "diff", "--no-color", "--no-index", "--", "/dev/null", path,
                                           ok=(0, 1))
                text = out.decode("utf-8", "replace")
        binary = "Binary files" in text[:2000] and "differ" in text[:2000]
        return {"project": key, "path": path, "staged": staged, "diff": text, "truncated": truncated, "binary": binary,
                "tooLarge": None}

    async def stage(self, key, paths):
        root = self.roots.root(key)
        clean = [await self._file(key, p) for p in paths[:500]]
        if not clean:
            raise FileError(400, "nothing to stage")
        async with self._lock:
            await git(root, "add", "--", *[_spec(p) for p in clean])
        return {"ok": True, "staged": clean}

    async def stage_all(self, key):
        """Stage every changed, non-protected path listed by status. Never `git add -A`, so a
        secret-looking file that is not gitignored is not swept in."""
        st = await self.status(key)
        paths = sorted({r["path"] for r in st["unstaged"] + st["untracked"] if not r["protected"]})
        if not paths:
            return {"ok": True, "staged": []}
        return await self.stage(key, paths)

    async def unstage(self, key, paths):
        root = self.roots.root(key)
        clean = [await self._file(key, p) for p in paths[:500]]
        if not clean:
            raise FileError(400, "nothing to unstage")
        # A staged rename/copy is two index entries: unstage the original path too.
        st = await self.status(key)
        for r in st["staged"]:
            if r["path"] in clean and r.get("orig") and r["orig"] not in clean:
                clean.append(_path(r["orig"]))
        async with self._lock:
            head_ok = True
            try:
                await git(root, "rev-parse", "--verify", "HEAD")
            except FileError:
                head_ok = False
            if head_ok:
                await git(root, "restore", "--staged", "--", *[_spec(p) for p in clean])
            else:
                await git(root, "rm", "--cached", "--quiet", "--", *[_spec(p) for p in clean])
        return {"ok": True, "unstaged": clean}

    async def discard(self, key, rel, files):
        """Throw away unstaged changes to one path. Tracked: restore from the index.
        Untracked: delete the file (descriptor-safe, via files.Roots.delete). The UI confirms first."""
        root = self.roots.root(key)
        path = await self._file(key, rel)
        async with self._lock:
            out, _ = await git(root, "ls-files", "--error-unmatch", "--", _spec(path), ok=(0, 1))
            if out.strip():
                await git(root, "restore", "--worktree", "--", _spec(path))
                return {"ok": True, "path": path, "discarded": "changes"}
        files.delete(key, path)
        return {"ok": True, "path": path, "discarded": "untracked file"}

    async def commit(self, key, message, expect):
        """A normal commit of what is staged. `expect` is the list of staged paths the user saw;
        if the index changed since, the commit is refused."""
        if not isinstance(message, str) or not message.strip() or len(message) > 10000 or "\x00" in message:
            raise FileError(400, "a commit message is required")
        root = self.roots.root(key)
        async with self._lock:
            st = await self.status(key)
            staged = sorted({r["path"] for r in st["staged"]})
            if not staged:
                raise FileError(409, "nothing is staged")
            if sorted(set(expect or [])) != staged:
                raise FileError(409, "the staged files changed; review them again", staged=staged)
            await git(root, "commit", "--quiet", "--file=-", input_bytes=message.encode("utf-8"))
            out, _ = await git(root, "rev-parse", "HEAD")
        return {"ok": True, "sha": out.decode().strip(), "files": staged}

    async def branches(self, key):
        root = self.roots.root(key)
        out, _ = await git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads", limit=1024 * 1024)
        return [b for b in out.decode("utf-8", "replace").splitlines() if b]

    async def create_branch(self, key, name, switch=True):
        """Create a branch at HEAD. `switch` uses `git switch -c`, which carries local changes
        along and never overwrites them. Switching to an EXISTING branch is not offered here."""
        if not isinstance(name, str) or not BRANCH_RE.match(name):
            raise FileError(400, "bad branch name")
        root = self.roots.root(key)
        async with self._lock:
            await git(root, "check-ref-format", "--branch", name)
            if name in await self.branches(key):
                raise FileError(409, f"branch {name} already exists", exists=True)
            if switch:
                await git(root, "switch", "--quiet", "-c", name)
            else:
                await git(root, "branch", "--", name)
        return {"ok": True, "branch": name, "switched": bool(switch)}


def ticket_branch_name(key, title):
    """SV-056 + 'Valuation view!' → SV-056-valuation-view (deterministic, ≤ 60 chars)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    words, out = slug.split("-"), []
    for w in words:
        if len("-".join(out + [w])) > 40:
            break
        out.append(w)
    tail = "-".join(out)
    return f"{key}-{tail}" if tail else key
