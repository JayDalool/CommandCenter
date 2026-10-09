"""CC-024: a DONE ticket's worktree is removed only when nothing can be lost.

Real git, in temp dirs: a bare "remote", a clone, and linked worktrees. Each check that must keep
a worktree has its own test; the happy path proves the branch survives.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from ccd import registry, worktree_cleanup
from ccd.daemon import Daemon
from ccd.pipeline import Pipeline
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, fake_git, fake_host, new_db

BRANCH = "CC-024-cleanup"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


def commit(cwd, name, text="x\n"):
    with open(os.path.join(cwd, name), "w") as f:
        f.write(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", f"add {name}")


class Repos(unittest.TestCase):
    """tmp/remote.git (bare) ← tmp/repo (clone, main) and tmp/worktrees/CC-024 on BRANCH, pushed."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="wtc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote = os.path.join(self.tmp, "remote.git")
        self.repo = os.path.join(self.tmp, "repo")
        self.root = os.path.join(self.tmp, "worktrees")
        os.makedirs(self.root)
        git(self.tmp, "init", "-q", "--bare", "-b", "main", self.remote)
        git(self.tmp, "clone", "-q", self.remote, self.repo)
        git(self.repo, "checkout", "-q", "-b", "main")
        commit(self.repo, "README.md")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.wt = self.add_worktree(os.path.join(self.root, "CC-024"), BRANCH)

    def add_worktree(self, path, branch, push=True):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(self.repo, "worktree", "add", "-q", "-b", branch, path)
        if push:
            git(path, "push", "-q", "-u", "origin", branch)
        return path

    def blocker(self, path=None, branch=BRANCH, cwds=(), repo=None):
        return worktree_cleanup.blocker(repo or self.repo, path or self.wt, branch, list(cwds) if cwds is not None else None,
                                        root=self.root)

    def run_all(self, path=None, branch=BRANCH, cwds=()):
        return worktree_cleanup.run([("CC-024", "commandcenter", self.repo, branch, path or self.wt)], list(cwds),
                                    root=self.root)

    def assertKept(self, reason_part, **kw):
        why = self.blocker(**kw)
        self.assertIsNotNone(why)
        self.assertIn(reason_part, why)
        self.assertTrue(os.path.isdir(kw.get("path") or self.wt))


class Removal(Repos):
    def test_clean_pushed_worktree_is_removed_and_the_branch_stays(self):
        self.assertIsNone(self.blocker())
        out = self.run_all()
        self.assertEqual([(o[3], o[4]) for o in out], [("removed", None)])
        self.assertFalse(os.path.exists(self.wt))
        self.assertIn(BRANCH, git(self.repo, "branch", "--list", BRANCH))
        self.assertNotIn(self.wt, git(self.repo, "worktree", "list", "--porcelain"))
        # the commits are still there, on the remote too: the worktree can be recreated
        git(self.repo, "worktree", "add", "-q", self.wt, BRANCH)
        self.assertTrue(os.path.isdir(self.wt))

    def test_ignored_files_go_with_it(self):
        commit(self.wt, ".gitignore", "node_modules/\n")
        git(self.wt, "push", "-q")
        os.makedirs(os.path.join(self.wt, "node_modules"))
        with open(os.path.join(self.wt, "node_modules", "x.js"), "w") as f:
            f.write("1\n")
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(self.run_all()[0][3], "removed")
        self.assertFalse(os.path.exists(self.wt))

    def test_claude_worktrees_folder_of_the_project_is_allowed_with_the_branch(self):
        inside = self.add_worktree(os.path.join(self.repo, ".claude", "worktrees", "CC-024"), BRANCH + "-b")
        self.assertIsNone(self.blocker(path=inside, branch=BRANCH + "-b"))
        self.assertEqual(self.run_all(path=inside, branch=BRANCH + "-b")[0][3], "removed")
        self.assertFalse(os.path.exists(inside))

    def test_ordinary_ignored_files_do_not_block_removal(self):
        commit(self.wt, ".gitignore", "node_modules/\n.venv/\n*.log\n")
        git(self.wt, "push", "-q")
        for d in ("node_modules/pkg/lib", ".venv/lib/site-packages"):
            os.makedirs(os.path.join(self.wt, d))
            with open(os.path.join(self.wt, d, "f.js"), "w") as f:
                f.write("1\n")
        with open(os.path.join(self.wt, "run.log"), "w") as f:
            f.write("1\n")
        self.assertIsNone(self.blocker())
        self.assertEqual(self.run_all()[0][3], "removed")

    def test_a_missing_path_is_silently_skipped(self):
        shutil.rmtree(self.wt)
        self.assertEqual(self.run_all(), [])

    def test_only_worktree_remove_without_force_is_ever_called(self):
        calls = []
        with mock.patch.object(worktree_cleanup, "_git", lambda cwd, *a, **k: calls.append((cwd, a)) or (0, "", "")):
            self.assertEqual(worktree_cleanup.remove(self.repo, self.wt), (True, ""))
        self.assertEqual(calls, [(self.repo, ("worktree", "remove", self.wt))])


