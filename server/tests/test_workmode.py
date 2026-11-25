"""Work mode (ccd/workmode.py): which tickets can move without Jay and in what order, when an idle lead is reminded,
the limits that stop it, Jay's switch over HTTP, and that a reminder is never typed over a draft."""
import datetime
import json
import os
import stat
import tempfile
import time
import unittest

from ccd import workmode
from ccd.workmode import WorkMode, movable, reminder_text, triage

from .test_api import JSON, ApiBase

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=workmode.TZ).timestamp()   # a Monday morning in Winnipeg


def describe_text(r):
    return workmode.describe(r, T0)


def row(key, stage="investigate", status="RESEARCHING", priority="NO_PRIORITY", due=None, number=1, holder=None,
        waiting=None, stale=False, type_="FEATURE", flags=(), reworked=False, urgent=False, triage_=False):
    return {"key": key, "status": status, "type": type_, "flags": list(flags), "priority": priority, "dueAt": due,
            "number": number, "stage": stage, "holder": holder, "waitingOn": waiting, "stale": stale,
            "reworked": reworked, "urgent": urgent, "needsTriage": triage_}


class Movable(unittest.TestCase):
    def test_only_tickets_the_lead_can_move_without_jay(self):
        rows = [row("CC-1"),
                row("CC-2", waiting="jay"),                             # an open question or a gate
                row("CC-3", status="BLOCKED"),
                row("CC-4", stage="merge", status="READY_TO_MERGE"),    # Jay merges
                row("CC-5", holder={"seat": "developer"}),              # somebody is in the seat
                row("CC-6", holder={"seat": "developer"}, stale=True),  # …but has recorded nothing for 48 h
                row("CC-7", stage="intake", status="INBOX", waiting="lead"),
                row("CC-8", stage="codeReview", status="IN_REVIEW", waiting="reviewer"),
                row("CC-9", stage="done", status="DONE"),
                row("CC-10", type_="OWNER_ACTION"),                      # Jay's own to-do
                row("CC-11", flags=["needs_legal"]),                     # a lawyer's question
                row("CC-12", flags=["needs_jay"]),                       # risky, but the investigation can go on
                row("CC-13", stage="intake", status="INBOX", flags=["needs_jay"]),     # the board: Needs Jay
                row("CC-14", stage="intake", status="PROPOSED", flags=["needs:jay"]),  # the label spelling
                row("CC-15", stage="intake", status="INBOX", flags=["needs-legal"])]
        # CC-7 is an intake row: new ideas wait while a started ticket can move (c17)
        self.assertEqual(sorted(r["key"] for r in movable(rows)), ["CC-1", "CC-12", "CC-6", "CC-8"])
        self.assertEqual([r["key"] for r in movable([r for r in rows if r["key"] in ("CC-7", "CC-13")])], ["CC-7"])

    def test_a_blocker_without_a_next_step_or_owner_is_a_triage_line_outside_the_three_shown(self):
        # c20: needs triage = BLOCKED with neither (action and owner) nor a later handoff; the line is outside SHOW.
        blocked = row("CC-1", status="BLOCKED", waiting="jay", triage_=True)
        named = row("CC-2", status="BLOCKED", waiting="jay")
        self.assertEqual(movable([blocked, named]), [])
        self.assertEqual([r["key"] for r in triage([blocked, named])], ["CC-1"])
        busy = movable([row(f"CC-{n}", number=n) for n in range(3, 9)])
        text = reminder_text("commandcenter", busy, now=T0, blocked=triage([blocked]))
        self.assertIn("Blocked with no next step or owner, triage today: CC-1.", text)
        self.assertNotIn("CC-6", text)                                   # three shown at most; triage is extra
        only = reminder_text("commandcenter", [], now=T0, blocked=triage([blocked]))
        self.assertNotIn("Next:", only)
        self.assertIn("triage today: CC-1.", only)

    def test_order_is_closest_to_done_then_ticket_number_and_priority_does_not_order(self):
        # c16 (Jay, 2026-11-24): code review, user check and release first; then a build fixing review findings,
        # other build, technical review, investigation; inside a rank the lower ticket number first.
        rows = [row("LOWREV", priority="LOW", stage="codeReview", status="IN_REVIEW", number=30),
                row("HIGHFIX", priority="HIGH", stage="build", status="IN_PROGRESS", number=20, reworked=True),
                row("URGBUILD", priority="URGENT", stage="build", status="IN_PROGRESS", number=10),
                row("URGINV", priority="URGENT", stage="investigate", number=5),
                row("USER", stage="userCheck", status="IN_REVIEW", number=31),
                row("REL", stage="release", status="VERIFYING", number=32),
                row("TECH", stage="techReview", number=8),
                row("OLDPLAIN", stage="build", status="IN_PROGRESS", number=9, due=T0 + 86400)]
        self.assertEqual([r["key"] for r in movable(rows)],
                         ["LOWREV", "USER", "REL", "HIGHFIX", "OLDPLAIN", "URGBUILD", "TECH", "URGINV"])
        same = [row("B", priority="LOW", number=2, due=T0 + 5 * 86400), row("A", priority="URGENT", number=3),
                row("C", priority="HIGH", number=1)]
        self.assertEqual([r["key"] for r in movable(same)], ["C", "B", "A"])         # by number whatever the priority
        self.assertIn("urgent", describe_text(same[1]))                               # …but still shown

    def test_an_open_urgent_exception_ranks_above_everything_and_intake_waits_in_line(self):
        rows = [row("REV", stage="codeReview", status="IN_REVIEW", number=1),
                row("URG", stage="investigate", number=9, urgent=True)]
        self.assertEqual([r["key"] for r in movable(rows)], ["URG", "REV"])
        # c17: an URGENT-priority intake row is left out while started work can move, named oldest first otherwise
        idea = [row("I2", stage="intake", status="INBOX", priority="URGENT", number=2),
                row("I1", stage="intake", status="INBOX", number=1)]
        self.assertEqual([r["key"] for r in movable(idea + [row("BUILD", stage="build", number=3)])], ["BUILD"])
        self.assertEqual([r["key"] for r in movable(idea)], ["I1", "I2"])

    def test_reminder_names_stage_priority_and_due_never_the_title(self):
        rows = movable([row("CC-053", priority="HIGH", due=T0 + 2 * 86400),
                        row("CC-054", stage="codeReview", status="IN_REVIEW", due=T0 - 86400),
                        row("CC-055"), row("CC-056")])
        text = reminder_text("commandcenter", rows, now=T0)
        self.assertTrue(text.startswith("Work mode (Command Center): commandcenter has tickets"))
        self.assertIn("Next: CC-054 (code review, overdue since Sun 15 Nov); then CC-053 (investigate, high, due "
                      "Wed 18 Nov); then CC-055 (investigate).", text)
        self.assertNotIn("CC-056", text)                                       # three at most
        midnight = datetime.datetime(2026, 11, 16, 0, 0, tzinfo=workmode.TZ).timestamp()   # today, stored at 00:00
        self.assertIn("CC-057 (investigate, due Mon 16 Nov)", reminder_text("commandcenter", [row("CC-057", due=midnight)],
                                                                          now=T0))
        self.assertIn("never merge or deploy", text)
        self.assertIn("fill an empty seat per FLOW.md", text)
        self.assertIn("pipeline_cli ask", text)
        text = reminder_text("commandcenter", movable([row("CC-060", stage="release", status="DEPLOYING")]), now=T0)
        self.assertIn("Next: CC-060 (release, verify only).", text)


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="work-"), "work-mode.json")
        self.w = WorkMode(self.path)
        self.w.set("commandcenter", True, now=T0)

    def tick(self, at, status="idle", activity=None, can_move=1):
        return self.w.decide("commandcenter", status, activity, can_move, now=at)

    def test_off_projects_are_never_reminded_and_switching_validates(self):
        self.assertIsNone(self.w.decide("samvision", "idle", None, 3, now=T0 + 3600))
        with self.assertRaises(workmode.WorkModeError):
            self.w.set("Not A Key", True)
        with self.assertRaises(workmode.WorkModeError):
            self.w.set("samvision", "yes")

    def test_idle_grace_then_one_reminder_every_ten_minutes(self):
        self.assertIsNone(self.tick(T0))                                        # idle from now
        self.assertIsNone(self.tick(T0 + workmode.IDLE_GRACE - 1))
        self.assertEqual(self.tick(T0 + workmode.IDLE_GRACE), "nudge")
        self.w.nudged("commandcenter", now=T0 + workmode.IDLE_GRACE)
        self.assertIsNone(self.tick(T0 + 200))                                   # idle again: a new grace
        self.assertIsNone(self.tick(T0 + 200 + workmode.IDLE_GRACE))             # …but within the 10-minute gap
        self.assertEqual(self.tick(T0 + workmode.IDLE_GRACE + workmode.NUDGE_GAP), "nudge")

    def test_nothing_while_the_lead_works_or_waits_or_nothing_can_move(self):
        self.tick(T0)
        self.assertIsNone(self.tick(T0 + 3600, status="working"))
        self.assertEqual(self.w.get("commandcenter")["why"], "lead working")
        self.assertIsNone(self.tick(T0 + 3600, status="blocked"))
        self.assertEqual(self.w.get("commandcenter")["why"], "lead waiting for Jay")
        self.assertIsNone(self.tick(T0 + 3600, status=None))
        self.assertEqual(self.w.get("commandcenter")["why"], "no lead")
        self.assertIsNone(self.tick(T0 + 3600, can_move=0))
        self.assertEqual(self.w.get("commandcenter")["why"], "nothing can move without Jay")

    def remind(self, at, activity=None):
        """Idle long enough, one reminder due at `at`: decide, and count it when sent."""
        self.tick(at - workmode.IDLE_GRACE, activity=activity)
        action = self.tick(at, activity=activity)
        if action == "nudge":
            self.w.nudged("commandcenter", now=at)
        return action

    def test_three_reminders_without_a_ticket_change_rest_two_hours_and_a_change_ends_the_rest(self):
        at = T0
        for _ in range(workmode.REST_AFTER):
            at += workmode.NUDGE_GAP + workmode.IDLE_GRACE
            self.assertEqual(self.remind(at), "nudge")
        at += workmode.NUDGE_GAP + workmode.IDLE_GRACE
        self.assertEqual(self.remind(at), "rest")
        st = self.w.public("commandcenter", now=at)
        self.assertEqual(st["restUntil"], at + workmode.REST_S)
        self.assertIsNone(self.remind(at + 3600))                                # still resting
        self.assertEqual(self.remind(at + workmode.REST_S + 1), "nudge")         # rest over: three more tries
        # A ticket moved after the last reminder: no rest is due, the count starts again.
        later = at + workmode.REST_S + 1
        for i in range(workmode.REST_AFTER + 1):
            later += workmode.NUDGE_GAP + workmode.IDLE_GRACE
            self.assertEqual(self.remind(later, activity=later - 60), "nudge", i)

    def test_a_ticket_change_ends_a_rest_early(self):
        at = T0
        for _ in range(workmode.REST_AFTER + 1):
            at += workmode.NUDGE_GAP + workmode.IDLE_GRACE
            last = self.remind(at)
        self.assertEqual(last, "rest")
        self.assertEqual(self.remind(at + 1800, activity=at + 600), "nudge")

    def test_day_limit(self):
        at = T0
        for i in range(workmode.DAY_MAX):                                       # a ticket moves every time
            at += workmode.NUDGE_GAP
            self.assertEqual(self.remind(at, activity=at - 1), "nudge", i)
        self.assertIsNone(self.remind(at + workmode.NUDGE_GAP, activity=at))
        self.assertIn("again tomorrow", self.w.get("commandcenter")["why"])
        self.w.set("commandcenter", False, now=at + 60)                         # off and on again: still today's 36
        self.assertEqual(self.w.public("commandcenter", now=at + 60)["remindersToday"], 0)        # off shows none
        self.w.set("commandcenter", True, now=at + 120)
        self.assertEqual(self.w.public("commandcenter", now=at + 120)["remindersToday"], workmode.DAY_MAX)
        self.assertIsNone(self.remind(at + 2 * workmode.NUDGE_GAP, activity=at + 2 * workmode.NUDGE_GAP - 1))
        self.assertIn("again tomorrow", self.w.get("commandcenter")["why"])
        tomorrow = datetime.datetime(2026, 11, 17, 9, 0, tzinfo=workmode.TZ).timestamp()
        self.assertEqual(self.remind(tomorrow, activity=tomorrow - 1), "nudge")
        self.assertEqual(self.w.public("commandcenter", now=tomorrow)["remindersToday"], 1)

    def test_state_survives_a_restart_and_the_file_is_private(self):
        self.remind(T0 + 3600)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        again = WorkMode(self.path)
        self.assertTrue(again.active("commandcenter"))
        self.assertEqual(again.get("commandcenter")["lastNudgeAt"], T0 + 3600)
        again.set("commandcenter", False)
        self.assertFalse(WorkMode(self.path).active("commandcenter"))
        self.assertEqual(WorkMode(self.path).public("commandcenter")["remindersToday"], 0)

    def test_a_held_back_reminder_is_not_counted_and_restarts_the_grace(self):
        self.tick(T0)
        self.assertEqual(self.tick(T0 + workmode.IDLE_GRACE), "nudge")
        self.w.note("commandcenter", "input line not empty or not recognised")
        self.assertIsNone(self.tick(T0 + workmode.IDLE_GRACE + 60))
        self.assertEqual(self.w.public("commandcenter", now=T0 + 600)["remindersToday"], 0)


