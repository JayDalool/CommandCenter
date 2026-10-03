"""The HTTP/WS surface: what exists, who may call it, what leaves it."""
import contextlib
import json
import re
import time
import unittest

from starlette.testclient import TestClient

from ccd import security
from ccd.api import create_app
from ccd.daemon import DISPATCH_TEMPLATE, Daemon
from ccd.herdr import Herdr
from ccd.config import task_projects
from ccd.store import Store
from ccd.tasks import TaskStore

from .fake_herdr import FakeHerdr
from .helpers import FakeGitHub, cfg, fake_git, fake_host, new_db, wait_sync

PORT = 7777
TOKEN = "t" * 43
HOST = {"host": f"127.0.0.1:{PORT}"}
AUTH = dict(HOST, **{"x-ccd-token": TOKEN})
JSON = dict(AUTH, **{"content-type": "application/json"})

ALLOWED = {
    ("GET", "/api/health"), ("GET", "/api/state"), ("GET", "/api/activity"),
    ("GET", "/api/agents/{agent_id}/tail"), ("WS", "/api/events"),
    ("POST", "/api/action/answer"), ("POST", "/api/action/focus"),
    ("POST", "/api/action/ack"), ("POST", "/api/action/dispatch"),
    # P4B ticket system: product data, no infrastructure reach
    ("GET", "/api/development"),
    ("GET", "/api/tasks"), ("POST", "/api/tasks"), ("GET", "/api/tasks/import-preview"),
    ("GET", "/api/tasks/{key}"), ("PATCH", "/api/tasks/{key}"), ("GET", "/api/tasks/{key}/context"),
    ("POST", "/api/tasks/{key}/comments"), ("POST", "/api/tasks/{key}/relations"),
    ("POST", "/api/tasks/{key}/links"),
}
FORBIDDEN_WORDS = ("merge", "deploy", "prod", "docker", "secret", "config", "rule", "git", "apply", "exec",
                   "shell", "run", "kill", "restart", "delete", "worktree", "settings")


class ApiBase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHerdr().start_in_thread()
        self.gh = FakeGitHub()
        self.store = Store(new_db())
        self.cfg = cfg()
        self.tickets = TaskStore(new_db().replace("ccd.db", "tasks.db"), task_projects(self.cfg))
        self.daemon = Daemon(self.cfg, self.store, Herdr(self.fake.path, timeout=2.0), github_fn=self.gh,
                             host_fn=fake_host, git_fn=fake_git, oom_fn=lambda: 0, tasks=self.tickets)
        daemon = self.daemon

        @contextlib.asynccontextmanager
        async def lifespan(app):
            daemon.start()
            yield
            await daemon.stop()

        guarded, self.app = create_app(daemon, TOKEN, PORT, lifespan=lifespan, ui=getattr(self, "ui", ""))
        self.client = TestClient(guarded, base_url=f"http://127.0.0.1:{PORT}")
        self.client.__enter__()
        wait_sync(lambda: daemon.snap is not None and daemon.herdr_state["connected"]
                  and daemon.git["asOf"] is not None, what="daemon ready")
        self.settle()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.close()
        self.tickets.close()
        self.fake.stop_thread()

    def settle(self):
        before = self.daemon.snap
        self.daemon._dirty.set()
        wait_sync(lambda: self.daemon.snap is not before, what="rederive")

    def get(self, path, **kw):
        return self.client.get(path, headers=kw.pop("headers", AUTH), **kw)

    def post(self, path, body, headers=JSON):
        return self.client.post(path, content=json.dumps(body), headers=headers)


class Surface(ApiBase):
    def test_route_table_is_exactly_the_allowlist(self):
        table = set()
        for r in self.app.state.routes_table:
            methods = getattr(r, "methods", None)
            if methods is None:
                table.add(("WS", r.path))
            else:
                table |= {(m, r.path) for m in methods if m != "HEAD"}
        self.assertEqual(table, ALLOWED)

    def test_no_route_names_a_forbidden_capability(self):
        for _, path in ALLOWED:
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, path.lower(), f"{path} mentions {word}")

    def test_unknown_paths_404_and_wrong_methods_405(self):
        self.assertEqual(self.get("/api/merge").status_code, 404)
        self.assertEqual(self.post("/api/action/merge", {}).status_code, 404)
        self.assertEqual(self.get("/api/action/answer").status_code, 405)
        self.assertEqual(self.post("/api/state", {}).status_code, 405)


