"""Slack and ntfy (ccd/notify.py): off by default, quiet hours, client redaction, Jay-only replies, and the fixed
limit on what a Slack reply may approve."""
import asyncio
import datetime
import json
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from ccd import notify, security
from ccd.daemon import ActionError, Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg

JAY = "U0JAY0001"
TZ = ZoneInfo("America/Winnipeg")


def at(hh, mm=0, day=12):
    return datetime.datetime(2026, 11, day, hh, mm, tzinfo=TZ).timestamp()


class FakeSlack:
    def __init__(self):
        self.posts = []
        self.n = 0

    def post(self, channel, text, thread_ts=None):
        self.n += 1
        self.posts.append({"channel": channel, "text": text, "thread": thread_ts, "ts": f"{self.n}.0"})
        return {"ok": True, "ts": f"{self.n}.0"}

    def channels(self):
        return {"cto": "CCTO", "commandcenter": "CCC", "samvision": "CSV", "gyst": "CGY", "mfe": "CMF"}

    def dm(self, user):
        return "DJAY"

    def socket_url(self):
        return "wss://example.invalid/socket"


class FakeDaemon:
    """Just what the notifier calls."""

    def __init__(self, store):
        self.store = store
        self.events = []
        self.needs_list = []
        self.blocked = []
        self.questions = {}
        self.answered = []
        self.confirmed = []
        self.delivered = []
        self._stopping = False
        self.tasks = None

    def state(self):
        return {"needs": list(self.needs_list), "blocked": list(self.blocked), "projects": []}

    def _event(self, source, kind, text="", **kw):
        self.events.append((kind, text, kw))

    def _projects(self):
        return [{"key": k} for k in ("commandcenter", "samvision", "gyst", "mfe", "gauzemate")]

    def usage_state(self):
        return {"available": True, "budgets": [{"project": "samvision", "monthlyUsd": 200, "spentUsd": 41.2}],
                "byProject": [{"key": "gyst", "costUsd": 3.0}]}

    def task_work(self, key):
        return {"questions": self.questions.get(key, [])}

    async def task_answers(self, key, body, actor="jay", developer=False, via=None):
        self.answered.append((key, body, actor, developer, via))
        done = {a["id"] for a in body["answers"]}
        for q in self.questions.get(key, []):
            if q["id"] in done:
                q["answer"] = "x"
        return {"delivered": True}

    async def slack_confirm(self, key, gate):
        self.confirmed.append((key, gate))
        return {"delivered": True}

    async def deliver_to_lead(self, conversation, text, *, via="slack", ref=None, author="jay"):
        self.delivered.append((conversation, text, via, ref, author))
        return {"ok": True, "message": {"id": 7}, "delivery": "nudged"}


def make(clock=None, settings=None, conf=None, ntfy_url="https://ntfy.sh/topic-abcdef"):
    store = Store(os.path.join(tempfile.mkdtemp(), "ccd.db"))
    d = FakeDaemon(store)
    slack = FakeSlack()
    pushes = []
    c = {"ntfy_url": ntfy_url, "notify": {"slack": dict({"jay_member_id": JAY}, **(conf or {}))}}
    n = notify.Notifier(d, c, slack=slack, ntfy=lambda url, title, link=None: pushes.append((url, title, link)),
                        clock=clock or (lambda: at(12)), env_path=os.path.join(tempfile.mkdtemp(), "none.env"))
    n.daily["summary"] = notify.local_day(n.settings, n.clock())   # summaries have their own tests
    if settings is not None:
        n.update_settings(settings)
    return n, d, slack, pushes


def run(coro):
    return asyncio.run(coro)


def need(ref="SV-1", kind="gate", gate="merge", project="samvision", text="Ready to merge: Valuation table"):
    return {"project": project, "ref": ref, "kind": kind, "gate": gate, "text": text}


