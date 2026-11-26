"""Release email (CC-078, ccd/releasemail.py): one digest per live app, 24 h before its window, never twice, over
verified TLS, from a mail.env that only Jay's user can read. Synthetic data only: a fake SMTP, fake tickets, a
made-up address on a reserved domain. Nothing here opens a socket."""
import asyncio
import datetime
import json
import os
import re
import ssl
import smtplib
import tempfile
import threading
import unittest
import zoneinfo
from pathlib import Path
from unittest import mock

from ccd import notify, release, releasemail
from ccd.pipeline import Pipeline
from ccd.release import Release
from ccd.store import Store
from ccd.tasks import TaskStore

WPG = zoneinfo.ZoneInfo("America/Winnipeg")
ADDR = "jay-test@example.invalid"
PASSWORD = "pw-synthetic-0451"
ENV = {"MAIL_HOST": "smtp.example.invalid", "MAIL_PORT": "465", "MAIL_USER": "ccd-test", "MAIL_PASSWORD": PASSWORD,
       "MAIL_FROM": "ccd-test@example.invalid", "MAIL_TO": ADDR}
PROJECTS = [{"key": "samvision", "name": "SamVision", "prefix": "SV"}, {"key": "gyst", "name": "GYST", "prefix": "GYST"}]


def at(d, hh=0, mm=0, month=11, tz=WPG):
    return datetime.datetime(2026, month, d, hh, mm, tzinfo=tz).timestamp()


# 2026-11-18 is a Wednesday: the default window is Wed 22:00, so the digest is due Tue 11-17 22:00.
WED = at(18, 22)
DUE = at(17, 22)


def run(coro):
    return asyncio.run(coro)


class Dirty:
    def set(self):
        pass


class FakeDaemon:
    def __init__(self, store, ts, pipeline, releases):
        self.store, self.ts, self.pipeline, self.releases = store, ts, pipeline, releases
        self.events = []
        self._stopping = False
        self._dirty = Dirty()
        self.tasks = None

    def _event(self, source, kind, text="", **kw):
        self.events.append((kind, text, kw))

    def _projects(self):
        return [{"key": p["key"]} for p in PROJECTS]

    def state(self):
        return {"needs": [], "blocked": [], "projects": []}


class Server:
    """What the fake SMTP records, and where it fails."""

    def __init__(self):
        self.sent = []          # raw messages accepted
        self.calls = []         # (step, detail)
        self.fail = None        # connect | tls | login | rcpt | data | cert
        self.starttls = True
        self.threads = []
        self.on_mail = None
        self.ctor = []


def fake_smtp_for(server):
    class Fake:
        def __init__(self, host, port, timeout=None, context=None):
            if server.fail == "connect":
                raise OSError(f"cannot reach {host}")
            if server.fail == "cert":
                raise ssl.SSLCertVerificationError("certificate verify failed")
            server.ctor.append({"host": host, "port": port, "timeout": timeout, "context": context})
            server.threads.append(threading.current_thread())

        def ehlo(self):
            server.calls.append(("ehlo", None))

        def has_extn(self, name):
            return server.starttls

        def starttls(self, context=None):
            server.calls.append(("starttls", context))

        def login(self, user, password):
            if server.fail == "login":
                raise smtplib.SMTPAuthenticationError(535, b"authentication failed for " + ADDR.encode())
            server.calls.append(("login", user))

        def mail(self, frm):
            server.calls.append(("mail", frm))
            if server.on_mail:
                server.on_mail()
            return 250, b"ok"

        def rcpt(self, to):
            server.calls.append(("rcpt", to))
            if server.fail == "rcpt":
                return 550, b"no such user " + to.encode()
            return 250, b"ok"

        def data(self, msg):
            server.calls.append(("data", None))
            if server.fail == "data":
                raise smtplib.SMTPServerDisconnected("connection lost during DATA")
            server.sent.append(msg)
            return 250, b"queued"

        def quit(self):
            server.calls.append(("quit", None))
    return Fake


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccd-mail-")
        self.t = [DUE]
        self.server = Server()
        fake = fake_smtp_for(self.server)
        for name in ("SMTP_SSL", "SMTP"):
            p = mock.patch.object(releasemail.smtplib, name, fake)
            p.start()
            self.addCleanup(p.stop)
        self.env_path = os.path.join(self.tmp, "mail.env")
        self.write_env()
        self.store = Store(os.path.join(self.tmp, "ccd.db"))
        self.ts = TaskStore(":memory:", PROJECTS)
        self.pipe = Pipeline(self.ts)
        self.rel = Release(os.path.join(self.tmp, "release.json"))
        self.pipe.releases = self.rel
        self.rel.set_live("samvision", True)
        self.d = FakeDaemon(self.store, self.ts, self.pipe, self.rel)
        self.slack_posts = []
        self.pushes = []
        self.n = self.notifier()
        self.n.update_settings({"releaseMail": True})

    def notifier(self, conf=None):
        slack = mock.Mock()
        slack.post.side_effect = lambda *a, **k: self.slack_posts.append(a) or {"ok": True, "ts": "1.0"}
        slack.scopes = None
        return notify.Notifier(self.d, {"notify": {"slack": dict({"jay_member_id": "U0JAY0001"}, **(conf or {}))}},
                               slack=slack, ntfy=lambda *a, **k: self.pushes.append(a), clock=lambda: self.t[0],
                               env_path=os.path.join(self.tmp, "none.env"), mail_env_path=self.env_path)

    def write_env(self, **over):
        env = dict(ENV, **over)
        with open(self.env_path, "w") as f:
            f.write("".join(f"{k}={v}\n" for k, v in env.items() if v is not None))
        os.chmod(self.env_path, 0o600)

    def tick(self, when=None):
        if when is not None:
            self.t[0] = when
        run(self.n.tick())

    def ticket(self, project, title, status="VERIFYING", merge_at=None, deploy=None):
        t, _ = self.ts.create(project, title)
        self.ts.db.execute("UPDATE tickets SET status=? WHERE key=?", (status, t["key"]))
        self.ts.db.execute("INSERT INTO ticket_work(ticket_id, merge, deploy, updated_at) VALUES (?,?,?,0)",
                           (t["id"], json.dumps({"at": merge_at}) if merge_at else None,
                            json.dumps(deploy) if deploy else None))
        return t["key"]

    def rows(self, project="samvision"):
        return self.n.mail.ledger(project)

    def body(self, i=-1):
        import email
        m = email.message_from_bytes(self.server.sent[i])
        return m["Subject"], m.get_payload(decode=True).decode()

    def wipe_notifier(self):
        """A restart: a new Notifier on the same stores."""
        self.n = self.notifier()
        return self.n


