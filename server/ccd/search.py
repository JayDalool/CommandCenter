"""Go to File and Search in Project, inside a registered root only.

Both run ripgrep on demand (never a background crawl), with no symlink
following, .gitignore respected, and these always excluded: .git, node_modules,
build output, virtualenvs and caches (EXCLUDE_DIRS), plus every protected
secret name (files.is_protected_name). Results are bounded and each run has a
hard timeout; the browser cancels by aborting its request.
"""
import asyncio
import json
import os
import shutil
import time

from .files import FileError, is_protected_name

EXCLUDE_DIRS = (".git", "node_modules", "dist", "build", "out", ".next", ".nuxt", ".venv", "venv", "__pycache__",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", "coverage", "target", ".turbo",
                ".gradle", "vendor", ".terraform", ".idea", ".vscode-test")
FILES_MAX = 50000
MATCH_MAX = 500
QUERY_MAX = 300
TIMEOUT = 10.0
FILE_CACHE_S = 30


def _rg():
    return shutil.which("rg")


def _globs():
    out = []
    for d in EXCLUDE_DIRS:
        out += ["-g", f"!**/{d}/**", "-g", f"!{d}/"]
    # protected names: the same lists files.py enforces
    for pat in ("*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx", "*.gpg", "*.asc", "*.token",
                ".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".npmrc", ".pypirc",
                ".git-credentials", ".pgpass", ".htpasswd", "credentials", "credentials.json", "token", "token.txt",
                "secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml", "**/.ssh/**", "**/.gnupg/**",
                "**/.aws/**", "**/.azure/**", "**/.kube/**", "**/.docker/**", "**/.password-store/**"):
        out += ["--iglob", f"!{pat}"]
    # dotenv variants are dropped after the search by is_protected_name, which keeps the
    # example/sample/template/dist family; a positive glob here would restrict the search to those.
    return out


async def _run(args, cwd, limit_bytes=8 * 1024 * 1024):
    proc = await asyncio.create_subprocess_exec(*args, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
    out = bytearray()
    truncated = False
    try:
        async def read():
            nonlocal truncated
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                out.extend(chunk)
                if len(out) > limit_bytes:
                    truncated = True
                    break
        await asyncio.wait_for(read(), TIMEOUT)
    except asyncio.TimeoutError:
        truncated = True
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()
    return bytes(out), truncated


def _excluded(path):
    parts = path.split("/")
    return any(p in EXCLUDE_DIRS or p.lower() == ".git" or is_protected_name(p) for p in parts)


async def _git_files(root):
    """Tracked + untracked-not-ignored files, via git (respects .gitignore). Fallback when rg is absent."""
    raw, truncated = await _run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                root)
    return [p for p in raw.decode("utf-8", "replace").split("\x00") if p], truncated


