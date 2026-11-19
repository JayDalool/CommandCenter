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
SCRIPT = REPO / "scripts" / "check-tz.sh"


def _porcelain():
    return subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


@unittest.skipUnless(shutil.which("bash"), "needs bash")
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
        self.assertRegex(out, r"(?m)^tzdata \(Python \S+\): \S+")
        if shutil.which("node"):
            self.assertRegex(out, r"(?m)^(PASS|FAIL)\s+Node v\S+ ICU tz \S+:")

    def test_script_has_no_write_commands(self):
        text = SCRIPT.read_text()
        for bad in (" > /", ">>", "rm ", "apt", "sudo", "tee ", "mv ", "cp "):
            self.assertNotIn(bad, text, f"check-tz.sh must stay read-only: found {bad!r}")


if __name__ == "__main__":
    unittest.main()