class DueTime(Base):
    def test_one_email_at_the_due_time_even_inside_quiet_hours(self):
        self.tick(DUE - 60)
        self.assertEqual(self.server.sent, [])
        self.assertTrue(notify.in_quiet(self.n.settings, DUE))      # 22:00 is quiet hours: the mail still goes
        self.tick(DUE)
        self.assertEqual(len(self.server.sent), 1)
        self.assertEqual([c for c in self.server.calls if c[0] in ("mail", "rcpt")],
                         [("mail", ENV["MAIL_FROM"]), ("rcpt", ADDR)])
        self.tick(DUE + 600)
        self.tick(WED - 1)
        self.assertEqual(len(self.server.sent), 1)
        self.assertEqual(self.rows()[0]["state"], "delivered")

    def test_a_project_that_is_not_live_gets_none(self):
        self.rel.set_live("samvision", False)
        self.tick(DUE)
        self.assertEqual(self.server.sent, [])
        self.assertEqual(self.rows(), [])

    def test_release_email_off_sends_nothing(self):
        self.n.update_settings({"releaseMail": False})
        self.tick(DUE)
        self.assertEqual(self.server.sent, [])

    def test_a_sunday_window_across_the_clock_change_is_due_the_evening_before_on_the_wall_clock(self):
        chi = zoneinfo.ZoneInfo("America/Chicago")
        w = dict(release.DEFAULT_WINDOW, weekday=0, tz="America/Chicago")
        after = at(1, 22, month=11, tz=chi)                    # Sunday 22:00, after the 2026-11-01 change
        before = at(31, 22, month=10, tz=chi)                   # Saturday 22:00, still daylight time
        self.assertNotEqual(datetime.datetime.fromtimestamp(before, chi).utcoffset(),
                            datetime.datetime.fromtimestamp(after, chi).utcoffset())
        W, due, _ = releasemail.ReleaseMail.due_window(w, before - 3600)
        self.assertEqual((W, due), (after, before))
        self.assertNotEqual(after - before, 24 * 3600)          # 25 h of real time, 24 h on the clock

    def test_catch_up_after_a_missed_due_time_sends_one_late_digest(self):
        self.tick(at(18, 10))                                   # ccd was down at the due time
        self.assertEqual(len(self.server.sent), 1)
        self.tick(at(18, 21))
        self.assertEqual(len(self.server.sent), 1)

    def test_a_started_window_is_never_mailed(self):
        self.tick(WED + 60)
        self.assertEqual(self.server.sent, [])

    def test_switched_on_inside_the_24_hours_sends_one(self):
        self.n.update_settings({"releaseMail": False})
        self.tick(at(18, 8))
        self.n.update_settings({"releaseMail": True})
        self.tick(at(18, 20))
        self.assertEqual(len(self.server.sent), 1)

    def test_live_switched_on_inside_the_24_hours_sends_one(self):
        self.rel.set_live("samvision", False)
        self.tick(at(18, 8))
        self.rel.set_live("samvision", True)
        self.tick(at(18, 20))
        self.assertEqual(len(self.server.sent), 1)


class Content(Base):
    def test_three_headings_in_order_with_none_for_an_empty_one(self):
        self.tick(DUE)
        subject, body = self.body()
        self.assertEqual(subject, "SamVision release Wed 2026-11-18 22:00 EST: 0 scheduled")
        heads = [body.index(h) for h in releasemail.SECTIONS]
        self.assertEqual(heads, sorted(heads))
        self.assertEqual(body.count("None"), 3)

    def test_tickets_land_in_the_right_section_and_every_line_starts_with_its_key(self):
        merged_before = self.ticket("samvision", "Merged Tuesday morning", merge_at=at(17, 9))
        merged_after_cutoff = self.ticket("samvision", "Merged Wednesday afternoon", merge_at=at(18, 13))
        urgent = self.ticket("samvision", "Urgent one", merge_at=at(17, 9),
                             deploy={"env": "live", "requestedAt": at(17, 9), "urgent": True})
        requested = self.ticket("samvision", "Deploy asked for", merge_at=at(17, 8),
                                deploy={"env": "live", "requestedAt": at(17, 9), "approvedAt": None})
        later = self.ticket("samvision", "Merged too late, deploy asked", merge_at=at(18, 13),
                            deploy={"env": "live", "requestedAt": at(18, 13)})
        done = self.ticket("samvision", "Verified and closed", status="DONE", merge_at=at(10, 9),
                           deploy={"env": "live", "requestedAt": at(10, 9), "result": "pass", "deployedAt": at(15, 22)})
        old = self.ticket("samvision", "Verified long ago", status="DONE", merge_at=at(1, 9),
                          deploy={"env": "live", "requestedAt": at(1, 9), "result": "pass", "deployedAt": at(3, 22)})
        self.tick(DUE)
        subject, body = self.body()
        parts = re.split(r"^(?=Scheduled this|Verified in|Held)", body, flags=re.M)
        scheduled, verified, held = parts[1], parts[2], parts[3]
        for k in (merged_before, requested):
            self.assertIn(k, scheduled)
        for k in (merged_after_cutoff, urgent, later, done, old):
            self.assertNotIn(k, scheduled)
        self.assertIn(done, verified)
        self.assertNotIn(old, verified)         # before the first digest's one-week look-back
        self.assertIn(later, held)
        self.assertIn("2 scheduled", subject)
        for line in body.splitlines():
            if line.startswith("  ") and "None" not in line:
                self.assertRegex(line.strip(), r"^(SV|GYST)-\d+")
        self.assertEqual(self.rows()[0]["listed"]["scheduled"], sorted([merged_before, requested],
                         key=lambda k: int(k.split("-")[1])))

    def test_verified_since_the_last_digest_reads_closed_tickets_and_starts_at_the_last_delivery(self):
        self.tick(DUE)                                      # first digest, delivered at DUE
        sent_at = self.rows()[0]["sentAt"]
        before = self.ticket("samvision", "Verified before the last digest", status="DONE", merge_at=at(10, 9),
                             deploy={"env": "live", "requestedAt": at(10), "result": "pass", "deployedAt": sent_at - 3600})
        after = self.ticket("samvision", "Verified after it", status="DONE", merge_at=at(10, 9),
                            deploy={"env": "live", "requestedAt": at(10), "result": "pass", "deployedAt": sent_at + 3600})
        self.tick(at(24, 22))
        _, body = self.body()
        self.assertIn(after, body)
        self.assertNotIn(before, body)

    def test_the_footer_takes_the_cutoff_from_the_window_not_from_noon(self):
        self.rel.set_window(3, "10:00")                     # a morning window opens before noon: its start is the cutoff
        self.tick(at(17, 10))
        _, body = self.body()
        self.assertIn("Changes merged before Wed 2026-11-18 10:00 EST also join this release", body)
        self.assertNotIn("12:00", body)
        self.assertIn("Go Live lists them", body)

    def test_a_client_project_shows_keys_only(self):
        self.rel.set_live("gyst", True)
        self.n = self.notifier({"client_projects": ["gyst"]})
        self.n.update_settings({"releaseMail": True})
        key = self.ticket("gyst", "Quarterly tax filing helper", merge_at=at(17, 9))
        self.tick(DUE)
        self.assertEqual(len(self.server.sent), 2)
        for raw in self.server.sent:
            import email
            m = email.message_from_bytes(raw)
            text = m["Subject"] + m.get_payload(decode=True).decode()
            if "GYST" in m["Subject"]:
                self.assertIn(key, text)
                self.assertNotIn("Quarterly", text)
                self.assertNotIn("tax", text)


class NeverTwice(Base):
    def test_a_restart_and_later_ticks_send_nothing_more(self):
        self.tick(DUE)
        self.wipe_notifier().update_settings({"releaseMail": True})
        self.tick(DUE + 3600)
        self.tick(WED - 1)
        self.assertEqual(len(self.server.sent), 1)

    def test_a_window_moved_within_the_release_or_earlier_sends_nothing(self):
        self.tick(DUE)
        self.rel.set_window(3, "22:30")
        self.tick(DUE + 60)
        self.rel.set_window(3, "20:00")
        self.tick(DUE + 120)
        self.rel.set_window(2, "22:00")                     # Tuesday, earlier than the mailed window
        self.tick(DUE + 180)
        self.assertEqual(len(self.server.sent), 1)

    def test_moved_to_a_later_weekday_before_the_sent_window_ends_gets_one_digest_for_the_new_window(self):
        self.tick(DUE)
        self.rel.set_window(4, "22:00")                     # Thursday
        self.tick(DUE + 60)                                 # the Thursday digest is not due until Wednesday 22:00
        self.assertEqual(len(self.server.sent), 1)
        self.tick(at(18, 22))
        self.assertEqual(len(self.server.sent), 2)
        self.assertEqual(self.rows()[0]["window"], at(19, 22))
        self.tick(at(18, 23))
        self.wipe_notifier().update_settings({"releaseMail": True})
        self.tick(at(19, 8))
        self.assertEqual(len(self.server.sent), 2)

    def test_the_next_week_gets_its_own_digest(self):
        self.tick(DUE)
        self.tick(at(19, 1))                                # the window has ended
        self.assertEqual(len(self.server.sent), 1)
        self.tick(at(24, 22))
        self.assertEqual(len(self.server.sent), 2)
        self.assertEqual([r["window"] for r in self.rows()], [at(25, 22), WED])


