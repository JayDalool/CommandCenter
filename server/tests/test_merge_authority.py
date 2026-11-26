"""CC-080 c1, c7, c8: the merge authority written in code, policy, docs and CI agrees with itself.

Standard library only (tomllib, re): no YAML parser is added to read ci.yml (security review, CC-080).
"""
import os
import re
import tomllib
import unittest

from ccd import config, merge_policy as mp, pipeline, registry
from ccd.daemon import Daemon

from .test_merge_policy import decide, f, view

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


def profile(project):
    with open(os.path.join(ROOT, "policy", "projects", f"{project}.toml"), "rb") as fh:
        return tomllib.load(fh)


def agents_protected():
    """The backticked paths of AGENTS.md's "Protected paths" list (the paragraph after "the list below")."""
    text = read("AGENTS.md")
    block = text.split("widens that to the list below", 1)[1].split("Never weaken the rails", 1)[0]
    return set(re.findall(r"`([^`]+)`", block))


def sample(glob):
    """A real file path inside a protected glob."""
    return glob[:-2] + "sub/notes.md" if glob.endswith("/**") else glob


class ProtectedPaths(unittest.TestCase):
    """c1: every path AGENTS.md and the project policy protect is one ccd never merges by itself."""

    def test_agents_md_and_the_policy_list_the_same_paths(self):
        policy = set(profile("commandcenter")["target"]["self_protection"]["require_jay_for_paths"])
        self.assertTrue(policy)
        self.assertEqual(agents_protected(), policy)

    def test_each_protected_path_is_denied_and_held_in_any_case(self):
        for glob in sorted(agents_protected()):
            for path in {sample(glob), sample(glob).upper(), sample(glob).title()}:
                self.assertTrue(mp.denied(path), path)
                d = decide(pr=view([f(path, "ADDED")]))
                self.assertFalse(d.ok, path)
                self.assertIn(f"{path} is never auto-merged", d.reasons, path)


def ci_workflow():
    """(workflow name, set of job ids, pull_request block lines) from ci.yml, read line by line: a top-level key
    starts at column 0 and its children are indented two spaces."""
    lines = read(".github/workflows/ci.yml").splitlines()
    name = next(ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("name:"))
    jobs, pr, section, in_pr = set(), [], None, False
    for ln in lines:
        if ln and not ln.startswith((" ", "#")):
            section = ln.split(":", 1)[0].strip()
            continue
        child = re.match(r"^  ([A-Za-z0-9_-]+):", ln)
        if section == "jobs" and child:
            jobs.add(child.group(1))
        if section == "on":
            if child:
                in_pr = child.group(1) == "pull_request"
            elif in_pr and ln.strip():
                pr.append(ln.strip())
    return name, jobs, pr


class AuthorityAgrees(unittest.TestCase):
    """c7: registry, policy profiles, the daemon's candidates, GYST's own rule and CI agree on who merges."""

    def test_only_commandcenter_is_low_risk_everywhere(self):
        low = [k for k in registry.PROJECTS if registry.pipeline_of(k).get("merge") == "low-risk"]
        self.assertEqual(low, ["commandcenter"])
        for k in registry.PROJECTS:
            self.assertEqual(profile(k)["enforced"]["merge"], registry.pipeline_of(k)["merge"], k)
        self.assertEqual(sorted(mp.ALLOW), ["commandcenter"])
        self.assertEqual(sorted(mp.BASE), ["commandcenter"])
        self.assertEqual(sorted(mp.REQUIRED_CHECKS), ["commandcenter"])
        self.assertEqual(Daemon._auto_merge_projects(None), ["commandcenter"])

    def test_gyst_is_never_a_candidate(self):
        # GYST's AGENTS.md rule 13: agents never merge into master. ccd agrees: owner, and no allowlist, base or
        # required checks, so even a low-risk registry entry could not make a GYST PR qualify.
        self.assertEqual(registry.pipeline_of("gyst")["merge"], "owner")
        self.assertEqual(pipeline.policy({"project": "gyst"}, "gyst")["merge"], "owner")
        for table in (mp.ALLOW, mp.BASE, mp.REQUIRED_CHECKS):
            self.assertNotIn("gyst", table)
        d = mp.classify("gyst", {"project": "gyst", "status": "READY_TO_MERGE"}, {}, view(baseRefName="master"),
                        "JayDalool/gyst-lifeops#7", ["JayDalool/gyst-lifeops#7"], "low-risk")
        self.assertFalse(d.ok)
        self.assertIn("gyst has no authorized base branch", d.reasons)

    @unittest.skipUnless(os.path.exists(os.path.join(registry.PROJECTS["gyst"]["root"], "AGENTS.md")),
                         "the GYST checkout is on jay-server only, not on the CI runner")
    def test_gysts_own_rule_still_says_agents_never_merge(self):
        with open(os.path.join(registry.PROJECTS["gyst"]["root"], "AGENTS.md"), encoding="utf-8") as fh:
            self.assertIn("Agents never merge into `master`", fh.read())

    def test_required_checks_are_ci_jobs_that_run_on_every_pr_to_the_base(self):
        name, jobs, pr = ci_workflow()
        for workflow, job in mp.REQUIRED_CHECKS["commandcenter"]:
            self.assertEqual(workflow, name)
            self.assertIn(job, jobs)
        self.assertIn(f"branches: [{mp.BASE['commandcenter']}]", pr)
        # Codex CC-080 r1: the rollup names a workflow but not its file, so ci.yml must be the only workflow with
        # that name (required_ci holds any PR that changes .github/, so a PR cannot add a look-alike).
        folder = os.path.join(ROOT, ".github", "workflows")
        named = sorted(n for n in os.listdir(folder) if n.endswith((".yml", ".yaml")) and any(
            ln.split(":", 1)[1].strip().strip("'\"") == name
            for ln in read(f".github/workflows/{n}").splitlines() if ln.startswith("name:")))
        self.assertEqual(named, ["ci.yml"])
        # A path filter would let a PR skip a required job; absent then holds the merge, but say so here first.
        self.assertFalse([ln for ln in pr if ln.startswith(("paths", "paths-ignore"))], pr)


class DocsAgree(unittest.TestCase):
    """c8: the docs changed with the rules, and auto_merge stays off."""

    def flat(self, path):
        return " ".join(read(path).split())

    def test_auto_merge_stays_off(self):
        self.assertIs(config.DEFAULTS["auto_merge"], False)

    def test_the_rule_docs_name_cc_080(self):
        for path in ("AGENTS.md", "docs/flow/FLOW.md", "docs/adr/0007-auto-merge-policy.md", "docs/SECURITY.md"):
            self.assertTrue("CC-080" in read(path), path)

    def test_adr_0007_keeps_auto_merge_off_until_slice_2(self):
        self.assertTrue("must stay off until slice 2" in self.flat("docs/adr/0007-auto-merge-policy.md"))

    def test_no_doc_still_allows_a_pr_with_no_checks(self):
        paths = ["AGENTS.md", "README.md", "server/ccd/merge_policy.py"]
        for folder, _dirs, files in os.walk(os.path.join(ROOT, "docs")):
            paths += [os.path.relpath(os.path.join(folder, n), ROOT) for n in files if n.endswith(".md")]
        for path in paths:
            text = self.flat(path).lower()
            self.assertFalse("no checks at all is allowed" in text.replace("*", ""), path)
