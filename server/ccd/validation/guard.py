"""Write guard: while installed, the harness cannot start a program, open a network connection or resolve a name
(other than GET requests to one allowed live ccd), open or attach a database for writing, create, write, move or
delete a file outside the folders it is given, or talk to herdr. Each of those raises GuardError.

It guards Python's own entry points (open, os.*, sqlite3, socket, http.client, subprocess). It is a safety net
for the harness's own code, not a sandbox against hostile code.

`self_check()` tries each forbidden thing and reports whether it was blocked. The harness refuses to run any
scenario unless every probe was blocked."""
import builtins
import http.client
import io
import os
import socket
import sqlite3
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class GuardError(PermissionError):
    pass


def _inside(path, roots):
    try:
        p = Path(os.path.realpath(os.fspath(path)))
    except (TypeError, ValueError):
        return False
    return any(p == r or r in p.parents for r in roots)


def _writes(mode):
    return any(c in str(mode) for c in "wax+")


@contextmanager
def installed(write_dirs=(), live_url=None):
    """Block every write path. `write_dirs`: the only folders files and databases may be written in (the report
    folder; the restore drill's temporary copy). `live_url`: the one ccd that GET requests may go to."""
    roots = [Path(os.path.realpath(d)) for d in write_dirs]
    live = urlsplit(live_url) if live_url else None
    live_addr = (live.hostname, live.port or (443 if live.scheme == "https" else 80)) if live else None
    saved = []

    def patch(obj, name, value):
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def blocked(what):
        def _raise(*_a, **_k):
            raise GuardError(f"the readiness harness never {what}")
        return _raise

    class NoPopen(subprocess.Popen):
        def __init__(self, *_a, **_k):     # noqa: D401 — no program ever starts
            raise GuardError("the readiness harness never starts a program")

    real_open, real_connect, real_sqlite = builtins.open, socket.socket.connect, sqlite3.connect
    real_connect_ex, real_getaddrinfo = socket.socket.connect_ex, socket.getaddrinfo
    real_request = http.client.HTTPConnection.request
    real_os_open = os.open
    allowed = _resolved(live_addr, real_getaddrinfo) if live_addr else set()

    def guarded_open(file, mode="r", *a, **k):
        if _writes(mode) and not (isinstance(file, int) or _inside(file, roots)):
            raise GuardError(f"the readiness harness never writes {file}")
        return real_open(file, mode, *a, **k)

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def guarded_os_open(path, flags, *a, **k):
        if flags & write_flags and not _inside(path, roots):
            raise GuardError(f"the readiness harness never writes {path}")
        return real_os_open(path, flags, *a, **k)

    def path_guard(name, real, nargs=1):
        def fn(*a, **k):
            for p in a[:nargs]:
                if not _inside(p, roots):
                    raise GuardError(f"the readiness harness never changes {p} ({name})")
            return real(*a, **k)
        return fn

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and (address[0], address[1]) in allowed:
            return real_connect(sock, address)
        raise GuardError(f"the readiness harness never connects to {address!r}")

    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and (address[0], address[1]) in allowed:
            return real_connect_ex(sock, address)
        raise GuardError(f"the readiness harness never connects to {address!r}")

    def guarded_getaddrinfo(host, port, *a, **k):
        if live_addr and host in {live_addr[0]} | {h for h, _p in allowed}:
            return real_getaddrinfo(host, port, *a, **k)
        raise GuardError(f"the readiness harness never resolves {host!r}")

    def no_attach(action, *_a):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ATTACH else sqlite3.SQLITE_OK

    def guarded_sqlite(database, *a, **k):
        db = os.fspath(database) if not isinstance(database, str) else database
        ok = False
        if db == ":memory:":
            ok = True
        elif k.get("uri") and db.startswith("file:"):
            path, _, query = db[5:].partition("?")
            ok = "mode=ro" in query.split("&") or _inside(path, roots)
        elif _inside(db, roots):
            ok = True
        if not ok:
            raise GuardError(f"the readiness harness never opens {db} for writing")
        conn = real_sqlite(database, *a, **k)
        conn.set_authorizer(no_attach)        # ATTACH would reach a file this check never saw
        return conn

    def guarded_request(conn, method, url, *a, **k):
        if str(method).upper() != "GET":
            raise GuardError(f"the readiness harness never sends {method}")
        return real_request(conn, method, url, *a, **k)

    patch(subprocess, "Popen", NoPopen)
    patch(os, "system", blocked("starts a program"))
    for name in ("execv", "execve", "execvp", "execvpe", "spawnv", "spawnve", "posix_spawn", "posix_spawnp", "fork"):
        if hasattr(os, name):
            patch(os, name, blocked("starts a program"))
    patch(builtins, "open", guarded_open)
    patch(io, "open", guarded_open)
    patch(os, "open", guarded_os_open)
    for name, n in (("mkdir", 1), ("makedirs", 1), ("remove", 1), ("unlink", 1), ("rmdir", 1), ("truncate", 1),
                    ("chmod", 1), ("rename", 2), ("replace", 2), ("symlink", 2), ("link", 2)):
        if hasattr(os, name):
            patch(os, name, path_guard(name, getattr(os, name), n))
    patch(socket.socket, "connect", guarded_connect)
    patch(socket.socket, "connect_ex", guarded_connect_ex)
    patch(socket.socket, "sendto", blocked("sends a datagram"))
    patch(socket, "getaddrinfo", guarded_getaddrinfo)
    try:
        import _posixsubprocess
        patch(_posixsubprocess, "fork_exec", blocked("starts a program"))
    except ImportError:
        pass
    patch(sqlite3, "connect", guarded_sqlite)
    patch(http.client.HTTPConnection, "request", guarded_request)
    try:
        from .. import herdr
        patch(herdr.Herdr, "_request", blocked("talks to herdr"))
    except Exception:  # noqa: BLE001 — herdr not importable means nothing to block
        pass
    try:
        yield
    finally:
        for obj, name, value in reversed(saved):
            setattr(obj, name, value)


