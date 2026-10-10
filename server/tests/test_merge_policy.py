"""The auto-merge classifier (ccd/merge_policy.py): pure functions over plain dicts, no GitHub, no database."""
import copy
import unittest

from ccd import merge_policy as mp

HEAD = "ab" * 20
REF = "JayDalool/CommandCenter#7"


def f(path, change="MODIFIED", add=5, dele=2):
    return {"path": path, "additions": add, "deletions": dele, "changeType": change}


def fr(project, files):
    """file_reasons with the PR totals the files add up to."""
    ok = [x for x in files if isinstance(x, dict) and isinstance(x.get("additions"), int)]
    return mp.file_reasons(project, files, sum(x["additions"] for x in ok), sum(x["deletions"] for x in ok))


def view(files=None, **over):
    files = files if files is not None else [f("server/tests/test_x.py", "ADDED"), f("docs/API.md")]
    pr = {"state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "baseRefName": "main", "headRefOid": HEAD,
          "isCrossRepository": False, "files": files, "statusCheckRollup": [],
          "additions": sum(x["additions"] for x in files), "deletions": sum(x["deletions"] for x in files)}
    pr.update(over)
    return pr


def ticket(**over):
    t = {"key": "CC-040", "project": "commandcenter", "status": "READY_TO_MERGE", "type": "MAINTENANCE", "flags": [],
         "labels": []}
    t.update(over)
    return t


def work(**over):
    w = {"gate": None, "confirmed": [], "review": {"verdict": "APPROVE", "head": HEAD, "pr": REF, "cycles": 0}}
    w.update(over)
    return w


def decide(pr=None, t=None, w=None, open_prs=(REF,), policy="low-risk", ref=REF):
    return mp.classify("commandcenter", t or ticket(), w or work(), pr or view(), ref, list(open_prs), policy)


