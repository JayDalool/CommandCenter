"""Real terminals for the Workspace: named PTY sessions owned by ccd (ADR 0004 phase 3).

Session names are fixed, never paths:

    repo:<PREFIX>   cwd = that project's registered root (registry.root_of)
    server          cwd = $HOME

Anything else is refused. Each session is one login shell running as jay in
its own process group (setsid + controlling tty). Several browser views may
attach to one session and share it, as tmux does. Closing the browser only
detaches; the shell keeps running until CLOSE SESSION, until it exits, until
it sits unattached for IDLE_EXPIRE seconds, or until ccd stops.

Output goes into a bounded ring buffer (replayed on attach) and to each
client's bounded queue; a client that cannot keep up is dropped with `lost`
rather than ever stalling the shell. Input and output are never logged or
stored: the audit trail records session created / attached / detached /
closed / expired with the session name and client count only.

This module never talks to herdr: Claude panes are herdr's and are untouched.
"""
import asyncio
import fcntl
import json
import logging
import os
import pwd
import secrets
import shutil
import signal
import struct
import termios
import time

from . import registry

RING_BYTES = 256 * 1024
CLIENT_QUEUE = 512          # chunks; ~ up to 32 MiB worst case per client before it is dropped
READ_CHUNK = 64 * 1024
INPUT_MAX = 64 * 1024       # one input message
IDLE_EXPIRE = 12 * 3600     # an unattached session ends after this long
CLOSE_GRACE = 2.0


class PtyError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def session_cwd(name, roots=None, home=None):
    """The cwd for a session name, from the registry only. Raises PtyError otherwise."""
    if name == "server":
        return home or pwd.getpwuid(os.getuid()).pw_dir
    if isinstance(name, str) and name.startswith("repo:"):
        prefix = name[5:]
        roots = roots if roots is not None else {
            p["prefix"]: p.get("root") for p in registry.PROJECTS.values()}
        root = roots.get(prefix)
        if root and os.path.isdir(root):
            return os.path.realpath(root)
        raise PtyError(404, f"no registered project with prefix {prefix!r}")
    raise PtyError(400, "session must be repo:<PREFIX> or server")


class Client:
    def __init__(self):
        self.queue = asyncio.Queue(CLIENT_QUEUE)
        self.lost = False


class Session:
    def __init__(self, name, cwd, pid, fd):
        self.name, self.cwd, self.pid, self.fd = name, cwd, pid, fd
        self.created = time.time()
        self.ring = bytearray()
        self.clients = set()
        self.detached_at = time.time()
        self.exit_code = None
        self.pending = bytearray()   # input waiting for the pty to accept it
        self.ended = False
        self.closing = None

    def public(self):
        return {"name": self.name, "cwd": self.cwd, "clients": len(self.clients), "createdAt": self.created,
                "alive": not self.ended, "pid": self.pid}


