"""Messages: Jay's conversations with the CTO and each project lead (HQ launch plan, Jay's answers C1-C8, 2026-11-12).

    conversation  "cto" (the cross-project lead, a herdr agent named `cto`) or a project key (that project's
                  coordinator, its lead). Nothing else is a conversation.
    message       one row per message, kept for good (C4). side "jay" is Jay's (from HQ, or from Slack through
                  Daemon.deliver_to_lead), side "lead" is the lead's (cc-reply). A message is never typed into a
                  terminal: the lead gets one FIXED nudge naming the conversation and the two commands, and reads
                  the words itself with cc-inbox (C2 b).
    file          images (PNG, JPEG, GIF, WebP), PDF and Markdown/plain text (C6). The type comes from the file's
                  first bytes (and, for text, its name and a clean UTF-8 decode), never from what the uploader says.
                  SVG, HTML and everything else are refused. Blobs live outside every repository, named by a
                  generated id; downloads are always application/octet-stream + attachment, so a browser never
                  renders or runs one. HQ shows an image by fetching its bytes and building a blob of the stored type.

Storage: its own SQLite file (DATA_DIR/chat.db, 0600) and blob folder (0700), apart from tasks.db and ccd.db, which
hold operational metadata only. Message text that looks like a credential is refused whole, as onboarding drafts are.
"""
import hashlib
import os
import re
import secrets
import sqlite3
import time

from .attachments import display_name
from .onboarding import SECRET_RE

CTO = "cto"
TEXT_MAX = 16000
LIST_MAX = 200
ID_RE = re.compile(r"^[0-9a-f]{32}$")
CONV_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
PENDING_TTL = 24 * 3600     # an uploaded file not attached to a message within a day is removed
FILES_PER_MESSAGE = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation TEXT NOT NULL,
  side         TEXT NOT NULL CHECK (side IN ('jay','lead')),
  author       TEXT NOT NULL,
  text         TEXT NOT NULL,
  via          TEXT NOT NULL DEFAULT 'app' CHECK (via IN ('app','slack','cli')),
  ref          TEXT,
  reply_to     INTEGER REFERENCES messages(id),
  at           REAL NOT NULL,
  seen_at      REAL
);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conversation, id);
CREATE INDEX IF NOT EXISTS messages_unseen ON messages(side, seen_at);
CREATE TABLE IF NOT EXISTS files (
  id           TEXT PRIMARY KEY,
  conversation TEXT NOT NULL,
  message_id   INTEGER REFERENCES messages(id),
  side         TEXT NOT NULL CHECK (side IN ('jay','lead')),
  name         TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('image','pdf','markdown')),
  mime         TEXT NOT NULL,
  size         INTEGER NOT NULL,
  sha256       TEXT NOT NULL,
  uploaded_at  REAL NOT NULL,
  uploaded_by  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS files_message ON files(message_id);
