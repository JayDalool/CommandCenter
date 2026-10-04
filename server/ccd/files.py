"""The Workspace's view of a project checkout: list, read, download, save, upload.

The browser names a project KEY and a path relative to it. The root comes from
the project registry (`registry.root_of`) and nowhere else; no request can name
a filesystem root. Every path goes through `Roots.resolve`, which:

  * refuses NUL, control characters, backslashes, absolute paths, `..`, and
    percent-encoded `.`/`..`/separators (a second decode never happens, but a
    name that would mean traversal after one is refused anyway)
  * resolves symlinks and refuses anything whose real path leaves the root
  * refuses `.git` anywhere in the path, before and after resolution
  * marks secret-looking paths (PROTECTED) as listable but never readable,
    downloadable, writable or uploadable

Reads are capped (TEXT_MAX); bigger or binary files offer metadata and a
download instead. Saves are atomic (temp file in the same directory, fsync,
rename), keep the file's mode, and refuse when the file changed since it was
opened (`baseSha`). Uploads never overwrite silently: the caller picks
fail (default) / replace / rename, and fail and rename use a hard link, which
cannot clobber an existing name.

Protected-file policy (the exact rules; docs/SECURITY.md repeats them):
  directory names   .git .ssh .gnupg .aws .azure .kube .docker .password-store
  file names        .env .env.*  (except .env.example .env.sample .env.template .env.dist)
                    id_rsa id_dsa id_ecdsa id_ed25519 (public .pub keys are not secret)
                    .netrc .npmrc .pypirc .git-credentials .pgpass .htpasswd
                    credentials credentials.json token token.txt *.token
                    secrets.json secrets.yaml secrets.yml secrets.toml
  extensions        .pem .key .p12 .pfx .jks .keystore .kdbx .gpg .asc
"""
import contextlib
import hashlib
import os
import re
import secrets as _secrets
import stat
import subprocess
import threading
import time
from urllib.parse import unquote

from . import registry

TEXT_MAX = 2 * 1024 * 1024          # the editor opens nothing bigger
LIST_MAX = 3000                     # entries returned for one directory
UPLOAD_MAX = 50 * 1024 * 1024       # per file; config `upload_max_mb` may lower or raise it
NAME_MAX = 255

DENY_DIRS = {".git", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store"}
DENY_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
              ".pgpass", ".htpasswd", "credentials", "credentials.json", "token", "token.txt", "secrets.json",
              "secrets.yaml", "secrets.yml", "secrets.toml", ".env"}
