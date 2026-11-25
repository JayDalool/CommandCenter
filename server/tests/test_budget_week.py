"""CC-064 (a): the weekly budget, its per-app shares and the 50/80/95/100 alerts (ccd/budgets.py, daemon.budget_tick).
Test data is synthetic: made-up token counts and dollar amounts, no real usage."""
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from ccd import budgets, security, tasks
from ccd import chat as chat_mod

from .test_api import ApiBase, JSON
from .test_notify import JAY, make, run

WIN = ZoneInfo("America/Winnipeg")
APPS = ["samvision", "gyst", "mfe", "gauzemate", "commandcenter"]


def at(y, mo, d, h=0, mi=0, tz=WIN):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=tz).timestamp()


def settings(**over):
    shares = {a: 0 for a in APPS}
    shares.update(samvision=50, gyst=30, mfe=20)
    return budgets.clean_settings(dict({"weekUsd": "100.00", "shares": shares}, **over), APPS)


def use(db, when, usd=None, project="samvision", source="claude", tokens=0, ref=[0]):
    """One synthetic usage row. usd None = no known price (counted at the fallback price)."""
    ref[0] += 1
    db.execute("INSERT INTO usage_records (at, source, ref, project, model, input, output, cost_usd) "
               "VALUES (?,?,?,?,?,?,?,?)", (when, source, f"r{ref[0]}", project, "m", tokens, 0, usd))


class Period(unittest.TestCase):
    def test_the_week_starts_on_jays_reset_in_local_time_not_at_utc_midnight(self):
        week = {"weekday": 1, "hour": 0, "tz": "America/Winnipeg"}       # Monday 00:00 Winnipeg
        start, end = budgets.week_bounds(at(2026, 11, 25, 12), week)       # a Wednesday
        self.assertEqual(start, at(2026, 11, 23))
        self.assertEqual(end, at(2026, 11, 30))
        self.assertEqual(budgets.week_key(at(2026, 11, 25, 12), week), "2026-11-23")
        # 23:59:59 Winnipeg on Sunday is still the old week, though it is already Monday in UTC.
        just_before = at(2026, 11, 23) - 1
        self.assertEqual(budgets.week_key(just_before, week), "2026-11-16")
        self.assertEqual(budgets.week_key(at(2026, 11, 23), week), "2026-11-23")   # the reset instant opens the new week
        self.assertEqual(datetime.datetime.fromtimestamp(just_before, datetime.timezone.utc).weekday(), 0)

    def test_the_default_week_is_monday_midnight_winnipeg_and_sunday_is_zero(self):
        self.assertEqual(budgets.week_bounds(at(2026, 11, 25, 12))[0], at(2026, 11, 23))
        sunday5pm = {"weekday": 0, "hour": 17, "tz": "America/Winnipeg"}
        self.assertEqual(budgets.week_bounds(at(2026, 11, 22, 16, 59), sunday5pm)[0], at(2026, 11, 15, 17))
        self.assertEqual(budgets.week_bounds(at(2026, 11, 22, 17), sunday5pm)[0], at(2026, 11, 22, 17))

    def test_a_week_across_daylight_saving_keeps_the_wall_clock_reset(self):
        # America/Chicago: its US rules are fixed (clocks go back 2026-11-01 and forward 2026-03-08), so the test
        # does not depend on how the installed tz database treats Winnipeg's future rules.
        chi, week = ZoneInfo("America/Chicago"), {"weekday": 1, "hour": 0, "tz": "America/Chicago"}
        s, e = budgets.week_bounds(at(2026, 10, 28, tz=chi), week)
        self.assertEqual((e - s) / 3600, 169)
        s, e = budgets.week_bounds(at(2026, 3, 4, tz=chi), week)
        self.assertEqual((e - s) / 3600, 167)
        self.assertEqual(budgets.week_key(e, week), "2026-03-09")

    def test_every_hour_of_the_dst_weeks_is_in_exactly_one_week(self):
        for hour_of_reset in (0, 2, 3):          # 02:00 does not exist on the spring-forward Sunday
            week = {"weekday": 0, "hour": hour_of_reset, "tz": "America/Chicago"}
            for first in (at(2026, 3, 1, tz=ZoneInfo("America/Chicago")), at(2026, 10, 25, tz=ZoneInfo("America/Chicago"))):
                prev_end = None
                for i in range(0, 24 * 21):
                    now = first + i * 3600
                    s, e = budgets.week_bounds(now, week)
                    self.assertTrue(s <= now < e, (hour_of_reset, i))
                    if prev_end is not None and now >= prev_end:
                        self.assertEqual(s, prev_end)                       # weeks follow each other, no gap, no overlap
                    prev_end = e

    def test_period_bounds_knows_the_week_and_keeps_day_and_month(self):
        now = at(2026, 11, 25, 12)
        self.assertEqual(budgets.period_bounds(now, "week"), budgets.week_bounds(now))
        d0, d1 = budgets.period_bounds(now, "day")
        self.assertEqual(d1 - d0, 86400)
        m0, m1 = budgets.period_bounds(now, "month")
        self.assertEqual((m1 - m0) / 86400, 30)

    def test_a_bad_week_is_refused(self):
        for bad in ({"weekday": 7, "hour": 0, "tz": "UTC"}, {"weekday": 1, "hour": 24, "tz": "UTC"},
                    {"weekday": True, "hour": 0, "tz": "UTC"}, {"weekday": 1, "hour": 0, "tz": "Mars/Base"},
                    {"weekday": 1, "hour": 0, "tz": None}, "monday"):
            with self.assertRaises(budgets.BudgetError, msg=str(bad)):
                budgets.clean_week(bad)