class Settings(unittest.TestCase):
    def test_everything_is_off_until_jay_switches_it_on(self):
        n, d, slack, pushes = make()
        self.assertEqual((n.settings["slack"], n.settings["ntfy"]), (False, False))
        d.needs_list = [need()]
        run(n.tick())
        d.needs_list = [need(), need("SV-2")]
        run(n.tick())
        run(n.summaries(force=True))
        self.assertEqual((slack.posts, pushes), ([], []))

    def test_settings_are_validated_and_survive_a_restart(self):
        n, d, _, _ = make()
        for bad in ({"slack": "yes"}, {"quietStart": "25:00"}, {"timezone": "Mars/Base"}, {"replyScope": "all"},
                    {"token": "x"}):
            with self.assertRaises(ValueError):
                n.update_settings(bad)
        n.update_settings({"slack": True, "quietStart": "23:30", "quietEnd": "06:15"})
        again = notify.Notifier(d, {"notify": {}}, slack=FakeSlack())
        self.assertEqual((again.settings["slack"], again.settings["quietStart"], again.settings["quietEnd"]),
                         (True, "23:30", "06:15"))

    def test_quiet_hours_cross_midnight(self):
        s = dict(notify.SETTINGS_DEFAULTS)
        self.assertTrue(notify.in_quiet(s, at(22, 0)))
        self.assertTrue(notify.in_quiet(s, at(3, 0)))
        self.assertFalse(notify.in_quiet(s, at(7, 0)))
        self.assertFalse(notify.in_quiet(s, at(21, 59)))
        self.assertFalse(notify.in_quiet(dict(s, quietStart="07:00", quietEnd="07:00"), at(3, 0)))

    def test_public_state_never_carries_a_token_or_the_ntfy_url(self):
        n, _, _, _ = make()
        body = json.dumps(n.public())
        self.assertNotIn("ntfy.sh", body)
        self.assertNotIn("topic-abcdef", body)
        self.assertTrue(n.public()["configured"]["ntfy"])

    def test_a_test_reports_each_channel_and_clears_an_old_error(self):
        n, _, slack, pushes = make(settings={"slack": True, "ntfy": True})
        n.status["lastError"] = "slack #gyst: the bot is not in #gyst"
        r = run(n.send_test())
        self.assertEqual((r["slack"], r["ntfy"], r["status"]["lastError"]), (True, True, None))
        self.assertEqual((len(slack.posts), len(pushes)), (1, 1))
        n.update_settings({"ntfy": False})
        n._ntfy = None
        r = run(n.send_test())
        self.assertEqual((r["slack"], r["ntfy"]), (True, False))

    def test_a_failed_push_is_reported_as_failed(self):
        n, _, _, _ = make(settings={"ntfy": True})

        def boom(*a, **k):
            raise OSError("down")
        n._ntfy = boom
        r = run(n.send_test())
        self.assertEqual((r["slack"], r["ntfy"]), (False, False))
        self.assertIn("ntfy", r["status"]["lastError"])

    def test_slack_env_must_be_owner_only(self):
        p = os.path.join(tempfile.mkdtemp(), "slack.env")
        with open(p, "w") as f:
            f.write("SLACK_BOT_TOKEN=xoxb-1111111111-abcdef\nSLACK_APP_TOKEN=xapp-1-A111-222-abcdef\n")
        os.chmod(p, 0o644)
        with self.assertRaises(notify.SlackError):
            notify.read_env(p)
        os.chmod(p, 0o600)
        self.assertEqual(notify.read_env(p)["SLACK_APP_TOKEN"], "xapp-1-A111-222-abcdef")

    def test_slack_env_may_not_be_a_link(self):
        d = tempfile.mkdtemp()
        real = os.path.join(d, "real.env")
        with open(real, "w") as f:
            f.write("SLACK_BOT_TOKEN=xoxb-1\n")
        os.chmod(real, 0o600)
        link = os.path.join(d, "slack.env")
        os.symlink(real, link)
        with self.assertRaises(notify.SlackError):
            notify.read_env(link)

    def test_slack_tokens_are_redacted(self):
        text, n = security.redact("bot xoxb-1111111111-abcdef app xapp-1-A111-222-abcdef")
        self.assertEqual(n, 2)
        self.assertNotIn("xapp-1", text)


