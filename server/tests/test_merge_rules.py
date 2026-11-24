"""CC-057 (A): the merge rules for small, low-risk PRs in four projects (ccd/merge_policy.py, merge_facts.py, registry,
config switch, security sign-off, size lineage). Every test here fails without the rule it names: they are the
round-2 security tech review's HIGH and MEDIUM items."""
import base64
import json
import unittest

from ccd import config, merge_facts, merge_policy as mp, pipeline, registry
from ccd.pipeline import Pipeline
from ccd.tasks import TaskError, TaskStore

from .test_merge_policy import HEAD, REF, f, facts_for, green, run, ticket, view, work

PROJECTS = ("commandcenter", "mfe", "gyst", "samvision")


def refused(project, path, change="MODIFIED"):
    return bool(mp.file_reasons(project, [f(path, change)], 5, 2))


def decide_in(project, files, facts="default", w=None, t=None, rollup="default", **over):
    """classify for a project with a PR that satisfies every non-file rule, so only `files` and `facts` decide."""
    rollup = green(*registry.checks_of(project)) if rollup == "default" else rollup
    over.setdefault("baseRefName", registry.base_of(project))
    pr = view(files, statusCheckRollup=rollup, **over)
    if facts == "default":
        facts = facts_for(files, project)
    return mp.classify(project, t or ticket(project=project), w or work(), pr, REF, [REF], "low-risk", facts)


class Matching(unittest.TestCase):
    def test_brace_globs_are_expanded_at_compile_time(self):
        self.assertEqual(sorted(mp.expand_braces("a/{b,c}.py")), ["a/b.py", "a/c.py"])
        self.assertEqual(sorted(mp.expand_braces("{a,b}/{c,d}")), ["a/c", "a/d", "b/c", "b/d"])
        self.assertEqual(mp.expand_braces("a/{b"), ["a/{b"])      # a brace with no partner is just a character
        # SamVision's braces were literal before, so every one of these denies matched nothing
        for path in ("samvision/api/web.py", "samvision/api/settings.py", "samvision/api/ratelimit.py",
                     "samvision/api/templates/_map.html", "samvision/api/templates/error.html",
                     "samvision/api/static/leaflet.js", "samvision/api/static/htmx.min.js", "samvision/vehicle/live.py"):
            self.assertTrue(any(p.match(path) for p in mp._DENY_P["samvision"]), path)

    def test_no_compiled_pattern_keeps_a_literal_brace(self):
        for pats in list(mp._DENY_P.values()) + [mp._COMMON] + list(mp._FREE.values()) + list(mp._CODE.values()):
            for p in pats:
                self.assertNotIn("\\{", p.pattern)
                self.assertNotIn("\\}", p.pattern)
        self.assertNotIn("{", mp._glob("a/{b,c}.py"))

    def test_every_deny_entry_matches_a_sample_path(self):
        def sample(pat):
            return pat.replace("**/", "a/").replace("**", "a/b").replace("*", "x")
        for project in PROJECTS:
            compiled = mp._COMMON + mp._DENY_P[project]
            for pat in mp.COMMON_DENY + mp._deny_of(project):
                for one in mp.expand_braces(pat):
                    s = sample(one)
                    self.assertTrue(any(p.match(s) for p in compiled), (project, pat, s))

    def test_deny_wins_over_an_allow_entry(self):
        # app/**/page.tsx is allowed in MFE, and the expenses and reports pages are denied: deny wins
        for path in ("app/expenses/[id]/page.tsx", "app/reports/[householdId]/page.tsx", "app/dashboard/page.tsx"):
            self.assertTrue(mp.allowed("mfe", path), path)
            self.assertTrue(mp.denied(path, "mfe"), path)
            self.assertTrue(refused("mfe", path), path)
        self.assertTrue(mp.allowed("gyst", "internal/handlers/handlers.go"))
        self.assertTrue(mp.denied("internal/handlers/handlers.go", "gyst"))

    def test_the_name_catch_all_is_tested_against_every_path_part(self):
        # the old catch-all matched only the file name, so a folder called login or auth let the page through
        for path in ("app/login/page.tsx", "app/settings/password/page.tsx", "app/api-keys/token/page.tsx",
                     "app/(auth)/x/page.tsx", "components/session/panel.tsx", "app/oauth/x/page.tsx"):
            self.assertTrue(mp.allowed("mfe", path), path)
            self.assertTrue(mp.name_hit(path), path)
            self.assertTrue(refused("mfe", path), path)
        self.assertEqual(mp.name_hit("components/logout-button.tsx"), "logout")

    def test_the_name_catch_all_ignores_case(self):
        for project, path in (("gyst", "internal/services/Auth.go"), ("mfe", "components/LOGIN-form.tsx"),
                              ("mfe", "components/Session/x.tsx")):
            self.assertTrue(refused(project, path), path)

    def test_a_non_ascii_path_is_refused(self):
        # a Cyrillic a in auth.go would slip past every name match
        for project, path in (("gyst", "internal/services/аuth.go"), ("mfe", "components/lоgin.tsx")):
            self.assertFalse(mp.safe_path(path))
            self.assertEqual(mp.file_reasons(project, [f(path)], 5, 2), ["a changed file has an unusable path"])


