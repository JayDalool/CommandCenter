"""Slack and ntfy (ccd/notify.py): off by default, quiet hours, client redaction, Jay-only replies, and the fixed
limit on what a Slack reply may approve."""
import asyncio
import datetime
import json
import os
import tempfile
import unittest
import urllib.parse
from zoneinfo import ZoneInfo

from ccd import notify, security
from ccd.daemon import ActionError, Daemon
from ccd.pipeline import plan_digest
from ccd.store import Store
from ccd.tasks import TaskError, TaskStore

from .helpers import cfg

JAY = "U0JAY0001"
TZ = ZoneInfo("America/Winnipeg")


def at(hh, mm=0, day=12):
    return datetime.datetime(2026, 11, day, hh, mm, tzinfo=TZ).timestamp()


class FakeSlack:
    def __init__(self):
        self.posts = []
        self.uploads = []
        self.upload_error = None
        self.n = 0
        self.scopes = None          # as SlackWeb before its first call: the token's scopes are not known yet

    def post(self, channel, text, thread_ts=None, as_=None, broadcast=False):
        self.n += 1
        self.posts.append({"channel": channel, "text": text, "thread": thread_ts, "ts": f"{self.n}.0", "as": as_,
                           "broadcast": broadcast})
        return {"ok": True, "ts": f"{self.n}.0"}

    def upload(self, channel, thread_ts, name, data):
        if self.upload_error:
            raise notify.SlackError(self.upload_error)
        self.uploads.append({"channel": channel, "thread": thread_ts, "name": name, "data": data})
        return {"ok": True}

    def channels(self):
        return {"cto": "CCTO", "commandcenter": "CCC", "samvision": "CSV", "gyst": "CGY", "mfe": "CMF"}

    def dm(self, user):
        return "DJAY"

    def socket_url(self):
        return "wss://example.invalid/socket"