class Guarding(ApiBase):
    def test_health_is_open_but_nothing_else_is(self):
        self.assertEqual(self.client.get("/api/health", headers=HOST).status_code, 200)
        for path in ("/api/state", "/api/activity", "/api/agents/wE:p2/tail"):
            self.assertEqual(self.client.get(path, headers=HOST).status_code, 401, path)

    def test_wrong_token_is_refused(self):
        r = self.client.get("/api/state", headers=dict(HOST, **{"x-ccd-token": "nope"}))
        self.assertEqual(r.status_code, 401)

    def test_dns_rebinding_host_is_refused(self):
        r = self.client.get("/api/state", headers=dict(AUTH, host=f"evil.example:{PORT}"))
        self.assertEqual(r.status_code, 403)

    def test_cross_origin_browser_request_is_refused(self):
        r = self.client.get("/api/state", headers=dict(AUTH, origin="https://evil.example"))
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/api/state", headers=dict(AUTH, origin=f"http://127.0.0.1:{PORT}"))
        self.assertEqual(r.status_code, 200)

    def test_actions_need_json_so_a_form_post_cannot_trigger_them(self):
        r = self.client.post("/api/action/focus", content="agentId=wE:p2",
                             headers=dict(AUTH, **{"content-type": "application/x-www-form-urlencoded"}))
        self.assertEqual(r.status_code, 415)
        r = self.client.post("/api/action/focus", content='{"agentId":"wE:p2"}',
                             headers=dict(AUTH, **{"content-type": "text/plain"}))
        self.assertEqual(r.status_code, 415)

    def test_no_cors_headers_are_ever_sent(self):
        r = self.get("/api/state", headers=dict(AUTH, origin=f"http://localhost:{PORT}"))
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in r.headers})
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_websocket_without_token_is_closed(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/api/events", headers=HOST) as ws:
                ws.receive_json()


class Reads(ApiBase):
    def test_state_shape(self):
        st = self.get("/api/state").json()
        for key in ("seq", "latestSeq", "agents", "coordinators", "projects", "alerts", "host", "sources",
                    "needs", "blocked", "stale", "totals", "health"):
            self.assertIn(key, st)
        self.assertEqual({a["id"] for a in st["agents"]}, {"wE:p2", "wE:p4"})
        self.assertEqual(sorted(st["coordinators"]), ["gauzemate", "gyst", "mfe", "samvision"])
        self.assertIsNone(st["agents"][0]["context"], "context meter deferred: rendered as —")

    def test_health(self):
        h = self.client.get("/api/health", headers=HOST).json()
        self.assertTrue(h["ok"])
        self.assertTrue(h["herdr"]["connected"])
        self.assertIn("calls", h)
        self.assertNotIn("token", json.dumps(h).lower())

    def test_activity_lists_events_newest_first(self):
        ev = self.get("/api/activity?limit=5").json()["events"]
        self.assertTrue(ev)
        self.assertEqual([e["seq"] for e in ev], sorted((e["seq"] for e in ev), reverse=True))
        self.assertEqual(self.get("/api/activity?limit=abc").status_code, 400)

    def test_tail_is_redacted_and_bounded(self):
        self.fake.tails["wE:p2"] = "ok\nexport GH_TOKEN=ghp_" + "A" * 36 + "\npassword: hunter2hunter2\ndone"
        r = self.get("/api/agents/wE:p2/tail?lines=999").json()
        self.assertEqual(r["lines"], 200)
        self.assertNotIn("ghp_AAAA", r["text"])
        self.assertNotIn("hunter2", r["text"])
        self.assertGreaterEqual(r["redactions"], 2)
        self.assertEqual(self.get("/api/agents/samvision/tail").json()["agentId"], "wE:p2", "canonical name works")
        self.assertEqual(self.get("/api/agents/wE:p1/tail").status_code, 404, "a shell pane is not an agent")

    def test_tails_are_never_persisted(self):
        self.fake.tails["wE:p2"] = "UNIQUE-TAIL-MARKER-7731"
        self.get("/api/agents/wE:p2/tail")
        rows = self.store.db.execute("SELECT text, data FROM events").fetchall()
        kv = self.store.db.execute("SELECT value FROM kv").fetchall()
        self.assertNotIn("UNIQUE-TAIL-MARKER-7731", json.dumps(rows) + json.dumps(kv))


class WebSocket(ApiBase):
    def test_hello_then_live_event(self):
        with self.client.websocket_connect("/api/events", headers=AUTH) as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["type"], "hello")
            self.fake.run(self.fake.push_status, "wE:p2", "working")
            msg = ws.receive_json()
            while msg["type"] != "event" or msg["event"]["kind"] != "agent.state_changed":
                msg = ws.receive_json()
            self.assertEqual(msg["event"]["agentId"], "wE:p2")

    def test_reconnect_replays_what_was_missed(self):
        with self.client.websocket_connect("/api/events", headers=AUTH) as ws:
            seq = ws.receive_json()["seq"]
        self.fake.run(self.fake.push_status, "wE:p4", "working")      # while disconnected
        wait_sync(lambda: any(e["kind"] == "agent.state_changed" for e in self.store.since(seq)), what="logged")
        t0 = time.monotonic()
        with self.client.websocket_connect(f"/api/events?since={seq}", headers=AUTH) as ws:
            got = []
            msg = ws.receive_json()
            while msg["type"] != "replay_done":
                got.append(msg)
                msg = ws.receive_json()
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertTrue(any(m["event"]["kind"] == "agent.state_changed" and m["event"]["agentId"] == "wE:p4"
                            for m in got))
        self.assertEqual([m["event"]["seq"] for m in got], sorted(m["event"]["seq"] for m in got))

    def test_token_in_query_works_for_browsers(self):
        with self.client.websocket_connect(f"/api/events?token={TOKEN}", headers=HOST) as ws:
            self.assertEqual(ws.receive_json()["type"], "hello")

    def test_since_out_of_range_says_events_lost(self):
        with self.client.websocket_connect("/api/events?since=99999999", headers=AUTH) as ws:
            self.assertEqual(ws.receive_json()["type"], "events_lost")
        with self.client.websocket_connect("/api/events?since=banana", headers=AUTH) as ws:
            self.assertEqual(ws.receive_json()["type"], "events_lost")

    def test_slow_client_is_told_to_resync(self):
        q = self.daemon.subscribe(maxsize=2)
        for i in range(5):
            self.daemon._event("test", "test.flood", str(i))
        self.assertTrue(q.lost)
        self.daemon.unsubscribe(q)