class PerProject(unittest.TestCase):
    """The plan's refused lists, per project, and one qualifying change each."""

    def test_samvision_refused(self):
        for path in ("samvision/api/web.py", "samvision/api/settings.py", "samvision/api/market.py",
                     "samvision/api/calibration.py", "samvision/api/templates/_sold_table.html",
                     "samvision/api/templates/_market_panel.html", "samvision/api/templates/_explorer_panel.html",
                     "samvision/api/templates/cme_report.html", "samvision/api/templates/imports_new.html",
                     "samvision/api/templates/reset.html", "samvision/api/templates/account.html",
                     "samvision/api/static/leaflet.js", "samvision/api/static/htmx.min.js", "samvision/cma/x.py",
                     "parsed_csv/a.csv", "samvision/api/auth.py", "samvision/api/tenancy.py"):
            self.assertTrue(refused("samvision", path), path)
            self.assertTrue(refused("samvision", path, "ADDED"), path)

    def test_gyst_refused(self):
        for path in ("internal/handlers/handlers.go", "internal/handlers/requestlog.go", "internal/handlers/localpath.go",
                     "internal/handlers/auth.go", "internal/handlers/health_water.go",
                     "internal/repository/repository.go", "internal/repository/execer.go",
                     "internal/repository/audit.go", "internal/repository/settings.go", "internal/services/push.go",
                     "migrations/x.sql", "web/templates/layout.html", "web/templates/settings.html",
                     "web/static/js/galaxy.js", "web/static/service-worker.js", "cmd/server/main.go",
                     "internal/db/db.go"):
            self.assertTrue(refused("gyst", path), path)

    def test_mfe_refused(self):
        for path in ("lib/expenses.ts", "lib/reporting.ts", "lib/reporting/export-csv.ts", "lib/categories.ts",
                     "lib/validation/household.ts", "lib/uploads.ts", "app/layout.tsx", "app/clients/page.tsx",
                     "components/logout-button.tsx", "components/login-form.tsx", "prisma/schema.prisma", "package.json",
                     "proxy.ts", "next.config.ts", "components/accountant-view.tsx", "app/api/x/page.tsx"):
            self.assertTrue(refused("mfe", path), path)

    def test_command_center_refused(self):
        for path in ("server/ccd/merge_policy.py", "web/app/src/App.tsx", ".github/workflows/ci.yml", "scripts/x.sh",
                     "policy/projects/mfe.toml", "docs/adr/0008-x.md", "AGENTS.md", "server/ccd/merge_facts.py"):
            self.assertTrue(refused("commandcenter", path), path)

    def test_one_small_change_qualifies_per_project(self):
        cases = {"commandcenter": [f("server/tests/test_x.py", "ADDED"), f("docs/API.md")],
                 "mfe": [f("lib/utils.ts"), f("tests/money.test.ts", "ADDED")],
                 "gyst": [f("internal/services/calendar.go"), f("internal/services/calendar_test.go", "ADDED")],
                 "samvision": [f("samvision/vehicle/helpers.py"), f("tests/test_helpers.py", "ADDED")]}
        for project, files in cases.items():
            d = decide_in(project, files)
            self.assertEqual((d.ok, d.reasons), (True, []), project)

    def test_mixed_pr_one_allowed_one_refused_is_refused(self):
        for project, files in (("mfe", [f("lib/utils.ts"), f("lib/expenses.ts")]),
                               ("gyst", [f("internal/services/calendar.go"), f("internal/handlers/handlers.go")]),
                               ("samvision", [f("samvision/vehicle/helpers.py"), f("samvision/api/web.py")])):
            d = decide_in(project, files)
            self.assertFalse(d.ok, project)

    def test_renamed_deleted_and_copied_files_are_refused(self):
        for change in ("RENAMED", "DELETED", "COPIED", "CHANGED"):
            self.assertTrue(refused("gyst", "internal/services/calendar.go", change), change)

    def test_new_app_files_are_refused_but_new_tests_and_docs_are_not(self):
        # tech review H2: an ADDED page has no base text, so it dodges the content rule
        for project, path in (("mfe", "app/x/page.tsx"), ("gyst", "internal/handlers/x.go"),
                              ("samvision", "samvision/api/x.py"), ("mfe", "components/new-card.tsx"),
                              ("gyst", "web/static/js/new.js")):
            r = mp.file_reasons(project, [f(path, "ADDED")], 5, 0)
            self.assertTrue(r and "new app file" in r[0], (project, path, r))
            self.assertEqual(mp.file_reasons(project, [f(path, "MODIFIED")], 5, 0), [], (project, path))
        for project, path in (("mfe", "tests/new.test.ts"), ("gyst", "internal/services/new_test.go"),
                              ("samvision", "tests/test_new.py"), ("mfe", "docs/new.md")):
            self.assertEqual(mp.file_reasons(project, [f(path, "ADDED")], 5, 0), [], (project, path))

    def test_the_other_projects_checkout_paths_are_not_allowed_in_this_one(self):
        self.assertTrue(refused("mfe", "internal/services/calendar.go"))
        self.assertTrue(refused("gyst", "lib/utils.ts"))
        self.assertTrue(refused("samvision", "lib/utils.ts"))