class Settings(unittest.TestCase):
    def test_a_valid_body_is_stored_in_exact_cents_with_shares_summing_to_100(self):
        s = settings(weekUsd=250)
        self.assertEqual((s["weekUsd"], s["weekTokens"], sum(s["shares"].values())), ("250.00", None, 100))
        self.assertEqual(s["week"], budgets.DEFAULT_WEEK)
        self.assertEqual(settings(weekUsd="100.005")["weekUsd"], "100.01")      # half up, never banker's
        self.assertEqual(settings(weekUsd="0.014")["weekUsd"], "0.01")
        self.assertEqual(settings(weekUsd=19.99)["weekUsd"], "19.99")           # a float never leaks binary error

    def test_what_is_refused(self):
        shares = {a: 0 for a in APPS}
        shares["samvision"] = 100
        ok = {"weekUsd": 10, "shares": shares}
        for bad in ({"weekUsd": 0}, {"weekUsd": 0.004}, {"weekUsd": -5}, {"weekUsd": True}, {"weekUsd": "NaN"},
                    {"weekUsd": "Infinity"}, {"weekUsd": "abc"}, {"weekUsd": 1000000.01}, {"weekUsd": None},
                    {"weekTokens": 0}, {"weekTokens": 1.5}, {"weekTokens": True},
                    {"shares": dict(shares, samvision=99)}, {"shares": dict(shares, gyst=1)},
                    {"shares": dict(shares, samvision=99.5, gyst=0.5)}, {"shares": dict(shares, samvision=True)},
                    {"shares": dict(shares, samvision=101, gyst=-1)}, {"shares": {"samvision": 100}},
                    {"shares": dict(shares, nope=0)}, {"shares": "all"}, {"week": {"weekday": 9, "hour": 0, "tz": "UTC"}}):
            with self.assertRaises(budgets.BudgetError, msg=str(bad)):
                budgets.clean_settings(dict(ok, **bad), APPS)
        with self.assertRaises(budgets.BudgetError):
            budgets.clean_settings([], APPS)
        self.assertEqual(budgets.clean_settings(dict(ok, weekUsd="1000000"), APPS)["weekUsd"], "1000000.00")

    def test_an_app_share_of_the_week_is_rounded_to_the_cent_half_up(self):
        s = settings(weekUsd="100.01")
        usd, _ = budgets._line_limits(s, 33)
        self.assertEqual(str(usd), "33.00")                                       # 33.0033
        usd, _ = budgets._line_limits(settings(weekUsd="0.50"), 1)
        self.assertEqual(str(usd), "0.01")                                       # 0.005 rounds up
        usd, tok = budgets._line_limits(settings(weekUsd="10.00", weekTokens=1001), 50)
        self.assertEqual((str(usd), tok), ("5.00", 500))                          # tokens round down


