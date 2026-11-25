"""Release email (CC-078): one digest to Jay per live app, 24 h before its release window.

Off until Jay switches "Release email" on (notify setting releaseMail, Settings, Developer Unlock). Mail settings and
Jay's address live only in ~/.config/command-center/mail.env (0600, path CCD_MAIL_ENV for tests): never in the repo,
ccd.db, events, logs or GET /api/notify. The mail path only reads tickets (Pipeline.release_items) and changes no
ticket, gate or release state, so Go Live still needs Jay's press (c9).

Never two emails for one app and window (c6). The ledger row is written as `sending` BEFORE the SMTP call, so a
crash mid-send leaves a row that closes as failed+uncertain at the next start, and an uncertain failure (the
connection died during DATA, so the mail may have been accepted) is never retried. The cost of that choice: an
uncertain failure may mean no email, which Jay sees as an alert.
"""
import datetime
import email.policy
import email.utils
import json
import re
import smtplib
import ssl
import time
import zoneinfo
from email.message import EmailMessage

from . import release as release_mod
from .security import redact

SMTP_TIMEOUT = 30           # s, every blocking SMTP step
RETRY_AFTER = 300           # s between a definite failure and its one retry
LEDGER_MAX = 12
FIRST_LOOKBACK = 7 * 86400  # the first digest's "verified" section reaches back a week
ADDR_RE = re.compile(r"^[^@\s,;<>()\[\]\\\"]+@[^@\s,;<>()\[\]\\\"]+\.[^@\s,;<>()\[\]\\\"]+$")
SECTIONS = ("Scheduled this release", "Verified in production since last digest", "Held")


class MailError(Exception):
    """`uncertain`: the failure came during or after DATA, so the server may have accepted the message."""

    def __init__(self, what, uncertain=False):
        super().__init__(what)
        self.what = what
        self.uncertain = uncertain


def mail_config(env):
    """The settings from mail.env, or MailError (definite) naming only the key that is wrong, never a value."""
    for k in ("MAIL_HOST", "MAIL_PORT", "MAIL_USER", "MAIL_PASSWORD", "MAIL_FROM", "MAIL_TO"):
        if not env.get(k):
            raise MailError(f"mail.env is missing {k}")
    try:
        port = int(env["MAIL_PORT"])
    except ValueError:
        raise MailError("MAIL_PORT must be 465 or 587") from None
    if port not in (465, 587):
        # Port 25 and the rest would allow plain text; only implicit TLS (465) and STARTTLS (587) are used.
        raise MailError("MAIL_PORT must be 465 or 587")
    if not ADDR_RE.match(env["MAIL_FROM"]):
        raise MailError("MAIL_FROM must be one address")
    if not ADDR_RE.match(env["MAIL_TO"]):
        raise MailError("MAIL_TO must be exactly one address")
    return {"host": env["MAIL_HOST"], "port": port, "user": env["MAIL_USER"], "password": env["MAIL_PASSWORD"],
            "from": env["MAIL_FROM"], "to": env["MAIL_TO"]}


def _why(stage, e):
    """What to record about a failure: the step and the exception class (and SMTP code), never the server's text,
    which can carry the address, and never the password."""
    code = getattr(e, "smtp_code", None)
    return f"{stage}: {type(e).__name__}" + (f" {code}" if isinstance(code, int) else "")


def deliver(conf, msg):
    """Send `msg` (an EmailMessage) over verified TLS, step by step. Raises MailError; `uncertain` is set when the
    failure is during or after DATA. Blocking: the notifier runs it in a thread."""
    ctx = ssl.create_default_context()      # CERT_REQUIRED and check_hostname: never an unverified certificate
    stage = "connect"
    smtp = None
    try:
        if conf["port"] == 465:
            smtp = smtplib.SMTP_SSL(conf["host"], conf["port"], timeout=SMTP_TIMEOUT, context=ctx)
        else:
            smtp = smtplib.SMTP(conf["host"], conf["port"], timeout=SMTP_TIMEOUT)
            stage = "ehlo"
            smtp.ehlo()
            stage = "tls"
            if not smtp.has_extn("starttls"):
                raise MailError("tls: STARTTLS not offered")
            smtp.starttls(context=ctx)
        stage = "ehlo"
        smtp.ehlo()
        stage = "login"
        smtp.login(conf["user"], conf["password"])
        stage = "mail"
        code, _ = smtp.mail(conf["from"])
        if code != 250:
            raise MailError(f"mail: {code}")
        stage = "rcpt"
        code, _ = smtp.rcpt(conf["to"])
        if code not in (250, 251):
            raise MailError(f"rcpt: {code}")
        stage = "data"
        code, _ = smtp.data(msg.as_bytes(policy=email.policy.SMTP))
        if code != 250:
            raise MailError(f"data: {code}", uncertain=True)
    except MailError as e:
        raise MailError(e.what, uncertain=e.uncertain or stage == "data") from None
    except Exception as e:  # noqa: BLE001 — every failure is classified, none escapes as an exception type
        raise MailError(_why(stage, e), uncertain=stage == "data") from None
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001 — the message is already settled; a failed goodbye changes nothing
                pass


