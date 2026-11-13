"""Slack and ntfy: what needs Jay reaches his phone, and his Slack replies reach the project leads.

Off until Jay switches it on (Settings, PUT /api/notify, or `python -m ccd.notify_cli on both`; Jay with Developer Unlock). Both channels start off.

    Slack   one bot in a workspace of Jay's own. Socket Mode: ccd opens an OUTBOUND WebSocket to Slack, so nothing
            listens and the loopback-only rule stands. Tokens live in ~/.config/command-center/slack.env (0600):
            SLACK_BOT_TOKEN (xoxb-) and SLACK_APP_TOKEN (xapp-). They are never logged, served or stored elsewhere.
    ntfy    the topic URL that config.json already holds. Only "something needs you": a title and a link, never
            details, because anyone who knows the topic can read it.

What is sent where:

    DM to Jay        every new Needs You item (gate, questions, merge, task, CI, a blocked agent). A reply in its
                     thread is his answer (below).
    #<project>       that project's alerts (PR opened/closed, checks failing, merges, deploys) and each morning a
                     technical summary: PRs, checks, reviews, deploys.
    #cto             host and ccd alerts, and each morning the owner's summary: per project, what shipped, what
                     waits on Jay, and spend against budget.
    ntfy             the same Needs You items as the DM, as a title and a link.

Client projects (`client_projects`, GauzeMate today) carry only IDs and a risk summary: no titles, no reasons, no
question text, no technical summary. Their replies go to the lead as text and never answer or approve anything.

Quiet hours (22:00 to 07:00 America/Winnipeg by default, changeable in Settings) hold the DM and ntfy; held items
are sent when quiet hours end. Channel posts still go out: Slack's own default only notifies a phone for direct
messages and mentions.

Jay's replies. Only messages from the one Slack member ID in config.json (`notify.slack.jay_member_id`), in his DM
with the bot or a channel the bot is in, are read; everything else is ignored. A reply in the thread of an item:

    questions   it answers them (one question: the whole reply; several: numbered lines "1. …"), exactly as the
                Answer button does, and the answers go to the task's own session (or, with none running, to the
                project's lead). A choice question's options are listed numbered (lettered when there are several
                questions) with the recommended one marked; a reply of just "2" (or "1. b") picks that option.
    gate        "approve" (or yes / ok / go / lgtm) closes the gate ONLY for the Low-risk gates in SLACK_GATES, and
                only while `replyScope` is "answers_low_risk" (default "answers": off until Jay decides). Plans, merges, deploys and anything else open
                CommandCenter from the link: a stolen Slack login cannot merge, deploy or change a plan.
    otherwise   the text goes to the project's lead (Daemon.deliver_to_lead, the in-app chat's store), and the
                lead's reply comes back in the same thread.

A message outside a thread goes to the lead of that channel's project; in #cto or the DM, to the CTO.
"""
import asyncio
import collections
import datetime
import hashlib
import json
import logging
import os
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from . import registry
from .security import redact

log = logging.getLogger("ccd.notify")

SLACK_ENV = Path(os.environ.get("CCD_SLACK_ENV", Path.home() / ".config" / "command-center" / "slack.env"))
SLACK_API = "https://slack.com/api/"

# The gates a Slack reply may close. Fixed in code on purpose: no setting widens it to plans, merges or deploys.
# failure = clear a blocker so the task resumes; ui = accept a UI review. Both are reversible and neither merges,
# deploys, changes a plan, a credential or a permission.
SLACK_GATES = frozenset({"failure", "ui"})
REPLY_SCOPES = ("answers", "answers_low_risk")
APPROVE_RE = re.compile(r"^\s*(approve|approved|yes|y|ok|okay|go|go ahead|lgtm|:\+1:|👍|✅)\s*[.!]*\s*$", re.I)
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

SETTINGS_DEFAULTS = {
    "slack": False,                 # post to Slack and read Jay's replies
    "ntfy": False,                  # push Needs You items to the ntfy topic
    "quietStart": "22:00",
    "quietEnd": "07:00",
    "summaryAt": "07:00",           # owner's and technical summaries, daily
    "timezone": "America/Winnipeg",
    # "answers": every approval opens CommandCenter (D-024 clause 12 as it stands). "answers_low_risk" lets a Slack
    # reply clear a blocker or accept a UI review; it waits on Jay's decision and is never the default.
    "replyScope": "answers",
}
CONFIG_DEFAULTS = {
    "jay_member_id": "",            # Jay's Slack member ID: the only author whose messages are read
    "team_id": "",                  # optional: the workspace; events from any other are ignored
    "cto_channel": "cto",
    "channels": {"commandcenter": "commandcenter", "samvision": "samvision", "gyst": "gyst", "mfe": "mfe"},
    "client_projects": ["gauzemate"],
    "link_base": "http://localhost:7777",   # where CommandCenter opens on Jay's devices (the SSH tunnel today)
}
HELD_MAX = 50
THREADS_MAX = 1000
SEEN_EVENTS_MAX = 500
ALERT_KINDS = ("pr.opened", "pr.closed", "ci.main_changed", "pr.ci_changed", "task.pipeline")
PIPELINE_ALERTS = {"pipeline.merged": "merged", "pipeline.auto_merged": "auto-merged", "pipeline.deployed": "deployed",
                   "pipeline.done": "done", "pipeline.auto_merge_failed": "auto-merge failed"}