class ContentRule(unittest.TestCase):
    """An allowed file whose text imports the sign-in, database or permission layer is refused, base or head."""

    def cases(self):
        return [("mfe", "components/card.tsx", 'import { prisma } from "@/lib/db/prisma";'),
                ("mfe", "components/card.tsx", 'import { requireHouseholdMember } from "../lib/auth/permissions";'),
                ("mfe", "app/x/page.tsx", "const s = await getSession();"),
                ("mfe", "components/card.tsx", "if (canViewReport(user)) {"),
                ("mfe", "components/card.tsx", "const c = cookies();"),
                ("gyst", "internal/services/calendar.go", "rows, err := s.Repo.ListEvents(ctx)"),
                ("gyst", "internal/services/calendar.go", 'import "lifeops-tracker/internal/repository"'),
                ("gyst", "internal/services/calendar.go", 'import "database/sql"'),
                ("gyst", "internal/services/calendar.go", "func init() { register() }"),
                ("samvision", "samvision/api/routes_x.py", "from .tenancy import scope"),
                ("samvision", "samvision/vehicle/helpers.py", "from sqlalchemy import text"),
                ("samvision", "samvision/analytics/x.py", "user = current_user()"),
                ("samvision", "samvision/api/static/extra.js", "const m = L.map('map');"),
                ("mfe", "public/logo.svg", "<svg><script>alert(1)</script></svg>"),
                ("mfe", "public/logo.svg", '<svg><a href="javascript:alert(1)"/></svg>'),
                ("mfe", "public/logo.svg", '<svg onload="x()"></svg>'),
                ("mfe", "public/logo.svg", "<svg><foreignObject/></svg>"),
                ("mfe", "components/card.tsx", "const m = await import(name);"),
                ("samvision", "samvision/vehicle/helpers.py", "importlib.import_module(name)")]

    def test_head_text_with_a_marker_is_refused(self):
        for project, path, text in self.cases():
            files = [f(path)]
            facts = facts_for(files, project)
            facts["texts"][path]["head"] = text
            d = decide_in(project, files, facts)
            self.assertFalse(d.ok, (project, path, text))
            self.assertTrue(any("sign-in, database or permission layer (head text)" in r for r in d.reasons), d.reasons)

    def test_base_text_with_a_marker_is_refused_even_when_the_edit_removes_nothing(self):
        # a one-line change in a file that already wires the auth layer is the case the rule is for
        for project, path, text in self.cases():
            files = [f(path)]
            facts = facts_for(files, project)
            facts["texts"][path]["base"] = text
            d = decide_in(project, files, facts)
            self.assertFalse(d.ok, (project, path, text))
            self.assertTrue(any("(base text)" in r for r in d.reasons), d.reasons)

    def test_a_clean_file_passes_and_a_test_file_is_exempt(self):
        d = decide_in("mfe", [f("lib/utils.ts")])
        self.assertTrue(d.ok, d.reasons)
        # the name catch-all still refuses a test file called auth-*; a neutral name shows the content exemption
        files = [f("tests/flow.test.ts")]
        facts = facts_for(files, "mfe")
        facts["texts"]["tests/flow.test.ts"] = {"head": 'import { getSession } from "@/lib/auth/session";',
                                                "base": "const prisma = 1; prisma.x()"}
        self.assertTrue(decide_in("mfe", files, facts).ok)

    def test_missing_unreadable_or_truncated_facts_refuse(self):
        files = [f("lib/utils.ts")]
        cases = {"no facts": None, "errors": facts_for(files, errors=["gh down"]),
                 "truncated": facts_for(files, truncated=True)}
        for name, facts in cases.items():
            self.assertFalse(decide_in("mfe", files, facts).ok, name)
        facts = facts_for(files)
        facts["texts"]["lib/utils.ts"]["head"] = None       # over 1 MB: the contents API sends no text
        self.assertFalse(decide_in("mfe", files, facts).ok)
        facts = facts_for(files)
        del facts["texts"]["lib/utils.ts"]
        self.assertFalse(decide_in("mfe", files, facts).ok)
        facts = facts_for(files)
        facts["texts"]["lib/utils.ts"].pop("base")
        self.assertFalse(decide_in("mfe", files, facts).ok)

    def test_contents_with_no_text_is_not_an_empty_file(self):
        good = {"type": "file", "encoding": "base64", "content": base64.b64encode(b"x = 1\n").decode()}
        self.assertEqual(mp.text_of_contents(good), "x = 1\n")
        for bad in (None, {}, {"type": "symlink"}, {"type": "file", "encoding": "none", "content": ""},
                    {"type": "file", "encoding": "base64", "content": None},
                    {"type": "file", "encoding": "base64", "content": base64.b64encode(b"\xff\xfe").decode()}):
            self.assertIsNone(mp.text_of_contents(bad), bad)


class Modes(unittest.TestCase):
    def test_symlink_submodule_executable_or_unread_modes_are_refused(self):
        files = [f("lib/utils.ts")]
        for mode in ("120000", "160000", "100755", "040000", None):
            for side in ("base", "head"):
                facts = facts_for(files)
                facts["modes"]["lib/utils.ts"][side] = mode
                self.assertFalse(decide_in("mfe", files, facts).ok, (mode, side))
        facts = facts_for(files)
        del facts["modes"]["lib/utils.ts"]
        self.assertFalse(decide_in("mfe", files, facts).ok)

    def test_an_added_file_must_not_exist_at_base(self):
        files = [f("docs/x.md", "ADDED")]
        facts = facts_for(files)
        facts["modes"]["docs/x.md"]["base"] = "100644"
        self.assertFalse(decide_in("mfe", files, facts).ok)


class LabelsSizeAndScreens(unittest.TestCase):
    def test_risk_labels_on_the_pr_or_an_issue_refuse(self):
        files = [f("lib/utils.ts")]
        for label in ("risk:elevated", "risk:privileged", "risk:not-agent-eligible", "type:security", "security",
                      "Risk:Elevated", " SECURITY "):
            facts = facts_for(files, labels=["bug", label])
            d = decide_in("mfe", files, facts)
            self.assertFalse(d.ok, label)
            self.assertTrue(any("risk label" in r for r in d.reasons), d.reasons)
        self.assertTrue(decide_in("mfe", files, facts_for(files, labels=["bug", "docs"])).ok)

    def test_labels_that_could_not_all_be_read_refuse(self):
        files = [f("lib/utils.ts")]
        self.assertFalse(decide_in("mfe", files, facts_for(files, labelsComplete=False)).ok)

    def test_size_must_be_small_and_never_risky(self):
        files = [f("lib/utils.ts")]
        small = {"stored": "small", "effective": "small", "everRisky": False, "raised": False, "parentRisky": False}
        self.assertTrue(decide_in("mfe", files, facts_for(files, size=small)).ok)
        for over in ({"stored": "standard", "effective": "standard"}, {"stored": None, "effective": None},
                     {"stored": "small", "effective": "risky"}, {"everRisky": True}, {"raised": True},
                     {"parentRisky": True}):
            d = decide_in("mfe", files, facts_for(files, size=dict(small, **over)))
            self.assertFalse(d.ok, over)
        self.assertFalse(decide_in("mfe", files, facts_for(files, size=None)).ok)

    def test_screen_files_need_a_passed_user_check_at_the_head(self):
        for project, path in (("mfe", "components/card.tsx"), ("gyst", "web/templates/index.html"),
                              ("gyst", "web/static/css/app.css"), ("samvision", "samvision/api/static/extra.js")):
            files = [f(path)]
            self.assertFalse(decide_in(project, files).ok, path)
            ok = decide_in(project, files, w=work(userCheck={"result": "pass", "head": HEAD}))
            self.assertTrue(ok.ok, (path, ok.reasons))
            for uc in ({"result": "fail", "head": HEAD}, {"result": "pass", "head": "cd" * 20}):
                self.assertFalse(decide_in(project, files, w=work(userCheck=uc)).ok, (path, uc))
        self.assertTrue(decide_in("mfe", [f("lib/utils.ts")]).ok)       # not a screen file: no user check needed