class Keeps(Repos):
    def test_outside_the_worktree_folders(self):
        other = self.add_worktree(os.path.join(self.tmp, "elsewhere", "CC-024"), BRANCH + "-c")
        self.assertKept("outside the worktree folders", path=other, branch=BRANCH + "-c")

    def test_the_root_itself_is_never_removed(self):
        self.assertIn("outside", self.blocker(path=self.root))

    def test_other_claude_folder_names_under_the_repo_are_not_allowed(self):
        other = self.add_worktree(os.path.join(self.repo, ".claude", "other", "CC-024"), BRANCH + "-d")
        self.assertKept("outside the worktree folders", path=other, branch=BRANCH + "-d")

    def test_symlink_to_a_worktree(self):
        link = os.path.join(self.root, "link")
        os.symlink(self.wt, link)
        self.assertKept("symlink", path=link)
        self.assertEqual(self.run_all(path=link)[0][3], "kept")

    def test_symlinked_parent_folder(self):
        os.makedirs(os.path.join(self.tmp, "real"))
        os.symlink(os.path.join(self.tmp, "real"), os.path.join(self.root, "dir"))
        path = os.path.join(self.root, "dir", "CC-024b")
        git(self.repo, "worktree", "add", "-q", "-b", BRANCH + "-e", os.path.join(self.tmp, "real", "CC-024b"))
        self.assertIn("symlink", self.blocker(path=path, branch=BRANCH + "-e"))

    def test_ignored_nested_linked_worktree_with_a_dirty_file_is_kept(self):
        # a Claude Code subagent worktree inside the ticket worktree, ignored like GauzeMate's .git/info/exclude
        commit(self.wt, ".gitignore", ".claude/\n")
        git(self.wt, "push", "-q")
        nested = os.path.join(self.wt, ".claude", "worktrees", "agent-x")
        os.makedirs(os.path.dirname(nested))
        git(self.repo, "worktree", "add", "-q", "-b", "worktree-agent-x", nested)
        with open(os.path.join(nested, "work.txt"), "w") as f:
            f.write("unsaved\n")
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("nested")
        self.assertEqual(self.run_all()[0][3], "kept")
        self.assertTrue(os.path.exists(os.path.join(nested, "work.txt")))

    def test_ignored_nested_clone_with_a_git_folder_is_kept(self):
        commit(self.wt, ".gitignore", "vendor/\n")
        git(self.wt, "push", "-q")
        os.makedirs(os.path.join(self.wt, "vendor"))
        clone = os.path.join(self.wt, "vendor", "other")
        git(self.tmp, "clone", "-q", self.remote, clone)
        with open(os.path.join(clone, "wip.txt"), "w") as f:
            f.write("unsaved\n")
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("git repository")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_realpath_must_equal_the_recorded_path(self):
        with mock.patch("os.path.realpath", lambda p: p + "-moved" if p == self.wt else p):
            self.assertIn("symlink", worktree_cleanup.path_problem(self.repo, self.wt, self.root))

    def _edit_hidden(self, flag):
        git(self.wt, "update-index", flag, "README.md")
        with open(os.path.join(self.wt, "README.md"), "a") as f:
            f.write("unsaved edit\n")
        # the whole point: git itself sees nothing
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def test_skip_worktree_edit_is_kept(self):
        self._edit_hidden("--skip-worktree")
        self.assertKept("hidden from git status")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_assume_unchanged_edit_is_kept(self):
        self._edit_hidden("--assume-unchanged")
        self.assertKept("hidden from git status")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_flags_set_back_to_normal_do_not_block(self):
        git(self.wt, "update-index", "--skip-worktree", "README.md")
        git(self.wt, "update-index", "--no-skip-worktree", "README.md")
        git(self.wt, "update-index", "--assume-unchanged", "README.md")
        git(self.wt, "update-index", "--no-assume-unchanged", "README.md")
        self.assertIsNone(self.blocker())

    def test_bare_repository_in_an_ignored_folder_is_kept(self):
        commit(self.wt, ".gitignore", "vendor/\n*.git/\n")
        git(self.wt, "push", "-q")
        os.makedirs(os.path.join(self.wt, "vendor"))
        git(self.tmp, "init", "-q", "--bare", os.path.join(self.wt, "vendor", "x.git"))
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("bare git repository")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_bare_repository_directly_under_an_ignored_folder_is_kept(self):
        commit(self.wt, ".gitignore", "backup.git/\n")
        git(self.wt, "push", "-q")
        git(self.tmp, "init", "-q", "--bare", os.path.join(self.wt, "backup.git"))
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("bare git repository")

    def test_ignored_worktree_of_a_different_repo_is_kept(self):
        other = os.path.join(self.tmp, "other")
        git(self.tmp, "init", "-q", "-b", "main", other)
        commit(other, "o.txt")
        commit(self.wt, ".gitignore", "vendor/\n")
        git(self.wt, "push", "-q")
        os.makedirs(os.path.join(self.wt, "vendor"))
        nested = os.path.join(self.wt, "vendor", "ow")
        git(other, "worktree", "add", "-q", "-b", "side", nested)
        with open(os.path.join(nested, "work.txt"), "w") as f:
            f.write("unsaved\n")
        self.assertTrue(os.path.isfile(os.path.join(nested, ".git")))  # a gitfile, not a folder
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("git repository")
        self.assertEqual(self.run_all()[0][3], "kept")
        self.assertTrue(os.path.exists(os.path.join(nested, "work.txt")))

    def test_unreadable_ignored_folder_is_kept(self):
        commit(self.wt, ".gitignore", "secret/\n")
        git(self.wt, "push", "-q")
        d = os.path.join(self.wt, "secret", "inner")
        os.makedirs(d)
        os.chmod(os.path.join(self.wt, "secret"), 0)
        self.addCleanup(os.chmod, os.path.join(self.wt, "secret"), 0o755)
        if os.access(os.path.join(self.wt, "secret"), os.R_OK):
            self.skipTest("running as a user that ignores permissions")
        self.assertKept("could not be read")

    def test_merge_in_progress_is_kept_even_with_a_clean_status(self):
        head = git(self.wt, "rev-parse", "HEAD").strip()
        gitdir = git(self.wt, "rev-parse", "--absolute-git-dir").strip()
        with open(os.path.join(gitdir, "MERGE_HEAD"), "w") as f:
            f.write(head + "\n")
        self.assertKept("in progress")

    def test_rebase_in_progress_is_kept(self):
        gitdir = git(self.wt, "rev-parse", "--absolute-git-dir").strip()
        os.makedirs(os.path.join(gitdir, "rebase-merge"))
        self.assertKept("in progress")

    def test_dirty_submodule_hidden_by_ignore_all_is_kept(self):
        sub = os.path.join(self.tmp, "sub")
        git(self.tmp, "init", "-q", "-b", "main", sub)
        commit(sub, "s.txt")
        git(self.wt, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "lib")
        git(self.wt, "config", "-f", ".gitmodules", "submodule.lib.ignore", "all")
        git(self.wt, "add", ".gitmodules")
        git(self.wt, "commit", "-q", "-m", "submodule")
        git(self.wt, "push", "-q")
        with open(os.path.join(self.wt, "lib", "s.txt"), "a") as f:
            f.write("unsaved\n")
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")  # hidden by ignore=all
        self.assertKept("changed or untracked")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_the_ignored_scan_runs_after_the_pane_and_process_checks(self):
        with mock.patch.object(worktree_cleanup, "hidden_repo", side_effect=AssertionError("walked")):
            self.assertKept("pane", cwds=[self.wt])
            self.assertKept("herdr is not connected", cwds=None)
            p = subprocess.Popen(["sleep", "30"], cwd=self.wt)
            self.addCleanup(p.wait)
            self.addCleanup(p.kill)
            self.assertKept("process")

    def test_commit_only_in_the_worktrees_head_reflog_is_kept(self):
        git(self.wt, "checkout", "-q", "--detach")
        commit(self.wt, "detached.txt")
        git(self.wt, "checkout", "-q", BRANCH)
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(git(self.wt, "rev-list", "HEAD", "--not", "--remotes"), "")  # the old check is satisfied
        self.assertKept("reflog")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_commit_only_in_a_refs_worktree_ref_is_kept(self):
        sha = git(self.wt, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "keep me").strip()
        git(self.wt, "update-ref", "refs/worktree/keep", sha)
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("refs/worktree")

    def test_a_tag_or_remote_branch_that_holds_the_reflog_commit_is_enough(self):
        git(self.wt, "checkout", "-q", "--detach")
        commit(self.wt, "detached.txt")
        git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/saved")
        git(self.wt, "checkout", "-q", BRANCH)
        git(self.wt, "fetch", "-q")
        self.assertIsNone(self.blocker())

    def test_amend_and_reset_on_the_pushed_branch_do_not_keep_it_forever(self):
        commit(self.wt, "c.txt")
        git(self.wt, "push", "-q")
        git(self.wt, "commit", "-q", "--amend", "-m", "amended")
        git(self.wt, "push", "-q", "-f")
        commit(self.wt, "d.txt")
        git(self.wt, "reset", "-q", "--hard", "HEAD~1")  # the discarded commit was never pushed
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertIsNone(self.blocker())
        self.assertEqual(self.run_all()[0][3], "removed")
        self.assertFalse(os.path.exists(self.wt))

    def test_a_file_name_that_is_not_utf8_does_not_break_the_checks(self):
        commit(self.wt, ".gitignore", "*.log\n")
        git(self.wt, "push", "-q")
        with open(os.path.join(os.fsencode(self.wt), b"bad\xff.log"), "w") as f:
            f.write("1\n")
        self.assertIsNone(self.blocker())
        self.assertEqual(self.run_all()[0][3], "removed")

    def test_an_untracked_file_name_that_is_not_utf8_keeps_it(self):
        with open(os.path.join(os.fsencode(self.wt), b"bad\xff.txt"), "w") as f:
            f.write("1\n")
        self.assertKept("changed or untracked")

    def test_an_ignored_non_utf8_folder_is_still_scanned_for_repositories(self):
        commit(self.wt, ".gitignore", "vend*/\n")
        git(self.wt, "push", "-q")
        d = os.path.join(os.fsencode(self.wt), b"vend\xffor")
        os.makedirs(os.path.join(d, b"x", b".git"))
        self.assertKept("git repository")

    def test_one_tickets_exception_does_not_stop_the_others_or_lose_results(self):
        second = self.add_worktree(os.path.join(self.root, "CC-025"), "CC-025-two")
        third = self.add_worktree(os.path.join(self.root, "CC-026"), "CC-026-three")
        real = worktree_cleanup.blocker

        def flaky(repo, path, branch, cwds, **kw):
            if path == second:
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "boom")
            return real(repo, path, branch, cwds, **kw)
        items = [("CC-024", "commandcenter", self.repo, BRANCH, self.wt),
                 ("CC-025", "commandcenter", self.repo, "CC-025-two", second),
                 ("CC-026", "commandcenter", self.repo, "CC-026-three", third)]
        with mock.patch.object(worktree_cleanup, "blocker", flaky):
            out = worktree_cleanup.run(items, [], root=self.root)
        self.assertEqual([(o[0], o[3]) for o in out],
                         [("CC-024", "removed"), ("CC-025", "kept"), ("CC-026", "removed")])
        self.assertIn("UnicodeDecodeError", out[1][4])
        self.assertTrue(os.path.isdir(second))

    def test_the_cheap_checks_run_again_after_the_slow_walk(self):
        def walk_then_someone_edits(real):
            with open(os.path.join(real, "late.txt"), "w") as f:
                f.write("typed while we were scanning\n")
            return None
        with mock.patch.object(worktree_cleanup, "hidden_repo", walk_then_someone_edits):
            out = self.run_all()
        self.assertEqual(out[0][3], "kept")
        self.assertIn("changed or untracked", out[0][4])
        self.assertTrue(os.path.exists(os.path.join(self.wt, "late.txt")))

    def test_a_pane_opened_during_the_walk_keeps_it(self):
        panes = []
        with mock.patch.object(worktree_cleanup, "hidden_repo", lambda real: panes.append(self.wt) and None):
            out = worktree_cleanup.run([("CC-024", "commandcenter", self.repo, BRANCH, self.wt)], panes, root=self.root)
        self.assertEqual(out[0][3], "kept")
        self.assertIn("pane", out[0][4])

    def test_a_dot_git_folder_inside_a_tracked_folder_is_kept(self):
        os.makedirs(os.path.join(self.wt, "docs"))
        commit(self.wt, "docs/a.txt")
        git(self.wt, "push", "-q")
        os.makedirs(os.path.join(self.wt, "docs", ".git"))
        with open(os.path.join(self.wt, "docs", ".git", "notes.txt"), "w") as f:
            f.write("unsaved\n")
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertKept("holds a .git")

    def test_not_a_registered_worktree(self):
        clone = os.path.join(self.root, "CC-024c")
        git(self.tmp, "clone", "-q", self.remote, clone)
        self.assertKept("not a registered worktree", path=clone, branch="main")

    def test_main_checkout(self):
        main = os.path.join(self.root, "main-checkout")
        git(self.tmp, "clone", "-q", self.remote, main)
        self.assertKept("main checkout", path=main, branch="main", repo=main)

    def test_locked_worktree(self):
        git(self.repo, "worktree", "lock", self.wt)
        self.assertKept("locked")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_other_branch_checked_out(self):
        self.assertKept("not the branch checked out", branch="CC-024-something-else")

    def test_a_claude_code_agent_worktree_is_never_matched(self):
        agent = self.add_worktree(os.path.join(self.repo, ".claude", "worktrees", "agent-a1b2"), "worktree-agent-a1b2")
        self.assertKept("not the branch checked out", path=agent)

    def test_detached_head(self):
        git(self.wt, "checkout", "-q", "--detach")
        self.assertKept("not the branch checked out")

    def test_no_recorded_branch(self):
        self.assertIn("no recorded branch", self.blocker(branch=None))

    def test_modified_file(self):
        with open(os.path.join(self.wt, "README.md"), "a") as f:
            f.write("more\n")
        self.assertKept("changed or untracked")

    def test_staged_file(self):
        with open(os.path.join(self.wt, "new.txt"), "w") as f:
            f.write("1\n")
        git(self.wt, "add", "new.txt")
        self.assertKept("changed or untracked")

    def test_untracked_file(self):
        with open(os.path.join(self.wt, "scratch.txt"), "w") as f:
            f.write("1\n")
        self.assertKept("changed or untracked")
        self.assertEqual(self.run_all()[0][3], "kept")
        self.assertTrue(os.path.exists(os.path.join(self.wt, "scratch.txt")))

    def test_commit_missing_from_every_remote(self):
        commit(self.wt, "local.txt")
        self.assertKept("on no remote")

    def test_repo_without_a_remote_keeps_everything(self):
        git(self.repo, "remote", "remove", "origin")
        self.assertKept("on no remote")

    def test_herdr_not_connected(self):
        self.assertKept("herdr is not connected", cwds=None)

    def test_herdr_pane_inside(self):
        self.assertKept("pane", cwds=["/somewhere/else", self.wt])
        os.makedirs(os.path.join(self.wt, "sub"))
        self.assertKept("pane", cwds=[os.path.join(self.wt, "sub")])

    def test_pane_in_a_sibling_with_the_same_prefix_does_not_count(self):
        self.assertIsNone(self.blocker(cwds=[self.wt + "-2"]))

    def test_process_inside(self):
        p = subprocess.Popen(["sleep", "30"], cwd=self.wt)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        self.assertKept("process")
        self.assertEqual(self.run_all()[0][3], "kept")

    def test_git_refusing_the_removal_keeps_it_with_the_reason(self):
        with mock.patch.object(worktree_cleanup, "remove", lambda repo, path: (False, "contains submodules")):
            out = self.run_all()
        self.assertEqual(out[0][3], "kept")
        self.assertIn("contains submodules", out[0][4])
        self.assertTrue(os.path.isdir(self.wt))

    def test_project_without_a_checkout(self):
        out = worktree_cleanup.run([("CC-024", "commandcenter", None, BRANCH, self.wt)], [], root=self.root)
        self.assertEqual(out[0][3], "kept")


