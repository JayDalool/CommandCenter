"""Tickets over HTTP/WS, GitHub automation, dispatch by ticket, workspaces, and the served UI."""
import json
import os
import tempfile

from .helpers import wait_sync, pr
from .test_api import AUTH, HOST, JSON, PORT, TOKEN, ApiBase


class TaskApi(ApiBase):
    def create(self, **body):
        r = self.post("/api/tasks", dict({"project": "commandcenter", "title": "a ticket"}, **body))
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def patch(self, key, body, headers=JSON):
        return self.client.patch(f"/api/tasks/{key}", content=json.dumps(body), headers=headers)

    def test_create_list_get(self):
        t = self.create(priority="HIGH", assignee="role:PLANNER")
        self.assertEqual((t["key"], t["priority"], t["assignee"]), ("CC-001", "HIGH", "role:PLANNER"))
        lst = self.get("/api/tasks").json()
        self.assertEqual([x["key"] for x in lst["tickets"]], ["CC-001"])
        self.assertIn("INBOX", lst["meta"]["statuses"])
        self.assertIn("CC", {p["prefix"] for p in lst["projects"]})
        self.assertEqual(self.get("/api/tasks/CC-001").json()["title"], "a ticket")
        self.assertEqual(self.get("/api/tasks/cc-001").json()["key"], "CC-001")
        self.assertEqual(self.get("/api/tasks/CC-999").status_code, 404)

    def test_patch_comment_relate_link(self):
        self.create()
        self.create(title="other")
        r = self.patch("CC-001", {"status": "IN_PROGRESS", "needs_jay": True, "labels": ["ui"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "IN_PROGRESS")
        self.assertEqual(self.post("/api/tasks/CC-001/comments", {"body": "hello\nworld"}).json()["comments"][0]["body"],
                         "hello\nworld")
        self.assertEqual(self.post("/api/tasks/CC-001/relations", {"kind": "blocked_by", "target": "CC-002"})
                         .json()["blockedBy"], ["CC-002"])
        t = self.post("/api/tasks/CC-001/links", {"provider": "github", "kind": "pr", "ref": "JayDalool/x#5",
                                                  "url": "https://github.com/JayDalool/x/pull/5"}).json()
        self.assertEqual(t["prNumber"], 5)
        self.assertEqual(self.patch("CC-001", {"status": "NOPE"}).status_code, 400)

    def test_writes_need_token_and_json(self):
        self.assertEqual(self.client.post("/api/tasks", content="{}", headers=HOST).status_code, 401)
        r = self.client.patch("/api/tasks/CC-001", content='{"title":"x"}',
                              headers=dict(AUTH, **{"content-type": "text/plain"}))
        self.assertEqual(r.status_code, 415)
        r = self.client.post("/api/tasks", content="project=commandcenter&title=x",
                             headers=dict(AUTH, **{"content-type": "application/x-www-form-urlencoded"}))
        self.assertEqual(r.status_code, 415)

    def test_flags_reach_the_global_needs_queue(self):
        self.create()
        before = self.get("/api/state").json()["totals"]["needs"]
        self.patch("CC-001", {"flags": {"needs_ui_review": True}})
        st = self.get("/api/state").json()
        n = [x for x in st["needs"] if x["kind"] == "ticket"]
        self.assertEqual([(x["ref"], x["flags"]) for x in n], [("CC-001", ["needs_ui_review"])])
        self.assertEqual(st["totals"]["needs"], before + 1)
        self.assertTrue(st["sources"]["tasks"]["ok"])

    def test_mutations_are_live_events(self):
        with self.client.websocket_connect("/api/events", headers=AUTH) as ws:
            self.assertEqual(ws.receive_json()["type"], "hello")
            self.create()
            ev = ws.receive_json()
            self.assertEqual((ev["event"]["kind"], ev["event"]["ref"]), ("task.created", "CC-001"))
            self.patch("CC-001", {"status": "PROPOSED"})
            ev = ws.receive_json()["event"]
            self.assertEqual((ev["kind"], ev["data"]["kind"], ev["data"]["to"]), ("task.updated", "status", "PROPOSED"))

    def test_context_is_an_agent_brief(self):
        self.create(title="Ship the thing")
        ctx = self.get("/api/tasks/CC-001/context").json()
        self.assertIn("CC-001 · Ship the thing", ctx["brief"])
        self.assertIn("Not authorized", ctx["brief"])
        self.assertFalse(ctx["dispatchable"])

    def test_import_preview_writes_nothing(self):
        r = self.get("/api/tasks/import-preview")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["applied"])
        self.assertEqual(self.get("/api/tasks").json()["tickets"], [])


class Automation(ApiBase):
    def poll(self):
        self.daemon._auto_seen.clear()
        self.client.portal.call(self.daemon.poll_github_once)
        self.settle()

    def ticket(self, status):
        t, _ = self.tickets.create("samvision", "feature", number=56, status=status)
        return t

    def test_open_pr_links_and_moves_to_review_then_ready_then_verifying(self):
        self.ticket("IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefName="sv-056-feature")]
        self.poll()
        t = self.tickets.get("SV-056")
        self.assertEqual((t["status"], t["prNumber"], t["branch"]), ("IN_REVIEW", 94, "sv-056-feature"))
        auto = [e for e in t["timeline"] if e["actor"] == "system:automation"]
        self.assertTrue(all(e["trigger"] for e in auto))
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature", review="APPROVED"),
                                                 headRefName="sv-056-feature")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "READY_TO_MERGE")
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 94, "title": "SV-056: the feature", "url": "u",
                                                "mergedAt": "2026-10-03T00:00:00Z"}]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "VERIFYING")

    def test_no_transition_from_weak_signals(self):
        self.ticket("PROPOSED")
        self.tickets.create("samvision", "other", number=57, status="READY_TO_IMPLEMENT")
        # a merged PR never seen open, and a red PR: no status moves
        self.gh.data["samvision"]["merged"] = [{"number": 90, "title": "SV-057 tidy", "url": "u", "mergedAt": "x"}]
        self.gh.data["samvision"]["prs"] = [pr(95, "SV-056 draft idea", ci="FAILURE")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "PROPOSED")  # linked, but not moved from PROPOSED
        self.assertEqual(self.tickets.get("SV-056")["prNumber"], 95)
        self.assertEqual(self.tickets.get("SV-057")["status"], "READY_TO_IMPLEMENT")

    MERGED_94 = [{"number": 94, "title": "SV-056: the feature", "url": "u", "mergedAt": "2026-10-03T00:00:00Z",
                  "mergeCommit": {"oid": "f" * 40}}]

    def test_a_merge_moves_a_ticket_once_and_a_reopen_waits_for_a_new_merge(self):
        self.ticket("IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefName="sv-056-feature")]
        self.poll()
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = self.MERGED_94
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "VERIFYING")
        self.tickets.update("SV-056", {"status": "IN_PROGRESS"}, "jay")          # Jay reopens it
        self.gh.data["samvision"]["prs"] = [dict(pr(95, "SV-056: the fix"), headRefName="sv-056-feature")]
        for _ in range(2):                                                         # #94 is still in the merged list
            self.poll()
            self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")
        # a NEW merge still moves it
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 95, "title": "SV-056: the fix", "url": "u",
                                                "mergedAt": "2026-10-04T00:00:00Z"}] + self.MERGED_94
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "VERIFYING")

    def test_a_ticket_set_back_to_review_by_hand_is_not_sent_on_by_an_old_merge(self):
        self.ticket("IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefName="sv-056-feature")]
        self.poll()
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = self.MERGED_94
        self.poll()
        self.tickets.update("SV-056", {"status": "DONE"}, "jay")
        self.tickets.update("SV-056", {"status": "IN_REVIEW"}, "jay")
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")

    def test_other_projects_keys_are_not_linked(self):
        self.tickets.create("gauzemate", "gz thing")
        self.gh.data["samvision"]["prs"] = [pr(96, "mentions GZ-001 in passing")]
        self.poll()
        self.assertEqual(self.tickets.get("GZ-001")["links"], [])


class DispatchByTicket(ApiBase):
    def test_dispatch_accepts_an_existing_ticket_and_moves_it(self):
        self.tickets.create("samvision", "plan me", number=56, status="PROPOSED")
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "SV-056", "verb": "plan"})
        self.assertEqual(r.status_code, 200, r.text)
        t = self.tickets.get("SV-056")
        self.assertEqual(t["status"], "RESEARCHING")
        self.assertIn("dispatch", t["timeline"][-1]["trigger"])

    def test_dispatch_refuses_unknown_or_foreign_tickets(self):
        self.tickets.create("gauzemate", "gz")
        # Shape alone is not enough to cross projects: GZ-001 is GauzeMate's.
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "GZ-001", "verb": "plan"})
        self.assertEqual(r.status_code, 409)
        # A retired prefix behaves the same once its ticket exists.
        self.tickets.db.execute("INSERT OR IGNORE INTO task_project_aliases(prefix, project, retired_at) "
                                "VALUES ('GM', 'gauzemate', 0)")
        self.tickets.create("gauzemate", "legacy numbered", number=14)
        self.assertTrue(self.tickets.exists("GZ-014"))
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "nonsense", "verb": "plan"})
        self.assertEqual(r.status_code, 400)