class Levels(unittest.TestCase):
    def test_a_level_is_reached_at_its_percentage(self):
        from decimal import Decimal as D
        for pct, level in (("0", 0), ("49.99", 0), ("50", 50), ("50.00", 50), ("79.99", 50), ("80", 80), ("94.99", 80),
                           ("95", 95), ("99.99", 95), ("100", 100), ("250", 100)):
            self.assertEqual(budgets.level_of(D(pct)), level, pct)
        self.assertEqual(budgets.level_of(None), 0)
        self.assertEqual(budgets.WEEK_LEVELS, (50, 80, 95, 100))


class Lines(unittest.TestCase):
    def setUp(self):
        self.ts = tasks.TaskStore(os.path.join(tempfile.mkdtemp(prefix="bw-"), "tasks.db"), [])
        self.now = at(2026, 11, 25, 12)
        self.start = at(2026, 11, 23)

    def tearDown(self):
        self.ts.close()

    def report(self, s=None, meter=True):
        return budgets.week_report(self.ts.db, self.now, s if s is not None else settings(), APPS,
                                   meter_at=self.now - 60 if meter else None)

    def line(self, rep, key):
        return next(x for x in rep["lines"] if x["key"] == key)

    def test_no_settings_means_no_lines_and_no_alerts(self):
        use(self.ts.db, self.now - 100, 99.0)
        rep = budgets.week_report(self.ts.db, self.now, None, APPS, meter_at=self.now)
        self.assertEqual((rep["enabled"], rep["lines"]), (False, []))

    def test_an_account_line_and_one_line_per_app(self):
        rep = self.report()
        self.assertEqual([x["key"] for x in rep["lines"]], ["*"] + sorted(APPS))
        self.assertEqual((rep["currency"], rep["estimate"], rep["weekKey"]), ("USD", True, "2026-11-23"))
        self.assertEqual(self.line(rep, "*")["limitUsd"], 100.0)
        self.assertEqual((self.line(rep, "samvision")["limitUsd"], self.line(rep, "gyst")["limitUsd"]), (50.0, 30.0))

    def test_an_app_line_counts_its_own_spend_and_the_account_counts_all_of_it(self):
        use(self.ts.db, self.now - 100, 25.0, project="samvision")
        use(self.ts.db, self.now - 100, 15.0, project="gyst")
        use(self.ts.db, self.now - 100, 10.0, project=None)                      # tied to no app: the account only
        rep = self.report()
        self.assertEqual(self.line(rep, "samvision")["spentUsd"], 25.0)
        self.assertEqual((self.line(rep, "samvision")["pct"], self.line(rep, "samvision")["level"]), (50.0, 50))
        self.assertEqual((self.line(rep, "gyst")["pct"], self.line(rep, "gyst")["level"]), (50.0, 50))
        self.assertEqual((self.line(rep, "*")["spentUsd"], self.line(rep, "*")["level"]), (50.0, 50))

    def test_the_week_edges_and_what_is_not_counted(self):
        use(self.ts.db, self.start, 10.0)                                        # the reset instant is in this week
        use(self.ts.db, self.start - 1, 40.0)                                    # one second earlier is last week's
        use(self.ts.db, self.start + 7 * 86400, 40.0)                            # the next reset is next week's
        use(self.ts.db, self.now - 5, 40.0, source="reported")                   # reported steps double count: skipped
        rep = self.report()
        self.assertEqual(self.line(rep, "*")["spentUsd"], 10.0)

    def test_a_reply_with_no_price_counts_at_the_dearest_listed_price(self):
        use(self.ts.db, self.now - 5, None, tokens=1_000_000)
        rep = self.report()
        self.assertGreater(self.line(rep, "*")["spentUsd"], 0)

    def test_an_app_with_no_share_has_no_budget_and_no_level(self):
        use(self.ts.db, self.now - 5, 90.0, project="gauzemate")
        line = self.line(self.report(), "gauzemate")
        self.assertEqual((line["limitUsd"], line["pct"], line["level"]), (0.0, None, 0))

    def test_exactly_at_a_percentage_the_level_is_reached_and_a_cent_under_it_is_not(self):
        use(self.ts.db, self.now - 5, 24.99, project="samvision")                # 49.98% of 50.00
        self.assertEqual(self.line(self.report(), "samvision")["level"], 0)
        use(self.ts.db, self.now - 4, 0.01, project="samvision")                 # 25.00 = 50.00%
        self.assertEqual(self.line(self.report(), "samvision")["level"], 50)

    def test_a_token_limit_raises_the_level_when_it_is_the_tighter_one(self):
        use(self.ts.db, self.now - 5, 1.0, tokens=900)
        rep = self.report(settings(weekTokens=1000))
        self.assertEqual((self.line(rep, "*")["pct"], self.line(rep, "*")["level"]), (90.0, 80))

    def test_a_stale_meter_alerts_nothing_and_says_so(self):
        use(self.ts.db, self.now - 5, 99.0)
        rep = self.report(meter=False)
        self.assertTrue(rep["stale"])
        self.assertEqual({x["level"] for x in rep["lines"]}, {0})
        self.assertEqual(self.line(rep, "*")["reached"], 95)


