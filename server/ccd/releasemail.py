"""Release email (CC-078): one digest to Jay per live app, 24 h before its release window.

Off until Jay switches "Release email" on (notify setting releaseMail, Settings, Developer Unlock). Mail settings and
Jay's address live only in ~/.config/command-center/mail.env (0600, path CCD_MAIL_ENV for tests): never in the repo,
ccd.db, events, logs or GET /api/notify. The mail path only reads tickets (Pipeline.release_items) and changes no
ticket, gate or release state, so Go Live still needs Jay's press (c9).

Never two emails for one app and window (c6). The ledger row is written as `sending` BEFORE the SMTP call, so a
crash mid-send leaves a row that closes as failed+uncertain at the next start, and an uncertain failure (the
connection died during DATA, so the mail may have been accepted) is never retried. The cost of that choice: an
uncertain failure may mean no email, which Jay sees as an alert.

Pulls by Slack (CC-088). After a digest is delivered, one DM to Jay per app lists its Scheduled items, held until
quiet hours end (Jay's answer on the plan). Jay's reply in that thread with ticket IDs pulls them: the pull is
recorded in the digest's ledger row and nothing else, so it only withholds (Go Live leaves the item out with a
warning; its code is on main and still ships until reverted). Only Notifier.from_jay proves a reply is Jay's. A pull,
or an urgent live deploy Jay approved after the digest, sends one correction email, with the digest's never-twice
rules: its ledger entry is written before the send and an uncertain failure is never retried.
"""
import collections
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
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]+")
# CC-088. A pull's grammar: only ticket IDs, optionally after "pull". Anything else in the thread is refused with a
# why, so "ok", "deploy" or "add GYST-14" there never reaches an approval or the lead (tech review A6).
KEY_RE = re.compile(r"^[A-Za-z]{1,8}-\d{1,6}$")
PULL_TEXT_MAX = 200
PULL_KEYS_MAX = 20
CORRECTIONS_MAX = 10        # correction emails per digest
FOREIGN_GAP = 600           # s: at most one "not from you" DM per release thread in this time
PULL_REASON = "pulled from this release: its code still ships until reverted"


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


def pulled(store, project):
    """CC-088: the ticket keys Jay pulled from the app's newest digest. Read from ccd.db on every call, so Go Live sees
    a pull with Slack, Release email or the notifier off (tech review A2). A pull lasts until the app's next digest
    row, not until its window ends: Go Live is Jay's press at any time (A1)."""
    rows = store.get(f"release_mail:{project}", [])[0] or []
    return set(rows[0].get("pulls") or {}) if rows else set()