class Actions(ApiBase):
    def test_answer_only_reaches_a_blocked_agent(self):
        r = self.post("/api/action/answer", {"agentId": "wE:p2", "text": "1"})
        self.assertEqual(r.status_code, 409)
        self.fake.set_status("wE:p2", "blocked")
        r = self.post("/api/action/answer", {"agentId": "samvision", "text": "1"})
        self.assertEqual(r.status_code, 200, r.text)
        sent = [(m, p) for m, p in self.fake.calls if m in ("pane.send_text", "pane.send_keys")]
        self.assertEqual(sent, [("pane.send_text", {"pane_id": "wE:p2", "text": "1"}),
                                ("pane.send_keys", {"pane_id": "wE:p2", "keys": ["Enter"]})])

    def test_answer_text_cannot_smuggle_keystrokes(self):
        self.fake.set_status("wE:p2", "blocked")
        for bad in ("", "a\nb", "\x1b[A", "x" * 2001, 5, None):
            r = self.post("/api/action/answer", {"agentId": "wE:p2", "text": bad})
            self.assertEqual(r.status_code, 400, repr(bad))

    def test_answer_is_audited_without_its_text(self):
        self.fake.set_status("wE:p2", "blocked")
        self.post("/api/action/answer", {"agentId": "wE:p2", "text": "my-private-answer"})
        ev = [e for e in self.store.since(0) if e["kind"] == "action.answer"]
        self.assertEqual(len(ev), 1)
        self.assertNotIn("my-private-answer", json.dumps(ev))

    def test_focus(self):
        r = self.post("/api/action/focus", {"agentId": "gauzemate"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(("agent.focus", {"target": "wE:p4"}), self.fake.calls)
        self.assertEqual(self.post("/api/action/focus", {"agentId": "wE:p1"}).status_code, 404)

    def test_ack(self):
        self.fake.run(self.fake.push_status, "wE:p4", "blocked")
        wait_sync(lambda: any(a["id"] == "blocked:wE:p4" for a in self.daemon.alerts), what="alert raised")
        r = self.post("/api/action/ack", {"alertId": "blocked:wE:p4"})
        self.assertEqual(r.status_code, 200, r.text)
        st = self.get("/api/state").json()
        self.assertTrue(next(a for a in st["alerts"] if a["id"] == "blocked:wE:p4")["ack"])
        self.assertEqual(self.post("/api/action/ack", {"alertId": "nope"}).status_code, 404)

    def test_dispatch_sends_the_skill_message_verbatim(self):
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "SV-056", "verb": "plan",
                                               "note": "look at SV-056"})
        self.assertEqual(r.status_code, 200, r.text)
        prompt = [p for m, p in self.fake.calls if m == "agent.prompt"]
        self.assertEqual(len(prompt), 1)
        self.assertEqual(prompt[0]["target"], "samvision")
        text = prompt[0]["text"]
        self.assertIn("Not authorized by this message: merge, deploy, production, --apply, secrets, rule changes.",
                      text)
        self.assertTrue(text.startswith("Dispatch from Jay via command-center: plan SV-056."))
        self.assertEqual(text.count("\n"), DISPATCH_TEMPLATE.count("\n"))

    def test_dispatch_guards(self):
        cases = [
            ({"project": "gyst", "taskId": "#4", "verb": "plan"}, 409),        # no coordinator: lanes
            ({"project": "nope", "taskId": "#4", "verb": "plan"}, 404),
            ({"project": "samvision", "taskId": "SV-1", "verb": "merge"}, 400),
            ({"project": "samvision", "taskId": "SV-1", "verb": "deploy"}, 400),
            ({"project": "samvision", "taskId": "rm -rf /", "verb": "plan"}, 400),
            ({"project": "samvision", "taskId": "SV-1", "verb": "plan", "note": "a\nb"}, 400),
        ]
        for body, code in cases:
            self.assertEqual(self.post("/api/action/dispatch", body).status_code, code, body)
        self.assertEqual([m for m, _ in self.fake.calls if m == "agent.prompt"], [])

    def test_dispatch_never_interrupts_a_busy_coordinator(self):
        self.fake.set_status("wE:p4", "working")
        r = self.post("/api/action/dispatch", {"project": "gauzemate", "taskId": "#24", "verb": "plan"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("working", r.json()["error"])

    def test_dispatch_refuses_a_coordinator_without_its_canonical_name(self):
        del self.fake.agent("wE:p2")["name"]
        r = self.post("/api/action/dispatch", {"project": "samvision", "taskId": "SV-1", "verb": "plan"})
        self.assertEqual(r.status_code, 404)  # nothing answers to "samvision" any more

    def test_herdr_down_actions_fail_closed(self):
        self.fake.stop_thread()
        wait_sync(lambda: not self.daemon.herdr_state["ok"], what="herdr down")
        self.assertEqual(self.post("/api/action/focus", {"agentId": "wE:p2"}).status_code, 503)
        self.fake = FakeHerdr().start_in_thread()  # for tearDown


class NoSecrets(ApiBase):
    # Credential-SHAPED values. The bare word "password" is allowed: checklist
    # lines like "create restic password" are instructions, not secrets.
    PATTERNS = [r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_", r"sk-[A-Za-z0-9_-]{20,}", r"ntfy\.sh/",
                r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s'\",]{6,}",
                r"(?i)bearer\s+[A-Za-z0-9._-]{10,}", r"BEGIN [A-Z ]*PRIVATE KEY", r"postgres(ql)?://[^\s:@]+:[^\s@]+@"]

    def test_no_read_endpoint_leaks_the_token_or_credentials(self):
        blobs = [self.client.get("/api/health", headers=HOST).text, self.get("/api/state").text,
                 self.get("/api/activity?limit=1000").text]
        for blob in blobs:
            self.assertNotIn(TOKEN, blob)
            for pat in self.PATTERNS:
                self.assertIsNone(re.search(pat, blob), pat)
            self.assertEqual(security.redact(blob)[1], 0, "the tail redactor finds nothing to redact either")

    def test_config_contents_beyond_public_fields_never_leave(self):
        self.cfg["ntfy_url"] = "https://ntfy.sh/supersecret-topic-123"
        self.settle()
        st = self.get("/api/state").text
        self.assertNotIn("supersecret-topic-123", st)
        self.assertNotIn("ntfy", st)


class Tokens(unittest.TestCase):
    def test_token_file_is_private_and_stable(self):
        import os
        import stat
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "sub", "ccd.token")
        a = security.load_or_create_token(path)
        b = security.load_or_create_token(path)
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 32)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_redaction_patterns(self):
        text, n = security.redact("token=abcdef123456 and sk-ant-" + "x" * 30 + " and https://ntfy.sh/mytopic123")
        self.assertEqual(n, 3)
        self.assertNotIn("abcdef123456", text)


if __name__ == "__main__":
    unittest.main()


class LogScrub(unittest.TestCase):
    def test_websocket_token_in_a_query_string_never_reaches_the_log(self):
        import logging
        import os
        from ccd import __main__ as main_mod
        main_mod.setup_logging()
        logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" [accepted]', "127.0.0.1:5",
                                                "/api/events?since=3&token=" + TOKEN)
        for h in logging.getLogger().handlers:
            h.flush()
        text = open(os.path.join(os.environ["CCD_STATE_DIR"], "ccd.log")).read()
        self.assertNotIn(TOKEN, text)
        self.assertIn("token=[redacted]", text)
        self.assertIn("since=3", text, "the rest of the line survives")