class WorkModeApi(ApiBase):
    """Over HTTP with a fake herdr: Jay's switch, and what a tick types into the lead's pane."""
    DEV = "d" * 43
    EMPTY_PROMPT = "assistant text\n╭" + "─" * 20 + "╮\n│ > " + " " * 16 + "│\n╰" + "─" * 20 + "╯"
    DRAFT = "assistant text\n╭" + "─" * 20 + "╮\n│ > half a thought   │\n╰" + "─" * 20 + "╯"

    def equip(self, daemon):
        from ccd import security
        daemon.dev_gate = security.DeveloperGate(self.DEV)
        daemon.work = WorkMode(os.path.join(tempfile.mkdtemp(prefix="work-"), "work-mode.json"))

    def dev(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON)
        return dict(JSON, **{"x-ccd-developer": r.json()["session"]})

    def put(self, project, on, headers=None):
        return self.client.put(f"/api/work-mode/projects/{project}", content=json.dumps({"on": on}),
                               headers=headers or JSON)

    def prompts(self):
        return [p for m, p in self.fake.calls if m == "agent.prompt"]

    def idle_long_ago(self, project="samvision"):
        s = self.daemon.work.state.setdefault(project, {})
        s["idleSince"] = time.time() - 3600

    def tick(self):
        self.client.portal.call(self.daemon.work_tick)

    def test_every_project_starts_off_and_only_jay_unlocked_switches_it(self):
        st = self.get("/api/work-mode").json()
        self.assertTrue(st["projects"])
        self.assertFalse(any(p["on"] for p in st["projects"].values()))
        self.assertEqual(st["limits"]["dayMax"], workmode.DAY_MAX)
        self.assertEqual(self.put("samvision", True).status_code, 403)
        self.assertEqual(self.put("samvision", True, {**JSON, "x-ccd-actor": "agent:coordinator"}).status_code, 403)
        dev = self.dev()
        self.assertEqual(self.put("nope", True, dev).status_code, 404)
        self.assertEqual(self.put("samvision", "yes", dev).status_code, 400)
        r = self.put("samvision", True, dev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["projects"]["samvision"]["on"])
        self.assertFalse(r.json()["projects"]["gyst"]["on"])
        data = [e["data"] for e in self.get("/api/activity?limit=50").json()["events"] if e["kind"] == "action.work_mode"]
        self.assertIn({"kind": "work_mode_set", "on": True}, data)        # the store keeps "on" (EVENT_DATA_KEYS)
        self.assertFalse(self.put("samvision", False, dev).json()["projects"]["samvision"]["on"])

    def test_an_idle_lead_is_reminded_of_the_next_tickets_and_never_over_a_draft(self):
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        self.tickets.create("samvision", "other", number=57, status="INBOX", priority="HIGH")
        self.put("samvision", True, self.dev())
        self.assertEqual(self.get("/api/work-mode").json()["projects"]["samvision"]["next"], ["SV-056", "SV-057"])
        self.idle_long_ago()
        self.fake.tails["wE:p2"] = self.DRAFT
        self.tick()
        self.assertEqual(self.prompts(), [])                                     # a draft: nothing typed
        self.assertEqual(self.daemon.work.get("samvision")["why"], "input line not empty or not recognised")
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT
        self.idle_long_ago()
        self.tick()
        sent = self.prompts()
        self.assertEqual([p["target"] for p in sent], ["wE:p2"])                 # samvision's lead only
        self.assertIn("Next: SV-056 (intake); then SV-057 (intake, high).", sent[0]["text"])
        self.assertNotIn("feature", sent[0]["text"])                            # never a title
        self.assertEqual(self.get("/api/work-mode").json()["projects"]["samvision"]["remindersToday"], 1)
        nudges = [e["data"] for e in self.get("/api/activity?limit=50").json()["events"]
                  if e["kind"] == "action.work_mode" and e["data"].get("kind") == "work_mode_nudge"]
        self.assertEqual(nudges[0]["tickets"], ["SV-056", "SV-057"])        # keys only, never titles
        self.idle_long_ago()
        self.tick()
        self.assertEqual(len(self.prompts()), 1)                                 # the 10-minute gap

    def test_a_budget_hold_sends_nothing(self):
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        self.put("samvision", True, self.dev())
        self.daemon.chat_budget_check = lambda conv: [{"scope": "company", "key": "*", "holdReason": "limit"}]
        self.idle_long_ago()
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT
        self.tick()
        self.assertEqual(self.prompts(), [])
        self.assertEqual(self.daemon.work.get("samvision")["why"], "budget on hold")

    def test_a_lead_that_turns_busy_before_the_send_gets_nothing_and_nothing_is_counted(self):
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        self.put("samvision", True, self.dev())
        self.idle_long_ago()
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT
        self.fake.set_status("wE:p2", "working")      # herdr has it working; ccd's cached view still says idle
        self.tick()
        self.assertEqual(self.prompts(), [])
        self.assertNotEqual(self.daemon.work.get("samvision").get("why"), "lead working")   # decide() saw it idle
        st = self.get("/api/work-mode").json()["projects"]["samvision"]
        self.assertEqual((st["remindersToday"], st["lastReminderAt"]), (0, None))

    def test_paused_night_shift_or_nothing_to_move_sends_nothing(self):
        dev = self.dev()
        self.put("samvision", True, dev)
        self.idle_long_ago()
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT
        self.tick()
        self.assertEqual(self.prompts(), [])                                     # no open ticket
        self.assertEqual(self.daemon.work.get("samvision")["why"], "nothing can move without Jay")
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        from ccd import nightshift
        self.daemon.night = nightshift.NightShift(tempfile.mkdtemp(prefix="night-"))
        self.daemon.night.start("samvision")
        self.idle_long_ago()
        self.tick()
        self.assertEqual(self.prompts(), [])
        self.assertEqual(self.daemon.work.get("samvision")["why"], "night shift running")
        self.daemon.night.end("samvision", "test")
        self.put("gauzemate", True, dev)                                         # paused in the test registry
        self.daemon.work.state.setdefault("gauzemate", {})["idleSince"] = time.time() - 3600
        self.tick()
        self.assertEqual(self.daemon.work.get("gauzemate")["why"], "project paused")
        self.assertEqual(self.prompts(), [])                                     # nothing typed anywhere