class Failures(Base):
    def test_a_definite_failure_is_retried_once_after_300_s_and_the_alert_clears(self):
        self.server.fail = "rcpt"
        self.tick(DUE)
        r = self.rows()[0]
        self.assertEqual((r["state"], r["attempts"], r["uncertain"]), ("failed", 1, False))
        self.assertEqual([a["text"] for a in self.n.mail.alerts()], ["SamVision release email failed, retrying once"])
        self.assertTrue(any(k == "notify.failed" for k, _, _ in self.d.events))
        self.assertEqual(self.n.public()["mail"]["last"]["state"], "failed")
        self.tick(DUE + 299)
        self.assertEqual(len(self.server.calls) and self.rows()[0]["attempts"], 1)
        self.server.fail = None
        self.tick(DUE + 300)
        self.assertEqual((self.rows()[0]["state"], self.rows()[0]["attempts"]), ("delivered", 2))
        self.assertEqual(self.n.mail.alerts(), [])
        self.assertEqual(len(self.server.sent), 1)
        self.assertEqual(self.rows()[0]["messageId"], f"<release-samvision-{int(WED)}@commandcenter>")

    def test_a_second_refusal_is_final_with_no_third_try(self):
        self.server.fail = "rcpt"
        self.tick(DUE)
        self.tick(DUE + 300)
        self.assertEqual(self.rows()[0]["attempts"], 2)
        self.assertEqual([a["text"] for a in self.n.mail.alerts()], ["SamVision release email failed twice, not sent"])
        self.tick(DUE + 900)
        self.tick(DUE + 3600)
        self.assertEqual(self.rows()[0]["attempts"], 2)
        self.assertEqual(self.server.sent, [])

    def test_no_retry_at_or_after_the_window_start(self):
        self.server.fail = "rcpt"
        self.tick(DUE)
        self.server.fail = None
        self.tick(WED)
        self.tick(WED + 600)
        self.assertEqual((self.rows()[0]["attempts"], self.server.sent), (1, []))

    def test_a_connection_lost_during_data_is_uncertain_and_never_resent(self):
        self.server.fail = "data"
        self.tick(DUE)
        r = self.rows()[0]
        self.assertEqual((r["state"], r["uncertain"]), ("failed", True))
        self.assertEqual([a["text"] for a in self.n.mail.alerts()],
                         ["SamVision release email may not have been sent, not retried"])
        self.server.fail = None
        self.tick(DUE + 300)
        self.tick(DUE + 3600)
        self.wipe_notifier().update_settings({"releaseMail": True})
        self.tick(DUE + 7200)
        self.assertEqual((self.server.sent, self.rows()[0]["attempts"]), ([], 1))

    def test_a_row_left_in_sending_becomes_uncertain_at_start_and_is_never_resent(self):
        self.store.put("release_mail:samvision", [{
            "window": WED, "due": DUE, "state": "sending", "uncertain": False, "attempts": 1, "at": DUE,
            "sentAt": None, "messageId": "<x@y>", "error": None, "listed": {}}])
        n = self.wipe_notifier()
        n.update_settings({"releaseMail": True})
        r = n.mail.ledger("samvision")[0]
        self.assertEqual((r["state"], r["uncertain"]), ("failed", True))
        self.assertEqual(len(n.mail.alerts()), 1)
        self.tick(DUE + 600)
        self.assertEqual(self.server.sent, [])

    def test_the_ledger_row_is_in_the_database_as_sending_before_mail_from(self):
        seen = []

        def check():
            rows, _ = self.store.get("release_mail:samvision")
            seen.append(rows[0]["state"])
        self.server.on_mail = check
        self.tick(DUE)
        self.assertEqual(seen, ["sending"])
        self.assertEqual(self.store.get("release_mail:samvision")[0][0]["state"], "delivered")

    def test_a_certificate_error_and_a_refused_login_are_definite_failures(self):
        for fail in ("cert", "login", "connect"):
            with self.subTest(fail=fail):
                self.rows().clear()
                self.n.mail._save("samvision")
                self.server.fail = fail
                self.tick(DUE)
                r = self.rows()[0]
                self.assertEqual((r["state"], r["uncertain"]), ("failed", False))

    def test_the_address_and_password_appear_nowhere_after_a_refusal_that_names_them(self):
        self.server.fail = "rcpt"
        with self.assertLogs("ccd.notify", level="WARNING") as logs:
            self.tick(DUE)
            self.tick(DUE + 300)
        kv = json.dumps(self.store.db.execute("SELECT key, value FROM kv").fetchall())
        events = json.dumps(self.d.events, default=str)
        alerts = json.dumps(self.n.mail.alerts())
        public = json.dumps(self.n.public())
        for where in (kv, events, alerts, public, "\n".join(logs.output)):
            self.assertNotIn(ADDR, where)
            self.assertNotIn(PASSWORD, where)
            self.assertNotIn("jay-test", where)

    def test_a_mail_step_that_raises_does_not_stop_the_needs_and_a_slack_failure_does_not_stop_the_mail(self):
        self.n.update_settings({"slack": True})
        self.d.needs_list = []
        called = []

        async def boom():
            raise RuntimeError("smtp exploded")

        async def needs():
            called.append("needs")

        async def summaries():
            called.append("summaries")
        self.n.mail.run, real = boom, self.n.mail.run
        self.n.check_needs = needs
        self.n.summaries = summaries
        self.tick(DUE)
        self.assertEqual(called, ["needs", "summaries"])
        self.assertTrue(any("release mail" in str(e) for e in self.d.events))
        self.n.mail.run = real
        self.assertIn("summaries", called)

        async def slack_down():
            raise RuntimeError("slack down")
        self.n.check_needs = slack_down
        self.tick(DUE + 10)
        self.assertEqual(len(self.server.sent), 1)