class Alerts(unittest.TestCase):
    def line(self, level, usd=100.0, share=None, tokens=None):
        return {"level": level, "limitUsd": usd, "limitTokens": tokens, "share": share}

    def test_zero_to_85_posts_only_the_80_alert_and_marks_the_50_sent(self):
        level, rec = budgets.alert_due(self.line(80), None)
        self.assertEqual((level, rec["sent"]), (80, [50, 80]))
        self.assertEqual(budgets.alert_due(self.line(80), rec)[0], None)          # the same level again: nothing
        self.assertEqual(budgets.alert_due(self.line(95), rec)[0], 95)
        self.assertEqual(budgets.alert_due(self.line(0), None)[0], None)

    def test_a_lower_level_than_one_already_sent_posts_nothing(self):
        _, rec = budgets.alert_due(self.line(95), None)
        self.assertEqual(budgets.alert_due(self.line(50), rec)[0], None)

    def test_a_change_to_the_amount_the_tokens_or_the_share_re_arms(self):
        _, rec = budgets.alert_due(self.line(95, share=50), None)
        self.assertEqual(budgets.alert_due(self.line(95, share=50), rec)[0], None)
        self.assertEqual(budgets.alert_due(self.line(95, usd=200.0, share=50), rec)[0], 95)
        self.assertEqual(budgets.alert_due(self.line(95, share=40), rec)[0], 95)
        self.assertEqual(budgets.alert_due(self.line(95, share=50, tokens=5), rec)[0], 95)

    def test_the_text_says_estimate_and_not_your_bill_and_promises_no_hold(self):
        line = {"scope": "app", "key": "gyst", "name": "GYST", "level": 80, "spentUsd": 24.5, "limitUsd": 30.0}
        t = budgets.alert_text(line, "2026-11-23")
        self.assertIn("Estimate", t)
        self.assertIn("Not your bill", t)
        self.assertIn("80%", t)
        self.assertIn("$24.50 of $30.00", t)
        self.assertNotIn("hold", t.lower())
        self.assertIn("reached its weekly budget", budgets.alert_text(dict(line, level=100), "2026-11-23"))
        self.assertIn("all apps", budgets.alert_text(dict(line, scope="account", key="*"), "2026-11-23"))