class NamedChecks(unittest.TestCase):
    def test_the_project_checks_are_registered(self):
        self.assertEqual(registry.checks_of("commandcenter"), ("backend", "web"))
        self.assertEqual(registry.checks_of("mfe"), ("checks",))
        self.assertEqual(registry.checks_of("gyst"), ("check",))
        self.assertEqual(registry.checks_of("samvision"), ("tests", "licensed-data", "stylesheet"))
        self.assertEqual({k: registry.base_of(k) for k in PROJECTS},
                         {"commandcenter": "main", "mfe": "main", "gyst": "master", "samvision": "main"})

    def test_a_green_rollup_without_the_named_jobs_is_not_green(self):
        files = [f("docs/x.md", "ADDED")]
        for rollup in ([], green("lint"), green("backend"), [run("backend"), run("web", workflow="")],
                       [{"conclusion": "SUCCESS", "state": "SUCCESS", "context": "backend"}]):
            d = decide_in("commandcenter", files, rollup=rollup)
            self.assertFalse(d.ok, rollup)
            self.assertNotEqual(d.ci, "green", rollup)

    def test_a_commit_status_or_a_third_party_check_does_not_satisfy_a_named_job(self):
        files = [f("docs/x.md", "ADDED")]
        status = {"__typename": "StatusContext", "context": "web", "state": "SUCCESS"}
        d = decide_in("commandcenter", files, rollup=[run("backend"), status])
        self.assertFalse(d.ok)
        self.assertIn("required CI check web is missing", d.reasons)
        d = decide_in("commandcenter", files, rollup=[run("backend"), run("web", workflow=""), ])
        self.assertFalse(d.ok)
        d = decide_in("commandcenter", files, rollup=[run("backend"), run("web", typ="StatusContext")])
        self.assertFalse(d.ok)

    def test_one_named_job_failing_or_pending_is_not_green(self):
        files = [f("docs/x.md", "ADDED")]
        d = decide_in("samvision", files, rollup=[run("tests"), run("licensed-data", "FAILURE"), run("stylesheet")])
        self.assertEqual((d.ok, d.wait), (False, False))
        d = decide_in("samvision", files, rollup=[run("tests"), run("licensed-data", "", "IN_PROGRESS"), run("stylesheet")])
        self.assertEqual((d.ok, d.wait), (False, True))
        d = decide_in("samvision", files, rollup=green("tests", "licensed-data"))
        self.assertIn("required CI check stylesheet is missing", d.reasons)
        self.assertTrue(decide_in("samvision", files, rollup=green("tests", "licensed-data", "stylesheet")).ok)

    def test_extra_third_party_checks_never_count(self):
        files = [f("docs/x.md", "ADDED")]
        rollup = green("backend", "web") + [run("codecov", workflow="")]
        self.assertTrue(decide_in("commandcenter", files, rollup=rollup).ok)
        d = decide_in("commandcenter", files, rollup=[run("codecov", workflow="")])
        self.assertFalse(d.ok)

    def test_the_base_branch_is_per_project(self):
        files = [f("docs/x.md", "ADDED")]
        self.assertTrue(decide_in("gyst", files).ok)
        d = decide_in("gyst", files, baseRefName="main")
        self.assertFalse(d.ok)
        self.assertIn("not master", " ".join(d.reasons))
        self.assertFalse(decide_in("mfe", files, baseRefName="master").ok)


class SecuritySignOff(unittest.TestCase):
    def test_each_trigger_alone_makes_a_security_sign_off_required(self):
        files = [f("lib/utils.ts")]
        self.assertFalse(mp.security_required("mfe", ticket(), files, [], facts_for(files)))
        self.assertTrue(mp.security_required("mfe", ticket(type="SECURITY"), files, [], facts_for(files)))
        for label in ("security", "migration", "risk:elevated", "risk:privileged", "type:security"):
            self.assertTrue(mp.security_required("mfe", ticket(), files, [label], facts_for(files)), label)
            self.assertTrue(mp.security_required("mfe", ticket(labels=[label]), files, [], facts_for(files)), label)
        for path in ("lib/expenses.ts", "app/login/page.tsx", "prisma/schema.prisma"):    # deny and name hits
            self.assertTrue(mp.security_required("mfe", ticket(), [f(path)], [], None), path)
        bad = facts_for(files)
        bad["texts"]["lib/utils.ts"]["head"] = 'import { prisma } from "@/lib/db/prisma"'
        self.assertTrue(mp.security_required("mfe", ticket(), files, [], bad))             # content marker


