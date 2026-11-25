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
from ccd.workmode import WorkMode, movable, reminder_text

from .test_api import JSON, ApiBase

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=workmode.TZ).timestamp()   # a Monday morning in Winnipeg


def row(key, stage="investigate", status="RESEARCHING", priority="NO_PRIORITY", due=None, number=1, holder=None,
        waiting=None, stale=False, type_="FEATURE", flags=()):
    return {"key": key, "status": status, "type": type_, "flags": list(flags), "priority": priority, "dueAt": due,
            "number": number, "stage": stage, "holder": holder, "waitingOn": waiting, "stale": stale}


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
        self.assertEqual(sorted(r["key"] for r in movable(rows)), ["CC-1", "CC-12", "CC-6", "CC-7", "CC-8"])

    def test_full_build_lanes_hide_tickets_waiting_to_start_a_build(self):      # CC-090
        rows = [row("B1", stage="build", status="READY_TO_IMPLEMENT"),
                row("B2", stage="build", status="IN_PROGRESS", holder={"seat": "developer"}, stale=True),
                row("R1", stage="codeReview", status="IN_REVIEW"),
                row("I1")]
        self.assertEqual(sorted(r["key"] for r in movable(rows, build_full=True)), ["B2", "I1", "R1"])
        # a lane freed: the waiting build ticket is listed again
        self.assertEqual(sorted(r["key"] for r in movable(rows)), ["B1", "B2", "I1", "R1"])

    def test_order_is_priority_then_due_date_then_later_stage_then_oldest(self):
        rows = [row("A", priority="LOW", number=1),
                row("B", priority="HIGH", due=T0 + 5 * 86400, number=2),
                row("C", priority="HIGH", due=T0 + 86400, number=3),
                row("D", priority="HIGH", number=4),                                  # no due date: after dated ones
                row("E", priority="URGENT", number=9),
                row("F", number=5),                                                   # no priority: last
                row("G", priority="HIGH", due=T0 + 86400, stage="codeReview", status="IN_REVIEW", number=7),
                row("H", priority="HIGH", due=T0 + 86400, stage="codeReview", status="IN_REVIEW", number=6)]
        self.assertEqual([r["key"] for r in movable(rows)], ["E", "H", "G", "C", "B", "D", "A", "F"])

    def test_reminder_names_stage_priority_and_due_never_the_title(self):
        rows = movable([row("CC-053", priority="HIGH", due=T0 + 2 * 86400),
                        row("CC-054", stage="codeReview", status="IN_REVIEW", due=T0 - 86400),
                        row("CC-055"), row("CC-056")])
        text = reminder_text("commandcenter", rows, now=T0)
        self.assertTrue(text.startswith("Work mode (Command Center): commandcenter has tickets"))
        self.assertIn("Next: CC-053 (investigate, high, due Wed 18 Nov); then CC-054 (code review, overdue since "
                      "Sun 15 Nov); then CC-055 (investigate).", text)
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

    def test_work_next_uses_pipelines_own_lane_count(self):      # CC-090
        pl = self.daemon.pipeline
        rows = [row("SV-1", stage="build", status="READY_TO_IMPLEMENT"), row("SV-2", stage="codeReview", status="IN_REVIEW")]
        self.daemon.work_rows = lambda project: rows
        pl.lanes = lambda project: pl.lane_limit(project)            # every lane taken
        self.assertEqual([r["key"] for r in self.daemon.work_next("samvision")], ["SV-2"])
        pl.lanes = lambda project: pl.lane_limit(project) - 1        # one frees
        self.assertEqual(sorted(r["key"] for r in self.daemon.work_next("samvision")), ["SV-1", "SV-2"])

    def test_an_idle_lead_is_reminded_of_the_next_tickets_and_never_over_a_draft(self):
        self.tickets.create("samvision", "feature", number=56, status="INBOX")
        self.tickets.create("samvision", "other", number=57, status="INBOX", priority="HIGH")
        self.put("samvision", True, self.dev())
        self.assertEqual(self.get("/api/work-mode").json()["projects"]["samvision"]["next"], ["SV-057", "SV-056"])
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
        self.assertIn("Next: SV-057 (intake, high); then SV-056 (intake).", sent[0]["text"])
        self.assertNotIn("feature", sent[0]["text"])                            # never a title
        self.assertEqual(self.get("/api/work-mode").json()["projects"]["samvision"]["remindersToday"], 1)
        nudges = [e["data"] for e in self.get("/api/activity?limit=50").json()["events"]
                  if e["kind"] == "action.work_mode" and e["data"].get("kind") == "work_mode_nudge"]
        self.assertEqual(nudges[0]["tickets"], ["SV-057", "SV-056"])        # keys only, never titles
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


if __name__ == "__main__":
    unittest.main()