class Paths(unittest.TestCase):
    def test_allowed_paths_qualify(self):
        for path in ("server/tests/test_x.py", "server/tests/sub/deeper/test_y.py", "web/app/tests/work.test.tsx", "web/app/tests/a/b.test.ts",
                     "docs/API.md", "docs/jay/MY_ACTIONS.md", "docs/design/deep/er/notes.md", "README.md"):
            self.assertEqual(fr("commandcenter", [f(path, "ADDED")]), [], path)

    def test_everything_else_is_outside_the_allowlist(self):
        for path in ("server/ccd/x.py", "web/app/src/App.tsx", "server/other.py", "docs/notes.txt", "docs/img/a.png", "server/tests/fixtures/a/b.json", "server/tests/data.txt",
                     "server/tests/blob.so", "server/tests/mod.pyc", "server/tests/run.sh", "web/app/tests/a.json",
                     "web/app/tests/a.js", "web/app/tests/snap.snap",
                     "web/README.md", "server/tests", "tests/x.py", "scripts/a.sh"):
            self.assertTrue(fr("commandcenter", [f(path)]), path)

    def test_the_denylist_wins_over_the_allowlist(self):
        for path in ("server/ccd/daemon.py", "scripts/go-live.sh", "launcher/main.go", ".github/workflows/launcher.yml",
                     "web/app/src/api/types.ts", "plans/TICKET-PIPELINE-V1.md", "docs/SECURITY.md", "docs/adr/0007-x.md",
                     "AGENTS.md", "CLAUDE.md", "docs/CLAUDE.md", ".claude/settings.json",
                     "package.json", "web/app/package-lock.json", "web/app/tests/package.json", "server/requirements.txt",
                     "server/tests/requirements-dev.txt", "yarn.lock", "go.sum",
                     "docs/security.md", "Docs/ADR/0007-x.md", "agents.md"):
            self.assertTrue(mp.denied(path), path)
            self.assertTrue(fr("commandcenter", [f(path, "ADDED")]), path)

    def test_agent_config_and_build_output_never_qualify_at_any_depth(self):
        for path in ("server/tests/.claude/settings.json", "docs/.claude/commands/go.md", "server/tests/.mcp.json",
                     "server/tests/.codex/config.toml", "server/tests/GEMINI.md", "docs/GEMINI.md",
                     "server/tests/.claude/skills/x/SKILL.md", "docs/skills/SKILL.md", "docs/sub/AGENTS.md",
                     "web/app/tests/.claude/x.ts", "server/tests/.hidden.py", "docs/.hidden.md", "docs/.github/x.md",
                     "server/tests/__pycache__/test_x.cpython-314.pyc", "server/tests/__pycache__/test_x.py",
                     "server/tests/blob.so", "docs/.env.md", "server/tests/.codex/x.py", "docs/CLAUDE.MD"):
            self.assertTrue(mp.denied(path) or not mp.allowed("commandcenter", path), path)
            self.assertTrue(fr("commandcenter", [f(path, "ADDED")]), path)

    def test_more_agent_files_are_denied_in_any_case_at_any_depth(self):
        for name in ("CLAUDE.local.md", "claude.LOCAL.md", "AGENTS.override.md", "Agents.Override.MD", "AGENT.md", "agent.md",
                     "Agent.MD"):
            for folder in ("", "docs/", "docs/sub/deep/", "server/tests/", "server/tests/a/b/"):
                path = folder + name
                self.assertTrue(mp.denied(path), path)
                if folder:
                    self.assertTrue(fr("commandcenter", [f(path, "ADDED")]), path)

    def test_hidden_and_pycache_parts_are_denied_even_where_the_type_would_fit(self):
        for path in ("server/tests/.claude/x.py", "docs/.claude/x.md", "web/app/tests/.codex/x.tsx",
                     "server/tests/__pycache__/x.py", "docs/a/.b/c.md"):
            self.assertTrue(mp.allowed("commandcenter", path), path)    # the allowlist alone would take it
            self.assertTrue(mp.denied(path), path)
            self.assertTrue(fr("commandcenter", [f(path, "ADDED")]), path)

    def test_binaries_do_not_count_as_zero_lines_and_qualify(self):
        r = mp.file_reasons("commandcenter", [{"path": "server/tests/x.bin", "changeType": "ADDED", "additions": 0,
                                               "deletions": 0}], 0, 0)
        self.assertTrue(r)
        self.assertTrue(mp.file_reasons("commandcenter", [{"path": "server/tests/x.so", "changeType": "ADDED",
                                                           "additions": 0, "deletions": 0}], 0, 0))

    def test_a_denied_file_in_an_allowed_folder_blocks_the_whole_pr(self):
        r = fr("commandcenter", [f("server/tests/test_a.py"), f("docs/SECURITY.md")])
        self.assertEqual(len(r), 1)
        self.assertIn("docs/SECURITY.md is never auto-merged", r[0])

    def test_odd_paths_are_refused(self):
        for path in ("../server/tests/a.py", "server/tests/../ccd/x.py", "/server/tests/a.py", "server\\tests\\a.py",
                     "server/tests/a\x00.py", "", "server//tests/a.py", None, 7):
            self.assertTrue(fr("commandcenter", [f(path)]), repr(path))

    def test_a_project_without_an_allowlist_never_qualifies(self):
        for project in ("samvision", "gauzemate", "mfe", "gyst", "nope"):
            self.assertEqual(fr(project, [f("docs/API.md")]), [f"{project} has no auto-merge allowlist"])
        d = mp.classify("gyst", ticket(project="gyst"), work(), view(), REF, [REF])
        self.assertFalse(d.ok)

    def test_only_added_or_modified_files(self):
        for change in ("DELETED", "RENAMED", "COPIED", "CHANGED", None, "added"):
            r = fr("commandcenter", [f("server/tests/test_a.py", change)])
            self.assertTrue(r and "only added or modified" in r[0], change)
        for change in ("ADDED", "MODIFIED"):
            self.assertEqual(fr("commandcenter", [f("server/tests/test_a.py", change)]), [])

    def test_a_missing_file_list_never_qualifies(self):
        for files in (None, [], "x", {}):
            self.assertTrue(mp.file_reasons("commandcenter", files, 1, 1))