def _sized_flow_base():
    class B(unittest.TestCase):
        def setUp(self):
            self.ts = TaskStore(":memory:", [{"key": "commandcenter", "name": "Command Center", "prefix": "CC"}])
            self.pl = Pipeline(self.ts)
    return B


class FlowFacts(_sized_flow_base()):
    PLAN = {"summary": "tests", "approach": "x", "reproduced": "yes", "findings": ["a"]}
    SHA = "abcdef1234567890abcdef1234567890abcdef12"
    SHA2 = "1234567890abcdef1234567890abcdef12345678"

    def sized(self, size, parent=None):
        k = self.ts.create("commandcenter", "T", description="a thing to do")[0]["key"]
        self.pl.intake(k, size, ["it works"], "agent:coordinator", priority="MEDIUM", parent=parent)
        return k

    def in_review(self, k):
        self.pl.start(k, f"{k}-x", f"/tmp/wt/{k}", "agent:coordinator")
        self.pl.role(k, "implementer", "agent:implementer", session="dev-1")
        self.ts.update(k, {"status": "IN_REVIEW"}, "system:automation", trigger="PR #1 is open")

    def pr(self, head=None):
        return {"ref": "JayDalool/CommandCenter#1", "head": head or self.SHA}

    def test_a_small_ticket_reports_small_and_no_history(self):
        k = self.sized("small")
        self.assertEqual(self.pl.merge_size_facts(k), {"stored": "small", "effective": "small", "everRisky": False,
                                                       "raised": False, "parentRisky": False})

    def test_a_ticket_raised_by_the_technical_reviewer_is_marked(self):
        k = self.sized("standard")
        self.pl.role(k, "planner", "agent:planner", session="inv-1")
        self.pl.plan(k, self.PLAN, "agent:planner", session="inv-1")
        self.pl.plan_review(k, "APPROVE", "agent:tech-reviewer", "bigger than it looks", blast="b", tests=["t"],
                            size="risky", session="tr-1")
        facts = self.pl.merge_size_facts(k)
        self.assertEqual((facts["stored"], facts["raised"], facts["everRisky"]), ("risky", True, True))
        self.assertTrue(mp.size_reasons(facts))

    def test_a_ticket_that_was_risky_at_intake_stays_marked_after_it_is_lowered(self):
        k = self.sized("risky")
        self.pl.define(k, "jay", size="standard", developer=True)
        facts = self.pl.merge_size_facts(k)
        self.assertEqual((facts["stored"], facts["everRisky"]), ("standard", True))

    def test_a_risky_parent_marks_the_child(self):
        parent = self.sized("risky")
        child = self.sized("small", parent=parent)
        self.assertTrue(self.pl.merge_size_facts(child)["parentRisky"])
        calm = self.sized("standard")
        self.assertFalse(self.pl.merge_size_facts(self.sized("small", parent=calm))["parentRisky"])

    def test_security_check_is_the_security_engineers_and_bound_to_one_head(self):
        k = self.sized("small")
        self.in_review(k)
        for actor in ("agent:reviewer", "agent:implementer", "agent:user-reviewer", "jay", "agent:coordinator"):
            with self.assertRaises(TaskError) as e:
                self.pl.security_check(k, "pass", self.SHA, actor, "looked", pr=self.pr(), session="sec-1")
            self.assertEqual(e.exception.status, 403, actor)
        self.assertFalse(self.pl.security_signoff(k, self.SHA))
        self.pl.security_check(k, "pass", self.SHA, "agent:security-engineer", "no auth change", pr=self.pr(), session="sec-1")
        self.assertTrue(self.pl.security_signoff(k, self.SHA))
        self.assertFalse(self.pl.security_signoff(k, self.SHA2))          # a pass at head A does not count for head B

    def test_the_newest_check_for_a_head_wins(self):
        k = self.sized("small")
        self.in_review(k)
        self.pl.security_check(k, "pass", self.SHA, "agent:security-engineer", "ok", pr=self.pr(), session="sec-1")
        self.pl.security_check(k, "fail", self.SHA, "agent:security-engineer", "found a hole", pr=self.pr(), session="sec-1")
        self.assertFalse(self.pl.security_signoff(k, self.SHA))

    def test_the_implementer_session_cannot_record_it(self):
        k = self.sized("small")
        self.in_review(k)
        for session in ("dev-1", k, k.lower()):
            with self.assertRaises(TaskError) as e:
                self.pl.security_check(k, "pass", self.SHA, "agent:security-engineer", "ok", pr=self.pr(), session=session)
            self.assertEqual(e.exception.status, 409, session)
        self.assertFalse(self.pl.security_signoff(k, self.SHA))

    def test_security_check_needs_the_current_head_a_note_a_session_and_a_real_sha(self):
        k = self.sized("small")
        self.in_review(k)
        sec = "agent:security-engineer"
        for kwargs, status in (({"head": self.SHA2}, 409), ({"head": "abc"}, 400), ({"note": ""}, 400),
                               ({"session": None}, 400), ({"result": "maybe"}, 400)):
            args = dict(result="pass", head=self.SHA, note="ok", session="sec-1")
            args.update(kwargs)
            with self.assertRaises(TaskError) as e:
                self.pl.security_check(k, args["result"], args["head"], sec, args["note"], pr=self.pr(), session=args["session"])
            self.assertEqual(e.exception.status, status, kwargs)
        with self.assertRaises(TaskError):      # no PR ccd can see
            self.pl.security_check(k, "pass", self.SHA, sec, "ok", pr=None, session="sec-1")