class Needs(unittest.TestCase):
    def on(self, **kw):
        return make(settings={"slack": True, "ntfy": True}, **kw)

    def test_first_tick_is_a_baseline_then_each_new_item_is_one_dm_and_one_push(self):
        n, d, slack, pushes = self.on()
        d.needs_list = [need("SV-1")]
        run(n.tick())
        self.assertEqual(slack.posts, [])               # what already waited is in the morning summary
        d.needs_list = [need("SV-1"), need("SV-2", "questions", None, text="Claude needs 1 answer: Comps")]
        d.questions["SV-2"] = [{"id": 5, "text": "Use last year's comps?", "kind": "yesno", "answer": None}]
        run(n.tick())
        run(n.tick())                                   # no repeat
        self.assertEqual(len(slack.posts), 1)
        dm = slack.posts[0]
        self.assertEqual(dm["channel"], "DJAY")
        self.assertIn("Use last year's comps?", dm["text"])
        self.assertIn("http://localhost:7777/#/tasks/SV-2", dm["text"])
        self.assertEqual(pushes, [("https://ntfy.sh/topic-abcdef", "SamVision: Questions · SV-2",
                                   "http://localhost:7777/#/tasks/SV-2")])

    def test_client_project_carries_only_ids_and_a_risk_line(self):
        n, d, slack, pushes = self.on()
        run(n.tick())
        d.needs_list = [need("GM-4", "questions", None, "gauzemate", "Claude needs 2 answers: Patient intake form")]
        d.questions["GM-4"] = [{"id": 1, "text": "Store the clinic's patient IDs?", "kind": "text", "answer": None}]
        run(n.tick())
        text = slack.posts[0]["text"]
        self.assertIn("GM-4", text)
        self.assertIn("Risk:", text)
        self.assertNotIn("Patient", text)
        self.assertNotIn("clinic", text)
        self.assertEqual(pushes[0][1], "GauzeMate: GM-4 needs you")

    def test_quiet_hours_hold_the_dm_and_push_until_morning(self):
        now = [at(23)]
        n, d, slack, pushes = make(clock=lambda: now[0], settings={"slack": True, "ntfy": True})
        run(n.tick())
        d.needs_list = [need("SV-9")]
        run(n.tick())
        self.assertEqual((slack.posts, pushes), ([], []))
        now[0] = at(7, 1, day=13)
        n.daily["summary"] = "2026-11-13"               # keep the summary out of this test
        run(n.check_needs())
        self.assertIn("quiet hours", slack.posts[0]["text"])
        self.assertIn("SV-9", slack.posts[1]["text"])
        self.assertEqual(len(pushes), 1)

    def test_an_item_resolved_overnight_is_not_sent_in_the_morning(self):
        now = [at(23)]
        n, d, slack, _ = make(clock=lambda: now[0], settings={"slack": True})
        run(n.tick())
        d.needs_list = [need("SV-9")]
        run(n.check_needs())
        d.needs_list = []
        now[0] = at(8, day=13)
        run(n.check_needs())
        self.assertEqual(slack.posts, [])


class Summaries(unittest.TestCase):
    def test_owner_summary_in_cto_and_technical_summary_per_project_once_a_day(self):
        now = [at(7, 5)]
        n, d, slack, _ = make(clock=lambda: now[0], settings={"slack": True})
        n.daily = {}
        d.needs_list = [need("SV-1"), need("GM-2", project="gauzemate")]
        run(n.summaries())
        run(n.summaries())                              # once a day
        chans = [p["channel"] for p in slack.posts]
        self.assertEqual(chans, ["CCTO", "CCC", "CSV", "CGY", "CMF"])
        owner = slack.posts[0]["text"]
        self.assertIn("SamVision*: 0 shipped, 0 deployed, 1 waiting on you, $41 of $200 this month", owner)
        self.assertIn("client: details in CommandCenter", owner)
        self.assertIn("2 items wait on you", owner)
        self.assertIn("Waiting on Jay: 1 (SV-1)", slack.posts[2]["text"])
        now[0] = at(6, 59, day=13)
        run(n.summaries())
        self.assertEqual(len(slack.posts), 5)


