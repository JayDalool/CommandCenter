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
    def python_line(self, tzpath="", pypath=""):
        env = {**os.environ, "PYTHONTZPATH": tzpath, "CHECK_TZ_PYPATH": pypath}
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
            self.assertNotIn("pip", line)

    def test_python_line_says_when_nothing_has_the_zone(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("no source has America/Winnipeg", self.python_line(str(self.make_dir(t, "e", "2001a", zone=False))))

    def test_script_has_no_write_commands(self):
        text = SCRIPT.read_text()
        for bad in (" > /", ">>", "rm ", "apt", "sudo", "tee ", "mv ", "cp "):
            self.assertNotIn(bad, text, f"check-tz.sh must stay read-only: found {bad!r}")


if __name__ == "__main__":
    unittest.main()
