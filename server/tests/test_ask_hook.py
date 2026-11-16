"""Claude's own question tool (AskUserQuestion) sent to Jay through CommandCenter: scripts/cc-ask-hook, the hook
endpoint, and how a session is matched to a ticket or a lead (ccd/ask_hook.py, Daemon.ask_from_session)."""
import io
import json
import os
import shutil
import tempfile
import unittest

from ccd import ask_hook, daemon as daemon_mod, notify
from ccd import chat as chat_mod

from .test_api import ApiBase, JSON
from .test_notify import FakeSlack

ASK = [{"question": "Which database for the reports?", "header": "Database", "multiSelect": False,
        "options": [{"label": "Postgres", "description": "concurrent users, already deployed"},
                    {"label": "SQLite", "description": "simplest for one user"}]},
       {"question": "Which exports?", "header": "Exports", "multiSelect": True,
        "options": [{"label": "CSV", "description": ""}, {"label": "PDF", "description": ""}]}]
LEAD_SESSION = "ae9345c7-8e20-474f-9d2a-de7c3828a8dc"     # the fixture's SamVision coordinator (wE:p2)


class Convert(unittest.TestCase):
    def test_questions_become_pipeline_questions(self):
        qs = ask_hook.questions_of(ASK)
        self.assertEqual(qs, [
            {"text": "Which database for the reports?",
             "options": ["Postgres: concurrent users, already deployed", "SQLite: simplest for one user"]},
            {"text": "Which exports? (pick one or more)", "options": ["CSV", "PDF"]}])
        self.assertEqual(ask_hook.questions_of([{"question": "Anything else?", "options": []}]),
                         [{"text": "Anything else?"}])
        self.assertEqual(len(ask_hook.questions_of([{"question": "q", "options": [{"label": "x" * 400}] * 2}])[0]
                             ["options"][0]), ask_hook.OPTION_MAX)

    def test_anything_else_is_not_routed(self):
        for bad in (None, [], "a question", [{"question": ""}], [{"question": "q"}] * 5, [{"question": "q",
                                                                                           "options": ["x", "y"]}]):
            self.assertEqual(ask_hook.questions_of(bad), [], repr(bad))

    def test_a_leads_message_numbers_questions_and_options(self):
        text = ask_hook.lead_text(ask_hook.questions_of(ASK))
        self.assertIn("1. Which database for the reports?\n   1) Postgres: concurrent users", text)
        self.assertIn("2. Which exports? (pick one or more)\n   1) CSV\n   2) PDF", text)
        self.assertTrue(text.endswith("Reply with numbered lines (1. …, 2. …): an option's number or your own words."))


class Hook(unittest.TestCase):
    def run_hook(self, event, result=None, raises=False):
        calls = []

        def call(method, path, body, actor):
            calls.append((method, path, body, actor))
            if raises:
                raise FileNotFoundError("no token")
            return result

        out = io.StringIO()
        code = ask_hook.main(stdin=io.StringIO(json.dumps(event) if not isinstance(event, str) else event),
                             stdout=out, call=call)
        self.assertEqual(code, 0)
        return out.getvalue(), calls

    EVENT = {"session_id": "abc-123", "tool_name": "AskUserQuestion", "tool_input": {"questions": ASK}}

    def test_routed_questions_deny_the_prompt_with_where_they_went(self):
        out, calls = self.run_hook(self.EVENT, (0, {"routed": "ticket", "key": "SV-1", "say": "Sent to Jay."}))
        self.assertEqual(calls, [("POST", "/api/hooks/ask", {"sessionId": "abc-123", "questions": ASK},
                                  "agent:ask-hook")])
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Sent to Jay."}})

    def test_claudes_own_prompt_stays_whenever_ccd_did_not_route_them(self):
        for result in ((0, {"routed": None}), (1, {"error": "Command Center is not reachable"}), (0, ["x"])):
            out, _ = self.run_hook(self.EVENT, result)
            self.assertEqual(out, "", result)
        self.assertEqual(self.run_hook(self.EVENT, raises=True)[0], "")
        out, calls = self.run_hook(dict(self.EVENT, tool_name="Bash"))
        self.assertEqual((out, calls), ("", []))
        self.assertEqual(self.run_hook("not json")[0], "")