class ReplyBase(unittest.TestCase):
    def setUp(self):
        self.n, self.d, self.slack, _ = make(settings={"slack": True})
        run(self.n.tick())

    def send(self, need_item, questions=None):
        if questions is not None:
            self.d.questions[need_item["ref"]] = questions
        self.d.needs_list = self.d.needs_list + [need_item]
        run(self.n.tick())
        return self.slack.posts[-1]["ts"]

    def reply(self, text, thread=None, user=JAY, channel="DJAY", **extra):
        self.n_replies = getattr(self, "n_replies", 0) + 1
        ev = dict({"type": "message", "user": user, "text": text, "channel": channel, "ts": f"99.{self.n_replies}"},
                  **extra)
        if thread:
            ev["thread_ts"] = thread
        return run(self.n.on_slack({"event": ev}))



class Replies(ReplyBase):
    def test_only_jays_own_messages_are_read(self):
        ts = self.send(need("SV-3", "questions", None), [{"id": 1, "text": "A or B?", "kind": "text", "answer": None}])
        self.assertIsNone(self.reply("A", ts, user="U0SOMEONE"))
        self.assertIsNone(self.reply("A", ts, subtype="message_changed"))
        self.assertIsNone(self.reply("A", ts, bot_id="B1"))
        self.assertEqual(self.d.answered, [])
        self.n.conf["jay_member_id"] = ""
        self.assertIsNone(self.reply("A", ts))          # no member ID configured: nobody is read

    def test_a_reply_answers_one_question(self):
        ts = self.send(need("SV-3", "questions", None), [{"id": 11, "text": "A or B?", "kind": "text", "answer": None}])
        r = self.reply("B, keep it simple", ts)
        self.assertEqual(r["did"], "answered")
        self.assertEqual(self.d.answered, [("SV-3", {"answers": [{"id": 11, "answer": "B, keep it simple"}]}, "jay", True, "slack")])
        self.assertEqual(self.slack.posts[-1]["thread"], ts)

    def test_several_questions_need_numbered_answers(self):
        qs = [{"id": 1, "text": "Mobile too?", "kind": "yesno", "answer": None},
              {"id": 2, "text": "Which colour?", "kind": "text", "answer": None}]
        ts = self.send(need("SV-4", "questions", None), qs)
        self.assertEqual(self.reply("yes and blue", ts)["did"], "answer_incomplete")
        self.assertEqual(self.reply("1. maybe\n2. blue", ts)["did"], "answer_invalid")
        self.assertEqual(self.reply("1. yes\n2) blue", ts)["did"], "answered")
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 1, "answer": "yes"}, {"id": 2, "answer": "blue"}])

    def test_approve_closes_only_low_risk_gates(self):
        self.n.update_settings({"replyScope": "answers_low_risk"})
        for gate in ("failure", "ui"):
            ts = self.send(need(f"SV-{gate}", "gate", gate))
            self.assertEqual(self.reply("approve", ts)["did"], f"approved_{gate}")
        for gate in ("merge", "deploy", "plan"):
            ts = self.send(need(f"SV-{gate}", "gate", gate))
            r = self.reply("approve", ts)
            self.assertEqual(r["did"], "approval_refused", gate)
        self.assertEqual(self.d.confirmed, [("SV-failure", "failure"), ("SV-ui", "ui")])

    def test_answers_only_is_the_default_and_approves_nothing(self):
        self.assertEqual(self.n.settings["replyScope"], "answers")
        ts = self.send(need("SV-5", "gate", "failure"))
        self.assertEqual(self.reply("yes", ts)["did"], "approval_refused")
        self.assertEqual(self.d.confirmed, [])

    def test_client_items_never_answer_or_approve_they_go_to_the_lead(self):
        ts = self.send(need("GM-1", "gate", "failure", "gauzemate"))
        r = self.reply("approve", ts)
        self.assertEqual(r["did"], "lead_nudged")
        self.assertEqual(self.d.confirmed, [])
        self.assertEqual(self.d.delivered[-1][:4], ("gauzemate", "approve", "slack", "GM-1"))

    def test_other_text_goes_to_the_lead_and_outside_a_thread_by_channel(self):
        ts = self.send(need("SV-6", "gate", "merge"))
        self.reply("why is this one so big?", ts)
        self.assertEqual(self.d.delivered[-1][:4], ("samvision", "why is this one so big?", "slack", "SV-6"))
        self.n._ids = FakeSlack().channels()
        self.n._dm = "DJAY"
        self.reply("status?", channel="CGY")
        self.assertEqual(self.d.delivered[-1][0], "gyst")
        self.reply("what shipped this week?", channel="DJAY")
        self.assertEqual(self.d.delivered[-1][0], "cto")
        self.assertEqual(self.slack.posts[-1]["text"], "Sent to the CTO.")

    def test_without_the_chat_store_a_reply_says_so(self):
        del FakeDaemon.deliver_to_lead
        try:
            ts = self.send(need("SV-7", "gate", "merge"))
            self.assertEqual(self.reply("hold this", ts)["did"], "lead_unavailable")
        finally:
            FakeDaemon.deliver_to_lead = _deliver