class Switch(unittest.TestCase):
    def test_the_switch_fails_closed(self):
        self.assertEqual(config.auto_merge_projects([]), ([], None))
        self.assertEqual(config.auto_merge_projects(False), ([], None))
        self.assertEqual(config.auto_merge_projects(True), (["commandcenter"], None))   # the old boolean
        self.assertEqual(config.auto_merge_projects(["mfe", "commandcenter", "mfe"]), (["commandcenter", "mfe"], None))
        for bad in ("true", "commandcenter", 1, 0, None, {"mfe": True}, [None], ["mfe", 7], ["nope"], ["mfe", "nope"],
                    [["mfe"]], [True]):
            projects, why = config.auto_merge_projects(bad)
            self.assertEqual(projects, [], bad)
            self.assertTrue(why, bad)

    def test_a_paused_or_client_project_can_never_be_switched_on(self):
        projects, why = config.auto_merge_projects(["gauzemate"])
        self.assertEqual(projects, [])
        self.assertIn("paused or client", why)
        projects, why = config.auto_merge_projects(["commandcenter", "gauzemate"])
        self.assertEqual(projects, [])         # one bad key voids the list: a typo never half-applies

    def test_the_default_is_an_empty_list(self):
        self.assertEqual(config.DEFAULTS["auto_merge"], [])

    def test_every_registered_low_risk_project_has_rules_and_the_others_do_not(self):
        for key in PROJECTS:
            self.assertEqual(pipeline.policy({"project": key}, key)["merge"], "low-risk", key)
            self.assertIn(key, mp.PROJECT)
            self.assertTrue(registry.checks_of(key) and registry.base_of(key), key)
        self.assertNotIn("gauzemate", mp.PROJECT)
        self.assertEqual(registry.checks_of("gauzemate"), ())


class FactsFetch(unittest.TestCase):
    """merge_facts.fetch with a fake `gh api`: every read pinned to a SHA, every failure refuses."""
    BASE = "ba" * 20

    def gh(self, **over):
        calls = []
        text = base64.b64encode(b"export const x = 1;\n").decode()
        answers = {"pull": {"base": {"sha": self.BASE, "ref": "main"}, "head": {"sha": HEAD}, "labels": [{"name": "bug"}],
                            "body": "Refs #12"},
                   "linked": {"closingIssuesReferences": []},
                   "commits": [{"sha": "c1" * 20}],
                   "commit": {"files": [{"filename": "lib/utils.ts"}]},
                   "issue": {"labels": [{"name": "risk:elevated"}]},
                   "tree": {"truncated": False, "tree": [{"path": "lib/utils.ts", "mode": "100644"}]},
                   "contents": {"type": "file", "encoding": "base64", "content": text}}
        answers.update(over)

        def run_(args):
            calls.append(args)
            if args[:3] == ["gh", "pr", "view"]:
                if isinstance(answers["linked"], Exception):
                    raise answers["linked"]
                return answers["linked"]
            path = args[2]
            if path.endswith("/commits?per_page=100"):
                if isinstance(answers["commits"], Exception):
                    raise answers["commits"]
                return answers["commits"]
            for key, marker in (("commit", "/commits/"), ("pull", "/pulls/"), ("issue", "/issues/"), ("tree", "/git/trees/"),
                                ("contents", "/contents/")):
                if marker in path:
                    if isinstance(answers[key], Exception):
                        raise answers[key]
                    return answers[key]
            raise OSError("unexpected")
        return run_, calls

    def test_labels_of_the_pr_and_referenced_issues_are_read_and_reads_are_pinned(self):
        gh, calls = self.gh()
        facts = merge_facts.fetch(gh, "JayDalool/MyFamilyExpenses", 7, HEAD, [f("lib/utils.ts")], "mfe")
        self.assertEqual(facts["errors"], [])
        self.assertEqual(sorted(facts["labels"]), ["bug", "risk:elevated"])
        self.assertEqual(facts["base"], {"ref": "main", "sha": self.BASE})
        self.assertTrue(facts["labelsComplete"])
        self.assertEqual(facts["modes"]["lib/utils.ts"], {"base": "100644", "head": "100644"})
        self.assertEqual(facts["texts"]["lib/utils.ts"], {"base": "export const x = 1;\n", "head": "export const x = 1;\n"})
        refs = [c[2] for c in calls]
        self.assertIn(f"repos/JayDalool/MyFamilyExpenses/git/trees/{self.BASE}?recursive=1", refs)
        self.assertIn(f"repos/JayDalool/MyFamilyExpenses/git/trees/{HEAD}?recursive=1", refs)
        self.assertIn(f"repos/JayDalool/MyFamilyExpenses/contents/lib/utils.ts?ref={self.BASE}", refs)
        self.assertIn(f"repos/JayDalool/MyFamilyExpenses/contents/lib/utils.ts?ref={HEAD}", refs)
        d = decide_in("mfe", [f("lib/utils.ts")], facts)
        self.assertFalse(d.ok)                  # the Issue's risk:elevated label refuses it
        self.assertTrue(any("risk label" in r for r in d.reasons))

    def test_every_failure_mode_lands_in_errors_and_refuses(self):
        for over in ({"pull": OSError("gh down")}, {"tree": OSError("rate limited")}, {"contents": ValueError("bad json")},
                     {"pull": {"base": {"sha": "nothex"}, "head": {"sha": HEAD}}},
                     {"pull": {"base": {"sha": self.BASE}, "head": {"sha": "cd" * 20}}},     # the head moved
                     {"tree": {"truncated": True, "tree": []}}, {"tree": {"tree": []}}, {"tree": []},
                     {"issue": {"labels": None}}):
            gh, _ = self.gh(**over)
            facts = merge_facts.fetch(gh, "JayDalool/MyFamilyExpenses", 7, HEAD, [f("lib/utils.ts")], "mfe")
            d = decide_in("mfe", [f("lib/utils.ts")], facts)
            self.assertFalse(d.ok, over)

    def test_too_many_referenced_issues_refuse(self):
        body = " ".join(f"Refs #{n}" for n in range(1, 30))
        gh, _ = self.gh(pull={"base": {"sha": self.BASE}, "head": {"sha": HEAD}, "labels": [], "body": body})
        facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")
        self.assertTrue(facts["errors"])
        self.assertFalse(facts["labelsComplete"])

    def test_test_files_are_not_read_for_text_but_their_modes_are(self):
        gh, calls = self.gh(tree={"truncated": False, "tree": [{"path": "tests/a.test.ts", "mode": "120000"}]})
        facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("tests/a.test.ts")], "mfe")
        self.assertFalse([c for c in calls if "/contents/" in c[2]])
        self.assertFalse(decide_in("mfe", [f("tests/a.test.ts")], facts).ok)          # a symlinked test is refused

    def test_an_added_file_is_read_at_head_only(self):
        gh, calls = self.gh(tree={"truncated": False, "tree": [{"path": "docs/x.md", "mode": "100644"}]})
        # base tree lacks nothing here: the same tree answers both sides, so the file looks present at base too
        facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("docs/x.md", "ADDED")], "mfe")
        self.assertEqual([c[2].rpartition("ref=")[2] for c in calls if "/contents/" in c[2]], [HEAD])
        self.assertEqual(list(facts["texts"]["docs/x.md"]), ["head"])