class Size(unittest.TestCase):
    def test_ten_files_and_three_hundred_lines_are_the_limits(self):
        ten = [f(f"server/tests/test_{i}.py", "ADDED", 20, 10) for i in range(10)]
        self.assertEqual(mp.file_reasons("commandcenter", ten, 200, 100), [])
        self.assertTrue(mp.file_reasons("commandcenter", ten + [f("server/tests/test_11.py")], 205, 102))
        over = [f(f"server/tests/test_{i}.py", "ADDED", 20, 10) for i in range(9)] + [f("server/tests/z.py", "ADDED", 20, 11)]
        r = mp.file_reasons("commandcenter", over, 200, 101)
        self.assertEqual(r, ["301 lines changed (limit 300)"])

    def test_the_prs_own_totals_count_too(self):
        one = [f("server/tests/test_a.py", "ADDED", 1, 0)]
        self.assertEqual(mp.file_reasons("commandcenter", one, 1, 0), [])
        self.assertEqual(mp.file_reasons("commandcenter", one, 250, 60), ["310 lines changed (limit 300)"])

    def test_unknown_counts_never_qualify(self):
        one = [f("server/tests/test_a.py", "ADDED", 1, 0)]
        for adds, dels in ((None, 0), (1, None), ("1", 0), (True, 0), (-1, 0)):
            self.assertEqual(mp.file_reasons("commandcenter", one, adds, dels), ["the PR's line counts are unknown"])
        self.assertTrue(mp.file_reasons("commandcenter", [{"path": "server/tests/a.py", "changeType": "ADDED"}], 1, 0))

    def test_a_hundred_files_is_refused_quickly_and_with_one_short_reason_list(self):
        files = [f(f"server/tests/test_{i}.py", "ADDED", 1, 0) for i in range(100)]
        r = mp.file_reasons("commandcenter", files, 100, 0)
        self.assertEqual(r, ["100 files changed (limit 10)"])
        files[50] = f("server/ccd/x.py")        # a hundred files and a bad one: still refused, still short
        self.assertTrue(mp.file_reasons("commandcenter", files, 100, 0))
        self.assertLessEqual(len(mp.file_reasons("commandcenter", [f(f"x/{i}") for i in range(100)], 1, 1)), 6)


class Ci(unittest.TestCase):
    def test_states(self):
        self.assertEqual(mp.ci_state([]), "none")
        self.assertEqual(mp.ci_state(None), "none")
        self.assertEqual(mp.ci_state([{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}, {"conclusion": "SKIPPED"}]), "green")
        self.assertEqual(mp.ci_state([{"conclusion": "SUCCESS"}, {"status": "IN_PROGRESS", "conclusion": ""}]), "pending")
        self.assertEqual(mp.ci_state([{"state": "PENDING"}]), "pending")
        self.assertEqual(mp.ci_state([{"conclusion": "FAILURE"}, {"state": "PENDING"}]), "failing")
        self.assertEqual(mp.ci_state([{"conclusion": "CANCELLED"}]), "failing")
        self.assertEqual(mp.ci_state([{"conclusion": "SOMETHING_NEW"}]), "unknown")
        self.assertEqual(mp.ci_state([{"status": "COMPLETED"}]), "unknown")
        self.assertEqual(mp.ci_state("green"), "unknown")

    def test_no_checks_at_all_qualifies_and_is_not_called_green(self):
        d = decide(view(statusCheckRollup=[]))
        self.assertEqual((d.ok, d.ci), (True, "none"))
        self.assertEqual(decide(view(statusCheckRollup=[{"conclusion": "SUCCESS"}])).ci, "green")

    def test_failing_blocks_and_pending_waits(self):
        d = decide(view(statusCheckRollup=[{"conclusion": "FAILURE"}]))
        self.assertEqual((d.ok, d.wait, d.ci), (False, False, "failing"))
        self.assertIn("a CI check is failing", d.reasons)
        d = decide(view(statusCheckRollup=[{"conclusion": "SUCCESS"}, {"status": "QUEUED", "conclusion": ""}]))
        self.assertEqual((d.ok, d.wait, d.ci), (False, True, "pending"))
        d = decide(view(statusCheckRollup=[{"conclusion": "SOMETHING_NEW"}]))
        self.assertEqual((d.ok, d.wait), (False, False))