class SlackWebRequests(unittest.TestCase):
    """What ccd sends to Slack's Web API. Slack ignores a JSON body on a read method: conversations.list sent as JSON
    ran with its defaults and listed public channels only, so ccd never found its private project channels."""

    def setUp(self):
        self.sent = []
        self.pages = [{"ok": True, "channels": [{"name": "commandcenter", "id": "CCC"}],
                       "response_metadata": {"next_cursor": "page2"}},
                      {"ok": True, "channels": [{"name": "cto", "id": "CCTO"}], "response_metadata": {}}]

        test = self

        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.body).encode()

            @property
            def headers(self):
                return getattr(test, "headers", {})

        def opener(req, timeout=None):
            test.sent.append(req)
            return Resp(test.pages.pop(0) if "conversations.list" in req.full_url else {"ok": True, "ts": "1.0"})
        self.web = notify.SlackWeb("xoxb-test", opener=opener)

    def test_the_channel_list_is_asked_for_as_a_form_with_private_channels(self):
        self.assertEqual(self.web.channels(), {"commandcenter": "CCC", "cto": "CCTO"})
        self.assertEqual(len(self.sent), 2)
        for req in self.sent:
            self.assertEqual(req.get_header("Content-type"), "application/x-www-form-urlencoded")
            self.assertEqual(req.get_header("Authorization"), "Bearer xoxb-test")
        first = urllib.parse.parse_qs(self.sent[0].data.decode())
        self.assertEqual(first, {"types": ["private_channel,public_channel"], "exclude_archived": ["true"],
                                 "limit": ["200"]})
        self.assertEqual(urllib.parse.parse_qs(self.sent[1].data.decode())["cursor"], ["page2"])

    def test_the_tokens_scopes_are_read_and_a_post_can_carry_a_seats_name(self):
        self.headers = {"x-oauth-scopes": "chat:write, groups:read,chat:write.customize"}
        self.web.post("CCC", "plan recorded", thread_ts="9.0", as_=("Investigator", ":mag:"), broadcast=True)
        self.assertEqual(self.web.scopes, {"chat:write", "groups:read", "chat:write.customize"})
        self.assertEqual(json.loads(self.sent[0].data), {"channel": "CCC", "text": "plan recorded", "unfurl_links": False,
                                                         "unfurl_media": False, "thread_ts": "9.0",
                                                         "reply_broadcast": True, "username": "Investigator",
                                                         "icon_emoji": ":mag:"})

    def test_a_file_goes_by_slacks_external_upload_and_its_bytes_never_carry_the_token(self):
        answers = {"files.getUploadURLExternal": {"ok": True, "upload_url": "https://files.slack.com/upload/v1/ABC",
                                                  "file_id": "F123"},
                   "files.completeUploadExternal": {"ok": True, "files": [{"id": "F123"}]}}
        sent = self.sent

        class Resp:
            def __init__(self, body):
                self.body, self.headers = body, {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.body).encode()

        def opener(req, timeout=None):
            sent.append(req)
            return Resp(answers.get(req.full_url.rsplit("/", 1)[-1], {"ok": True}))
        self.web.open = opener
        self.web.upload("CCC", "9.0", "report.md", b"# Report\n")
        ask, put, done = self.sent
        self.assertEqual(urllib.parse.parse_qs(ask.data.decode()), {"filename": ["report.md"], "length": ["9"]})
        self.assertEqual((put.full_url, put.data, put.get_header("Authorization")),
                         ("https://files.slack.com/upload/v1/ABC", b"# Report\n", None))
        self.assertEqual(urllib.parse.parse_qs(done.data.decode()), {
            "files": ['[{"id": "F123", "title": "report.md"}]'], "channel_id": ["CCC"], "thread_ts": ["9.0"]})
        self.assertEqual(done.get_header("Authorization"), "Bearer xoxb-test")
        self.sent.clear()
        answers["files.getUploadURLExternal"]["upload_url"] = "https://files.example.com/upload"
        with self.assertRaises(notify.SlackError):
            self.web.upload("CCC", "9.0", "report.md", b"# Report\n")
        self.assertEqual(len(self.sent), 1)                     # the bytes went nowhere

    def test_a_post_is_still_json(self):
        self.web.post("CCC", "hello", thread_ts="9.0")
        req = self.sent[0]
        self.assertTrue(req.get_header("Content-type").startswith("application/json"))
        self.assertEqual(json.loads(req.data), {"channel": "CCC", "text": "hello", "unfurl_links": False,
                                                "unfurl_media": False, "thread_ts": "9.0"})


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
        self.plans = {}
        self.reviews = {}
        self.work = {}
        self.merged = []
        self.deploys = []
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
        return dict({"questions": self.questions.get(key, []), "plan": self.plans.get(key) or {},
                     "planReview": self.reviews.get(key)}, **self.work.get(key, {}))

    async def task_answers(self, key, body, actor="jay", developer=False, via=None):
        self.answered.append((key, body, actor, developer, via))
        done = {a["id"] for a in body["answers"]}
        for q in self.questions.get(key, []):
            if q["id"] in done:
                q["answer"] = "x"
        return {"delivered": True}

    async def slack_confirm(self, key, gate, plan_hash=None):
        self.confirmed.append((key, gate))
        self.plan_hash = plan_hash
        return {"delivered": True, "work": self.work.get(key, {})}

    async def slack_merge(self, key, head):
        self.merged.append((key, head))
        return {"merging": [{"key": key, "head": head}], "skipped": []}

    async def slack_deploy(self, key, plan_hash):
        self.deploys.append((key, plan_hash))
        return {"delivered": True}

    async def slack_ask_back(self, key, text):
        self.asked_back = getattr(self, "asked_back", []) + [(key, text)]
        return getattr(self, "ask_back_result", {"delivered": True, "reason": None})

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
        for bad in ({"slack": "yes"}, {"quietStart": "25:00"}, {"timezone": "Mars/Base"}, {"replyScope": "everything"},
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

    def test_options_are_numbered_with_the_recommended_one_and_a_number_answers(self):
        q = {"id": 21, "text": "Export format?", "kind": "choice", "options": ["CSV", "XLSX", "Both"],
             "recommended": 1, "why": "clients open it in Excel", "answer": None}
        ts = self.send(need("SV-5", "questions", None), [q])
        dm = self.slack.posts[-1]["text"]
        self.assertIn("*1*  CSV", dm)
        self.assertIn("*2*  XLSX  ⭐ _recommended_: clients open it in Excel", dm)
        self.assertIn("an option's number, or your own answer", dm)
        self.assertEqual(self.reply("2", ts)["did"], "answered")
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 21, "answer": "XLSX"}])

    def test_with_several_questions_options_are_lettered_and_own_words_still_count(self):
        qs = [{"id": 31, "text": "Format?", "kind": "choice", "options": ["CSV", "XLSX"], "recommended": 0,
               "why": "simplest", "answer": None},
              {"id": 32, "text": "Who first?", "kind": "choice", "options": ["Admins", "Everyone"], "answer": None}]
        ts = self.send(need("SV-6", "questions", None), qs)
        dm = self.slack.posts[-1]["text"]
        self.assertIn("*a*  CSV  ⭐ _recommended_: simplest", dm)
        self.assertIn("*b*  Everyone", dm)
        self.assertEqual(self.reply("1. b\n2. only the pilot group", ts)["did"], "answered")
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 31, "answer": "XLSX"},
                                                             {"id": 32, "answer": "only the pilot group"}])

    def test_several_options_by_number_or_letter(self):
        q = {"id": 51, "text": "Which exports? (pick one or more)", "kind": "choice", "options": ["CSV", "XLSX", "PDF"],
             "answer": None}
        ts = self.send(need("SV-51", "questions", None), [q])
        self.assertEqual(self.reply("1, 3", ts)["did"], "answered")
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 51, "answer": "CSV; PDF"}])
        q2 = [dict(q, id=52, answer=None), {"id": 53, "text": "Who?", "kind": "text", "answer": None}]
        ts = self.send(need("SV-52", "questions", None), q2)
        self.assertEqual(self.reply("1. a and d\n2. admins", ts)["did"], "answer_invalid")
        self.assertIn("Question 1 has options a–c", self.slack.posts[-1]["text"])
        self.assertEqual(self.reply("1. a and b\n2. admins", ts)["did"], "answered")
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 52, "answer": "CSV; XLSX"},
                                                             {"id": 53, "answer": "admins"}])

    def test_a_reply_ending_with_a_question_mark_asks_the_agent_and_answers_nothing(self):
        q = {"id": 61, "text": "Export format?", "kind": "choice", "options": ["CSV", "XLSX"], "answer": None}
        ts = self.send(need("SV-61", "questions", None), [q])
        self.assertIn("A reply that ends with ? goes to the agent", self.slack.posts[-1]["text"])
        r = self.reply("What does XLSX change for the importer?", ts)
        self.assertEqual(r["did"], "asked_back")
        self.assertEqual(self.d.asked_back, [("SV-61", "What does XLSX change for the importer?")])
        self.assertEqual(self.d.answered, [])
        self.assertIn("Its answer comes back in this thread", self.slack.posts[-1]["text"])
        # The agent answers (pipeline_cli reply): in that same thread, quoted as its words.
        self.assertTrue(run(self.n.agent_reply("SV-61", "samvision", "XLSX needs the openpyxl reader.\n<!channel>")))
        post = self.slack.posts[-1]
        self.assertEqual((post["channel"], post["thread"]), ("DJAY", ts))
        self.assertIn("The agent answers:\n> XLSX needs the openpyxl reader.\n> &lt;!channel&gt;", post["text"])
        self.assertEqual(self.reply("2", ts)["did"], "answered")                      # the questions still take answers
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 61, "answer": "XLSX"}])

    def test_a_question_back_with_no_task_session_goes_to_the_lead(self):
        ts = self.send(need("SV-62", "questions", None), [{"id": 62, "text": "A or B?", "kind": "text", "answer": None}])
        self.d.ask_back_result = {"delivered": False, "noSession": True}
        self.assertEqual(self.reply("why not both?", ts)["did"], "lead_nudged")
        self.assertEqual(self.d.delivered[-1][0], "samvision")
        self.d.ask_back_result = {"delivered": False, "reason": "the agent is working"}
        r = self.reply("why not both?", ts)
        self.assertEqual(r["did"], "ask_back_undelivered")
        self.assertIn("the agent is working", self.slack.posts[-1]["text"])
        self.assertEqual(self.d.answered, [])

    def test_an_agent_reply_for_a_client_project_or_with_no_thread(self):
        self.assertFalse(run(self.n.agent_reply("GZ-1", "gauzemate", "details")))
        self.assertTrue(run(self.n.agent_reply("SV-63", "samvision", "No thread yet")))
        post = self.slack.posts[-1]
        self.assertEqual((post["channel"], post["thread"]), ("DJAY", None))

    def test_a_number_out_of_range_or_on_a_text_question_is_kept_as_written(self):
        ts = self.send(need("SV-7", "questions", None), [{"id": 41, "text": "How many?", "kind": "text", "answer": None}])
        self.reply("3", ts)
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 41, "answer": "3"}])
        ts = self.send(need("SV-8", "questions", None), [{"id": 42, "text": "Pick", "kind": "choice",
                                                          "options": ["x", "y"], "answer": None}])
        for wrong in ("5", "1, 9"):                            # a pick of an option it does not have is refused
            self.assertEqual(self.reply(wrong, ts)["did"], "answer_invalid", wrong)
            self.assertIn("This question has options 1–2. Reply with those, or start with Other:",
                          self.slack.posts[-1]["text"])
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 41, "answer": "3"}])
        self.reply("Other: 5", ts)
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 42, "answer": "Other: 5"}])
        ts = self.send(need("SV-9", "questions", None), [{"id": 43, "text": "Replicas?", "kind": "choice",
                                                          "options": ["2", "4", "8"], "answer": None}])
        self.reply("2", ts)                                    # the option "2", not the second option
        self.assertEqual(self.d.answered[-1][1]["answers"], [{"id": 43, "answer": "2"}])

    def test_approve_closes_only_low_risk_gates(self):
        self.n.update_settings({"replyScope": "answers_low_risk"})
        for gate in ("failure", "ui"):
            ts = self.send(need(f"SV-{gate}", "gate", gate))
            self.assertEqual(self.reply("approve", ts)["did"], f"approved_{gate}")
        for gate in ("merge", "deploy"):
            ts = self.send(need(f"SV-{gate}", "gate", gate))
            r = self.reply("approve", ts)
            self.assertEqual(r["did"], "approval_refused", gate)
        self.assertEqual(self.d.confirmed, [("SV-failure", "failure"), ("SV-ui", "ui")])

    HEAD = "a" * 40

    def test_with_everything_a_merge_reply_merges_the_head_the_dm_showed(self):
        self.n.update_settings({"replyScope": "all"})
        self.d.work["SV-40"] = {"review": {"verdict": "APPROVE", "head": self.HEAD, "pr": "o/r#5"}}
        ts = self.send(need("SV-40", "gate", "merge", text="Ready to merge: PR o/r#5 approved and green"))
        dm = self.slack.posts[-1]["text"]
        self.assertIn("*PR:* o/r#5 · head `aaaaaaaaaaaa` · review APPROVE", dm)
        self.assertIn("Reply *merge*", dm)
        r = self.reply("merge", ts)
        self.assertEqual(r["did"], "approved_merge")
        self.assertEqual(self.d.merged, [("SV-40", self.HEAD)])
        self.assertEqual(self.d.confirmed, [])                    # never a bare gate approval

    def test_only_the_word_merge_merges(self):
        self.n.update_settings({"replyScope": "all"})
        self.d.work["SV-39"] = {"review": {"verdict": "APPROVE", "head": self.HEAD, "pr": "o/r#4"}}
        ts = self.send(need("SV-39", "gate", "merge", text="Ready to merge: PR o/r#4 approved and green"))
        for casual in ("ok", "yes", "👍", "approve"):
            r = self.reply(casual, ts)
            self.assertEqual(r["did"], "merge_word_needed", casual)
            self.assertIn("Nothing was merged", self.slack.posts[-1]["text"])
        self.assertEqual((self.d.merged, self.d.confirmed), ([], []))
        self.assertEqual(self.reply("Merge it.", ts)["did"], "approved_merge")
        self.assertEqual(self.d.merged, [("SV-39", self.HEAD)])

    def test_a_merge_reply_after_a_new_head_merges_nothing(self):
        self.n.update_settings({"replyScope": "all"})
        self.d.work["SV-41"] = {"review": {"verdict": "APPROVE", "head": self.HEAD, "pr": "o/r#6"}}
        ts = self.send(need("SV-41", "gate", "merge", text="Ready to merge: PR o/r#6 approved and green"))
        self.d.work["SV-41"] = {"review": {"verdict": "APPROVE", "head": "b" * 40, "pr": "o/r#6"}}
        self.assertEqual(self.reply("merge", ts)["did"], "approval_stale")
        self.assertEqual(self.d.merged, [])

    def test_merges_and_deploys_need_everything(self):
        self.n.update_settings({"replyScope": "answers_low_risk"})
        self.d.work["SV-42"] = {"review": {"verdict": "APPROVE", "head": self.HEAD, "pr": "o/r#7"}}
        ts = self.send(need("SV-42", "gate", "merge"))
        self.assertNotIn("Reply *merge*", self.slack.posts[-1]["text"])
        self.assertEqual(self.reply("merge", ts)["did"], "approval_refused")
        ts = self.send(need("SV-43", "gate", "deploy", text="Deploy approval: Ready for live deployment"))
        self.assertEqual(self.reply("deploy", ts)["did"], "approval_refused")
        self.assertEqual((self.d.merged, self.d.confirmed), ([], []))

    def deploy_ready(self, key, plan):
        self.d.work[key] = {"deploy": {"env": "live", "approvedAt": 5.0, "approvedBy": "jay:slack", "result": None,
                                       "plan": plan}}
        run(self.n.on_event({"kind": "task.pipeline", "project": "samvision", "ref": key, "text": f"{key} deploy plan",
                             "data": {"kind": "pipeline.deploy_prepared"}}))
        return [p for p in self.slack.posts if p["channel"] == "DJAY"][-1]

    def test_a_deploy_takes_an_approve_then_a_deploy_on_the_plan(self):
        self.n.update_settings({"replyScope": "all"})
        self.d.work["SV-44"] = {"deploy": {"env": "live", "approvedAt": 5.0, "approvedBy": "jay:slack", "result": None}}
        ts = self.send(need("SV-44", "gate", "deploy", text="Deploy approval: Ready for live deployment"))
        self.assertIn("nothing deploys until you reply *deploy*", self.slack.posts[-1]["text"])
        r = self.reply("approve", ts)
        self.assertEqual(r["did"], "approved_deploy")
        self.assertIn("Approved to prepare", self.slack.posts[-1]["text"])
        self.assertEqual(self.d.deploys, [])
        plan = {"summary": "1. run migration 0042\n2. restart ccd\nrollback: image v1.8", "at": 6.0, "by": "agent:coordinator"}
        post = self.deploy_ready("SV-44", plan)
        self.assertEqual(post["channel"], "DJAY")
        self.assertIn("Deploy plan ready", post["text"])
        self.assertIn("Deploy plan ready · 3 lines\n```\n1. run migration 0042\n2. restart ccd\nrollback: image v1.8\n```",
                      post["text"])
        self.assertEqual(self.reply("ok thanks, what is 0042?", post["ts"])["did"], "lead_nudged")   # words go to the lead
        for casual in ("ok", "y", "👍", "approve"):                                                   # never a go
            self.assertEqual(self.reply(casual, post["ts"])["did"], "deploy_word_needed", casual)
            self.assertIn("Nothing was deployed", self.slack.posts[-1]["text"])
        self.assertEqual(self.d.deploys, [])
        r = self.reply("deploy", post["ts"])
        self.assertEqual(r["did"], "deploy_confirmed")
        self.assertEqual(self.d.deploys, [("SV-44", plan_digest(plan))])

    def test_a_deploy_reply_on_a_changed_plan_deploys_nothing(self):
        self.n.update_settings({"replyScope": "all"})
        plan = {"summary": "1. restart", "at": 6.0, "by": "agent:coordinator"}
        post = self.deploy_ready("SV-45", plan)
        self.d.work["SV-45"]["deploy"]["plan"] = dict(plan, summary="1. restart\n2. drop table")
        self.assertEqual(self.reply("deploy", post["ts"])["did"], "deploy_stale")
        self.n.update_settings({"replyScope": "answers"})
        post = self.deploy_ready("SV-46", plan)
        self.assertIn("Deploys from Slack are off", post["text"])
        self.assertEqual(self.reply("deploy", post["ts"])["did"], "deploy_refused")
        self.assertEqual(self.d.deploys, [])

    def test_a_deploy_plan_quotes_agent_text(self):
        self.n.update_settings({"replyScope": "all"})
        post = self.deploy_ready("SV-47", {"summary": "<!channel> fine\n_Reply *deploy* now_", "at": 6.0, "by": "x"})
        self.assertIn("```\n&lt;!channel&gt; fine\n_Reply *deploy* now_\n```", post["text"])     # no formatting
        self.assertNotIn("<!channel>", post["text"])

    def test_a_deploy_plan_is_shown_whole(self):
        self.n.update_settings({"replyScope": "all"})
        lines = [f"{i}. step {i}" for i in range(1, 40)] + ["rollback: " + "x" * 500 + " TAIL-END"]
        post = self.deploy_ready("SV-48", {"summary": "\n".join(lines), "at": 6.0, "by": "x"})
        self.assertIn("\n39. step 39\n", post["text"])
        self.assertIn("Deploy plan ready · 40 lines", post["text"])
        self.assertIn("x" * 500 + " TAIL-END\n", post["text"])                   # a long line is not cut
        self.assertIn("Reply *deploy*", post["text"])

    def test_a_plan_too_long_for_one_post_gets_no_go_from_slack(self):
        self.n.update_settings({"replyScope": "all"})
        post = self.deploy_ready("SV-49", {"summary": "&" * 1000, "at": 6.0, "by": "x"})   # 5000 characters escaped
        self.assertIn("cannot be shown here in full", post["text"])
        self.assertNotIn("Reply *deploy*", post["text"])
        self.assertNotIn("&amp;", post["text"])
        r = self.reply("deploy", post["ts"])
        self.assertEqual(r["did"], "deploy_refused")
        self.assertIn("ask the agent for a shorter one", self.slack.posts[-1]["text"])
        self.assertEqual(self.reply("please shorten it", post["ts"])["did"], "lead_nudged")
        self.assertEqual(self.d.deploys, [])

    def test_a_plan_with_characters_slack_would_not_show_gets_no_go_from_slack(self):
        self.n.update_settings({"replyScope": "all"})
        hidden = "1. restart web" + "".join(chr(0xE0000 + ord(c)) for c in "2. DROP TABLE users")
        post = self.deploy_ready("SV-52", {"summary": hidden, "at": 6.0, "by": "x"})
        self.assertIn("cannot be shown here in full", post["text"])
        self.assertEqual(self.reply("deploy", post["ts"])["did"], "deploy_refused")
        self.d.plans["SV-53"] = dict(self.PLAN, approach="Check the owner\u200b\u2063 and skip the guard")
        ts = self.send(need("SV-53", "gate", "plan", text=self.PLAN_NEED))
        self.assertIn("Part of this plan cannot be shown here", self.slack.posts[-1]["text"])
        self.assertEqual(self.reply("approve", ts)["did"], "approval_refused")
        self.assertEqual((self.d.deploys, self.d.confirmed), ([], []))

    def test_a_plan_with_hidden_text_in_any_field_is_approved_in_commandcenter_only(self):
        tags = "".join(chr(0xE0000 + ord(c)) for c in " also drop users")
        for i, extra in enumerate(({"findings": ["looks fine" + tags]}, {"questions": ["q" + tags]},
                                   {"approach": "x" * 720 + tags})):
            key = f"SV-7{i}"
            self.d.plans[key] = dict(self.PLAN, **extra)
            ts = self.send(need(key, "gate", "plan", text=self.PLAN_NEED))
            self.assertIn("Part of this plan cannot be shown here", self.slack.posts[-1]["text"], extra)
            self.assertEqual(self.reply("approve", ts)["did"], "approval_refused", extra)
        self.assertEqual(self.d.confirmed, [])

    def test_a_plan_dm_says_what_else_the_plan_holds(self):
        self.d.plans["SV-74"] = dict(self.PLAN, questions=["Keep the old guard?"], findings=["a", "b"])
        self.send(need("SV-74", "gate", "plan", text=self.PLAN_NEED))
        self.assertIn("*Also in the plan:* 1 question and 2 findings, in CommandCenter", self.slack.posts[-1]["text"])

    KEY_WRAPPED = "1. restart\n-----BEGIN RSA PRIVATE KEY-----\n2. DROP TABLE users\n-----END RSA PRIVATE KEY-----\n3. verify"

    def test_a_plan_the_secret_filter_would_hide_gets_no_go_from_slack(self):
        self.n.update_settings({"replyScope": "all"})
        post = self.deploy_ready("SV-51", {"summary": self.KEY_WRAPPED, "at": 6.0, "by": "x"})
        self.assertIn("cannot be shown here in full", post["text"])
        self.assertNotIn("Reply *deploy*", post["text"])
        self.assertNotIn("[redacted]", post["text"])
        self.assertEqual(self.reply("deploy", post["ts"])["did"], "deploy_refused")
        self.assertEqual(self.d.deploys, [])

    WED_22 = datetime.datetime(2026, 11, 18, 22, 0, tzinfo=ZoneInfo("America/Winnipeg")).timestamp()

    def test_a_held_deploy_plan_says_until_when(self):
        self.n.update_settings({"replyScope": "all"})
        self.d.work["SV-50"] = {"deploy": {"env": "live", "approvedAt": 5.0, "approvedBy": "jay:slack", "result": None,
                                           "heldUntil": self.WED_22, "plan": {"summary": "1. restart", "at": 6.0,
                                                                               "by": "x"}}}
        run(self.n.on_event({"kind": "task.pipeline", "project": "samvision", "ref": "SV-50", "text": "SV-50 plan",
                             "data": {"kind": "pipeline.deploy_prepared"}}))
        post = [p for p in self.slack.posts if p["channel"] == "DJAY"][-1]
        self.assertIn("Held for the release window until Wed 2026-11-18 22:00 ", post["text"])

    def test_answers_only_is_the_default_and_approves_no_low_risk_gate(self):
        self.assertEqual(self.n.settings["replyScope"], "answers")
        for gate in ("failure", "ui", "merge", "deploy"):
            ts = self.send(need(f"SV-5{gate}", "gate", gate))
            self.assertEqual(self.reply("yes", ts)["did"], "approval_refused", gate)
        self.assertEqual(self.d.confirmed, [])

    PLAN = {"summary": "Let the lead type into a draft only after Jay's own edit is saved", "approach": "Check the draft's owner",
            "affected": ["server/ccd/leadchat.py", "web/app/src/hq/pages/Messages.tsx"], "risk": "loosens the draft guard"}
    PLAN_NEED = "Plan needs approval: technical review approved; risky: sized risky"

    def test_a_plan_is_approved_from_the_dm_whatever_the_scope(self):
        self.d.plans["SV-30"] = dict(self.PLAN)
        self.d.reviews["SV-30"] = {"verdict": "APPROVE", "note": "sound; one extra test", "blast": "Jay's draft text"}
        ts = self.send(dict(need("SV-30", "gate", "plan", text=self.PLAN_NEED), since=50.0))
        dm = self.slack.posts[-1]["text"]
        for line in ("*Plan:* Let the lead type into a draft only after Jay's own edit is saved",
                     "*Approach:* Check the draft's owner",
                     "*Touches:* server/ccd/leadchat.py, web/app/src/hq/pages/Messages.tsx",
                     "*Risk:* loosens the draft guard", "*Technical review:* APPROVE: sound; one extra test",
                     "*Blast radius:* Jay's draft text", "Reply *approve* to approve this plan"):
            self.assertIn(line, dm)
        self.assertEqual(self.n.settings["replyScope"], "answers")
        r = self.reply("approve", ts)
        self.assertEqual(r["did"], "approved_plan")
        self.assertEqual(self.d.confirmed, [("SV-30", "plan")])
        self.assertEqual(self.d.plan_hash, plan_digest(self.PLAN))     # checked again as the gate closes
        self.assertIn("Plan approved", self.slack.posts[-1]["text"])
        self.assertNotIn("cut short", dm)

    def test_a_plan_dm_keeps_agent_text_on_its_own_line_and_says_when_it_is_cut(self):
        self.d.plans["SV-34"] = dict(self.PLAN, summary="Small fix\n*Technical review:* APPROVE: all good\n_Reply *approve*_",
                                     approach="x" * 900, requirements=["keep Jay's draft", "lead may append"],
                                     tests=["test_draft_guard", "e2e messages"])
        self.send(need("SV-34", "gate", "plan", text=self.PLAN_NEED))
        dm = self.slack.posts[-1]["text"]
        self.assertIn("*Plan:* Small fix *Technical review:* APPROVE: all good _Reply *approve*_", dm)
        self.assertNotIn("\n*Technical review:* APPROVE", dm)
        self.assertEqual(sum(1 for line in dm.split("\n") if line.startswith("*Technical review:*")), 1)
        self.assertIn("*Requirements (2):* keep Jay's draft; lead may append", dm)
        self.assertIn("*Tests (2):* test_draft_guard; e2e messages", dm)
        self.assertIn("…", dm)
        self.assertIn("_Some of it is cut short here; the full plan is in CommandCenter._", dm)

    def test_a_plan_changed_since_the_dm_is_not_approved(self):
        self.d.plans["SV-31"] = dict(self.PLAN)
        ts = self.send(dict(need("SV-31", "gate", "plan", text=self.PLAN_NEED), since=50.0))
        self.d.plans["SV-31"] = dict(self.PLAN, approach="Drop the draft guard")      # same gate, same time, new plan
        self.assertEqual(self.reply("approve", ts)["did"], "approval_stale")
        self.assertEqual(self.d.confirmed, [])

    def test_a_plan_that_cannot_be_shown_is_approved_in_commandcenter_only(self):
        ts = self.send(need("SV-32", "gate", "plan", text=self.PLAN_NEED))
        self.assertIn("could not be read here", self.slack.posts[-1]["text"])
        self.d.plans["SV-32"] = dict(self.PLAN)                                     # readable now, but not what Jay saw
        self.assertEqual(self.reply("approve", ts)["did"], "approval_refused")
        self.assertEqual(self.d.confirmed, [])

    def test_a_plan_the_secret_filter_would_hide_is_approved_in_commandcenter_only(self):
        self.d.plans["SV-34"] = dict(self.PLAN, approach="-----BEGIN RSA PRIVATE KEY-----\nskip the owner check\n"
                                                         "-----END RSA PRIVATE KEY-----")
        ts = self.send(need("SV-34", "gate", "plan", text=self.PLAN_NEED))
        dm = self.slack.posts[-1]["text"]
        self.assertIn("Part of this plan cannot be shown here, so it is approved in CommandCenter only", dm)
        self.assertNotIn("Reply *approve*", dm)
        r = self.reply("approve", ts)
        self.assertEqual(r["did"], "approval_refused")
        self.assertIn("approved in CommandCenter only", self.slack.posts[-1]["text"])
        self.assertEqual(self.d.confirmed, [])

    def test_a_plan_dm_shows_agent_text_as_plain_text(self):
        self.d.plans["SV-33"] = dict(self.PLAN, summary="<!channel> see <https://evil.example|ccd>")
        self.send(need("SV-33", "gate", "plan", text=self.PLAN_NEED))
        dm = self.slack.posts[-1]["text"]
        self.assertNotIn("<!channel>", dm)
        self.assertIn("&lt;!channel&gt; see &lt;https://evil.example|ccd&gt;", dm)

    def test_client_items_never_answer_or_approve_they_go_to_the_lead(self):
        self.d.plans["GM-2"] = {"summary": "client plan"}
        for ref, gate in (("GM-1", "failure"), ("GM-2", "plan")):
            ts = self.send(need(ref, "gate", gate, "gauzemate"))
            self.assertNotIn("client plan", self.slack.posts[-1]["text"])
            r = self.reply("approve", ts)
            self.assertEqual(r["did"], "lead_nudged")
            self.assertEqual(self.d.delivered[-1][:4], ("gauzemate", "approve", "slack", ref))
        self.assertEqual(self.d.confirmed, [])

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

    def test_a_channel_the_bot_joined_after_connecting_reaches_its_lead(self):
        # The socket read the list before #commandcenter's invite: Slack lists a private channel only to members.
        self.n._ids = {k: v for k, v in FakeSlack().channels().items() if k != "commandcenter"}
        r = self.reply("what's next?", channel="CCC")
        self.assertEqual(r["did"], "lead_nudged")
        self.assertEqual(self.d.delivered[-1][:2], ("commandcenter", "what's next?"))
        self.assertEqual(self.n._ids["commandcenter"], "CCC")

    def test_an_unknown_channel_rereads_the_list_at_most_once_a_minute(self):
        calls = []
        real = self.slack.channels
        self.slack.channels = lambda: calls.append(1) or real()
        self.n._ids = real()
        self.assertEqual(self.reply("hello", channel="CCC")["did"], "lead_nudged")   # a known channel: no re-read
        self.assertEqual(calls, [])
        self.assertEqual(self.reply("hello", channel="CRANDOM")["did"], "ignored")
        self.assertEqual(self.reply("hello again", channel="CRANDOM")["did"], "ignored")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.reply("hello", channel="CJUSTJOINED")["did"], "ignored")    # its own minute
        self.assertEqual(len(calls), 2)
        clock = self.n.clock
        self.n.clock = lambda: clock() + notify.IDS_REFRESH_S
        self.assertEqual(self.reply("hello?", channel="CRANDOM")["did"], "ignored")
        self.assertEqual(len(calls), 3)

    def test_a_failed_reread_is_recorded_and_the_message_ignored(self):
        def broken():
            raise notify.SlackError("conversations.list: ratelimited")
        self.slack.channels = broken
        self.n._ids = {"cto": "CCTO"}
        self.assertEqual(self.reply("what's next?", channel="CCC")["did"], "ignored")
        self.assertEqual(self.d.delivered, [])
        self.assertIn("slack channels", self.n.status["lastError"])

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
                return {"id": 9, "conversation": "samvision", "replyTo": 7,
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
                return {"id": 8, "conversation": "samvision", "text": "It touches the importer.", "replyTo": 7}
        d.chat = Chat()
        run(n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 8, "conversation": "samvision"}}))
        self.assertEqual((slack.posts[-1]["channel"], slack.posts[-1]["thread"]), ("DJAY", ts))
        self.assertIn("It touches the importer.", slack.posts[-1]["text"])