class RoundTwo(FactsFetch):
    """Codex review round 1 of PR A: base race, commit history, every reference source, pending checks, sign-off."""

    def test_the_base_branch_comes_from_the_same_pinned_read_as_the_head(self):
        gh, _ = self.gh(pull={"base": {"sha": self.BASE, "ref": "release"}, "head": {"sha": HEAD}, "labels": [], "body": ""})
        facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")
        self.assertEqual(facts["base"]["ref"], "release")
        # the PR view said main a moment ago; the files were judged against release: refused
        d = decide_in("mfe", [f("lib/utils.ts")], facts)
        self.assertFalse(d.ok)
        self.assertIn("the PR's base branch is not the one the files were judged against", d.reasons)
        self.assertEqual(decide_in("mfe", [f("lib/utils.ts")], facts_for([f("lib/utils.ts")], "mfe", base=None)).ok, False)

    def test_verify_catches_a_retarget_with_the_same_head(self):
        facts = {"head": HEAD, "base": {"ref": "main", "sha": self.BASE}}
        ok = lambda args: {"base": {"ref": "main", "sha": self.BASE}, "head": {"sha": HEAD}}      # noqa: E731
        self.assertEqual(merge_facts.verify(ok, "o/r", 7, facts), "")
        retarget = lambda args: {"base": {"ref": "release", "sha": self.BASE}, "head": {"sha": HEAD}}   # noqa: E731
        self.assertIn("base", merge_facts.verify(retarget, "o/r", 7, facts))
        advanced = lambda args: {"base": {"ref": "main", "sha": "cd" * 20}, "head": {"sha": HEAD}}       # noqa: E731
        self.assertIn("base", merge_facts.verify(advanced, "o/r", 7, facts))
        moved = lambda args: {"base": {"ref": "main", "sha": self.BASE}, "head": {"sha": "cd" * 20}}     # noqa: E731
        self.assertIn("head", merge_facts.verify(moved, "o/r", 7, facts))

        def down(args):
            raise OSError("gh down")
        self.assertTrue(merge_facts.verify(down, "o/r", 7, facts))
        self.assertTrue(merge_facts.verify(lambda a: [], "o/r", 7, facts))

    def test_a_denied_path_in_an_intermediate_commit_refuses_even_when_the_net_diff_is_clean(self):
        files = [f("samvision/vehicle/helpers.py")]
        clean = facts_for(files, "samvision")
        self.assertTrue(decide_in("samvision", files, clean).ok)
        for touched in ("parsed_csv/x.csv", "samvision/cma/x.py", "samvision/api/auth.py", ".github/workflows/ci.yml"):
            facts = facts_for(files, "samvision", history=["samvision/vehicle/helpers.py", touched])
            d = decide_in("samvision", files, facts)
            self.assertFalse(d.ok, touched)
            self.assertTrue(any("a commit of the PR touched" in r for r in d.reasons), d.reasons)
        self.assertFalse(decide_in("samvision", files, facts_for(files, "samvision", history=None)).ok)

    def test_the_history_is_read_from_every_commit_including_renames(self):
        gh, calls = self.gh(commits=[{"sha": "c1" * 20}, {"sha": "c2" * 20}],
                            commit={"files": [{"filename": "lib/utils.ts"},
                                              {"filename": "lib/new.ts", "previous_filename": "prisma/schema.prisma"}]})
        facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")
        self.assertEqual(facts["errors"], [])
        self.assertEqual(facts["history"], ["lib/new.ts", "lib/utils.ts", "prisma/schema.prisma"])
        self.assertEqual(len([c for c in calls if "/commits/" in c[2]]), 2)
        self.assertFalse(decide_in("mfe", [f("lib/utils.ts")], dict(facts, labels=[])).ok)     # the old name is denied

    def test_a_history_that_cannot_be_inspected_refuses(self):
        for over in ({"commits": []}, {"commits": [{"sha": "c1" * 20}] * 21}, {"commits": OSError("down")},
                     {"commits": [{"sha": "nothex"}]}, {"commit": {"files": [{"filename": "a"}] * 300}},
                     {"commit": {"nofiles": 1}}, {"commit": {"files": [{"nope": 1}]}}):
            gh, _ = self.gh(**over)
            facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")
            self.assertTrue(facts["errors"], over)
            self.assertFalse(decide_in("mfe", [f("lib/utils.ts")], facts).ok, over)

    def test_every_reference_source_is_read(self):
        body = ("Refs #1, see https://github.com/o/r/issues/2 and other/repo#3 and "
                "https://github.com/third/place/pull/4. Not a ref: abc#5 or a/b/c#6.")
        refs = merge_facts.references("o/r", body, [{"number": 9, "repository": {"nameWithOwner": "o/r"}},
                                                    {"number": 10, "repository": {"nameWithOwner": "x/y"}}],
                                      ["o/r#11", "z/z#12"])
        self.assertEqual(refs, {("o/r", 1), ("o/r", 2), ("other/repo", 3), ("third/place", 4), ("o/r", 9), ("x/y", 10),
                                ("o/r", 11), ("z/z", 12)})
        for bad in ([{"number": "9"}], ["no-number"]):
            with self.assertRaises(ValueError):
                merge_facts.references("o/r", "", bad if isinstance(bad[0], dict) else [], bad if isinstance(bad[0], str) else [])

    def test_a_risk_label_on_a_url_qualified_or_linked_issue_refuses(self):
        for name, over in (("url", {"pull": {"base": {"sha": self.BASE, "ref": "main"}, "head": {"sha": HEAD}, "labels": [],
                                             "body": "Fixes https://github.com/JayDalool/MyFamilyExpenses/issues/12"}}),
                           ("qualified", {"pull": {"base": {"sha": self.BASE, "ref": "main"}, "head": {"sha": HEAD},
                                                   "labels": [], "body": "Refs other/repo#12"}}),
                           ("linked", {"pull": {"base": {"sha": self.BASE, "ref": "main"}, "head": {"sha": HEAD},
                                                "labels": [], "body": ""},
                                       "linked": {"closingIssuesReferences": [{"number": 12, "repository":
                                                                               {"nameWithOwner": "o/r"}}]}})):
            gh, calls = self.gh(**over)
            facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")
            self.assertEqual(facts["errors"], [], name)
            self.assertIn("risk:elevated", facts["labels"], name)
            self.assertFalse(decide_in("mfe", [f("lib/utils.ts")], facts).ok, name)
        gh, calls = self.gh(pull={"base": {"sha": self.BASE, "ref": "main"}, "head": {"sha": HEAD}, "labels": [],
                                  "body": "Refs other/repo#12"})
        merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")
        self.assertIn("repos/other/repo/issues/12", [c[2] for c in calls])

    def test_the_tickets_own_github_issue_links_count_and_unreadable_ones_refuse(self):
        gh, calls = self.gh(pull={"base": {"sha": self.BASE, "ref": "main"}, "head": {"sha": HEAD}, "labels": [], "body": ""})
        facts = merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe", ["o/r#40"])
        self.assertIn("risk:elevated", facts["labels"])
        for over in ({"linked": OSError("down")}, {"linked": {"closingIssuesReferences": [{"number": "x"}]}},
                     {"issue": OSError("down")}):
            gh, _ = self.gh(**over)
            self.assertTrue(merge_facts.fetch(gh, "o/r", 7, HEAD, [f("lib/utils.ts")], "mfe")["errors"], over)


