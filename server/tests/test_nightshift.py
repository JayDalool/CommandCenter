"""The night-shift supervisor (ccd/nightshift.py): reminders from facts only, and when a shift ends."""
import os
import tempfile
from datetime import datetime
import unittest

from ccd import nightshift
from ccd.nightshift import IDLE_GRACE, MAX_NUDGES, MAX_QUIET, NUDGE_GAP, NightShift, cutoff_after


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="night-")
        self.ns = NightShift(self.dir, cutoff="07:00")
        # 22:00 local on a fixed day: the cutoff is 07:00 the next morning, nine hours on
        self.t0 = datetime(2026, 10, 8, 22, 0).timestamp()
        self.ns.start("samvision", now=self.t0)

    def send(self, status, now, activity_at=None):
        """One supervisor tick plus the delivery the daemon does: a nudge counts once it is delivered."""
        a = self.ns.decide("samvision", status, activity_at=activity_at, now=now)
        if a == "nudge":
            self.ns.nudged("samvision", now=now)
        return a

    def report(self, status, mtime):
        d = os.path.join(self.dir, "samvision")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "2026-10-09.md")
        with open(p, "w") as f:
            f.write(f"Status: {status}\n\n1. Ready to deploy\n- SV-080 PR #130 SAFE\n")
        os.utime(p, (mtime, mtime))

    def test_working_or_blocked_never_gets_a_reminder(self):
        for i in range(30):
            self.assertIsNone(self.ns.decide("samvision", "working", now=self.t0 + i * 60))
            self.assertIsNone(self.ns.decide("samvision", "blocked", now=self.t0 + 2000 + i * 60))
        self.assertTrue(self.ns.active("samvision"))

    def test_an_idle_coordinator_is_reminded_after_the_grace_and_not_more_often_than_the_gap(self):
        t = self.t0
        self.assertIsNone(self.ns.decide("samvision", "idle", now=t))                 # idle starts now
        self.assertIsNone(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE - 1))
        self.assertEqual(self.send("idle", t + IDLE_GRACE), "nudge")
        self.ns.decide("samvision", "working", now=t + IDLE_GRACE + 60)               # it went back to work
        self.ns.decide("samvision", "idle", now=t + IDLE_GRACE + 120)
        self.assertIsNone(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE + 120 + IDLE_GRACE))  # gap not over
        self.assertEqual(self.send("idle", t + IDLE_GRACE + NUDGE_GAP + 1), "nudge")
        self.assertEqual(self.ns.get("samvision")["nudges"], 2)

    def test_a_complete_report_ends_the_shift(self):
        self.report("working", self.t0 + 10)
        self.assertIsNone(self.ns.decide("samvision", "idle", now=self.t0 + 20))
        self.report("complete", self.t0 + 30)
        self.assertEqual(self.ns.decide("samvision", "idle", now=self.t0 + 40), "end:complete")
        self.assertFalse(self.ns.active("samvision"))
        self.assertIsNone(self.ns.decide("samvision", "idle", now=self.t0 + 5000))

    def test_an_old_complete_report_from_last_night_does_not_end_tonights_shift(self):
        self.report("complete", self.t0 - 86400)
        self.assertIsNone(self.ns.decide("samvision", "idle", now=self.t0 + 10))
        self.assertTrue(self.ns.active("samvision"))

    def test_reminders_that_change_nothing_end_the_shift(self):
        t = self.t0
        nudges = 0
        for i in range(40):
            a = self.send("idle", t + i * 60)
            nudges += a == "nudge"
            if a and a.startswith("end:"):
                break
        self.assertEqual(a, "end:no progress")
        self.assertEqual(nudges, MAX_QUIET)
        self.assertIn("no progress", self.ns.get("samvision")["endReason"])

    def test_ticket_activity_counts_as_progress_but_the_reminder_limit_still_stops_it(self):
        t = self.t0
        self.send("idle", t)
        self.assertEqual(self.send("idle", t + IDLE_GRACE), "nudge")
        nudges, a = 1, None
        for k in range(1, 12):          # a ticket changes after every reminder: never "no progress"
            now = t + IDLE_GRACE + k * (NUDGE_GAP + 1)
            self.send("idle", now - IDLE_GRACE - 1, activity_at=now - 30)
            a = self.send("idle", now, activity_at=now - 30)
            if a != "nudge":
                break
            nudges += 1
        self.assertEqual(nudges, MAX_NUDGES)
        self.assertEqual(a, "end:reminder limit")
        self.assertFalse(self.ns.active("samvision"))

    def test_a_coordinator_that_works_after_every_reminder_still_stops_at_the_cap(self):
        """Seen working is not progress: with nothing changing it runs out after MAX_QUIET reminders; and even
        when it does touch a ticket each time, MAX_NUDGES is the hard stop."""
        for touches in (False, True):
            ns = NightShift(tempfile.mkdtemp(prefix="night-"), cutoff="07:00")
            ns.start("samvision", now=self.t0)
            sent, now, last = 0, self.t0, None
            for _ in range(200):
                now += 60
                act = now - 5 if touches else None
                a = ns.decide("samvision", "idle", activity_at=act, now=now)
                if a == "nudge":
                    ns.nudged("samvision", now=now)
                    sent += 1
                    for _ in range(3):      # then it works for a few minutes
                        now += 60
                        self.assertIsNone(ns.decide("samvision", "working", activity_at=now - 5 if touches else None, now=now))
                elif a:
                    last = a
                    break
            self.assertFalse(ns.active("samvision"))
            self.assertEqual((sent, last), (MAX_NUDGES, "end:reminder limit") if touches else (MAX_QUIET, "end:no progress"))

    def test_the_morning_cutoff_ends_the_shift_even_while_the_coordinator_works(self):
        cut = cutoff_after(self.t0, "07:00")
        self.assertEqual(datetime.fromtimestamp(cut), datetime(2026, 10, 9, 7, 0))
        self.assertIsNone(self.ns.decide("samvision", "working", now=cut - 1))
        self.assertEqual(self.ns.decide("samvision", "working", now=cut), "end:morning cutoff")
        self.assertEqual(self.ns.get("samvision")["endReason"], "morning cutoff")
        self.assertIsNone(self.ns.decide("samvision", "idle", now=cut + 3600))
        # a shift begun at 03:00 ends the same morning; the cutoff is configurable and a bad value falls back
        self.assertEqual(datetime.fromtimestamp(cutoff_after(datetime(2026, 10, 9, 3, 0).timestamp(), "07:00")),
                         datetime(2026, 10, 9, 7, 0))
        self.assertEqual(datetime.fromtimestamp(cutoff_after(self.t0, "05:30")), datetime(2026, 10, 9, 5, 30))
        self.assertEqual(datetime.fromtimestamp(cutoff_after(self.t0, "nonsense")), datetime(2026, 10, 9, 7, 0))

    def test_an_idle_coordinator_is_not_reminded_after_the_cutoff(self):
        cut = cutoff_after(self.t0, "07:00")
        self.ns.decide("samvision", "idle", now=cut - 1000)
        self.assertEqual(self.ns.decide("samvision", "idle", now=cut + 5), "end:morning cutoff")
        self.assertEqual(self.ns.get("samvision")["nudges"], 0)

    def test_a_reminder_that_was_not_delivered_is_not_counted(self):
        t = self.t0
        self.ns.decide("samvision", "idle", now=t)
        for i in range(5):              # due again and again; every delivery failed or found Claude busy
            self.assertEqual(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE + i * 60), "nudge")
        s = self.ns.get("samvision")
        self.assertEqual((s["nudges"], s["lastNudgeAt"], s["quiet"]), (0, None, 0))
        self.ns.nudged("samvision", now=t + 600)
        self.assertEqual(self.ns.get("samvision")["nudges"], 1)

    def test_state_survives_a_restart_and_reports_are_read_safely(self):
        self.report("working", self.t0 + 5)
        again = NightShift(self.dir)
        self.assertTrue(again.active("samvision"))
        rep = again.report("samvision")
        self.assertEqual((rep["status"], rep["name"]), ("working", "2026-10-09.md"))
        self.assertIsNone(again.report("../etc"))
        self.assertIsNone(again.report("gyst"))
        self.assertTrue(again.end("samvision", "ended by Jay"))
        self.assertFalse(again.end("samvision", "twice"))

    def test_the_reminder_is_true_to_whether_a_report_exists(self):
        none = self.ns.nudge_text("samvision")
        self.assertIn("no morning report", none)
        self.assertNotIn("still says", none)
        self.assertIn("Status: working", none)
        self.report("complete", self.t0 - 86400)                  # last night's report is not this shift's
        self.assertIn("no morning report", self.ns.nudge_text("samvision"))
        self.report("working", self.t0 + 10)
        text = self.ns.nudge_text("samvision")
        self.assertIn("still says Status: working", text)
        self.assertIn("/night-shift", text)
        self.assertIn("Status: complete", text)


if __name__ == "__main__":
    unittest.main()
