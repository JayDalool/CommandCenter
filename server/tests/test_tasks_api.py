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
        self.assertEqual(sv["limits"], {"investigate": {"used": 0, "max": None}, "build": {"used": 0, "max": None}})
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


class PinnedPr(Automation):
    """CC-071: the lead pins a ticket to exactly one PR; only that PR moves, reviews or merges it."""
    SV = "JayDalool/SamVisionAI#249"
    JD = "JayDalool/jay-dev#10"
    JDL = "jaydalool/jay-dev"          # the poll's own spelling: pins are matched in lowercase
    NATIVE = "SV-118-advisor-typed-guard"
    H1 = "a1" * 20
    H2 = "b2" * 20
    key = "SV-087"

    def step(self, op, body, actor="agent:coordinator", key=None):
        h = dict(JSON, **{"x-ccd-actor": actor})
        return self.client.post(f"/api/tasks/{key or self.key}/work/{op}", content=json.dumps(body), headers=h)

    def lane(self, number=87, project="samvision", size="standard"):
        """A planned ticket: READY_TO_IMPLEMENT, with an accepted plan. Later steps act on its key."""
        prefix = {"samvision": "SV", "commandcenter": "CC"}[project]
        self.key = f"{prefix}-{number:03d}"
        self.tickets.create(project, f"feature {number}", number=number, status="INBOX", description="Comps miss sold homes")
        self.step("intake", {"size": size, "criteria": ["Five comps show"], "priority": "HIGH"})
        self.step("role", {"role": "planner", "session": f"inv-{number}"}, "agent:planner")
        self.step("plan", {"plan": {"summary": "the feature"}, "session": f"inv-{number}"}, "agent:planner")
        r = self.step("plan-review", {"verdict": "APPROVE", "note": "ok", "session": f"tr-{number}"}, "agent:tech-reviewer")
        self.assertEqual(r.json()["status"], "READY_TO_IMPLEMENT", r.text)
        return self.key

    def pin(self, ref="", key=None, actor="agent:coordinator"):
        return self.step("link", {"pr": self.SV if ref == "" else ref}, actor, key)

    def started(self, number=87, ref=None, branch=None, project="samvision"):
        self.lane(number, project)
        r = self.pin(ref or (self.SV if project == "samvision" else self.JD))
        self.assertEqual(r.status_code, 200, r.text)
        r = self.step("start", {"branch": branch or self.NATIVE, "worktree": f"/srv/server/worktrees/x/{self.key}"})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "IN_PROGRESS"), r.text)
        return self.key

    def sv_open(self, *rows):
        """rows: (number, branch, head, title); the SamVision poll lists exactly these PRs open."""
        self.gh.data["samvision"]["prs"] = [dict(pr(n, t), headRefName=b, headRefOid=h) for n, b, h, t in rows]
        self.poll()

    def sv_merged(self, number=249, head=None, title="SV-118 advisor", **extra):
        node = {"number": number, "title": title, "url": "u", "mergedAt": "2026-10-03T00:00:00Z",
                "mergeCommit": {"oid": "f" * 40}}
        if head:
            node["headRefOid"] = head
        self.gh.data["samvision"]["prs"] = []
        self.gh.data["samvision"]["merged"] = [dict(node, **extra)]
        self.poll()

    def jd(self, opened=(), merged=()):
        """What jay-dev's poll lists. opened rows: (number, branch, head)."""
        self.gh.data[self.JDL] = {"issues": [], "prs": [dict(pr(n, "jay-dev change"), headRefName=b, headRefOid=h)
                                                        for n, b, h in opened], "merged": list(merged), "closed": [], "ci": []}
        self.poll()

    def cc_polled(self):
        """Make CommandCenter one of the polled projects, as it is in production, so a CC ticket has an own-repo poll."""
        base = next(p for p in self.daemon.cfg["projects"] if p["key"] == "samvision")
        self.daemon.cfg["projects"].append(dict(base, key="commandcenter", name="Command Center", session="commandcenter",
                                                repo="JayDalool/CommandCenter", branch="main"))
        self.daemon.gh["commandcenter"] = {k: (v.copy() if isinstance(v, dict) else v)
                                           for k, v in self.daemon.gh["samvision"].items()}
        self.gh.data["commandcenter"] = {"issues": [], "prs": [], "merged": [], "closed": [], "ci": []}

    def status(self, key=None):
        return self.tickets.get(key or self.key)["status"]

    def events(self, kind, key=None):
        return [json.loads(d or "{}") for (d,) in self.tickets.db.execute(
            "SELECT e.data FROM ticket_events e JOIN tickets t ON t.id=e.ticket_id WHERE t.key=? AND e.kind=?",
            (key or self.key, kind))]

    def work(self, key=None):
        return self.get(f"/api/tasks/{key or self.key}/work").json()

    def user_pass(self, head, key=None):
        return self.step("user-check", {"result": "pass", "head": head, "note": "tried it", "session": "ur-1",
                                        "criteria": ["c1=pass"]}, "agent:user-reviewer", key)

    def approve(self, head, key=None):
        return self.step("review", {"verdict": "APPROVE", "head": head, "session": "cr-1"}, "agent:reviewer", key)

    # P1
    def test_P1_only_the_lead_or_jay_pins_and_a_plain_link_never_does(self):
        self.lane()
        for actor in ("agent:implementer", "agent:reviewer", "agent:planner"):
            self.assertEqual(self.pin(actor=actor).status_code, 403, actor)
        self.assertEqual(self.events("pipeline.linked"), [])
        # a plain links row, by an agent or by Jay, is display only: native start is still refused
        for actor in ("agent:implementer", "jay"):
            r = self.client.post(f"/api/tasks/{self.key}/links", headers=dict(JSON, **{"x-ccd-actor": actor}),
                                 content=json.dumps({"provider": "github", "kind": "pr", "ref": self.SV,
                                                     "url": "https://github.com/JayDalool/SamVisionAI/pull/249"}))
            self.assertIn(r.status_code, (200, 201), r.text)
        r = self.step("start", {"branch": self.NATIVE, "worktree": "/srv/server/worktrees/x/SV-087"})
        self.assertEqual(r.status_code, 400, r.text)
        for actor in ("agent:coordinator", "jay"):
            self.assertEqual(self.pin(actor=actor).status_code, 200, actor)
        self.assertEqual(len(self.events("pipeline.linked")), 1)          # the same ref again is a no-op

    # P2
    def test_P2_link_refuses_what_is_not_a_pinnable_pr(self):
        self.lane()
        bad = ["JayDalool/SamVisionAI#0249", "JayDalool/SamVisionAI#0", "JayDalool/./x#1", "JayDalool/SamVisionAI#1\\n",
               " JayDalool/SamVisionAI#1", "JayDalool/..#1", "JayDalool/SamVisionAI #1", "noslash#1", None, 5,
               "JayDalool/gyst-lifeops#1", "JayDalool/GauzeMate#1", "JayDalool/jay-dev#10", "other/repo#1"]
        for ref in bad:
            r = self.pin(ref)
            self.assertEqual(r.status_code, 400, (ref, r.text))
        self.tickets.create("samvision", "not planned", number=88, status="READY_TO_IMPLEMENT")
        self.assertEqual(self.pin(key="SV-088").status_code, 409)            # not in the pipeline
        self.assertEqual(self.pin("jaydalool/samvisionai#249").status_code, 200)
        self.assertEqual(self.events("pipeline.linked")[0]["pr"], self.SV)       # stored in the registry's casing
        self.tickets.create("gauzemate", "paused", number=1, status="READY_TO_IMPLEMENT")
        r = self.pin("JayDalool/GauzeMate#5", key="GZ-001", actor="jay")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(self.events("pipeline.linked", "GZ-001"), [])
        self.tickets.update(self.key, {"status": "IN_REVIEW"}, "jay")
        self.assertEqual(self.pin("JayDalool/SamVisionAI#250").status_code, 409)   # only before review

    def test_P2_a_plain_row_in_another_case_does_not_break_the_pin_or_double_the_row(self):
        self.lane()
        self.tickets.link(self.key, "github", "pr", "jaydalool/samvisionai#249", None, "x", "agent:implementer")
        self.assertEqual(self.pin().status_code, 200)
        self.assertEqual(len([l for l in self.tickets.get(self.key)["links"] if l["ref"].lower() == self.SV.lower()]), 1)
        self.assertEqual(self.pin("JayDalool/SamVisionAI#250").status_code, 200)   # a re-pin before review

    # P3
    def test_P3_one_owner_and_a_cancelled_owner_gives_the_pr_up(self):
        a = self.started(87)
        self.lane(88)
        b = self.key
        r = self.pin(key=b)
        self.assertEqual(r.status_code, 409, r.text)
        self.tickets.update(a, {"status": "CANCELLED"}, "jay")
        self.assertEqual(self.pin(key=b).status_code, 200)
        self.step("start", {"branch": "SV-118-other-name", "worktree": "/srv/server/worktrees/x/SV-088"}, key=b)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 advisor"))
        self.assertEqual(self.status(b), "IN_REVIEW")
        # the old ticket is reopened: it still holds its pin, but it is inert, and the new owner still moves
        self.tickets.update(a, {"status": "IN_REVIEW"}, "jay")
        r = self.approve(self.H1, key=a)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(self.daemon._ticket_prs(self.tickets.get(a)), [])
        self.assertEqual([p["ref"] for p in self.daemon._ticket_prs(self.tickets.get(b))], [self.SV])

    # P4
    def test_P4_a_native_branch_needs_a_pin_and_a_safe_name(self):
        from ccd.pipeline import native_branch_problem
        self.lane()
        wt = {"worktree": "/srv/server/worktrees/x/SV-087"}
        self.assertEqual(self.step("start", dict(wt, branch=self.NATIVE)).status_code, 400)
        self.pin()
        for bad in ("main", "master", "Main", "HEAD", "refs/heads/x", "origin/x", "SV-118/", "x.lock", "a..b", "-x",
                    "a b", "x\\n", "a/b/c/d"):
            r = self.step("start", dict(wt, branch=bad))
            self.assertEqual(r.status_code, 400, (bad, r.text))
            self.assertEqual(self.status(), "READY_TO_IMPLEMENT")
        self.assertIn("base", native_branch_problem("develop", base="develop"))
        self.assertEqual(self.step("start", dict(wt, branch=self.NATIVE)).json()["status"], "IN_PROGRESS")

    def test_P4_a_key_led_branch_still_starts_without_a_pin(self):
        self.lane()
        r = self.step("start", {"branch": "SV-087-feature", "worktree": "/srv/server/worktrees/x/SV-087"})
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)

    # P5, P6
    def test_P5_an_explicit_pin_wins_over_key_led_linking_and_plain_links(self):
        self.tickets.create("samvision", "the SV-118 ticket", number=118, status="IN_PROGRESS")
        self.started(87)
        self.tickets.create("samvision", "plain", number=56, status="IN_PROGRESS")
        self.tickets.link("SV-056", "github", "pr", self.SV, None, "x", "agent:implementer")
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 advisor"))
        self.assertEqual((self.status("SV-087"), self.status("SV-118"), self.status("SV-056")),
                         ("IN_REVIEW", "IN_PROGRESS", "IN_PROGRESS"))
        self.assertEqual(self.tickets.get("SV-118")["links"], [])
        self.assertEqual(self.daemon._ticket_prs(self.tickets.get("SV-056")), [])     # not offered to review, rework, merge
        self.assertEqual(self.daemon._pr_state(self.tickets.get("SV-056")), None)

    def test_c3_without_a_pin_a_key_led_pr_still_links_and_a_pinned_native_one_moves_its_own_ticket(self):
        self.tickets.create("samvision", "keyled", number=56, status="IN_PROGRESS")
        self.started(57, ref=self.SV)
        self.sv_open((94, "sv-056-feature", "94" * 20, "SV-056: the feature"), (249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual((self.status("SV-056"), self.status("SV-057")), ("IN_REVIEW", "IN_REVIEW"))
        self.assertEqual(self.tickets.get("SV-056")["prNumber"], 94)

    def test_P6_a_pinned_ticket_ignores_a_key_led_pr_of_its_own_key(self):
        self.started(87)
        self.sv_open((300, "SV-087-other", self.H2, "SV-087: another PR"))
        self.assertEqual(self.status(), "IN_PROGRESS")
        self.assertEqual(self.daemon._ticket_prs(self.tickets.get(self.key)), [])
        self.sv_open((300, "SV-087-other", self.H2, "SV-087: another PR"), (249, self.NATIVE, self.H1, "x"))
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertEqual([p["ref"] for p in self.daemon._ticket_prs(self.tickets.get(self.key))], [self.SV])
        self.assertEqual(self.approve(self.H2).status_code, 409)                  # #300's head is not the pin's

    # P7
    def test_P7_review_and_user_check_bind_to_the_pin_and_its_head(self):
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertEqual(self.user_pass(self.H2).status_code, 409)                # not the observed head
        self.assertEqual(self.approve(self.H2).status_code, 409)
        # CC-071 (Codex round 5): the user-check and APPROVE refusals above also have older, independent causes
        # (head guard, missing user check). A changes-requested review at a wrong head has none, so only the pin's
        # own head-equality guard (pipeline._one_pr) refuses it.
        r = self.step("review", {"verdict": "REQUEST_CHANGES", "head": self.H2, "session": "cr-1"}, "agent:reviewer")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual((self.status(), self.work()["review"]["cycles"]), ("IN_REVIEW", 0))
        # bootstrap data from before this process started never counts
        entry = self.daemon.gh["samvision"]
        old = entry["asOf"]
        entry["asOf"] = self.daemon.started - 5
        self.assertEqual(self.user_pass(self.H1).status_code, 409)
        self.assertEqual(self.approve(self.H1).status_code, 409)
        entry["asOf"] = old
        # a failed poll after an open one
        self.gh.fail = True
        self.poll()
        self.assertEqual(self.user_pass(self.H1).status_code, 409)
        self.gh.fail = False
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        r = self.user_pass(self.H1)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.work()["userCheck"]["pr"], self.SV)
        # a user check recorded on another ref at the same head does not carry to the pin
        pl = self.daemon.pipeline
        tid = pl.ts._id_of(self.key)
        uc = dict(self.work()["userCheck"], pr="JayDalool/other#1")
        pl._flow_set(tid, 1.0, user_check=uc)
        self.assertEqual(self.approve(self.H1).status_code, 409)
        pl._flow_set(tid, 2.0, user_check=dict(uc, pr=self.SV))
        self.assertEqual(self.approve(self.H1).json()["status"], "READY_TO_MERGE")
        # the PR closed: nothing to approve against
        self.sv_open()
        self.assertEqual(self.daemon._ticket_prs(self.tickets.get(self.key)), [])

    def test_data_stored_before_this_process_started_moves_and_merges_nothing(self):
        """CC-071 (Codex round 5): the open and the merged automation both refuse pre-start data; asOf is only
        trusted once this process has polled."""
        self.started(87)
        self.daemon.started = self.daemon.started + 3600              # every poll below is "from before the start"
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual(self.status(), "IN_PROGRESS")
        self.daemon.started = self.daemon.started - 3600
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual(self.user_pass(self.H1).status_code, 200)
        self.assertEqual(self.approve(self.H1).json()["status"], "READY_TO_MERGE")
        self.daemon.started = self.daemon.started + 3600
        self.sv_merged(249, head=self.H1)
        self.assertEqual((self.status(), self.events("pipeline.unreviewed_merge"), self.events("pipeline.merged")),
                         ("READY_TO_MERGE", [], []))
        self.daemon.started = self.daemon.started - 3600
        self.sv_merged(249, head=self.H1)
        self.assertEqual(self.status(), "VERIFYING")

    def test_a_jay_dev_poll_stored_before_this_process_started_moves_nothing(self):
        self.lane(7, "commandcenter")
        self.pin(self.JD)
        self.step("start", {"branch": "fix-thing", "worktree": "/srv/server/worktrees/x/CC-007"})
        self.daemon.started = self.daemon.started + 3600
        self.jd(opened=[(10, "fix-thing", self.H1)])
        self.assertEqual(self.status("CC-007"), "IN_PROGRESS")
        self.daemon.started = self.daemon.started - 3600
        self.jd(opened=[(10, "fix-thing", self.H1)])
        self.assertEqual(self.status("CC-007"), "IN_REVIEW")
        self.assertEqual(self.user_pass(self.H1, "CC-007").status_code, 200)
        self.assertEqual(self.approve(self.H1, "CC-007").json()["status"], "READY_TO_MERGE")
        self.daemon.started = self.daemon.started + 3600
        node = {"number": 10, "title": "x", "url": "u", "mergedAt": "x", "headRefOid": self.H1,
                "mergeCommit": {"oid": "e" * 40}}
        self.jd(merged=[node])
        self.assertEqual((self.status("CC-007"), self.events("pipeline.merged", "CC-007")), ("READY_TO_MERGE", []))

    def test_a_poll_node_without_a_head_does_not_move_a_pinned_ticket(self):
        """CC-071 (Codex round 5): "" is not an observed head, and new_head("") is true."""
        self.started(87)
        node = dict(pr(249, "SV-118 x"), headRefName=self.NATIVE)
        del node["headRefOid"]
        self.gh.data["samvision"]["prs"] = [node]
        self.poll()
        self.assertEqual(self.status(), "IN_PROGRESS")
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual(self.status(), "IN_REVIEW")
        self.lane(7, "commandcenter")
        self.pin(self.JD)
        self.step("start", {"branch": "fix-thing", "worktree": "/srv/server/worktrees/x/CC-007"})
        self.jd(opened=[(10, "fix-thing", self.H1)])
        self.gh.data[self.JDL]["prs"][0].pop("headRefOid")
        self.tickets.update("CC-007", {"status": "IN_PROGRESS"}, "jay")
        self.poll()
        self.assertEqual(self.status("CC-007"), "IN_PROGRESS")

    def test_development_shows_the_pin_when_its_display_link_is_gone(self):
        """CC-071 (Codex round 5): the pin is durable, its plain link row is not; the row must not fall back to an
        unrelated link's PR."""
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"), (10, "other", self.H2, "SV-087 look-alike"))
        self.tickets.link(self.key, "github", "pr", "JayDalool/SamVisionAI#10", None, "other", "agent:implementer")
        self.tickets.link(self.key, "github", "pr", self.SV, None, None, "jay", remove=True)
        self.assertEqual(self.daemon.pipeline.pin_of(self.key), self.SV)
        row = next(r for r in self.daemon.development()["rows"] if r["key"] == self.key)
        self.assertEqual((row["pr"]["number"], row["pr"]["url"]), (249, "https://github.com/JayDalool/SamVisionAI/pull/249"))
        self.assertEqual(row["pr"]["state"], "OPEN")

    # P8
    def test_P8_a_merge_counts_only_for_the_pin_at_the_reviewed_head(self):
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual(self.user_pass(self.H1).status_code, 200)
        self.assertEqual(self.approve(self.H1).json()["status"], "READY_TO_MERGE")
        self.sv_merged(249, head=self.H2)                      # merged at another head: not what was reviewed
        self.sv_merged(249, head=self.H2)
        self.assertEqual(self.status(), "READY_TO_MERGE")
        self.assertEqual(len(self.events("pipeline.unreviewed_merge")), 1)
        self.sv_merged(249, head=self.H1)
        self.assertEqual(self.status(), "VERIFYING")
        w = self.work()
        self.assertEqual((w["merge"]["pr"], w["merge"]["sha"]), (self.SV, "f" * 40))
        self.assertEqual([e["pr"] for e in self.events("pipeline.merged")], [self.SV])
        # replay after a hand reopen does not fire again
        self.tickets.update(self.key, {"status": "IN_REVIEW"}, "jay")
        self.sv_merged(249, head=self.H1)
        self.assertEqual(len(self.events("pipeline.merged")), 1)
        self.assertEqual(self.status(), "IN_REVIEW")

    def test_P8_a_merge_before_any_review_does_not_move_the_ticket_and_notes_once(self):
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        for _ in range(2):
            self.sv_merged(249, head=self.H1)
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertEqual(len(self.events("pipeline.unreviewed_merge")), 1)

    def test_a_merged_node_without_its_head_neither_moves_nor_notes_until_it_has_one(self):
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.user_pass(self.H1)
        self.approve(self.H1)
        self.sv_merged(249)                                     # data stored before headRefOid was fetched
        self.assertEqual((self.status(), self.events("pipeline.unreviewed_merge")), ("READY_TO_MERGE", []))
        self.sv_merged(249, head=self.H1)
        self.assertEqual(self.status(), "VERIFYING")

    def test_a_plain_linked_commandcenter_merge_leaves_the_jay_dev_pinned_ticket_alone(self):
        """CC-071 P8 (Codex round 5): CommandCenter#10 is not jay-dev#10, even when plain-linked to the ticket."""
        self.cc_polled()
        self.lane(7, "commandcenter")
        self.pin(self.JD)
        self.step("start", {"branch": "fix-thing", "worktree": "/srv/server/worktrees/x/CC-007"})
        self.tickets.link("CC-007", "github", "pr", "JayDalool/CommandCenter#10", None, "plain", "agent:implementer")
        self.jd(opened=[(10, "fix-thing", self.H1)])
        self.assertEqual(self.user_pass(self.H1, "CC-007").status_code, 200)
        self.assertEqual(self.approve(self.H1, "CC-007").json()["status"], "READY_TO_MERGE")

        def cc_merged():
            self.gh.data["commandcenter"]["merged"] = [{"number": 10, "title": "CC-007 look-alike", "url": "u",
                                                        "mergedAt": "x", "headRefOid": self.H1,
                                                        "mergeCommit": {"oid": "c" * 40}}]
            self.poll()
        cc_merged()
        self.assertEqual(self.status("CC-007"), "READY_TO_MERGE")
        self.assertEqual((self.events("pipeline.merged", "CC-007"), self.work("CC-007")["merge"]), ([], None))
        self.jd(merged=[{"number": 10, "title": "x", "url": "u", "mergedAt": "x", "headRefOid": self.H1,
                         "mergeCommit": {"oid": "e" * 40}}])
        self.assertEqual(self.status("CC-007"), "VERIFYING")
        cc_merged()                                                       # and again once VERIFYING
        w = self.work("CC-007")
        self.assertEqual((w["merge"]["pr"], w["merge"]["sha"]), (self.JD, "e" * 40))
        self.assertEqual(len(self.events("pipeline.merged", "CC-007")), 1)

    # re-pin
    def test_a_repin_drops_the_old_pr_and_an_old_approval_does_not_carry(self):
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"), (250, "SV-119-next", self.H1, "SV-119 y"))
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertEqual(self.user_pass(self.H1).status_code, 200)
        self.assertEqual(self.approve(self.H1).json()["status"], "READY_TO_MERGE")      # both on #249
        self.assertEqual(self.step("rework", {"reason": "other PR"}, "jay").json()["status"], "IN_PROGRESS")
        self.assertEqual(self.pin("JayDalool/SamVisionAI#250").status_code, 200)
        self.assertEqual([p["ref"] for p in self.daemon._ticket_prs(self.tickets.get(self.key))],
                         ["JayDalool/SamVisionAI#250"])
        self.lane(88)
        self.assertEqual(self.pin(self.SV, key="SV-088").status_code, 200)       # #249 is free for another ticket
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"), (250, "SV-119-next", self.H1, "SV-119 y"))
        self.assertEqual(self.status("SV-087"), "IN_REVIEW")
        # #250 has the very head #249 was approved at: neither the approval nor the user check carries over
        self.assertEqual(self.approve(self.H1, "SV-087").status_code, 409)
        self.assertEqual(self.status("SV-087"), "IN_REVIEW")
        self.assertEqual(self.user_pass(self.H1, "SV-087").status_code, 200)
        self.assertEqual(self.work("SV-087")["userCheck"]["pr"], "JayDalool/SamVisionAI#250")
        self.assertEqual(self.approve(self.H1, "SV-087").json()["status"], "READY_TO_MERGE")

    def test_a_reworked_pinned_ticket_returns_to_review_only_on_its_repinned_pr(self):
        self.started(87)
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.user_pass(self.H1)
        self.approve(self.H1)
        self.sv_merged(249, head=self.H1)
        self.assertEqual(self.status(), "VERIFYING")
        r = self.step("rework", {"reason": "follow-up"}, "jay")
        self.assertEqual(r.json()["status"], "IN_PROGRESS", r.text)
        self.gh.data["samvision"]["merged"] = []
        self.sv_open((300, "SV-087-follow-up", self.H2, "SV-087: follow-up"))     # key-led: ignored
        self.assertEqual(self.status(), "IN_PROGRESS")
        self.assertEqual(self.pin("JayDalool/SamVisionAI#300").status_code, 200)
        self.sv_open((300, "SV-087-follow-up", self.H2, "SV-087: follow-up"))
        self.assertEqual(self.status(), "IN_REVIEW")

    def test_the_pin_matches_the_polled_slug_in_any_case(self):
        self.started(87)
        self.gh.data["samvision"]["prs"] = [dict(pr(249, "SV-118 x"), headRefName=self.NATIVE, headRefOid=self.H1)]
        self.daemon.cfg["projects"][0]["repo"] = "jaydalool/samvisionai"
        self.poll()
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertEqual([p["ref"] for p in self.daemon._ticket_prs(self.tickets.get(self.key))], [self.SV])

    # P9, c5
    def test_c5_a_ticket_pinned_to_a_jay_dev_pr_is_reviewed_there_and_its_merge_moves_it_on(self):
        polled = []
        inner = self.daemon.github_fn

        def spy(project):
            polled.append(project["key"])
            return inner(project)
        self.daemon.github_fn = spy
        self.lane(7, "commandcenter")
        self.poll()
        self.assertNotIn(self.JDL, polled)                                       # polled only while a ticket pins it
        self.assertEqual(self.pin(self.JD).status_code, 200)
        self.step("start", {"branch": "fix-thing", "worktree": "/srv/server/worktrees/x/CC-007"})
        self.jd(opened=[(10, "fix-thing", self.H1)])
        self.assertIn(self.JDL, polled)
        self.assertEqual(self.status(), "IN_REVIEW")
        self.assertEqual(set(self.daemon.health()["gh"]["projects"]), {p["key"] for p in self.cfg["projects"]})
        # jay-dev is not a project: it must not appear in the polled snapshot either
        self.assertEqual(set(self.daemon.gh), {p["key"] for p in self.cfg["projects"]})
        r = self.user_pass(self.H1)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.work()["userCheck"]["pr"], self.JD)
        self.assertEqual(self.approve(self.H1).json()["status"], "READY_TO_MERGE")
        self.assertEqual(self.work()["review"]["pr"], self.JD)
        row = next(r for r in self.daemon.development()["rows"] if r["key"] == self.key)
        self.assertEqual(row["pr"]["url"], "https://github.com/JayDalool/jay-dev/pull/10")
        self.assertEqual(row["pr"]["state"], "OPEN")
        ready, skipped = self.daemon.merge_batch("commandcenter")
        self.assertEqual(ready, [])
        self.assertIn("another repository", skipped[0]["reason"])
        self.jd(merged=[{"number": 10, "title": "jay-dev change", "url": "u", "mergedAt": "x", "headRefOid": self.H1,
                         "mergeCommit": {"oid": "e" * 40}}])
        self.assertEqual(self.status(), "VERIFYING")
        self.assertEqual(self.work()["merge"]["pr"], self.JD)
        kinds = [e["data"].get("kind") for e in self.get("/api/activity?limit=200").json()["events"] if e["kind"] == "task.pipeline"]
        self.assertIn("pipeline.merged", kinds)                                  # announced like any merge

    def test_P9_a_failed_repo_poll_stops_only_itself(self):
        self.cc_polled()
        self.started(87)
        self.lane(7, "commandcenter")
        self.pin(self.JD)
        self.step("start", {"branch": "fix-thing", "worktree": "/srv/server/worktrees/x/CC-007"})
        inner = self.daemon.github_fn
        broken = {"key": self.JDL}

        def flaky(project):
            if project["key"] == broken["key"]:
                e = {"error": "gh failed"}
                return {k: e for k in ("issues", "prs", "merged", "closed", "ci")}
            return inner(project)
        self.daemon.github_fn = flaky
        self.gh.data[self.JDL] = {"issues": [], "prs": [dict(pr(10, "x"), headRefName="fix-thing", headRefOid=self.H1)],
                                  "merged": [], "closed": [], "ci": []}
        self.key = "SV-087"
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual((self.status("SV-087"), self.status("CC-007")), ("IN_REVIEW", "IN_PROGRESS"))
        broken["key"] = "commandcenter"                                          # the pinned ticket's own repo fails
        self.poll()
        self.assertEqual(self.status("CC-007"), "IN_REVIEW")                     # jay-dev still moves it

    def test_a_plain_samvision_link_on_a_cc_ticket_does_not_move_it(self):
        self.tickets.create("commandcenter", "cc", number=9, status="IN_PROGRESS")
        self.tickets.link("CC-009", "github", "pr", self.SV, None, "x", "agent:implementer")
        self.sv_open((249, self.NATIVE, self.H1, "SV-118 x"))
        self.assertEqual(self.status("CC-009"), "IN_PROGRESS")