-- Nudges sent to a lead for the messages it has not read yet. Reset when it reads its inbox.
CREATE TABLE IF NOT EXISTS nudges (
  conversation TEXT PRIMARY KEY,
  count        INTEGER NOT NULL DEFAULT 0,
  last_at      REAL
);
"""

TEXT_NAMES = (".md", ".markdown", ".txt")
IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
               (b"GIF89a", "image/gif"))


class ChatError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def sniff(head, name):
    """(kind, mime) from the first bytes and the name, or None. Text must also decode cleanly (checked on the whole
    file by the caller)."""
    for magic, mime in IMAGE_MAGIC:
        if head.startswith(magic):
            return "image", mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    lower = name.lower()
    if lower.endswith(TEXT_NAMES) and b"\x00" not in head:
        return "markdown", "text/markdown" if not lower.endswith(".txt") else "text/plain"
    return None


def check_text(text, required=True):
    if not isinstance(text, str):
        raise ChatError(400, "text must be a string")
    text = text.replace("\r\n", "\n").strip()
    if required and not text:
        raise ChatError(400, "a message needs some text or a file")
    if len(text) > TEXT_MAX:
        raise ChatError(413, f"a message is at most {TEXT_MAX} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise ChatError(400, "a message cannot hold control characters")
    if SECRET_RE.search(text):
        raise ChatError(400, "this looks like a password, token or key; never send credentials in a message")
    return text


class Chat:
    def __init__(self, db_path, blob_dir, max_bytes, clock=time.time):
        self.blob_dir = str(blob_dir)
        self.max_bytes = int(max_bytes)
        self.clock = clock
        os.makedirs(self.blob_dir, mode=0o700, exist_ok=True)
        os.chmod(self.blob_dir, 0o700)
        db_path = str(db_path)
        fd = os.open(db_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(db_path, 0o600)
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---------- messages ----------

    _MCOLS = "id, conversation, side, author, text, via, ref, reply_to, at, seen_at"

    def _msg(self, r, files):
        return {"id": r[0], "conversation": r[1], "side": r[2], "author": r[3], "text": r[4], "via": r[5],
                "ref": r[6], "replyTo": r[7], "at": r[8], "seenAt": r[9], "files": files.get(r[0], [])}

    def _files_for(self, ids):
        out = {}
        if not ids:
            return out
        marks = ",".join("?" * len(ids))
        for r in self.db.execute(f"SELECT {self._FCOLS} FROM files WHERE message_id IN ({marks}) ORDER BY rowid",
                                 list(ids)):
            out.setdefault(r[2], []).append(self._file(r))
        return out

    def _rows(self, rows):
        files = self._files_for([r[0] for r in rows])
        return [self._msg(r, files) for r in rows]

    def get(self, mid):
        r = self.db.execute(f"SELECT {self._MCOLS} FROM messages WHERE id=?", (mid,)).fetchone() \
            if isinstance(mid, int) and not isinstance(mid, bool) else None
        if not r:
            raise ChatError(404, "no such message")
        return self._rows([r])[0]

    def add(self, conversation, side, author, text, *, via="app", ref=None, reply_to=None, file_ids=()):
        """Store one message, attaching files this side uploaded to this conversation and not yet sent."""
        file_ids = list(dict.fromkeys(file_ids or ()))
        if len(file_ids) > FILES_PER_MESSAGE:
            raise ChatError(400, f"at most {FILES_PER_MESSAGE} files per message")
        text = check_text(text, required=not file_ids)
        if ref is not None and (not isinstance(ref, str) or len(ref) > 120):
            raise ChatError(400, "ref must be a short string")
        if reply_to is not None:
            row = self.db.execute("SELECT conversation FROM messages WHERE id=?", (reply_to,)).fetchone() \
                if isinstance(reply_to, int) and not isinstance(reply_to, bool) else None
            if not row or row[0] != conversation:
                raise ChatError(400, "replyTo must be a message in this conversation")
        for fid in file_ids:
            f = self.db.execute("SELECT conversation, side, message_id FROM files WHERE id=?", (fid,)).fetchone() \
                if isinstance(fid, str) and ID_RE.match(fid) else None
            if not f or f[0] != conversation or f[1] != side or f[2] is not None:
                raise ChatError(400, "a file must be uploaded to this conversation by the sender and not sent yet")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.db.execute("INSERT INTO messages(conversation, side, author, text, via, ref, reply_to, at) "
                                  "VALUES (?,?,?,?,?,?,?,?)",
                                  (conversation, side, author, text, via, ref, reply_to, self.clock()))
            mid = cur.lastrowid
            for fid in file_ids:
                n = self.db.execute("UPDATE files SET message_id=? WHERE id=? AND message_id IS NULL",
                                    (mid, fid)).rowcount
                if n != 1:
                    raise ChatError(409, "a file was sent by another message")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(mid)

    def history(self, conversation, before=None, limit=50):
        limit = max(1, min(int(limit), LIST_MAX))
        if before is None:
            rows = self.db.execute(f"SELECT {self._MCOLS} FROM messages WHERE conversation=? ORDER BY id DESC LIMIT ?",
                                   (conversation, limit)).fetchall()
        else:
            rows = self.db.execute(f"SELECT {self._MCOLS} FROM messages WHERE conversation=? AND id<? "
                                   f"ORDER BY id DESC LIMIT ?", (conversation, int(before), limit)).fetchall()
        return self._rows(list(reversed(rows)))

    def unseen(self, conversation, side):
        """Messages from `side` in this conversation the other side has not read, oldest first."""
        rows = self.db.execute(f"SELECT {self._MCOLS} FROM messages WHERE conversation=? AND side=? AND seen_at IS NULL "
                               f"ORDER BY id", (conversation, side)).fetchall()
        return self._rows(rows)

    def mark_seen(self, conversation, side, up_to=None):
        """The other side read `side`'s messages (all, or up to and including id up_to). Returns how many."""
        now = self.clock()
        if up_to is None:
            n = self.db.execute("UPDATE messages SET seen_at=? WHERE conversation=? AND side=? AND seen_at IS NULL",
                                (now, conversation, side)).rowcount
        else:
            n = self.db.execute("UPDATE messages SET seen_at=? WHERE conversation=? AND side=? AND seen_at IS NULL "
                                "AND id<=?", (now, conversation, side, int(up_to))).rowcount
        if side == "jay":
            self.db.execute("DELETE FROM nudges WHERE conversation=?", (conversation,))
        return n

    def summary(self):
        """Per conversation: the last message, Jay's unread (lead messages he has not seen) and waiting (Jay's
        messages the lead has not read)."""
        out = {}
        for conv, unread, waiting, last_id in self.db.execute(
                "SELECT conversation, SUM(side='lead' AND seen_at IS NULL), SUM(side='jay' AND seen_at IS NULL), "
                "MAX(id) FROM messages GROUP BY conversation"):
            last = self.get(last_id)
            out[conv] = {"unread": unread or 0, "waiting": waiting or 0,
                         "last": {k: last[k] for k in ("id", "side", "author", "at", "via")} |
                         {"text": last["text"][:160], "files": len(last["files"])}}
        return out

    def unread_for_jay(self):
        return {c: n for c, n in self.db.execute(
            "SELECT conversation, COUNT(*) FROM messages WHERE side='lead' AND seen_at IS NULL GROUP BY conversation")}

    # ---------- nudges ----------

    def nudge_state(self, conversation):
        r = self.db.execute("SELECT count, last_at FROM nudges WHERE conversation=?", (conversation,)).fetchone()
        return {"count": r[0], "lastAt": r[1]} if r else {"count": 0, "lastAt": None}

    def nudged(self, conversation):
        self.db.execute("INSERT INTO nudges(conversation, count, last_at) VALUES (?, 1, ?) ON CONFLICT(conversation) "
                        "DO UPDATE SET count = count + 1, last_at = excluded.last_at", (conversation, self.clock()))

    def waiting_conversations(self):
        """Conversations with Jay messages the lead has not read."""
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT conversation FROM messages WHERE side='jay' AND seen_at IS NULL ORDER BY conversation")]

    # ---------- files ----------

    _FCOLS = "id, conversation, message_id, side, name, kind, mime, size, sha256, uploaded_at, uploaded_by"

    @staticmethod
    def _file(r):
        return {"id": r[0], "conversation": r[1], "messageId": r[2], "side": r[3], "name": r[4], "kind": r[5],
                "mime": r[6], "size": r[7], "sha256": r[8], "uploadedAt": r[9], "uploadedBy": r[10]}

    def _blob(self, fid):
        if not isinstance(fid, str) or not ID_RE.match(fid):
            raise ChatError(404, "no such file")
        return os.path.join(self.blob_dir, fid)

    def file(self, fid):
        r = self.db.execute(f"SELECT {self._FCOLS} FROM files WHERE id=?", (fid,)).fetchone() \
            if isinstance(fid, str) and ID_RE.match(fid) else None
        if not r:
            raise ChatError(404, "no such file")
        return self._file(r)

    async def upload(self, conversation, side, author, name, chunks, length=None):
        try:
            name = display_name(name)
        except Exception:  # noqa: BLE001 — FileError: same message either way
            raise ChatError(400, "bad file name")
        mb = self.max_bytes // (1024 * 1024)
        if length is not None and length > self.max_bytes:
            raise ChatError(413, f"a file is at most {mb} MB")
        fid = secrets.token_hex(16)
        path = self._blob(fid)
        h, size, head, kind = hashlib.sha256(), 0, b"", None
        text_check = None
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ChatError(413, f"a file is at most {mb} MB")
                    if kind is None:
                        head += chunk
                        if len(head) >= 16:
                            kind = sniff(head, name)
                            if kind is None:
                                raise ChatError(415, "only images (PNG, JPEG, GIF, WebP), PDF and Markdown or text "
                                                     "files can be sent")
                            if kind[0] == "markdown":
                                import codecs
                                text_check = codecs.getincrementaldecoder("utf-8")("strict")
                            if text_check:
                                self._text_ok(text_check, head)
                    elif text_check:
                        self._text_ok(text_check, chunk)
                    h.update(chunk)
                    f.write(chunk)
                if kind is None:   # a file shorter than 16 bytes
                    kind = sniff(head, name)
                    if kind is None or size == 0:
                        raise ChatError(415, "only images (PNG, JPEG, GIF, WebP), PDF and Markdown or text files "
                                             "can be sent")
                    if kind[0] == "markdown":
                        import codecs
                        text_check = codecs.getincrementaldecoder("utf-8")("strict")
                        self._text_ok(text_check, head)
                if text_check:
                    self._text_ok(text_check, b"", final=True)
                f.flush()
                os.fsync(f.fileno())
            self.db.execute(f"INSERT INTO files({self._FCOLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (fid, conversation, None, side, name, kind[0], kind[1], size, h.hexdigest(),
                             self.clock(), author))
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return self.file(fid)

    @staticmethod
    def _text_ok(decoder, data, final=False):
        try:
            decoder.decode(data, final)
        except UnicodeDecodeError:
            raise ChatError(415, "a Markdown or text file must be UTF-8 text")
        if b"\x00" in data:
            raise ChatError(415, "a Markdown or text file must be UTF-8 text")

    def open(self, fid):
        """(fd, row). The caller streams and closes fd."""
        row = self.file(fid)
        fd = os.open(self._blob(fid), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        return fd, row

    def prune_pending(self):
        """Remove files uploaded more than a day ago and never sent. Sent files are kept with their messages."""
        cutoff = self.clock() - PENDING_TTL
        gone = [r[0] for r in self.db.execute("SELECT id FROM files WHERE message_id IS NULL AND uploaded_at < ?",
                                              (cutoff,))]
        for fid in gone:
            self.db.execute("DELETE FROM files WHERE id=? AND message_id IS NULL", (fid,))
            try:
                os.unlink(self._blob(fid))
            except FileNotFoundError:
                pass
        return len(gone)


def valid_conversation(conv):
    return isinstance(conv, str) and bool(CONV_RE.match(conv))
