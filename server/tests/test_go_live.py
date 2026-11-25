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


class GoLiveBase(unittest.TestCase):
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
        self.release(self.head())   # a previous release is recorded unless a test removes it (CC-063)

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
        env.update(getattr(self, "extra_env", {}))
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, cwd=self.tmp,
                              capture_output=True, text=True, timeout=60)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def assert_untouched(self, before):
        self.assertEqual(self.head(), before)
        self.assertEqual(os.listdir(self.markers), [], "a deploy step or shim ran")
        self.assertFalse((self.home / "command-center").exists(), "go-live wrote under HOME")

    def refs(self):
        return git(self.repo, "for-each-ref"), git(self.origin, "for-each-ref")

    def release(self, sha, suffix=""):
        """Point the UI release ccd serves at <sha>, named the way deploy-web.sh names it, with its index.html."""
        web = self.home / ".local" / "share" / "command-center" / "web"
        name = f"20261012T000000Z-{sha[:7]}{suffix}"
        (web / "releases" / name).mkdir(parents=True, exist_ok=True)
        (web / "releases" / name / "index.html").write_text("<html></html>")
        (web / "current").unlink(missing_ok=True)
        (web / "current").symlink_to(f"releases/{name}")


class GoLiveTest(GoLiveBase):
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

    def test_e_rollback_text_names_the_recorded_release_and_never_copies_the_backup(self):
        full = self.head()
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"Rollback (back to release 20261012T000000Z-{full[:7]} @ {full[:12]}):", r.stdout)
        self.assertIn(f"git switch --detach {full}", r.stdout)
        self.assertIn("server/.venv/bin/pip install -q -r server/requirements.txt", r.stdout)
        self.assertIn("ln -sfn releases/20261012T000000Z-", r.stdout)   # re-points web/current, no npm rebuild
        self.assertIn("mv -T", r.stdout)
        self.assertNotIn("deploy-web.sh", r.stdout.split("Rollback would be:")[1])
        self.assertNotIn("cp ", r.stdout.split("Rollback would be:")[1])  # Q182: the backup is never copied back
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
        self.release(before)
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

    def test_m_rollback_names_what_is_live_when_the_checkout_was_pulled_ahead(self):
        # CC-051: a git pull in the live checkout moved HEAD past what ccd serves; the rollback named HEAD
        live = self.head()
        self.release(live)
        pulled = self.push_main("merged and pulled, never deployed")
        git(self.repo, "pull", "-q", "--ff-only")
        new = self.push_main("merged since")
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"note: the checkout is at {pulled[:12]} but live is {live[:12]}", r.stdout)
        self.assertIn(f"@ {live[:12]}):", r.stdout)
        self.assertIn(f"git switch --detach {live}", r.stdout)
        arriving = r.stdout.split("leaving live:")[0]
        self.assertIn("merged and pulled, never deployed", arriving)  # not live yet, so it arrives
        self.assertIn("merged since", arriving)
        self.assertIn(f"== deploying main @ {new}", r.stdout)
        self.assert_untouched(pulled)

    def test_n_no_previous_release_is_said_never_guessed_from_head(self):
        # CC-063: web/current naming no commit used to fall back to HEAD, a guess that could roll back to the wrong code
        before = self.head()
        web = self.home / ".local" / "share" / "command-center" / "web"
        for label, setup in (
            ("no web/current", lambda: (web / "current").unlink()),
            ("a rev this checkout does not have", lambda: self.release("0" * 40)),
            ("a release with no index.html", lambda: (self.release(before), (web / "current").resolve().joinpath("index.html").unlink())),
            ("a name with no commit in it", lambda: ((web / "current").unlink(), (web / "current").symlink_to("releases/odd"))),
        ):
            with self.subTest(label):
                self.release(before)
                setup()
                r = self.run_script("--dry-run")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("no previous release is recorded", r.stdout)
                self.assertNotIn("git switch --detach", r.stdout)
        self.assert_untouched(before)

    def test_n_dirty_release_of_head_is_the_previous_release(self):
        before = self.head()
        self.release(before, "-dirty")
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("note:", r.stdout)
        self.assertIn(f"git switch --detach {before}", r.stdout)
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