def _py_grep(root, paths, query, case, glob):
    """Bounded FIXED-STRING search in Python (the fallback when ripgrep is absent): no symlinks
    followed, ≤ 2 MB per file, ≤ 10 hits per line, MATCH_MAX hits, TIMEOUT seconds. Plain substring
    search is linear; a user regex is never run in-process, where backtracking would hold the GIL."""
    import fnmatch
    smart = case or query != query.lower()
    needle = query if smart else query.lower()
    deadline = time.monotonic() + TIMEOUT
    matches, files, truncated = [], set(), False
    for rel in paths:
        if time.monotonic() > deadline:
            truncated = True
            break
        if glob and not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(rel.rsplit("/", 1)[-1], glob):
            continue
        full = os.path.join(root, rel)
        try:
            if os.path.islink(full) or not os.path.isfile(full) or os.path.getsize(full) > 2 * 1024 * 1024:
                continue
            real = os.path.realpath(full)
            if not real.startswith(root + os.sep):
                continue
            with open(real, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if b"\x00" in data[:8192]:
            continue
        per_file = 0
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if time.monotonic() > deadline:
                return matches, files, True
            hay = line if smart else line.lower()
            at = hay.find(needle)
            if at < 0:
                continue
            ranges = []
            while at >= 0 and len(ranges) < 10:
                ranges.append((at, at + len(needle)))
                at = hay.find(needle, at + max(1, len(needle)))
            matches.append({"path": rel, "line": n, "text": line[:400], "ranges": ranges})
            files.add(rel)
            per_file += 1
            if per_file >= 50:
                break
            if len(matches) >= MATCH_MAX:
                return matches, files, True
    return matches, files, truncated


class Search:
    def __init__(self, roots):
        self.roots = roots  # files.Roots
        self._files = {}

    async def files(self, key):
        """Every searchable file path in the project (relative), for client-side fuzzy Go to File."""
        root = self.roots.root(key)
        hit = self._files.get(key)
        if hit and time.monotonic() - hit[0] < FILE_CACHE_S:
            return hit[1]
        rg = _rg()
        if rg:
            raw, truncated = await _run([rg, "--files", "--hidden", "--no-follow", "--no-messages", *_globs()], root)
            listed = raw.decode("utf-8", "replace").splitlines()
        else:
            listed, truncated = await _git_files(root)
            listed = [p for p in listed if not _excluded(p)]
        paths = []
        for line in listed:
            if not line or any(is_protected_name(p) or p.lower() == ".git" for p in line.split("/")):
                continue
            paths.append(line)
            if len(paths) >= FILES_MAX:
                truncated = True
                break
        paths.sort()
        out = {"project": key, "files": paths, "truncated": truncated}
        self._files[key] = (time.monotonic(), out)
        return out

    async def text(self, key, query, *, regex=False, case=False, glob=None):
        root = self.roots.root(key)
        if not isinstance(query, str) or not query or len(query) > QUERY_MAX or "\x00" in query:
            raise FileError(400, f"query must be 1–{QUERY_MAX} characters")
        if glob and (not isinstance(glob, str) or len(glob) > 100 or glob.startswith("!") or ".." in glob):
            raise FileError(400, "bad file filter")
        rg = _rg()
        if not rg:
            if regex:
                raise FileError(400, "regular-expression search needs ripgrep on the server; plain text search works")
            listed, _ = await _git_files(root)
            listed = [p for p in listed if not _excluded(p)]
            m, f, truncated = await asyncio.to_thread(_py_grep, os.path.realpath(root), listed, query, case,
                                                      glob or None)
            return {"project": key, "query": query, "matches": m, "files": len(f), "truncated": truncated,
                    "engine": "python"}
        args = [rg, "--json", "--hidden", "--no-follow", "--no-messages", "--max-filesize", "2M",
                "--max-count", "50", "--max-columns", "400", "--max-columns-preview", *_globs()]
        args += ["--case-sensitive"] if case else ["--smart-case"]
        if not regex:
            args.append("--fixed-strings")
        if glob:
            if not isinstance(glob, str) or len(glob) > 100 or glob.startswith("!") or ".." in glob:
                raise FileError(400, "bad file filter")
            args += ["-g", glob]
        args += ["--regexp", query, "--", "."]
        raw, truncated = await _run(args, root)
        matches, files = [], set()
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "match":
                continue
            d = ev["data"]
            path = (d.get("path") or {}).get("text") or ""
            path = path[2:] if path.startswith("./") else path
            if not path or any(is_protected_name(p) or p.lower() == ".git" for p in path.split("/")):
                continue
            text = (d.get("lines") or {}).get("text") or ""
            subs = [(m["start"], m["end"]) for m in d.get("submatches") or []][:10]
            matches.append({"path": path, "line": d.get("line_number"), "text": text.rstrip("\n")[:400],
                            "ranges": subs})
            files.add(path)
            if len(matches) >= MATCH_MAX:
                truncated = True
                break
        return {"project": key, "query": query, "matches": matches, "files": len(files), "truncated": truncated}