def _resolved(addr, getaddrinfo=socket.getaddrinfo):
    host, port = addr
    out = {(host, port)}
    try:
        for info in getaddrinfo(host, port, type=socket.SOCK_STREAM):
            out.add((info[4][0], port))
    except OSError:
        pass
    return out


def self_check():
    """Try each forbidden action; [{probe, blocked}]. Call inside `installed()`."""
    outside = Path(tempfile.gettempdir()) / f"ccd-guard-probe-{os.getpid()}"
    probes = [
        ("start a program (subprocess)", lambda: subprocess.run(["true"], check=False)),
        ("start a program (os.system)", lambda: os.system("true")),
        ("write a file outside the report folder", lambda: open(outside, "w").close()),
        ("open a database for writing", lambda: sqlite3.connect(str(outside) + ".db").close()),
        ("open a network connection", lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.2).close()),
        ("send a non-GET HTTP request", lambda: http.client.HTTPConnection("127.0.0.1", 9).request("POST", "/")),
        ("write a file with io.open", lambda: io.open(outside, "w").close()),
        ("write a file with os.open", lambda: os.close(os.open(outside, os.O_WRONLY | os.O_CREAT))),
        ("write a file with pathlib", lambda: outside.write_text("x")),
        ("create a folder", lambda: os.mkdir(str(outside) + ".d")),
        ("delete a file", lambda: os.remove(str(outside) + ".none")),
        ("move a file", lambda: os.replace(str(outside) + ".a", str(outside) + ".b")),
        ("attach a database", lambda: sqlite3.connect(":memory:").execute(f"ATTACH '{outside}.db' AS x")),
        ("resolve a name", lambda: socket.getaddrinfo("example.com", 443)),
        ("connect with connect_ex", lambda: socket.socket().connect_ex(("127.0.0.1", 9))),
        ("send a datagram", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9))),
    ]
    out = []
    for name, fn in probes:
        try:
            fn()
            ok = False
        except GuardError:
            ok = True
        except sqlite3.DatabaseError as e:
            ok = "not authorized" in str(e)       # the ATTACH authoriser said no
        except Exception:  # noqa: BLE001 — anything else means the call got past the guard
            ok = False
        out.append({"probe": name, "blocked": ok})
    try:
        from .. import herdr
        herdr.Herdr("/nonexistent")._request("pane.send", {})
        out.append({"probe": "talk to herdr", "blocked": False})
    except GuardError:
        out.append({"probe": "talk to herdr", "blocked": True})
    except Exception:  # noqa: BLE001
        out.append({"probe": "talk to herdr", "blocked": False})
    return out