class Decide(unittest.TestCase):
    def test_a_clean_docs_and_tests_pr_qualifies(self):
        d = decide()
        self.assertEqual((d.ok, d.reasons, d.wait), (True, [], False))

    def test_flags_types_and_labels_exclude(self):
        for over in ({"flags": ["needs_jay"]}, {"flags": ["needs:jay"]}, {"flags": ["needs_legal"]},
                     {"flags": ["needs_ui_review"]}, {"flags": ["needs_deploy"]},
                     {"type": "SECURITY"}, {"type": "LEGAL"}, {"type": "DESIGN"},
                     {"labels": ["ui"]}, {"labels": ["gate:plan"]}, {"labels": ["migration"]}, {"labels": ["security"]},
                     {"labels": ["architecture"]}, {"labels": ["product-decision"]}, {"labels": ["financial"]}):
            d = decide(t=ticket(**over))
            self.assertFalse(d.ok, over)
            self.assertTrue(d.reasons, over)
        for over in ({"type": "DOCS"}, {"type": "FEATURE"}, {"labels": ["night-finding"]}):
            self.assertTrue(decide(t=ticket(**over)).ok, over)

    def test_owner_accept_excludes(self):
        d = decide(w=work(confirmed=["owner:accept"]))
        self.assertFalse(d.ok)
        self.assertIn("Jay asked to accept this ticket's merge himself", d.reasons)

    def test_an_open_gate_or_a_wrong_status_excludes(self):
        self.assertFalse(decide(w=work(gate="merge")).ok)
        self.assertFalse(decide(t=ticket(status="IN_REVIEW")).ok)

    def test_the_review_must_approve_this_head_of_this_pr(self):
        rv = lambda **o: work(review=dict(work()["review"], **o))  # noqa: E731
        self.assertFalse(decide(w=rv(verdict="REQUEST_CHANGES")).ok)
        self.assertFalse(decide(w=rv(verdict=None)).ok)
        self.assertFalse(decide(w=rv(head="cd" * 20)).ok)               # reviewed an older head
        self.assertFalse(decide(w=rv(head=HEAD[:7])).ok)                # a prefix is not a head
        self.assertFalse(decide(pr=view(headRefOid="cd" * 20)).ok)      # the PR moved on
        self.assertFalse(decide(w=rv(pr=None)).ok)                      # not recorded against a PR
        self.assertFalse(decide(w=rv(pr="JayDalool/CommandCenter#8")).ok)
        self.assertFalse(decide(w=rv(pr="Other/Repo#7")).ok)

    def test_exactly_one_open_linked_pr(self):
        self.assertFalse(decide(open_prs=()).ok)
        self.assertFalse(decide(open_prs=(REF, "JayDalool/CommandCenter#9")).ok)
        self.assertFalse(decide(open_prs=("JayDalool/CommandCenter#9",)).ok)

    def test_the_pr_must_be_open_ready_mergeable_on_main_and_not_cross_repo(self):
        for over in ({"state": "CLOSED"}, {"state": "MERGED"}, {"state": None}, {"isDraft": True}, {"isDraft": None},
                     {"mergeable": "CONFLICTING"}, {"mergeable": None}, {"baseRefName": "release"},
                     {"baseRefName": None}, {"isCrossRepository": True}, {"isCrossRepository": None}):
            d = decide(pr=view(**over))
            self.assertFalse(d.ok, over)
            self.assertFalse(d.wait, over)

    def test_mergeability_not_known_yet_waits(self):
        d = decide(pr=view(mergeable="UNKNOWN"))
        self.assertEqual((d.ok, d.wait), (False, True))

    def test_a_bad_file_beats_a_pending_check(self):
        d = decide(pr=view([f("server/ccd/x.py")], statusCheckRollup=[{"state": "PENDING"}]))
        self.assertEqual((d.ok, d.wait), (False, False))

    def test_the_policy_must_be_low_risk(self):
        for policy in ("owner", "auto", None, ""):
            self.assertFalse(decide(policy=policy).ok, policy)

    def test_nothing_is_mutated(self):
        pr, t, w = view(), ticket(), work()
        before = copy.deepcopy((pr, t, w))
        decide(pr=pr, t=t, w=w)
        self.assertEqual((pr, t, w), before)

    def test_a_pr_that_changes_this_policy_can_never_qualify(self):
        for path in ("server/ccd/merge_policy.py", "server/ccd/registry.py", "server/ccd/daemon.py",
                     "docs/adr/0007-auto-merge-policy.md", "server/ccd/skills/night-shift/SKILL.md"):
            self.assertFalse(decide(pr=view([f(path, "MODIFIED")])).ok, path)
        self.assertFalse(decide(pr=view([f("server/tests/test_merge_policy.py", "ADDED"),
                                         f("server/ccd/merge_policy.py")])).ok)
