"""Write guard: while installed, this process cannot start a program, open a network connection (other than GET
requests to one allowed live ccd), open a database for writing, write a file, or talk to herdr. Everything the
harness does that is not allowed raises GuardError.

`self_check()` tries each forbidden thing and reports whether it was blocked. The harness refuses to run any
scenario unless every probe was blocked."""
import builtins
import http.client
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
    real_request = http.client.HTTPConnection.request

    def guarded_open(file, mode="r", *a, **k):
        if _writes(mode) and not (isinstance(file, int) or _inside(file, roots)):
            raise GuardError(f"the readiness harness never writes {file}")
        return real_open(file, mode, *a, **k)

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and live_addr and \
                (address[0], address[1]) in _resolved(live_addr):
            return real_connect(sock, address)
        raise GuardError(f"the readiness harness never connects to {address!r}")

    def guarded_sqlite(database, *a, **k):
        db = os.fspath(database) if not isinstance(database, str) else database
        if db == ":memory:":
            return real_sqlite(database, *a, **k)
        if k.get("uri") and db.startswith("file:"):
            path, _, query = db[5:].partition("?")
            if "mode=ro" in query.split("&") or _inside(path, roots):
                return real_sqlite(database, *a, **k)
        elif _inside(db, roots):
            return real_sqlite(database, *a, **k)
        raise GuardError(f"the readiness harness never opens {db} for writing")

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
    patch(socket.socket, "connect", guarded_connect)
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


def _resolved(addr):
    host, port = addr
    out = {(host, port)}
    try:
        for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
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
    ]
    out = []
    for name, fn in probes:
        try:
            fn()
            ok = False
        except GuardError:
            ok = True
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