class Workspaces(ApiBase):
    def test_state_has_the_herdr_layout_without_titles(self):
        st = self.get("/api/state").json()
        ws = {w["label"]: w for w in st["workspaces"]}
        cc = ws["Command Center"]
        tab = cc["tabs"][0]
        cells = {c["id"]: c for c in tab["panes"]}
        self.assertEqual(cells["wE:p2"]["agentName"], "samvision")
        self.assertEqual(cells["wE:p2"]["role"], "coordinator")
        self.assertEqual(tab["area"], {"w": 120, "h": 40})
        self.assertNotIn("What still needs my answer", json.dumps(st["workspaces"]))

    def test_focus_workspace_and_tab(self):
        r = self.post("/api/action/focus", {"workspaceId": "wE"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(("workspace.focus", {"workspace_id": "wE"}), self.fake.calls)
        r = self.post("/api/action/focus", {"tabId": "wE:t2"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.post("/api/action/focus", {"workspaceId": "zz"}).status_code, 404)
        self.assertEqual(self.post("/api/action/focus", {"workspaceId": "a b"}).status_code, 400)


class WsSubprotocol(ApiBase):
    def test_token_as_subprotocol_keeps_it_out_of_the_url(self):
        with self.client.websocket_connect("/api/events", headers=dict(HOST),
                                           subprotocols=["ccd.v1", f"ccd-token.{TOKEN}"]) as ws:
            self.assertEqual(ws.accepted_subprotocol, "ccd.v1")
            self.assertEqual(ws.receive_json()["type"], "hello")

    def test_wrong_subprotocol_token_is_refused(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/api/events", headers=dict(HOST),
                                               subprotocols=["ccd.v1", "ccd-token.nope"]) as ws:
                ws.receive_json()


class ServedUi(ApiBase):
    def setUp(self):
        self.ui = tempfile.mkdtemp(prefix="ui-")
        os.makedirs(os.path.join(self.ui, "assets"))
        with open(os.path.join(self.ui, "index.html"), "w") as f:
            f.write("<!doctype html><title>CC</title>")
        with open(os.path.join(self.ui, "assets", "app.js"), "w") as f:
            f.write("console.log(1)")
        super().setUp()

    def test_ui_is_served_without_token_but_api_still_needs_it(self):
        r = self.client.get("/", headers=HOST)
        self.assertEqual(r.status_code, 200)
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertEqual(self.client.get("/assets/app.js", headers=HOST).status_code, 200)
        self.assertEqual(self.client.get("/api/state", headers=HOST).status_code, 401)
        self.assertEqual(self.client.get("/", headers=dict(HOST, host=f"evil:{PORT}")).status_code, 403)
        self.assertEqual(self.client.post("/", content="{}", headers=HOST).status_code, 405)

    def test_route_table_is_unchanged_by_the_mount(self):
        self.assertTrue(all(r.path.startswith("/api") for r in self.app.state.routes_table))


class ReviewFindings(ApiBase):
    """Regression tests for the P4B-3 review (stale ready, weak keys, create leaks, merged lookup, actor)."""

    def poll(self):
        self.daemon._auto_seen.clear()
        self.client.portal.call(self.daemon.poll_github_once)
        self.settle()

    def test_ready_to_merge_falls_back_when_the_pr_stops_being_ready(self):
        self.tickets.create("samvision", "f", number=56, status="IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [pr(94, "SV-056: f", review="APPROVED")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "READY_TO_MERGE")
        self.gh.data["samvision"]["prs"] = [pr(94, "SV-056: f", review="APPROVED", ci="FAILURE")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")

    def test_automation_never_undoes_a_human_status(self):
        self.tickets.create("samvision", "f", number=56, status="IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [pr(94, "SV-056: f")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")
        self.tickets.update("SV-056", {"status": "IN_PROGRESS"}, "jay")  # changes requested
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_PROGRESS")

    def test_mentions_reverts_and_lookalike_branches_do_not_link(self):
        self.tickets.create("samvision", "f", number=40, status="IN_PROGRESS")
        self.tickets.create("samvision", "g", number=2, status="IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [
            pr(91, "follow-up to SV-040"), pr(92, "Revert \"SV-040: f\""),
            dict(pr(93, "2fa"), headRefName="sv-2fa"), dict(pr(97, "x"), headRefName="feat/sv-0021")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-040")["links"], [])
        self.assertEqual(self.tickets.get("SV-002")["links"], [])
        self.assertEqual(self.tickets.pr_keys("feat(ui): SV-040 thing"), ["SV-040"])
        self.assertEqual(self.tickets.pr_keys("x", "claude/sv-040-fix"), ["SV-040"])
        self.assertEqual(self.tickets.pr_keys("sv-040 lowercase title"), [])

    def test_merged_pr_found_through_its_link_not_its_title(self):
        self.tickets.create("samvision", "f", number=56, status="IN_PROGRESS")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "Untitled"), headRefName="sv-056-x")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 94, "title": "Untitled", "url": "u", "mergedAt": "x"}]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "VERIFYING")

    def test_create_refuses_import_only_and_unknown_fields(self):
        for body in ({"number": 999999}, {"number": "x"}, {"actor": "system:x"}, {"id": 5}):
            r = self.post("/api/tasks", dict({"project": "commandcenter", "title": "t"}, **body))
            self.assertEqual(r.status_code, 400, (body, r.text))
        self.assertEqual(self.post("/api/tasks", {"project": "commandcenter", "title": "t"}).json()["key"], "CC-001")

    def test_create_closed_sets_completed(self):
        r = self.post("/api/tasks", {"project": "commandcenter", "title": "t", "status": "DONE"}).json()
        self.assertIsNotNone(r["completedAt"])

    def test_actor_header_attributes_agent_writes(self):
        h = dict(JSON, **{"x-ccd-actor": "agent:samvision"})
        r = self.client.post("/api/tasks", content=json.dumps({"project": "commandcenter", "title": "t"}), headers=h)
        self.assertEqual(r.json()["creator"], "agent:samvision")
        h = dict(JSON, **{"x-ccd-actor": "system:automation"})
        r = self.client.post("/api/tasks", content=json.dumps({"project": "commandcenter", "title": "t"}), headers=h)
        self.assertEqual(r.status_code, 400)

    def test_prefix_collision_is_an_error(self):
        from ccd import registry
        with self.assertRaises(registry.RegistryError):
            self.tickets.sync_projects([{"key": "sv2", "name": "x", "prefix": "SV"}])
        # A retired prefix is just as taken as a live one: numbers are never recycled.
        with self.assertRaises(registry.RegistryError):
            self.tickets.sync_projects([{"key": "gm2", "name": "x", "prefix": "GM"}])


class ServerData(ApiBase):
    def test_top_processes_are_names_and_memory_only(self):
        from ccd.daemon import top_processes
        rows, claude = top_processes(limit=5)
        self.assertLessEqual(len(rows), 5)
        self.assertTrue(all(set(r) == {"pid", "name", "rssMB"} for r in rows))
        self.assertIsInstance(claude, int)

    def test_state_carries_worktrees(self):
        st = self.get("/api/state").json()
        self.assertIn("/srv/server/worktrees/samvisionai/SV-056", st["worktrees"]["samvision"])


class DevelopmentView(ApiBase):
    """Ticket → branch → commits → PR → CI → review → merge → verify, on evidence only."""

    def poll(self):
        self.daemon._auto_seen.clear()
        self.client.portal.call(self.daemon.poll_github_once)
        self.settle()

    def rows(self, **q):
        r = self.get("/api/development" + ("?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else ""))
        self.assertEqual(r.status_code, 200, r.text)
        return {row["key"]: row for row in r.json()["rows"]}

    def with_branches(self, project, branches):
        self.daemon.git["branches"] = {project: branches}

    def test_a_ticket_with_no_work_and_no_activity_is_not_listed(self):
        self.tickets.create("samvision", "just an idea")
        self.assertNotIn("SV-001", self.rows())

    def test_roles_and_pipeline_review_appear_only_where_a_pipeline_step_recorded_them(self):
        self.tickets.create("samvision", "plain", status="IN_PROGRESS", assignee="agent:planner")
        self.tickets.create("samvision", "piped", status="INBOX")
        self.daemon.pipeline.plan("SV-002", {"summary": "do it", "tests": ["unit"]}, "agent:planner", model="opus")
        self.daemon.pipeline.start("SV-002", "SV-002-piped", "/srv/server/worktrees/sv/SV-002", "agent:implementer",
                                   model="sonnet")
        rows = self.rows()
        self.assertEqual(rows["SV-001"]["roles"], {})
        self.assertIsNone(rows["SV-001"]["pipelineReview"])
        self.assertEqual(sorted(rows["SV-002"]["roles"]), ["implementer", "planner"])
        self.assertEqual(rows["SV-002"]["roles"]["planner"]["model"], "opus")
        self.assertEqual(set(rows["SV-002"]["roles"]["planner"]), {"model", "at"})
        self.assertIsNone(rows["SV-002"]["pipelineReview"])
        head = "94" * 20
        self.tickets.update("SV-002", {"status": "IN_REVIEW"})
        self.daemon.pipeline.review("SV-002", "APPROVE", head, "agent:reviewer", session="review-1", model="opus")
        row = self.rows()["SV-002"]
        self.assertEqual(row["roles"]["reviewer"]["model"], "opus")
        self.assertEqual(row["pipelineReview"], {"verdict": "APPROVE", "head": head})

    def test_an_active_ticket_is_listed_even_before_any_work(self):
        self.tickets.create("samvision", "started", status="IN_PROGRESS")
        row = self.rows()["SV-001"]
        self.assertIsNone(row["branch"])
        self.assertIsNone(row["pr"])
        self.assertIsNone(row["commits"])

    def test_the_tickets_own_branch_brings_its_commit_count(self):
        self.tickets.create("samvision", "work", status="IN_PROGRESS", branch="SV-001-valuation")
        self.with_branches("samvision", {"SV-001-valuation": {"commits": 4, "head": "abc1234", "at": 1,
                                                              "countOk": True}})
        row = self.rows()["SV-001"]
        self.assertEqual((row["branch"]["name"], row["branch"]["evidence"]), ("SV-001-valuation", "ticket branch"))
        self.assertEqual((row["commits"], row["branch"]["head"]), (4, "abc1234"))

    def test_a_branch_whose_leading_segment_is_the_key_counts_as_evidence(self):
        self.tickets.create("samvision", "work", status="IN_PROGRESS")
        self.with_branches("samvision", {"sv-001-fix": {"commits": 2, "head": "d00d", "at": 1, "countOk": True},
                                         "follow-up-to-SV-001": {"commits": 9, "head": "bad", "at": 2,
                                                                 "countOk": True}})
        row = self.rows()["SV-001"]
        self.assertEqual(row["branch"]["name"], "sv-001-fix")           # leads the segment
        self.assertEqual(row["branch"]["evidence"], "branch named for the ticket")
        self.assertEqual(row["commits"], 2)                              # not the 9 of the mention-only branch

    def test_a_key_mentioned_in_a_branch_name_is_not_an_association(self):
        self.tickets.create("samvision", "work", status="IN_PROGRESS")
        self.with_branches("samvision", {"revert-SV-001": {"commits": 3, "head": "x", "at": 1, "countOk": True}})
        self.assertIsNone(self.rows()["SV-001"]["branch"])

    def test_a_linked_pr_brings_ci_review_and_the_merge_column(self):
        self.tickets.create("samvision", "work", status="IN_REVIEW")
        self.gh.data["samvision"]["prs"] = [pr(103, "SV-001: work", ci="SUCCESS", review="APPROVED")]
        self.poll()
        row = self.rows()["SV-001"]
        self.assertEqual((row["pr"]["number"], row["pr"]["state"]), (103, "OPEN"))
        self.assertEqual((row["ci"], row["review"]), ("PASS", "APPROVED"))
        self.assertEqual(row["merge"], "WAITING FOR JAY")      # automation moved it to READY_TO_MERGE
        self.assertEqual(row["status"], "READY_TO_MERGE")
        self.assertIsNone(row["deploy"])                        # ccd observes no deployments

    def test_failing_checks_read_as_fail(self):
        self.tickets.create("samvision", "work", status="IN_REVIEW")
        self.gh.data["samvision"]["prs"] = [pr(104, "SV-001: work", ci="FAILURE")]
        self.poll()
        row = self.rows()["SV-001"]
        self.assertEqual((row["ci"], row["review"], row["merge"]), ("FAIL", "PENDING", None))

    def test_a_merged_pr_shows_merged_and_verification_pending(self):
        self.tickets.create("samvision", "work", status="IN_REVIEW")
        self.gh.data["samvision"]["prs"] = [pr(105, "SV-001: work")]
        self.poll()
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 105, "title": "SV-001: work", "url": "u",
                                               "mergedAt": "2026-10-03T00:00:00Z"}]
        self.poll()
        row = self.rows()["SV-001"]
        self.assertEqual((row["pr"]["state"], row["merge"], row["verify"]), ("MERGED", "MERGED", "PENDING"))

    def test_the_project_filter_narrows_the_view(self):
        self.tickets.create("samvision", "sv work", status="IN_PROGRESS")
        self.tickets.create("gauzemate", "gz work", status="IN_PROGRESS")
        self.assertEqual(sorted(self.rows(project="gauzemate")), ["GZ-001"])

    def test_a_cached_github_row_without_a_number_is_skipped_not_fatal(self):
        self.daemon.gh["samvision"] = {"asOf": 1.0, "error": None,
                                       "data": {"prs": [{"title": "no number"}, pr(107, "SV-001: work")],
                                                "merged": [{"title": "also none"}]}}
        index = self.daemon._pr_index("samvision")
        self.assertEqual(sorted(index), [107])

    def test_an_odd_default_branch_is_refused_not_passed_to_git(self):
        from ccd import sources
        self.assertEqual(sources.branches_ahead("/srv/server/apps/samvisionai", "--upload-pack=touch /tmp/x"), {})
        self.assertEqual(sources.branches_ahead("/srv/server/apps/samvisionai", ""), {})


class PipelineApi(Automation):
    """The pipeline over HTTP: agent-attributed steps, head-bound approval that survives GitHub polls,
    owner gates only with Developer Unlock, gates in the one Needs Jay queue."""
    DEV = "d" * 43
    key = "SV-056"

    def equip(self, daemon):
        from ccd import security
        daemon.dev_gate = security.DeveloperGate(self.DEV)

    def step(self, op, body, actor="agent:coordinator", headers=None):
        h = dict(JSON, **{"x-ccd-actor": actor}, **(headers or {}))
        return self.client.post(f"/api/tasks/{self.key}/work/{op}", content=json.dumps(body), headers=h)

    def test_a_ticket_travels_plan_to_done_and_every_step_is_attributed(self):
        self.ticket("INBOX")
        plan = {"summary": "the feature", "tests": ["unit"]}
        self.assertEqual(self.step("plan", {"plan": plan, "model": "opus"}, "agent:planner").json()["status"],
                         "READY_TO_IMPLEMENT")
        r = self.step("start", {"branch": "SV-056-feature", "worktree": "/srv/server/worktrees/sv/SV-056"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
        head = "94" * 20
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefName="SV-056-feature", headRefOid=head)]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")
        r = self.step("review", {"verdict": "APPROVE", "head": head, "session": "review-1"}, "agent:reviewer")
        self.assertEqual(r.json()["status"], "READY_TO_MERGE", r.text)
        for _ in range(2):                       # no GitHub approval: must NOT flap back to IN_REVIEW
            self.poll()
            self.assertEqual(self.tickets.get("SV-056")["status"], "READY_TO_MERGE")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature", review="APPROVED"),
                                                 headRefName="SV-056-feature", headRefOid="95" * 20)]
        self.poll()                              # a new head + a stale GitHub approval: never promotes
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")
        kinds = [e["data"].get("kind") for e in self.get("/api/activity?limit=200").json()["events"]
                 if e["kind"] == "task.pipeline"]
        self.assertIn("pipeline.review_stale", kinds)             # automatic steps reach the event log
        evs = [e for e in self.get("/api/activity?limit=200").json()["events"] if e["kind"] == "task.pipeline"]
        # Who recorded a step goes with it (Slack posts it under that seat); ccd's own poll records none.
        self.assertEqual({e["data"].get("actor") for e in evs if e["data"].get("kind") == "pipeline.review"},
                         {"agent:reviewer"})
        self.assertFalse(any(e["data"].get("actor") for e in evs if e["data"].get("kind") == "pipeline.review_stale"))
        head = "95" * 20
        self.assertEqual(self.step("review", {"verdict": "APPROVE", "head": head, "session": "review-1"}, "agent:reviewer").json()["status"],
                         "READY_TO_MERGE")
        needs = [n for n in self.get("/api/state").json()["needs"] if n.get("ref") == "SV-056"]
        self.assertEqual([n["gate"] for n in needs], ["merge"])
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 94, "title": "SV-056: the feature", "url": "u",
                                                "mergedAt": "2026-10-03T00:00:00Z", "mergeCommit": {"oid": "f" * 40}}]
        self.poll()
        w = self.get("/api/tasks/SV-056/work").json()
        self.assertEqual((w["status"], w["gate"], w["merge"]["sha"]), ("VERIFYING", None, "f" * 40))
        r = self.step("verify", {"result": "pass", "evidence": "health ok"}, "agent:verifier")
        self.assertEqual(r.json()["status"], "DONE", r.text)
        # Closing releases the task's sessions in the background on ccd's loop; read through the API (the loop's
        # thread), never the shared SQLite connection from this test thread, once that has finished.
        wait_sync(lambda: self.get("/api/tasks/SV-056/work").json().get("released") is not None, what="released")
        actors = {e["actor"] for e in self.get("/api/tasks/SV-056").json()["timeline"] if (e.get("kind") or "").startswith("pipeline.")}
        self.assertEqual(actors, {"agent:planner", "agent:coordinator", "agent:reviewer", "agent:verifier",
                                  "system:automation"})

    def to_review_at(self, head, number=56):
        """Plan, start, a PR at `head`, one poll: SV-0<number> is IN_REVIEW. Later steps act on that key."""
        self.key = f"SV-{number:03d}"
        self.tickets.create("samvision", "feature", number=number, status="INBOX")
        self.step("plan", {"plan": {"summary": "the feature", "tests": ["unit"]}}, "agent:planner")
        self.step("start", {"branch": f"{self.key}-feature", "worktree": f"/srv/server/worktrees/sv/{self.key}"})
        self.at_head(head)
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")

    def at_head(self, head):
        n = 100 + int(self.key[-3:])
        self.gh.data["samvision"]["prs"] = [dict(pr(n, f"{self.key}: the feature"), headRefName=f"{self.key}-feature",
                                                 headRefOid=head)]

    def status(self):
        return self.tickets.get(self.key)["status"]

    def test_release_settings_are_jays_with_developer_unlock(self):
        r = self.get("/api/release").json()
        self.assertEqual((r["window"]["weekday"], r["window"]["time"], r["projects"]["samvision"]),
                         (3, "22:00", {"live": False}))
        body = json.dumps({"live": True})
        self.assertEqual(self.client.put("/api/release/projects/samvision", content=body, headers=JSON).status_code, 403)
        dev = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON).json()
        h = dict(JSON, **{"x-ccd-developer": dev["session"]})
        self.addCleanup(lambda: self.daemon.releases.set_live("samvision", False))
        r = self.client.put("/api/release/projects/samvision", content=body, headers=h)
        self.assertEqual((r.status_code, r.json()["projects"]["samvision"]), (200, {"live": True}), r.text)
        self.assertEqual(self.client.put("/api/release/projects/nope", content=body, headers=h).status_code, 404)
        self.assertEqual(self.client.put("/api/release/window", content=json.dumps({"weekday": 9, "time": "22:00"}),
                                         headers=h).status_code, 400)
        self.assertEqual(self.client.put("/api/release/projects/samvision", content=body,
                                         headers=dict(h, **{"x-ccd-actor": "agent:coordinator"})).status_code, 403)

    def test_the_delivery_flow_over_http_and_the_flow_view(self):
        """Intake, technical review, user check, code review, merge, verify, the closing note; /api/flow shows it."""
        self.tickets.create("samvision", "feature", number=56, status="INBOX", description="Comps miss sold homes")
        r = self.step("intake", {"size": "standard", "criteria": ["Five comps show"], "priority": "HIGH"})
        self.assertEqual((r.status_code, r.json()["status"], r.json()["flow"]["stage"]), (200, "RESEARCHING", "investigate"))
        row = next(t for t in self.get("/api/tasks").json()["tickets"] if t["key"] == "SV-056")
        self.assertEqual((row["size"], row["stage"], row["stale"]), ("standard", "investigate", False))
        self.assertEqual(len(row["route"]), 9)
        self.step("role", {"role": "planner", "session": "inv-1"}, "agent:planner")
        self.step("plan", {"plan": {"summary": "the feature"}, "session": "inv-1"}, "agent:planner")
        r = self.step("plan-review", {"verdict": "APPROVE", "note": "ok", "session": "inv-1"}, "agent:tech-reviewer")
        self.assertEqual(r.status_code, 409, r.text)                               # its own plan
        r = self.step("plan-review", {"verdict": "APPROVE", "note": "ok", "session": "tr-1"}, "agent:tech-reviewer")
        self.assertEqual(r.json()["status"], "READY_TO_IMPLEMENT", r.text)
        self.step("start", {"branch": "SV-056-feature", "worktree": "/srv/server/worktrees/sv/SV-056"})
        head = "94" * 20
        self.at_head(head)
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")
        r = self.step("review", {"verdict": "APPROVE", "head": head, "session": "cr-1"}, "agent:reviewer")
        self.assertEqual(r.status_code, 409, r.text)                               # the user check comes first
        r = self.step("user-check", {"result": "pass", "head": head, "note": "tried it", "session": "ur-1",
                                     "criteria": ["c1=pass"]}, "agent:user-reviewer")
        self.assertEqual(r.json()["flow"]["stage"], "codeReview", r.text)
        flow = self.get("/api/flow").json()["projects"]
        sv = next(p for p in flow if p["key"] == "samvision")
        self.assertEqual([s["seat"] for s in sv["seats"]], ["lead", "investigator", "techReviewer", "developer",
                                                           "userReviewer", "designReviewer", "codeReviewer", "verifier"])
        self.assertEqual([(t["key"], t["stage"], t["waitingOn"]) for t in sv["inFlight"]],
                         [("SV-056", "codeReview", "reviewer")])
        self.assertEqual(len(sv["inFlight"][0]["route"]), 9)
        self.assertEqual(sv["limits"], {"investigate": {"used": 0, "max": 2}, "build": {"used": 0, "max": 2}})
        r = self.step("review", {"verdict": "APPROVE", "head": head, "session": "cr-1"}, "agent:reviewer")
        self.assertEqual(r.json()["status"], "READY_TO_MERGE", r.text)
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 156, "title": "SV-056: the feature", "url": "u",
                                                "mergedAt": "2026-10-03T00:00:00Z", "mergeCommit": {"oid": "f" * 40}}]
        self.poll()
        self.assertEqual(self.status(), "VERIFYING")
        r = self.step("verify", {"result": "pass", "evidence": "health ok"}, "agent:verifier")
        self.assertEqual((r.json()["status"], r.json()["flow"]["waitingOn"]), ("VERIFYING", "lead"), r.text)
        r = self.step("close", {"note": "Comps fixed."})
        self.assertEqual(r.json()["status"], "DONE", r.text)
        kinds = [e["data"].get("kind") for e in self.get("/api/activity?limit=200").json()["events"]
                 if e["kind"] == "task.pipeline"]
        for k in ("pipeline.intake", "pipeline.plan_reviewed", "pipeline.user_checked", "pipeline.closed_note"):
            self.assertIn(k, kinds)

    def test_rework_returns_to_review_only_on_a_new_head(self):
        a, b = "94" * 20, "95" * 20
        for number, actor in ((56, "agent:coordinator"), (57, "jay")):
            with self.subTest(actor=actor):
                self.to_review_at(a, number)
                r = self.step("review", {"verdict": "REQUEST_CHANGES", "head": a, "session": "review-1"}, "agent:reviewer")
                self.assertEqual(r.status_code, 200, r.text)
                r = self.step("rework", {"reason": "fix the findings"}, actor)
                self.assertEqual((r.status_code, r.json()["status"]), (200, "IN_PROGRESS"), r.text)
                for _ in range(2):                                  # the same head: no new work to review
                    self.poll()
                    self.assertEqual(self.status(), "IN_PROGRESS")
                self.at_head(b)
                self.poll()
                self.assertEqual(self.status(), "IN_REVIEW")
                last = self.tickets.last_status_event(self.key)
                self.assertEqual((last["actor"], last["from"], last["to"]), ("system:automation", "IN_PROGRESS", "IN_REVIEW"))
                self.assertIn(b[:7], last["trigger"])
                r = self.step("review", {"verdict": "APPROVE", "head": b, "session": "review-2"}, "agent:reviewer")
                self.assertEqual((r.status_code, r.json()["status"]), (200, "READY_TO_MERGE"), r.text)

    def test_rework_from_blocked_is_not_undone_by_the_next_poll(self):
        a = "94" * 20
        self.to_review_at(a)
        self.step("review", {"verdict": "REQUEST_CHANGES", "head": a, "session": "review-1"}, "agent:reviewer")
        r = self.step("block", {"reason": "waiting on a decision"})
        self.assertEqual(r.json()["status"], "BLOCKED", r.text)
        r = self.step("rework", {"reason": "fix it"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
        self.poll()                                                 # from BLOCKED, so from != IN_REVIEW
        self.assertEqual(self.status(), "IN_PROGRESS")
        self.at_head("95" * 20)
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")

    def test_a_second_rework_at_an_unreviewed_head_is_not_reversed(self):
        a, b, c = "94" * 20, "95" * 20, "96" * 20
        self.to_review_at(a)
        self.step("review", {"verdict": "REQUEST_CHANGES", "head": a, "session": "review-1"}, "agent:reviewer")
        self.step("rework", {"reason": "first"})
        self.at_head(b)
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")                 # b was never reviewed
        r = self.step("rework", {"reason": "second, before any review of b"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
        for _ in range(2):                                           # b != the reviewed head a, but b is known
            self.poll()
            self.assertEqual(self.status(), "IN_PROGRESS")
        self.at_head(c)
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertIn(c[:7], self.tickets.last_status_event("SV-056")["trigger"])

    def test_an_unrelated_open_pr_does_not_undo_a_rework(self):
        a = "94" * 20
        self.to_review_at(a)
        self.step("review", {"verdict": "REQUEST_CHANGES", "head": a, "session": "review-1"}, "agent:reviewer")
        self.tickets.link("SV-056", "github", "pr", "JayDalool/SamVisionAI#300",
                          "https://github.com/JayDalool/SamVisionAI/pull/300", "notes", "jay")
        self.gh.data["samvision"]["prs"].append(
            dict(pr(300, "unrelated notes"), headRefName="notes", headRefOid="c3" * 20))
        self.poll()                                                  # ccd sees both PRs open
        self.assertEqual(self.status(), "IN_REVIEW")
        self.step("rework", {"reason": "fix it"})                    # both open PRs are recorded with the rework
        for _ in range(2):
            self.poll()
            self.assertEqual(self.status(), "IN_PROGRESS")

    def test_a_replacement_pr_returns_a_reworked_ticket_to_review(self):
        a = "94" * 20
        self.to_review_at(a)
        self.step("review", {"verdict": "REQUEST_CHANGES", "head": a, "session": "review-1"}, "agent:reviewer")
        self.step("rework", {"reason": "start over"})
        self.poll()
        self.assertEqual(self.status(), "IN_PROGRESS")
        replacement = dict(pr(301, "SV-056: the feature again"), headRefName="SV-056-again", headRefOid="d4" * 20)
        self.gh.data["samvision"]["prs"] = [replacement]             # the old PR closed, a new one opened
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertIn("after rework", self.tickets.last_status_event("SV-056")["trigger"])

    def test_jay_status_edit_still_wins_on_a_pipeline_ticket(self):
        self.to_review_at("94" * 20)
        r = self.patch({"status": "IN_PROGRESS"}, "jay", self.unlock())      # Jay's manual edit: no trigger
        self.assertEqual((r.status_code, r.json()["status"]), (200, "IN_PROGRESS"), r.text)
        self.assertIsNone(self.tickets.last_status_event("SV-056")["trigger"])
        self.at_head("95" * 20)                                              # even a new head does not undo it
        self.poll()
        self.assertEqual(self.status(), "IN_PROGRESS")

    def test_a_new_pr_head_invalidates_the_approval(self):
        self.ticket("IN_REVIEW")
        self.tickets.link("SV-056", "github", "pr", "JayDalool/SamVisionAI#94", "https://github.com/JayDalool/SamVisionAI/pull/94", "t", "jay")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"))]
        self.poll()
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefOid="a" * 40)]
        self.poll()
        self.assertEqual(self.step("review", {"verdict": "APPROVE", "head": "a" * 40, "session": "review-1"}, "agent:reviewer")
                         .json()["status"], "READY_TO_MERGE")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefOid="b" * 40)]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")

    def test_owner_gates_need_jay_with_developer_unlock(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"labels": ["migration"]}, "jay")
        self.assertEqual(self.step("plan", {"plan": {"summary": "x"}}, "agent:planner").json()["gate"], "plan")
        self.assertEqual(self.step("confirm", {"gate": "plan"}, "jay").status_code, 403)          # no unlock
        sid = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON).json()["session"]
        dev = {"x-ccd-developer": sid}
        self.assertEqual(self.step("confirm", {"gate": "plan"}, "agent:coordinator", dev).status_code, 403)  # not Jay
        r = self.step("confirm", {"gate": "plan"}, "jay", dev)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "READY_TO_IMPLEMENT"))

    def test_review_refuses_a_ticket_with_several_open_prs(self):
        self.ticket("IN_REVIEW")
        for n in (94, 95):
            self.tickets.link("SV-056", "github", "pr", f"JayDalool/SamVisionAI#{n}",
                              f"https://github.com/JayDalool/SamVisionAI/pull/{n}", "t", "jay")
        self.gh.data["samvision"]["prs"] = [dict(pr(94)), dict(pr(95))]
        self.poll()
        self.assertEqual(self.step("review", {"verdict": "APPROVE", "head": "a" * 40, "session": "review-1"}, "agent:reviewer").status_code, 409)

    def test_a_gate_is_one_needs_jay_item_even_with_a_flag(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"needs_jay": True}, "jay")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        st = self.get("/api/state").json()
        mine = [n for n in st["needs"] if n.get("ref") == "SV-056"]
        self.assertEqual([n["kind"] for n in mine], ["gate"])

    def unlock(self):
        sid = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON).json()["session"]
        return {"x-ccd-developer": sid}

    def patch(self, body, actor="agent:coordinator", headers=None):
        h = dict(JSON, **{"x-ccd-actor": actor}, **(headers or {}))
        return self.client.patch("/api/tasks/SV-056", content=json.dumps(body), headers=h)

    def test_a_pipeline_ticket_never_jumps_a_gate_through_a_plain_edit(self):
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        # (b) no status jump: not by an agent, not by Jay without Developer Unlock
        for actor in ("agent:coordinator", "jay"):
            self.assertEqual(self.patch({"status": "READY_TO_MERGE"}, actor).status_code, 409, actor)
        self.assertEqual(self.tickets.get("SV-056")["status"], "READY_TO_IMPLEMENT")
        r = self.patch({"status": "BLOCKED"}, "jay", self.unlock())                    # Jay's explicit override
        self.assertEqual((r.status_code, r.json()["status"]), (200, "BLOCKED"))
        self.assertEqual(self.patch({"priority": "HIGH"}).status_code, 200)            # ordinary fields still edit

    def test_an_open_gate_cannot_be_dodged_by_editing_what_opened_it(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"labels": ["migration"]}, "jay")
        self.assertEqual(self.step("plan", {"plan": {"summary": "x"}}, "agent:planner").json()["gate"], "plan")
        # (c) drop the label, then re-plan: refused, and a re-plan never closes Jay's gate
        for body in ({"labels": []}, {"type": "DOCS"}, {"needs_jay": False}):
            self.assertEqual(self.patch(body).status_code, 409, body)
        self.tickets.update("SV-056", {"labels": []}, "jay")                            # even if it changed anyway…
        w = self.step("plan", {"plan": {"summary": "v2"}}, "agent:planner").json()
        self.assertEqual((w["gate"], w["planState"], w["status"]), ("plan", "proposed", "RESEARCHING"))

    def test_a_fix_pr_after_a_failed_verification_needs_review_and_merge_again(self):
        merged_94 = self.MERGED_94
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "the feature"}}, "agent:planner")
        self.step("start", {"branch": "SV-056-feature", "worktree": "/srv/server/worktrees/sv/SV-056"})
        head = "94" * 20
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: the feature"), headRefName="SV-056-feature", headRefOid=head)]
        self.poll()
        self.step("review", {"verdict": "APPROVE", "head": head, "session": "review-1"}, "agent:reviewer")
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = merged_94
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "VERIFYING")
        self.assertEqual(self.step("verify", {"result": "fail", "evidence": "health 500"}, "agent:verifier").json()["status"],
                         "BLOCKED")
        r = self.step("rework", {"reason": "fix the 500"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
        # the fix goes up as a NEW PR #97; #94 is still among GitHub's recently merged PRs
        head97 = "97" * 20
        self.gh.data["samvision"]["prs"] = [dict(pr(97, "SV-056: fix the 500"), headRefName="SV-056-feature",
                                                 headRefOid=head97)]
        for _ in range(2):
            self.poll()
            self.assertEqual(self.get("/api/tasks/SV-056/work").json()["status"], "IN_REVIEW")
        r = self.step("verify", {"result": "pass", "evidence": "looks fine"}, "agent:verifier")
        self.assertEqual(r.status_code, 409, r.text)
        # #97 is approved at its head, then merged: VERIFYING once, the merge record is #97
        self.assertEqual(self.step("review", {"verdict": "APPROVE", "head": head97, "session": "review-2"},
                                   "agent:reviewer").json()["status"], "READY_TO_MERGE")
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 97, "title": "SV-056: fix the 500", "url": "u",
                                                "mergedAt": "2026-10-05T00:00:00Z",
                                                "mergeCommit": {"oid": "e" * 40}}] + merged_94
        for _ in range(2):
            self.poll()
            w = self.get("/api/tasks/SV-056/work").json()
            self.assertEqual(w["status"], "VERIFYING")
            self.assertEqual(w["merge"]["pr"], "JayDalool/SamVisionAI#97")
        unreviewed = [e for e in self.get("/api/activity?limit=200").json()["events"] if e["kind"] == "task.pipeline"
                      and e["data"].get("kind") == "pipeline.unreviewed_merge"]
        self.assertEqual(unreviewed, [])

    def test_a_ui_gate_cannot_be_skipped_by_marking_done(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"needs_ui_review": True}, "jay")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        self.step("start", {"branch": "SV-056-x", "worktree": "/srv/w/SV-056"})
        self.tickets.update("SV-056", {"status": "VERIFYING"}, "system:automation")
        self.assertEqual(self.step("verify", {"result": "pass", "evidence": "ok"}, "agent:verifier").json()["gate"], "ui")
        # (a) an agent cannot mark it DONE around the UI gate
        self.assertEqual(self.patch({"status": "DONE"}).status_code, 409)
        needs = [n for n in self.get("/api/state").json()["needs"] if n.get("ref") == "SV-056"]
        self.assertEqual([n["gate"] for n in needs], ["ui"])

    def test_a_merge_without_a_recorded_approval_is_flagged(self):
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        self.step("start", {"branch": "SV-056-x", "worktree": "/srv/w/SV-056"})
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: x"), headRefName="SV-056-x")]
        self.poll()
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 94, "title": "SV-056: x", "url": "u", "mergedAt": "x"}]
        self.poll()
        ev = [e for e in self.get("/api/activity?limit=200").json()["events"] if e["kind"] == "task.pipeline"
              and e["data"].get("kind") == "pipeline.unreviewed_merge"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["severity"], "action")

    def test_a_ticket_in_the_pipeline_by_review_alone_is_guarded_too(self):
        self.ticket("IN_REVIEW")
        self.tickets.link("SV-056", "github", "pr", "JayDalool/SamVisionAI#94",
                          "https://github.com/JayDalool/SamVisionAI/pull/94", "t", "jay")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: x"), headRefOid="a" * 40)]
        self.poll()
        self.step("review", {"verdict": "REQUEST_CHANGES", "head": "a" * 40}, "agent:reviewer")
        for body in ({"status": "READY_TO_MERGE"}, {"status": "DONE"}):
            self.assertEqual(self.patch(body).status_code, 409, body)
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")

    def test_archiving_cannot_hide_an_open_gate(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"labels": ["migration"]}, "jay")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        self.assertEqual(self.patch({"archived": True}).status_code, 409)

    def test_dispatch_never_moves_a_pipeline_ticket_past_start(self):
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "SV-056", "verb": "implement"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.tickets.get("SV-056")["status"], "READY_TO_IMPLEMENT")
        r = self.step("start", {"branch": "SV-056-x", "worktree": "/srv/w/SV-056"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)

    def test_scenario_1_a_flag_cannot_be_dropped_before_its_gate(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"needs_ui_review": True}, "jay")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")              # low risk: auto-accepted
        self.step("start", {"branch": "SV-056-x", "worktree": "/srv/w/SV-056"})
        for body in ({"needs_ui_review": False}, {"flags": []}, {"labels": ["x"]}, {"type": "DOCS"}):
            self.assertEqual(self.patch(body).status_code, 409, body)            # no gate open, still refused
            self.assertEqual(self.patch(body, "jay").status_code, 409, body)     # Jay without unlock too
        self.assertIn("needs_ui_review", self.tickets.get("SV-056")["flags"])
        self.tickets.update("SV-056", {"status": "VERIFYING"}, "system:automation")
        self.assertEqual(self.step("verify", {"result": "pass", "evidence": "ok"}, "agent:verifier").json()["gate"], "ui")
        self.assertEqual(self.patch({"needs_ui_review": False}, "jay", self.unlock()).status_code, 200)  # owner override

    def test_scenario_2_an_approved_plan_cannot_be_swapped_for_another(self):
        self.ticket("INBOX")
        self.tickets.update("SV-056", {"labels": ["security"]}, "jay")
        self.step("plan", {"plan": {"summary": "rate-limit login"}}, "agent:planner")
        dev = self.unlock()
        self.assertEqual(self.step("confirm", {"gate": "plan"}, "jay", dev).json()["status"], "READY_TO_IMPLEMENT")
        self.assertEqual(self.patch({"labels": []}).status_code, 409)               # can't strip the label
        self.tickets.update("SV-056", {"labels": []}, "jay")                          # …and even if it changed anyway
        w = self.step("plan", {"plan": {"summary": "rewrite the login flow"}}, "agent:planner").json()
        self.assertEqual((w["status"], w["gate"], w["planState"]), ("RESEARCHING", "plan", "proposed"))
        needs = [n for n in self.get("/api/state").json()["needs"] if n.get("ref") == "SV-056"]
        self.assertEqual([n["gate"] for n in needs], ["plan"])

    def test_a_pr_opened_before_start_waits_for_start(self):
        self.ticket("INBOX")
        self.step("plan", {"plan": {"summary": "x"}}, "agent:planner")
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: x"), headRefName="SV-056-x")]
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "READY_TO_IMPLEMENT")  # not straight to review
        self.assertEqual(self.step("start", {"branch": "SV-056-x", "worktree": "/srv/w/SV-056"}).json()["status"],
                         "IN_PROGRESS")
        self.poll()
        self.assertEqual(self.tickets.get("SV-056")["status"], "IN_REVIEW")

    def test_unknown_steps_and_bad_bodies_are_refused(self):
        self.ticket("INBOX")
        self.assertEqual(self.step("merge", {}).status_code, 404)
        self.assertEqual(self.step("plan", {"plan": "do it"}).status_code, 400)
        self.assertEqual(self.client.post("/api/tasks/SV-056/work/plan", content="{}",
                                          headers=dict(JSON, **{"x-ccd-actor": "root"})).status_code, 400)


