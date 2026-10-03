"""The lifted board logic: same answers as the legacy board, fewer calls."""
import copy
import json
import unittest

from ccd import model, sources

from .fake_herdr import load_snapshot
from .helpers import PROJECTS, WORKTREES, cfg

GRAPHQL = {"data": {"repository": {
    "issues": {"pageInfo": {"hasNextPage": False}, "nodes": [
        {"number": 4, "title": "GYST-VN-009 — sync calendar", "url": "u4", "updatedAt": "2026-10-01T00:00:00Z",
         "labels": {"nodes": [{"name": "status:ready"}, {"name": "risk:not-agent-eligible"}]}},
        {"number": 5, "title": "needs a decision", "url": "u5", "updatedAt": "2026-10-01T00:00:00Z",
         "labels": {"nodes": [{"name": "needs:jay"}]}}]},
    "pullRequests": {"nodes": [
        {"number": 44, "title": "feat: thing", "url": "p44", "isDraft": False, "reviewDecision": "APPROVED",
         "headRefName": "b", "headRefOid": "abcdef1234", "updatedAt": "2026-10-02T00:00:00Z", "labels": {"nodes": []},
         "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]}},
        {"number": 45, "title": "wip", "url": "p45", "isDraft": False, "reviewDecision": None,
         "headRefName": "c", "headRefOid": "1234567890", "updatedAt": "2026-10-02T00:00:00Z", "labels": {"nodes": []},
         "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]}}]},
    "merged": {"nodes": [{"number": 40, "title": "old", "url": "p40", "mergedAt": "2026-10-02T00:00:00Z"}]},
    "closed": {"nodes": [{"number": 3, "title": "done", "url": "u3", "closedAt": "2026-10-02T00:00:00Z",
                          "stateReason": "COMPLETED"}]},
    "ref": {"target": {"oid": "abc", "url": "c", "statusCheckRollup": {"state": "FAILURE"}}},
}}}


class Reshape(unittest.TestCase):
    def test_graphql_becomes_the_legacy_five_keys(self):
        r = sources.reshape(GRAPHQL)
        self.assertEqual(set(r) - {"truncated"}, {"issues", "prs", "merged", "closed", "ci"})
        self.assertEqual(r["issues"][0]["labels"], [{"name": "status:ready"}, {"name": "risk:not-agent-eligible"}])
        self.assertEqual(r["prs"][0]["statusCheckRollup"], [{"state": "SUCCESS"}])
        self.assertEqual(r["ci"][0]["conclusion"], "failure")

    def test_model_reads_it_exactly_as_before(self):
        c = cfg()
        view = model.project_view(c["projects"][1], sources.reshape(GRAPHQL), [], {}, c)
        prs = {p["number"]: p for p in view["prs"]}
        self.assertTrue(prs[44]["ready"], "approved + green = ready to merge")
        self.assertEqual(prs[45]["ci"], "✗")
        self.assertEqual(view["main_ci"], "✗")
        stages = {t["ref"]: t for t in view["tasks"]}
        self.assertTrue(stages["GYST-VN-009"]["you_do_it"])
        self.assertEqual(stages["#5"]["stage"], "needs_jay")

    def test_no_checks_renders_as_no_data(self):
        g = copy.deepcopy(GRAPHQL)
        g["data"]["repository"]["ref"] = {"target": {"oid": "x", "statusCheckRollup": None}}
        self.assertEqual(sources.reshape(g)["ci"], [])

    def test_errors_and_missing_repos_become_per_key_errors(self):
        r = sources.reshape({"errors": [{"message": "Could not resolve to a Repository"}]})
        self.assertTrue(all("error" in v for v in r.values()))

    def test_one_gh_process_per_repo(self):
        calls = []
        orig, fx = sources._run, sources.FIXTURES
        sources.FIXTURES = None
        sources._run = lambda args, **kw: (calls.append(args) or (0, json.dumps(GRAPHQL), ""))
        try:
            sources.github(PROJECTS[1])
        finally:
            sources._run, sources.FIXTURES = orig, fx
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["gh", "api", "graphql"])
        self.assertIn("ref=refs/heads/master", calls[0], "the configured branch, not an assumed main")


class DeriveParity(unittest.TestCase):
    def test_derive_equals_the_legacy_build_on_the_same_inputs(self):
        c = cfg()
        snap = load_snapshot()
        panes = sources.panes_from(snap)
        gh = {"gyst": sources.reshape(GRAPHQL)}
        srv = {"disk": 50}
        unpushed = {"gyst": [{"branch": "wip", "commits": 1, "age_h": 50}]}
        orig = (model.sources.github, model.sources.herdr_panes, model.sources.server,
                model.sources.unpushed_branches, model.sources.worktree_paths, model._blocked_since)
        age = model._age_h
        model._age_h = lambda iso: 12.0  # both runs read the same clock
        self.addCleanup(setattr, model, "_age_h", age)
        try:
            model.sources.github = lambda p: gh.get(p["key"], {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []})
            model.sources.herdr_panes = lambda: panes
            model.sources.server = lambda cfg_: srv
            model.sources.unpushed_branches = lambda path: next((v for k, v in unpushed.items()
                                                                 if any(p["path"] == path and p["key"] == k for p in PROJECTS)), [])
            model.sources.worktree_paths = lambda path: next(v for k, v in WORKTREES.items()
                                                             if any(p["path"] == path and p["key"] == k for p in PROJECTS))
            model._blocked_since = lambda panes_: {}
            legacy = model.build(c)
        finally:
            (model.sources.github, model.sources.herdr_panes, model.sources.server,
             model.sources.unpushed_branches, model.sources.worktree_paths, model._blocked_since) = orig
        new = model.derive(c, {"gyst": gh["gyst"], "samvision": legacy_empty(), "mfe": legacy_empty(),
                               "gauzemate": legacy_empty()}, panes, srv, unpushed, WORKTREES, {})
        for snap_ in (legacy, new):
            snap_.pop("at")
        self.assertEqual(json.dumps(legacy, sort_keys=True, default=str), json.dumps(new, sort_keys=True, default=str))


def legacy_empty():
    return {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []}


if __name__ == "__main__":
    unittest.main()
