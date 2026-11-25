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

Files a lead sends with a message in Messages (cc-reply --file) go with its words (Jay, 2026-11-17, "Upload, chosen
projects only"): uploaded into the same Slack thread for the projects Jay switches on (`slackFiles`, Settings, off
for all by default), as each file's name and size everywhere else. Never uploaded: SamVision (its licensed WRREB
data never leaves the server), the CTO (it works across projects, SamVision's among them) and client projects
(NO_SLACK_FILES, fixed in code); those get a count of files only, not their names. A text file that redact() would
change stays here too. An upload needs the bot scope files:write; without it the file is listed instead.

Quiet hours (22:00 to 07:00 America/Winnipeg by default, changeable in Settings) hold the DM and ntfy; held items
are sent when quiet hours end. Channel posts still go out: Slack's own default only notifies a phone for direct
messages and mentions.

Jay's replies. Only messages from the one Slack member ID in config.json (`notify.slack.jay_member_id`), in his DM
with the bot or a channel the bot is in, are read; everything else is ignored. A reply in the thread of an item:

    questions   it answers them (one question: the whole reply; several: numbered lines "1. …"), exactly as the
                Answer button does, and the answers go to the task's own session (or, with none running, to the
                project's lead). A choice question's options are listed numbered (lettered when there are several
                questions) with the recommended one marked; a reply of just "2" (or "1. b") picks that option.
    gate        "approve" (or yes / ok / go / lgtm) closes only the gates in SLACK_GATES, each only as its DM showed
                it. A plan (PLAN_GATES): always (its summary, approach, risk and technical review are in the DM). The
                Low-risk gates (LOW_RISK_GATES): with `replyScope` "answers_low_risk" or "all". A merge or a live
                deploy (SHIP_GATES): only with "all", which Jay sets in CommandCenter with Developer Unlock (default
                "answers"). "merge" merges that one PR at the head the DM showed, as the Merge button does. A
                deploy takes two replies: "approve" (or "deploy") asks the agent to PREPARE; its plan comes back as
                a new DM (deploy_go), and only "deploy" there tells it to deploy.
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
from .pipeline import plan_digest, unshown
from .security import redact

log = logging.getLogger("ccd.notify")

SLACK_ENV = Path(os.environ.get("CCD_SLACK_ENV", Path.home() / ".config" / "command-center" / "slack.env"))
SLACK_API = "https://slack.com/api/"

# The gates a Slack reply may close, fixed in code; replyScope (Jay's setting, changed only in CommandCenter with
# Developer Unlock) says which of them a reply closes now.
# failure = clear a blocker so the task resumes; ui = accept a UI review. Both are reversible and neither merges,
# deploys, changes a plan, a credential or a permission. They need replyScope "answers_low_risk" or "all".
LOW_RISK_GATES = frozenset({"failure", "ui"})
# plan = approve a plan Jay must approve (a risky one, after the technical review), whatever replyScope says: Jay's
# decision of 2026-11-16, so a risky ticket does not wait for him to open CommandCenter. Only the plan the DM
# showed. It starts implementation; the PR still needs its review and Jay's merge.
PLAN_GATES = frozenset({"plan"})
# merge = merge one reviewed, green PR at the head the DM showed (Daemon.slack_merge, the Merge button's path);
# deploy = approve a live deploy, which only asks for a plan, then confirm that plan with a second reply. Jay's
# decision of 2026-11-16 ("Slack should be able to do everything … only deploy if asked to"). Only with replyScope
# "all": a stolen Slack login alone cannot turn it on.
SHIP_GATES = frozenset({"merge", "deploy"})
SLACK_GATES = LOW_RISK_GATES | PLAN_GATES | SHIP_GATES
REPLY_SCOPES = ("answers", "answers_low_risk", "all")
APPROVE_RE = re.compile(r"^\s*(approve|approved|yes|y|ok|okay|go|go ahead|lgtm|:\+1:|👍|✅)\s*[.!]*\s*$", re.I)
# Only these words merge or deploy: an "ok" or 👍 on a merge DM or a deploy plan does neither (handle_reply).
MERGE_RE = re.compile(r"^\s*(merge|merge it|merge now)\s*[.!]*\s*$", re.I)
DEPLOY_RE = re.compile(r"^\s*(deploy|deploy it|deploy now|go live|ship it)\s*[.!]*\s*$", re.I)
POST_LIMIT = 3900   # characters of one Slack post ccd sends; longer text is cut
# Projects whose Messages files are never uploaded to Slack, whatever slackFiles says (client projects too).
NO_SLACK_FILES = frozenset({"samvision", "cto"})
FILES_SCOPE = "files:write"     # the scope Slack needs before the bot may upload a file
SECRET_FILE = "this file looks like it holds a password, token or key"
UPLOAD_MAX = 50 * 1024 * 1024   # bytes of one uploaded file; Messages takes 20 MB by default (chat_file_max_mb)
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

SETTINGS_DEFAULTS = {
    "slack": False,                 # post to Slack and read Jay's replies
    "ntfy": False,                  # push Needs You items to the ntfy topic
    "quietStart": "22:00",
    "quietEnd": "07:00",
    "summaryAt": "07:00",           # owner's and technical summaries, daily
    "timezone": "America/Winnipeg",
    # "answers": answers and plans (PLAN_GATES, Jay's 2026-11-16 decision); other approvals open CommandCenter.
    # "answers_low_risk" also clears a blocker or accepts a UI review. "all" also merges and deploys (SHIP_GATES).
    # Changed only in CommandCenter with Developer Unlock; never the default beyond "answers".
    "replyScope": "answers",
    # Projects whose leads' Messages files are uploaded to Slack (Jay, 2026-11-17). Never NO_SLACK_FILES or a client.
    "slackFiles": [],
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
IDS_REFRESH_S = 60              # at most one re-read of the channel list a minute per unknown channel
ALERT_KINDS = ("pr.opened", "pr.closed", "ci.main_changed", "pr.ci_changed", "task.pipeline")
PIPELINE_ALERTS = {"pipeline.merged": "merged", "pipeline.auto_merged": "auto-merged", "pipeline.deployed": "deployed",
                   "pipeline.done": "done", "pipeline.auto_merge_failed": "auto-merge failed",
                   # CC-076: Jay is told about every urgent exception in the channel, with its kind and reason.
                   "pipeline.urgent": "urgent exception"}
# Who posts a ticket's steps in its Slack thread: the seat of the actor that recorded the step (pipeline_cli
# --role), with its icon. Anything else (Jay, ccd's own GitHub poll) posts as the app itself.
SEATS = {"agent:coordinator": ("Lead", ":compass:"), "agent:planner": ("Investigator", ":mag:"),
         "agent:tech-reviewer": ("Technical reviewer", ":triangular_ruler:"),
         "agent:implementer": ("Developer", ":hammer_and_wrench:"), "agent:user-reviewer": ("User reviewer", ":test_tube:"),
         "agent:design-reviewer": ("Design reviewer", ":art:"), "agent:reviewer": ("Code reviewer", ":eyes:"),
         "agent:verifier": ("Verifier", ":white_check_mark:")}
LEAD_ICON, CTO_ICON = ":compass:", ":office:"
# The steps a ticket's thread shows: each seat's result, the gates, and what happened to it. Not the many small
# records (criteria edits, evidence, findings one by one, writer checkpoints, stale marks).
TEAM_KINDS = frozenset({
    "pipeline.intake", "pipeline.role", "pipeline.plan", "pipeline.plan_reviewed", "pipeline.plan_accepted",
    "pipeline.review_ready",
    "pipeline.replan", "pipeline.started", "pipeline.handoff", "pipeline.user_checked", "pipeline.review",
    "pipeline.rework", "pipeline.blocked", "pipeline.questions", "pipeline.answered", "pipeline.gate_opened",
    "pipeline.gate_confirmed", "pipeline.ready_to_merge", "pipeline.unreviewed_merge", "pipeline.verified",
    "pipeline.released", "pipeline.deploy_requested", "pipeline.deploy_approved", "pipeline.closed_note",
    "pipeline.deploy_prepared", "pipeline.deploy_confirmed",
    *PIPELINE_ALERTS})
CUSTOMIZE = "chat:write.customize"     # the scope Slack needs before a bot may post under another name and icon
TICKETS_MAX = 500
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
        elif k == "slackFiles":
            if not isinstance(v, list) or len(v) > 20 or not all(isinstance(x, str) and x for x in v):
                raise ValueError("slackFiles must be a list of project keys")
            never = sorted(set(v) & NO_SLACK_FILES)
            if never:
                raise ValueError(f"files from {', '.join(registry.name_of(x) if x != 'cto' else 'the CTO' for x in never)}"
                                 " are never uploaded to Slack")
            v = sorted(set(v))
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


def local_time(settings, ts):
    """A unix time as Jay reads it: his timezone, to the minute."""
    return datetime.datetime.fromtimestamp(ts, ZoneInfo(settings["timezone"])).strftime("%a %Y-%m-%d %H:%M %Z")


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
    """The few Web API calls ccd makes, over urllib. `call` is synchronous; the notifier runs it in a thread.

    Slack reads a JSON body only on its write methods. A read method such as conversations.list ignores it and runs
    with its defaults (public channels only), so reads send their arguments as a form (`form=True`)."""

    def __init__(self, bot_token, app_token=None, opener=None):
        self.bot = bot_token
        self.app = app_token
        self.open = opener or urllib.request.urlopen
        self.scopes = None      # the bot token's scopes, from the last response's x-oauth-scopes header

    def call(self, method, body=None, token=None, retries=2, form=False):
        if form:
            data = urllib.parse.urlencode({k: str(v).lower() if isinstance(v, bool) else v
                                           for k, v in (body or {}).items()}).encode()
            kind = "application/x-www-form-urlencoded"
        else:
            data, kind = json.dumps(body or {}).encode(), "application/json; charset=utf-8"
        req = urllib.request.Request(SLACK_API + method, data=data, method="POST", headers={
            "Authorization": f"Bearer {token or self.bot}", "Content-Type": kind})
        for attempt in range(retries + 1):
            try:
                with self.open(req, timeout=15) as r:
                    out = json.loads(r.read() or b"{}")
                    granted = (getattr(r, "headers", None) or {}).get("x-oauth-scopes")
                    if granted is not None and (token or self.bot) == self.bot:
                        self.scopes = {x.strip() for x in granted.split(",") if x.strip()}
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

    def post(self, channel, text, thread_ts=None, as_=None, broadcast=False):
        """as_: (name, icon emoji) to post under, which needs CUSTOMIZE. broadcast: a thread reply also shown in
        the channel."""
        body = {"channel": channel, "text": text, "unfurl_links": False, "unfurl_media": False}
        if thread_ts:
            body["thread_ts"] = thread_ts
            if broadcast:
                body["reply_broadcast"] = True
        if as_:
            body["username"], body["icon_emoji"] = as_
        return self.call("chat.postMessage", body)

    def upload(self, channel, thread_ts, name, data):
        """Upload one file into a thread (needs files:write): Slack's external upload, the only one it still
        offers. Ask for an upload URL, send the bytes there (no token: the URL is signed), then share the file."""
        r = self.call("files.getUploadURLExternal", {"filename": name, "length": len(data)}, form=True)
        url, fid = r.get("upload_url") or "", r.get("file_id")
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not (parts.hostname or "").endswith(".slack.com") or not fid:
            raise SlackError("files.getUploadURLExternal: no Slack upload URL")
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/octet-stream"})
        try:
            with self.open(req, timeout=120) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            raise SlackError(f"file upload: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise SlackError(f"file upload: {type(e).__name__}") from None
        body = {"files": json.dumps([{"id": fid, "title": name}]), "channel_id": channel}
        if thread_ts:
            body["thread_ts"] = thread_ts
        return self.call("files.completeUploadExternal", body, form=True)

    def channels(self):
        out, cursor = {}, None
        while True:
            body = {"types": "private_channel,public_channel", "exclude_archived": True, "limit": 200}
            if cursor:
                body["cursor"] = cursor
            r = self.call("conversations.list", body, form=True)     # as JSON, Slack lists public channels only
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

def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def cut(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


def size_text(n):
    """A file size as people read it: 820 bytes, 14 KB, 3.2 MB."""
    n = n if isinstance(n, int) and n >= 0 else 0
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


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
    """A reply of just an option's number or letter ("2", "b", "2.") answers with that option's text, and several
    ("1, 3", "a and c") with those options' texts. Anything else is Jay's own answer, as written."""
    opts = q.get("options") or []
    if any(str(o).strip().lower() == (text or "").strip().lower() for o in opts):
        return text            # the option's own text ("2" when the options are 2 / 4 / 8)
    if q.get("kind") != "choice" or not opts:
        return text
    marks = _marks(text)
    if not marks or any(not 0 <= j < len(opts) for j in marks):
        return text
    picked = []
    for j in marks:
        if opts[j] not in picked:
            picked.append(opts[j])
    return "; ".join(picked)


def _marks(text):
    """The option indexes a reply made only of option numbers or letters names ("2", "b.", "1, 3", "a and c"), or
    None for anything else. A number past 8 or a letter past h still counts, so a wrong pick can be refused."""
    if not re.fullmatch(r"\s*(\d{1,2}|[a-zA-Z])[.)]?(?:\s*(?:,|&|\band\b|\s)\s*(\d{1,2}|[a-zA-Z])[.)]?)*\s*",
                        text or ""):
        return None
    out = []
    for t in re.findall(r"(?<![A-Za-z0-9])(\d{1,2}|[a-zA-Z])(?![A-Za-z0-9])", re.sub(r"\band\b", " ", text)):
        t = t.lower()
        out.append(int(t) - 1 if t.isdigit() else ord(t) - ord("a"))
    return out


def bad_pick(q, text):
    """A reply that only picks options of a choice question and names one it does not have ("4" of three, "1, 9").
    Not when an option's own text is a number: then "5" may be Jay's own value ("2 / 4 / 8 replicas")."""
    opts = q.get("options") or []
    if q.get("kind") != "choice" or not opts or any(re.fullmatch(r"\s*\d+\s*", str(o)) for o in opts):
        return False
    if any(str(o).strip().lower() == (text or "").strip().lower() for o in opts):
        return False
    marks = _marks(text)
    return bool(marks) and any(not 0 <= j < len(opts) for j in marks)


def _cut(text, n):
    """Agent text on ONE line of the DM: line breaks collapsed, so it cannot pass a line of its own off as ccd's
    (a "Technical review" or "Reply approve" line); cut at n characters, marked with "…"."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _items(values, n):
    return _cut("; ".join(str(v) for v in values or []), n)


def plan_lines(plan, review):
    """A plan waiting for Jay, short enough for one DM: what it does, how, what it touches, its risk, and what the
    technical reviewer said."""
    out = [f"*Plan:* {esc(_cut(plan.get('summary'), 500))}"]
    if plan.get("approach"):
        out.append(f"*Approach:* {esc(_cut(plan['approach'], 700))}")
    if plan.get("requirements"):
        out.append(f"*Requirements ({len(plan['requirements'])}):* " + esc(_items(plan["requirements"], 400)))
    if plan.get("affected"):
        out.append("*Touches:* " + esc(_cut(", ".join(str(a) for a in plan["affected"]), 300)))
    if plan.get("risk"):
        out.append(f"*Risk:* {esc(_cut(plan['risk'], 300))}")
    if plan.get("tests"):
        out.append(f"*Tests ({len(plan['tests'])}):* " + esc(_items(plan["tests"], 400)))
    if review:
        out.append(f"*Technical review:* {esc(_cut(review.get('verdict'), 20))}: {esc(_cut(review.get('note'), 300))}")
        if review.get("blast"):
            out.append(f"*Blast radius:* {esc(_cut(review['blast'], 300))}")
    else:
        out.append("*Technical review:* none on this route")
    more = [f"{len(plan[k])} {k if len(plan[k]) != 1 else k[:-1]}" for k in ("questions", "findings") if plan.get(k)]
    if more:
        out.append(f"*Also in the plan:* {' and '.join(more)}, in CommandCenter")
    if any(line.endswith("…") for line in out):
        out.append("_Some of it is cut short here; the full plan is in CommandCenter._")
    return out


def plan_unshown(value):
    """Whether any text anywhere in a plan (every field, shown in the DM or not) has a character Slack would not
    show (pipeline.unshown). An approval covers the whole plan, so such a plan is approved in CommandCenter only."""
    if isinstance(value, str):
        return unshown(value) is not None
    if isinstance(value, dict):
        return any(plan_unshown(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(plan_unshown(v) for v in value)
    return False


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
        self._ids_at = {}              # unknown channel id -> when a message from it last re-read the list
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
        self.tickets = dict(self.store.get("notify:tickets", {})[0] or {})    # ticket key -> its thread in Slack
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
                "clientProjects": list(self.conf["client_projects"]), "slackGates": sorted(LOW_RISK_GATES),
                "slackFiles": {"choices": self.file_choices(), "never": sorted(NO_SLACK_FILES),
                               "scope": self.files_scope()},
                "slackPlans": bool(PLAN_GATES),
                "quietNow": in_quiet(self.settings, self.clock()), "held": len(self.held)}

    def update_settings(self, body):
        settings = clean_settings(body, self.settings)
        if isinstance(body, dict) and "slackFiles" in body:
            other = [k for k in settings["slackFiles"] if k not in self.file_choices()]
            if other:
                raise ValueError(f"files from {', '.join(other)} cannot be uploaded to Slack: only "
                                 f"{', '.join(self.file_choices()) or 'no project'}")
        self.settings = settings
        self.store.put("notify:settings", self.settings)
        self.d._event("notify", "notify.settings", "notification settings changed",
                      data={"kind": "notify.settings"})
        return self.public()

    # ----- plumbing -----

    def client(self, project):
        return project in self.conf["client_projects"]

    def file_choices(self):
        """The projects whose Messages files Jay may have uploaded to Slack: those with a channel, never
        NO_SLACK_FILES or a client project."""
        return [k for k in self.conf["channels"] if k not in NO_SLACK_FILES and not self.client(k)]

    def files_upload(self, conv):
        """Whether a lead's files in this conversation are uploaded to Slack now. Checked again on every send."""
        return conv in self.settings["slackFiles"] and conv in self.file_choices()

    def files_scope(self):
        """Whether the bot token has files:write: True or False from Slack's last answer, None before one."""
        scopes = getattr(self._slack, "scopes", None)
        return None if scopes is None else FILES_SCOPE in scopes

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

    def _as(self, who):
        """How a post shows who wrote it, `who` being (name, icon emoji): under that name and icon once Slack has
        granted CUSTOMIZE, else as the app with the name in bold at the start. Returns (SlackWeb.post's as_, prefix)."""
        if not who:
            return None, ""
        if CUSTOMIZE in (getattr(self.slack(), "scopes", None) or ()):
            return who, ""
        return None, f"{who[1]} *{esc(who[0])}*: "

    async def post(self, where, text, thread_ts=None, item=None, who=None, broadcast=False):
        """Post to a channel name, or 'dm'. Records the thread so a reply can find its item. Returns ts or None."""
        if not self.settings["slack"]:
            return None
        try:
            cid = await (self.dm_id() if where == "dm" else self.channel_id(where))
            as_, prefix = self._as(who)
            r = await self._call(self.slack().post, cid, redact(prefix + text)[0][:POST_LIMIT], thread_ts, as_, broadcast)
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

    def need_text(self, n, plan=None, review=None):
        """The DM for one item. A client project's carries its ID and a risk line only. `plan` is a plan gate's
        plan as send_need read it (so the DM shows exactly what its planHash covers); `review` likewise is a merge
        gate's review, whose head the item records."""
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
            lines.append("_A reply that ends with ? goes to the agent as your question; its answer comes back here._")
        elif n.get("kind") == "gate" and n.get("gate") in PLAN_GATES:
            p = plan
            if p is None:
                lines.append("_The plan could not be read here: approve it in CommandCenter. A reply here goes to the lead._")
            else:
                lines += plan_lines(p["plan"], p["review"])
                if redact("\n".join(lines))[1] or unshown("\n".join(lines)) or plan_unshown(p["plan"]):
                    # Part of it would not show (post() redacts; Slack draws no invisible character): no planHash.
                    lines.append("_Part of this plan cannot be shown here, so it is approved in CommandCenter only. A "
                                 "reply here goes to the lead._")
                else:
                    lines.append("_Reply *approve* to approve this plan and start implementation, or write to the "
                                 "lead._")
        elif n.get("kind") == "gate" and n.get("gate") == "merge" and self.allows("merge"):
            rv = review if review is not None else self._review(n.get("ref"))
            if rv.get("head"):
                lines.append(f"*PR:* {esc(rv.get('pr') or 'linked PR')} · head `{esc(str(rv['head'])[:12])}` · review "
                             f"{esc(rv.get('verdict'))}")
                lines.append("_Reply *merge* to merge this PR at this head, as the Merge button does, or write to the "
                             "lead._")
            else:
                lines.append("_Merge this in CommandCenter. A reply here goes to the lead._")
        elif n.get("kind") == "gate" and n.get("gate") == "deploy" and self.allows("deploy"):
            lines.append("_Reply *approve* and the agent prepares it: its deploy plan comes to you as a new message, "
                         "and nothing deploys until you reply *deploy* to that one._")
        elif n.get("kind") == "gate" and n.get("gate") in LOW_RISK_GATES and self.allows(n.get("gate")):
            lines.append("_Reply *approve* to " + ("clear the blocker" if n["gate"] == "failure" else "accept the UI")
                         + ", or write to the lead._")
        elif n.get("kind") == "gate":
            lines.append("_Approve this in CommandCenter. A reply here goes to the lead._")
        return "\n".join(lines) + open_

    def _work(self, key):
        try:
            return self.d.task_work(key) or {}
        except Exception:  # noqa: BLE001
            return {}

    def _review(self, key):
        return self._work(key).get("review") or {}

    def _deploy(self, key):
        return self._work(key).get("deploy") or {}

    async def send_deploy_plan(self, key, project):
        """The plan an agent recorded for a deploy Jay approved (pipeline.deploy_plan): a new DM, its own item, whose
        "deploy" reply is the go (deploy_go). The agent's lines are in a code block, so they read as its text, not ccd's.
        Every line is shown whole, since the go approves the whole plan; one that will not fit in a post gets no go
        from Slack. Sent at any hour, like a Slack approval's own reply: Jay asked for this plan, so quiet hours do
        not hold it."""
        d = self._deploy(key)
        if self.client(project) or not d.get("plan") or d.get("goAt") or d.get("result"):
            return
        text = str(d["plan"].get("summary") or "")
        shown_lines = [esc(line) for line in text.splitlines() if line.strip()]
        # A code block: no Slack formatting applies inside it (a struck-through or bold step reads as written), and
        # pipeline.deploy_plan refuses the ``` that would end it early.
        quoted = ["```", *shown_lines, "```"]
        head = f"*{self.name(project)}* · {esc(key)} · Deploy plan ready · {len(shown_lines)} lines"
        link = self.link({"ref": key})
        open_ = f"\n<{link}|Open in CommandCenter>" if link else ""
        plan_hash = plan_digest(d["plan"])
        if not self.allows("deploy"):
            # A Slack approval is confirmed only from Slack (pipeline.deployed): say how to turn it back on.
            hint = ("_Deploys from Slack are off now: set Your Slack replies to Everything in CommandCenter, then "
                    "reply *deploy* here._")
        else:
            hint = "_Reply *deploy* to deploy it by this plan. Nothing deploys until you do._"
            if d.get("heldUntil"):
                hint += (f"\n_Held for the release window until {local_time(self.settings, d['heldUntil'])}: "
                         "a *deploy* reply before then is refused._")
        body = "\n".join([head, *quoted, hint]) + open_
        shown, hidden = redact(body)
        if hidden or unshown(body) or len(shown) > POST_LIMIT:
            # post() would hide part of it or cut it, so Jay would not see all of what "deploy" approves.
            # (pipeline.deploy_plan refuses such a plan; this holds for one recorded before that check.)
            plan_hash = None
            body = "\n".join([head, "_This plan cannot be shown here in full, so it cannot be confirmed from Slack. "
                                     "Reply here to ask the agent for a shorter one with no secrets in it._"]) + open_
        await self.post("dm", body, item={"type": "deploy_go", "project": project, "ref": key, "planHash": plan_hash})
        await self.push(f"{self.name(project)}: deploy plan ready · {key}", link)

    def _plan(self, key):
        """The ticket's plan and its technical review as ccd has them now; None when there is no plan to show."""
        try:
            w = self.d.task_work(key) or {}
        except Exception:  # noqa: BLE001
            return None
        plan = w.get("plan") or {}
        return {"plan": plan, "review": w.get("planReview")} if plan.get("summary") else None

    def push_title(self, n):
        proj = n.get("project")
        if self.client(proj):
            return f"{self.name(proj)}: {n.get('ref')} needs you"
        return f"{self.name(proj)}: {need_label(n)} · {n.get('ref')}"

    async def send_need(self, n):
        item = {"type": "need", "project": n.get("project"), "kind": n.get("kind"), "gate": n.get("gate"),
                "ref": n.get("ref"), "stale": bool(n.get("stale")), "qids": list(n.get("qids") or []),
                "textHash": _digest(n.get("text")), "since": n.get("since")}
        p = rv = None
        if n.get("kind") == "gate" and n.get("gate") == "merge" and not self.client(n.get("project")):
            # The head this DM shows, read once: a merge reply merges exactly it (approve()).
            rv = self._review(n.get("ref"))
            item["head"] = rv.get("head")
        if n.get("kind") == "gate" and n.get("gate") in PLAN_GATES and not self.client(n.get("project")):
            # The plan this DM shows, read once. An approve applies to this plan only (approve()).
            p = self._plan(n.get("ref"))
            item["planHash"] = plan_digest(p["plan"]) if p else None
        text = self.need_text(n, plan=p, review=rv)
        if p is not None and (redact(text)[1] or unshown(text) or plan_unshown(p["plan"])):
            # Part of what an approve approves would not show: CommandCenter only.
            item["planHash"] = None
        await self.post("dm", text, item=item)
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
        if kind == "task.pipeline" and (ev.get("data") or {}).get("kind") == "pipeline.deploy_prepared" \
                and is_ticket(ev.get("ref")):
            await self.send_deploy_plan(ev["ref"], proj)
        chan = self.conf["channels"].get(proj)
        if not chan or self.client(proj):
            return
        if kind == "task.pipeline" and is_ticket(ev.get("ref")):
            if (ev.get("data") or {}).get("kind") in TEAM_KINDS:
                await self.team_step(ev, chan)
            return
        text = self.alert_text(ev)
        if text:
            await self.post(chan, text)

    async def team_step(self, ev, chan):
        """One step of a ticket, in the ticket's own thread in its project's channel, under the seat that recorded
        it (SEATS). The first step starts the thread. Jay's replies there go to the lead with the ticket's key.
        Merged, deployed and done also show in the channel itself."""
        key, data = ev["ref"], ev.get("data") or {}
        text = str(ev.get("text") or "")
        if text.startswith(key + " "):
            text = text[len(key) + 1:]
        if data.get("kind") in ("pipeline.handoff", "pipeline.blocked", "pipeline.user_checked"):
            work = self._work(key)
            when = ev.get("at") or self.clock()
            if data.get("kind") == "pipeline.handoff":
                handoff = work.get("handoff") or {}
                if (handoff.get("at") or 0) > when:
                    handoff = {}  # A newer handoff is a different Slack update.
                parts = [f"{label}: {str(handoff[field])[:220]}"
                         + (f" (owner: {handoff['owner']})" if field == "next" and handoff.get("owner") else "")
                         for field, label in
                         (("done", "Completed"), ("next", "Next"), ("blockers", "Blocked by")) if handoff.get(field)]
                text = "\n".join(parts) or text
            elif data.get("kind") == "pipeline.blocked":
                blocked = work.get("blocked") or {}
                if (blocked.get("at") or 0) > when:
                    blocked = {}  # A newer block is a different Slack update.
                # The same test as the work-mode line and `pipeline_cli tasks` (Pipeline.triage_needed), so the post
                # never says a next step exists when the lead has been told to triage it.
                if blocked.get("action") and blocked.get("owner"):
                    text = f"{text}\nNext: {str(blocked['action'])[:220]} (owner: {blocked['owner']})"
                else:
                    text = f"{text}\nNo next step or owner: the lead triages it today"
            else:
                check = work.get("userCheck") or {}
                if check.get("note") and (check.get("at") or 0) <= when:
                    text += f"\nChecked: {str(check['note'])[:220]}"
        root = await self._ticket_thread(key, ev.get("project"), chan)
        if root is not None:
            await self.post(chan, esc(text), thread_ts=root, who=SEATS.get(data.get("actor")),
                            broadcast=data.get("kind") in PIPELINE_ALERTS)

    def _ticket_item(self, cid, ts):
        """A ticket's thread found from notify:tickets, for a root that `threads` has already pruned (it keeps
        1000 posts; a busy week can push a quiet ticket's root out while the ticket is still open)."""
        for key, t in self.tickets.items():
            if t.get("ts") == ts and self._ids.get(t.get("channel")) == cid:
                return {"type": "ticket", "project": t.get("project") or self.project_of_channel(cid), "ref": key}
        return None

    async def _ticket_thread(self, key, project, chan):
        """The ts of the ticket's thread in `chan`, starting it (key, title, a link) the first time."""
        t = self.tickets.get(key)
        if t and t.get("channel") == chan:
            return t["ts"]
        try:
            title = str((self.d.tasks.get(key) or {}).get("title") or "") if getattr(self.d, "tasks", None) else ""
        except Exception:  # noqa: BLE001 — a ticket ccd cannot read still gets its thread
            title = ""
        link = self.link({"ref": key})
        head = f"*{esc(key)}*" + (f" · {esc(title[:150])}" if title else "") + (f"  <{link}|Open>" if link else "")
        ts = await self.post(chan, head, item={"type": "ticket", "project": project, "ref": key})
        if ts is None:
            return None
        self.tickets[key] = {"channel": chan, "ts": ts, "at": self.clock(), "project": project}
        if len(self.tickets) > TICKETS_MAX:
            for k in sorted(self.tickets, key=lambda k: self.tickets[k].get("at") or 0)[:len(self.tickets) - TICKETS_MAX]:
                del self.tickets[k]
        self.store.put("notify:tickets", self.tickets)
        return ts

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
        if item is None and thread:
            item = self._ticket_item(cid, thread)
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

    async def _reply(self, cid, ts, text, who=None):
        """Post in a thread. True when Slack took it."""
        if not self.settings["slack"]:
            return False
        try:
            as_, prefix = self._as(who)
            await self._call(self.slack().post, cid, redact(prefix + text)[0][:POST_LIMIT], ts, as_)
        except SlackError as e:
            self._fail("slack reply", e)
            return False
        return True

    async def handle_reply(self, cid, item, text):
        if not text:
            return {"did": "empty"}
        if item and item.get("type") == "ticket":
            return await self.to_lead(item.get("project"), text, item.get("ref"))
        if item and item.get("type") == "need":
            proj, ref = item.get("project"), item.get("ref")
            if not self.client(proj):
                if item.get("kind") == "questions" and not item.get("stale") and text.rstrip().endswith("?"):
                    # Jay asks the agent back instead of answering (Jay, 2026-11-16): nothing is recorded as an answer.
                    return dict(await self.ask_back(ref, text, proj), project=proj)
                if item.get("kind") == "questions" and not item.get("stale"):
                    r = await self.answer(ref, text, item.get("qids") or [])
                    if r:
                        return dict(r, project=proj)
                gate = item.get("gate")
                if item.get("kind") == "gate" and gate == "merge" and self.allows("merge") \
                        and APPROVE_RE.match(text) and not MERGE_RE.match(text):
                    # A merge ships: an "ok" or 👍 is not one. (A deploy approval only asks for a plan, so it may.)
                    return {"did": "merge_word_needed", "project": proj,
                            "say": "Nothing was merged: reply *merge* to merge this PR."}
                word = {"merge": MERGE_RE, "deploy": DEPLOY_RE}.get(gate)
                if item.get("kind") == "gate" and (APPROVE_RE.match(text) or (word and word.match(text))):
                    return dict(await self.approve(ref, gate, item), project=proj)
            return await self.to_lead(proj, text, ref)
        if item and item.get("type") == "deploy_go":
            proj, ref = item.get("project"), item.get("ref")
            if not self.client(proj) and DEPLOY_RE.match(text):
                return dict(await self.deploy_go(ref, item), project=proj)
            if not self.client(proj) and APPROVE_RE.match(text):
                return {"did": "deploy_word_needed", "project": proj,
                        "say": "Nothing was deployed: reply *deploy* to deploy by this plan."}
            return await self.to_lead(proj, text, ref)
        to = self._route(cid)
        if to is None and cid not in self._ids.values() and await self._reread_channels(cid):
            to = self._route(cid)
        if to:
            return await self.to_lead(to, text, None)
        return {"did": "ignored"}

    def _route(self, cid):
        """Whose a message outside an item's thread is: "cto" (the DM or #cto), a project key, or None."""
        if cid == self._dm or self._ids.get(self.conf["cto_channel"]) == cid:
            return "cto"
        return self.project_of_channel(cid)

    async def _reread_channels(self, cid):
        """The channel list is read when the socket connects, and Slack lists a private channel only once the bot is
        in it. A message from a channel the list lacks means the bot was invited since: read it again, at most once a
        minute for that channel (Slack sends events only from channels the bot is in, so there are few). Returns
        whether it was read."""
        now = self.clock()
        if now - self._ids_at.get(cid, float("-inf")) < IDS_REFRESH_S:
            return False
        self._ids_at = {k: v for k, v in self._ids_at.items() if now - v < IDS_REFRESH_S}
        self._ids_at[cid] = now
        try:
            self._ids = await self._call(self.slack().channels)
        except SlackError as e:
            self._fail("slack channels", e)
            return False
        return True

    async def ask_back(self, key, text, project):
        """Jay's question about a ticket's open questions: typed into its task session (Daemon.slack_ask_back), which
        answers into this thread (agent_reply). With no task session it goes to the project's lead instead."""
        try:
            r = await self.d.slack_ask_back(key, text)
        except Exception as e:  # noqa: BLE001
            return {"did": "ask_back_failed", "say": f"Could not send that: {esc(getattr(e, 'message', None) or e)}"}
        if r.get("delivered"):
            return {"did": "asked_back",
                    "say": "Sent to the agent. Its answer comes back in this thread; your answers still go here too."}
        if r.get("noSession"):
            return await self.to_lead(project, text, key)
        return {"did": "ask_back_undelivered",
                "say": "Not delivered: " + esc(str(r.get("reason") or "the task session was not reached"))
                + ". Try again in a minute."}

    def _questions_thread(self, key):
        """(channel id, ts) of the latest questions DM for this ticket, or None."""
        found = [(item.get("at") or 0, k) for k, item in self.threads.items()
                 if item.get("type") == "need" and item.get("kind") == "questions" and item.get("ref") == key]
        if not found:
            return None
        cid, _, ts = max(found)[1].partition(":")
        return (cid, ts) if cid and ts else None

    async def agent_reply(self, key, project, text):
        """The task session's answer to Jay's question (pipeline_cli reply), in the thread of the ticket's latest
        questions DM, quoted so it reads as the agent's words; a new DM when there is no such thread. Never a client
        project's. Returns whether it was posted."""
        if not self.settings["slack"] or self.client(project) or not str(text or "").strip():
            return False
        quoted = "\n".join(f"> {esc(line)}" for line in str(text).splitlines() if line.strip())
        body = f"*{self.name(project)}* · {esc(key)} · The agent answers:\n{quoted}"
        where = self._questions_thread(key)
        if where is None:
            return bool(await self.post("dm", body, item={"type": "ticket", "project": project, "ref": key}))
        try:
            await self._call(self.slack().post, where[0], redact(body)[0][:POST_LIMIT], where[1], None)
        except SlackError as e:
            self._fail("slack agent reply", e)
            return False
        return True

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
        for i, (q, a) in enumerate(zip(qs, parts), 1):
            if bad_pick(q, a):
                which = f"Question {i} has" if len(qs) > 1 else "This question has"
                n = len(q["options"])
                return {"did": "answer_invalid",
                        "say": f"{which} options " + (f"a–{LETTERS[n - 1]}" if len(qs) > 1 else f"1–{n}")
                               + ". Reply with those, or start with Other: for your own answer."}
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
            to = r.get("deliveredTo")
            if r.get("delivered"):
                said = "Answered." + (" Sent to the project's lead (no task session is running)." if to == "lead"
                                      else " Sent to the task's session.")
            elif to == "lead":
                said = "Answered. Saved for the project's lead in Messages; it reads it when it runs."
            else:
                said = "Answered. Not delivered yet: " + esc(str(r.get("reason") or "no session was reached")) + "."
        return {"did": "answered", "say": said}

    def allows(self, gate):
        """Whether a Slack reply closes this gate now: fixed in code (SLACK_GATES), then Jay's replyScope."""
        scope = self.settings["replyScope"]
        return (gate in PLAN_GATES or (gate in LOW_RISK_GATES and scope in ("answers_low_risk", "all"))
                or (gate in SHIP_GATES and scope == "all"))

    async def approve(self, key, gate, item=None):
        link = self.link({"ref": key})
        if not self.allows(gate):
            return {"did": "approval_refused",
                    "say": "That one is approved in CommandCenter, not from Slack." + (f" <{link}|Open it>" if link else "")}
        # Only the gate that message showed: same ticket, gate, reason and time, and for a plan the same plan.
        # Anything else is refused.
        now = [n for n in self.needs() if n.get("kind") == "gate" and n.get("ref") == key and n.get("gate") == gate]
        same = bool(item) and any(_digest(n.get("text")) == item.get("textHash") and n.get("since") == item.get("since")
                                  for n in now)
        if gate in PLAN_GATES and item and not item.get("planHash"):
            return {"did": "approval_refused",
                    "say": "This plan could not be shown here in full, so it is approved in CommandCenter only."
                    + (f" <{link}|Open it>" if link else "")}
        if same and gate in PLAN_GATES:
            p = self._plan(key)
            same = p is not None and bool(item.get("planHash")) and plan_digest(p["plan"]) == item["planHash"]
        if same and gate == "merge":
            same = bool(item.get("head")) and self._review(key).get("head") == item["head"]
        if not same:
            return {"did": "approval_stale",
                    "say": "This has changed since this message, so nothing was approved." + (f" <{link}|Open it>" if link else "")}
        try:
            if gate == "merge":
                # The Merge button's own path, for this one PR at the head the DM showed.
                m = await self.d.slack_merge(key, item["head"])
                if not m.get("merging"):
                    why = "; ".join(esc(s.get("reason")) for s in m.get("skipped") or []) or "it is no longer ready"
                    return {"did": "merge_skipped", "say": f"Not merged: {why}."}
                return {"did": "approved_merge", "say": "Merging: the lead merges this PR at that head and reports "
                                                       "in the ticket's thread."}
            # A plan: the daemon checks the hash again as it closes the gate, so a plan replaced after the check
            # above is not approved either.
            r = await (self.d.slack_confirm(key, gate, plan_hash=item.get("planHash")) if gate in PLAN_GATES
                       else self.d.slack_confirm(key, gate))
        except Exception as e:  # noqa: BLE001
            return {"did": "approve_failed", "say": f"Could not approve: {esc(getattr(e, 'message', None) or e)}"}
        said = {"failure": "Blocker cleared; the task resumes.", "ui": "UI accepted.",
                "plan": "Plan approved; implementation starts."}.get(gate, "Approved.")
        d = ((r or {}).get("work") or {}).get("deploy") or {}
        if gate == "deploy" and d.get("approvedAt") and not d.get("result"):
            said = ("Approved to prepare. The agent writes the deploy plan and it comes to you here as a new message; "
                    "nothing deploys until you reply *deploy* to that one.")
        elif gate == "deploy":
            said = "Release approved."
        return {"did": f"approved_{gate}",
                "say": said + ("" if (r or {}).get("delivered", True) else " The task session was not running to hear it.")}

    async def deploy_go(self, key, item):
        """Jay's "deploy" reply to a deploy plan DM: the go for exactly that plan (Daemon.slack_deploy checks it again
        in the transaction that records it)."""
        link = self.link({"ref": key})
        if not self.allows("deploy"):
            return {"did": "deploy_refused",
                    "say": "Deploys from Slack are off now: set Your Slack replies to Everything in CommandCenter, then "
                           "reply *deploy* here." + (f" <{link}|Open it>" if link else "")}
        if not item.get("planHash"):
            return {"did": "deploy_refused",
                    "say": "Nothing was deployed: this plan could not be shown here in full. Reply here to ask the "
                           "agent for a shorter one with no secrets in it."}
        d = self._deploy(key)
        if not d.get("plan") or plan_digest(d["plan"]) != item["planHash"] or d.get("goAt") or d.get("result"):
            return {"did": "deploy_stale",
                    "say": "This plan changed or was already handled, so nothing was deployed." + (f" <{link}|Open it>" if link else "")}
        try:
            r = await self.d.slack_deploy(key, item["planHash"])
        except Exception as e:  # noqa: BLE001
            return {"did": "deploy_failed", "say": f"Could not confirm: {esc(getattr(e, 'message', None) or e)}"}
        return {"did": "deploy_confirmed",
                "say": "Deploying by this plan. The result comes in the ticket's thread."
                + ("" if (r or {}).get("delivered", True) else " The task session was not running to hear it: open "
                   "CommandCenter to start it.")}

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
        files = [f for f in msg.get("files") or [] if isinstance(f, dict) and f.get("id")]
        upload = bool(files) and self.files_upload(conv)
        if self.client(conv):
            body = "replied. Client project: read it in CommandCenter."
        elif upload:
            body = esc(str(msg.get('text') or '')[:3000]) or f"sent {plural(len(files), 'file')}."
        else:
            body = esc(str(msg.get('text') or '')[:2800 if files else 3000])
            if files:
                body = f"{body}\n{self.file_list(files, conv)}" if body else self.file_list(files, conv)
        as_ = (who, CTO_ICON if conv == "cto" else LEAD_ICON)
        if origin:
            cid, thread = origin["channel"], origin["ts"]
            posted = await self._reply(cid, thread, body, as_)
        else:
            where = self.conf["cto_channel"] if conv == "cto" else self.conf["channels"][conv] \
                if self.conf["channels"].get(conv) and not self.client(conv) else "dm"
            thread = posted = await self.post(where, body, who=as_)
            cid = (await (self.dm_id() if where == "dm" else self.channel_id(where))) if posted else None
        if upload and posted:
            await self.upload_files(cid, thread, files, conv)

    def file_list(self, files, conv, failed=None):
        """Files that stay in CommandCenter, for Slack: one line each (name and size) and why they are not here.
        SamVision's and the CTO's get a count only: a file name can carry an address or an MLS number."""
        if conv in NO_SLACK_FILES:
            whose = "The CTO's" if conv == "cto" else self.name(conv)
            return (f"_:paperclip: {plural(len(files), 'file')} in CommandCenter → Messages. {whose} files and their "
                    "names never go to Slack._")
        lines = [f":paperclip: {esc(cut(str(f.get('name') or 'file'), 80))} · {size_text(f.get('size'))}" for f in files]
        if failed:
            why = ("Slack has not granted the bot files:write yet (docs/runbooks/slack-and-ntfy.md)"
                   if "missing_scope" in failed or "not_allowed_token_type" in failed
                   else "it looks like it holds a password, token or key" if SECRET_FILE in failed
                   else "the upload to Slack failed")
            lines.append(f"_In CommandCenter → Messages: {why}._")
        else:
            lines.append(f"_In CommandCenter → Messages. To get {self.name(conv)}'s files here, switch it on in "
                         "Settings → Slack and phone._")
        return "\n".join(lines)

    async def upload_files(self, cid, thread, files, conv):
        """Upload a lead's files into the thread its words went to. A file that does not upload is listed instead."""
        failed, reason = [], None
        for f in files:
            try:
                data = await self._call(self._lead_file, f["id"], conv)
                await self._call(self.slack().upload, cid, thread, str(f.get("name") or "file"), data)
            except Exception as e:  # noqa: BLE001 — a file that cannot go is listed; the words already went
                self._fail("slack file", e)
                failed.append(f)
                reason = reason or str(e)
                continue
            # What left the server, on the record: which conversation's file, its name, size and digest.
            self.d._event("notify", "notify.file_uploaded", f"{conv}: uploaded {cut(str(f.get('name')), 120)} to Slack",
                          data={"conversation": conv, "fileId": f["id"], "size": len(data), "sha256": f.get("sha256")})
        if failed:
            await self._reply(cid, thread, self.file_list(failed, conv, failed=reason))

    def _lead_file(self, fid, conv):
        """The bytes of a file the lead of `conv` sent in Messages, at most UPLOAD_MAX."""
        fd, row = self.d.chat.open(fid)
        with os.fdopen(fd, "rb") as fh:
            if row.get("conversation") != conv or row.get("side") != "lead" or row.get("messageId") is None:
                raise SlackError("not a file this lead sent")
            data = fh.read(UPLOAD_MAX + 1)
        if len(data) > UPLOAD_MAX:
            raise SlackError("file too large to upload")
        # Words to Slack go through redact(); a text file is checked the same way and stays here if it would change.
        # (Messages already refused one that matched onboarding.SECRET_RE when the lead sent it.)
        if str(row.get("mime") or "").startswith("text/") and redact(data.decode("utf-8", "replace"))[1]:
            raise SlackError(SECRET_FILE)
        return data

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