NEED_LABEL = {"plan": "Plan needs approval", "merge": "Ready to merge", "ui": "UI review", "deploy": "Deploy approval",
              "failure": "Blocked", "questions": "Questions", "task": "Your task", "ci": "Main checks failing",
              "blocked": "Agent waiting", "flag": "Needs you"}


class SlackError(Exception):
    pass


# ---------- settings ----------

def clean_settings(raw, base=None):
    """Validated settings: base (defaults) overlaid with the known keys of raw. Raises ValueError on a bad value."""
    out = dict(base or SETTINGS_DEFAULTS)
    if not isinstance(raw, dict):
        raise ValueError("settings must be an object")
    for k, v in raw.items():
        if k not in SETTINGS_DEFAULTS:
            raise ValueError(f"unknown setting {k}")
        if k in ("slack", "ntfy"):
            if not isinstance(v, bool):
                raise ValueError(f"{k} must be true or false")
        elif k in ("quietStart", "quietEnd", "summaryAt"):
            if not isinstance(v, str) or not TIME_RE.match(v):
                raise ValueError(f"{k} must be HH:MM (24-hour)")
        elif k == "timezone":
            try:
                ZoneInfo(str(v))
            except Exception:  # noqa: BLE001
                raise ValueError("unknown time zone") from None
        elif k == "replyScope" and v not in REPLY_SCOPES:
            raise ValueError(f"replyScope must be one of {', '.join(REPLY_SCOPES)}")
        out[k] = v
    return out


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet(settings, now=None):
    """True inside quiet hours. A window that crosses midnight (22:00 to 07:00) is handled; equal ends mean none."""
    tz = ZoneInfo(settings["timezone"])
    t = datetime.datetime.fromtimestamp(now if now is not None else time.time(), tz)
    m = t.hour * 60 + t.minute
    a, b = _minutes(settings["quietStart"]), _minutes(settings["quietEnd"])
    if a == b:
        return False
    return a <= m < b if a < b else (m >= a or m < b)


def local_day(settings, now):
    return datetime.datetime.fromtimestamp(now, ZoneInfo(settings["timezone"])).strftime("%Y-%m-%d")


def due(settings, hhmm, last_day, now):
    """Whether a daily job at hhmm (local) is due now and has not run today."""
    t = datetime.datetime.fromtimestamp(now, ZoneInfo(settings["timezone"]))
    return t.hour * 60 + t.minute >= _minutes(hhmm) and last_day != t.strftime("%Y-%m-%d")


def read_env(path):
    """KEY=VALUE lines from slack.env. Refused unless the file is the owner's only (0600 or stricter)."""
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return {}
    if p.is_symlink():
        raise SlackError(f"{p.name} must be a plain file, not a link")
    st = p.stat()
    if st.st_uid != os.getuid():
        raise SlackError(f"{p.name} must belong to the user ccd runs as")
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o077:
        raise SlackError(f"{p.name} must be readable by its owner only (chmod 600)")
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------- clients ----------

class SlackWeb:
    """The few Web API calls ccd makes, over urllib. `call` is synchronous; the notifier runs it in a thread."""

    def __init__(self, bot_token, app_token=None, opener=None):
        self.bot = bot_token
        self.app = app_token
        self.open = opener or urllib.request.urlopen

    def call(self, method, body=None, token=None, retries=2):
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(SLACK_API + method, data=data, method="POST", headers={
            "Authorization": f"Bearer {token or self.bot}", "Content-Type": "application/json; charset=utf-8"})
        for attempt in range(retries + 1):
            try:
                with self.open(req, timeout=15) as r:
                    out = json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < retries:
                    time.sleep(min(30, int(e.headers.get("Retry-After") or 1)))
                    continue
                raise SlackError(f"{method}: HTTP {e.code}") from None
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise SlackError(f"{method}: {type(e).__name__}") from None
            if not out.get("ok"):
                raise SlackError(f"{method}: {out.get('error') or 'failed'}")
            return out
        raise SlackError(f"{method}: rate limited")

    def post(self, channel, text, thread_ts=None):
        body = {"channel": channel, "text": text, "unfurl_links": False, "unfurl_media": False}
        if thread_ts:
            body["thread_ts"] = thread_ts
        return self.call("chat.postMessage", body)

    def channels(self):
        out, cursor = {}, None
        while True:
            body = {"types": "private_channel,public_channel", "exclude_archived": True, "limit": 200}
            if cursor:
                body["cursor"] = cursor
            r = self.call("conversations.list", body)
            for c in r.get("channels") or []:
                out[c["name"]] = c["id"]
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return out

    def dm(self, user):
        return self.call("conversations.open", {"users": user})["channel"]["id"]

    def socket_url(self):
        return self.call("apps.connections.open", token=self.app)["url"]