class Daemons(Repos, unittest.IsolatedAsyncioTestCase):
    """The git poll feeds DONE tickets in; events record the outcome once."""

    async def asyncSetUp(self):
        self.ts = TaskStore(":memory:", [{"key": "commandcenter", "name": "Command Center", "prefix": "CC"}])
        self.pl = Pipeline(self.ts)
        t, _ = self.ts.create("commandcenter", "Worktree cleanup")
        self.key = t["key"]
        self.wt = self.add_worktree(os.path.join(self.root, self.key), f"{self.key}-cleanup")
        self.branch = f"{self.key}-cleanup"
        self.pl.plan(self.key, {"summary": "s", "requirements": ["r"], "approach": "a", "affected": ["f"], "risk": "low",
                                "tests": ["t"], "questions": []}, "agent:planner")
        self.pl.start(self.key, self.branch, self.wt, "agent:coordinator")
        self.db = new_db()
        self.store = Store(self.db)
        self.addCleanup(self.store.close)
        patches = [mock.patch.object(registry, "root_of", lambda project: self.repo),
                   mock.patch.object(worktree_cleanup, "WORKTREES_ROOT", self.root)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def daemon(self, **over):
        d = Daemon(cfg(**over), self.store, None, host_fn=fake_host, git_fn=fake_git, tasks=self.ts)
        d.herdr_state.update(connected=True, ok=True, lastSnapshotAt=1.0)
        d.panes = []
        return d

    def done(self):
        self.ts.db.execute("UPDATE tickets SET status='DONE' WHERE key=?", (self.key,))

    def kinds(self):
        return [(e["data"].get("kind"), e["ref"]) for e in self.store.since(0) if e["kind"] == "task.pipeline"]

    async def test_done_ticket_is_removed_after_the_git_poll_and_recorded_once(self):
        self.done()
        d = self.daemon(worktree_cleanup=True)
        await d.poll_git_once()
        self.assertFalse(os.path.exists(self.wt))
        self.assertIn(self.branch, git(self.repo, "branch", "--list", self.branch))
        self.assertEqual(self.kinds(), [("pipeline.worktree_removed", self.key)])
        await d.poll_git_once()
        self.assertEqual(len(self.kinds()), 1)

    async def test_ticket_that_is_not_done_is_left_alone(self):
        d = self.daemon(worktree_cleanup=True)
        await d.poll_git_once()
        self.assertTrue(os.path.isdir(self.wt))
        self.assertEqual(self.kinds(), [])

    async def test_kill_switch_off_removes_nothing(self):
        self.done()
        d = self.daemon(worktree_cleanup=False)
        await d.poll_git_once()
        self.assertTrue(os.path.isdir(self.wt))
        self.assertEqual(self.kinds(), [])

    async def test_test_helper_config_has_the_switch_off(self):
        self.assertIs(cfg()["worktree_cleanup"], False)

    async def test_default_config_has_the_switch_on(self):
        from ccd import config
        self.assertIs(config.DEFAULTS["worktree_cleanup"], True)

    async def test_kept_is_recorded_once_per_reason(self):
        self.done()
        with open(os.path.join(self.wt, "scratch.txt"), "w") as f:
            f.write("1\n")
        d = self.daemon(worktree_cleanup=True)
        await d.poll_git_once()
        await d.poll_git_once()
        self.assertEqual(self.kinds(), [("pipeline.worktree_kept", self.key)])
        ev = [e for e in self.store.since(0) if e["data"].get("kind") == "pipeline.worktree_kept"][0]
        self.assertIn("changed or untracked", ev["data"]["reason"])
        self.assertTrue(os.path.isdir(self.wt))
        # a new reason is a new record
        os.remove(os.path.join(self.wt, "scratch.txt"))
        commit(self.wt, "local.txt")
        await d.poll_git_once()
        self.assertEqual(len(self.kinds()), 2)
        # and a restart does not repeat the last one (the reason is stored)
        d2 = self.daemon(worktree_cleanup=True)
        await d2.poll_git_once()
        self.assertEqual(len(self.kinds()), 2)
        # once pushed, it goes
        git(self.wt, "push", "-q")
        await d2.poll_git_once()
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.kinds()[-1], ("pipeline.worktree_removed", self.key))

    async def test_herdr_down_keeps_it(self):
        self.done()
        d = self.daemon(worktree_cleanup=True)
        d.herdr_state.update(connected=False, ok=False, error="gone")
        await d.poll_git_once()
        self.assertTrue(os.path.isdir(self.wt))
        self.assertEqual(self.kinds(), [("pipeline.worktree_kept", self.key)])

    async def test_agent_pane_inside_keeps_it(self):
        self.done()
        d = self.daemon(worktree_cleanup=True)
        d.panes = [{"pane_id": "w:p1", "cwd": self.wt, "live": False}]
        await d.clean_worktrees()
        self.assertTrue(os.path.isdir(self.wt))

    async def test_removed_worktree_leaves_the_known_list(self):
        self.done()
        d = self.daemon(worktree_cleanup=True)
        d.git["worktrees"] = {"commandcenter": [self.repo, self.wt]}
        await d.clean_worktrees()
        self.assertEqual(d.git["worktrees"]["commandcenter"], [self.repo])


if __name__ == "__main__":
    unittest.main()
