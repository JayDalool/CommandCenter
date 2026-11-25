"""Manitoba's permanent UTC−05 (IANA tzdata 2026e): ccd's local-time paths give the right instants on a Winnipeg host.

ccd stores epoch seconds. Some paths read the host's zone through the C library (nightshift.cutoff_after, the
"brief written today" check in model.py, records._ts), so these tests set TZ=America/Winnipeg. Others name
America/Winnipeg through zoneinfo (release windows, pipeline due dates, work mode, notify quiet hours); those are
pinned to absolute UTC instants below, because the existing tests for them build and compare in the same zone and
would pass on stale tz data (CC-054). A failure here on a correct ccd means the machine's tz database predates
2026e: it would read Winnipeg as UTC−06 from 2026-11-01 07:00 UTC and put every local time an hour early.
"""
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ccd import budgets, pipeline, records, release, workmode
from ccd.notify import in_quiet
from ccd.nightshift import cutoff_after

STALE = "this machine's tz database predates IANA 2026e (Manitoba's permanent UTC−05)"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


def _restore_tz(old):
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset (POSIX)")
class WinnipegHost(unittest.TestCase):
    def setUp(self):
        # addCleanup, not tearDown: the restore must run even when setUp or an assertion fails, or a stale-tz
        # failure here would leave TZ=America/Winnipeg set for every later test in the process (CC-054).
        self.addCleanup(_restore_tz, os.environ.get("TZ"))
        os.environ["TZ"] = "America/Winnipeg"
        time.tzset()

    def test_offsets_before_and_after_the_change(self):
        cases = [  # (UTC instant, Winnipeg offset in hours)
            ((2026, 1, 15, 18, 0), -6),    # historical winter: CST
            ((2026, 7, 15, 18, 0), -5),    # historical summer: CDT
            ((2026, 11, 1, 8, 0), -5),     # an hour after the old fall-back (07:00 UTC): no change
            ((2027, 1, 15, 18, 0), -5),    # first winter on permanent UTC−05
            ((2027, 3, 14, 12, 0), -5),    # the old spring-forward day: no change
            ((2027, 11, 7, 12, 0), -5),    # the old fall-back day: no change
        ]
        zone = ZoneInfo("America/Winnipeg")
        for parts, hours in cases:
            at = utc(*parts)
            with self.subTest(at=datetime.fromtimestamp(at, timezone.utc).isoformat()):
                self.assertEqual(time.localtime(at).tm_gmtoff, hours * 3600, STALE)    # the C library: what ccd uses
                self.assertEqual(datetime.fromtimestamp(at, zone).utcoffset(), timedelta(hours=hours), STALE)

    def test_the_night_shift_cutoff_is_07_00_local_across_the_old_dst_dates(self):
        cases = [  # (shift start, local 23:00 the night before), cutoff in UTC, shift length
            ((2026, 1, 15, 5, 0), (2026, 1, 15, 13, 0), 8),     # historical CST: 07:00 −06 = 13:00 UTC
            ((2026, 11, 1, 4, 0), (2026, 11, 1, 12, 0), 8),     # the change night: no extra hour
            ((2027, 3, 14, 4, 0), (2027, 3, 14, 12, 0), 8),     # no lost hour in March 2027
            ((2027, 11, 7, 4, 0), (2027, 11, 7, 12, 0), 8),     # no extra hour in November 2027
        ]
        for start, cut, hours in cases:
            with self.subTest(start=start):
                c = cutoff_after(utc(*start), "07:00")
                self.assertEqual(c, utc(*cut), STALE)
                self.assertEqual(c - utc(*start), hours * 3600)
                self.assertEqual(datetime.fromtimestamp(c).strftime("%H:%M"), "07:00")

    def test_local_midnight_rolls_the_date_at_05_00_utc_after_the_change(self):
        # 00:30 on 2 Nov 2026 in Winnipeg (−05). Old rules would read it as 23:30 on 1 Nov.
        at = utc(2026, 11, 2, 5, 30)
        self.assertEqual(datetime.fromtimestamp(at).date().isoformat(), "2026-11-02", STALE)   # model.py brief check
        self.assertEqual(records._ts(at), "2026-11-02 00:30", STALE)
        self.assertEqual(records._ts(utc(2026, 1, 15, 5, 30)), "2026-01-14 23:30")             # history keeps −06

    def test_utc_budget_periods_do_not_follow_the_host_zone(self):
        at = utc(2026, 11, 2, 5, 30)
        self.assertEqual(budgets.period_bounds(at, "day"), (utc(2026, 11, 2), utc(2026, 11, 3)))
        self.assertEqual(budgets.period_bounds(at, "month"), (utc(2026, 11, 1), utc(2026, 12, 1)))

    def test_zoneinfo_release_window_is_wednesday_22_00_at_minus_05(self):
        window = {"weekday": 3, "time": "22:00", "tz": "America/Winnipeg"}      # weekday 3 = Wednesday
        # Wed 4 Nov 2026 22:00 Winnipeg = Thu 5 Nov 03:00 UTC; stale data gives 04:00 UTC.
        self.assertEqual(release.window_start(window, datetime(2026, 11, 4).date()), utc(2026, 11, 5, 3), STALE)

    def test_zoneinfo_due_dates_end_at_23_59_at_minus_05(self):
        # small = 2 days: due 12 Nov 23:59 Winnipeg = 13 Nov 04:59 UTC.
        self.assertEqual(pipeline.due_by_size("small", utc(2026, 11, 10, 12)), utc(2026, 11, 13, 4, 59), STALE)
        self.assertEqual(pipeline.clean_due("2026-11-12", utc(2026, 11, 10, 12)), utc(2026, 11, 13, 4, 59), STALE)

    def test_zoneinfo_work_mode_day_rolls_at_05_00_utc(self):
        self.assertEqual(workmode._day(utc(2026, 11, 2, 4, 59)), "2026-11-01", STALE)
        self.assertEqual(workmode._day(utc(2026, 11, 2, 5, 0)), "2026-11-02", STALE)

    def test_zoneinfo_quiet_hours_are_22_00_to_07_00_at_minus_05(self):
        s = {"timezone": "America/Winnipeg", "quietStart": "22:00", "quietEnd": "07:00"}
        self.assertTrue(in_quiet(s, utc(2026, 11, 2, 3, 0)), STALE)         # 22:00 -05
        self.assertFalse(in_quiet(s, utc(2026, 11, 2, 2, 59)), STALE)       # 21:59 -05
        self.assertTrue(in_quiet(s, utc(2026, 11, 2, 11, 59)), STALE)       # 06:59 -05
        self.assertFalse(in_quiet(s, utc(2026, 11, 2, 12, 0)), STALE)       # 07:00 -05


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset (POSIX)")
class RestoresTheZone(unittest.TestCase):
    def test_a_failing_winnipeg_test_still_restores_the_host_zone(self):
        class Inner(WinnipegHost):
            def test_fails(self):
                self.fail("on purpose")
        self.addCleanup(_restore_tz, os.environ.get("TZ"))
        os.environ["TZ"] = "Asia/Kolkata"       # +05:30 all year: distinct from Winnipeg
        time.tzset()
        before = time.localtime(utc(2026, 7, 15)).tm_gmtoff
        result = unittest.TestResult()
        Inner("test_fails")(result)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(time.localtime(utc(2026, 7, 15)).tm_gmtoff, before)
        self.assertEqual(before, 19800)


if __name__ == "__main__":
    unittest.main()