class TeamThreads(ReplyBase):
    """Each ticket has one thread in its project's channel; every seat posts its step there under its own name."""

    def setUp(self):
        super().setUp()

        class Tasks:
            def get(self, key):
                return {"key": key, "title": "Comps table is empty"}
        self.d.tasks = Tasks()

    def step(self, key, kind, text, actor=None, project="samvision"):
        data = {"kind": kind, **({"actor": actor} if actor else {})}
        run(self.n.on_event({"source": "tasks", "kind": "task.pipeline", "project": project, "ref": key,
                             "text": f"{key} {text}", "data": data}))

    def channel_posts(self, cid="CSV"):
        return [p for p in self.slack.posts if p["channel"] == cid]

    def test_steps_share_the_tickets_thread_each_under_its_seat(self):
        self.step("SV-40", "pipeline.plan", "plan recorded: three files, low risk", "agent:planner")
        self.step("SV-40", "pipeline.plan_reviewed", "technical review: APPROVE", "agent:tech-reviewer")
        root, plan, review = self.channel_posts()
        self.assertIsNone(root["thread"])
        self.assertTrue(root["text"].startswith("*SV-40* · Comps table is empty  <http://localhost:7777/#/tasks/SV-40|Open>"))
        self.assertEqual([plan["thread"], review["thread"]], [root["ts"], root["ts"]])
        # Until Slack grants chat:write.customize: the app's own name, the seat in bold first.
        self.assertEqual(plan["text"], ":mag: *Investigator*: plan recorded: three files, low risk")
        self.assertIsNone(plan["as"])
        self.slack.scopes = {"chat:write", notify.CUSTOMIZE}
        self.step("SV-40", "pipeline.started", "build started on SV-40-comps", "agent:coordinator")
        self.step("SV-40", "pipeline.review", "code review: APPROVE at abc123", "agent:reviewer")
        lead, code = self.channel_posts()[-2:]
        self.assertEqual((lead["as"], lead["text"]), (("Lead", ":compass:"), "build started on SV-40-comps"))
        self.assertEqual(code["as"], ("Code reviewer", ":eyes:"))
        self.assertEqual(len([p for p in self.channel_posts() if p["thread"] is None]), 1)      # still one thread

    def test_handoff_and_blocker_state_explain_the_next_action(self):
        self.d.task_work = lambda key: {
            "handoff": {"done": "Portion tests passed", "next": "Check the review screen", "owner": "user-reviewer"},
            "blocked": {"action": "Check the missing fixture", "owner": "developer"},
        }
        self.step("SV-44", "pipeline.handoff", "handoff updated", "agent:implementer")
        self.step("SV-44", "pipeline.blocked", "Preview data missing", "agent:coordinator")
        _, handoff, blocker = self.channel_posts()
        self.assertIn("Completed: Portion tests passed\nNext: Check the review screen (owner: user-reviewer)",
                      handoff["text"])
        self.assertIn("Preview data missing\nNext: Check the missing fixture (owner: developer)", blocker["text"])

    def test_a_block_with_no_next_step_or_no_owner_says_the_lead_triages_it_today(self):
        for blocked in ({}, {"action": "Fix the fixture"}, {"owner": "developer"}):
            self.d.task_work = lambda key, blocked=blocked: {"blocked": blocked}
            self.step("SV-45", "pipeline.blocked", "Preview data missing", "agent:coordinator")
            self.assertIn("Preview data missing\nNo next step or owner: the lead triages it today",
                          self.channel_posts()[-1]["text"])

    def test_the_blocked_post_uses_the_shared_triage_predicate(self):
        # CC-076 Codex round 1, finding 4: an open question, or a later handoff with next and owner, is not a triage case.
        from ccd.pipeline import Pipeline
        cases = [
            ({"blocked": {"at": 1}, "openQuestions": 1}, "Next: Jay's answer to the open question"),
            ({"blocked": {"at": 1}, "handoff": {"next": "Re-run CI", "owner": "developer", "at": 2}},
             "Next: Re-run CI (owner: developer)"),
            ({"blocked": {"at": 1}, "handoff": {"next": "Re-run CI", "at": 2}},
             "No next step or owner: the lead triages it today"),
            ({"blocked": {"at": 1}, "handoff": {"next": "Old", "owner": "lead", "at": 0}},
             "No next step or owner: the lead triages it today"),
        ]
        for work, expect in cases:
            self.d.task_work = lambda key, work=work: work
            self.step("SV-50", "pipeline.blocked", "stuck", "agent:coordinator")
            post = self.channel_posts()[-1]["text"]
            self.assertIn(expect, post)
            needed = Pipeline.triage_needed("BLOCKED", work.get("blocked"), work.get("handoff"),
                                            work.get("openQuestions", 0))
            self.assertEqual(needed, "No next step" in post)

    def test_user_check_says_what_was_tested(self):
        self.d.task_work = lambda key: {"userCheck": {"note": "Tried the export on 375px", "at": 1}}
        self.step("SV-47", "pipeline.user_checked", "user check passed", "agent:user-reviewer")
        post = self.channel_posts()[-1]
        self.assertIn("user check passed\nChecked: Tried the export on 375px", post["text"])
        self.assertIn("User reviewer", post["text"])                      # the seat label on the post

    def test_review_ready_posts_in_the_ticket_thread(self):
        self.step("SV-49", "pipeline.review_ready", "PR #9 at abc1234 has green checks and no review")
        root, ready = self.channel_posts()
        self.assertEqual((ready["thread"], ready["broadcast"]), (root["ts"], False))

    def test_milestones_also_show_in_the_channel_and_small_records_stay_out(self):
        self.step("SV-41", "pipeline.criteria", "criteria updated: 3 criteria", "agent:coordinator")
        self.step("SV-41", "pipeline.evidence", "evidence: screenshot", "agent:user-reviewer")
        self.assertEqual(self.channel_posts(), [])
        self.step("SV-41", "pipeline.merged", "merged: PR #12")
        root, merged = self.channel_posts()
        self.assertEqual((merged["thread"], merged["broadcast"], merged["as"]), (root["ts"], True, None))
        self.assertEqual(merged["text"], "merged: PR #12")                 # ccd's own step: the app's name

    def test_agent_text_is_escaped_and_a_client_project_gets_nothing(self):
        self.step("SV-42", "pipeline.blocked", "blocked: <!channel> <https://evil|Open>", "agent:implementer")
        text = self.channel_posts()[-1]["text"]
        self.assertNotIn("<!channel>", text)
        self.assertNotIn("<https://evil", text)
        before = len(self.slack.posts)
        self.step("GM-3", "pipeline.plan", "plan recorded", "agent:planner", project="gauzemate")
        self.assertEqual(len(self.slack.posts), before)

    def test_a_reply_in_the_tickets_thread_goes_to_the_lead_with_its_key(self):
        self.step("SV-43", "pipeline.gate_opened", "plan gate opened: risky")
        root = self.channel_posts()[0]
        r = self.reply("why risky?", root["ts"], channel="CSV")
        self.assertEqual(r["did"], "lead_nudged")
        self.assertEqual(self.d.delivered[-1][:4], ("samvision", "why risky?", "slack", "SV-43"))

    def test_a_reply_still_finds_its_ticket_after_the_root_was_pruned(self):
        self.step("SV-46", "pipeline.plan", "plan recorded", "agent:planner")
        root = self.channel_posts()[0]
        self.n._ids = FakeSlack().channels()
        self.n.threads.pop(f"CSV:{root['ts']}")              # a busy week pushed the root out of `threads`
        r = self.reply("is this still needed?", root["ts"], channel="CSV")
        self.assertEqual(r["did"], "lead_nudged")
        self.assertEqual(self.d.delivered[-1][:4], ("samvision", "is this still needed?", "slack", "SV-46"))

    def test_the_thread_survives_a_restart(self):
        self.step("SV-44", "pipeline.plan", "plan recorded", "agent:planner")
        root = self.channel_posts()[0]
        again = notify.Notifier(self.d, {"notify": {"slack": {"jay_member_id": JAY}}}, slack=self.slack,
                                clock=self.n.clock)
        run(again.on_event({"source": "tasks", "kind": "task.pipeline", "project": "samvision", "ref": "SV-44",
                            "text": "SV-44 technical review: APPROVE", "data": {"kind": "pipeline.plan_reviewed"}}))
        self.assertEqual(self.channel_posts()[-1]["thread"], root["ts"])

    def test_lead_replies_post_under_the_leads_name(self):
        ts = self.send(need("SV-45", "gate", "merge"))
        self.reply("why?", ts)

        class Chat:
            def get(self, mid):
                return {"id": 9, "conversation": "samvision", "replyTo": 7, "text": "It touches the importer."}
        self.d.chat = Chat()
        run(self.n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 9}}))
        self.assertEqual(self.slack.posts[-1]["text"], ":compass: *SamVision lead*: It touches the importer.")
        self.slack.scopes = {notify.CUSTOMIZE}
        run(self.n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 9}}))
        self.assertEqual((self.slack.posts[-1]["as"], self.slack.posts[-1]["text"]),
                         (("SamVision lead", ":compass:"), "It touches the importer."))