class Migration(unittest.TestCase):
    def test_budget_changes_is_append_only_and_the_newest_row_wins(self):
        ts = tasks.TaskStore(os.path.join(tempfile.mkdtemp(prefix="bw-"), "tasks.db"), [])
        try:
            self.assertIsNone(ts.latest_budget_change())
            ts.add_budget_change("jay", "hq", "settings", {"weekUsd": "1.00"}, at=1.0)
            row = ts.add_budget_change("jay", "hq", "settings", {"weekUsd": "2.00"}, at=2.0)
            self.assertEqual(ts.latest_budget_change()["body"], {"weekUsd": "2.00"})
            self.assertEqual(ts.latest_budget_change()["id"], row["id"])
            self.assertIsNone(ts.latest_budget_change("release"))
            for sql in ("UPDATE budget_changes SET actor = 'x'", "DELETE FROM budget_changes"):
                with self.assertRaises(sqlite3.DatabaseError):
                    ts.db.execute(sql)
            with self.assertRaises(sqlite3.IntegrityError):
                ts.db.execute("INSERT INTO budget_changes(at, actor, via, kind, body) VALUES (0,'a','slack','settings','{}')")
            with self.assertRaises(sqlite3.IntegrityError):
                ts.db.execute("INSERT INTO budget_changes(at, actor, via, kind, body) VALUES (0,'a','hq','settings','nope')")
        finally:
            ts.close()


DEV = "d" * 43


