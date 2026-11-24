"""scripts/go-live.sh (CC-030): deploys origin/main by default, other branches only with --i-know.

Every run is against a throw-away clone (CC_REPO), a temp HOME and CCD_DATA_DIR, and PATH shims for
systemctl, curl and go that leave a marker and fail. Only --dry-run and refusal paths are exercised, so no
deploy step (pip, deploy-web.sh, ccd restart) ever runs.
"""
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
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
    """The throw-away clone, origin and shims; no tests of its own."""

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

    def run_script(self, *args, env=None, timeout=60):
        env_extra = env or {}
        env = {
            "PATH": f"{self.shims}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "CCD_DATA_DIR": str(self.data),
            "CC_REPO": str(self.repo),
            "CCD_LAUNCHER_DIR": str(self.tmp / "launcher"),
        }
        env.update(GIT_ENV)
        env.update(env_extra)
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, cwd=self.tmp,
                              capture_output=True, text=True, timeout=timeout)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def assert_untouched(self, before):
        self.assertEqual(self.head(), before)
        self.assertEqual(os.listdir(self.markers), [], "a deploy step or shim ran")
        self.assertFalse((self.home / "command-center").exists(), "go-live wrote under HOME")



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

    def release(self, sha, suffix=""):
        """Point the UI release ccd serves at <sha>, named the way deploy-web.sh names it."""
        web = self.home / ".local" / "share" / "command-center" / "web"
        (web / "releases").mkdir(parents=True, exist_ok=True)
        (web / "current").unlink(missing_ok=True)
        (web / "current").symlink_to(f"releases/20261012T000000Z-{sha[:7]}{suffix}")

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
        self.assertIn(f"Rollback (back to live @ {live[:12]}):", r.stdout)
        self.assertIn(f"git switch --detach {live} &&", r.stdout)
        arriving = r.stdout.split("leaving live:")[0]
        self.assertIn("merged and pulled, never deployed", arriving)  # not live yet, so it arrives
        self.assertIn("merged since", arriving)
        self.assertIn(f"== deploying main @ {new}", r.stdout)
        self.assert_untouched(pulled)

    def test_n_live_release_matching_head_or_unknown_falls_back_quietly(self):
        before = self.head()
        self.release(before, "-dirty")
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("note:", r.stdout)
        self.assertIn("Rollback (back to main @", r.stdout)
        self.release("0" * 40)  # a rev this checkout does not have
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"note: cannot tell the live version", r.stdout)
        self.assertIn(f"git switch --detach {before} &&", r.stdout)
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


SYSTEMCTL_SHIM = """#!/bin/sh
echo "$@" >> "{m}/systemctl"
case "$1 $2" in
  "--user is-active") exit $([ -f "{m}/active.$4" ] && echo 0 || echo 1) ;;
esac
exit 0
"""

# Plays systemd-run and the release watcher: records every argument, then writes the verdict the test chose
# (watch-mode) into result.json after a moment, as the real watcher does. "hang" never ends, "die" ends with none.
SYSTEMD_RUN_SHIM = """#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a" >> "{m}/systemd-run"; done
echo '---' >> "{m}/systemd-run"
[ -f "{m}/systemd-run.fail" ] && exit 1
unit=""; prev=""
for a in "$@"; do [ "$prev" = "--unit" ] && unit="$a"; prev="$a"; wdir="$a"; done
mode="$(cat "{m}/watch-mode" 2>/dev/null || echo healthy)"
touch "{m}/active.$unit"
case "$mode" in
  hang) ;;
  die) ( sleep 1.5; rm -f "{m}/active.$unit" ) >/dev/null 2>&1 </dev/null & ;;
  *) ( sleep 0.3
       printf '{{"result":"%s","step":"%s","check":"api","reason":"why","restarts":0,"message":"Rollback: release x failed api; live is now y.","notified":true}}\\n' \\
         "$mode" "$(cat "{m}/watch-step" 2>/dev/null)" > "$wdir/result.json.tmp"
       mv "$wdir/result.json.tmp" "$wdir/result.json"
       rm -f "{m}/active.$unit" ) >/dev/null 2>&1 </dev/null & ;;
esac
exit 0
"""


# Stands in for the committed watcher: --recover leaves a marker next to itself so a test can see it was run.
WATCHER_STUB = (
    "import sys, os\n"
    "if '--recover' in sys.argv:\n"
    "    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recovered'), 'w').write('1')\n"
)

