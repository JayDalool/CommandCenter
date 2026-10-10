"""scripts/go-live.sh (CC-030): deploys origin/main by default, other branches only with --i-know.

Every run is against a throw-away clone (CC_REPO), a temp HOME and CCD_DATA_DIR, and PATH shims for
systemctl, curl and go that leave a marker and fail. Only --dry-run and refusal paths are exercised, so no
deploy step (pip, deploy-web.sh, ccd restart) ever runs.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "go-live.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd, *args):
    env = dict(os.environ, **GIT_ENV)
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


class GoLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="go-live-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.data = self.tmp / "data"
        self.markers = self.tmp / "markers"
        for d in (self.home, self.data, self.markers):
            d.mkdir()
        # shims: each leaves a marker and fails
        self.shims = self.tmp / "shims"
        self.shims.mkdir()
        for name in ("systemctl", "curl", "go"):
            f = self.shims / name
            f.write_text(f'#!/bin/sh\necho "$@" >> "{self.markers}/{name}"\nexit 1\n')
            f.chmod(0o755)
        # bare origin, the live checkout (CC_REPO) and a second clone that plays "the reviewers merging"
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.repo = self.tmp / "live"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.repo))
        git(self.repo, "checkout", "-q", "-b", "main")
        scripts = self.repo / "scripts"
        scripts.mkdir()
        for name in ("deploy-web.sh", "install-claude-commands.sh"):
            f = scripts / name
            f.write_text(f'#!/bin/sh\necho ran >> "{self.markers}/{name}"\n')
            f.chmod(0o755)
        (self.repo / "app.txt").write_text("one\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "initial")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.other))

    def push_main(self, subject):
        git(self.other, "checkout", "-q", "main")
        git(self.other, "commit", "-q", "--allow-empty", "-m", subject)
        git(self.other, "push", "-q", "origin", "main")
        return git(self.other, "rev-parse", "HEAD")

    def push_feature(self, subject):
        git(self.other, "checkout", "-q", "-B", "feature", "origin/main")
        git(self.other, "commit", "-q", "--allow-empty", "-m", subject)
        git(self.other, "push", "-q", "origin", "feature")
        return git(self.other, "rev-parse", "HEAD")

    def run_script(self, *args):
        env = {
            "PATH": f"{self.shims}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "CCD_DATA_DIR": str(self.data),
            "CC_REPO": str(self.repo),
            "CCD_LAUNCHER_DIR": str(self.tmp / "launcher"),
        }
        env.update(GIT_ENV)
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, cwd=self.tmp,
                              capture_output=True, text=True, timeout=60)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def assert_untouched(self, before):
        self.assertEqual(self.head(), before)
        self.assertEqual(os.listdir(self.markers), [], "a deploy step or shim ran")
        self.assertFalse((self.home / "command-center").exists(), "go-live wrote under HOME")

    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_default_dry_run_targets_origin_main(self):
        before = self.head()
        new = self.push_main("brand new reviewed change")
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"== deploying main @ {new}", r.stdout)
        self.assertIn("brand new reviewed change", r.stdout)
        self.assertIn("Rollback would be:", r.stdout)
        self.assertIn(str(self.repo), r.stdout)  # the script really used CC_REPO
        self.assertNotIn("NOT main", r.stdout)
        self.assert_untouched(before)

    def test_a_already_at_target(self):
        before = self.head()
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(already at target)", r.stdout)
        self.assert_untouched(before)

    def test_b_bare_word_is_usage_error(self):
        before = self.head()
        r = self.run_script("feature")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)
        self.assert_untouched(before)

    def test_b_branch_without_value_is_usage_error(self):
        before = self.head()
        r = self.run_script("--branch")
        self.assertEqual(r.returncode, 2)
        self.assert_untouched(before)

    def test_c_other_branch_needs_i_know(self):
        before = self.head()
        self.push_feature("risky change")
        r = self.run_script("--branch", "feature")
        self.assertEqual(r.returncode, 2)
        self.assertIn("go-live: feature is not main; deploy only reviewed main, or add --i-know", r.stderr)
        self.assert_untouched(before)

    def test_d_other_branch_with_i_know_dry_run_warns(self):
        before = self.head()
        feat = self.push_feature("risky change")
        r = self.run_script("--branch", "feature", "--i-know", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"== deploying feature @ {feat}", r.stdout)
        self.assertIn("NOT main", r.stdout)
        self.assertIn("risky change", r.stdout)
        self.assert_untouched(before)

    def test_e_rollback_text_from_main_and_detached(self):
        full = self.head()
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"git switch --detach {full} && server/.venv/bin/pip install -q -r server/requirements.txt "
                      "&& scripts/deploy-web.sh", r.stdout)
        self.assertIn("Rollback (back to main @", r.stdout)
        self.assertIn("(then git switch main once fixed)", r.stdout)
        self.assertIn("cp ", r.stdout)  # the tasks.db restore line stays
        git(self.repo, "switch", "-q", "--detach")
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"git switch --detach {full} &&", r.stdout)
        self.assertIn("Rollback (back to HEAD @", r.stdout)
        self.assert_untouched(full)

    def test_f_diverged_local_main_is_refused(self):
        self.push_main("origin side")
        (self.repo / "app.txt").write_text("local only\n")
        git(self.repo, "commit", "-q", "-am", "local side")
        before = self.head()
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("local main has diverged", r.stderr)
        self.assert_untouched(before)

    def test_g_dirty_tracked_file_is_refused(self):
        (self.repo / "app.txt").write_text("edited\n")
        before = self.head()
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("uncommitted changes", r.stderr)
        self.assert_untouched(before)

    def refs(self):
        return git(self.repo, "for-each-ref"), git(self.origin, "for-each-ref")

    def test_h_refspec_branch_values_are_refused_and_change_no_refs(self):
        self.push_feature("feature work")
        before = self.head()
        refs = self.refs()
        for value in ("main:refs/heads/x", "feature:refs/remotes/origin/main", "main:"):
            for extra in ((), ("--dry-run",)):
                with self.subTest(value=value, extra=extra):
                    r = self.run_script("--branch", value, "--i-know", *extra)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("usage:", r.stderr)
                    self.assertNotIn("== fetch", r.stdout)
                    self.assertEqual(self.refs(), refs)
                    self.assert_untouched(before)

    def test_i_other_invalid_branch_names_are_refused(self):
        before = self.head()
        refs = self.refs()
        for value in ("a..b", "a b", "x.lock", "a~1", "@{-1}", "feature/"):
            with self.subTest(value=value):
                r = self.run_script("--branch", value, "--i-know", "--dry-run")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.refs()[0], refs[0])
                self.assert_untouched(before)

    def test_j_dry_run_lists_commits_leaving_live(self):
        git(self.repo, "switch", "-q", "-c", "work")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "only on the live checkout")
        before = self.head()
        new = self.push_main("arriving from main")
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"== deploying main @ {new}", r.stdout)
        arriving, leaving = r.stdout.split("leaving live:")
        self.assertIn("arriving from main", arriving)
        self.assertNotIn("only on the live checkout", arriving)
        self.assertIn("only on the live checkout", leaving.split("Rollback would be:")[0])
        self.assertNotIn("arriving from main", leaving)
        self.assert_untouched(before)

    def test_k_nothing_leaving_live_prints_none(self):
        before = self.head()
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("leaving live:\n(none)\n", r.stdout)
        self.assert_untouched(before)

    def test_l_feature_branch_fetch_updates_only_its_tracking_ref(self):
        feat = self.push_feature("risky change")
        before = self.head()
        main_ref = git(self.repo, "rev-parse", "refs/remotes/origin/main")
        r = self.run_script("--branch", "feature", "--i-know", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git(self.repo, "rev-parse", "refs/remotes/origin/feature"), feat)
        self.assertEqual(git(self.repo, "rev-parse", "refs/remotes/origin/main"), main_ref)
        self.assert_untouched(before)


if __name__ == "__main__":
    unittest.main()
