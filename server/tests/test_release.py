"""Live or not live, and release day (ccd/release.py; the flow contract §5)."""
import datetime
import json
import os
import tempfile
import unittest
import zoneinfo

from unittest import mock

from ccd import pipeline, release
from ccd.pipeline import Pipeline
from ccd.release import Release, ReleaseError
from ccd.tasks import TaskError, TaskStore

WPG = zoneinfo.ZoneInfo("America/Winnipeg")
W = dict(release.DEFAULT_WINDOW)
HEAD = "abcdef1234567890abcdef1234567890abcdef12"


def at(y, m, d, hh=0, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=WPG).timestamp()


class Window(unittest.TestCase):
    # 2026-11-18 is a Wednesday.
    def test_merged_before_noon_on_release_day_goes_that_night(self):
        self.assertEqual(release.slot_for(W, at(2026, 11, 18, 11, 59)), (at(2026, 11, 18, 22), at(2026, 11, 18, 12)))

    def test_merged_after_noon_waits_a_week(self):
        self.assertEqual(release.slot_for(W, at(2026, 11, 18, 12, 1))[0], at(2026, 11, 25, 22))

    def test_merged_earlier_in_the_week(self):
        self.assertEqual(release.slot_for(W, at(2026, 11, 14, 9))[0], at(2026, 11, 18, 22))

    def test_the_next_window_survives_a_clock_change(self):
        # Winnipeg moves to standard time on 2026-11-01: the window stays at 22:00 local.
        start, _ = release.next_window(W, at(2026, 10, 29, 23, 59) + 3 * 3600)
        self.assertEqual(datetime.datetime.fromtimestamp(start, WPG).strftime("%a %H:%M"), "Wed 22:00")
        self.assertEqual(start, at(2026, 11, 4, 22))

    def test_a_running_window_is_still_next(self):
        self.assertEqual(release.next_window(W, at(2026, 11, 18, 23))[0], at(2026, 11, 18, 22))


class Settings(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="ccd-release-"), "release.json")

    def test_defaults_persistence_and_validation(self):
        r = Release(self.path)
        self.assertEqual((r.window, r.live("samvision")), (W, False))
        r.set_live("samvision", True)
        r.set_window(2, "17:00")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        r2 = Release(self.path)
        self.assertEqual((r2.live("samvision"), r2.window["weekday"], r2.window["time"]), (True, 2, "17:00"))
        for bad in ((7, "22:00"), (3, "24:00"), (True, "22:00"), (3, "9pm")):
            with self.assertRaises(ReleaseError):
                r.set_window(*bad)
        with self.assertRaises(ReleaseError):
            r.set_live("samvision", "yes")
        pub = r2.public(["samvision", "gyst"], at(2026, 11, 14))
        self.assertEqual(pub["projects"], {"samvision": {"live": True}, "gyst": {"live": False}})
        self.assertEqual(pub["window"]["next"], int(at(2026, 11, 17, 17)))

    def test_a_damaged_file_reads_as_the_defaults(self):
        with open(self.path, "w") as f:
            f.write("{nope")
        self.assertEqual(Release(self.path).window, W)
        with open(self.path, "w") as f:
            json.dump({"window": {"weekday": 9, "time": "x"}, "live": {"samvision": "yes"}}, f)
        r = Release(self.path)
        self.assertEqual((r.window, r.live("samvision")), (W, False))

    def test_hold(self):
        r = Release(self.path)
        merged = at(2026, 11, 16, 10)
        self.assertIsNone(r.hold("samvision", merged, at(2026, 11, 16, 11)))          # not live: no window
        r.set_live("samvision", True)
        self.assertEqual(r.hold("samvision", merged, at(2026, 11, 16, 11)), at(2026, 11, 18, 22))
        self.assertIsNone(r.hold("samvision", merged, at(2026, 11, 18, 22, 30)))      # in the window
        self.assertEqual(r.hold("samvision", merged, at(2026, 11, 19, 1)), at(2026, 11, 25, 22))   # missed it


