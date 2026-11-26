"""scripts/cc-prune-build-cache runs only `docker builder prune -f` and fails closed (CC-096).

No test reaches the real docker: every main() call that gets past the argument, stop-file and lock checks uses a
recording fake runner, and every subprocess-level run of the script stops before docker (argument or stop file).
"""
import ast
import fcntl
import os
import re
import signal
import stat
import sys
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "cc-prune-build-cache"
RUNBOOK = REPO / "docs" / "runbooks" / "build-cache-prune.md"
CRON = ("30 4 * * 0 /usr/bin/python3 -I /srv/server/repos/CommandCenter/scripts/cc-prune-build-cache "
        ">> /home/jay/command-center/state/build-cache-prune.log 2>&1")
IDS = "k3j2h1g0f9d8s7a6p5o4i3u2y\nq1w2e3r4t5y6u7i8o9p0a1s2d\n"


def _load():
    loader = SourceFileLoader("cc_prune_build_cache", str(SCRIPT))
    mod = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


mod = _load()


class Runner:
    def __init__(self, stdout="", returncode=0, exc=None):
        self.calls, self.stdout, self.returncode, self.exc = [], stdout, returncode, exc

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "stderr-secret")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / "command-center" / "state"
        self.state.mkdir(parents=True)

    def go(self, runner, argv=()):
        out = []
        with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(a[0]) if not k.get("file") else None):
            code = mod.main(list(argv), run=runner, home=self.home)
        return code, out


class Parser(Base):
    def test_buildx_total_line(self):
        r = Runner(IDS + "Total:\t1.53GB\n")
        code, out = self.go(r)
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 1)
        self.assertRegex(out[0], r"^\d{4}-\d\d-\d\dT[\d:]+\+00:00 freed 1.53GB$")
        self.assertNotIn("k3j2h", out[0])

    def test_old_cli_total_line(self):
        _, out = self.go(Runner(IDS + "Total reclaimed space: 1.53GB\n"))
        self.assertTrue(out[0].endswith(" freed 1.53GB"))

    def test_unknown_when_missing_or_bad_size(self):
        for text in ("", IDS, "Total:\t$(rm -rf)\n", "Total:\t1.5 GB extra\n", "Total:\n"):
            _, out = self.go(Runner(text))
            self.assertTrue(out[0].endswith(" freed unknown"), text)

    def test_docker_text_never_printed(self):
        _, out = self.go(Runner("secret-path /home/x\nTotal:\t2GB\n", returncode=3))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith(" docker exit 3"))
        self.assertNotIn("secret", out[0])


class Env(Base):
    def test_argv_env_and_binary_are_fixed(self):
        hostile = {"DOCKER_HOST": "tcp://evil:1", "DOCKER_CONTEXT": "x", "DOCKER_CONFIG": "/x", "BUILDX_BUILDER": "other",
                   "BUILDX_CONFIG": "/x", "PYTHONPATH": "/x", "PATH": "/tmp/evil"}
        r = Runner("Total:\t1GB\n")
        with mock.patch.dict(os.environ, hostile):
            code, _ = self.go(r)
        self.assertEqual(code, 0)
        self.assertEqual(len(r.calls), 1)
        argv, kw = r.calls[0]
        self.assertEqual(argv, ["docker", "builder", "prune", "-f"])
        self.assertEqual(kw["env"], {"PATH": "/usr/bin:/bin", "HOME": str(self.home),
                                     "DOCKER_HOST": "unix:///var/run/docker.sock", "BUILDX_BUILDER": "default"})
        self.assertEqual(kw["executable"], "/usr/bin/docker")
        self.assertIs(kw["close_fds"], True)


class Refusals(Base):
    def test_any_argument_exits_2_without_running(self):
        for argv in (["--all"], ["-a"], ["images"], [""]):
            r = Runner()
            code, _ = self.go(r, argv)
            self.assertEqual(code, 2, argv)
            self.assertEqual(r.calls, [])

    def test_stop_file_kinds_block_the_run(self):
        stop = self.state / "cleanup.stop"
        for make in (lambda: stop.write_text(""), lambda: stop.mkdir(), lambda: stop.symlink_to(self.home / "nowhere")):
            make()
            r = Runner()
            code, out = self.go(r)
            self.assertEqual((code, r.calls), (0, []))
            self.assertTrue(out[0].endswith(" stopped"))
            if stop.is_dir() and not stop.is_symlink():
                stop.rmdir()
            else:
                stop.unlink()

    def test_stop_check_error_means_no_run(self):
        real = os.lstat

        def fake(path, *a, **k):
            if str(path).endswith("cleanup.stop"):
                raise PermissionError(13, "denied")
            return real(path, *a, **k)

        r = Runner()
        with mock.patch.object(mod.os, "lstat", side_effect=fake):
            code, _ = self.go(r)
        self.assertEqual((code, r.calls), (1, []))


