"""Files attached to a ticket or a project. Never part of any repository.

Blobs live under ATTACH_DIR (default ~/.local/share/command-center/attachments,
mode 0700), named by a generated id; the original name is display metadata only
and never becomes a path. Metadata lives in DATA_DIR/attachments.db. Downloads
are always `application/octet-stream` + `Content-Disposition: attachment`, so a
browser saves an attachment and never renders or runs it (HTML, SVG, scripts).
"""
import hashlib
import os
import re
import secrets
import sqlite3
import time
import unicodedata

from .files import FileError, NAME_MAX

OWNER_KINDS = ("ticket", "project")
ID_RE = re.compile(r"^[0-9a-f]{32}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS attachments (
  id          TEXT PRIMARY KEY,
  owner_kind  TEXT NOT NULL CHECK (owner_kind IN ('ticket','project')),
  owner_key   TEXT NOT NULL,
  name        TEXT NOT NULL,
  size        INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  uploaded_at REAL NOT NULL,
  uploaded_by TEXT NOT NULL,
  removed_at  REAL,
  removed_by  TEXT
);
CREATE INDEX IF NOT EXISTS attachments_owner ON attachments(owner_kind, owner_key);
"""


def display_name(name):
    """A safe display name: no path, no control characters, bounded length."""
    if not isinstance(name, str):
        raise FileError(400, "bad file name")
    name = unicodedata.normalize("NFC", name).replace("\\", "/").rsplit("/", 1)[-1]
    # Control and format characters (incl. bidi overrides like U+202E) could disguise a name.
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf")).strip()
    if not name or name in (".", ".."):
        raise FileError(400, "bad file name")
    while len(name.encode()) > NAME_MAX:
        name = name[:-1]
    return name


def content_disposition(name):
    """RFC 6266: an ASCII fallback plus the exact UTF-8 name."""
    from urllib.parse import quote
    ascii_name = re.sub(r'[^A-Za-z0-9._ ()-]', "_", unicodedata.normalize("NFKD", name)
                        .encode("ascii", "ignore").decode()) or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


class Attachments:
    def __init__(self, db_path, blob_dir, max_bytes):
        self.blob_dir = str(blob_dir)
        os.makedirs(self.blob_dir, mode=0o700, exist_ok=True)
        os.chmod(self.blob_dir, 0o700)
        self.max_bytes = max_bytes
        self.db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def _blob(self, aid):
        if not ID_RE.match(aid or ""):
            raise FileError(404, "no such attachment")
        return os.path.join(self.blob_dir, aid)

    @staticmethod
    def _row(r):
        return {"id": r[0], "ownerKind": r[1], "ownerKey": r[2], "name": r[3], "size": r[4], "sha256": r[5],
                "uploadedAt": r[6], "uploadedBy": r[7]}

    _COLS = "id, owner_kind, owner_key, name, size, sha256, uploaded_at, uploaded_by"

    def list(self, kind, key):
        if kind not in OWNER_KINDS:
            raise FileError(400, "owner must be ticket or project")
        rows = self.db.execute(f"SELECT {self._COLS} FROM attachments WHERE owner_kind=? AND owner_key=? "
                               "AND removed_at IS NULL ORDER BY uploaded_at DESC", (kind, key)).fetchall()
        return [self._row(r) for r in rows]

    def get(self, aid):
        r = self.db.execute(f"SELECT {self._COLS} FROM attachments WHERE id=? AND removed_at IS NULL",
                            (aid,)).fetchone() if ID_RE.match(aid or "") else None
        if not r:
            raise FileError(404, "no such attachment")
        return self._row(r)

    async def add(self, kind, key, name, chunks, actor, length=None):
        if kind not in OWNER_KINDS:
            raise FileError(400, "owner must be ticket or project")
        name = display_name(name)
        mb = self.max_bytes // (1024 * 1024)
        if length is not None and length > self.max_bytes:
            raise FileError(413, f"file is larger than the {mb} MB limit")
        aid = secrets.token_hex(16)
        path = self._blob(aid)
        h = hashlib.sha256()
        size = 0
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FileError(413, f"file is larger than the {mb} MB limit")
                    h.update(chunk)
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            self.db.execute(f"INSERT INTO attachments({self._COLS}) VALUES (?,?,?,?,?,?,?,?)",
                            (aid, kind, key, name, size, h.hexdigest(), time.time(), actor))
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return self.get(aid)

    def open(self, aid):
        """(fd, row). The caller streams and closes fd."""
        row = self.get(aid)
        fd = os.open(self._blob(aid), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        return fd, row

    def remove(self, aid, actor):
        row = self.get(aid)
        self.db.execute("UPDATE attachments SET removed_at=?, removed_by=? WHERE id=?", (time.time(), actor, aid))
        try:
            os.unlink(self._blob(aid))
        except FileNotFoundError:
            pass
        return row