class GoLiveRunTest(GoLiveBase):
    """A REAL go-live run (CC-063) in a throw-away clone, HOME and PATH of shims: systemctl, curl and the venv's
    pip and python record what they are asked and change nothing. The release check itself is a stub committed into
    the clone's server/ccd/, so these tests are about go-live's wiring (steps, exit codes, what it never does);
    test_release_check.py covers the check."""

    def setUp(self):
        super().setUp()
        t = self.tmp
        for name in ("systemctl", "curl", "go"):
            (self.shims / name).unlink()
        write(self.shims / "systemctl", f"""#!/bin/sh
echo "$@" >> "{self.markers}/systemctl"
case "$*" in
  *show*) cat "{t}/oldpid" 2>/dev/null; exit 0 ;;
  *restart*) exit "$(cat "{t}/restart_rc" 2>/dev/null || echo 0)" ;;
esac
exit 0
""")
        write(self.shims / "curl", f"""#!/bin/sh
echo "$@" >> "{self.markers}/curl"
cat "{t}/health.json" 2>/dev/null || exit 22
""")
        # committed into the clone, so "git switch" to a new main brings them along
        web = "$HOME/.local/share/command-center/web"
        write(self.repo / "scripts" / "deploy-web.sh", f"""#!/bin/sh
echo ran >> "{self.markers}/deploy-web.sh"
d="releases/20261101T000000Z-$(git rev-parse --short=7 HEAD)"
mkdir -p "{web}/$d" && echo '<html>new</html>' > "{web}/$d/index.html"
ln -sfn "$d" "{web}/current"
""")
        (self.repo / "server" / "ccd").mkdir(parents=True)
        write(self.repo / "server" / "ccd" / "release_check.py", """import os, sys
args = sys.argv[1:]
with open(os.environ["STUB_MARKER"], "a") as f:
    f.write(" ".join(args) + "\\n")
with open(os.environ["STUB_MARKER"] + ".steps", "w") as f:
    f.write(open(args[args.index("--steps-file") + 1]).read())
print(os.environ.get("STUB_OUT", "release check: healthy"))
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
""")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "deploy stubs")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.other, "pull", "-q", "origin", "main")
        self.release(self.head())          # the live release is this commit
        # untracked venv shims
        venv = self.repo / "server" / ".venv" / "bin"
        venv.mkdir(parents=True)
        write(venv / "pip", f'#!/bin/sh\necho "$@" >> "{self.markers}/pip"\nexit "$(cat "{t}/pip_rc" 2>/dev/null || echo 0)"\n')
        write(venv / "python", f'#!/bin/sh\ncat "{t}/new_schema" 2>/dev/null; exit 0\n')
        (t / "oldpid").write_text("400\n")
        (t / "new_schema").write_text("15\n")
        (t / "health.json").write_text('{"tasks": {"schemaVersion": 14}, "herdr": {"ok": true}}')
        self.stub_marker = self.markers.parent / "stub-args"
        self.extra_env = {"STUB_MARKER": str(self.stub_marker)}

    def go(self, **env):
        self.extra_env.update({k: str(v) for k, v in env.items()})
        new = self.push_main("a new reviewed change")
        return new, self.run_script()

    def restarts(self):
        return [l for l in (self.markers / "systemctl").read_text().splitlines() if "restart" in l]

    def check_args(self):
        return self.stub_marker.read_text()

    def steps(self):
        return Path(str(self.stub_marker) + ".steps").read_text()

    def test_c1_healthy_deploys_as_before_and_runs_the_check_once(self):
        live = self.head()
        new, r = self.go()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("release check: healthy", r.stdout)
        self.assertIn(f"Live is on main ({new[:7]})", r.stdout)
        self.assertEqual(self.head(), new)
        self.assertEqual(len(self.restarts()), 1)
        args = self.check_args()
        self.assertEqual(len(args.splitlines()), 1)
        self.assertIn("--old-pid 400", args)
        self.assertIn("--herdr-ok true", args)
        self.assertIn(f"--from {live}", args)
        self.assertIn(f"--to {new}", args)
        self.assertNotIn("do not record", r.stdout + r.stderr)

    def test_c8_failed_check_alerts_and_changes_nothing(self):
        live = self.head()
        new, r = self.go(STUB_EXIT=3, STUB_OUT="Release check FAILED: api")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("do not record deployed as pass", r.stderr)
        self.assertNotIn("Live is on", r.stdout)
        # nothing was rolled back: the checkout is the target, web/current is the new release, one restart only
        self.assertEqual(self.head(), new)
        web = self.home / ".local" / "share" / "command-center" / "web"
        self.assertIn(new[:7], os.readlink(web / "current"))
        self.assertEqual(len(self.restarts()), 1)
        # the steps the check shows name this release's previous commit and release, and never copy the backup
        steps = self.steps()
        self.assertIn(f"git switch --detach {live}", steps)
        self.assertIn(f"ln -sfn releases/20261012T000000Z-{live[:7]}", steps)
        self.assertIn("migration_safety rollback", steps)
        self.assertIn("--to 14", steps)
        self.assertNotIn("cp ", steps)
        self.assertIn("docs/runbooks/tasks-db-v15-rollback.md", steps)

    def test_exit_4_and_2_pass_through_with_the_same_warning(self):
        for code in (4, 2):
            with self.subTest(code=code):
                self.setUp()
                _, r = self.go(STUB_EXIT=code)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                self.assertIn("do not record deployed as pass", r.stderr)

    def test_no_migration_step_when_the_schema_did_not_change(self):
        (self.tmp / "new_schema").write_text("14\n")
        self.go()
        self.assertNotIn("migration_safety", self.steps())
        self.assertIn("no database change", self.steps())

    def test_old_ccd_down_before_the_restart_says_schema_unknown_and_does_not_judge_herdr(self):
        (self.tmp / "health.json").unlink()
        self.go()
        steps = self.steps()
        self.assertNotIn("migration_safety rollback --db", steps)   # no guessed --to
        self.assertIn("not known: do not guess", steps)
        args = self.check_args()
        self.assertIn("--herdr-ok unknown", args)
        self.assertIn("--old-pid 400", args)        # still taken from systemctl's MainPID

    def test_c9_no_previous_release_is_said_in_the_steps_and_never_a_head_guess(self):
        web = self.home / ".local" / "share" / "command-center" / "web"
        (web / "current").unlink()
        _, r = self.go()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no previous release is recorded", self.steps())
        self.assertNotIn("git switch --detach", self.steps())
        self.assertIn("--from  --to", self.check_args())

    def test_a_failing_restart_still_runs_the_check(self):
        (self.tmp / "restart_rc").write_text("1\n")
        _, r = self.go(STUB_EXIT=3)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(self.stub_marker.exists())
        self.assertIn("systemctl restart ccd failed", r.stderr)

    def test_a_failing_step_after_the_switch_prints_where_and_the_steps(self):
        live = self.head()
        (self.tmp / "pip_rc").write_text("1\n")
        new, r = self.go()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("go-live stopped at: server requirements", r.stderr)
        self.assertIn(f"git switch --detach {live}", r.stderr)
        self.assertIn("do not record deployed as pass", r.stderr)
        self.assertFalse(self.stub_marker.exists())     # the check never ran
        self.assertEqual(self.restarts(), [])

    def test_c9_the_check_is_a_stdlib_file_run_isolated(self):
        script = SCRIPT.read_text()
        self.assertIn('python3 -I "$REPO/server/ccd/release_check.py"', script)
        # the live script never rolls back itself: no stop/start of ccd and no git switch outside the printed steps
        deploy_part = script.split('echo "== restart ccd"')[1].split("cat <<EOF")[0]
        self.assertNotIn("stop ccd", deploy_part)
        self.assertNotIn("switch --detach", deploy_part)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
