"""The night-shift supervisor (ccd/nightshift.py): reminders from facts only, and when a shift ends."""
import os
import tempfile
import unittest

from ccd import nightshift
from ccd.nightshift import IDLE_GRACE, MAX_QUIET, NUDGE_GAP, NightShift


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="night-")
        self.ns = NightShift(self.dir)
        self.t0 = 1_000_000.0
        self.ns.start("samvision", now=self.t0)

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
        self.assertEqual(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE), "nudge")
        self.ns.decide("samvision", "working", now=t + IDLE_GRACE + 60)               # it went back to work
        self.ns.decide("samvision", "idle", now=t + IDLE_GRACE + 120)
        self.assertIsNone(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE + 120 + IDLE_GRACE))  # gap not over
        self.assertEqual(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE + NUDGE_GAP + 1), "nudge")
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
            now = t + i * 60
            a = self.ns.decide("samvision", "idle", now=now)
            if a == "nudge":
                nudges += 1
            if a and a.startswith("end:"):
                break
        self.assertEqual(a, "end:no progress")
        self.assertEqual(nudges, MAX_QUIET)
        self.assertIn("no progress", self.ns.get("samvision")["endReason"])

    def test_ticket_activity_counts_as_progress(self):
        t = self.t0
        self.ns.decide("samvision", "idle", now=t)
        self.assertEqual(self.ns.decide("samvision", "idle", now=t + IDLE_GRACE), "nudge")
        for k in range(1, 8):           # a ticket changes after every reminder: never "no progress"
            now = t + IDLE_GRACE + k * (NUDGE_GAP + 1)
            self.ns.decide("samvision", "idle", activity_at=now - 30, now=now - IDLE_GRACE - 1)
            self.assertEqual(self.ns.decide("samvision", "idle", activity_at=now - 30, now=now), "nudge")
        self.assertTrue(self.ns.active("samvision"))

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

    def test_the_reminder_is_one_fixed_sentence(self):
        text = nightshift.NUDGE_TEXT.format(project="samvision")
        self.assertIn("/night-shift", text)
        self.assertIn("Status: complete", text)


if __name__ == "__main__":
    unittest.main()


class NoBurn(unittest.TestCase):
    def test_working_briefly_after_each_reminder_is_not_progress(self):
        # The leak this guards: a reminder makes Claude read its tasks (working), then idle again. Without a
        # report rewrite or a ticket change that is no progress, so the shift ends after MAX_QUIET reminders.
        ns = NightShift(tempfile.mkdtemp(prefix="night-"))
        t = 1_000_000.0
        ns.start("gyst", now=t)
        nudges, a = 0, None
        for i in range(200):
            now = t + i * 60
            a = ns.decide("gyst", "working" if i % 11 == 1 else "idle", now=now)
            nudges += a == "nudge"
            if a and a.startswith("end:"):
                break
        self.assertEqual(a, "end:no progress")
        self.assertEqual(nudges, MAX_QUIET)