DENY_EXT = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".gpg", ".asc", ".token"}
ENV_OK = {".env.example", ".env.sample", ".env.template", ".env.dist"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class FileError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def is_protected_name(name):
    low = name.lower()
    if low in DENY_DIRS or low in DENY_NAMES:
        return True
    if low.startswith(".env.") and low not in ENV_OK:
        return True
    return os.path.splitext(low)[1] in DENY_EXT


def _check_component(c):
    if not c or c in (".", ".."):
        raise FileError(400, "bad path")
    if _CTRL.search(c) or "\\" in c or len(c.encode()) > NAME_MAX:
        raise FileError(400, "bad path")
    once = unquote(c)
    if once != c and (once in (".", "..") or "/" in once or "\\" in once or "\x00" in once):
        raise FileError(400, "bad path")


def split_rel(rel):
    """'a/b/c' → ['a','b','c'], refusing anything that is not a plain relative path."""
    if rel is None:
        rel = ""
    if not isinstance(rel, str) or len(rel) > 4096 or "\x00" in rel or "\\" in rel:
        raise FileError(400, "bad path")
    if rel.startswith("/"):
        raise FileError(400, "paths are relative to the project")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    for p in parts:
        _check_component(p)
    return parts


def check_name(name):
    """A single new file name from the browser (an upload)."""
    if not isinstance(name, str):
        raise FileError(400, "bad file name")
    _check_component(name)
    if "/" in name or name.startswith(".ccd-"):
        raise FileError(400, "bad file name")
    if is_protected_name(name):
        raise FileError(403, f"{name} looks like a secret file; Command Center does not write those")
    return name


def _is_text(data):
    """The editor's one definition of text: UTF-8 with no NUL in the first 8 KB."""
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


class Roots:
    def __init__(self, roots=None, upload_max=UPLOAD_MAX):
        """roots: key → path. Default: every registered project's `root`."""
        if roots is None:
            roots = {k: v["root"] for k, v in registry.PROJECTS.items() if v.get("root")}
        self.roots = {k: os.path.realpath(v) for k, v in roots.items()}
        self.upload_max = upload_max
        self._write = threading.Lock()
        self._git_cache = {}

    def root(self, key):
        r = self.roots.get(key) if isinstance(key, str) else None
        if not r:
            raise FileError(404, "unknown project")
        if not os.path.isdir(r):
            raise FileError(404, "project checkout not found on the server")
        return r

    def resolve(self, key, rel, *, must_exist=True):
        """(root, real_path, rel_parts). Raises FileError on anything unsafe."""
        root = self.root(key)
        parts = split_rel(rel)
        if any(p.lower() == ".git" for p in parts):
            raise FileError(403, ".git is not browsable or writable here")
        if any(is_protected_name(p) for p in parts):
            raise FileError(403, "protected file", protected=True)
        full = os.path.join(root, *parts)
        real = os.path.realpath(full)
        if real != root and not real.startswith(root + os.sep):
            raise FileError(403, "that path leaves the project")
        real_parts = os.path.relpath(real, root).split(os.sep) if real != root else []
        if any(p.lower() == ".git" for p in real_parts) or any(is_protected_name(p) for p in real_parts):
            raise FileError(403, "protected file", protected=True)
        if must_exist and not os.path.lexists(real):
            raise FileError(404, "no such file")
        return root, real, parts

    # ---------- reading ----------

    def _git_status(self, root):
        hit = self._git_cache.get(root)
        if hit and time.monotonic() - hit[0] < 10:
            return hit[1]
        out = {}
        try:
            r = subprocess.run(["git", "-C", root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"],
                               capture_output=True, timeout=5, check=False)
            if r.returncode == 0:
                for item in r.stdout.decode("utf-8", "replace").split("\x00"):
                    if len(item) > 3:
                        out[item[3:]] = item[:2].strip() or "M"
        except (OSError, subprocess.TimeoutExpired):
            out = None
        self._git_cache[root] = (time.monotonic(), out)
        return out

    def list(self, key, rel="", git=False):
        root, real, parts = self.resolve(key, rel)
        if not os.path.isdir(real):
            raise FileError(400, "not a folder")
        status = self._git_status(root) if git else None
        here = "/".join(parts)
        entries = []
        truncated = False
        with os.scandir(real) as it:
            for e in it:
                if e.name.lower() == ".git":
                    continue
                if len(entries) >= LIST_MAX:
                    truncated = True
                    break
                try:
                    link = e.is_symlink()
                    st = e.stat(follow_symlinks=True)
                except OSError:
                    entries.append({"name": e.name, "kind": "broken", "size": None, "mtime": None,
                                    "protected": False, "link": True})
                    continue
                kind = "dir" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
                if link:
                    target = os.path.realpath(e.path)
                    if target != root and not target.startswith(root + os.sep):
                        kind = "outside"
                rel_path = f"{here}/{e.name}" if here else e.name
                row = {"name": e.name, "kind": kind, "size": st.st_size if kind == "file" else None,
                       "mtime": st.st_mtime, "protected": is_protected_name(e.name), "link": link}
                if status is not None:
                    if kind == "dir":
                        pre = rel_path + "/"
                        row["git"] = "M" if any(k.startswith(pre) for k in status) else None
                    else:
                        row["git"] = status.get(rel_path)
                entries.append(row)
        entries.sort(key=lambda r: (r["kind"] != "dir", r["name"].lower()))
        return {"project": key, "path": here, "crumbs": parts, "entries": entries, "truncated": truncated,
                "git": status is not None}

    def _open_regular(self, real):
        fd = os.open(real, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(fd)
            raise FileError(400, "not a regular file")
        return fd, st

    def read(self, key, rel):
        _, real, parts = self.resolve(key, rel)
        fd, st = self._open_regular(real)
        meta = {"project": key, "path": "/".join(parts), "size": st.st_size, "mtime": st.st_mtime,
                "mode": oct(st.st_mode & 0o7777)}
        with os.fdopen(fd, "rb") as f:
            if st.st_size > TEXT_MAX:
                return {**meta, "kind": "large", "text": None, "sha": None}
            data = f.read(TEXT_MAX + 1)
        sha = hashlib.sha256(data).hexdigest()
        if not _is_text(data):
            return {**meta, "kind": "binary", "text": None, "sha": sha}
        return {**meta, "kind": "text", "text": data.decode("utf-8"), "sha": sha}

    def open_download(self, key, rel):
        """(fd, size, name) of a regular file. The caller streams it and closes fd."""
        _, real, parts = self.resolve(key, rel)
        fd, st = self._open_regular(real)
        return fd, st.st_size, parts[-1] if parts else "file"

    # ---------- writing ----------

    def _tmp_in(self, folder, mode):
        for _ in range(5):
            tmp = os.path.join(folder, f".ccd-{_secrets.token_hex(6)}.tmp")
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
                return fd, tmp
            except FileExistsError:
                continue
        raise FileError(500, "could not create a temporary file")

    def _writable_dir(self, key, rel_dir):
        root, real_dir, parts = self.resolve(key, rel_dir)
        if not os.path.isdir(real_dir):
            raise FileError(400, "destination is not a folder")
        return root, real_dir, parts

    def save(self, key, rel, text, base_sha):
        """Atomic replace of a text file, refused if it changed since `base_sha`.
        base_sha None means 'create a new file' and is refused if the name exists."""
        if not isinstance(text, str):
            raise FileError(400, "text must be a string")
        data = text.encode("utf-8")
        if len(data) > TEXT_MAX:
            raise FileError(413, "file too large for the editor")
        parts = split_rel(rel)
        if not parts:
            raise FileError(400, "bad path")
        name = parts[-1]
        if is_protected_name(name):
            raise FileError(403, "protected file", protected=True)
        _, folder, dparts = self._writable_dir(key, "/".join(parts[:-1]))
        target = os.path.join(folder, name)
        with self._write:
            mode = 0o644
            if os.path.lexists(target):
                st = os.lstat(target)
                if stat.S_ISLNK(st.st_mode):
                    raise FileError(403, "refusing to write through a symlink")
                if not stat.S_ISREG(st.st_mode):
                    raise FileError(400, "not a regular file")
                if base_sha is None:
                    raise FileError(409, "a file with that name already exists", conflict=True)
                with open(target, "rb") as f:
                    current = f.read(TEXT_MAX + 1)
                cur_sha = hashlib.sha256(current).hexdigest()
                if cur_sha != base_sha:
                    raise FileError(409, "the file changed on disk since you opened it", conflict=True,
                                    currentSha=cur_sha, mtime=st.st_mtime)
                if not _is_text(current):
                    raise FileError(400, "not a text file; the editor will not overwrite it")
                mode = stat.S_IMODE(st.st_mode)
            elif base_sha is not None:
                raise FileError(409, "the file was deleted on disk since you opened it", conflict=True)
            fd, tmp = self._tmp_in(folder, mode)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(tmp, mode)
                os.replace(tmp, target)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
            st = os.stat(target)
        return {"project": key, "path": "/".join(dparts + [name]), "sha": hashlib.sha256(data).hexdigest(),
                "size": len(data), "mtime": st.st_mtime}

    async def upload(self, key, rel_dir, name, chunks, conflict="fail", length=None):
        """Write an uploaded stream into `rel_dir/name`. `chunks` is an async iterator of bytes."""
        check_name(name)
        if conflict not in ("fail", "replace", "rename"):
            raise FileError(400, "conflict must be fail, replace or rename")
        if length is not None and length > self.upload_max:
            raise FileError(413, f"file is larger than the {self.upload_max // (1024 * 1024)} MB upload limit")
        _, folder, dparts = self._writable_dir(key, rel_dir)
        fd, tmp = self._tmp_in(folder, 0o644)
        size = 0
        h = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self.upload_max:
                        raise FileError(413, f"file is larger than the {self.upload_max // (1024 * 1024)} MB "
                                             "upload limit")
                    h.update(chunk)
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            final = self._place(folder, name, tmp, conflict)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        return {"project": key, "path": "/".join(dparts + [final]), "name": final, "size": size,
                "sha": h.hexdigest(), "renamed": final != name}

    def _place(self, folder, name, tmp, conflict):
        with self._write:
            target = os.path.join(folder, name)
            if conflict == "replace" and os.path.lexists(target):
                st = os.lstat(target)
                if not stat.S_ISREG(st.st_mode):
                    raise FileError(409, "only a regular file can be replaced", conflict=True)
                os.chmod(tmp, stat.S_IMODE(st.st_mode))
                os.replace(tmp, target)
                return name
            candidates = [name]
            if conflict == "rename":
                stem, ext = os.path.splitext(name)
                candidates += [f"{stem} ({i}){ext}" for i in range(1, 100)]
            for cand in candidates:
                try:
                    os.link(tmp, os.path.join(folder, cand))  # never clobbers
                    return cand
                except FileExistsError:
                    continue
            raise FileError(409, f"{name} already exists", conflict=True, exists=True)

