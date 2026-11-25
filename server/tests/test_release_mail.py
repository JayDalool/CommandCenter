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
        self.n.mail.run, real = boom, self.n.mail.run
        self.n.check_needs = needs
        self.tick(DUE)
        self.assertEqual(called, ["needs"])
        self.assertTrue(any("release mail" in str(e) for e in self.d.events))
        self.n.mail.run = real

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
        before = dump()
        self.tick(DUE)
        self.assertEqual(len(self.server.sent), 1)
        self.assertEqual(dump(), before)
        src = Path(releasemail.__file__).read_text()
        for word in ("confirm", "deploy_go", "deployed", "deploy_request", "act_go_live"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