def ntfy_send(url, title, link=None, priority="default", opener=None):
    """One push. The body is the title again: ntfy shows it, and nothing more is ever sent."""
    headers = {"Title": title[:120].encode("ascii", "replace").decode(), "Priority": priority, "Tags": "bell"}
    if link:
        headers["Click"] = link
    req = urllib.request.Request(url, data=title[:200].encode(), method="POST", headers=headers)
    with (opener or urllib.request.urlopen)(req, timeout=15) as r:
        r.read()


# ---------- formatting ----------

def esc(text):
    """Untrusted text (agent-set reasons, question text, lead replies, PR titles) as plain Slack text: no
    <!channel>, no mentions, no links that look like ccd's own."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _digest(text):
    return hashlib.sha256(str(text or "").encode()).hexdigest()[:16]


def item_key(n):
    """One DM per item. A new batch of questions (other open ids) or a gate with another reason is a new item."""
    extra = ""
    if n.get("kind") == "questions":
        extra = ",".join(str(i) for i in n.get("qids") or [])
    elif n.get("kind") == "gate":
        extra = _digest(n.get("text"))
    return f"{n.get('project')}:{n.get('kind')}:{n.get('ref')}:{n.get('gate') or ''}:{extra}"


LETTERS = "abcdefgh"


def option_lines(q, letters=False):
    """A choice question's options for the DM: numbered (one question) or lettered (several), the recommended one
    marked with why."""
    if q.get("kind") != "choice" or not q.get("options"):
        return []
    out = []
    for j, o in enumerate(q["options"]):
        mark = LETTERS[j] if letters else str(j + 1)
        rec = q.get("recommended") == j
        line = f"      *{mark}*  {esc(str(o)[:200])}"
        if rec:
            line += "  ⭐ _recommended_" + (f": {esc(str(q.get('why') or '')[:300])}" if q.get("why") else "")
        out.append(line)
    return out


def pick_option(q, text):
    """A reply of just an option's number or letter ("2", "b", "2.") answers with that option's text. Anything else
    is Jay's own answer, as written."""
    opts = q.get("options") or []
    m = re.fullmatch(r"\s*([1-8]|[a-hA-H])[.)]?\s*", text or "")
    if q.get("kind") != "choice" or not opts or not m:
        return text
    t = m.group(1).lower()
    j = int(t) - 1 if t.isdigit() else LETTERS.index(t)
    return opts[j] if 0 <= j < len(opts) else text


def need_label(n):
    return NEED_LABEL.get(n.get("gate") or n.get("kind"), "Needs you")


def is_ticket(ref):
    return bool(re.match(r"^[A-Z][A-Z0-9-]{0,20}-\d{1,6}$", str(ref or "")))