class PtyManager:
    def __init__(self, audit=None, roots=None, home=None, shell=None, env=None, own_scope=False):
        self.sessions = {}
        self.audit = audit or (lambda kind, text, data: None)
        self.roots = roots
        self.home = home
        pw = pwd.getpwuid(os.getuid())
        self.shell = shell or pw.pw_shell or "/bin/bash"
        self.user = pw.pw_name
        self.env = env
        # own_scope: start each shell in its own transient systemd user scope, OUTSIDE ccd's
        # cgroup, so a build in a terminal neither shares ccd's MemoryMax nor can get ccd OOM-killed.
        self.own_scope = own_scope and shutil.which("systemd-run") is not None
        if own_scope and not self.own_scope:
            logging.getLogger("ccd").warning(json.dumps({"msg": "systemd-run not found: terminals share ccd's cgroup "
                                                                "and MemoryMax"}))
        self._lock = asyncio.Lock()

    # ---------- lifecycle ----------

    def _child_env(self, cwd):
        base = self.env if self.env is not None else os.environ
        # XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS: so `systemctl --user` and `journalctl --user`
        # work in the shell (and systemd-run can place it in its own scope). They are paths, not secrets.
        keep = {k: base[k] for k in ("PATH", "LANG", "LC_ALL", "TZ", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
                if k in base}
        home = self.home or pwd.getpwuid(os.getuid()).pw_dir
        keep.update(HOME=home, USER=self.user, LOGNAME=self.user, SHELL=self.shell, PWD=cwd,
                    TERM="xterm-256color", COLORTERM="truecolor")
        keep.setdefault("LANG", "C.UTF-8")
        return keep

    def _spawn(self, name, cwd, cols, rows):
        # Everything the child needs is built here, BEFORE the fork: after fork in a
        # threaded process the child may only chdir, close and exec.
        env = self._child_env(cwd)
        argv = [os.path.basename(self.shell), "-l"]
        shell = self.shell
        unit = None
        if self.own_scope:
            unit = f"cc-pty-{name.replace(':', '-')}-{secrets.token_hex(3)}"
            argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={unit}",
                    "--description=Command Center terminal " + name, "--", self.shell, "-l"]
            shell = shutil.which("systemd-run")
        try:
            maxfd = os.sysconf("SC_OPEN_MAX")
        except (ValueError, OSError):
            maxfd = 4096
        pid, fd = os.forkpty()
        if pid == 0:  # child: a new session, the pty is its controlling tty (fds 0-2)
            try:
                os.closerange(3, maxfd)  # no other terminal's master, no ccd socket or db leaks in
                os.chdir(cwd)
                os.execve(shell, argv, env)
            finally:
                os._exit(127)
        os.set_inheritable(fd, False)
        self._winsize(fd, cols, rows)
        os.set_blocking(fd, False)
        s = Session(name, cwd, pid, fd)
        s.unit = unit
        return s

    @staticmethod
    def _winsize(fd, cols, rows):
        cols = max(2, min(int(cols), 500))
        rows = max(1, min(int(rows), 300))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def open(self, name, cols=80, rows=24):
        """The session `name`, starting it if needed. Returns (session, created)."""
        cwd = session_cwd(name, self.roots, self.home)
        async with self._lock:
            s = self.sessions.get(name)
            if s and not s.ended:
                return s, False
            s = self._spawn(name, cwd, cols, rows)
            self.sessions[name] = s
            asyncio.get_running_loop().add_reader(s.fd, self._on_output, s)
        self.audit("pty.session.created", f"terminal {name} started", {"session": name})
        return s, True

    def _on_output(self, s):
        try:
            data = os.read(s.fd, READ_CHUNK)
        except BlockingIOError:
            return
        except OSError:
            data = b""  # EIO: the shell side closed
        if not data:
            self._ended(s)
            return
        s.ring += data
        if len(s.ring) > RING_BYTES:
            del s.ring[: len(s.ring) - RING_BYTES]
        for c in list(s.clients):
            if c.lost:
                continue
            try:
                c.queue.put_nowait(data)
            except asyncio.QueueFull:
                c.lost = True  # never stall the shell for a slow viewer
                try:
                    c.queue.get_nowait()
                    c.queue.put_nowait(None)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def _ended(self, s, reason="exited"):
        if s.ended:
            return
        s.ended = True
        reason = s.closing or reason
        loop = asyncio.get_running_loop()
        try:
            loop.remove_reader(s.fd)
            loop.remove_writer(s.fd)
        except (ValueError, OSError):
            pass
        if s.exit_code is None:
            try:
                pid, status = os.waitpid(s.pid, os.WNOHANG)
                if pid:
                    s.exit_code = os.waitstatus_to_exitcode(status)
                else:
                    loop.create_task(self._reap_later(s))  # the pty closed a moment before the shell exited
            except ChildProcessError:
                s.exit_code = -1
        try:
            os.close(s.fd)
        except OSError:
            pass
        if self.sessions.get(s.name) is s:
            del self.sessions[s.name]
        for c in list(s.clients):
            try:
                c.queue.put_nowait(None)
            except asyncio.QueueFull:  # make room: the end must always reach the viewer
                c.lost = True
                try:
                    c.queue.get_nowait()
                    c.queue.put_nowait(None)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        kind = {"expired": "pty.session.expired"}.get(reason, "pty.session.closed")
        self.audit(kind, f"terminal {s.name} {reason}", {"session": s.name, "clients": len(s.clients)})

    async def _reap_later(self, s):
        """Never leave a zombie: wait for the exited shell, and SIGKILL its group if it lingers."""
        if not await self._reaped(s, 5.0):
            try:
                os.killpg(s.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self._reaped(s, 2.0)

    async def _reaped(self, s, wait):
        deadline = time.monotonic() + wait
        while True:
            try:
                pid, status = os.waitpid(s.pid, os.WNOHANG)
            except ChildProcessError:
                return True
            if pid:
                s.exit_code = os.waitstatus_to_exitcode(status)
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def close(self, name, reason="closed"):
        """Explicit CLOSE SESSION: SIGHUP the session's process group, SIGKILL after a grace period.
        Only this session's group is signalled."""
        s = self.sessions.get(name)
        if not s:
            raise PtyError(404, "no such session")
        if s.ended or s.closing:  # another close is already signalling this group
            return {"ok": True, "name": name}
        s.closing = reason
        pgid = s.pid  # forkpty's child called setsid: its pid is its process group
        try:
            os.killpg(pgid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        if not await self._reaped(s, CLOSE_GRACE):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self._reaped(s, 1.0)
        await self._stop_scope(s)
        self._ended(s, reason)
        return {"ok": True, "name": name}

    async def _stop_scope(self, s):
        """CLOSE SESSION ends everything started in that terminal, background and nohup jobs
        included: they live in the session's own scope, which is stopped here. Nothing else is."""
        if not getattr(s, "unit", None):
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "stop", "--no-block", f"{s.unit}.scope",
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), 5)
        except (OSError, asyncio.TimeoutError):
            pass

    async def close_all(self):
        for name in list(self.sessions):
            try:
                await self.close(name, "closed (ccd stopping)")
            except PtyError:
                pass

    async def expire_idle(self, now=None):
        now = now or time.time()
        for s in list(self.sessions.values()):
            if not s.clients and now - s.detached_at > IDLE_EXPIRE:
                try:
                    await self.close(s.name, "expired")
                except PtyError:
                    continue  # it ended on its own meanwhile

    # ---------- clients ----------

    def attach(self, s):
        c = Client()
        replay = bytes(s.ring)
        s.clients.add(c)
        if s.ended:  # the shell exited between open and attach: tell this view at once
            c.queue.put_nowait(None)
        self.audit("pty.attached", f"terminal {s.name} attached", {"session": s.name, "clients": len(s.clients)})
        return c, replay

    def detach(self, s, c):
        if c in s.clients:
            s.clients.discard(c)
            if not s.clients:
                s.detached_at = time.time()
            self.audit("pty.detached", f"terminal {s.name} detached", {"session": s.name, "clients": len(s.clients)})

    def write(self, s, data):
        if s.ended:
            raise PtyError(409, "session has ended")
        if not isinstance(data, (bytes, bytearray)) or len(data) > INPUT_MAX:
            raise PtyError(413, "input too large")
        if len(s.pending) + len(data) > 4 * INPUT_MAX:
            raise PtyError(429, "terminal is not reading input")
        s.pending += data
        self._flush(s)

    def _flush(self, s):
        loop = asyncio.get_running_loop()
        while s.pending:
            try:
                n = os.write(s.fd, s.pending)
            except BlockingIOError:
                loop.add_writer(s.fd, self._flush, s)
                return
            except OSError:
                s.pending.clear()
                return
            del s.pending[:n]
        try:
            loop.remove_writer(s.fd)
        except (ValueError, OSError):
            pass

    def resize(self, s, cols, rows):
        if not s.ended:
            self._winsize(s.fd, cols, rows)

    def list(self):
        return [s.public() for s in self.sessions.values()]