class WeekApi(ApiBase):
    """Over HTTP with a fake herdr: Jay's save, /api/usage's budgetWeek, and the alerts into Messages."""

    def equip(self, daemon):
        daemon.dev_gate = security.DeveloperGate(DEV)
        self.base = tempfile.mkdtemp(prefix="bweek-")
        daemon.chat = chat_mod.Chat(os.path.join(self.base, "chat.db"), os.path.join(self.base, "files"), 1 << 20)

    def tearDown(self):
        super().tearDown()
        self.daemon.chat.close()
        shutil.rmtree(self.base)

    def dev(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV}), headers=JSON)
        return dict(JSON, **{"x-ccd-developer": r.json()["session"]})

    def body(self, **over):
        shares = {p["key"]: 0 for p in self.daemon._projects()}
        shares.update(samvision=50, gyst=30, mfe=20)
        return dict({"weekUsd": "100.00", "shares": shares}, **over)

    def save(self, **over):
        return self.client.post("/api/budgets/week", content=json.dumps(self.body(**over)), headers=self.dev())

    def events(self, kind):
        return [e for e in self.store.since(0) if e["kind"] == kind]

    def tick(self, now, meter=True):
        self.daemon.meter_read_at = now - 30 if meter else None
        return self.daemon.budget_tick(now)

    def levels(self, posted, conv="samvision"):
        """The levels posted in one conversation: the account line (the CTO's) alerts on its own."""
        return [p["level"] for p in posted if p["conversation"] == conv]

    def alerts(self, conv="samvision"):
        return [m for m in self.daemon.chat.history(conv, limit=50) if m["author"] == "ccd"]

    # ---- the save ----

    def test_nothing_is_set_by_default(self):
        bw = self.get("/api/usage").json()["budgetWeek"]
        self.assertEqual((bw["enabled"], bw["lines"]), (False, []))
        self.assertEqual(self.tick(at(2026, 11, 25, 12)), [])
        self.assertEqual(self.alerts(), [])

    def test_only_jay_with_developer_unlock_saves(self):
        no_dev = self.client.post("/api/budgets/week", content=json.dumps(self.body()), headers=JSON)
        self.assertEqual(no_dev.status_code, 403)
        agent = dict(self.dev(), **{"x-ccd-actor": "agent:cto"})
        self.assertEqual(self.client.post("/api/budgets/week", content=json.dumps(self.body()), headers=agent).status_code, 403)
        self.assertIsNone(self.tickets.latest_budget_change())

    def test_a_save_is_recorded_and_shows_in_usage_with_groundwork_off(self):
        self.assertFalse(self.daemon.cfg["onboarding_groundwork"])
        r = self.save()
        self.assertEqual(r.status_code, 200, r.text)
        row = self.tickets.latest_budget_change()
        self.assertEqual((row["actor"], row["via"], row["kind"]), ("jay", "hq", "settings"))
        self.assertEqual(row["body"]["weekUsd"], "100.00")
        bw = self.get("/api/usage").json()["budgetWeek"]
        self.assertTrue(bw["enabled"])
        self.assertEqual((bw["currency"], bw["estimate"], bw["note"]), ("USD", True, "Estimate, not your bill"))
        self.assertEqual(bw["settings"]["shares"]["gyst"], 30)
        self.assertIn("samvision", [a["key"] for a in bw["apps"]])
        self.assertEqual(self.get("/api/onboarding/budgets").status_code, 404)    # the shadow report stays off

    def test_a_bad_save_changes_nothing_and_the_latest_save_wins(self):
        self.assertEqual(self.save(weekUsd=-1).status_code, 400)
        shares = self.body()["shares"]
        self.assertEqual(self.save(shares=dict(shares, mfe=19)).status_code, 400)
        self.assertEqual(self.save(shares={"samvision": 100}).status_code, 400)
        self.assertIsNone(self.tickets.latest_budget_change())
        self.assertEqual(self.save(weekUsd="80").status_code, 200)
        self.assertEqual(self.save(weekUsd="90").status_code, 200)
        self.assertEqual(self.get("/api/usage").json()["budgetWeek"]["settings"]["weekUsd"], "90.00")
        self.assertEqual(self.tickets.db.execute("SELECT COUNT(*) FROM budget_changes").fetchone()[0], 2)

    # ---- the alerts ----

    def spend(self, usd, project="samvision", when=None):
        use(self.tickets.db, when or at(2026, 11, 25, 11), usd, project=project)

    def test_one_alert_per_level_per_week_in_the_apps_conversation(self):
        self.save()
        now = at(2026, 11, 25, 12)
        self.spend(42.5)                                                          # 85% of the app's 50.00
        posted = self.tick(now)
        self.assertEqual([(p["level"], p["conversation"]) for p in posted], [(80, "samvision")])
        msgs = self.alerts()
        self.assertEqual(len(msgs), 1)
        self.assertEqual((msgs[0]["side"], msgs[0]["author"]), ("lead", "ccd"))
        self.assertIn("Estimate", msgs[0]["text"])
        self.assertIn("Not your bill", msgs[0]["text"])
        self.assertIn("80%", msgs[0]["text"])
        self.assertEqual(self.tick(now + 300), [])                                # the same level again: nothing
        self.assertEqual(len(self.alerts()), 1)
        self.spend(5.0)                                                           # 95%
        self.assertEqual(self.levels(self.tick(now + 600)), [95])
        self.assertEqual(len(self.alerts()), 2)

    def test_a_pass_that_crosses_several_levels_posts_only_the_highest(self):
        self.save()
        self.spend(48.0)                                                          # 96% of 50.00
        self.assertEqual(self.levels(self.tick(at(2026, 11, 25, 12))), [95])
        self.assertEqual(len(self.alerts()), 1)
        self.spend(2.0)
        self.assertEqual(self.levels(self.tick(at(2026, 11, 25, 12, 10))), [100])

    def test_the_account_line_posts_in_the_cto_conversation(self):
        self.save()
        self.spend(60.0, project=None)                                            # 60% of the 100.00 account
        posted = self.tick(at(2026, 11, 25, 12))
        self.assertEqual([(p["level"], p["conversation"]) for p in posted], [(50, "cto")])
        self.assertIn("all apps", self.alerts("cto")[0]["text"])

    def test_a_restart_at_the_same_level_does_not_repeat(self):
        self.save()
        self.spend(42.5)
        now = at(2026, 11, 25, 12)
        self.tick(now)
        self.daemon.meter_read_at = None                                          # a restart forgets what the meter read
        self.assertEqual(self.tick(now + 120), [])
        self.assertEqual(len(self.alerts()), 1)

    def test_nothing_is_posted_while_the_meter_has_not_read(self):
        self.save()
        self.spend(48.0)                                                          # 96% of the app's 50.00
        now = at(2026, 11, 25, 12)
        self.assertEqual(self.tick(now, meter=False), [])
        self.assertEqual(self.alerts(), [])
        bw = self.daemon.budget_week_state(now)
        self.assertTrue(bw["stale"])
        self.assertEqual({x["level"] for x in bw["lines"]}, {0})
        self.assertEqual(self.levels(self.tick(now)), [95])               # alerts once it has read

    def test_a_failed_post_is_tried_again_next_tick(self):
        self.save()
        self.spend(42.5)
        now = at(2026, 11, 25, 12)
        with mock.patch.object(self.daemon.chat, "add", side_effect=chat_mod.ChatError(500, "disk full")):
            self.assertEqual(self.tick(now), [])
        self.assertEqual(self.alerts(), [])
        self.assertEqual(self.levels(self.tick(now + 300)), [80])

    def test_a_failed_record_after_the_post_repeats_it_once(self):
        self.save()
        self.spend(42.5)
        now = at(2026, 11, 25, 12)
        with mock.patch.object(self.store, "put", side_effect=sqlite3.OperationalError("locked")):
            self.assertEqual(len(self.tick(now)), 1)
        self.assertEqual(len(self.tick(now + 300)), 1)                            # posted again, now recorded
        self.assertEqual(self.tick(now + 600), [])
        self.assertEqual(len(self.alerts()), 2)

    def test_next_week_re_arms_and_a_change_of_amount_or_share_re_arms(self):
        self.save()
        self.spend(42.5)
        now = at(2026, 11, 25, 12)
        self.tick(now)
        self.assertEqual(self.tick(now + 60), [])
        self.assertEqual(self.save(weekUsd="80.00").status_code, 200)             # 42.50 is now 106% of 40.00
        self.assertEqual(self.levels(self.tick(now + 120)), [100])
        next_week = at(2026, 11, 30, 1)                                           # after Monday's reset
        use(self.tickets.db, next_week - 60, 25.0)                                # 62% of the new week's 40.00
        self.assertEqual(self.levels(self.tick(next_week)), [50])

    def test_the_alert_is_an_event_not_a_lead_reply_and_names_no_amount_in_its_data(self):
        self.save()
        self.spend(42.5)
        self.tick(at(2026, 11, 25, 12))
        self.assertEqual(self.events("chat.reply"), [])
        ev = self.events("budget.alert")
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["project"], ev[0]["data"]["conversation"]), ("samvision", "samvision"))
        self.assertIn("Estimate", ev[0]["text"])

    def test_the_client_sees_ids_and_numbers_only(self):
        self.save()
        self.spend(10.0)
        bw = self.get("/api/usage").json()["budgetWeek"]
        for line in bw["lines"]:
            self.assertEqual(set(line) - {"scope", "key", "name", "share", "limitUsd", "limitTokens", "spentUsd", "spentTokens",
                                           "pct", "level", "reached", "currency", "estimate", "weekKey"}, set())

    def test_a_new_app_has_no_share_until_jay_saves_again(self):
        self.save()
        row = self.tickets.latest_budget_change()
        row["body"]["shares"].pop("mfe")                                          # as if mfe were added after the save
        self.tickets.db.execute("DROP TRIGGER budget_changes_append_only_d")
        self.tickets.db.execute("DROP TRIGGER budget_changes_append_only_u")
        self.tickets.db.execute("UPDATE budget_changes SET body = ? WHERE id = ?", (json.dumps(row["body"]), row["id"]))
        lines = {x["key"]: x for x in self.daemon.budget_week_state(at(2026, 11, 25))["lines"]}
        self.assertEqual(lines["mfe"]["share"], 0)


class Slack(unittest.TestCase):
    def test_a_budget_alert_posts_as_the_app_in_the_apps_channel_and_the_cto_channel(self):
        n, d, slack, _ = make(settings={"slack": True})
        run(n.on_event({"source": "budget", "kind": "budget.alert", "project": "samvision",
                        "text": "Estimate: SamVision used 80% of its weekly budget. Not your bill.",
                        "data": {"conversation": "samvision"}}))
        run(n.on_event({"source": "budget", "kind": "budget.alert", "project": None,
                        "text": "Estimate: all apps used 50% of its weekly budget. Not your bill.", "data": {}}))
        posts = [p for p in slack.posts if "weekly budget" in p["text"]]
        self.assertEqual([p["channel"] for p in posts], ["CSV", "CCTO"])
        self.assertTrue(all(p["as"] is None and "Not your bill" in p["text"] for p in posts))


if __name__ == "__main__":
    unittest.main()