class Notifier:
    """Owned by the daemon. `loops()` are added to the daemon's loops; every send is best effort and a failure is
    an event, never an exception that reaches the daemon."""

    TICK = 20

    def __init__(self, daemon, cfg, *, slack=None, ntfy=None, clock=time.time, env_path=None):
        self.d = daemon
        self.store = daemon.store
        ncfg = (cfg.get("notify") or {}) if isinstance(cfg, dict) else {}
        self.conf = dict(CONFIG_DEFAULTS, **{k: v for k, v in (ncfg.get("slack") or {}).items() if k in CONFIG_DEFAULTS})
        self.conf["channels"] = dict(CONFIG_DEFAULTS["channels"], **((ncfg.get("slack") or {}).get("channels") or {}))
        self.ntfy_url = (cfg.get("ntfy_url") or "") if isinstance(cfg, dict) else ""
        self.clock = clock
        self.env_path = env_path or SLACK_ENV
        self._slack = slack            # a SlackWeb, or a fake in tests; built from slack.env when None
        self._ntfy = ntfy or ntfy_send
        self._ids = {}                 # channel name -> id
        self._dm = None
        self.status = {"slack": "off", "socket": "off", "ntfy": "off", "lastError": None, "lastSentAt": None}
        saved, _ = self.store.get("notify:settings", {})
        try:
            self.settings = clean_settings(saved or {})
        except ValueError:
            self.settings = dict(SETTINGS_DEFAULTS)
        seen, _ = self.store.get("notify:seen", None)
        self.seen = set(seen) if seen is not None else None   # None until the first tick sets a baseline
        self.held = list(self.store.get("notify:held", [])[0] or [])
        self.threads = dict(self.store.get("notify:threads", {})[0] or {})
        self.daily = dict(self.store.get("notify:daily", {})[0] or {})
        self._queue = None
        seen_ev, _ = self.store.get("notify:events", [])
        self.seen_events = collections.deque(seen_ev or [], maxlen=SEEN_EVENTS_MAX)
        self.was_quiet = None

    # ----- settings and status -----

    def public(self):
        """GET /api/notify. Never a token, never the ntfy URL; whether each is configured, yes."""
        try:
            env = read_env(self.env_path)
            env_error = None
        except SlackError as e:
            env, env_error = {}, str(e)
        return {"settings": dict(self.settings), "status": dict(self.status),
                "configured": {"slackTokens": bool(env.get("SLACK_BOT_TOKEN") and env.get("SLACK_APP_TOKEN")),
                               "slackTokensError": env_error, "jayMemberId": bool(self.conf["jay_member_id"]),
                               "ntfy": bool(self.ntfy_url)},
                "channels": {"cto": self.conf["cto_channel"], **self.conf["channels"]},
                "clientProjects": list(self.conf["client_projects"]), "slackGates": sorted(SLACK_GATES),
                "quietNow": in_quiet(self.settings, self.clock()), "held": len(self.held)}

    def update_settings(self, body):
        self.settings = clean_settings(body, self.settings)
        self.store.put("notify:settings", self.settings)
        self.d._event("notify", "notify.settings", "notification settings changed",
                      data={"kind": "notify.settings"})
        return self.public()

    # ----- plumbing -----

    def client(self, project):
        return project in self.conf["client_projects"]

    def name(self, project):
        return registry.name_of(project) if registry.project(project) else (project or "CommandCenter")

    def link(self, n=None):
        base = (self.conf["link_base"] or "").rstrip("/")
        if not base:
            return None
        if n and is_ticket(n.get("ref")):
            return f"{base}/#/tasks/{n['ref']}"
        return f"{base}/#/needs"

    def slack(self):
        if self._slack is None:
            env = read_env(self.env_path)
            if not env.get("SLACK_BOT_TOKEN"):
                raise SlackError("no Slack tokens yet (slack.env)")
            self._slack = SlackWeb(env["SLACK_BOT_TOKEN"], env.get("SLACK_APP_TOKEN"))
        return self._slack

    async def _call(self, fn, *a):
        return await asyncio.to_thread(fn, *a)

    async def channel_id(self, name):
        if name not in self._ids:
            self._ids = await self._call(self.slack().channels)
        cid = self._ids.get(name)
        if not cid:
            raise SlackError(f"the bot is not in #{name} (type /invite @CommandCenter there)")
        return cid

    async def dm_id(self):
        if not self.conf["jay_member_id"]:
            raise SlackError("Jay's Slack member ID is not in config.json yet")
        if self._dm is None:
            self._dm = await self._call(self.slack().dm, self.conf["jay_member_id"])
        return self._dm

    def _fail(self, what, e):
        msg = redact(str(e))[0][:200]
        self.status["lastError"] = f"{what}: {msg}"
        log.warning(json.dumps({"msg": "notify failed", "what": what, "error": msg}))
        self.d._event("notify", "notify.failed", f"{what} failed", severity="warn",
                      data={"kind": what, "error": msg})

    async def post(self, where, text, thread_ts=None, item=None):
        """Post to a channel name, or 'dm'. Records the thread so a reply can find its item. Returns ts or None."""
        if not self.settings["slack"]:
            return None
        try:
            cid = await (self.dm_id() if where == "dm" else self.channel_id(where))
            r = await self._call(self.slack().post, cid, redact(text)[0][:3900], thread_ts)
        except SlackError as e:
            self._fail(f"slack {where}", e)
            return None
        self.status.update(slack="ok", lastSentAt=self.clock())
        ts = r.get("ts")
        if item is not None and ts:
            self.threads[f"{cid}:{ts}"] = dict(item, at=self.clock())
            if len(self.threads) > THREADS_MAX:
                for k in sorted(self.threads, key=lambda k: self.threads[k].get("at") or 0)[:len(self.threads) - THREADS_MAX]:
                    del self.threads[k]
            self.store.put("notify:threads", self.threads)
        return ts

    async def push(self, title, link):
        """True when the push was accepted; False when ntfy is off, has no topic, or failed."""
        if not (self.settings["ntfy"] and self.ntfy_url):
            return False
        try:
            await self._call(self._ntfy, self.ntfy_url, title, link)
            self.status["ntfy"] = "ok"
            return True
        except Exception as e:  # noqa: BLE001
            self.status["ntfy"] = "failing"
            self._fail("ntfy", type(e).__name__)
            return False

    async def send_test(self):
        """One test DM and one test push, each reported on its own. lastError is cleared first, so it holds only
        what failed in this test."""
        self.status["lastError"] = None
        ts = await self.post("dm", "CommandCenter test: Slack works. Reply here to check that replies reach ccd.")
        pushed = await self.push("CommandCenter test", self.link())
        return {"ok": True, "slack": bool(ts), "ntfy": pushed, "status": dict(self.status)}

    # ----- Needs You → DM and ntfy -----

    def needs(self):
        st = self.d.state()
        items = [dict(n) for n in st.get("needs") or []]
        for n in items:
            if n.get("kind") == "questions" and is_ticket(n.get("ref")) and not self.client(n.get("project")):
                n["qids"] = [q["id"] for q in self.open_questions(n["ref"])]
        for b in st.get("blocked") or []:
            items.append({"project": b.get("project"), "kind": "blocked", "ref": b.get("pane_id"),
                          "text": f"{b.get('name') or 'an agent'} is waiting for you"})
        return items

    def need_text(self, n):
        """The DM for one item. A client project's carries its ID and a risk line only."""
        proj = n.get("project")
        label = need_label(n)
        link = self.link(n)
        open_ = f"\n<{link}|Open in CommandCenter>" if link else ""
        if self.client(proj):
            return (f"*{self.name(proj)}* · {esc(n.get('ref'))} · {label}\nClient project: details stay in CommandCenter. "
                    f"Risk: waiting on you; nothing moves until you act.{open_}")
        lines = [f"*{self.name(proj)}* · {esc(n.get('ref'))} · {label}", esc(str(n.get("text") or "")[:300])]
        if n.get("kind") == "questions" and is_ticket(n.get("ref")) and not n.get("stale"):
            shown = set(n.get("qids") or [])
            qs = [q for q in self.open_questions(n["ref"]) if q["id"] in shown]
            several = len(qs) > 1
            for i, q in enumerate(qs, 1):
                lines.append(f"{i}. {esc(q['text'][:400])}")
                lines += option_lines(q, letters=several)
            choice = any(q.get("kind") == "choice" and q.get("options") for q in qs)
            if several:
                lines.append("_Reply in this thread with numbered lines (1. …, 2. …): "
                             + ("an option's letter, or your own answer" if choice else "one answer each") + "._")
            else:
                lines.append("_Reply in this thread with " + ("an option's number, or your own answer" if choice
                                                              else "your answer") + "._")
        elif n.get("kind") == "gate" and n.get("gate") in SLACK_GATES and self.settings["replyScope"] == "answers_low_risk":
            lines.append("_Reply *approve* to " + ("clear the blocker" if n["gate"] == "failure" else "accept the UI")
                         + ", or write to the lead._")
        elif n.get("kind") == "gate":
            lines.append("_Approve this in CommandCenter. A reply here goes to the lead._")
        return "\n".join(lines) + open_

    def push_title(self, n):
        proj = n.get("project")
        if self.client(proj):
            return f"{self.name(proj)}: {n.get('ref')} needs you"
        return f"{self.name(proj)}: {need_label(n)} · {n.get('ref')}"

    async def send_need(self, n):
        await self.post("dm", self.need_text(n), item={"type": "need", "project": n.get("project"),
                                                        "kind": n.get("kind"), "gate": n.get("gate"),
                                                        "ref": n.get("ref"), "stale": bool(n.get("stale")),
                                                        "qids": list(n.get("qids") or []),
                                                        "textHash": _digest(n.get("text")), "since": n.get("since")})
        await self.push(self.push_title(n), self.link(n))

    async def check_needs(self):
        items = {item_key(n): n for n in self.needs()}
        if self.seen is None:
            # First run: today's queue is the baseline (it is in the morning summary), not a burst of messages.
            self.seen = set(items)
            self.store.put("notify:seen", sorted(self.seen))
            return
        new = [items[k] for k in items if k not in self.seen]
        self.seen = set(items)
        self.store.put("notify:seen", sorted(self.seen))
        quiet = in_quiet(self.settings, self.clock())
        for n in new:
            if quiet:
                self.held = (self.held + [n])[-HELD_MAX:]
            else:
                await self.send_need(n)
        if quiet:
            self.store.put("notify:held", self.held)
        elif self.held:
            held, self.held = self.held, []
            self.store.put("notify:held", [])
            still = {k for k in items}
            waiting = [n for n in held if item_key(n) in still]
            if waiting:
                await self.post("dm", f"Good morning. {len(waiting)} item{'s' if len(waiting) != 1 else ''} came in "
                                      f"during quiet hours and still need you:")
                for n in waiting:
                    await self.send_need(n)

    # ----- channel alerts -----

    def alert_text(self, ev):
        kind, proj, data = ev.get("kind"), ev.get("project"), ev.get("data") or {}
        if kind == "pr.ci_changed" and data.get("to") != "✗":
            return None
        if kind == "task.pipeline":
            what = PIPELINE_ALERTS.get(data.get("kind"))
            if not what:
                return None
            if self.client(proj):
                return f"{esc(ev.get('ref'))} {what}"
            return esc(ev.get("text"))
        if self.client(proj):
            return f"{esc(ev.get('ref') or '')} {kind}".strip()
        return esc(ev.get("text"))

    async def on_event(self, ev):
        kind = ev.get("kind")
        if kind == "chat.reply":
            await self.relay_reply(ev)
            return
        if kind == "alert.raised" and ev.get("source") == "alerts" and not ev.get("project"):
            await self.post(self.conf["cto_channel"], f":warning: {esc(ev.get('text'))}")
            return
        if kind not in ALERT_KINDS:
            return
        proj = ev.get("project")
        chan = self.conf["channels"].get(proj)
        if not chan or self.client(proj):
            return
        text = self.alert_text(ev)
        if text:
            await self.post(chan, text)

    # ----- summaries -----

    def _day_events(self, since):
        """{project: {kind: [ticket keys]}} for merges, deploys and done in the window, from tasks.db."""
        out = {}
        tasks = getattr(self.d, "tasks", None)
        if tasks is None:
            return out
        for proj, key, kind in tasks.db.execute(
                "SELECT t.project, t.key, e.kind FROM ticket_events e JOIN tickets t ON t.id=e.ticket_id WHERE e.at >= ? "
                "AND e.kind IN ('pipeline.merged','pipeline.auto_merged','pipeline.deployed','pipeline.done') "
                "ORDER BY e.id", (since,)):
            out.setdefault(proj, {}).setdefault(kind, []).append(key)
        return out

    def owner_summary(self, now):
        st = self.d.state()
        needs = {}
        for n in self.needs():
            needs[n.get("project")] = needs.get(n.get("project"), 0) + 1
        day = self._day_events(now - 86400)
        try:
            usage = self.d.usage_state() or {}
        except Exception:  # noqa: BLE001
            usage = {}
        budgets = {b["project"]: b for b in usage.get("budgets") or []}
        spent = {r["key"]: r.get("costUsd") or 0 for r in usage.get("byProject") or []}
        keys = [p["key"] for p in self.d._projects()] if hasattr(self.d, "_projects") else \
            [p.get("key") for p in st.get("projects") or []]
        lines = [f"*Owner's summary* · {local_day(self.settings, now)}"]
        for k in keys:
            shipped = len(set(day.get(k, {}).get("pipeline.done", []) + day.get(k, {}).get("pipeline.merged", [])
                              + day.get(k, {}).get("pipeline.auto_merged", [])))
            deployed = len(set(day.get(k, {}).get("pipeline.deployed", [])))
            b = budgets.get(k)
            money = (f"${b['spentUsd']:.0f} of ${b['monthlyUsd']:.0f} this month" if b and b.get("monthlyUsd")
                     else f"${spent.get(k, 0):.0f} in 14 days, no budget set")
            line = f"• *{self.name(k)}*: {shipped} shipped, {deployed} deployed, {needs.get(k, 0)} waiting on you, {money}"
            if self.client(k):
                line += " · client: details in CommandCenter"
            lines.append(line)
        total = sum(needs.values())
        link = self.link()
        lines.append(f"{total} item{'s wait' if total != 1 else ' waits'} on you in all." + (f" <{link}|Open Needs You>" if link else ""))
        return "\n".join(lines)

    def tech_summary(self, key, now):
        st = self.d.state()
        view = next((v for v in st.get("projects") or [] if v.get("key") == key), None) or {}
        day = self._day_events(now - 86400).get(key, {})
        prs = view.get("prs") or []
        lines = [f"*Technical summary* · {self.name(key)} · {local_day(self.settings, now)}",
                 f"Main checks: {view.get('main_ci') or 'unknown'}",
                 f"Open PRs: {len(prs)}"]
        for pr in prs[:10]:
            review = pr.get("review") or pr.get("reviewDecision") or "no review"
            lines.append(f"  • #{pr.get('number')} {esc(str(pr.get('title') or '')[:80])} · checks {pr.get('ci') or '?'} · {review}")
        merged = sorted(set(day.get("pipeline.merged", []) + day.get("pipeline.auto_merged", [])))
        lines.append(f"Merged in 24 h: {', '.join(merged) if merged else 'none'}")
        deployed = sorted(set(day.get("pipeline.deployed", [])))
        lines.append(f"Deployed in 24 h: {', '.join(deployed) if deployed else 'none'}")
        waiting = [n for n in self.needs() if n.get("project") == key]
        lines.append(f"Waiting on Jay: {len(waiting)}" + (" (" + ", ".join(esc(n.get('ref')) for n in waiting[:8]) + ")"
                                                          if waiting else ""))
        return "\n".join(lines)

    async def summaries(self, force=False):
        now = self.clock()
        if not force and not due(self.settings, self.settings["summaryAt"], self.daily.get("summary"), now):
            return False
        self.daily["summary"] = local_day(self.settings, now)
        self.store.put("notify:daily", self.daily)
        await self.post(self.conf["cto_channel"], self.owner_summary(now))
        for key, chan in self.conf["channels"].items():
            if not self.client(key):
                await self.post(chan, self.tech_summary(key, now))
        return True

    # ----- Jay's replies -----

    def open_questions(self, key):
        try:
            work = self.d.task_work(key)
        except Exception:  # noqa: BLE001
            return []
        return [q for q in work.get("questions") or [] if q.get("answer") is None and q.get("purpose") != "stale"]

    def project_of_channel(self, cid):
        for k, name in self.conf["channels"].items():
            if self._ids.get(name) == cid:
                return k
        return None

    def from_jay(self, ev, team=None):
        jay = self.conf["jay_member_id"]
        if not jay or ev.get("user") != jay:
            return False
        if ev.get("subtype") or ev.get("bot_id"):
            return False
        if self.conf["team_id"] and (team or ev.get("team")) != self.conf["team_id"]:
            return False
        return ev.get("type") == "message" and isinstance(ev.get("text"), str)

    async def on_slack(self, payload):
        """One Events API payload from the socket. Anything not from Jay is dropped without a trace in Slack."""
        ev = (payload or {}).get("event") or {}
        if not self.settings["slack"] or not self.from_jay(ev, payload.get("team_id")):
            return None
        # Slack redelivers an event after a missed ack or a reconnect: act on each message once.
        mark = ev.get("client_msg_id") or payload.get("event_id") or f"{ev.get('channel')}:{ev.get('ts')}"
        if mark in self.seen_events:
            return None
        self.seen_events.append(mark)
        self.store.put("notify:events", list(self.seen_events))
        cid, text = ev.get("channel"), ev["text"].strip()
        thread = ev.get("thread_ts")
        here = thread or ev.get("ts")
        item = self.threads.get(f"{cid}:{thread}") if thread else None
        result = await self.handle_reply(cid, item, text)
        self.d._event("notify", "notify.slack_reply", f"Slack reply: {result['did']}",
                      project=result.get("project"), ref=(item or {}).get("ref"),
                      data={"kind": result["did"], "count": len(text)})
        if result.get("say"):
            await self._reply(cid, here, result["say"])
        if result.get("message_id") is not None:
            self.threads[f"msg:{result['message_id']}"] = {"type": "origin", "channel": cid, "ts": here,
                                                         "conversation": result.get("project"), "at": self.clock()}
            self.store.put("notify:threads", self.threads)
        return result

    async def _reply(self, cid, ts, text):
        if not self.settings["slack"]:
            return
        try:
            await self._call(self.slack().post, cid, redact(text)[0][:3900], ts)
        except SlackError as e:
            self._fail("slack reply", e)

    async def handle_reply(self, cid, item, text):
        if not text:
            return {"did": "empty"}
        if item and item.get("type") == "need":
            proj, ref = item.get("project"), item.get("ref")
            if not self.client(proj):
                if item.get("kind") == "questions" and not item.get("stale"):
                    r = await self.answer(ref, text, item.get("qids") or [])
                    if r:
                        return dict(r, project=proj)
                if (item.get("kind") == "gate" and APPROVE_RE.match(text)):
                    return dict(await self.approve(ref, item.get("gate"), item), project=proj)
            return await self.to_lead(proj, text, ref)
        if cid == self._dm or self._ids.get(self.conf["cto_channel"]) == cid:
            return await self.to_lead("cto", text, None)
        proj = self.project_of_channel(cid)
        if proj:
            return await self.to_lead(proj, text, None)
        return {"did": "ignored"}

    async def answer(self, key, text, qids):
        """Answers exactly the questions that message showed. If any of them was answered since, or there are
        newer ones, nothing is recorded: a late reply never answers a question Jay did not see in Slack."""
        open_ = {q["id"]: q for q in self.open_questions(key)}
        if not qids or any(i not in open_ for i in qids):
            link = self.link({"ref": key})
            return {"did": "answer_stale",
                    "say": "These questions have changed since this message, so nothing was recorded. Answer the newer "
                           "message, or in CommandCenter." + (f" <{link}|Open it>" if link else "")}
        qs = [open_[i] for i in qids]
        if len(qs) == 1:
            parts = [text]
        else:
            found = dict(re.findall(r"(?m)^\s*(\d{1,2})[.):]\s*(.+?)\s*$", text))
            parts = [found.get(str(i)) for i in range(1, len(qs) + 1)]
            if not all(parts):
                return {"did": "answer_incomplete",
                        "say": f"There are {len(qs)} questions. Reply with numbered lines (1. …, 2. …), one per question."}
        parts = [pick_option(q, a) for q, a in zip(qs, parts)]
        for q, a in zip(qs, parts):
            if q.get("kind") == "yesno" and a.strip().lower() not in ("yes", "no") and not a.lower().startswith("other:"):
                return {"did": "answer_invalid", "say": f"“{esc(q['text'][:120])}” is yes or no (or Other: …)."}
        answers = [{"id": q["id"], "answer": a.strip()} for q, a in zip(qs, parts)]
        try:
            # Jay, identified by his Slack member ID: answering is within what a Slack reply may do (C3, D4).
            r = await self.d.task_answers(key, {"answers": answers}, actor="jay", developer=True, via="slack")
        except Exception as e:  # noqa: BLE001
            return {"did": "answer_failed", "say": f"Could not record that: {esc(getattr(e, 'message', None) or e)}"}
        if r.get("complete") is False:
            said = "Answered. Another question on this task is still open in CommandCenter."
        else:
            said = "Answered." + (" Sent to the task's session." if r.get("delivered") else
                                   " The task session gets it when it is running.")
        return {"did": "answered", "say": said}

    async def approve(self, key, gate, item=None):
        link = self.link({"ref": key})
        if gate not in SLACK_GATES or self.settings["replyScope"] != "answers_low_risk":
            return {"did": "approval_refused",
                    "say": "That one is approved in CommandCenter, not from Slack." + (f" <{link}|Open it>" if link else "")}
        # Only the gate that message showed: same ticket, gate, reason and time. Anything else is refused.
        now = [n for n in self.needs() if n.get("kind") == "gate" and n.get("ref") == key and n.get("gate") == gate]
        if not item or not any(_digest(n.get("text")) == item.get("textHash") and n.get("since") == item.get("since")
                               for n in now):
            return {"did": "approval_stale",
                    "say": "This has changed since this message, so nothing was approved." + (f" <{link}|Open it>" if link else "")}
        try:
            r = await self.d.slack_confirm(key, gate)
        except Exception as e:  # noqa: BLE001
            return {"did": "approve_failed", "say": f"Could not approve: {esc(getattr(e, 'message', None) or e)}"}
        return {"did": f"approved_{gate}",
                "say": ("Blocker cleared; the task resumes." if gate == "failure" else "UI accepted.")
                + ("" if (r or {}).get("delivered", True) else " The task session was not running to hear it.")}

    async def to_lead(self, conversation, text, ref):
        deliver = getattr(self.d, "deliver_to_lead", None)
        who = "the CTO" if conversation == "cto" else f"the {self.name(conversation)} lead"
        if deliver is None:
            return {"did": "lead_unavailable", "project": conversation,
                    "say": "Messages to leads arrive with the chat update. Open CommandCenter for now."}
        try:
            r = await deliver(conversation, text, via="slack", ref=ref, author="jay")
        except Exception as e:  # noqa: BLE001
            return {"did": "lead_failed", "project": conversation,
                    "say": f"Could not pass that on: {esc(getattr(e, 'message', None) or e)}"}
        delivery = (r or {}).get("delivery")
        say = {"nudged": f"Sent to {who}.", "queued": f"Sent; {who} sees it when it finishes what it is doing.",
               "lead-offline": f"Saved, but {who} is not running. Open Messages in CommandCenter to start it.",
               "lead-paused": f"Saved. {self.name(conversation)} is paused, so {who} reads it when you resume it."}
        return {"did": f"lead_{delivery or 'sent'}", "project": conversation, "say": say.get(delivery, f"Sent to {who}."),
                "message_id": ((r or {}).get("message") or {}).get("id")}

    async def relay_reply(self, ev):
        """A lead answered a message: post it in the Slack thread it came from, or the project's channel."""
        data = ev.get("data") or {}
        chat = getattr(self.d, "chat", None)
        if chat is None:
            return
        try:
            msg = chat.get(data.get("messageId"))
        except Exception:  # noqa: BLE001
            return
        if not msg:
            return
        conv = msg.get("conversation") or data.get("conversation")
        reply_to = msg.get("replyTo")
        origin = self.threads.get(f"msg:{reply_to}") if reply_to is not None else None
        if origin is None:
            # Leads usually answer without --reply-to: thread it under Jay's latest Slack message to this
            # conversation from the last day, if there is one.
            recent = [v for k, v in self.threads.items() if k.startswith("msg:") and v.get("conversation") == conv
                      and (v.get("at") or 0) > self.clock() - 86400]
            origin = max(recent, key=lambda v: v.get("at") or 0) if recent else None
        who = "CTO" if conv == "cto" else f"{self.name(conv)} lead"
        if self.client(conv):
            body = f"*{who}* replied. Client project: read it in CommandCenter."
        else:
            body = f"*{who}*: {esc(str(msg.get('text') or '')[:3000])}"
        if origin:
            await self._reply(origin["channel"], origin["ts"], body)
        elif conv == "cto":
            await self.post(self.conf["cto_channel"], body)
        elif self.conf["channels"].get(conv) and not self.client(conv):
            await self.post(self.conf["channels"][conv], body)
        else:
            await self.post("dm", body)

    # ----- loops -----

    async def tick(self):
        if not (self.settings["slack"] or self.settings["ntfy"]):
            return
        try:
            await self.check_needs()
            if self.settings["slack"]:
                await self.summaries()
        except Exception as e:  # noqa: BLE001 — notifications never take ccd down
            self._fail("notify tick", repr(e))

    async def tick_loop(self):
        while not self.d._stopping:
            await self.tick()
            await asyncio.sleep(self.TICK)

    async def event_loop(self):
        q = self.d.subscribe()
        try:
            while not self.d._stopping:
                ev = await q.get()
                if self.settings["slack"]:
                    try:
                        await self.on_event(ev)
                    except Exception as e:  # noqa: BLE001
                        self._fail("notify event", repr(e))
        finally:
            self.d.unsubscribe(q)

    async def socket_loop(self, connect=None):
        """Socket Mode: an outbound WebSocket that Slack pushes Jay's messages into. Reconnects with backoff."""
        backoff = 2
        while not self.d._stopping:
            if not self.settings["slack"]:
                self.status["socket"] = "off"
                await asyncio.sleep(10)
                continue
            try:
                await self._socket_once(connect)
                backoff = 2
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.status["socket"] = "reconnecting"
                self._fail("slack socket", repr(e))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    async def _socket_once(self, connect=None):
        if connect is None:
            from websockets.asyncio.client import connect  # pinned in requirements.txt
        url = await self._call(self.slack().socket_url)
        if not self._ids:
            self._ids = await self._call(self.slack().channels)
        if self.conf["jay_member_id"]:
            await self.dm_id()
        async with connect(url, max_size=2 ** 20) as ws:
            self.status["socket"] = "connected"
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("envelope_id"):
                    await ws.send(json.dumps({"envelope_id": msg["envelope_id"]}))
                if msg.get("type") == "disconnect":
                    return
                if msg.get("type") == "events_api":
                    try:
                        await self.on_slack(msg.get("payload") or {})
                    except Exception as e:  # noqa: BLE001
                        self._fail("slack reply", repr(e))
                if not self.settings["slack"]:
                    return

    def loops(self):
        return [self.tick_loop, self.event_loop, self.socket_loop]