class PendingAndSignOff(unittest.TestCase):
    def test_a_pending_check_outside_the_required_names_waits(self):
        files = [f("docs/x.md", "ADDED")]
        rollup = green("backend", "web") + [run("web-e2e", "", "IN_PROGRESS")]
        d = decide_in("commandcenter", files, rollup=rollup)
        self.assertEqual((d.ok, d.wait, d.ci), (False, True, "pending"))
        d = decide_in("commandcenter", files, rollup=green("backend", "web") + [run("codecov", "", "QUEUED", workflow="")])
        self.assertEqual((d.ok, d.wait, d.ci), (False, True, "pending"))

    def test_classify_needs_the_sign_off_when_it_is_required_or_unknown(self):
        files = [f("docs/x.md", "ADDED")]
        self.assertTrue(decide_in("commandcenter", files).ok)
        for facts in (facts_for(files, securityRequired=True), facts_for(files, securityRequired=None),
                      facts_for(files, securityRequired=True, securitySignoff=False)):
            d = decide_in("commandcenter", files, facts)
            self.assertFalse(d.ok)
            self.assertIn("the change needs a security sign-off at this head", d.reasons)
        self.assertTrue(decide_in("commandcenter", files, facts_for(files, securityRequired=True, securitySignoff=True)).ok)
        bad = facts_for(files)
        del bad["securityRequired"]
        self.assertFalse(decide_in("commandcenter", files, bad).ok)


class ConfigFile(unittest.TestCase):
    def test_a_rejected_auto_merge_value_is_never_copied_into_the_message(self):
        for bad in ("super-secret-token-123", {"k": "super-secret-token-123"}, ["super-secret-token-123"], 12345):
            projects, why = config.auto_merge_projects(bad)
            self.assertEqual(projects, [])
            self.assertNotIn("super-secret", why)
            self.assertNotIn("12345", why)

    def test_an_unreadable_or_invalid_config_file_gives_defaults_an_empty_switch_and_a_diagnostic(self):
        import os
        import tempfile
        d = tempfile.mkdtemp(prefix="cfg-")
        bad = os.path.join(d, "config.json")
        open(bad, "w").write('{"auto_merge": ["commandcenter"], oops')
        cfg = config.load(bad)
        self.assertEqual(cfg["auto_merge"], [])
        self.assertIn("could not be read", cfg["_config_problem"])
        self.assertNotIn("oops", cfg["_config_problem"])
        os.chmod(bad, 0)
        try:
            cfg = config.load(bad)
            self.assertEqual(cfg["auto_merge"], [])
            self.assertIn("_config_problem", cfg)
        finally:
            os.chmod(bad, 0o600)
        good = os.path.join(d, "ok.json")
        open(good, "w").write('{"auto_merge": ["commandcenter"]}')
        cfg = config.load(good)
        self.assertEqual((cfg["auto_merge"], "_config_problem" in cfg), (["commandcenter"], False))


if __name__ == "__main__":
    unittest.main()