class ReviewPrompts(WorkModeApi):
    """CC-076 (c19): green checks on an unreviewed PR tell a lead in work mode, once per head, through the one send path."""
    HEAD = "a" * 40

    def as_(self, actor):
        return dict(JSON, **{"x-ccd-actor": actor})

    def step(self, op, body, actor):
        return self.client.post(f"/api/tasks/SV-056/work/{op}", content=json.dumps(body), headers=self.as_(actor))

    def poll(self):
        self.daemon._auto_seen.clear()
        self.client.portal.call(self.daemon.poll_github_once)
        self.settle()

    def to_review(self, head=None, **pr_kw):
        from .helpers import pr
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        self.step("plan", {"plan": {"summary": "x", "tests": ["u"]}}, "agent:planner")
        r = self.step("start", {"branch": "SV-056-x", "worktree": "/srv/server/worktrees/sv/SV-056"}, "agent:coordinator")
        self.assertEqual(r.status_code, 200, r.text)
        self.push(head or self.HEAD, **pr_kw)

    def push(self, head, ci="SUCCESS", draft=False):
        from .helpers import pr
        self.gh.data["samvision"]["prs"] = [dict(pr(94, "SV-056: x", ci=ci), headRefName="SV-056-x", headRefOid=head,
                                                 isDraft=draft)]
        self.poll()

    def ready_events(self):
        return [e for e in self.get("/api/activity?limit=200").json()["events"]
                if e["kind"] == "task.pipeline" and e["data"].get("kind") == "pipeline.review_ready"]

    def lead_ready(self):
        self.put("samvision", True, self.dev())
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT

    def test_one_prompt_per_head_in_the_same_rederive_and_a_new_head_sends_again(self):
        self.lead_ready()
        self.to_review()
        [p] = self.prompts()
        self.assertEqual(p["target"], "wE:p2")
        self.assertIn("SV-056", p["text"])
        self.assertIn("green checks", p["text"])
        self.assertNotIn("feature", p["text"])                                   # never a title
        self.poll()
        self.assertEqual(len(self.prompts()), 1)                                 # the same head again: nothing
        self.assertEqual(len(self.ready_events()), 1)
        self.push("b" * 40)
        self.assertEqual(len(self.prompts()), 2)                                 # a new head sends again
        self.assertEqual(len(self.ready_events()), 2)

    def test_work_mode_off_records_the_event_and_types_nothing(self):
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT
        self.to_review()
        self.assertEqual(len(self.ready_events()), 1)
        self.assertEqual(self.prompts(), [])
        self.put("samvision", True, self.dev())                                   # switching on later still tells it
        self.client.portal.call(self.daemon.send_review_prompts)
        self.assertEqual(len(self.prompts()), 1)

    def test_a_reviewer_recorded_before_the_head_does_not_suppress_it_and_one_after_does(self):
        self.lead_ready()
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        self.step("plan", {"plan": {"summary": "x", "tests": ["u"]}}, "agent:planner")
        self.step("start", {"branch": "SV-056-x", "worktree": "/srv/server/worktrees/sv/SV-056"}, "agent:coordinator")
        self.step("role", {"role": "reviewer", "session": "old"}, "agent:reviewer")          # before this head
        self.push(self.HEAD)
        self.assertEqual(len(self.prompts()), 1)
        # A second head while the lead's input line holds a draft: pending, then a reviewer starts, then it is dropped.
        self.fake.tails["wE:p2"] = self.DRAFT
        self.push("b" * 40)
        self.assertEqual(len(self.prompts()), 1)
        time.sleep(0.01)
        self.step("role", {"role": "reviewer", "session": "new"}, "agent:reviewer")          # after this head
        self.fake.tails["wE:p2"] = self.EMPTY_PROMPT
        self.client.portal.call(self.daemon.send_review_prompts)
        self.assertEqual(len(self.prompts()), 1)

    def test_day_max_a_draft_pr_and_red_checks_type_nothing(self):
        self.lead_ready()
        self.daemon.work.state.setdefault("samvision", {}).update(day=workmode._day(time.time()),
                                                                  dayCount=workmode.DAY_MAX)
        self.to_review()
        self.assertEqual(self.prompts(), [])                                     # DAY_MAX reached
        self.assertEqual(len(self.ready_events()), 1)                            # the event and Slack post still stand
        self.daemon.work.state["samvision"]["dayCount"] = 0
        self.push("c" * 40, draft=True)
        self.push("d" * 40, ci="FAILURE")
        self.assertEqual(len(self.ready_events()), 1)                            # no event for a draft or red checks

    def test_no_ci_checks_is_said_as_such(self):
        self.lead_ready()
        self.to_review(ci=None)
        [p] = self.prompts()
        self.assertIn("no CI checks", p["text"])
        self.assertNotIn("green", p["text"])

    def test_a_review_prompt_and_a_work_tick_the_same_minute_type_one_text(self):
        self.tickets.create("samvision", "other", number=57, status="INBOX")
        self.lead_ready()
        self.to_review()
        self.idle_long_ago()
        self.tick()
        self.assertEqual(len(self.prompts()), 1)

    def test_a_herdr_error_is_logged_and_the_snapshot_still_publishes(self):
        from ccd import herdr as herdr_mod
        self.lead_ready()

        async def boom(*a, **kw):
            raise herdr_mod.HerdrError("down")
        self.daemon.herdr.prompt = boom
        self.to_review()                                                          # settle() returned: it published
        self.assertEqual(self.prompts(), [])
        self.assertEqual(len(self.ready_events()), 1)


if __name__ == "__main__":
    unittest.main()