_deliver = FakeDaemon.deliver_to_lead


class ReviewFindings(ReplyBase):
    """The #91 security review: what a reply may touch is exactly what its message showed."""

    def test_a_late_reply_never_answers_newer_questions(self):
        ts = self.send(need("SV-20", "questions", None), [{"id": 1, "text": "Use Postgres?", "kind": "text", "answer": None}])
        self.d.questions["SV-20"][0]["answer"] = "answered in the app"
        self.d.questions["SV-20"].append({"id": 2, "text": "Drop the old users table?", "kind": "yesno", "answer": None})
        run(self.n.tick())
        self.assertIn("Drop the old users table?", self.slack.posts[-1]["text"])   # a new batch is a new DM
        r = self.reply("yes", ts)
        self.assertEqual(r["did"], "answer_stale")
        self.assertEqual(self.d.answered, [])
        self.assertEqual(self.reply("yes", self.slack.posts[-2]["ts"])["did"], "answered")
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 2, "answer": "yes"}])

    def test_an_old_approve_never_clears_a_newer_blocker(self):
        self.n.update_settings({"replyScope": "answers_low_risk"})
        ts = self.send(dict(need("SV-21", "gate", "failure", text="Blocked: needs a sample file"), since=100.0))
        self.d.needs_list = [dict(need("SV-21", "gate", "failure", text="Blocked: needs a database password"), since=200.0)]
        self.assertEqual(self.reply("approve", ts)["did"], "approval_stale")
        self.assertEqual(self.d.confirmed, [])

    def test_a_redelivered_event_is_handled_once(self):
        ts = self.send(need("SV-22", "gate", "merge"))
        ev = {"event_id": "Ev1", "event": {"type": "message", "user": JAY, "text": "hold it", "channel": "DJAY",
                                           "ts": "70.1", "thread_ts": ts, "client_msg_id": "m-1"}}
        run(self.n.on_slack(ev))
        self.assertIsNone(run(self.n.on_slack(dict(ev, retry_attempt=1))))
        self.assertEqual(len(self.d.delivered), 1)

    def test_lead_replies_in_a_thread_are_redacted_and_escaped(self):
        ts = self.send(need("SV-23", "gate", "merge"))
        self.reply("why?", ts)

        class Chat:
            def get(self, mid):
                return {"id": 9, "conversation": "samvision", "reply_to": 7,
                        "text": "token=abcdef1234567890 <!channel> <https://evil.example|Open in CommandCenter>"}
        self.d.chat = Chat()
        run(self.n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 9}}))
        text = self.slack.posts[-1]["text"]
        self.assertEqual(self.slack.posts[-1]["thread"], ts)
        self.assertNotIn("abcdef1234567890", text)
        self.assertNotIn("<!channel>", text)
        self.assertNotIn("<https://evil", text)
        self.assertIn("&lt;!channel&gt;", text)

    def test_agent_text_cannot_post_mentions_or_fake_links(self):
        self.send(need("SV-24", "gate", "merge", text="Ready to merge: <!channel> <https://evil|Open in CommandCenter>"))
        text = self.slack.posts[-1]["text"]
        self.assertNotIn("<!channel>", text)
        self.assertEqual(text.count("|Open in CommandCenter>"), 1)          # only ccd's own link

    def test_a_stale_question_left_open_is_said_plainly(self):
        async def partial(key, body, actor="jay", developer=False, via=None):
            return {"delivered": False, "complete": False}
        ts = self.send(need("SV-25", "questions", None), [{"id": 3, "text": "A?", "kind": "text", "answer": None}])
        self.d.task_answers = partial
        r = self.reply("A", ts)
        self.assertEqual(r["say"], "Answered. Another question on this task is still open in CommandCenter.")


