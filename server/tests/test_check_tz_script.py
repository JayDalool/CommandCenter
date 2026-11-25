"""scripts/check-tz.sh prints a tzdata version for each runtime and changes nothing (CC-054, c2).

It must not assert exit 0: a host Node whose ICU tz data predates 2026e correctly makes the script exit 1.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WINNIPEG = Path("/usr/share/zoneinfo/America/Winnipeg")
SCRIPT = REPO / "scripts" / "check-tz.sh"


def _porcelain():
    return subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


@unittest.skipUnless(shutil.which("bash") and WINNIPEG.is_file(), "needs bash and the system Winnipeg zone file")
class CheckTzScript(unittest.TestCase):
    def run_script(self):
        with tempfile.TemporaryDirectory() as home:
            before_tree = _tree(home)
            before_git = _porcelain()
            r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60,
                               env={**os.environ, "HOME": home})
            self.assertEqual(_tree(home), before_tree, "the script wrote into HOME")
            self.assertEqual(_porcelain(), before_git, "the script changed the repo")
        return r

    def test_prints_a_version_line_per_runtime_and_changes_nothing(self):
        r = self.run_script()
        self.assertIn(r.returncode, (0, 1), r.stderr)       # 1 = stale data somewhere, a valid result
        out = r.stdout
        self.assertRegex(out, r"(?m)^tzdata \(C library\): package \S+, ")
        self.assertRegex(out, r"(?m)^tzdata \(Python \S+\): \S+: # version \d{4}[a-z]$|^tzdata \(Python \S+\): pip tzdata package: ")
        if shutil.which("node"):
            self.assertRegex(out, r"(?m)^(PASS|FAIL)\s+Node v\S+ ICU tz \S+:")

    # CC-054: the Python line must name the tz data ZoneInfo reads for America/Winnipeg, not the first tzdata.zi found.
    def python_line(self, tzpath=None, pypath=""):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONTZPATH", "TZDIR")}
        env["CHECK_TZ_PYPATH"] = pypath
        if pypath:
            env["CHECK_TZ_TESTING"] = "1"       # the script ignores CHECK_TZ_PYPATH without it (round 4)
        if tzpath is not None:
            env["PYTHONTZPATH"] = tzpath
        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env)
        line = next((l for l in r.stdout.splitlines() if l.startswith("tzdata (Python python3)")), "")
        self.assertTrue(line, r.stdout)
        return line

    def make_dir(self, root, name, version=None, zone=True):
        d = Path(root) / name
        d.mkdir()
        if zone:
            (d / "America").mkdir()
            shutil.copy(WINNIPEG, d / "America" / "Winnipeg")
        if version:
            (d / "tzdata.zi").write_text(f"# version {version}\n")
        return d

    def test_python_line_names_the_directory_that_holds_the_zone(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn(f"{self.make_dir(t, 'a', '2099a')}: # version 2099a", self.python_line(str(Path(t) / "a")))

    def test_python_line_skips_an_earlier_directory_without_the_zone(self):
        with tempfile.TemporaryDirectory() as t:
            wrong = self.make_dir(t, "wrong", "2001a", zone=False)     # has tzdata.zi, no Winnipeg
            right = self.make_dir(t, "right", "2099b")
            line = self.python_line(f"{wrong}{os.pathsep}{right}")
            self.assertIn("2099b", line)
            self.assertNotIn("2001a", line)

    def test_python_line_says_when_the_zone_directory_has_no_tzdata_zi(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("no tzdata.zi in that directory", self.python_line(str(self.make_dir(t, "a"))))

    def test_python_line_falls_back_to_pip_tzdata_only_when_no_path_has_the_zone(self):
        with tempfile.TemporaryDirectory() as t:
            empty = self.make_dir(t, "empty", "2001a", zone=False)
            pkg = Path(t) / "site" / "tzdata"
            (pkg / "zoneinfo" / "America").mkdir(parents=True)
            (pkg / "__init__.py").write_text('IANA_VERSION = "2099c"\n')
            (pkg / "zoneinfo" / "__init__.py").write_text("")
            (pkg / "zoneinfo" / "America" / "__init__.py").write_text("")
            shutil.copy(WINNIPEG, pkg / "zoneinfo" / "America" / "Winnipeg")
            self.assertIn("pip tzdata package: 2099c", self.python_line(str(empty), str(Path(t) / "site")))
            # the zone is on TZPATH too: pip must not be reported
            full = self.make_dir(t, "full", "2099d")
            line = self.python_line(str(full), str(Path(t) / "site"))
            self.assertIn("2099d", line)
            self.assertNotIn("pip tzdata package", line)   # not "pip": a random temp dir name can contain it

    def test_hostile_environment_cannot_make_a_probe_write(self):
        # CC-054 review round 3: NODE_COMPILE_CACHE, PYTHONPYCACHEPREFIX, PYTHONSTARTUP, NODE_OPTIONS and HOME each
        # made a probe write somewhere. The script runs its probes under env -i, so none may reach them.
        def snapshot(root):
            out = {}
            for p in Path(root).rglob("*"):
                st = p.lstat()
                out[str(p)] = (st.st_mtime_ns, st.st_size)
            return out

        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            node_cache, py_cache, home = t / "node-cache", t / "py-cache", t / "home"
            for d in (node_cache, py_cache, home):
                d.mkdir()
            (t / "startup.py").write_text(f"open({str(t / 'ran-startup')!r}, 'w').write('x')\n")
            (t / "preload.js").write_text(f"require('fs').writeFileSync({str(t / 'ran-preload')!r}, 'x')\n")
            pkg = t / "site" / "tzdata"          # a writable pip tzdata the Python probe imports
            (pkg / "zoneinfo" / "America").mkdir(parents=True)
            (pkg / "__init__.py").write_text('IANA_VERSION = "2099c"\n')
            (pkg / "zoneinfo" / "__init__.py").write_text("")
            (pkg / "zoneinfo" / "America" / "__init__.py").write_text("")
            shutil.copy(WINNIPEG, pkg / "zoneinfo" / "America" / "Winnipeg")
            empty = self.make_dir(t, "empty", "2001a", zone=False)
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONTZPATH", "TZDIR")}
            env.update(NODE_COMPILE_CACHE=str(node_cache), PYTHONPYCACHEPREFIX=str(py_cache),
                       PYTHONSTARTUP=str(t / "startup.py"), NODE_OPTIONS=f"--require {t / 'preload.js'}",
                       HOME=str(home), PYTHONTZPATH=str(empty), CHECK_TZ_PYPATH=str(t / "site"), CHECK_TZ_TESTING="1")
            before, git_before = snapshot(t), _porcelain()
            r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=90, env=env)
            self.assertIn(r.returncode, (0, 1), r.stderr)
            self.assertIn("pip tzdata package: 2099c", r.stdout)      # the probe did run, with PYTHONTZPATH passed through
            self.assertEqual(snapshot(t), before, "a probe wrote or changed a file")
            self.assertFalse((t / "ran-startup").exists() or (t / "ran-preload").exists())
            self.assertEqual(_porcelain(), git_before)

    def test_pypath_is_ignored_without_the_testing_marker(self):
        # CC-054 round 4: a package on a caller-supplied path would run its __init__ inside the probe.
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            marker = t / "ran-init"
            pkg = t / "site" / "tzdata"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text(f"open({str(marker)!r}, 'w').write('x')\nIANA_VERSION = 'x'\n")
            empty = self.make_dir(t, "empty", "2001a", zone=False)
            env = {k: v for k, v in os.environ.items() if k not in ("TZDIR", "CHECK_TZ_TESTING")}
            env.update(PYTHONTZPATH=str(empty), CHECK_TZ_PYPATH=str(t / "site"))
            r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env)
            self.assertFalse(marker.exists(), "caller-supplied package code ran")
            self.assertIn("no source has America/Winnipeg", r.stdout)

    def test_host_zone_and_version_probes_ignore_the_callers_path(self):
        # CC-054 round 4: readlink, dpkg-query and head also ran with the caller's environment and PATH.
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            bin_dir = t / "bin"
            bin_dir.mkdir()
            for tool in ("readlink", "dpkg-query", "head", "date"):
                f = bin_dir / tool
                f.write_text(f"#!/bin/sh\ntouch {t}/ran-{tool}\necho hostile\n")
                f.chmod(0o755)
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
            env.pop("TZDIR", None)
            r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(sorted(p.name for p in t.iterdir()), ["bin"], "a hostile PATH tool ran")
            self.assertNotIn("hostile", r.stdout)
            self.assertRegex(r.stdout, r"(?m)^PASS  C library \(date\): -0500")

    def test_the_pip_fallback_writes_no_bytecode(self):
        # CC-054 review round 2: importing a writable pip tzdata used to leave __pycache__ files in its tree.
        with tempfile.TemporaryDirectory() as t:
            empty = self.make_dir(t, "empty", "2001a", zone=False)
            pkg = Path(t) / "site" / "tzdata"
            (pkg / "zoneinfo" / "America").mkdir(parents=True)
            (pkg / "__init__.py").write_text('IANA_VERSION = "2099c"\n')
            (pkg / "zoneinfo" / "__init__.py").write_text("")
            (pkg / "zoneinfo" / "America" / "__init__.py").write_text("")
            shutil.copy(WINNIPEG, pkg / "zoneinfo" / "America" / "Winnipeg")
            before = _tree(t)
            self.assertIn("pip tzdata package: 2099c", self.python_line(str(empty), str(Path(t) / "site")))
            self.assertEqual(_tree(t), before)
            self.assertFalse(list(Path(t).rglob("__pycache__")))

    def test_relative_pythontzpath_entries_are_ignored_like_zoneinfo_does(self):
        with tempfile.TemporaryDirectory() as t:
            good = self.make_dir(t, "good", "2099f")
            line = self.python_line(f"relative/dir{os.pathsep}{good}")
            self.assertIn(f"{good}: # version 2099f", line)

    def test_c_library_line_follows_tzdir(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.make_dir(t, "zi", "2099g")
            env = {**os.environ, "TZDIR": str(d)}
            r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env)
            self.assertIn(f"tzdata (C library): TZDIR={d} overrides the system package, # version 2099g", r.stdout)
            self.assertIn("PASS  C library (date): -0500", r.stdout)     # the Winnipeg file there is read, not the host's

    def test_c_library_line_without_tzdir_names_the_system_package(self):
        env = {k: v for k, v in os.environ.items() if k != "TZDIR"}
        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=env)
        self.assertRegex(r.stdout, r"(?m)^tzdata \(C library\): package \S+, ")

    def test_python_line_says_when_nothing_has_the_zone(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("no source has America/Winnipeg", self.python_line(str(self.make_dir(t, "e", "2001a", zone=False))))

    def test_script_has_no_write_commands(self):
        text = SCRIPT.read_text()
        for bad in (" > /", ">>", "rm ", "apt", "sudo", "tee ", "mv ", "cp "):
            self.assertNotIn(bad, text, f"check-tz.sh must stay read-only: found {bad!r}")


if __name__ == "__main__":
    unittest.main()