def _num(key):
    tail = key.rsplit("-", 1)[-1]
    return (key.rsplit("-", 1)[0], int(tail) if tail.isdigit() else 0)


class ReleaseMail:
    """Owned by the Notifier: due time, ledger, rendering and the send."""

    def __init__(self, notifier):
        self.n = notifier
        self.rows = {}                  # project -> ledger rows, newest first
        self.config_alerts = {}         # project -> window start, while mail.env stops a due digest
        self._config_failed = set()     # (project, window) already reported

    # ----- ledger -----

    def ledger(self, project):
        if project not in self.rows:
            self.rows[project] = list(self.n.store.get(f"release_mail:{project}", [])[0] or [])
        return self.rows[project]

    def _save(self, project):
        self.rows[project] = self.rows[project][:LEDGER_MAX]
        self.n.store.put(f"release_mail:{project}", self.rows[project])
        dirty = getattr(self.n.d, "_dirty", None)
        if dirty is not None:
            dirty.set()             # the alert is derived from the ledger

    def sweep(self):
        """A row still `sending` at start means ccd died mid-send: the message may or may not have gone. Close it
        as failed+uncertain; it is never resent."""
        for p in self._projects():
            changed = False
            for r in self.ledger(p):
                if r["state"] == "sending":
                    r.update(state="failed", uncertain=True, error="ccd stopped during the send")
                    changed = True
            if changed:
                self._save(p)
                self.n._fail("release mail", f"{p}: may not have been sent (ccd stopped during the send)")

    def _projects(self):
        return [p["key"] for p in self.n.d._projects()]

    def last(self):
        """The newest row over all apps, for GET /api/notify: no address, no error text."""
        best = None
        for p in self._projects():
            rows = self.ledger(p)
            if rows and (best is None or (rows[0]["at"] or 0) > (best[1]["at"] or 0)):
                best = (p, rows[0])
        if not best:
            return None
        return {"project": best[0], "window": best[1]["window"], "state": best[1]["state"], "at": best[1]["at"]}

    def alerts(self):
        out = []
        now = self.n.clock()
        for p in self._projects():
            rows = self.ledger(p)
            if rows and rows[0]["state"] == "failed":
                r = rows[0]
                name = self.n.name(p)
                if r["uncertain"]:
                    text = f"{name} release email may not have been sent, not retried"
                elif r["attempts"] >= 2:
                    text = f"{name} release email failed twice, not sent"
                elif now < r["window"]:
                    text = f"{name} release email failed, retrying once"
                else:
                    text = f"{name} release email failed, not sent"
                out.append({"id": f"mail:{p}:{r['window']}", "severity": "warn", "source": "notify", "project": p,
                            "text": text})
            w = self.config_alerts.get(p)
            if w and now < w:
                out.append({"id": f"mail:{p}:{w}", "severity": "warn", "source": "notify", "project": p,
                            "text": f"{self.n.name(p)} release email not sent: mail.env is not usable"})
        return out

    # ----- when -----

    @staticmethod
    def due_window(window, now):
        """(W, due, cutoff): W is the next window that has not started (a running one is never mailed), due is
        its start on the previous local date. Wall clock, so a clock change between them keeps the hour."""
        start, cutoff = release_mod.next_window(window, now)
        tz = zoneinfo.ZoneInfo(window.get("tz") or release_mod.DEFAULT_WINDOW["tz"])
        day = datetime.datetime.fromtimestamp(start, tz).date() - datetime.timedelta(days=1)
        return start, release_mod.window_start(window, day), cutoff

    # ----- content -----

    def render(self, project, start, cutoff, items):
        n = self.n
        window = self.n.d.releases.window
        tz = zoneinfo.ZoneInfo(window.get("tz") or release_mod.DEFAULT_WINDOW["tz"])

        def local(ts):
            return datetime.datetime.fromtimestamp(ts, tz).strftime("%a %Y-%m-%d %H:%M %Z")
        keys_only = n.client(project)       # a client project's mail carries IDs only, as its Slack posts do
        name = n.name(project)
        lines = [f"{name} release {local(start)}", ""]
        for heading, key in zip(SECTIONS, ("scheduled", "verified", "held")):
            lines.append(heading)
            rows = items[key]
            if not rows:
                lines.append("  None")
            for r in rows:
                title = "" if keys_only else " " + re.sub(r"[\x00-\x1f\x7f]+", " ", str(r["title"])).strip()[:100]
                lines.append(f"  {r['key']}{title}")
            lines.append("")
        # The digest is a snapshot at due time; what merges before the cutoff still joins this release (CC-078, the
        # lead's decision on the plan question): Go Live shows the final list before Jay presses it.
        lines.append(f"Changes merged before {local(cutoff)} also join this release; Go Live lists them before you "
                     "press it.")
        link = n.link()
        if link:
            lines.append(f"Command Center: {link}")
        subject = f"{name} release {local(start)}: {len(items['scheduled'])} scheduled"
        return subject, redact("\n".join(lines) + "\n")[0]

    def message(self, conf, subject, body, mid, now):
        m = EmailMessage()
        m["From"] = conf["from"]
        m["To"] = conf["to"]
        m["Subject"] = subject
        m["Date"] = email.utils.formatdate(now, localtime=False)
        m["Message-ID"] = mid
        m.set_content(body, charset="utf-8", cte="quoted-printable")
        return m

    # ----- the step -----

    def config(self):
        from . import notify    # read_env lives there; imported late because notify imports this module
        try:
            env = notify.read_env(self.n.mail_env_path)
            if not env:
                return None, "No mail settings on jay-server (mail.env)"
            return mail_config(env), None
        except notify.SlackError as e:
            return None, str(e)
        except MailError as e:
            return None, e.what

    async def run(self):
        """One tick. Never raises past the notifier; each app is independent."""
        n = self.n
        if n.d.releases is None or getattr(n.d, "pipeline", None) is None:
            return
        now = n.clock()
        for p in self._projects():
            if not n.d.releases.live(p):
                self.config_alerts.pop(p, None)
                continue
            try:
                await self._project(p, now)
            except Exception as e:  # noqa: BLE001 — one app's failure must not stop the others
                n._fail("release mail", f"{p}: {type(e).__name__}")

    async def _project(self, p, now):
        n = self.n
        window = n.d.releases.window
        start, due, cutoff = self.due_window(window, now)
        rows = self.ledger(p)
        newest = rows[0] if rows else None
        retry = False
        if newest and newest["window"] == start:
            # The same digest: delivered or sending is final; a failure is retried once, only if definite.
            if newest["state"] != "failed" or newest["uncertain"] or newest["attempts"] >= 2:
                return
            if now < newest["at"] + RETRY_AFTER or now >= start:
                return
            retry = True
        elif newest and start < newest["window"] + release_mod.WINDOW_HOURS * 3600:
            return      # a window moved within the release already mailed (or earlier): never a second email
        elif not (due <= now < start):
            self.config_alerts.pop(p, None)
            return
        conf, error = self.config()
        if conf is None:
            self.config_alerts[p] = start
            if (p, start) not in self._config_failed:
                self._config_failed.add((p, start))
                n._fail("release mail", f"{p}: {error}")
            return
        self.config_alerts.pop(p, None)
        since = next((r["sentAt"] for r in rows if r["state"] == "delivered" and r.get("sentAt")), now - FIRST_LOOKBACK)
        items = n.d.pipeline.release_items(p, start, cutoff, since, now)
        subject, body = self.render(p, start, cutoff, items)
        mid = f"<release-{p}-{int(start)}@commandcenter>"
        row = newest if retry else {"window": start, "due": due, "state": "sending", "uncertain": False,
                                    "attempts": 0, "at": now, "sentAt": None, "messageId": mid, "error": None,
                                    "listed": {}}
        row.update(state="sending", attempts=row["attempts"] + 1, at=now, error=None,
                   listed={k: [r["key"] for r in v] for k, v in items.items()})
        if not retry:
            rows.insert(0, row)
        self._save(p)           # BEFORE the send: whatever happens next, this app and window has an attempt on record
        try:
            await n._call(deliver, conf, self.message(conf, subject, body, mid, now))
        except MailError as e:
            row.update(state="failed", uncertain=e.uncertain, error=e.what)
            self._save(p)
            n._fail("release mail", f"{p}: {e.what}")
            return
        row.update(state="delivered", sentAt=n.clock(), error=None)
        self._save(p)
        n.status.update(lastSentAt=n.clock())

    async def send_test(self):
        """Jay's check of mail.env before a real digest: one short mail, no ledger row."""
        conf, error = self.config()
        if conf is None:
            self.n._fail("release mail test", error)
            return False
        now = self.n.clock()
        try:
            msg = self.message(conf, "CommandCenter test: release email works",
                               "This is a test. Release digests go to this address when Release email is on.\n",
                               f"<release-test-{int(now)}@commandcenter>", now)
            await self.n._call(deliver, conf, msg)
            return True
        except MailError as e:
            self.n._fail("release mail test", e.what)
            return False

    def status(self):
        conf, error = self.config()
        return {"configured": conf is not None, "error": error, "last": self.last()}