class Endpoint(ApiBase):
    def equip(self, daemon):
        self.base = tempfile.mkdtemp(prefix="askhook-")
        daemon.chat = chat_mod.Chat(os.path.join(self.base, "chat.db"), os.path.join(self.base, "files"), 1 << 20)
        daemon.notifier = notify.Notifier(daemon, {"notify": {}}, slack=FakeSlack())

    def tearDown(self):
        super().tearDown()
        self.daemon.chat.close()
        shutil.rmtree(self.base)

    def ask(self, session, questions=ASK):
        r = self.post("/api/hooks/ask", {"sessionId": session, "questions": questions})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_a_task_sessions_questions_become_the_tickets(self):
        t, _ = self.tickets.create("samvision", "Reports")
        self.fake.add_agent("wE:p9", "/srv/server/apps/samvisionai", name=t["key"].lower())
        self.settle()
        r = self.ask("s-wE:p9")
        self.assertEqual((r["routed"], r["key"]), ("ticket", t["key"]))
        self.assertIn("End your turn now and wait", r["say"])
        qs = self.daemon.task_work(t["key"])["questions"]
        self.assertEqual([(q["text"], q["kind"], q["options"], q["answer"]) for q in qs], [
            ("Which database for the reports?", "choice",
             ["Postgres: concurrent users, already deployed", "SQLite: simplest for one user"], None),
            ("Which exports? (pick one or more)", "choice", ["CSV", "PDF"], None)])

    def test_a_leads_questions_go_to_its_messages_conversation(self):
        r = self.ask(LEAD_SESSION)
        self.assertEqual((r["routed"], r["conversation"]), ("lead", "samvision"))
        self.assertIn("cc-inbox samvision", r["say"])
        msgs = self.daemon.chat.history("samvision", None, 10)
        self.assertEqual([(m["side"], m["author"]) for m in msgs], [("lead", "agent:lead-samvision")])
        self.assertIn("1. Which database for the reports?", msgs[0]["text"])
        self.assertIn("chat.reply", [e["kind"] for e in self.store.since(0)])        # so it reaches Slack

    def test_jays_question_back_reaches_the_task_session_and_its_reply_is_recorded(self):
        t, _ = self.tickets.create("samvision", "Reports")
        k = t["key"]
        self.fake.add_agent("wE:p9", "/srv/server/apps/samvisionai", name=k.lower())
        self.settle()
        r = self.client.portal.call(lambda: self.daemon.slack_ask_back(k, "Why not both?"))
        self.assertTrue(r["delivered"], r)
        sent = [p for m, p in self.fake.calls if m == "agent.prompt"]
        self.assertEqual(sent[-1]["target"], "wE:p9")
        self.assertEqual(sent[-1]["text"], daemon_mod.ASK_BACK_TEMPLATE.format(key=k, text="Why not both?"))
        lead = dict(JSON, **{"x-ccd-actor": "agent:coordinator"})
        r = self.client.post(f"/api/tasks/{k}/work/reply", content=json.dumps({"text": "Both doubles the tests."}),
                             headers=lead)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["posted"])                                         # Slack is off in this test
        (trigger,) = self.tickets.db.execute("SELECT trigger FROM ticket_events WHERE kind='pipeline.replied'").fetchone()
        self.assertEqual(trigger, "answered Jay: Both doubles the tests.")
        self.assertEqual(self.client.post(f"/api/tasks/{k}/work/reply", content=json.dumps({"text": ""}),
                                          headers=lead).status_code, 400)

    def test_a_question_back_with_no_task_session_says_so_for_the_lead_fallback(self):
        t, _ = self.tickets.create("samvision", "No session")
        r = self.client.portal.call(lambda: self.daemon.slack_ask_back(t["key"], "Why?"))
        self.assertEqual((r["delivered"], r["noSession"]), (False, True))
        self.assertEqual([p for m, p in self.fake.calls if m == "agent.prompt"], [])

    def test_a_question_back_is_never_typed_for_a_client_project(self):
        t, _ = self.tickets.create("gauzemate", "Intake")
        with self.assertRaises(daemon_mod.ActionError) as e:
            self.client.portal.call(lambda: self.daemon.slack_ask_back(t["key"], "Why?"))
        self.assertEqual(e.exception.status, 403)

    def test_any_other_session_keeps_claudes_own_prompt(self):
        self.assertEqual(self.ask("not-a-session")["routed"], None)
        self.fake.add_agent("wE:p8", "/tmp", name="scratch")                          # a Claude that is no ticket's
        self.settle()
        self.assertEqual(self.ask("s-wE:p8")["routed"], None)
        self.assertEqual(self.ask("s-wE:p8", questions=[{"question": ""}])["routed"], None)
        t, _ = self.tickets.create("samvision", "Closed one")
        self.tickets.update(t["key"], {"status": "CANCELLED"}, "jay")
        self.fake.add_agent("wE:p7", "/tmp", name=t["key"].lower())
        self.settle()
        r = self.ask("s-wE:p7")                                                       # a closed ticket takes none
        self.assertEqual(r["routed"], None)
        self.assertIn("open ticket", r["error"])
        self.assertEqual(self.client.post("/api/hooks/ask", content="{}").status_code, 401)


if __name__ == "__main__":
    unittest.main()