class InThePipeline(unittest.TestCase):
    PROJECTS = [{"key": "samvision", "name": "SamVision", "prefix": "SV"}]

    def setUp(self):
        self.ts = TaskStore(":memory:", self.PROJECTS)
        self.pl = Pipeline(self.ts)
        self.pl.releases = Release(os.path.join(tempfile.mkdtemp(prefix="ccd-release-"), "release.json"))
        self.pl.releases.set_live("samvision", True)
        p = mock.patch.object(pipeline, "_now", return_value=at(2026, 11, 16, 10))     # a Monday morning
        p.start()
        self.addCleanup(p.stop)

    def verifying(self, size):
        k = self.ts.create("samvision", "x", description="why")[0]["key"]
        self.pl.intake(k, size, ["works"], "jay")
        self.ts.update(k, {"status": "VERIFYING"}, "jay")
        self.pl.merged(k, "JayDalool/SamVisionAI#1", "f" * 40)
        return k

    def test_a_live_deploy_waits_for_the_window(self):
        k = self.verifying("small")
        self.pl.deploy_request(k, "live", "the fix", "ok", "agent:coordinator")
        d = self.pl.work(k)["deploy"]
        self.assertTrue(d["heldUntil"])
        self.pl.confirm(k, "deploy", "jay")
        with self.assertRaises(TaskError) as e:
            self.pl.deployed(k, "live", "pass", "health ok", "agent:coordinator")
        self.assertIn("release window", e.exception.message)
        with self.assertRaises(TaskError):            # urgent is only for risky tickets
            k2 = self.verifying("small")
            self.pl.deploy_request(k2, "live", "x", "ok", "agent:coordinator")
            self.pl.confirm(k2, "deploy", "jay", urgent=True)

    def test_jay_approves_a_risky_deploy_as_urgent(self):
        k = self.verifying("risky")
        self.pl.deploy_request(k, "live", "the fix", "ok", "agent:coordinator")
        self.pl.confirm(k, "deploy", "jay", urgent=True)
        self.assertTrue(self.pl.work(k)["deploy"]["urgent"])
        self.pl.deployed(k, "live", "pass", "health ok", "agent:coordinator")
        self.assertEqual(self.pl.work(k)["deploy"]["result"], "pass")

    def test_a_deploy_with_no_merge_record_goes_in_an_open_window(self):
        r = self.pl.releases
        self.assertIsNone(r.hold("samvision", None, at(2026, 11, 18, 22, 30)))
        self.assertEqual(r.hold("samvision", None, at(2026, 11, 18, 21)), at(2026, 11, 18, 22))

    def test_urgent_on_a_needs_deploy_gate_carries_into_the_deploy(self):
        k = self.ts.create("samvision", "x", description="why", labels=["security"], needs_deploy=True)[0]["key"]
        self.ts.update(k, {"status": "VERIFYING"}, "jay")          # risky by policy, never sized
        self.pl.verify(k, "pass", "ok", "agent:verifier")
        self.assertEqual(self.pl.work(k)["gate"], "deploy")
        self.pl.confirm(k, "deploy", "jay", urgent=True)
        self.assertTrue(self.pl.work(k)["deploy"]["urgent"])
        self.pl.deployed(k, "live", "pass", "health ok", "agent:coordinator")

    def test_a_failed_deploy_is_recorded_even_when_held(self):
        k = self.verifying("small")
        self.pl.deploy_request(k, "live", "the fix", "ok", "agent:coordinator")
        self.pl.confirm(k, "deploy", "jay")
        self.assertTrue(self.pl.work(k)["deploy"]["heldUntil"])
        t, _, _ = self.pl.deployed(k, "live", "fail", "it went out early and broke", "agent:coordinator")
        self.assertEqual(t["status"], "BLOCKED")

    def test_the_cutoff_shown_is_still_ahead(self):
        pub = self.pl.releases.public(["samvision"], at(2026, 11, 18, 15))
        self.assertEqual((pub["window"]["next"], pub["cutoff"]), (int(at(2026, 11, 18, 22)), int(at(2026, 11, 25, 12))))

    def test_a_project_that_is_not_live_deploys_when_approved(self):
        self.pl.releases.set_live("samvision", False)
        k = self.verifying("small")
        self.pl.deploy_request(k, "live", "the fix", "ok", "agent:coordinator")
        self.assertIsNone(self.pl.work(k)["deploy"].get("heldUntil"))
        self.pl.confirm(k, "deploy", "jay")
        self.pl.deployed(k, "live", "pass", "health ok", "agent:coordinator")


if __name__ == "__main__":
    unittest.main()
