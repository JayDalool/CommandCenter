"""Tickets over HTTP/WS, GitHub automation, dispatch by ticket, workspaces, and the served UI."""
import json
import os
import tempfile

from .helpers import pr
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

    def test_other_projects_keys_are_not_linked(self):
        self.tickets.create("gauzemate", "gm thing")
        self.gh.data["samvision"]["prs"] = [pr(96, "mentions GM-001 in passing")]
        self.poll()
        self.assertEqual(self.tickets.get("GM-001")["links"], [])


class DispatchByTicket(ApiBase):
    def test_dispatch_accepts_an_existing_ticket_and_moves_it(self):
        self.tickets.create("samvision", "plan me", number=56, status="PROPOSED")
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "SV-056", "verb": "plan"})
        self.assertEqual(r.status_code, 200, r.text)
        t = self.tickets.get("SV-056")
        self.assertEqual(t["status"], "RESEARCHING")
        self.assertIn("dispatch", t["timeline"][-1]["trigger"])

    def test_dispatch_refuses_unknown_or_foreign_tickets(self):
        self.tickets.create("gauzemate", "gm")
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "CC-404", "verb": "plan"})
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "GM-001", "verb": "plan"})
        self.assertEqual(r.status_code, 409)


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
        with self.assertRaises(ValueError):
            self.tickets.sync_projects([{"key": "sv2", "name": "x", "prefix": "SV"}])


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