class LeadReplies(unittest.TestCase):
    def test_a_lead_reply_returns_to_the_slack_thread_it_answers(self):
        n, d, slack, _ = make(settings={"slack": True})
        run(n.tick())
        d.needs_list = [need("SV-8", "gate", "merge")]
        run(n.tick())
        ts = slack.posts[-1]["ts"]
        run(n.on_slack({"event": {"type": "message", "user": JAY, "text": "why?", "channel": "DJAY", "ts": "50.0",
                                  "thread_ts": ts}}))

        class Chat:
            def get(self, mid):
                return {"id": 8, "conversation": "samvision", "text": "It touches the importer.", "reply_to": 7}
        d.chat = Chat()
        run(n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 8, "conversation": "samvision"}}))
        self.assertEqual((slack.posts[-1]["channel"], slack.posts[-1]["thread"]), ("DJAY", ts))
        self.assertIn("It touches the importer.", slack.posts[-1]["text"])


class Socket(unittest.TestCase):
    def test_envelopes_are_acknowledged_and_events_handled(self):
        n, d, slack, _ = make(settings={"slack": True})
        frames = [{"type": "hello"},
                  {"type": "events_api", "envelope_id": "E1",
                   "payload": {"event": {"type": "message", "user": JAY, "text": "hi", "channel": "CCTO", "ts": "1.1"}}},
                  {"type": "disconnect"}]
        sent = []

        class WS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def __aiter__(self):
                async def gen():
                    for f in frames:
                        yield json.dumps(f)
                return gen()

            async def send(self, raw):
                sent.append(json.loads(raw))

        run(n._socket_once(connect=lambda url, **kw: WS()))
        self.assertEqual(sent, [{"envelope_id": "E1"}])
        self.assertEqual(d.delivered[-1][:2], ("cto", "hi"))


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    """The daemon's own guard: whatever calls it, Slack closes only the Low-risk gates."""

    async def asyncSetUp(self):
        self.store = Store(os.path.join(tempfile.mkdtemp(), "ccd.db"))
        self.ts = TaskStore(":memory:", [{"key": "samvision", "name": "SamVision", "prefix": "SV"},
                                         {"key": "gauzemate", "name": "GauzeMate", "prefix": "GZ"}])
        self.d = Daemon(cfg(meter={"enabled": False}), self.store, None, tasks=self.ts)
        self.d.notifier = notify.Notifier(self.d, {"notify": {}}, slack=FakeSlack())

    async def test_merge_deploy_and_plan_are_refused(self):
        t, _ = self.ts.create("samvision", "Valuation")
        for gate in ("merge", "deploy", "plan"):
            with self.assertRaises(ActionError) as e:
                await self.d.slack_confirm(t["key"], gate)
            self.assertEqual(e.exception.status, 403)

    async def test_a_blocker_is_cleared_with_via_slack(self):
        t, _ = self.ts.create("samvision", "Valuation")
        self.d.pipeline.plan(t["key"], {"summary": "s", "risk": "low"}, "agent:planner")
        self.d.pipeline.block(t["key"], "needs a sample file", "agent:coordinator")
        r = await self.d.slack_confirm(t["key"], "failure")
        self.assertIsNone(r["work"]["gate"])
        self.assertFalse(r["delivered"])                # no task session in this test
        (data,) = self.ts.db.execute("SELECT data FROM ticket_events WHERE kind='pipeline.gate_confirmed'").fetchone()
        self.assertEqual(json.loads(data).get("via"), "slack")

    async def test_slack_answers_are_recorded_as_slack(self):
        t, _ = self.ts.create("samvision", "Valuation")
        self.d.pipeline.ask(t["key"], ["Same layout on mobile?"], "agent:coordinator")
        qid = self.d.task_work(t["key"])["questions"][0]["id"]
        await self.d.task_answers(t["key"], {"answers": [{"id": qid, "answer": "Yes"}]}, "jay", developer=True, via="slack")
        q = self.d.task_work(t["key"])["questions"][0]
        self.assertEqual(q["answeredBy"], "jay:slack")
        (data,) = self.ts.db.execute("SELECT data FROM ticket_events WHERE kind='pipeline.answered'").fetchone()
        self.assertEqual(json.loads(data).get("via"), "slack")

    async def test_client_project_gates_are_refused(self):
        t, _ = self.ts.create("gauzemate", "Intake")
        self.d.pipeline.plan(t["key"], {"summary": "s", "risk": "low"}, "agent:planner")
        self.d.pipeline.block(t["key"], "x", "agent:coordinator")
        with self.assertRaises(ActionError):
            await self.d.slack_confirm(t["key"], "failure")