class ExplicitLinks(Automation):
    """CC-071: the lead links a ticket to its PR (repo-native branch, or another allow-listed repo); ccd reads only
    the registry allow list, an explicit link wins over key-led linking, and a merge counts only after the link."""
    BRANCH = "SV-118-advisor-typed-guard"
    REF = "JayDalool/SamVisionAI#249"
    JD = "JayDalool/jay-dev#10"
    HEAD = "a1" * 20

    def setUp(self):
        super().setUp()
        self.key = "SV-087"
        self.pr_reads = []
        self.pr_node = {}                       # "owner/repo#n" -> node the fake github_pr returns
        self.daemon.github_pr_fn = self.fake_pr

    def fake_pr(self, slug, number):
        self.pr_reads.append(f"{slug}#{number}")
        return dict(self.pr_node.get(f"{slug}#{number}") or {"error": "not found"})

    def step(self, op, body, actor="agent:coordinator", key=None):
        h = dict(JSON, **{"x-ccd-actor": actor})
        return self.client.post(f"/api/tasks/{key or self.key}/work/{op}", content=json.dumps(body), headers=h)

    def future(self, days=1):
        import datetime
        return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def planned(self, number, project="samvision", title=None):
        prefix = {"samvision": "SV", "commandcenter": "CC"}[project]
        self.key = f"{prefix}-{number:03d}"
        self.tickets.create(project, title or f"feature {number}", number=number, status="INBOX",
                            description="Comps miss sold homes")
        r = self.step("plan", {"plan": {"summary": "the feature", "tests": ["unit"]}}, "agent:planner")
        self.assertEqual(r.json()["status"], "READY_TO_IMPLEMENT", r.text)
        return self.key

    def open_prs(self, *rows):
        """rows: (number, branch, head, title)."""
        self.gh.data["samvision"]["prs"] = [dict(pr(n, t), headRefName=b, headRefOid=h) for n, b, h, t in rows]
        self.gh.data["samvision"]["merged"] = []
        self.poll()

    def links(self, key):
        return [(l["ref"], l["createdBy"]) for l in self.tickets.get(key)["links"]]

    def test_R1_only_the_lead_or_jay_links_over_http(self):                                    # R1
        self.planned(87)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"))
        for who in ("agent:implementer", "agent:reviewer", "agent:planner"):
            self.assertEqual(self.step("link", {"pr": self.REF}, who).status_code, 403, who)
        self.assertEqual(self.links("SV-087"), [])
        r = self.step("link", {"pr": self.REF}, "agent:coordinator")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.links("SV-087"), [(self.REF, "agent:coordinator")])
        self.assertTrue(any(e["kind"] == "pipeline.linked" for e in self.tickets.get("SV-087")["timeline"]))
        self.planned(88)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"), (250, "x-branch", self.HEAD, "Other"))
        h = dict(JSON)                                                      # no X-CCD-Actor header: Jay
        r = self.client.post("/api/tasks/SV-088/work/link", content=json.dumps({"pr": "JayDalool/SamVisionAI#250"}), headers=h)
        self.assertEqual((r.status_code, self.links("SV-088")), (200, [("JayDalool/SamVisionAI#250", "jay")]), r.text)

    def test_R2_an_agents_links_row_is_not_an_explicit_link(self):                              # R2
        self.planned(87)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"))
        r = self.post("/api/tasks/SV-087/links", {"provider": "github", "kind": "pr", "ref": self.REF},
                      dict(JSON, **{"x-ccd-actor": "agent:implementer"}))
        self.assertEqual(r.status_code, 200, r.text)
        r = self.step("start", {"branch": self.BRANCH, "worktree": "/srv/server/worktrees/sv/SV-087"})
        self.assertEqual(r.status_code, 400, r.text)                        # does not satisfy the native-branch rule
        self.assertEqual(self.tickets.get("SV-087")["status"], "READY_TO_IMPLEMENT")
        # ...does not suppress key-led linking: SV-057 holds the agent row, the PR's title still leads with SV-056
        self.tickets.create("samvision", "feature", number=56, status="IN_PROGRESS")
        self.tickets.create("samvision", "other", number=57, status="IN_PROGRESS")
        self.tickets.link("SV-057", "github", "pr", "JayDalool/SamVisionAI#94", None, "x", "agent:implementer")
        self.open_prs((94, "sv-056-feature", self.HEAD, "SV-056: the feature"))
        self.assertEqual((self.tickets.get("SV-056")["status"], self.tickets.get("SV-057")["status"]),
                         ("IN_REVIEW", "IN_REVIEW"))
        # ...and it is never polled cross-repo
        cc = self.tickets.create("commandcenter", "cc", status="IN_PROGRESS")[0]["key"]
        self.tickets.link(cc, "github", "pr", self.JD, None, "x", "agent:implementer")
        self.pr_node[self.JD] = {"number": 10, "state": "OPEN"}
        self.poll()
        self.assertEqual(self.pr_reads, [])

    def test_R3_and_R9_a_ref_that_fails_the_gate_never_reaches_github(self):                    # R3 / R9 (daemon side)
        cc = self.tickets.create("commandcenter", "cc", status="INBOX")[0]["key"]
        self.step("plan", {"plan": {"summary": "x", "tests": ["u"]}}, "agent:planner", key=cc)
        self.pr_node[self.JD] = {"number": 10, "state": "OPEN", "headRefName": "b", "title": "t"}
        for ref in ("JayDalool/jay-dev#010", "JayDalool/jay-dev#0", "JayDalool/jay-dev#1\n", "JayDalool/jay dev#1",
                    "JayDalool/SamVisionAI#5", "JayDalool/GauzeMate#5", "other/repo#5", "JayDalool/jay-dev/../x#5",
                    "JayDalool/..#5", 7):
            r = self.step("link", {"pr": ref}, key=cc)
            self.assertEqual(r.status_code, 400, (ref, r.text))
        self.assertEqual(self.pr_reads, [])
        r = self.step("link", {"pr": "jaydalool/JAY-DEV#10"}, key=cc)           # any case reaches gh, registry casing
        self.assertEqual((r.status_code, self.pr_reads, self.links(cc)), (200, ["JayDalool/jay-dev#10"],
                                                                         [(self.JD, "agent:coordinator")]), r.text)

    def test_R4_link_refuses_taken_merged_and_unseen_prs(self):                                 # R4
        self.planned(87)
        self.planned(88)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"))
        self.assertEqual(self.step("link", {"pr": "JayDalool/SamVisionAI#251"}, key="SV-087").status_code, 409)   # unseen
        self.assertEqual(self.step("link", {"pr": self.REF}, key="SV-087").status_code, 200)
        r = self.step("link", {"pr": self.REF}, key="SV-088")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("SV-087", r.text)
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 252, "title": "m", "url": "u", "mergedAt": "2026-10-03T00:00:00Z"}]
        self.poll()
        r = self.step("link", {"pr": "JayDalool/SamVisionAI#252"}, key="SV-088")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("merged", r.text)
        self.assertEqual(self.links("SV-088"), [])

    def test_c1_a_native_branch_is_linked_started_polled_and_reviewed(self):                    # c1
        for number, via_pr in ((87, False), (88, True)):
            key = self.key = f"SV-{number:03d}"
            self.tickets.create("samvision", f"feature {number}", number=number, status="INBOX", description="Comps miss")
            self.step("intake", {"size": "standard", "criteria": ["Five comps show"], "priority": "HIGH"}, key=key)
            self.step("plan", {"plan": {"summary": "the feature"}, "session": "inv-1"}, "agent:planner", key=key)
            r = self.step("plan-review", {"verdict": "APPROVE", "note": "ok", "session": "tr-1"}, "agent:tech-reviewer", key=key)
            self.assertEqual(r.json()["status"], "READY_TO_IMPLEMENT", r.text)
            n = 249 + number
            ref, branch, head = f"JayDalool/SamVisionAI#{n}", f"SV-{number + 31}-native", f"{number:02d}" * 20
            self.open_prs((n, branch, head, "A native title"))
            self.assertEqual(self.tickets.get(key)["links"], [], "ccd never guesses the link")
            wt = {"worktree": f"/srv/server/worktrees/sv/{key}"}
            if via_pr:
                r = self.step("start", dict(wt, branch=branch, pr=ref), key=key)
            else:
                self.assertEqual(self.step("start", dict(wt, branch=branch), key=key).status_code, 400)   # link first
                self.assertEqual(self.step("link", {"pr": ref}, key=key).status_code, 200)
                r = self.step("start", dict(wt, branch=branch), key=key)
            self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
            self.poll()
            self.assertEqual(self.tickets.get(key)["status"], "IN_REVIEW")
            r = self.step("user-check", {"result": "pass", "head": head, "note": "tried it", "session": "ur-1",
                                         "criteria": ["c1=pass"]}, "agent:user-reviewer", key=key)
            self.assertEqual(r.status_code, 200, r.text)
            r = self.step("review", {"verdict": "APPROVE", "head": head, "session": "cr-1"}, "agent:reviewer", key=key)
            self.assertEqual((r.json()["status"], r.json()["review"]["pr"]), ("READY_TO_MERGE", ref), r.text)

    def test_R5_and_N1_a_merge_counts_only_after_the_link(self):                                 # R5 / N1
        self.planned(87)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"))
        self.assertEqual(self.step("link", {"pr": self.REF}).status_code, 200)
        self.assertEqual(self.step("start", {"branch": self.BRANCH, "worktree": "/srv/server/worktrees/sv/SV-087"}).status_code, 200)
        self.poll()
        self.assertEqual(self.tickets.get("SV-087")["status"], "IN_REVIEW")
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 249, "title": "x", "url": "u", "mergedAt": "2026-10-03T00:00:00Z"}]
        self.poll()
        self.assertEqual(self.tickets.get("SV-087")["status"], "IN_REVIEW", "merged before the link: never counts")
        self.gh.data["samvision"]["merged"] = [{"number": 249, "title": "x", "url": "u", "mergedAt": self.future(),
                                                "mergeCommit": {"oid": "f" * 40}}]
        self.poll()
        self.assertEqual(self.tickets.get("SV-087")["status"], "VERIFYING")
        self.assertEqual(sum(1 for e in self.tickets.get("SV-087")["timeline"] if e.get("to") == "VERIFYING"), 1)
        # N1: an agent's row for the same ref becomes the lead's, with a fresh created_at
        self.tickets.create("samvision", "late", number=90, status="READY_TO_IMPLEMENT")
        self.open_prs((260, "x-late", self.HEAD, "late"))
        self.tickets.link("SV-090", "github", "pr", "JayDalool/SamVisionAI#260", None, "x", "agent:implementer")
        self.assertEqual(self.tickets.explicit_pr_links(key="SV-090"), [])
        self.assertEqual(self.step("link", {"pr": "JayDalool/SamVisionAI#260"}, key="SV-090").status_code, 200)
        self.assertEqual(self.links("SV-090"), [("JayDalool/SamVisionAI#260", "agent:coordinator")])

    def test_R7_and_N2_an_explicit_link_wins_over_key_led_linking(self):                        # R7 / N2
        self.planned(87)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"))
        self.assertEqual(self.step("link", {"pr": self.REF}).status_code, 200)
        self.step("start", {"branch": self.BRANCH, "worktree": "/srv/server/worktrees/sv/SV-087"})
        self.tickets.create("samvision", "the SV-118 ticket", number=118, status="IN_PROGRESS")
        self.tickets.create("samvision", "agent-linked", number=119, status="IN_PROGRESS")
        self.tickets.link("SV-119", "github", "pr", self.REF, None, "x", "agent:implementer")     # N2
        self.poll()
        self.assertEqual(self.tickets.get("SV-118")["links"], [])
        self.assertEqual((self.tickets.get("SV-118")["status"], self.tickets.get("SV-119")["status"]),
                         ("IN_PROGRESS", "IN_PROGRESS"))
        self.assertEqual(self.tickets.get("SV-087")["status"], "IN_REVIEW")
        self.tickets.update("SV-119", {"status": "IN_REVIEW"})
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [{"number": 249, "title": "x", "url": "u", "mergedAt": self.future()}]
        self.poll()
        self.assertEqual((self.tickets.get("SV-087")["status"], self.tickets.get("SV-119")["status"]),
                         ("VERIFYING", "IN_REVIEW"))
        # no explicit link: the key-led rule still links it
        self.open_prs((300, "SV-120-thing", self.HEAD, "A title"))
        self.tickets.create("samvision", "key led", number=120, status="IN_PROGRESS")
        self.poll()
        self.assertEqual(self.tickets.get("SV-120")["prNumber"], 300)

    def test_c3_key_led_and_explicit_prs_in_one_poll(self):                                       # c3
        self.tickets.create("samvision", "key led", number=56, status="IN_PROGRESS")
        self.planned(87)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"), (94, "sv-056-feature", self.HEAD, "SV-056: the feature"),
                      (95, "x", self.HEAD, "follow-up to SV-056, sv-087fix"))
        self.assertEqual(self.step("link", {"pr": self.REF}).status_code, 200)
        self.step("start", {"branch": self.BRANCH, "worktree": "/srv/server/worktrees/sv/SV-087"})
        self.poll()
        self.assertEqual((self.tickets.get("SV-056")["status"], self.tickets.get("SV-087")["status"]),
                         ("IN_REVIEW", "IN_REVIEW"))
        t = self.tickets.get("SV-056")
        self.assertEqual([l["ref"] for l in t["links"]], ["JayDalool/SamVisionAI#94"])
        self.assertIn("PR #94 title or branch leads with SV-056", [e.get("trigger") for e in t["timeline"]])

    def test_R8_a_pr_in_another_repo_is_not_confused_with_the_same_number_here(self):          # R8 (view)
        cc = self.tickets.create("commandcenter", "cc", status="IN_REVIEW")[0]["key"]
        self.tickets.link(cc, "github", "pr", self.JD, None, "x", "agent:coordinator")
        self.daemon.gh["commandcenter"] = {"data": {"prs": [pr(10, "own #10")], "merged": []}, "asOf": 1, "error": None}
        rows = {r["key"]: r for r in self.get("/api/development").json()["rows"]}
        p = rows[cc]["pr"]
        self.assertEqual((p["url"], p["state"], p["foreign"], p["repo"]),
                         ("https://github.com/JayDalool/jay-dev/pull/10", "UNKNOWN", True, "JayDalool/jay-dev"))

    def test_N4_commits_of_a_foreign_pr_are_not_read_from_this_checkout(self):                  # N4
        from unittest import mock
        cc = self.tickets.create("commandcenter", "cc", status="IN_REVIEW", branch="jay-dev-branch")[0]["key"]
        self.tickets.link(cc, "github", "pr", self.JD, None, "x", "agent:coordinator")
        with mock.patch("ccd.daemon.subprocess.run") as run:
            r = self.daemon.dev_commits(cc)
        run.assert_not_called()
        self.assertEqual((r["commits"], r["branch"]), ([], None))
        self.assertIn("another repository", r["error"])

    def add_cc_project(self):
        self.daemon.cfg["projects"].append({"key": "commandcenter", "name": "Command Center", "path": "/x",
                                            "repo": "JayDalool/CommandCenter", "branch": "main", "model": "opus",
                                            "effort": "", "index": "", "session": "commandcenter",
                                            "ui_tests": "docs/jay/UI_TESTS.md", "actions": "docs/jay/MY_ACTIONS.md",
                                            "links": [], "commands": []})
        self.daemon.gh["commandcenter"] = {"data": None, "asOf": None, "error": "not fetched yet", "lastAttempt": None}
        self.gh.data["commandcenter"] = {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []}

    def test_c5_a_pr_in_another_allow_listed_repo_reaches_review_and_its_merge_moves_on(self):  # c5
        self.add_cc_project()
        cc = self.planned(1, "commandcenter")
        self.pr_node[self.JD] = {"number": 10, "title": "jay-dev change", "state": "OPEN", "isDraft": False,
                                 "headRefName": "feature/jd", "headRefOid": self.HEAD, "reviewDecision": None,
                                 "statusCheckRollup": [{"state": "SUCCESS"}]}
        self.assertEqual(self.step("link", {"pr": self.JD}).status_code, 200)
        r = self.step("start", {"branch": "wrong", "worktree": "/srv/server/worktrees/cc/CC-001"})
        self.assertEqual(r.status_code, 409, r.text)                          # not the PR's head branch
        r = self.step("start", {"branch": "feature/jd", "worktree": "/srv/server/worktrees/cc/CC-001"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
        self.poll()
        self.assertEqual(self.tickets.get(cc)["status"], "IN_REVIEW")
        r = self.step("review", {"verdict": "APPROVE", "head": self.HEAD, "session": "cr-1"}, "agent:reviewer")
        self.assertEqual((r.json()["status"], r.json()["review"]["pr"]), ("READY_TO_MERGE", self.JD), r.text)
        self.pr_node[self.JD] = dict(self.pr_node[self.JD], state="MERGED", mergedAt=self.future(),
                                     mergeCommit={"oid": "e" * 40})
        self.poll()
        self.assertEqual(self.tickets.get(cc)["status"], "VERIFYING")
        self.poll()
        self.assertEqual(sum(1 for e in self.tickets.get(cc)["timeline"] if e.get("to") == "VERIFYING"), 1)

    def test_R9_the_poll_reads_at_most_twenty_linked_prs_and_says_so(self):                      # R9 (cap)
        self.add_cc_project()
        for n in range(1, 23):
            t = self.tickets.create("commandcenter", f"cc {n}", status="IN_PROGRESS")[0]
            self.tickets.link(t["key"], "github", "pr", f"JayDalool/jay-dev#{n}", None, "x", "agent:coordinator")
            self.pr_node[f"JayDalool/jay-dev#{n}"] = {"number": n, "state": "OPEN", "headRefName": "b", "title": "t"}
        self.poll()
        self.assertEqual(len(self.pr_reads), 20)
        self.poll()                                    # the next poll starts with the PRs the cap left out
        self.assertEqual(len(set(self.pr_reads)), 22, "every eligible PR is read within two polls")
        self.assertTrue(any(e["kind"] == "daemon.linked_capped" for e in self.get("/api/activity?limit=200").json()["events"]))

    def iso(self, epoch):
        import datetime
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_N1_promotion_takes_a_fresh_created_at_from_either_source(self):                   # N1 (strong)
        import time
        for number, creator in ((90, "agent:implementer"), (91, "system:automation")):
            ref = f"JayDalool/SamVisionAI#{number + 170}"
            key = f"SV-{number:03d}"
            self.tickets.create("samvision", f"t{number}", number=number, status="IN_REVIEW")
            self.open_prs((number + 170, f"x-{number}", self.HEAD, "no key here"))
            self.tickets.link(key, "github", "pr", ref, None, "x", creator)
            old = time.time() - 3600
            self.tickets.db.execute("UPDATE ticket_links SET created_at=? WHERE provider='github' AND ref=?", (old, ref))
            self.tickets.db.commit()
            self.assertEqual(self.step("link", {"pr": ref}, key=key).status_code, 200)
            [row] = self.tickets.explicit_pr_links(key=key)
            self.assertGreater(row["createdAt"], old + 3000, creator)       # fresh, not the original timestamp
            self.gh.data["samvision"]["prs"] = []
            # a merge between the original row and the promotion must not count...
            self.gh.data["samvision"]["merged"] = [{"number": number + 170, "title": "x", "url": "u",
                                                    "mergedAt": self.iso(old + 1800)}]
            self.poll()
            self.assertEqual(self.tickets.get(key)["status"], "IN_REVIEW", creator)
            # ...one after it does
            self.gh.data["samvision"]["merged"][0]["mergedAt"] = self.future()
            self.poll()
            self.assertEqual(self.tickets.get(key)["status"], "VERIFYING", creator)

    def test_High1_a_plain_link_elsewhere_never_makes_an_owned_pr_eligible(self):             # N2 downstream
        self.planned(87)
        self.open_prs((249, self.BRANCH, self.HEAD, "Typed guard"))
        self.assertEqual(self.step("link", {"pr": self.REF}).status_code, 200)
        self.tickets.create("samvision", "plain", number=119, status="IN_REVIEW")
        self.tickets.link("SV-119", "github", "pr", self.REF, None, "x", "agent:implementer")
        t87, t119 = self.tickets.get("SV-087"), self.tickets.get("SV-119")
        self.assertEqual([p["ref"] for p in self.daemon._open_prs(t87)], [self.REF])
        self.assertEqual((self.daemon._open_prs(t119), self.daemon._linked_prs(t119), self.daemon._pr_state(t119)),
                         ([], [], None))
        # with no explicit owner the legacy same-repo behaviour is unchanged
        self.open_prs((300, "plain-300", self.HEAD, "no key"))
        self.tickets.link("SV-119", "github", "pr", "JayDalool/SamVisionAI#300", None, "x", "agent:implementer")
        self.assertEqual([p["ref"] for p in self.daemon._open_prs(self.tickets.get("SV-119"))],
                         ["JayDalool/SamVisionAI#300"])

    def test_High2_a_failed_refresh_never_leaves_an_old_open_pr_deciding(self):               # High 2
        self.add_cc_project()
        cc = self.planned(1, "commandcenter")
        self.pr_node[self.JD] = {"number": 10, "title": "t", "state": "OPEN", "isDraft": False, "headRefName": "feature/jd",
                                 "headRefOid": self.HEAD, "statusCheckRollup": [{"state": "SUCCESS"}]}
        self.assertEqual(self.step("link", {"pr": self.JD}).status_code, 200)
        good = dict(self.pr_node[self.JD])
        del self.pr_node[self.JD]                                      # GitHub now fails for this PR
        r = self.step("start", {"branch": "feature/jd", "worktree": "/srv/server/worktrees/cc/CC-001"})
        self.assertEqual((r.status_code, self.tickets.get(cc)["status"]), (409, "READY_TO_IMPLEMENT"), r.text)
        self.pr_node[self.JD] = good
        self.assertEqual(self.step("start", {"branch": "feature/jd", "worktree": "/srv/server/worktrees/cc/CC-001"}).status_code, 200)
        self.poll()
        self.assertEqual(len(self.daemon._linked_prs(self.tickets.get(cc))), 1)
        del self.pr_node[self.JD]
        self.poll()                                                    # the refresh fails
        self.assertEqual(self.daemon._linked_prs(self.tickets.get(cc)), [])
        self.pr_node[self.JD] = good
        self.poll()
        self.assertEqual(len(self.daemon._linked_prs(self.tickets.get(cc))), 1)
        self.daemon.gh_linked[self.JD.lower()]["asOf"] -= 100000       # too old to act on
        self.assertEqual(self.daemon._linked_prs(self.tickets.get(cc)), [])

    def test_a_successful_foreign_read_advances_its_ticket_while_the_own_poll_is_failing(self):
        self.add_cc_project()
        cc = self.planned(1, "commandcenter")
        self.pr_node[self.JD] = {"number": 10, "title": "t", "state": "OPEN", "isDraft": False, "headRefName": "feature/jd",
                                 "headRefOid": self.HEAD, "statusCheckRollup": [{"state": "SUCCESS"}]}
        self.step("link", {"pr": self.JD})
        self.step("start", {"branch": "feature/jd", "worktree": "/srv/server/worktrees/cc/CC-001"})
        self.gh.fail = True
        self.poll()
        self.assertEqual(self.tickets.get(cc)["status"], "IN_REVIEW")

    def test_merge_dedup_is_by_the_full_pr_ref(self):
        cc = self.tickets.create("commandcenter", "cc", status="IN_REVIEW")[0]["key"]
        own = "JayDalool/CommandCenter#10"
        self.tickets.link(cc, "github", "pr", own, None, "x", "system:automation")
        self.daemon._automate_merged_pr(own, 10, None, self.future(-1))
        self.assertEqual(self.tickets.get(cc)["status"], "VERIFYING")
        self.tickets.update(cc, {"status": "IN_PROGRESS"}, "jay")
        self.tickets.update(cc, {"status": "IN_REVIEW"}, "jay")
        self.daemon._automate_merged_pr(own, 10, None, self.future(-1))      # replay of the same merge: ignored
        self.assertEqual(self.tickets.get(cc)["status"], "IN_REVIEW")
        self.tickets.link(cc, "github", "pr", self.JD, None, "x", "agent:coordinator")
        self.daemon._automate_merged_pr(self.JD, 10, None, self.future())    # same number, another repo: counts
        self.assertEqual(self.tickets.get(cc)["status"], "VERIFYING")
        self.tickets.update(cc, {"status": "IN_PROGRESS"}, "jay")
        self.tickets.update(cc, {"status": "IN_REVIEW"}, "jay")
        self.daemon._automate_merged_pr(self.JD, 10, None, self.future())    # and its own replay is ignored
        self.assertEqual(self.tickets.get(cc)["status"], "IN_REVIEW")

    def test_c5_standard_cross_repo_ticket_is_user_checked_and_reviewed_on_the_foreign_pr(self):   # c5 (strong)
        self.add_cc_project()
        key = self.key = "CC-001"
        self.tickets.create("commandcenter", "feature", number=1, status="INBOX", description="Needs a check")
        self.step("intake", {"size": "standard", "criteria": ["Five comps show"], "priority": "HIGH"})
        self.step("plan", {"plan": {"summary": "the feature"}, "session": "inv-1"}, "agent:planner")
        r = self.step("plan-review", {"verdict": "APPROVE", "note": "ok", "session": "tr-1"}, "agent:tech-reviewer")
        self.assertEqual(r.json()["status"], "READY_TO_IMPLEMENT", r.text)
        self.pr_node[self.JD] = {"number": 10, "title": "t", "state": "OPEN", "isDraft": False, "headRefName": "feature/jd",
                                 "headRefOid": self.HEAD, "statusCheckRollup": [{"state": "SUCCESS"}]}
        self.assertEqual(self.step("link", {"pr": self.JD}).status_code, 200)
        self.assertEqual(self.step("start", {"branch": "feature/jd", "worktree": "/srv/server/worktrees/cc/CC-001"}).status_code, 200)
        self.poll()
        self.assertEqual(self.tickets.get(key)["status"], "IN_REVIEW")
        r = self.step("user-check", {"result": "pass", "head": self.HEAD, "note": "tried it", "session": "ur-1",
                                     "criteria": ["c1=pass"]}, "agent:user-reviewer")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["userCheck"]["pr"], self.JD)
        r = self.step("review", {"verdict": "APPROVE", "head": self.HEAD, "session": "cr-1"}, "agent:reviewer")
        self.assertEqual((r.json()["status"], r.json()["review"]["pr"]), ("READY_TO_MERGE", self.JD), r.text)
        self.pr_node[self.JD] = dict(self.pr_node[self.JD], state="MERGED", mergedAt=self.future())
        self.poll()
        self.assertEqual(self.tickets.get(key)["status"], "VERIFYING")