class Lock(Base):
    def test_held_lock_is_busy_and_exit_0(self):
        fd = os.open(self.state / "build-cache-prune.lock", os.O_WRONLY | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = Runner()
        code, out = self.go(r)
        self.assertEqual((code, r.calls), (0, []))
        self.assertTrue(out[0].endswith(" busy"))

    def test_busy_when_another_process_holds_the_lock(self):
        # A real second process, not the same-process fd: flock conflicts are per open file description either way, but
        # this is the cron-overlap case the plan review asked for.
        code_src = ("import fcntl,os,sys;fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT,0o600);"
                    "fcntl.flock(fd,fcntl.LOCK_EX);print('ready',flush=True);sys.stdin.read()")
        holder = subprocess.Popen([sys.executable, "-I", "-c", code_src, str(self.state / "build-cache-prune.lock")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdin.close)
        self.assertEqual(holder.stdout.readline().strip(), "ready")
        r = Runner()
        code, out = self.go(r)
        self.assertEqual((code, len(r.calls)), (0, 0))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith(" busy"))

    def test_fifo_lock_is_refused_without_hanging(self):
        lock = self.state / "build-cache-prune.lock"
        os.mkfifo(lock)
        reader = os.open(lock, os.O_RDONLY | os.O_NONBLOCK)  # lets a plain open succeed, so only the fstat check refuses
        self.addCleanup(os.close, reader)

        def timeout(*_):
            raise AssertionError("lock open hung on a FIFO")

        old = signal.signal(signal.SIGALRM, timeout)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.alarm(5)
        self.addCleanup(signal.alarm, 0)
        r = Runner()
        code, out = self.go(r)
        self.assertEqual((code, len(r.calls)), (1, 0))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith(" lock error"))

    def test_fifo_lock_without_reader_does_not_hang(self):
        os.mkfifo(self.state / "build-cache-prune.lock")
        old = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(AssertionError("hung")))
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.alarm(5)
        self.addCleanup(signal.alarm, 0)
        r = Runner()
        self.assertEqual((self.go(r)[0], r.calls), (1, []))

    def test_state_dir_swapped_after_stop_check_still_uses_the_checked_directory(self):
        real, moved = self.state, self.home / "moved-state"
        evil = self.home / "evil"
        evil.mkdir()
        orig = os.lstat
        r = Runner("Total:\t1GB\n")

        # The stop file is absent, so lstat raises; swap in the finally, i.e. right after the stop check.
        def swap_on_missing(path, *a, **k):
            try:
                return orig(path, *a, **k)
            finally:
                if path == "cleanup.stop":
                    os.rename(real, moved)
                    real.symlink_to(evil)

        with mock.patch.object(mod.os, "lstat", side_effect=swap_on_missing):
            code, _ = self.go(r)
        self.assertEqual((code, len(r.calls)), (0, 1))
        self.assertTrue((moved / "build-cache-prune.lock").exists())
        self.assertEqual(list(evil.iterdir()), [])

    def test_symlinked_lock_path_fails_and_target_untouched(self):
        target = self.home / "victim"
        target.write_text("keep")
        (self.state / "build-cache-prune.lock").symlink_to(target)
        r = Runner()
        code, _ = self.go(r)
        self.assertEqual((code, r.calls), (1, []))
        self.assertEqual(target.read_text(), "keep")

    def test_symlink_to_missing_target_is_not_created(self):
        target = self.home / "never"
        (self.state / "build-cache-prune.lock").symlink_to(target)
        code, _ = self.go(Runner())
        self.assertEqual(code, 1)
        self.assertFalse(target.exists())

    def test_missing_state_dir_means_no_run(self):
        os.rmdir(self.state)
        r = Runner()
        self.assertEqual((self.go(r)[0], r.calls), (1, []))

    def test_symlinked_state_dir_means_no_run(self):
        os.rename(self.state, self.home / "real-state")
        self.state.symlink_to(self.home / "real-state")
        r = Runner()
        self.assertEqual((self.go(r)[0], r.calls), (1, []))

    def test_lock_file_is_not_truncated(self):
        lock = self.state / "build-cache-prune.lock"
        lock.write_text("keep")
        self.go(Runner("Total:\t1GB\n"))
        self.assertEqual(lock.read_text(), "keep")

    def test_new_lock_file_is_0600(self):
        self.go(Runner("Total:\t1GB\n"))
        self.assertEqual(stat.S_IMODE((self.state / "build-cache-prune.lock").stat().st_mode), 0o600)

    def test_flock_other_error_means_no_run(self):
        r = Runner()
        with mock.patch.object(mod.fcntl, "flock", side_effect=OSError(5, "io")):
            code, _ = self.go(r)
        self.assertEqual((code, r.calls), (1, []))