if __name__ == "__main__":
    unittest.main()


class OverHttp(unittest.TestCase):
    TOKEN = "t" * 43
    DEV = "d" * 43

    def setUp(self):
        from starlette.testclient import TestClient
        from ccd.api import create_app
        store = Store(os.path.join(tempfile.mkdtemp(), "ccd.db"))
        self.d = Daemon(cfg(meter={"enabled": False}), store, None, tasks=None)
        self.d.dev_gate = security.DeveloperGate(self.DEV)
        self.d.notifier = notify.Notifier(self.d, {"notify": {}}, slack=FakeSlack())
        guarded, _app = create_app(self.d, self.TOKEN, 7799)
        self.c = TestClient(guarded, base_url="http://127.0.0.1:7799")
        self.h = {"x-ccd-token": self.TOKEN, "content-type": "application/json"}

    def test_reading_needs_the_token_and_changing_needs_developer_unlock(self):
        self.assertEqual(self.c.get("/api/notify").status_code, 401)
        self.assertFalse(self.c.get("/api/notify", headers=self.h).json()["settings"]["slack"])
        self.assertEqual(self.c.put("/api/notify", content='{"slack": true}', headers=self.h).status_code, 403)
        sid = self.c.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=self.h).json()["session"]
        dev = dict(self.h, **{"x-ccd-developer": sid})
        agent = dict(dev, **{"x-ccd-actor": "agent:coordinator"})
        self.assertEqual(self.c.put("/api/notify", content='{"slack": true}', headers=agent).status_code, 403)
        self.assertEqual(self.c.put("/api/notify", content='{"quietStart": "9pm"}', headers=dev).status_code, 400)
        r = self.c.put("/api/notify", content='{"slack": true, "quietStart": "23:00"}', headers=dev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["settings"]["slack"], r.json()["settings"]["quietStart"]), (True, "23:00"))
