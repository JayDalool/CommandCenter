"""Manitoba's permanent UTC−05 (IANA tzdata 2026e): ccd's local-time paths give the right instants on a Winnipeg host.

ccd stores epoch seconds and works in UTC everywhere except three host-local paths: the night-shift morning cutoff
(nightshift.cutoff_after), the "brief written today" check (model.py) and the time stamps in task records
(records._ts). They read the host's time zone through the C library, so these tests set TZ=America/Winnipeg and
check the table from the Manitoba change. A failure here on a correct ccd means the machine's tz database predates
2026e: it would read Winnipeg as UTC−06 from 2026-11-01 07:00 UTC and put every local time an hour early.
"""
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ccd import budgets, records
from ccd.nightshift import cutoff_after

STALE = "this machine's tz database predates IANA 2026e (Manitoba's permanent UTC−05)"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset (POSIX)")
class WinnipegHost(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Winnipeg"
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
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


if __name__ == "__main__":
    unittest.main()