class Errors(Base):
    def test_timeout_one_line(self):
        code, out = self.go(Runner(exc=subprocess.TimeoutExpired("docker", 600)))
        self.assertEqual((code, len(out)), (1, 1))
        self.assertTrue(out[0].endswith(" docker timeout"))

    def test_oserror_one_line(self):
        for exc in (FileNotFoundError("x"), OSError("y"), PermissionError("z")):
            code, out = self.go(Runner(exc=exc))
            self.assertEqual((code, len(out)), (1, 1))
            self.assertTrue(out[0].endswith(" docker error"))

    def test_nonzero_exit(self):
        code, out = self.go(Runner(returncode=1))
        self.assertEqual(code, 1)
        self.assertTrue(out[0].endswith(" docker exit 1"))


class EndToEnd(unittest.TestCase):
    """Only runs that stop before docker: an argument, or a stop file."""

    def run_script(self, *args, home):
        env = {"HOME": home, "PATH": "/usr/bin:/bin"}
        return subprocess.run(["/usr/bin/python3", "-I", str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def test_argument_exits_2(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.run_script("--all", home=home).returncode, 2)

    def test_bare_script_with_stop_file_prints_stopped(self):
        with tempfile.TemporaryDirectory() as home:
            state = Path(home) / "command-center" / "state"
            state.mkdir(parents=True)
            (state / "cleanup.stop").write_text("")
            p = subprocess.run([str(SCRIPT)], env={"HOME": home, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0)
            self.assertTrue(p.stdout.strip().endswith(" stopped"))
            self.assertNotIn("Traceback", p.stderr)


class Static(unittest.TestCase):
    def setUp(self):
        self.src = SCRIPT.read_text()
        self.tree = ast.parse(self.src)

    def test_shebang_mode_and_not_symlink(self):
        self.assertEqual(self.src.splitlines()[0], "#!/usr/bin/python3 -I")
        out = subprocess.run(["git", "ls-files", "-s", "scripts/cc-prune-build-cache"], cwd=REPO, capture_output=True,
                             text=True).stdout
        if out:  # empty only before the file is staged
            self.assertTrue(out.startswith("100755 "), out)
        self.assertFalse(SCRIPT.is_symlink())

    def test_one_subprocess_call_and_no_delete_apis(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call)]
        names = []
        for c in calls:
            f = c.func
            names.append(f"{f.value.id}.{f.attr}" if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                         else getattr(f, "id", getattr(f, "attr", "")))
        self.assertEqual([n for n in names if n.startswith("subprocess.")], [])  # the one call is the injected run()
        self.assertEqual(names.count("run"), 1)
        for bad in ("system", "popen", "rmtree", "remove", "unlink", "Popen", "call", "check_output", "check_call"):
            self.assertFalse([n for n in names if n.split(".")[-1] == bad], bad)
        self.assertFalse([n for n in names if re.match(r"os\.(exec|spawn)", n)])
        for kw in (k for c in calls for k in c.keywords):
            if kw.arg == "shell":
                self.fail("shell= is never passed")

    def test_forbidden_words_nowhere_in_code(self):
        strings = [n.value for n in ast.walk(self.tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        strings = [s for s in strings if s is not ast.get_docstring(self.tree)]
        for word in ("volume", "image", "system", "rmi", "--all", "-a", "--filter", "--builder", "sudo"):
            for text in strings:
                self.assertNotIn(word, text.split(), word)
                if word.isalpha():
                    self.assertNotIn(word, text.lower(), word)
        self.assertEqual(mod.ARGV, ("docker", "builder", "prune", "-f"))

    def test_no_ccd_module_names_the_script(self):
        for p in (REPO / "server" / "ccd").rglob("*.py"):
            self.assertNotIn("cc-prune-build-cache", p.read_text(), p.name)


class Docs(unittest.TestCase):
    def test_runbook_has_exactly_the_cron_line(self):
        text = RUNBOOK.read_text()
        lines = [ln for ln in text.splitlines() if re.match(r"^[0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ ", ln)]
        self.assertEqual(lines, [CRON])
        for bad in ("%", ";", "&&", "|", "$", "`", "~"):
            self.assertNotIn(bad, CRON)
        for must in ("2026-11-25", "touch ~/command-center/state/cleanup.stop", "crontab -e",
                     "git -C /srv/server/repos/CommandCenter status --porcelain -- scripts/cc-prune-build-cache"):
            self.assertIn(must, text)

    def test_my_actions_line(self):
        want = ("- [ ] CC-096 · Install weekly build-cache prune cron line after Jay's yes · "
                "docs/runbooks/build-cache-prune.md")
        lines = (REPO / "docs" / "jay" / "MY_ACTIONS.md").read_text().splitlines()
        self.assertEqual([ln for ln in lines if "CC-096" in ln], [want])


if __name__ == "__main__":
    unittest.main()