# date +%s from a script the test controls: the values in clock-seq first, then +30 s per call. Every other use of
# date is the real one (the stamp), so the deadline tests need no sleeping and no wall-clock timing.
DATE_SHIM = """#!/bin/sh
if [ "$1" = "+%s" ]; then
  echo x >> "{m}/date-calls"
  cur="$(cat "{m}/clock" 2>/dev/null || echo 1000)"
  next="$(head -n 1 "{m}/clock-seq" 2>/dev/null)"
  if [ -n "$next" ]; then sed -i 1d "{m}/clock-seq"; cur="$next"; else cur=$((cur + 30)); fi
  echo "$cur" > "{m}/clock"
  echo "$cur"
  exit 0
fi
exec /bin/date "$@"
"""


class GoLiveRunTest(GoLiveBase):
    """CC-063: a REAL go-live run against the throw-away clone, with systemd-run and the watcher faked. Nothing here
    can reach the live install: HOME, CCD_DATA_DIR, CC_REPO and PATH are all temp."""

    def setUp(self):
        super().setUp()
        for name, body in (("systemctl", SYSTEMCTL_SHIM), ("systemd-run", SYSTEMD_RUN_SHIM)):
            f = self.shims / name
            f.write_text(body.format(m=self.markers))
            f.chmod(0o755)
        (self.repo / "server" / "ccd").mkdir(parents=True)
        (self.repo / "server" / "ccd" / "release_watch.py").write_text(WATCHER_STUB)
        (self.repo / "server" / "requirements.txt").write_text("a==1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "server files")
        git(self.repo, "push", "-q", "origin", "main")
        venv = self.repo / "server" / ".venv" / "bin"   # untracked, so the "no uncommitted changes" check ignores it
        venv.mkdir(parents=True)
        (venv / "pip").write_text(f'#!/bin/sh\necho "$@" >> "{self.markers}/pip"\n'
                                  f'[ "$1" = download ] && [ -f "{self.markers}/pip.fail" ] && exit 1\nexit 0\n')
        (venv / "python").write_text('#!/bin/sh\nexec python3 "$@"\n')
        for f in venv.iterdir():
            f.chmod(0o755)
        self.deploys = self.home / "command-center" / "deploys" / "commandcenter"
        self.watch_root = self.deploys / "watch"
        self.web = self.home / ".local" / "share" / "command-center" / "web"
        git(self.other, "pull", "-q", "origin", "main")
        self.new = self.push_main("the release going live")

    def mode(self, mode, step=""):
        (self.markers / "watch-mode").write_text(mode)
        (self.markers / "watch-step").write_text(step)

    def watch_dirs(self):
        return sorted(p for p in self.watch_root.iterdir() if p.is_dir()) if self.watch_root.exists() else []

    def sysrun_calls(self):
        text = (self.markers / "systemd-run").read_text()
        return [c.rstrip("\n").split("\n") for c in text.split("---\n") if c]

    def ran(self, name):
        return (self.markers / name).exists()

    # ---- exit codes and the words

    def test_healthy_watch_exits_0_and_the_rest_of_go_live_is_as_before(self):
        self.mode("healthy")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("release watch: healthy", r.stdout)
        self.assertIn(f"Live is on main ({self.new[:7]})", r.stdout)
        self.assertIn("Rollback: automatic", r.stdout)             # no direct database replacement on the success path
        self.assertNotIn("cp \"", r.stdout)
        self.assertEqual(self.head(), self.new)
        self.assertIn("restart ccd", (self.markers / "systemctl").read_text())

    def test_failed_watch_exit_codes_and_words(self):
        for mode, code, words in (("rolled_back", 3, "ROLLED BACK"), ("rollback_failed", 4, "ROLLBACK FAILED"),
                                  ("no_previous", 5, "NO PREVIOUS RELEASE")):
            with self.subTest(mode=mode):
                self.setUp()
                self.mode(mode, "verify")
                r = self.run_script()
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                self.assertIn(words, r.stdout)
                (wd,) = self.watch_dirs()
                self.assertIn(f"{wd}/watch.log", r.stdout)
                self.assertIn("deployed <KEY> --role coordinator --env live --result fail", r.stdout)

    def test_wait_bound_exits_6_and_result_reports_the_same_code(self):
        self.mode("hang")
        r = self.run_script(env={"CC_GOLIVE_DEADLINE_S": "2"})
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("scripts/go-live.sh --result", r.stdout)
        r = self.run_script("--result")
        self.assertEqual(r.returncode, 6)
        self.assertIn("still watching", r.stdout)
        (wd,) = self.watch_dirs()
        unit = f"cc-release-watch-{wd.name}"
        for mode, code in (("rolled_back", 3), ("rollback_failed", 4), ("no_previous", 5), ("healthy", 0)):
            (wd / "result.json").write_text(json.dumps({"result": mode, "step": "x", "check": "api"}))
            self.assertEqual(self.run_script("--result").returncode, code, mode)
        (wd / "result.json").unlink()
        (self.markers / f"active.{unit}").unlink()          # the watcher is gone and left no verdict
        r = self.run_script("--result")
        self.assertEqual(r.returncode, 4, r.stdout)
        self.assertIn("ROLLBACK FAILED", r.stdout)
        self.assertIn("start ccd", (self.markers / "systemctl").read_text().split("restart ccd")[-1],
                      "a stopped ccd is started by go-live.sh itself")

    def fake_clock(self, *seq):
        date = self.shims / "date"
        date.write_text(DATE_SHIM.format(m=self.markers))
        date.chmod(0o755)
        (self.markers / "clock-seq").write_text("".join(f"{v}\n" for v in seq))

    def test_the_deadline_counts_from_the_start_of_the_script(self):
        # Script start = t 1000; the first look at the verdict is at t 1240, i.e. the steps before the restart took 4
        # minutes; then 30 s per poll. The bound (540 s from the start) must end the wait at t 1540: 10 polls. A
        # deadline that restarted after the build would need 18.
        self.fake_clock(1000, 1240)
        self.mode("hang")
        try:
            r = self.run_script(env={"CC_GOLIVE_DEADLINE_S": "540"}, timeout=25)
        except subprocess.TimeoutExpired:
            self.fail("go-live.sh never gave up waiting: the deadline is not enforced")
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        calls = len((self.markers / "date-calls").read_text().split())
        self.assertLessEqual(calls, 14, "the wait must count from the start of the script")
        self.assertGreaterEqual(calls, 6)

    def test_the_deadline_is_checked_before_systemctl_can_hang(self):
        # a systemctl that never returns for is-active must not push the exit past the bound
        self.fake_clock(1000, 5000)       # the bound has long passed at the first look
        self.mode("hang")
        shim = SYSTEMCTL_SHIM.format(m=self.markers).replace(
            'case "$1 $2" in',
            'if [ "$1 $2" = "--user is-active" ]; then\n'
            f'  n=$(cat "{self.markers}/n" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "{self.markers}/n"\n'
            '  [ "$n" -gt 1 ] && sleep 20\nfi\ncase "$1 $2" in', 1)
        (self.shims / "systemctl").write_text(shim)
        try:
            r = self.run_script(env={"CC_GOLIVE_DEADLINE_S": "540"}, timeout=15)
        except subprocess.TimeoutExpired:
            self.fail("the deadline was checked after a systemctl call that can hang")
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)

    def test_a_watcher_that_dies_without_a_verdict_gets_ccd_started_and_exits_4(self):
        self.mode("die")
        r = self.run_script()
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("ROLLBACK FAILED at watcher_died", r.stdout)
        calls = (self.markers / "systemctl").read_text().splitlines()
        self.assertIn("--user start ccd", calls)

    # ---- systemd-run arguments and failure

    def test_systemd_run_gets_explicit_environment_and_exec_stop_post(self):
        self.mode("healthy")
        r = self.run_script(env={"CCD_PORT": "7788", "CCD_TOKEN_FILE": str(self.tmp / "tok"),
                                 "CCD_HERDR_SOCKET": str(self.tmp / "h.sock")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (call,) = self.sysrun_calls()
        (wd,) = self.watch_dirs()
        for want in ("--user", "--unit", f"cc-release-watch-{wd.name}", "--collect",
                     "CCD_PORT=7788", f"CCD_WEB_DIR={self.web}", f"CCD_DATA_DIR={self.data}",
                     f"CC_REPO={self.repo}", f"CCD_TOKEN_FILE={self.tmp / 'tok'}",
                     f"CCD_HERDR_SOCKET={self.tmp / 'h.sock'}", f"HOME={self.home}"):
            self.assertIn(want, call)
        # the watcher dying after stop must not leave ccd stopped (Restart=always ignores a stopped unit)
        stop_post = [a for a in call if a.startswith("ExecStopPost=")]
        self.assertEqual(len(stop_post), 2)
        self.assertIn("--recover", stop_post[0], "an interrupted rollback is undone before ccd is started")
        self.assertTrue(stop_post[0].startswith("ExecStopPost=-"), "and a failing recovery must not skip the start")
        self.assertTrue(stop_post[1].endswith(" --user start ccd"), stop_post)
        self.assertEqual(call[-2:], [str(wd / "release_watch.py"), str(wd)])
        self.assertTrue(any(a.startswith("PATH=") for a in call))
        copy = wd / "release_watch.py"
        self.assertEqual(copy.read_text(), WATCHER_STUB, "it runs from a copy, not the checkout")
        plan = json.loads((wd / "plan.json").read_text())
        self.assertEqual((plan["to_sha"], plan["unit"]), (self.new, f"cc-release-watch-{wd.name}"))
        self.assertFalse(plan["pins_differ"])

    def test_systemd_run_failure_is_not_watched_and_exits_7(self):
        (self.markers / "systemd-run.fail").write_text("")
        r = self.run_script()
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn("NOT WATCHED", r.stderr)
        self.assertIn("Do not record the ticket deployed; tell Jay", r.stderr)
        self.assertIn("git switch --detach", r.stderr)               # the manual rollback is printed

    def test_a_unit_that_never_becomes_active_is_not_watched(self):
        # systemd-run said yes but the unit is not there 5 s later
        shim = self.shims / "systemd-run"
        shim.write_text("#!/bin/sh\nexit 0\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn("NOT WATCHED", r.stderr)

    # ---- review round 2: setup and restart failures go through the watch, exact targets, lock handoff

    def test_a_failed_restart_still_goes_through_the_release_watch(self):
        # under set -e a failing `systemctl restart ccd` used to end the script with the new release down, unwatched
        (self.shims / "systemctl").write_text(SYSTEMCTL_SHIM.format(m=self.markers).replace(
            'case "$1 $2" in', 'if [ "$1" = "--user" ] && [ "$2" = restart ]; then exit 1; fi\ncase "$1 $2" in', 1))
        self.mode("rolled_back")
        r = self.run_script()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("systemctl restart ccd failed", r.stderr)
        self.assertEqual(len(self.sysrun_calls()), 1, "the watcher was started")

    def test_a_target_without_the_watcher_file_is_not_watched_exit_7_and_ccd_is_started(self):
        git(self.other, "rm", "-q", "server/ccd/release_watch.py")
        git(self.other, "commit", "-q", "-m", "predates the watcher")
        git(self.other, "push", "-q", "origin", "main")
        # the live checkout is only behind origin, and the file exists in neither
        git(self.repo, "fetch", "-q", "origin")
        git(self.repo, "reset", "-q", "--hard", "origin/main")
        git(self.other, "commit", "-q", "--allow-empty", "-m", "a release that predates the watcher")
        git(self.other, "push", "-q", "origin", "main")
        r = self.run_script()
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn("NOT WATCHED", r.stderr)
        self.assertIn("--user start ccd", (self.markers / "systemctl").read_text())
        self.assertFalse((self.watch_root / "active.json").exists())
        self.assertFalse(self.ran("systemd-run"))

    def test_active_json_exists_before_the_watcher_is_started(self):
        shim = self.shims / "systemd-run"
        shim.write_text(f'#!/bin/sh\n[ -f "{self.watch_root}/active.json" ] && echo yes > "{self.markers}/marker-first"\n'
                        + SYSTEMD_RUN_SHIM.format(m=self.markers).split("\n", 1)[1])
        self.mode("healthy")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.markers / "marker-first").exists(), "no moment with a live watcher and no marker")

    def test_a_marker_for_a_watcher_that_never_started_is_removed(self):
        (self.markers / "systemd-run.fail").write_text("")
        r = self.run_script()
        self.assertEqual(r.returncode, 7)
        self.assertFalse((self.watch_root / "active.json").exists())

    def test_the_previous_release_must_name_one_exact_commit(self):
        for name, ok in ((f"20261012T000000Z-{{sha}}-dirty", False), ("20261012T000000Z-0000000", False),
                         ("20261012T000000Z-{sha}", True)):
            with self.subTest(name=name):
                self.setUp()
                sha = self.head()
                rel = self.web / "releases" / name.format(sha=sha[:7])
                rel.mkdir(parents=True)
                (rel / "index.html").write_text("<html/>")
                os.symlink(f"releases/{rel.name}", self.web / "current")
                self.mode("healthy")
                r = self.run_script()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                (wd,) = self.watch_dirs()
                plan = json.loads((wd / "plan.json").read_text())
                self.assertEqual(plan["from_sha"], sha if ok else "", "the rollback target is never guessed")
                self.assertEqual("no valid rollback target" in r.stdout, not ok)

    def test_a_second_go_live_during_the_messages_retry_is_not_refused(self):
        # the verdict is final: lock free, marker gone, the watcher unit still alive retrying Messages
        d = self.make_watch("20261130T090000", {"result": "rolled_back", "notified": None, "message": "m"})
        (self.markers / "active.cc-release-watch-20261130T090000").write_text("")
        self.mode("healthy")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(d.exists())

    def test_the_watcher_that_died_is_recovered_before_ccd_is_started(self):
        self.mode("die")
        r = self.run_script()
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        (wd,) = self.watch_dirs()
        self.assertTrue((wd / "recovered").exists(), "--recover ran (undoes a half-done rollback)")
        order = (self.markers / "systemctl").read_text()
        self.assertIn("--user start ccd", order)

    def test_a_refused_run_writes_no_ref_and_nothing_under_home(self):
        self.hold_lock()
        refs = self.refs()
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.refs(), refs, "refused before the fetch")

    # ---- the lock

    def refs(self):
        return git(self.repo, "for-each-ref"), git(self.origin, "for-each-ref")

    def hold_lock(self):
        self.deploys.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.deploys / ".go-live.lock", os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.addCleanup(os.close, fd)

    def assert_nothing_deployed(self, before):
        self.assertEqual(self.head(), before)
        for name in ("pip", "systemd-run", "deploy-web.sh", "install-claude-commands.sh"):
            self.assertFalse(self.ran(name), f"{name} ran")
        self.assertFalse((self.home / "command-center" / "backups").exists(), "a backup was started")

    def test_second_go_live_while_the_lock_is_held_refuses_before_any_change(self):
        before = self.head()
        self.hold_lock()
        r = self.run_script()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("holds", r.stderr)
        self.assert_nothing_deployed(before)

    def test_second_go_live_while_a_watch_unit_is_active_refuses_before_any_change(self):
        before = self.head()
        self.watch_root.mkdir(parents=True)
        (self.watch_root / "active.json").write_text(json.dumps({"unit": "cc-release-watch-20261201T100000"}))
        (self.markers / "active.cc-release-watch-20261201T100000").write_text("")
        r = self.run_script()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("still running", r.stderr)
        self.assert_nothing_deployed(before)

    def test_a_stale_active_json_does_not_refuse_and_a_finished_watch_releases_the_lock(self):
        # the watcher clears active.json and frees the lock when its verdict is final, so a fix release is not
        # held up by the 30-minute Messages retry that follows
        self.watch_root.mkdir(parents=True)
        (self.watch_root / "active.json").write_text(json.dumps({"unit": "cc-release-watch-old"}))  # unit not active
        self.mode("healthy")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        fd = os.open(self.deploys / ".go-live.lock", os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)      # go-live let go of it
        finally:
            os.close(fd)
        self.assertTrue(json.loads((self.watch_root / "active.json").read_text())["unit"].startswith("cc-release-watch-2"))

    def test_dry_run_takes_no_lock(self):
        self.hold_lock()
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # ---- notices on every run, dry run included

    def make_watch(self, name, result=None, active=False, age=3600):
        d = self.watch_root / name
        d.mkdir(parents=True)
        (d / "plan.json").write_text("{}")
        if result is not None:
            (d / "result.json").write_text(json.dumps(result))
        if active:
            (self.markers / f"active.cc-release-watch-{name}").write_text("")
        old = time.time() - age
        os.utime(d, (old, old))
        return d

    def test_watcher_died_is_printed_by_every_run_dry_run_included(self):
        self.make_watch("20261130T090000")
        for args in (("--dry-run",), ("--dry-run", "--branch", "main")):
            r = self.run_script(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WATCHER DIED: 20261130T090000", r.stdout)

    def test_unnotified_rollbacks_are_printed_and_notified_or_healthy_ones_are_not(self):
        self.make_watch("20261130T090000", {"result": "rolled_back", "notified": False, "message": "Rollback: X"})
        self.make_watch("20261130T100000", {"result": "rolled_back", "notified": True})
        self.make_watch("20261130T110000", {"result": "healthy", "notified": None})
        self.make_watch("20261130T120000", active=True, age=3600)          # still watching: not dead
        self.make_watch("20261130T130000", age=2)                          # just created: its unit is starting
        r = self.run_script("--dry-run")
        self.assertIn("UNNOTIFIED: 20261130T090000", r.stdout)
        self.assertIn("Rollback: X", r.stdout)
        for quiet in ("20261130T100000", "20261130T110000", "20261130T120000", "20261130T130000"):
            self.assertNotIn(quiet, r.stdout)

    # ---- pins: both sets downloaded during go-live, before anything changes

    def test_pins_that_differ_download_both_sets_before_the_switch(self):
        self.push_main("pins moved")
        (self.other / "server").mkdir(exist_ok=True)
        (self.other / "server" / "requirements.txt").write_text("a==2\n")
        git(self.other, "commit", "-q", "-am", "bump a")
        git(self.other, "push", "-q", "origin", "main")
        self.mode("healthy")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pip = (self.markers / "pip").read_text().splitlines()
        downloads = [l for l in pip if l.startswith("download")]
        self.assertEqual(len(downloads), 2)
        self.assertLess(pip.index(downloads[1]), next(i for i, l in enumerate(pip) if l.startswith("install")))
        (wd,) = self.watch_dirs()
        self.assertEqual((wd / "wheels" / "old.txt").read_text(), "a==1\n")
        self.assertEqual((wd / "wheels" / "new.txt").read_text(), "a==2\n")
        self.assertTrue(json.loads((wd / "plan.json").read_text())["pins_differ"])

    def test_unchanged_pins_download_nothing(self):
        self.mode("healthy")
        self.run_script()
        self.assertFalse([l for l in (self.markers / "pip").read_text().splitlines() if l.startswith("download")])

    def test_wheels_that_cannot_be_downloaded_stop_go_live_before_any_change(self):
        (self.other / "server").mkdir(exist_ok=True)
        (self.other / "server" / "requirements.txt").write_text("a==2\n")
        git(self.other, "commit", "-q", "-am", "bump a")
        git(self.other, "push", "-q", "origin", "main")
        (self.markers / "pip.fail").write_text("")
        before = self.head()
        r = self.run_script()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("could not download the wheels", r.stderr)
        self.assertEqual(self.head(), before)
        self.assertFalse(self.ran("deploy-web.sh"))
        self.assertFalse((self.home / "command-center" / "backups").exists())

    # ---- what is recorded before the switch

    def test_the_exact_previous_ui_release_and_schema_are_recorded_before_the_switch(self):
        import sqlite3
        rel = self.web / "releases" / "20261012T000000Z-abcdef0"
        rel.mkdir(parents=True)
        (rel / "index.html").write_text("<html/>")
        os.symlink("releases/20261012T000000Z-abcdef0", self.web / "current")
        db = sqlite3.connect(self.data / "tasks.db")
        db.execute("PRAGMA user_version = 14")
        db.commit()
        db.close()
        self.mode("healthy")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (wd,) = self.watch_dirs()
        plan = json.loads((wd / "plan.json").read_text())
        self.assertEqual(plan["prev_web"], str(rel))
        self.assertEqual(plan["prev_schema"], 14)
        self.assertEqual(plan["from_sha"], git(self.repo, "rev-parse", "HEAD~1") if False else plan["from_sha"])

    def test_old_watch_dirs_are_pruned_to_the_newest_few(self):
        for i in range(9):
            self.make_watch(f"2026110{i + 1}T000000", {"result": "healthy"})
        self.mode("healthy")
        self.run_script()
        left = [p.name for p in self.watch_dirs()]
        self.assertEqual(len(left), 6)
        self.assertNotIn("20261101T000000", left)

    # ---- the coordinator's runbook (tech review: without it the coordinator and the watcher both roll back)

    def test_readme_tells_the_coordinator_the_watch_rolls_back_by_itself(self):
        text = (SCRIPT.parents[1] / "README.md").read_text()
        for needle in ("rolls back by itself", "never roll back by hand while a watch is active",
                       "scripts/go-live.sh --result", "exit 0", "exit 3", "exit 4", "exit 5", "exit 6", "exit 7", "exit 8",
                       "go-live-auto-rollback.md"):
            self.assertIn(needle.lower(), text.lower())


if __name__ == "__main__":
    unittest.main()