class LeadFiles(unittest.TestCase):
    """Files a lead sends in Messages (Jay, 2026-11-17: "Upload, chosen projects only"): uploaded for the projects
    Jay switched on, listed by name and size everywhere else, never uploaded for SamVision, the CTO or a client."""

    def setUp(self):
        from ccd import chat as chat_mod
        base = tempfile.mkdtemp()
        self.chat = chat_mod.Chat(os.path.join(base, "chat.db"), os.path.join(base, "files"), 1 << 20)
        self.addCleanup(self.chat.close)
        self.n, self.d, self.slack, _ = make(settings={"slack": True})
        self.d.chat = self.chat

    def lead_sends(self, conv, text, files=(("notes.md", b"# Notes\nThe importer is slow.\n"),)):
        async def chunks(data):
            yield data
        ids = [asyncio.run(self.chat.upload(conv, "lead", f"agent:lead-{conv}", name, chunks(data)))["id"]
               for name, data in files]
        msg = self.chat.add(conv, "lead", f"agent:lead-{conv}", text, via="cli", file_ids=ids)
        run(self.n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": msg["id"]}}))
        return msg

    def test_files_are_listed_by_name_and_size_until_jay_switches_the_project_on(self):
        self.lead_sends("commandcenter", "Here is the report.")
        post = self.slack.posts[-1]
        self.assertEqual(post["channel"], "CCC")
        self.assertEqual(post["text"].split("\n"), [
            ":compass: *Command Center lead*: Here is the report.", ":paperclip: notes.md · 30 bytes",
            "_In CommandCenter → Messages. To get Command Center's files here, switch it on in Settings → Slack and "
            "phone._"])
        self.assertEqual(self.slack.uploads, [])

    def test_a_switched_on_project_gets_each_file_in_the_thread_of_the_leads_words(self):
        self.n.update_settings({"slackFiles": ["commandcenter", "gyst"]})
        self.lead_sends("commandcenter", "Two files.", files=(("a.md", b"alpha"), ("b.txt", b"bravo")))
        post = self.slack.posts[-1]
        self.assertEqual(post["text"], ":compass: *Command Center lead*: Two files.")
        self.assertEqual([(u["channel"], u["thread"], u["name"], u["data"]) for u in self.slack.uploads],
                         [("CCC", post["ts"], "a.md", b"alpha"), ("CCC", post["ts"], "b.txt", b"bravo")])
        self.assertEqual([(t, kw["data"]["conversation"], kw["data"]["size"]) for k, t, kw in self.d.events
                          if k == "notify.file_uploaded"],
                         [("commandcenter: uploaded a.md to Slack", "commandcenter", 5),
                          ("commandcenter: uploaded b.txt to Slack", "commandcenter", 5)])
        self.lead_sends("gyst", "")                                       # a file and no words
        self.assertEqual(self.slack.posts[-1]["text"], ":compass: *GYST / LifeOps lead*: sent 1 file.")
        self.assertEqual(self.slack.uploads[-1]["thread"], self.slack.posts[-1]["ts"])

    def test_an_answer_in_a_slack_thread_brings_its_files_into_that_thread(self):
        self.n.update_settings({"slackFiles": ["commandcenter"]})
        jay = self.chat.add("commandcenter", "jay", "jay", "can you send the log?", via="slack")
        self.n.threads[f"msg:{jay['id']}"] = {"type": "origin", "channel": "DJAY", "ts": "42.0",
                                              "conversation": "commandcenter", "at": self.n.clock()}
        self.lead_sends("commandcenter", "Attached.")
        self.assertEqual((self.slack.posts[-1]["channel"], self.slack.posts[-1]["thread"]), ("DJAY", "42.0"))
        self.assertEqual((self.slack.uploads[-1]["channel"], self.slack.uploads[-1]["thread"]), ("DJAY", "42.0"))

    def test_samvision_the_cto_and_client_projects_never_upload(self):
        for bad in (["samvision"], ["cto"], ["gauzemate"], ["nope"], "commandcenter", [1]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.n.update_settings({"slackFiles": bad})
        self.assertNotIn("samvision", self.n.public()["slackFiles"]["choices"])
        self.n.settings["slackFiles"] = ["samvision", "cto", "commandcenter"]     # however it got there
        self.lead_sends("samvision", "The comps export.", files=(("12 Main St comps.md", b"comps"), ("b.md", b"b")))
        self.assertEqual(self.slack.posts[-1]["text"].split("\n")[1:], [
            "_:paperclip: 2 files in CommandCenter → Messages. SamVision files and their names never go to Slack._"])
        self.assertNotIn("Main St", json.dumps(self.slack.posts))            # a name can carry an address
        self.lead_sends("cto", "Cross-project notes.")
        self.assertIn("1 file in CommandCenter → Messages. The CTO's files and their names never go to Slack.",
                      self.slack.posts[-1]["text"])
        self.assertEqual(self.slack.uploads, [])

    def test_only_a_file_this_lead_sent_in_this_conversation_is_read_for_upload(self):
        async def chunks(data):
            yield data
        theirs = asyncio.run(self.chat.upload("samvision", "lead", "agent:lead-samvision", "comps.md", chunks(b"comps")))
        self.chat.add("samvision", "lead", "agent:lead-samvision", "comps", via="cli", file_ids=[theirs["id"]])
        jays = asyncio.run(self.chat.upload("commandcenter", "jay", "jay", "mine.md", chunks(b"mine")))
        self.chat.add("commandcenter", "jay", "jay", "mine", file_ids=[jays["id"]])
        unsent = asyncio.run(self.chat.upload("commandcenter", "lead", "agent:lead-commandcenter", "draft.md",
                                              chunks(b"draft")))
        for fid in (theirs["id"], jays["id"], unsent["id"]):
            with self.assertRaises(notify.SlackError):
                self.n._lead_file(fid, "commandcenter")

    def test_a_text_file_the_secret_filter_would_change_stays_here(self):
        self.n.update_settings({"slackFiles": ["commandcenter"]})
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVl"
        self.lead_sends("commandcenter", "The env.", files=(("env.md", f"TOKEN {jwt}\n".encode()), ("ok.md", b"fine")))
        self.assertEqual([u["name"] for u in self.slack.uploads], ["ok.md"])
        self.assertIn("_In CommandCenter → Messages: it looks like it holds a password, token or key._",
                      self.slack.posts[-1]["text"])
        self.assertNotIn(jwt, json.dumps(self.slack.posts))

    def test_a_client_projects_files_are_not_even_named(self):
        n, d, slack, _ = make(settings={"slack": True}, conf={"channels": {"gauzemate": "gauzemate"}})
        d.chat = self.chat
        n.settings["slackFiles"] = ["gauzemate"]
        self.n, self.slack = n, slack
        self.lead_sends("gauzemate", "Intake form.", files=(("patient-intake.md", b"secret"),))
        self.assertEqual(slack.posts[-1]["text"], ":compass: *GauzeMate lead*: replied. Client project: read it in "
                                                   "CommandCenter.")
        self.assertNotIn("patient-intake", json.dumps(slack.posts))
        self.assertEqual(slack.uploads, [])

    def test_a_file_that_does_not_upload_is_listed_with_the_reason(self):
        self.n.update_settings({"slackFiles": ["commandcenter"]})
        self.slack.upload_error = "files.getUploadURLExternal: missing_scope"
        self.lead_sends("commandcenter", "The log.")
        words, listed = self.slack.posts[-2:]
        self.assertEqual(listed["thread"], words["ts"])
        self.assertEqual(listed["text"].split("\n"), [
            ":paperclip: notes.md · 30 bytes",
            "_In CommandCenter → Messages: Slack has not granted the bot files:write yet "
            "(docs/runbooks/slack-and-ntfy.md)._"])
        self.assertIn("slack file", self.n.status["lastError"])
        self.assertNotIn("notify.file_uploaded", [k for k, _, _ in self.d.events])

    def test_the_bot_tokens_files_scope_shows_in_settings(self):
        self.assertIsNone(self.n.public()["slackFiles"]["scope"])
        self.slack.scopes = {"chat:write"}
        self.assertFalse(self.n.public()["slackFiles"]["scope"])
        self.slack.scopes = {"chat:write", notify.FILES_SCOPE}
        self.assertTrue(self.n.public()["slackFiles"]["scope"])
        self.assertEqual(self.n.public()["slackFiles"]["choices"], ["commandcenter", "gyst", "mfe"])

    def test_the_choice_survives_a_restart(self):
        self.n.update_settings({"slackFiles": ["mfe", "commandcenter", "mfe"]})
        again = notify.Notifier(self.d, {"notify": {}}, slack=FakeSlack())
        self.assertEqual(again.settings["slackFiles"], ["commandcenter", "mfe"])

    def test_sizes_read_as_people_say_them(self):
        self.assertEqual([notify.size_text(n) for n in (0, 820, 14 * 1024, int(3.2 * 1024 * 1024), None)],
                         ["0 bytes", "820 bytes", "14 KB", "3.2 MB", "0 bytes"])


class LeadRepliesWithoutReplyTo(unittest.TestCase):
    def test_an_unthreaded_reply_goes_under_jays_latest_slack_message_to_that_lead(self):
        n, d, slack, _ = make(settings={"slack": True})
        run(n.tick())
        d.needs_list = [need("SV-30", "gate", "merge")]
        run(n.tick())
        ts = slack.posts[-1]["ts"]
        run(n.on_slack({"event": {"type": "message", "user": JAY, "text": "why?", "channel": "DJAY", "ts": "51.0",
                                  "thread_ts": ts}}))

        class Chat:
            def get(self, mid):
                return {"id": 10, "conversation": "samvision", "text": "Because of the importer.", "replyTo": None}
        d.chat = Chat()
        run(n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 10}}))
        self.assertEqual((slack.posts[-1]["channel"], slack.posts[-1]["thread"]), ("DJAY", ts))
        d.chat = type("C", (), {"get": lambda self, mid: {"id": 11, "conversation": "gyst", "text": "hi", "replyTo": None}})()
        run(n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": 11}}))
        self.assertEqual((slack.posts[-1]["channel"], slack.posts[-1]["thread"]), ("CGY", None))


class RealChatShape(unittest.TestCase):
    def test_a_real_lead_reply_threads_back_under_its_slack_message(self):
        from ccd import chat as chat_mod
        base = tempfile.mkdtemp()
        store = chat_mod.Chat(os.path.join(base, "chat.db"), os.path.join(base, "files"), 4096)
        jay = store.add("samvision", "jay", "jay", "why?", via="slack")
        lead = store.add("samvision", "lead", "samvision", "Because of the importer.", reply_to=jay["id"])
        n, d, slack, _ = make(settings={"slack": True})
        d.chat = store
        n.threads[f"msg:{jay['id']}"] = {"type": "origin", "channel": "DJAY", "ts": "42.0", "conversation": "samvision",
                                         "at": n.clock()}
        run(n.on_event({"source": "chat", "kind": "chat.reply", "data": {"messageId": lead["id"]}}))
        self.assertEqual((slack.posts[-1]["channel"], slack.posts[-1]["thread"]), ("DJAY", "42.0"))


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
    """The daemon's own guard: whatever calls it, Slack closes only a plan or a Low-risk gate."""

    async def asyncSetUp(self):
        self.store = Store(os.path.join(tempfile.mkdtemp(), "ccd.db"))
        self.ts = TaskStore(":memory:", [{"key": "samvision", "name": "SamVision", "prefix": "SV"},
                                         {"key": "gauzemate", "name": "GauzeMate", "prefix": "GZ"}])
        self.d = Daemon(cfg(meter={"enabled": False}), self.store, None, tasks=self.ts)
        self.d.notifier = notify.Notifier(self.d, {"notify": {}}, slack=FakeSlack())

    async def test_merge_and_deploy_are_refused(self):
        t, _ = self.ts.create("samvision", "Valuation")
        for gate in ("merge", "deploy", "owner", "anything"):
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

    async def test_a_plan_is_approved_with_via_slack(self):
        t, _ = self.ts.create("samvision", "Valuation", needs_jay=True)
        self.d.pipeline.plan(t["key"], {"summary": "s", "risk": "high"}, "agent:planner")
        w = self.d.task_work(t["key"])
        self.assertEqual(w["gate"], "plan")
        r = await self.d.slack_confirm(t["key"], "plan", plan_hash=plan_digest(w["plan"]))
        self.assertIsNone(r["work"]["gate"])
        self.assertEqual(r["work"]["planState"], "accepted")
        (data,) = self.ts.db.execute("SELECT data FROM ticket_events WHERE kind='pipeline.gate_confirmed'").fetchone()
        self.assertEqual(json.loads(data).get("via"), "slack")

    async def test_a_plan_is_approved_only_as_the_dm_showed_it(self):
        t, _ = self.ts.create("samvision", "Valuation", needs_jay=True)
        self.d.pipeline.plan(t["key"], {"summary": "first", "risk": "high"}, "agent:planner")
        seen = plan_digest(self.d.task_work(t["key"])["plan"])
        with self.assertRaises(ActionError) as e:
            await self.d.slack_confirm(t["key"], "plan")                     # no hash: refused
        self.assertEqual(e.exception.status, 403)
        # Re-planned between the notifier's check and the approval: on this route the gate stays open.
        self.d.pipeline.plan(t["key"], {"summary": "second", "risk": "high"}, "agent:planner")
        self.assertEqual(self.d.task_work(t["key"])["gate"], "plan")
        with self.assertRaises(ActionError) as e:
            await self.d.slack_confirm(t["key"], "plan", plan_hash=seen)
        self.assertEqual(e.exception.status, 409)
        w = self.d.task_work(t["key"])
        self.assertEqual((w["gate"], w["plan"]["summary"]), ("plan", "second"))

    async def test_merges_and_deploys_need_everything_in_the_daemon_too(self):
        t, _ = self.ts.create("samvision", "Valuation")
        self.d.notifier.update_settings({"replyScope": "answers_low_risk"})
        with self.assertRaises(ActionError) as e:
            await self.d.slack_merge(t["key"], "a" * 40)
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(ActionError) as e:
            await self.d.slack_confirm(t["key"], "deploy")
        self.assertEqual(e.exception.status, 403)
        self.d.notifier.update_settings({"replyScope": "all"})
        with self.assertRaises(ActionError) as e:
            await self.d.slack_confirm(t["key"], "merge")              # a merge is never a bare gate approval
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(ActionError) as e:
            await self.d.slack_merge(t["key"], "a" * 40)               # Merge's own checks: nothing is ready
        self.assertEqual(e.exception.status, 409)
        with self.assertRaises(ActionError) as e:
            await self.d.act_merge("samvision", [{"key": t["key"], "head": "a" * 40}], actor="jay")
        self.assertEqual(e.exception.status, 403)                      # the API path still needs Developer Unlock

    async def test_a_deploy_from_slack_waits_for_its_plan_and_jays_second_reply(self):
        self.d.notifier.update_settings({"replyScope": "all"})
        t, _ = self.ts.create("samvision", "Valuation")
        k = t["key"]
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation")
        self.d.pipeline.deploy_request(k, "live", "valuation v2", "verifier pass", "agent:coordinator")
        r = await self.d.slack_confirm(k, "deploy")
        self.assertEqual(r["work"]["deploy"]["approvedBy"], "jay:slack")
        with self.assertRaises(TaskError):                             # approved from Slack: no pass before the go
            self.d.pipeline.deployed(k, "live", "pass", "health 200", "agent:coordinator")
        with self.assertRaises(ActionError):                           # no plan recorded yet
            await self.d.slack_deploy(k, "0" * 16)
        for unshowable in ("\n".join(f"{i}. step" for i in range(41)),                 # more than Slack shows whole
                           "1. restart\n-----BEGIN RSA PRIVATE KEY-----\n2. drop\n-----END RSA PRIVATE KEY-----",
                           "1. set token = abcdef123456",                                # the secret filter hides it
                           "1. restart \u202e2. drop",                                   # reads in another order
                           "1. restart web" + "".join(chr(0xE0000 + ord(c)) for c in "2. DROP TABLE users"),  # tags
                           "1. restart\u200b web", "1. restart web\ufe0f", "1. restart\u3164web",
                           "1. restart\rweb",
                           "1. restart web\u00a02. drop",                                # only plain spaces
                           "1. restart web" + " " * 20 + "2. drop",                      # pushed out of sight
                           "1. restart\n```\n~2. drop~"):                               # ends the code block
            with self.assertRaises(TaskError) as e:
                self.d.pipeline.deploy_plan(k, unshowable, "agent:coordinator")
            self.assertEqual(e.exception.status, 400)
        self.d.pipeline.deploy_plan(k, "1. migrate\n2. restart", "agent:coordinator")
        plan = self.d.task_work(k)["deploy"]["plan"]
        with self.assertRaises(ActionError):                           # not the plan Jay saw
            await self.d.slack_deploy(k, "f" * 16)
        r = await self.d.slack_deploy(k, plan_digest(plan))
        self.assertTrue(r["work"]["deploy"]["goAt"])
        self.assertFalse(r["delivered"])                               # no task session in this test
        with self.assertRaises(TaskError):                             # the plan is fixed once Jay said go
            self.d.pipeline.deploy_plan(k, "something else", "agent:coordinator")
        self.d.pipeline.deployed(k, "live", "pass", "health 200", "agent:coordinator")
        (data,) = self.ts.db.execute("SELECT data FROM ticket_events WHERE kind='pipeline.deploy_confirmed'").fetchone()
        self.assertEqual(json.loads(data).get("via"), "slack")

    async def test_a_deploy_approved_in_commandcenter_is_unchanged(self):
        t, _ = self.ts.create("samvision", "Valuation")
        k = t["key"]
        self.ts.update(k, {"status": "VERIFYING"}, "system:automation")
        self.d.pipeline.deploy_request(k, "live", "valuation v2", "verifier pass", "agent:coordinator")
        self.d.pipeline.confirm(k, "deploy", "jay", "gate")
        with self.assertRaises(TaskError) as e:                        # no Slack go for a CommandCenter approval
            self.d.pipeline.deploy_plan(k, "1. restart", "agent:coordinator")
        self.assertIn("approved in CommandCenter", e.exception.message)
        self.d.pipeline.deployed(k, "live", "pass", "health 200", "agent:coordinator")   # Jay confirmed in the pane

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
        t2, _ = self.ts.create("gauzemate", "Intake 2", needs_jay=True)
        self.d.pipeline.plan(t2["key"], {"summary": "s", "risk": "high"}, "agent:planner")
        seen = plan_digest(self.d.task_work(t2["key"])["plan"])
        with self.assertRaises(ActionError) as e:                     # refused as a client project, digest or not
            await self.d.slack_confirm(t2["key"], "plan", plan_hash=seen)
        self.assertIn("client projects", e.exception.message)
        self.assertEqual(self.d.task_work(t2["key"])["gate"], "plan")


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