def parse_pull(text):
    """The ticket keys of a pull reply ("GYST-12", "pull GYST-12, GYST-13"), upper-cased and in order, or None when
    the text is anything else ("GYST-12 please" too: all or nothing)."""
    words = [w for w in re.split(r"[\s,]+", text.strip().rstrip(".!")) if w]
    if words and words[0].lower() == "pull":
        words = words[1:]
    if not words or not all(KEY_RE.match(w) for w in words):
        return None
    return list(dict.fromkeys(w.upper() for w in words))


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
        # The "not from you" notice (CC-088): in memory only, apart from Jay's seen_events so a flood of foreign
        # messages cannot evict his marks, and holding no sender, text or length (tech review A5).
        self._foreign_at = {}           # "channel:thread" -> when the notice was last sent
        self._foreign_seen = collections.deque(maxlen=200)

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
                # The same rule for a correction email and the Slack list (CC-088): either may have gone out.
                for c in r.get("corrections") or []:
                    if c["state"] == "sending":
                        c.update(state="failed", uncertain=True, error="ccd stopped during the send")
                        changed = True
                if (r.get("slack") or {}).get("state") == "posting":
                    r["slack"].update(state="failed", uncertain=True)
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
            if rows and rows[0]["state"] == "delivered":
                out += self._row_alerts(p, rows[0])
            w = self.config_alerts.get(p)
            if w and now < w:
                out.append({"id": f"mail:{p}:{w}", "severity": "warn", "source": "notify", "project": p,
                            "text": f"{self.n.name(p)} release email not sent: mail.env is not usable"})
        return out

    def _row_alerts(self, p, r):
        """A delivered digest's failed Slack list or correction email (CC-088, tech review A7)."""
        out, name = [], self.n.name(p)
        s = r.get("slack") or {}
        if s.get("state") == "failed":
            final = s.get("uncertain") or s["attempts"] >= 2
            out.append({"id": f"mail:{p}:{r['window']}:slack", "severity": "warn", "source": "notify", "project": p,
                        "text": f"{name} release list not posted in Slack" + (": pulls by Slack unavailable" if final
                                                                             else ", retrying once")})
        c = (r.get("corrections") or [None])[-1]
        if c and c["state"] == "failed":
            text = (f"{name} release correction email may not have been sent, not retried" if c["uncertain"]
                    else f"{name} release correction email failed twice, not sent" if c["attempts"] >= 2
                    else f"{name} release correction email failed, retrying once")
            out.append({"id": f"mail:{p}:{r['window']}:c{c['n']}", "severity": "warn", "source": "notify",
                        "project": p, "text": text})
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

    def _local(self, ts):
        window = self.n.d.releases.window
        tz = zoneinfo.ZoneInfo(window.get("tz") or release_mod.DEFAULT_WINDOW["tz"])
        return datetime.datetime.fromtimestamp(ts, tz).strftime("%a %Y-%m-%d %H:%M %Z")

    def _line(self, project, key, title):
        """One item: its key, and its title without control characters unless the project is a client's (IDs only,
        as its Slack posts). Shared by the digest, the correction email and the Slack list (tech review A7)."""
        if self.n.client(project):
            return key
        return f"{key} {CTRL_RE.sub(' ', str(title or '')).strip()[:100]}".rstrip()

    def _section(self, lines, heading, project, rows):
        lines.append(heading)
        if not rows:
            lines.append("  None")
        for r in rows:
            lines.append("  " + self._line(project, r["key"], r["title"]))
        lines.append("")

    def render(self, project, start, cutoff, items):
        n = self.n
        local = self._local
        name = n.name(project)
        lines = [f"{name} release {local(start)}", ""]
        for heading, key in zip(SECTIONS, ("scheduled", "verified", "held")):
            self._section(lines, heading, project, items[key])
        # The digest is a snapshot at due time; what merges before the cutoff still joins this release (CC-078, the
        # lead's decision on the plan question): Go Live shows the final list before Jay presses it.
        lines.append(f"Changes merged before {local(cutoff)} also join this release; Go Live lists them before you "
                     "press it.")
        if n.settings["slack"]:
            lines.append("To pull an item from this release, reply with its ticket ID in the Slack message for this "
                         "release (in your DM after quiet hours).")
        link = n.link()
        if link:
            lines.append(f"Command Center: {link}")
        subject = f"{name} release {local(start)}: {len(items['scheduled'])} scheduled"
        return subject, redact("\n".join(lines) + "\n")[0]

    def message(self, conf, subject, body, mid, now, reply_to=None):
        m = EmailMessage()
        m["From"] = conf["from"]
        m["To"] = conf["to"]
        m["Subject"] = subject
        m["Date"] = email.utils.formatdate(now, localtime=False)
        m["Message-ID"] = mid
        if reply_to:
            # A correction threads under its digest in Jay's mail client.
            m["In-Reply-To"] = reply_to
            m["References"] = reply_to
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
        for p in self._projects():
            # Re-read the switch and the clock for every app: a slow send must not carry the batch past Jay turning
            # Release email off, or past a window start (Codex review of CC-078).
            if not n.settings["releaseMail"]:
                return
            now = n.clock()
            if not n.d.releases.live(p):
                self.config_alerts.pop(p, None)
                continue
            try:
                await self._project(p, now)
                await self.correct(p)
                await self.slack_list(p)
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

    # ----- pulls by Slack (CC-088) -----

    def _ended(self, row, now):
        return now >= row["window"] + release_mod.WINDOW_HOURS * 3600

    def _went_live(self, p, row):
        """Whether Go Live was sent for the app after this digest went out (tech review A3): what it listed has
        already been sent to production, so a pull or a list would be wrong."""
        night = getattr(self.n.d, "night", None)
        at = (night.get(p) if night is not None else {}).get("goLiveAt")
        return bool(at and row.get("sentAt") and at >= row["sentAt"])

    def _titles(self, p):
        return dict(self.n.d.pipeline.db.execute("SELECT key, title FROM tickets WHERE project=?", (p,)).fetchall())

    async def slack_list(self, p):
        """Post the newest delivered digest's Scheduled items to Jay's DM, once. Held while quiet hours last (Jay's
        answer on the plan), never after the window ends or Go Live was sent. Its state is written before the post;
        a definite failure is retried once after RETRY_AFTER, an unknown outcome never (a second list would be a
        second thread to pull from)."""
        from . import notify    # in_quiet lives there; imported late because notify imports this module
        n = self.n
        rows = self.ledger(p)
        row = rows[0] if rows else None
        if not n.settings["slack"] or row is None or row["state"] != "delivered":
            return
        now = n.clock()
        s = row.get("slack") or {}
        if s.get("state") in ("posting", "posted"):
            return
        if s.get("state") == "failed" and (s.get("uncertain") or s["attempts"] >= 2 or now < s["at"] + RETRY_AFTER):
            return
        if self._ended(row, now) or self._went_live(p, row) or notify.in_quiet(n.settings, now):
            return
        keys = (row.get("listed") or {}).get("scheduled") or []
        titles = self._titles(p)
        lines = [f"*{n.name(p)} release {self._local(row['window'])}*: reply in this thread with a ticket ID to pull "
                 "it from this release. A pulled item waits for the next release; its code is on main and still "
                 "ships with Go Live until reverted."]
        lines += [f"• {notify.esc(self._line(p, k, titles.get(k)))}" for k in keys] or ["Nothing is scheduled."]
        s = {"state": "posting", "attempts": s.get("attempts", 0) + 1, "at": now, "channel": None, "ts": None,
             "uncertain": False}
        row["slack"] = s
        self._save(p)
        ts = await n.post("dm", "\n".join(lines), item={"type": "release", "project": p, "window": row["window"]})
        if ts and n._dm:
            s.update(state="posted", channel=n._dm, ts=ts)
        else:
            s.update(state="failed")    # post() has already recorded why
        self._save(p)

    def find_thread(self, cid, ts):
        """The release list whose thread this is, from the ledger: Notifier.threads keeps 1000 posts and a busy week
        can prune a list's root. Channel AND thread must match (tech review A5)."""
        if not (isinstance(cid, str) and isinstance(ts, str) and cid and ts):
            return None
        for p in self._projects():
            for r in self.ledger(p):
                s = r.get("slack") or {}
                if s.get("channel") == cid and s.get("ts") == ts:
                    return {"type": "release", "project": p, "window": r["window"]}
        return None

    async def foreign(self, ev, payload):
        """A message that is not Jay's (from_jay said no). The one exception to dropping it unseen: a plain human
        message in a release list's thread gets Jay one fixed DM, at most once per thread per FOREIGN_GAP. It reads
        and changes nothing else, and records no sender, text or length anywhere (tech review A5)."""
        n = self.n
        if ev.get("type") != "message" or ev.get("subtype") or ev.get("bot_id") \
                or not isinstance(ev.get("user"), str) or not ev.get("user"):
            return
        cid, thread = ev.get("channel"), ev.get("thread_ts")
        if not (isinstance(cid, str) and isinstance(thread, str)):
            return
        item = n.threads.get(f"{cid}:{thread}")
        if not (item and item.get("type") == "release"):
            item = self.find_thread(cid, thread)
        if item is None:
            return
        mark = (payload or {}).get("event_id") or f"{cid}:{ev.get('ts')}"
        if mark in self._foreign_seen:
            return
        self._foreign_seen.append(mark)
        now, where = n.clock(), f"{cid}:{thread}"
        if now < self._foreign_at.get(where, now - FOREIGN_GAP) + FOREIGN_GAP:
            return
        self._foreign_at[where] = now
        name = n.name(item.get("project"))
        n.d._event("notify", "release.foreign_reply", f"A message in the {name} release thread was not Jay's; "
                   "nothing changed", project=item.get("project"), data={"kind": "release.foreign_reply"})
        await n.post("dm", f"A message in the {name} release thread was not from you; nothing changed.")

    def _deploy_started(self, key):
        """Whether the ticket's live deploy is already approved or has a result: pulling it would be too late."""
        row = self.n.d.pipeline.db.execute(
            "SELECT w.deploy FROM tickets t JOIN ticket_work w ON w.ticket_id=t.id WHERE t.key=?", (key,)).fetchone()
        d = json.loads(row[0]) if row and row[0] else {}
        return d.get("env") == "live" and bool(d.get("approvedAt") or d.get("result"))

    async def pull(self, item, text, ev):
        """Jay's reply in a release list's thread. Only withholds: on success the pull is written to the digest's
        ledger row and nothing else (no gate, ticket or deploy changes). Every refusal changes nothing and says why
        in the thread. Returns handle_reply's result."""
        n = self.n
        p = item.get("project")
        rows = self.ledger(p) if p in self._projects() else []
        row = rows[0] if rows and rows[0]["window"] == item.get("window") else None

        def no(why):
            return {"did": "pull_refused", "project": p, "say": "Nothing pulled: " + why}
        if row is None:
            return no("a newer release list replaced this one.")
        if ev.get("attachments") or ev.get("files"):
            # A forward or share arrives as Jay's own message with someone else's words attached: only his own typed
            # text may pull.
            return no("a forwarded or shared message cannot pull. Type the ticket ID in your reply.")
        keys = parse_pull(text) if len(text) <= PULL_TEXT_MAX else None
        if keys is None:
            return no("reply with ticket IDs only, such as the ones listed. This thread only pulls items.")
        if len(keys) > PULL_KEYS_MAX:
            return no(f"at most {PULL_KEYS_MAX} items in one reply.")
        now = n.clock()
        if self._ended(row, now):
            return no("this release window has ended.")
        if self._went_live(p, row):
            return no("Go Live was already sent for this release.")
        listed = set((row.get("listed") or {}).get("scheduled") or [])
        # Keys are stored zero-padded (GYST-012); "GYST-12" as Jay may type it is the same ticket.
        by_num = {_num(k): k for k in listed}
        keys = list(dict.fromkeys(by_num.get(_num(k), k) for k in keys))
        have = row.get("pulls") or {}
        for bad, why in (([k for k in keys if k not in listed], "not in this release's list"),
                         ([k for k in keys if k in have], "already pulled"),
                         ([k for k in keys if self._deploy_started(k)], "already approved to go live")):
            if bad:
                return no(f"{', '.join(bad)} {'is' if len(bad) == 1 else 'are'} {why}.")
        row["pulls"] = dict(have, **{k: {"at": now, "by": "jay:slack"} for k in keys})
        self._save(p)
        for k in keys:
            n.d._event("notify", "release.pulled", f"{k} pulled from the {n.name(p)} release by Jay in Slack",
                       project=p, ref=k, data={"kind": "release.pulled", "window": row["window"]})
        return {"did": "pulled", "project": p,
                "say": f"Pulled {', '.join(keys)}: held for the next release. Its code is on main and still ships "
                       "with Go Live until reverted." + (" A correction email follows." if n.settings["releaseMail"]
                                                         else "")}

    def render_correction(self, p, row, c, items):
        titles = self._titles(p)
        name = self.n.name(p)
        lines = [f"Correction: {name} release {self._local(row['window'])}", ""]
        self._section(lines, "Pulled from this release (now held for the next one)", p,
                      [{"key": k, "title": titles.get(k)} for k in c["keys"]])
        self._section(lines, "Added (urgent, outside the release window)", p,
                      [{"key": k, "title": titles.get(k)} for k in c["urgent"]])
        self._section(lines, "Scheduled this release (corrected)", p, items["scheduled"])
        lines.append("A pulled item's code is on main and still ships with Go Live until it is reverted.")
        link = self.n.link()
        if link:
            lines.append(f"Command Center: {link}")
        return f"Correction: {name} release {self._local(row['window'])}", redact("\n".join(lines) + "\n")[0]

    async def correct(self, p):
        """One correction email for what changed since the digest: new pulls, and urgent live deploys Jay approved
        after it was sent. Only while Release email is on and before the window ends, at most CORRECTIONS_MAX.
        Each entry records the keys it covered, so a pull during a send goes in the next one; the never-twice rules
        are the digest's."""
        n = self.n
        if not n.settings["releaseMail"]:
            return
        rows = self.ledger(p)
        row = rows[0] if rows else None
        now = n.clock()
        if row is None or row["state"] != "delivered" or not row.get("sentAt") or self._ended(row, now):
            return
        cs = row.get("corrections") or []
        last = cs[-1] if cs else None
        retry = bool(last and last["state"] == "failed" and not last["uncertain"] and last["attempts"] < 2)
        if last and (last["state"] == "sending" or (retry and now < last["at"] + RETRY_AFTER)):
            return
        window = n.d.releases.window
        day = datetime.datetime.fromtimestamp(
            row["window"], zoneinfo.ZoneInfo(window.get("tz") or release_mod.DEFAULT_WINDOW["tz"])).date()
        pulls = row.get("pulls") or {}
        items = n.d.pipeline.release_items(p, row["window"], release_mod.cutoff_of(window, day), row["sentAt"], now,
                                           pulled=set(pulls), urgent_after=row["sentAt"])
        if retry:
            c = last
        else:
            new = [k for k in pulls if all(k not in x["keys"] for x in cs)]
            urgent = [r["key"] for r in items["urgent"] if all(r["key"] not in x["urgent"] for x in cs)]
            if not (new or urgent) or len(cs) >= CORRECTIONS_MAX:
                return
            c = {"n": len(cs) + 1, "keys": new, "urgent": urgent, "state": "sending", "uncertain": False,
                 "attempts": 0, "at": now, "sentAt": None, "error": None,
                 "messageId": f"<release-{p}-{int(row['window'])}-c{len(cs) + 1}@commandcenter>"}
        conf, error = self.config()
        if conf is None:
            if (p, row["window"], "correction") not in self._config_failed:
                self._config_failed.add((p, row["window"], "correction"))
                n._fail("release mail", f"{p}: {error}")
            return
        subject, body = self.render_correction(p, row, c, items)
        c.update(state="sending", attempts=c["attempts"] + 1, at=now, error=None)
        if c is not last:
            row["corrections"] = cs + [c]
        self._save(p)           # BEFORE the send, as the digest
        try:
            await n._call(deliver, conf, self.message(conf, subject, body, c["messageId"], now, row["messageId"]))
        except MailError as e:
            c.update(state="failed", uncertain=e.uncertain, error=e.what)
            self._save(p)
            n._fail("release mail", f"{p}: correction: {e.what}")
            return
        c.update(state="delivered", sentAt=n.clock(), error=None)
        self._save(p)

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