class Transport(Base):
    def test_port_465_uses_implicit_tls_with_a_verifying_context_a_timeout_and_a_worker_thread(self):
        self.tick(DUE)
        (c,) = self.server.ctor
        self.assertEqual((c["host"], c["port"], c["timeout"]), (ENV["MAIL_HOST"], 465, 30))
        self.assertTrue(c["context"].check_hostname)
        self.assertEqual(c["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertNotIn("starttls", [s for s, _ in self.server.calls])
        self.assertTrue(all(t is not threading.main_thread() for t in self.server.threads))

    def test_port_587_must_offer_starttls_and_then_uses_a_verifying_context(self):
        self.write_env(MAIL_PORT="587")
        self.server.starttls = False
        self.tick(DUE)
        self.assertEqual((self.server.sent, self.rows()[0]["state"]), ([], "failed"))
        self.assertNotIn("login", [s for s, _ in self.server.calls])      # the password never went in clear
        self.server.starttls = True
        self.tick(DUE + 300)
        self.assertEqual(len(self.server.sent), 1)
        ctx = [c for s, c in self.server.calls if s == "starttls"][0]
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_any_other_port_is_a_config_error_and_nothing_is_opened(self):
        self.write_env(MAIL_PORT="25")
        self.tick(DUE)
        self.assertEqual((self.server.ctor, self.server.sent), ([], []))
        self.assertIn("465 or 587", self.n.public()["mail"]["error"])

    def test_a_group_readable_mail_env_is_refused(self):
        os.chmod(self.env_path, 0o640)
        self.tick(DUE)
        self.assertEqual((self.server.ctor, self.server.sent), ([], []))
        self.assertIn("chmod 600", self.n.public()["mail"]["error"])
        os.chmod(self.env_path, 0o600)
        self.tick(DUE + 60)                                  # fixed in time: it still goes, before the window
        self.assertEqual(len(self.server.sent), 1)

    def test_a_mail_env_owned_by_another_user_is_refused(self):
        with mock.patch.object(notify.os, "getuid", return_value=os.getuid() + 1):
            self.tick(DUE)
            error = self.n.public()["mail"]["error"]
        self.assertEqual(self.server.sent, [])
        self.assertIn("belong to the user", error)

    def test_a_mail_env_that_is_a_link_is_refused(self):
        real = os.path.join(self.tmp, "real.env")
        os.rename(self.env_path, real)
        os.symlink(real, self.env_path)
        self.tick(DUE)
        self.assertEqual(self.server.sent, [])

    def test_two_recipients_are_refused(self):
        for to in (f"{ADDR},other@example.invalid", f"{ADDR} other@example.invalid", f"{ADDR};x@example.invalid"):
            self.write_env(MAIL_TO=to)
            self.tick(DUE)
            self.assertEqual(self.server.sent, [], to)
            self.assertEqual(self.n.public()["mail"]["error"], "MAIL_TO must be exactly one address")

    def test_no_mail_env_means_not_configured_and_nothing_sent(self):
        os.unlink(self.env_path)
        self.tick(DUE)
        m = self.n.public()["mail"]
        self.assertEqual((m["configured"], self.server.sent), (False, []))
        self.assertEqual(m["error"], "No mail settings on jay-server (mail.env)")
        self.assertEqual(len(self.n.mail.alerts()), 1)       # Jay sees that a due digest could not go

    def test_a_test_email_reports_true_or_false_and_leaves_no_ledger_row(self):
        r = run(self.n.send_test())
        self.assertEqual((r["mail"], r["slack"], r["ntfy"]), (True, False, False))
        self.assertEqual(self.rows(), [])
        self.server.fail = "login"
        self.assertFalse(run(self.n.send_test())["mail"])
        self.n.update_settings({"releaseMail": False})
        self.assertFalse(run(self.n.send_test())["mail"])


class Codex1(Base):
    """Codex review round 1 of CC-078."""

    def two_apps(self):
        self.rel.set_live("gyst", True)

    def test_switching_release_email_off_during_one_send_stops_the_next_app(self):
        self.two_apps()
        self.server.on_mail = lambda: self.n.update_settings({"releaseMail": False})
        self.tick(DUE)
        self.assertEqual(len(self.server.sent), 1)

    def test_an_app_is_re_checked_against_the_clock_so_nothing_goes_at_the_window_start(self):
        self.two_apps()
        self.server.on_mail = lambda: self.t.__setitem__(0, WED)      # a slow send carries the batch to the start
        self.tick(WED - 1)
        self.assertEqual(len(self.server.sent), 1)

    def test_only_a_regular_owner_only_file_is_read_and_every_other_kind_is_a_sanitized_error(self):
        os.unlink(self.env_path)
        os.mkdir(self.env_path, 0o700)
        self.assertIn("regular file", self.n.public()["mail"]["error"])
        os.rmdir(self.env_path)
        os.mkfifo(self.env_path, 0o600)                                 # opening it would block the event loop
        self.assertIn("regular file", self.n.public()["mail"]["error"])
        os.unlink(self.env_path)
        self.write_env()
        os.chmod(self.env_path, 0o000)
        self.assertIn("could not be read", self.n.public()["mail"]["error"])
        os.chmod(self.env_path, 0o600)
        with open(self.env_path, "wb") as f:
            f.write(b"\xff\xfe=\x80\n")
        os.chmod(self.env_path, 0o600)
        self.assertIn("could not be read", self.n.public()["mail"]["error"])
        self.tick(DUE)
        self.assertEqual(self.server.sent, [])

    def test_mail_env_symlink_0644_and_a_swapped_file_are_refused_on_the_open_file(self):
        # CC-091: the mail.env caller goes through the same single-open reader.
        os.unlink(self.env_path)
        real = os.path.join(self.tmp, "real.env")
        with open(real, "w") as f:
            f.write("MAIL_HOST=h\n")
        os.chmod(real, 0o600)
        os.symlink(real, self.env_path)
        self.assertIn("not a link", self.n.public()["mail"]["error"])
        os.unlink(self.env_path)
        self.write_env()
        os.chmod(self.env_path, 0o644)
        self.assertIn("chmod 600", self.n.public()["mail"]["error"])
        real_open = os.open

        def swap_after_open(path, *a, **kw):
            fd = real_open(path, *a, **kw)
            os.unlink(self.env_path)
            with open(self.env_path, "w") as f:
                f.write("MAIL_HOST=h\n")
            os.chmod(self.env_path, 0o600)       # a clean file swapped in must not rescue the 0644 one
            return fd
        with mock.patch.object(os, "open", swap_after_open):
            conf, error = self.n.mail.config()
        self.assertIsNone(conf)
        self.assertIn("chmod 600", error)

    def test_the_runbooks_mail_env_example_is_accepted_as_written(self):
        text = (Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "slack-and-ntfy.md").read_text()
        block = re.search(r"```\n(MAIL_HOST=.*?)```", re.sub(r"(?m)^   ", "", text), re.S).group(1)
        with open(self.env_path, "w") as f:
            f.write(block.replace("MAIL_USER=...", "MAIL_USER=u").replace("MAIL_PASSWORD=...", "MAIL_PASSWORD=p"))
        os.chmod(self.env_path, 0o600)
        conf, error = self.n.mail.config()
        self.assertIsNone(error)
        self.assertEqual((conf["port"], conf["to"], conf["password"]), (465, "you@example.com", "p"))


class Switch(Base):
    def test_off_by_default_and_validated(self):
        self.assertFalse(notify.SETTINGS_DEFAULTS["releaseMail"])
        with self.assertRaises(ValueError):
            self.n.update_settings({"releaseMail": "yes"})

    def test_only_release_email_on_runs_the_mail_step_and_calls_neither_slack_nor_ntfy(self):
        self.assertEqual((self.n.settings["slack"], self.n.settings["ntfy"]), (False, False))
        self.tick(DUE)
        self.assertEqual((len(self.server.sent), self.slack_posts, self.pushes), (1, [], []))


class ReadOnly(Base):
    def test_a_digest_changes_no_ticket_state_and_the_source_names_no_deploy_step(self):
        self.ticket("samvision", "Merged", merge_at=at(17, 9))
        self.ticket("samvision", "Asked", merge_at=at(17, 9), deploy={"env": "live", "requestedAt": at(17, 9)})

        def dump():
            return self.ts.db.execute("SELECT * FROM ticket_work ORDER BY ticket_id").fetchall(), \
                self.ts.db.execute("SELECT key, status FROM tickets ORDER BY id").fetchall(), \
                self.ts.db.execute("SELECT COUNT(*) FROM ticket_events").fetchone()
        from ccd.daemon import Daemon
        from .helpers import cfg
        real = Daemon(cfg(meter={"enabled": False}), Store(os.path.join(self.tmp, "real.db")), None, tasks=self.ts)
        gated = self.ticket("samvision", "Waiting for Go Live", merge_at=at(17, 9),
                            deploy={"env": "live", "requestedAt": at(17, 9)})
        self.ts.db.execute("UPDATE ticket_work SET gate='deploy' WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)",
                           (gated,))
        review = real.go_live_review("samvision")
        self.assertEqual([a["key"] for a in review["approves"]], [gated])
        before = dump()
        self.tick(DUE)
        self.assertEqual(real.go_live_review("samvision"), review)
        self.assertEqual(len(self.server.sent), 1)
        self.assertEqual(dump(), before)
        src = Path(releasemail.__file__).read_text()
        for word in ("confirm", "deploy_go", "deployed", "deploy_request", "act_go_live"):
            self.assertNotIn(word, src)



# ----- CC-088: pull a digest item by Slack reply -----

JAY = "U0JAY0001"
TEAM = "T0TEAM001"
MORNING = at(18, 7)          # quiet hours end on Wed 11-18: the Slack list for the Tue 22:00 digest goes now
GN = "GYST / LifeOps"        # the registry's name for gyst


class FakeSlack:
    """A Slack that records every post; ts are distinct so each post is its own thread."""

    def __init__(self, posts):
        self.posts, self.n, self.scopes = posts, 0, None

    def post(self, channel, text, thread_ts=None, as_=None, broadcast=False):
        self.n += 1
        self.posts.append({"channel": channel, "text": text, "thread": thread_ts, "ts": f"{self.n}.0"})
        return {"ok": True, "ts": f"{self.n}.0"}

    def dm(self, user):
        return "DJAY"

    def channels(self):
        return {"cto": "CCTO", "samvision": "CSV", "gyst": "CGY"}


class Night:
    def __init__(self):
        self.state = {}

    def get(self, project):
        return dict(self.state.get(project) or {})

    def went_live(self, project, keys=(), now=None):
        self.state.setdefault(project, {}).update(goLiveAt=now, goLiveKeys=list(keys))


class PullBase(Base):
    def setUp(self):
        super().setUp()
        self.d.night = Night()
        self.rel.set_live("gyst", True)
        self.n.update_settings({"slack": True})
        self.g12 = self.ticket_n("gyst", 12, "Export to CSV", merge_at=at(17, 9))
        self.g13 = self.ticket_n("gyst", 13, "Budget view", merge_at=at(17, 10))
        self.g14 = self.ticket_n("gyst", 14, "Held for later", merge_at=at(18, 13),       # after the noon cutoff
                                 deploy={"env": "live", "requestedAt": at(18, 13)})
        self.g15 = self.ticket_n("gyst", 15, "Shipped last week", status="DONE", merge_at=at(10, 9),
                                 deploy={"env": "live", "requestedAt": at(10, 9), "result": "pass",
                                         "deployedAt": at(16)})
        self.mid = {}

    def notifier(self, conf=None):
        slack_conf = dict({"jay_member_id": JAY, "team_id": TEAM}, **(conf or {}))
        n = notify.Notifier(self.d, {"notify": {"slack": slack_conf}},
                            slack=FakeSlack(self.slack_posts), ntfy=lambda *a, **k: self.pushes.append(a),
                            clock=lambda: self.t[0], env_path=os.path.join(self.tmp, "none.env"),
                            mail_env_path=self.env_path)
        n.summaries = mock.AsyncMock()          # the morning channel summaries are not what these tests are about
        return n

    def ticket_n(self, project, number, title, merge_at=None, deploy=None, status="VERIFYING"):
        t, _ = self.ts.create(project, title, number=number)
        self.ts.db.execute("UPDATE tickets SET status=? WHERE key=?", (status, t["key"]))
        self.ts.db.execute("INSERT INTO ticket_work(ticket_id, merge, deploy, updated_at) VALUES (?,?,?,0)",
                           (t["id"], json.dumps({"at": merge_at}) if merge_at else None,
                            json.dumps(deploy) if deploy else None))
        return t["key"]

    def listed(self):
        """Digest at its due time, then the Slack list when quiet hours end. Returns the GYST list's post."""
        self.tick(DUE)
        self.tick(MORNING)
        return next(p for p in self.slack_posts if p["text"].startswith(f"*{GN} release"))

    def say(self, text, thread=None, user=JAY, team=TEAM, channel="DJAY", **extra):
        self.say_n = getattr(self, "say_n", 100) + 1
        ev = dict({"type": "message", "user": user, "text": text, "channel": channel, "ts": f"{self.say_n}.0",
                   "team": team}, **extra)
        if thread:
            ev["thread_ts"] = thread
        return run(self.n.on_slack({"team_id": team, "event_id": f"Ev{self.say_n}", "event": ev}))

    def gyst(self):
        return self.rows("gyst")[0]

    def mails(self):
        import email
        return [email.message_from_bytes(raw) for raw in self.server.sent]

    def corrections(self):
        return [m for m in self.mails() if m["Subject"].startswith("Correction")]

    def work_dump(self):
        return self.ts.db.execute("SELECT * FROM ticket_work ORDER BY ticket_id").fetchall(), \
            self.ts.db.execute("SELECT key, status FROM tickets ORDER BY id").fetchall()

    def thread_replies(self, ts):
        return [p["text"] for p in self.slack_posts if p["thread"] == ts]


class SlackList(PullBase):
    def test_c5_one_dm_per_live_app_after_quiet_hours_with_the_listed_keys(self):
        self.tick(DUE)
        self.assertEqual(len(self.server.sent), 2)
        self.tick(DUE + 60)
        self.tick(MORNING - 60)                                     # Tue 22:00 digest: quiet until 07:00
        self.assertEqual(self.slack_posts, [])
        self.tick(MORNING)
        self.assertEqual(len(self.slack_posts), 2)
        post = next(p for p in self.slack_posts if p["text"].startswith(f"*{GN} release"))
        self.assertEqual(post["channel"], "DJAY")
        self.assertIsNone(post["thread"])
        self.assertEqual(self.gyst()["listed"]["scheduled"], [self.g12, self.g13])
        for key in self.gyst()["listed"]["scheduled"]:
            self.assertIn(key, post["text"])
        self.assertIn("Export to CSV", post["text"])
        self.assertNotIn(self.g14, post["text"])
        self.assertEqual(self.gyst()["slack"], {"state": "posted", "attempts": 1, "at": MORNING, "channel": "DJAY",
                                                "ts": post["ts"], "uncertain": False})
        self.tick(MORNING + 600)
        self.wipe_notifier()
        self.tick(MORNING + 1200)
        self.assertEqual(len(self.slack_posts), 2)                  # once, restart included

    def test_the_digest_footer_points_to_slack_only_when_slack_is_on(self):
        self.tick(DUE)
        self.assertIn("reply with its ticket ID in the Slack message", self.body()[1])
        self.n.update_settings({"slack": False})
        self.tick(at(24, 22))
        self.assertNotIn("Slack", self.body()[1])

    def test_never_after_the_window_ends_or_after_go_live_was_sent(self):
        self.tick(DUE)
        self.d.night.went_live("gyst", [], now=DUE + 60)
        self.tick(MORNING)
        self.assertEqual([p["text"][:14] for p in self.slack_posts], ["*SamVision rel"])
        self.d.night.state = {}
        self.n.update_settings({"slack": False})
        self.tick(MORNING + 60)
        self.n.update_settings({"slack": True})
        self.tick(WED + release.WINDOW_HOURS * 3600)
        self.assertEqual(len(self.slack_posts), 1)

    def test_a_failed_post_is_retried_once_then_raises_the_alert(self):
        self.tick(DUE)
        self.n._slack.post = mock.Mock(side_effect=notify.SlackError("channel_not_found"))
        self.tick(MORNING)
        self.assertEqual(self.gyst()["slack"]["state"], "failed")
        self.assertIn(f"{GN} release list not posted in Slack, retrying once",
                      [a["text"] for a in self.n.mail.alerts()])
        self.tick(MORNING + 299)
        self.assertEqual(self.gyst()["slack"]["attempts"], 1)
        self.tick(MORNING + 300)
        self.assertEqual(self.gyst()["slack"]["attempts"], 2)
        self.assertIn(f"{GN} release list not posted in Slack: pulls by Slack unavailable",
                      [a["text"] for a in self.n.mail.alerts()])
        self.tick(MORNING + 3600)
        self.assertEqual(self.gyst()["slack"]["attempts"], 2)

    def test_a_list_left_posting_at_a_restart_is_never_posted_again(self):
        self.tick(DUE)
        self.rows("gyst")[0]["slack"] = {"state": "posting", "attempts": 1, "at": MORNING, "channel": None, "ts": None,
                                         "uncertain": False}
        self.n.mail._save("gyst")
        self.wipe_notifier()
        self.assertEqual((self.gyst()["slack"]["state"], self.gyst()["slack"]["uncertain"]), ("failed", True))
        self.tick(MORNING + 600)
        self.assertFalse(any(p["text"].startswith(f"*{GN}") for p in self.slack_posts))

    def test_a_ledger_row_from_cc_078_loads_alerts_and_has_no_pulls(self):
        self.store.put("release_mail:gyst", [{"window": WED, "due": DUE, "state": "delivered", "uncertain": False,
                                              "attempts": 1, "at": DUE, "sentAt": DUE, "error": None,
                                              "messageId": f"<release-gyst-{int(WED)}@commandcenter>",
                                              "listed": {"scheduled": [self.g12], "verified": [], "held": []}}])
        self.wipe_notifier()
        self.assertEqual(self.n.mail.alerts(), [])
        self.assertEqual(releasemail.pulled(self.store, "gyst"), set())
        self.assertEqual(releasemail.pulled(self.store, "samvision"), set())
        self.assertEqual(self.n.mail.find_thread("DJAY", "1.0"), None)
        self.tick(MORNING)
        self.assertEqual(self.gyst()["slack"]["state"], "posted")


class Pull(PullBase):
    def test_c5_jays_reply_pulls_moves_it_to_held_and_one_correction_email_lists_it(self):
        post = self.listed()
        before = self.work_dump()
        r = self.say(self.g12, thread=post["ts"])
        self.assertEqual(r["did"], "pulled")
        self.assertEqual(self.gyst()["pulls"], {self.g12: {"at": MORNING, "by": "jay:slack"}})
        reply = self.thread_replies(post["ts"])
        self.assertEqual(len(reply), 1)
        self.assertIn(f"Pulled {self.g12}: held for the next release", reply[0])
        self.assertIn("still ships with Go Live until reverted", reply[0])
        self.assertTrue(any(k == "release.pulled" and kw.get("ref") == self.g12 for k, _, kw in self.d.events))
        self.assertEqual(self.work_dump(), before)                  # ticket_work byte-identical: only withholds
        self.tick(MORNING + 20)
        [c] = self.corrections()
        digest = next(m for m in self.mails() if m["Subject"].startswith(f"{GN} release"))
        self.assertEqual((c["In-Reply-To"], c["References"]), (digest["Message-ID"], digest["Message-ID"]))
        self.assertEqual(c["Message-ID"], f"<release-gyst-{int(WED)}-c1@commandcenter>")
        self.assertEqual(c["Subject"], f"Correction: {GN} release Wed 2026-11-18 22:00 EST")
        body = c.get_payload(decode=True).decode()
        pulled, rest = body.split("Added (urgent", 1)
        self.assertIn(f"  {self.g12} Export to CSV", pulled)
        scheduled = rest.split("Scheduled this release (corrected)", 1)[1]
        self.assertIn(self.g13, scheduled)
        self.assertNotIn(self.g12, scheduled)
        self.assertEqual(self.work_dump(), before)
        items = self.pipe.release_items("gyst", WED, at(18, 12), DUE, MORNING, pulled={self.g12})
        self.assertEqual([r["key"] for r in items["scheduled"]], [self.g13])
        self.assertIn({"key": self.g12, "title": "Export to CSV", "pulled": True}, items["held"])
        self.assertEqual(self.pipe.release_items("gyst", WED, at(18, 12), DUE, MORNING),
                         {"scheduled": [{"key": self.g12, "title": "Export to CSV"},
                                        {"key": self.g13, "title": "Budget view"}], "verified": [],
                          "held": [{"key": self.g14, "title": "Held for later"}]})          # no "urgent", no mark

    def test_c5_the_thread_is_found_from_the_ledger_when_threads_was_pruned(self):
        post = self.listed()
        self.n.threads.clear()
        self.n.store.put("notify:threads", {})
        self.wipe_notifier()
        self.assertEqual(self.say(self.g12, thread=post["ts"])["did"], "pulled")

    def test_c2_unmatched_replies_change_nothing_and_each_gets_a_why(self):
        post = self.listed()
        ledger = json.dumps(self.gyst())
        self.assertEqual((self.gyst()["listed"]["held"], self.gyst()["listed"]["verified"]), ([self.g14], [self.g15]))
        cases = [("GYST-99", "GYST-99 is not in this release's list"),
                 (f"{self.g12} please", "ticket IDs only"),
                 (self.g14, f"{self.g14} is not in this release's list"),            # held
                 (self.g15, f"{self.g15} is not in this release's list"),            # verified
                 (f"{self.g12} GYST-99", "GYST-99 is not in this release's list"),
                 (" ".join(["GYST-000012"] * 18), "ticket IDs only"),                 # over 200 characters
                 (" ".join(f"GYST-{i}" for i in range(1, 22)), "at most 20 items")]
        for text, why in cases:
            r = self.say(text, thread=post["ts"])
            self.assertEqual(r["did"], "pull_refused", text)
            self.assertTrue(r["say"].startswith("Nothing pulled: "), text)
            self.assertIn(why, r["say"], text)
        self.assertEqual(len(self.thread_replies(post["ts"])), len(cases))
        self.assertEqual(json.dumps(self.gyst()), ledger)
        self.assertEqual(self.say(self.g12, thread=post["ts"])["did"], "pulled")
        r = self.say(self.g12, thread=post["ts"])
        self.assertIn("already pulled", r["say"])
        self.tick(MORNING + 20)
        self.assertEqual(len(self.corrections()), 1)

    def test_c2_all_or_nothing(self):
        post = self.listed()
        self.assertEqual(self.say(f"pull {self.g12}, GYST-99", thread=post["ts"])["did"], "pull_refused")
        self.assertNotIn("pulls", self.gyst())
        self.assertEqual(self.say("pull gyst-12, GYST-13.", thread=post["ts"])["did"], "pulled")   # as Jay types it
        self.assertEqual(set(self.gyst()["pulls"]), {self.g12, self.g13})

    def test_c2_a_top_level_message_goes_to_the_cto_as_today(self):
        self.listed()
        self.n.to_lead = mock.AsyncMock(return_value={"did": "to_lead", "project": "cto"})
        self.assertEqual(self.say(self.g12)["did"], "to_lead")
        self.n.to_lead.assert_awaited_once()
        self.assertEqual(self.n.to_lead.await_args.args[0], "cto")
        self.assertNotIn("pulls", self.gyst())

    def test_c2_after_the_window_ends_nothing_is_pulled(self):
        post = self.listed()
        self.t[0] = WED + release.WINDOW_HOURS * 3600
        r = self.say(self.g12, thread=post["ts"])
        self.assertIn("window has ended", r["say"])
        self.assertNotIn("pulls", self.gyst())

    def test_a3_after_go_live_was_sent_a_pull_is_refused_and_no_correction_goes(self):
        post = self.listed()
        self.d.night.went_live("gyst", [self.g13], now=MORNING + 5)
        self.t[0] = MORNING + 10
        r = self.say(self.g12, thread=post["ts"])
        self.assertIn("Go Live was already sent", r["say"])
        self.assertNotIn("pulls", self.gyst())
        self.tick(MORNING + 60)
        self.assertEqual(self.corrections(), [])

    def test_a_ticket_whose_live_deploy_is_approved_cannot_be_pulled(self):
        self.ts.db.execute("UPDATE ticket_work SET deploy=? WHERE ticket_id=(SELECT id FROM tickets WHERE key=?)",
                           (json.dumps({"env": "live", "requestedAt": at(17, 9), "approvedAt": at(17, 23)}),
                            self.g13))
        post = self.listed()
        self.assertIn("already approved to go live", self.say(self.g13, thread=post["ts"])["say"])

    def test_a6_other_words_in_the_release_thread_do_nothing_but_get_a_why(self):
        post = self.listed()
        before = self.work_dump()
        self.n.to_lead = mock.AsyncMock()
        self.n.approve = mock.AsyncMock()
        self.n.deploy_go = mock.AsyncMock()
        self.n.unblock = mock.AsyncMock()
        for text in ("ok", "deploy", "merge", "approve", "add GYST-14", "go live", "fix: it"):
            r = self.say(text, thread=post["ts"])
            self.assertEqual(r["did"], "pull_refused", text)
        for m in (self.n.to_lead, self.n.approve, self.n.deploy_go, self.n.unblock):
            m.assert_not_awaited()
        self.assertEqual(len(self.thread_replies(post["ts"])), 7)
        self.assertEqual(self.work_dump(), before)
        self.assertNotIn("pulls", self.gyst())


class Identity(PullBase):
    """c2: only Notifier.from_jay proves a reply is Jay's; nothing else in a release thread changes anything."""

    def assert_nothing_changed(self, ledger):
        self.assertEqual(json.dumps(self.gyst()), ledger)
        self.tick(self.t[0] + 20)
        self.assertEqual(self.corrections(), [])

    def test_c2_not_jay_bot_edit_other_team_forward_and_file_change_nothing(self):
        post = self.listed()
        ledger = json.dumps(self.gyst())
        n0 = len(self.slack_posts)
        self.say(self.g12, thread=post["ts"], bot_id="B0BOT")
        self.say(self.g12, thread=post["ts"], subtype="message_changed")
        self.say(self.g12, thread=post["ts"], user=JAY, subtype="bot_message")
        self.assertEqual(len(self.slack_posts), n0)                 # a bot or an edit: dropped without a trace
        r1 = self.say(self.g12, thread=post["ts"], attachments=[{"text": "GYST-12"}])
        r2 = self.say(self.g12, thread=post["ts"], files=[{"id": "F1"}])
        self.assertEqual((r1["did"], r2["did"]), ("pull_refused", "pull_refused"))
        self.assertIn("forwarded or shared", r1["say"])
        self.assertEqual(len(self.thread_replies(post["ts"])), 2)   # Jay's own replies get the why in the thread
        self.assert_nothing_changed(ledger)

    def test_c2_a_human_who_is_not_jay_gets_jay_one_fixed_dm_and_nothing_in_the_thread(self):
        post = self.listed()
        ledger = json.dumps(self.gyst())
        n0 = len(self.slack_posts)
        self.assertIsNone(self.say(self.g12, thread=post["ts"], user="U0OTHER01"))
        new = self.slack_posts[n0:]
        self.assertEqual(new, [{"channel": "DJAY", "text": f"A message in the {GN} release thread was not from you; "
                                                          "nothing changed.", "thread": None, "ts": new[0]["ts"]}])
        self.say(self.g12, thread=post["ts"], user="U0OTHER02")            # within 10 min: no second DM
        self.say(self.g12, thread=post["ts"], user=JAY, team="T0OTHER")    # another team is not Jay either
        self.assertEqual(len(self.slack_posts), n0 + 1)
        self.t[0] += releasemail.FOREIGN_GAP
        self.say(self.g12, thread=post["ts"], user="U0OTHER01")
        self.assertEqual(len(self.slack_posts), n0 + 2)
        self.assertEqual(self.thread_replies(post["ts"]), [])
        self.assert_nothing_changed(ledger)

    def test_the_notice_waits_for_quiet_hours_to_end_and_goes_once(self):
        post = self.listed()
        n0 = len(self.slack_posts)
        self.t[0] = at(18, 23)                                      # Wed 23:00: quiet hours
        self.say(self.g12, thread=post["ts"], user="U0OTHER01")
        self.say(self.g12, thread=post["ts"], user="U0OTHER02")
        self.tick(at(18, 23, 30))
        self.tick(at(19, 6, 59))
        self.assertEqual(len(self.slack_posts), n0)                 # nothing pings Jay in quiet hours
        self.tick(at(19, 7))
        new = self.slack_posts[n0:]
        self.assertEqual([(p["channel"], p["thread"], p["text"]) for p in new],
                         [("DJAY", None, f"A message in the {GN} release thread was not from you; nothing changed.")])
        self.tick(at(19, 7, 1))
        self.say(self.g12, thread=post["ts"], user="U0OTHER01")    # within 10 min of the notice
        self.assertEqual(len(self.slack_posts), n0 + 1)

    def test_a5_no_sender_or_text_is_kept_jays_marks_survive_and_another_channel_is_ignored(self):
        post = self.listed()
        self.n.to_lead = mock.AsyncMock(return_value={"did": "to_lead", "project": "cto"})
        self.assertEqual(self.say(self.g13, thread="999.0")["did"], "to_lead")       # Jay's own message: one mark
        mark = self.n.seen_events[-1]
        secret = "U0OTHERSECRET"
        text = "GYST-12 hunter2-synthetic"
        n0 = len(self.slack_posts)
        self.say(text, thread=post["ts"], user=secret, channel="CGY")          # same ts, another channel
        self.assertEqual(len(self.slack_posts), n0)
        events0 = len(self.d.events)
        with self.assertLogs("ccd", level="DEBUG") as logs:
            import logging
            logging.getLogger("ccd").debug("marker")
            for i in range(1100):
                self.say(text, thread=post["ts"], user=secret)
        self.assertIn(mark, self.n.seen_events)
        self.assertEqual(len(self.slack_posts), n0 + 1)
        dump = json.dumps([e for e in self.d.events[events0:]], default=str) + json.dumps(logs.output)
        dump += json.dumps(self.store.db.execute("SELECT key, value FROM kv").fetchall())
        dump += json.dumps(self.n.mail.alerts()) + json.dumps(self.n.status)
        for needle in (secret, "hunter2"):
            self.assertNotIn(needle, dump)
        # No length either: the only event is the fixed notice, carrying its kind and nothing else.
        self.assertEqual([(k, kw["data"]) for k, _, kw in self.d.events[events0:]],
                         [("release.foreign_reply", {"kind": "release.foreign_reply"})])

    def test_c2_a_non_jay_message_in_a_ticket_thread_or_a_channel_still_posts_nothing(self):
        self.listed()
        self.n.tickets["GYST-12"] = {"channel": "gyst", "ts": "77.0", "project": "gyst"}
        self.n._ids = {"gyst": "CGY", "cto": "CCTO"}
        n0 = len(self.slack_posts)
        self.say("GYST-12", thread="77.0", user="U0OTHER01", channel="CGY")
        self.say("GYST-12", user="U0OTHER01", channel="CGY")
        self.say("GYST-12", user="U0OTHER01")
        self.assertEqual(len(self.slack_posts), n0)


class Corrections(PullBase):
    def pull(self, key, post):
        self.assertEqual(self.say(key, thread=post["ts"])["did"], "pulled")

    def test_c3_two_pulls_send_two_corrections_each_with_only_its_new_key(self):
        post = self.listed()
        self.pull(self.g12, post)
        self.tick(MORNING + 20)
        self.tick(MORNING + 40)
        self.assertEqual(len(self.corrections()), 1)
        self.t[0] = MORNING + 3600
        self.pull(self.g13, post)
        self.tick(MORNING + 3620)
        first, second = self.corrections()
        self.assertEqual(second["Message-ID"], f"<release-gyst-{int(WED)}-c2@commandcenter>")
        pulled = second.get_payload(decode=True).decode().split("Added (urgent", 1)[0]
        self.assertIn(self.g13, pulled)
        self.assertNotIn(self.g12, pulled)
        self.assertEqual([c["keys"] for c in self.gyst()["corrections"]], [[self.g12], [self.g13]])
        self.wipe_notifier()
        self.tick(MORNING + 7200)
        self.assertEqual(len(self.corrections()), 2)                # a restart sends no repeat

    def test_c3_an_urgent_approval_after_the_digest_sends_one_correction(self):
        self.listed()
        urgent = self.ticket_n("gyst", 20, "Hotfix login", merge_at=at(18, 8),
                               deploy={"env": "live", "requestedAt": at(18, 8), "approvedAt": at(18, 8, 5),
                                       "urgent": True})
        self.tick(at(18, 8, 10))
        [c] = self.corrections()
        body = c.get_payload(decode=True).decode()
        added = body.split("Added (urgent, outside the release window)", 1)[1].split("Scheduled", 1)[0]
        self.assertIn(f"{urgent} Hotfix login", added)
        self.tick(at(18, 9))
        self.assertEqual(len(self.corrections()), 1)

    def test_c3_no_correction_without_an_outstanding_digest_or_with_release_email_off(self):
        self.ticket_n("gyst", 20, "Hotfix", deploy={"env": "live", "requestedAt": at(16), "approvedAt": at(16, 1),
                                                     "urgent": True})
        self.tick(at(17, 8))                                        # no digest yet
        self.assertEqual(self.server.sent, [])
        post = self.listed()
        self.n.update_settings({"releaseMail": False})
        self.assertEqual(self.say(self.g12, thread=post["ts"])["did"], "pulled")
        self.assertNotIn("correction email follows", self.thread_replies(post["ts"])[0])
        self.ticket_n("gyst", 21, "Hotfix 2", deploy={"env": "live", "requestedAt": at(18, 8),
                                                       "approvedAt": at(18, 8, 1), "urgent": True})
        self.tick(at(18, 9))
        self.assertEqual(self.corrections(), [])
        self.assertEqual(releasemail.pulled(self.store, "gyst"), {self.g12})   # the pull itself stands

    def test_c3_a_connection_lost_during_data_is_uncertain_never_resent_and_alerts(self):
        post = self.listed()
        self.pull(self.g12, post)
        self.server.fail = "data"
        self.tick(MORNING + 20)
        c = self.gyst()["corrections"][0]
        self.assertEqual((c["state"], c["uncertain"]), ("failed", True))
        self.assertIn(f"{GN} release correction email may not have been sent, not retried",
                      [a["text"] for a in self.n.mail.alerts()])
        self.server.fail = None
        self.tick(MORNING + 400)
        self.wipe_notifier()
        self.tick(MORNING + 800)
        self.assertEqual(self.corrections(), [])
        self.assertEqual(len(self.gyst()["corrections"]), 1)

    def test_c3_a_definite_failure_is_retried_once_after_300_s_and_a_second_alerts(self):
        post = self.listed()
        self.pull(self.g12, post)
        self.server.fail = "rcpt"
        self.tick(MORNING + 20)
        self.assertIn(f"{GN} release correction email failed, retrying once", [a["text"] for a in self.n.mail.alerts()])
        self.tick(MORNING + 319)
        self.assertEqual(self.gyst()["corrections"][0]["attempts"], 1)
        self.tick(MORNING + 320)
        self.assertEqual(self.gyst()["corrections"][0]["attempts"], 2)
        self.assertIn(f"{GN} release correction email failed twice, not sent",
                      [a["text"] for a in self.n.mail.alerts()])
        self.server.fail = None
        self.tick(MORNING + 1200)
        self.assertEqual(self.corrections(), [])

    def test_a_definite_failure_then_a_retry_that_goes(self):
        post = self.listed()
        self.pull(self.g12, post)
        self.server.fail = "rcpt"
        self.tick(MORNING + 20)
        self.server.fail = None
        self.tick(MORNING + 320)
        [c] = self.corrections()
        self.assertEqual(c["Message-ID"], f"<release-gyst-{int(WED)}-c1@commandcenter>")
        self.assertEqual(self.n.mail.alerts(), [])

    def test_a_sending_correction_at_a_restart_is_closed_uncertain(self):
        post = self.listed()
        self.pull(self.g12, post)
        row = self.gyst()
        row["corrections"] = [{"n": 1, "keys": [self.g12], "urgent": [], "state": "sending", "uncertain": False,
                               "attempts": 1, "at": MORNING, "sentAt": None, "error": None, "messageId": "<x>"}]
        self.n.mail._save("gyst")
        self.wipe_notifier()
        self.assertEqual((self.gyst()["corrections"][0]["state"], self.gyst()["corrections"][0]["uncertain"]),
                         ("failed", True))
        self.tick(MORNING + 600)
        self.assertEqual(self.corrections(), [])

    def test_a7_a_client_project_correction_has_ids_only_and_titles_are_cleaned(self):
        self.n = self.notifier({"client_projects": ["gyst"]})
        self.ts.db.execute("UPDATE tickets SET title=? WHERE key=?",
                           ("Export\x1b[31m to CSV token=ghp_" + "a" * 36, self.g13))
        post = self.listed()
        self.assertNotIn("Export", post["text"])
        self.pull(self.g12, post)
        self.tick(MORNING + 20)
        body = self.corrections()[0].get_payload(decode=True).decode()
        self.assertIn(self.g12, body)
        self.assertNotIn("Export", body)
        self.n = self.notifier()
        self.t[0] = MORNING + 3600
        self.pull(self.g13, post)
        self.tick(MORNING + 3620)
        body = self.corrections()[1].get_payload(decode=True).decode()
        self.assertIn(f"{self.g13} Export", body)
        self.assertNotIn("\x1b", body)
        self.assertNotIn("a" * 36, body)

    def test_the_slack_list_cleans_titles_too(self):
        self.ts.db.execute("UPDATE tickets SET title=? WHERE key=?", ("Budget\x07 view <!channel>", self.g13))
        post = self.listed()
        self.assertNotIn("\x07", post["text"])
        self.assertNotIn("<!channel>", post["text"])


class GoLivePulls(PullBase):
    def setUp(self):
        super().setUp()
        from ccd.daemon import Daemon
        from .helpers import cfg
        self.real = Daemon(cfg(meter={"enabled": False}), self.store, None, tasks=self.ts)
        self.real._to_coordinator = mock.AsyncMock(return_value="gyst-lead")
        for key in (self.g12, self.g13):
            self.ts.db.execute("UPDATE ticket_work SET gate='deploy', deploy=? WHERE ticket_id=(SELECT id FROM tickets "
                               "WHERE key=?)", (json.dumps({"env": "live", "requestedAt": at(17, 11)}), key))

    def go_live(self, keys):
        return run(self.real.act_go_live("gyst", "jay", True, keys))

    def deploy(self, key):
        return self.real.pipeline.work(key).get("deploy") or {}

    def test_c4_a_pulled_item_leaves_approves_with_a_warning_and_go_live_skips_it(self):
        post = self.listed()
        self.pull_it(post)
        review = self.real.go_live_review("gyst")
        self.assertEqual([a["key"] for a in review["approves"]], [self.g13])
        self.assertIn({"key": self.g12, "title": "Export to CSV", "reason": releasemail.PULL_REASON},
                      review["warnings"])
        self.assertEqual(releasemail.PULL_REASON, "pulled from this release: its code still ships until reverted")
        self.assertIsNone(self.real._go_live_blocked("gyst"))
        r = self.go_live([self.g12, self.g13])
        self.assertEqual(r["approved"], [self.g13])
        self.assertEqual(r["skipped"], [{"key": self.g12, "reason": releasemail.PULL_REASON}])
        self.assertIsNone(self.deploy(self.g12).get("approvedAt"))
        self.assertEqual(self.real.pipeline.work(self.g12)["gate"], "deploy")     # waits for the next window

    def pull_it(self, post):
        self.assertEqual(self.say(self.g12, thread=post["ts"])["did"], "pulled")

    def test_a1_a_pull_lasts_past_the_window_until_the_next_digest(self):
        post = self.listed()
        self.pull_it(post)
        self.t[0] = WED + 6 * 3600                                  # long after the window ended
        self.assertNotIn(self.g12, [a["key"] for a in self.real.go_live_review("gyst")["approves"]])
        self.assertEqual(self.go_live([self.g12])["skipped"], [{"key": self.g12, "reason": releasemail.PULL_REASON}])
        self.tick(at(24, 22))                                       # the next digest
        self.assertEqual(releasemail.pulled(self.store, "gyst"), set())
        self.assertIn(self.g12, self.gyst()["listed"]["scheduled"])
        self.assertIn(self.g12, [a["key"] for a in self.real.go_live_review("gyst")["approves"]])

    def test_a2_a_pull_applies_with_release_email_slack_or_the_notifier_off(self):
        post = self.listed()
        self.pull_it(post)
        self.n.update_settings({"releaseMail": False, "slack": False})
        self.assertNotIn(self.g12, [a["key"] for a in self.real.go_live_review("gyst")["approves"]])
        self.assertIsNone(self.real.notifier)
        self.assertEqual(self.go_live([self.g12])["approved"], [])

    def test_a4_a_pull_while_the_coordinator_message_is_sent_leaves_the_key_unapproved(self):
        post = self.listed()
        test = self

        async def meanwhile(*a, **k):
            r = await test.n.on_slack({"team_id": TEAM, "event_id": "EvA4", "event": {
                "type": "message", "user": JAY, "text": test.g12, "channel": "DJAY", "ts": "500.0",
                "thread_ts": post["ts"], "team": TEAM}})
            test.assertEqual(r["did"], "pulled")
            return "gyst-lead"
        self.real._to_coordinator = meanwhile
        r = self.go_live([self.g12, self.g13])
        self.assertEqual(r["approved"], [self.g13])
        self.assertEqual(r["skipped"], [{"key": self.g12, "reason": releasemail.PULL_REASON}])
        self.assertIsNone(self.deploy(self.g12).get("approvedAt"))

    def test_safety_a_pull_writes_no_ticket_state_and_releasemail_names_no_ship_step(self):
        post = self.listed()
        before = self.work_dump()
        self.pull_it(post)
        self.tick(MORNING + 20)
        self.assertEqual(len(self.corrections()), 1)
        self.assertEqual(self.work_dump(), before)
        src = Path(releasemail.__file__).read_text()
        for word in ("confirm", "deploy_go", "deployed", "deploy_request", "act_go_live"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
