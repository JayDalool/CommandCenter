"""Messages, ccd's side: who each conversation's lead is, delivery, the fixed nudge, and starting a stopped lead.

Mixed into Daemon (daemon.py). The store is chat.Chat (`self.chat`, set by __main__; None = Messages off).

Delivery (Jay's answer C2 b): a message is stored, and the lead gets ONE fixed nudge (NUDGE_TEXT: the conversation
id and the two commands, nothing Jay wrote) through herdr's agent.prompt, only when the lead is idle and its input
line is plainly empty, as the night-shift reminder does. A busy or blocked lead is nudged later by chat_tick; a lead
that never reads is reminded at most NUDGE_MAX times, NUDGE_EVERY apart. The lead reads the words with cc-inbox and
answers with cc-reply (scripts/, ccd/chat_cli.py).

Starting a lead (C7): only when Jay presses Start in Messages, only for a conversation's own lead, and only while
config.json sets "chat_start_leads": true. A start first checks the budgets (ccd/budgets.py, the same report as
Budgets): when the company's or the project's budget is at its hold, the start is refused with what it would exceed
until Jay confirms it (overBudgetOk), and that confirmation is recorded. The start uses herdr's own CLI: a new
workspace at the lead's root (`herdr workspace create --no-focus`), then `herdr agent start <name> --kind claude`
in that workspace's root pane. Nothing is split, moved or closed in Jay's existing layout, and nothing is ever
stopped. This is the one place ccd starts a Claude; README's rule names it.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time

from . import budgets as budgets_mod
from . import chat as chat_mod
from . import coordinators, registry, sources
from . import herdr as herdr_mod
from . import nightshift as nightshift_mod

log = logging.getLogger("ccd")

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
NUDGE_TEXT = ("There is a new message for you in Command Center Messages (conversation: {conv}). Read it with "
              "`{bin}/cc-inbox {conv}` and answer with `{bin}/cc-reply {conv} \"your answer\"` (add --file PATH to "
              "send an image, PDF or Markdown file). Your usual rules, gates and approvals apply to anything it "
              "asks for.")
NUDGE_EVERY = 15 * 60
NUDGE_MAX = 3
CHAT_TICK = 20
CTO_MODEL = "opus"
AGENT_RE = re.compile(r"^agent:[a-z0-9_:-]{1,64}$")
JAY_PER_MINUTE = 30        # Jay's messages per conversation per minute (a stuck client cannot flood a lead's inbox)


class LeadChat:
    """Daemon mixin. Needs: cfg, panes, herdr, herdr_state, tasks, policy, meter_read_at, _projects, _project,
    _fresh_agent, resync, _event, _broker, _throttle."""

    chat = None
    chat_starter = None   # tests replace the herdr CLI runner: fn(argv) -> (code, stdout, stderr)

    # ---------- who ----------

    def chat_ids(self):
        return [chat_mod.CTO] + [p["key"] for p in self._projects()]

    def _need_chat(self, conv=None):
        from .daemon import ActionError
        if self.chat is None:
            raise ActionError(503, "Messages is not configured")
        if conv is not None and conv not in self.chat_ids():
            raise ActionError(404, "no such conversation")

    def _cto_root(self):
        root = self.cfg.get("chat_cto_root") or os.path.expanduser("~")
        return os.path.realpath(os.path.expanduser(str(root)))

    def chat_lead(self, conv):
        """{name, state: ready|offline|found|multiple|none|unknown, status, paneId, root, model, effort, paused}."""
        if conv == chat_mod.CTO:
            name, root, model, effort, paused = "cto", self._cto_root(), self.cfg.get("chat_cto_model") or CTO_MODEL, \
                "", ""
            pane = None
            if self.herdr_state.get("ok"):
                live = [p for p in sources.agent_panes(self.panes) if p.get("agent_name") == "cto"]
                pane = live[0] if len(live) == 1 else None
                state = "ready" if pane else ("multiple" if live else "none")
            else:
                state = "unknown"
        else:
            proj = self._project(conv)
            name, root = coordinators.canonical(proj), coordinators.root_of(proj)
            model, effort, paused = proj.get("model") or "opus", proj.get("effort") or "", registry.paused(conv) or ""
            pane = None
            if self.herdr_state.get("ok"):
                r = coordinators.resolution(proj, self.panes)
                state = r["state"]
                pane = coordinators.pane_for(proj, self.panes, r)
            else:
                state = "unknown"
        return {"name": name, "state": state, "status": (pane or {}).get("status") if pane else None,
                "paneId": (pane or {}).get("pane_id"), "root": root, "model": model, "effort": effort,
                "paused": paused}

    def _lead_public(self, lead):
        # Paths and models stay on the server; the UI needs who and whether it is running.
        running = lead["state"] == "ready"
        status = lead["status"] if running else None
        return {"name": lead["name"], "state": lead["state"], "status": status,
                "running": running, "idle": running and status in ("idle", "done"), "paused": bool(lead["paused"])}

    # ---------- reads ----------

    def chat_overview(self, actor="jay"):
        self._need_jay(actor)
        self._need_chat()
        summ = self.chat.summary()
        out = []
        for conv in self.chat_ids():
            lead = self.chat_lead(conv)
            name = "CTO" if conv == chat_mod.CTO else (self._project(conv) or {}).get("name") or conv
            s = summ.get(conv) or {"unread": 0, "waiting": 0, "last": None}
            out.append({"id": conv, "name": name, "kind": "cto" if conv == chat_mod.CTO else "project",
                        "lead": self._lead_public(lead), **s, "nudges": self.chat.nudge_state(conv)})
        return {"conversations": out, "canStart": bool(self.cfg.get("chat_start_leads")),
                "unread": sum(c["unread"] for c in out), "limits": {"text": chat_mod.TEXT_MAX,
                                                                   "fileBytes": self.chat.max_bytes,
                                                                   "filesPerMessage": chat_mod.FILES_PER_MESSAGE}}

    def chat_history(self, conv, before=None, limit=50, actor="jay"):
        self._need_jay(actor)
        self._need_chat(conv)
        return {"conversation": conv, "messages": self.chat.history(conv, before, limit),
                "lead": self._lead_public(self.chat_lead(conv))}

    def chat_unread_total(self):
        if self.chat is None:
            return 0
        try:
            return sum(self.chat.unread_for_jay().values())
        except Exception:  # noqa: BLE001 — state() must never fail on Messages
            return 0

    # ---------- Jay's side ----------

    @staticmethod
    def lead_actor(conv):
        """The one agent actor that speaks for a conversation's lead (what cc-inbox and cc-reply send)."""
        return "agent:cto" if conv == chat_mod.CTO else f"agent:lead-{conv}"

    def _side_of(self, actor, conv):
        """jay, or lead when actor is THIS conversation's lead. Any other agent is refused: a lead cannot read or
        write another lead's conversation."""
        from .daemon import ActionError
        if actor == "jay":
            return "jay"
        if isinstance(actor, str) and AGENT_RE.match(actor) and actor == self.lead_actor(conv):
            return "lead"
        raise ActionError(403, f"only Jay or {self.lead_actor(conv)} can use this conversation")

    def _need_jay(self, actor):
        from .daemon import ActionError
        if actor != "jay":
            raise ActionError(403, "only Jay reads Messages here; a lead uses cc-inbox")

    def _jay_rate(self, conv):
        from .daemon import ActionError
        now = time.monotonic()
        recent = getattr(self, "_chat_sent", None)
        if recent is None:
            recent = self._chat_sent = {}
        q = [t for t in recent.get(conv, ()) if now - t < 60]
        if len(q) >= JAY_PER_MINUTE:
            raise ActionError(429, f"at most {JAY_PER_MINUTE} messages a minute in one conversation; wait a moment")
        q.append(now)
        recent[conv] = q

    async def chat_send(self, conv, body, actor):
        """POST /api/chat/{conv}/messages. Jay: store and deliver. An agent: the lead's reply (cc-reply)."""
        from .daemon import ActionError
        self._need_chat(conv)
        side = self._side_of(actor, conv)
        files = body.get("files") or []
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ActionError(400, "files must be a list of file ids")
        reply_to = body.get("replyTo")
        if side == "lead":
            self._throttle(f"chat-reply:{conv}", 1.0)
            msg = self._chat_add(conv, "lead", actor, body.get("text") or "", via="cli", reply_to=reply_to,
                                 file_ids=files)
            self._event("chat", "chat.reply", f"{msg['author']} replied in Messages ({conv})", project=self._proj_key(conv),
                        data={"conversation": conv, "messageId": msg["id"], "author": actor,
                              "files": len(msg["files"])})
            return {"ok": True, "message": msg}
        self._jay_rate(conv)
        msg = self._chat_add(conv, "jay", "jay", body.get("text") or "", via="app", reply_to=reply_to,
                             file_ids=files)
        delivery = await self._chat_deliver(conv)
        self._event("chat", "chat.sent", f"Jay messaged {self.chat_lead(conv)['name']} ({delivery})",
                    project=self._proj_key(conv), data={"conversation": conv, "messageId": msg["id"],
                                                        "delivery": delivery, "files": len(msg["files"])})
        return {"ok": True, "message": msg, "delivery": delivery}

    async def deliver_to_lead(self, conversation, text, *, via="slack", ref=None, author="jay"):
        """Jay's words for a lead from somewhere other than HQ (Slack). Stored and delivered like an HQ message;
        never starts a lead (that needs Jay's press and budget check in HQ). Returns {ok, message, delivery}."""
        from .daemon import ActionError
        self._need_chat(conversation)
        if author != "jay":
            raise ActionError(403, "only Jay's words are delivered to a lead")
        if via not in ("slack", "app"):
            raise ActionError(400, "via must be slack or app")
        self._jay_rate(conversation)
        msg = self._chat_add(conversation, "jay", "jay", text, via=via, ref=ref)
        delivery = await self._chat_deliver(conversation)
        self._event("chat", "chat.sent", f"Jay messaged {self.chat_lead(conversation)['name']} from {via} ({delivery})",
                    project=self._proj_key(conversation), data={"conversation": conversation, "messageId": msg["id"],
                                                                "delivery": delivery, "via": via})
        return {"ok": True, "message": msg, "delivery": delivery}

    def chat_seen(self, conv, body, actor):
        from .daemon import ActionError
        self._need_chat(conv)
        if self._side_of(actor, conv) != "jay":
            raise ActionError(403, "agents read with cc-inbox")
        try:
            n = self.chat.mark_seen(conv, "lead", body.get("upTo"))
        except chat_mod.ChatError as e:
            raise ActionError(e.status, e.message)
        if n:
            self._event("chat", "chat.seen", f"Jay read {n} message(s) ({conv})", project=self._proj_key(conv),
                        data={"conversation": conv, "count": n})
        return {"ok": True, "seen": n}

    # ---------- the lead's side ----------

    def chat_inbox(self, conv, actor, peek=False):
        """GET /api/chat/{conv}/inbox, for cc-inbox: Jay's unread messages, oldest first, then marked read."""
        from .daemon import ActionError
        self._need_chat(conv)
        if actor == "jay":
            raise ActionError(403, "the inbox is the lead's; Jay reads the conversation")
        self._side_of(actor, conv)
        msgs = self.chat.unseen(conv, "jay")
        if msgs and not peek:
            self.chat.mark_seen(conv, "jay", msgs[-1]["id"])
            self._event("chat", "chat.read", f"{actor} read {len(msgs)} message(s) ({conv})",
                        project=self._proj_key(conv), data={"conversation": conv, "count": len(msgs), "author": actor})
        recent = self.chat.history(conv, limit=12)
        return {"conversation": conv, "messages": msgs, "recent": [m for m in recent if m["id"] not in
                                                                    {x["id"] for x in msgs}]}

    # ---------- shared ----------

    @staticmethod
    def _proj_key(conv):
        return None if conv == chat_mod.CTO else conv

    def _chat_add(self, conv, side, author, text, **kw):
        from .daemon import ActionError
        try:
            return self.chat.add(conv, side, author, text, **kw)
        except chat_mod.ChatError as e:
            raise ActionError(e.status, e.message)

    async def chat_upload(self, conv, name, chunks, actor, length=None):
        from .daemon import ActionError
        self._need_chat(conv)
        side = self._side_of(actor, conv)
        try:
            row = await self.chat.upload(conv, side, actor, name, chunks, length=length)
        except chat_mod.ChatError as e:
            raise ActionError(e.status, e.message)
        return row

    def chat_open_file(self, fid, actor="jay"):
        """A file's bytes. Jay opens any; a lead only files in its own conversation (others look missing)."""
        from .daemon import ActionError
        self._need_chat()
        if actor != "jay":
            row = self.chat.file(fid) if chat_mod.ID_RE.match(fid or "") else None
            if not row or actor != self.lead_actor(row["conversation"]):
                raise ActionError(404, "no such file")
        try:
            return self.chat.open(fid)
        except chat_mod.ChatError as e:
            raise ActionError(e.status, e.message)
        except FileNotFoundError:
            raise ActionError(404, "no such file")

    # ---------- delivery ----------

    def nudge_text(self, conv):
        return NUDGE_TEXT.format(conv=conv, bin=SCRIPTS)

    async def _chat_deliver(self, conv, reminder=False):
        """Nudge the lead now if it can take it. Returns nudged | queued | lead-offline | lead-paused."""
        lead = self.chat_lead(conv)
        if lead["paused"]:
            return "lead-paused"
        if lead["state"] != "ready":
            return "lead-offline"
        st = self.chat.nudge_state(conv)
        if not reminder and st["count"] and st["lastAt"] and time.time() - st["lastAt"] < NUDGE_EVERY:
            return "nudged"      # already told about unread messages; cc-inbox shows this one too
        try:
            agent = await self._fresh_agent(lead["paneId"])
        except Exception:  # noqa: BLE001 — ActionError (herdr down, gone): the message waits
            return "queued"
        if agent["status"] not in ("idle", "done"):
            return "queued"
        try:
            screen = await self.herdr.read_tail(agent["pane_id"], 40)
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError):
            return "queued"
        if nightshift_mod.input_is_empty(screen["text"]) is not True:
            return "queued"      # never submit a half-typed draft of Jay's in that pane
        self._broker("pane.input", self._proj_key(conv), f"messages nudge -> pane {agent['pane_id']}")
        try:
            await self.herdr.prompt(agent["pane_id"], self.nudge_text(conv))
        except (OSError, herdr_mod.HerdrError, asyncio.TimeoutError) as e:
            log.warning(json.dumps({"msg": "messages nudge failed", "conversation": conv, "error": str(e)[:160]}))
            return "queued"
        self.chat.nudged(conv)
        self._event("action", "action.chat_nudge", f"messages {'reminder' if reminder else 'nudge'} → {lead['name']}",
                    project=self._proj_key(conv), agent_id=agent["pane_id"], data={"kind": "chat_nudge",
                                                                                   "conversation": conv})
        return "nudged"

    async def chat_loop(self):
        while not self._stopping:
            await asyncio.sleep(CHAT_TICK)
            try:
                await self.chat_tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — Messages must never take ccd down
                log.warning(json.dumps({"msg": "messages tick failed", "error": repr(e)[:200]}))

    async def chat_tick(self, now=None):
        """Nudge each idle lead that has unread messages from Jay and has not been nudged for them yet; remind it
        NUDGE_EVERY later, at most NUDGE_MAX times in all, until it reads them."""
        if self.chat is None or not self.herdr_state.get("ok"):
            return
        now = time.time() if now is None else now
        for conv in self.chat.waiting_conversations():
            if conv not in self.chat_ids():
                continue
            st = self.chat.nudge_state(conv)
            if st["count"] >= NUDGE_MAX or (st["lastAt"] and now - st["lastAt"] < NUDGE_EVERY):
                continue
            await self._chat_deliver(conv, reminder=st["count"] > 0)
        try:
            self.chat.prune_pending()
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"msg": "messages prune failed", "error": repr(e)[:200]}))

    # ---------- starting a stopped lead (C7) ----------

    def chat_budget_check(self, conv):
        """The budget lines a new lead session would run against that are at their hold now (company, and the
        project's own). Empty = within budget, or no budget set."""
        company = (self.cfg.get("budgets") or {}).get("company") if isinstance(self.cfg.get("budgets"), dict) else None
        db = getattr(self.tasks, "db", None)
        if db is None:
            return []
        report = budgets_mod.report(db, time.time(), company, self._profile_budgets(), None,
                                    meter_at=self.meter_read_at)
        mine = {("company", "*")} | ({("project", conv)} if conv != chat_mod.CTO else set())
        return [{k: line.get(k) for k in ("scope", "key", "period", "limitUsd", "assessedUsd", "pct", "holdReason")}
                for line in report["lines"] if (line["scope"], line["key"]) in mine and line["state"] == "hold"]

    def _herdr_cli(self, argv):
        if self.chat_starter is not None:
            return self.chat_starter(argv)
        herdr = os.path.abspath(shutil.which("herdr") or os.path.expanduser("~/.local/bin/herdr"))
        r = subprocess.run([herdr, *argv], capture_output=True, text=True, timeout=120, check=False)
        return r.returncode, r.stdout, r.stderr

    async def chat_start(self, conv, body, actor):
        """POST /api/chat/{conv}/start: Jay starts this conversation's lead (C7)."""
        from .daemon import ActionError
        self._need_chat(conv)
        if actor != "jay":
            raise ActionError(403, "only Jay starts a lead")
        if not self.cfg.get("chat_start_leads"):
            raise ActionError(409, "starting leads from Messages is switched off (config.json chat_start_leads)")
        lead = self.chat_lead(conv)
        if lead["paused"]:
            raise ActionError(409, f"{conv} is paused ({lead['paused']}); its lead is not started")
        if not self.herdr_state.get("ok"):
            raise ActionError(503, "herdr unreachable")
        await self.resync("action")
        lead = self.chat_lead(conv)
        if lead["state"] == "ready":
            delivery = await self._chat_deliver(conv)
            return {"ok": True, "started": False, "lead": self._lead_public(lead), "delivery": delivery}
        if lead["state"] in ("found", "multiple"):
            raise ActionError(409, f"a Claude is already running at {lead['name']}'s folder but is not identified as "
                                   f"its lead; adopt it in Workspace instead of starting another")
        if not os.path.isdir(lead["root"]):
            raise ActionError(409, f"{lead['name']}'s folder is not on this server")
        over = self.chat_budget_check(conv)
        if over and body.get("overBudgetOk") is not True:
            return {"ok": False, "needsApproval": True, "overBudget": over,
                    "error": f"starting {lead['name']} would run over budget"}
        self._throttle(f"chat-start:{conv}", 30.0)
        if over:
            self._event("chat", "chat.over_budget_start", f"Jay approved starting {lead['name']} over budget",
                        project=self._proj_key(conv), severity="warn", data={"conversation": conv, "count": len(over)})
        label = f"lead {lead['name']}"
        code, out, err = await asyncio.to_thread(self._herdr_cli, ["workspace", "create", "--cwd", lead["root"],
                                                                   "--label", label, "--no-focus"])
        try:
            pane_id = ((json.loads(out or "{}").get("result") or {}).get("root_pane") or {}).get("pane_id")
        except ValueError:
            pane_id = None
        if code != 0 or not isinstance(pane_id, str) or not pane_id:
            self._event("action", "action.failed", f"starting {lead['name']} failed", severity="warn",
                        project=self._proj_key(conv), data={"kind": "chat_start", "error": (err or out)[:160]})
            raise ActionError(502, f"herdr could not create the lead's workspace: {(err or out).strip()[:160]}")
        args = ["-n", lead["name"], "--rc", lead["name"], "--model", lead["model"]]
        if lead["effort"]:
            args += ["--effort", lead["effort"]]
        self._broker("pane.input", self._proj_key(conv), f"messages start {lead['name']} in pane {pane_id}")
        code, out, err = await asyncio.to_thread(self._herdr_cli, ["agent", "start", lead["name"], "--kind", "claude",
                                                                   "--pane", pane_id, "--timeout", "90000", "--", *args])
        if code != 0:
            self._event("action", "action.failed", f"starting {lead['name']} failed", severity="warn",
                        project=self._proj_key(conv), data={"kind": "chat_start", "pane": pane_id,
                                                             "error": (err or out)[:160]})
            raise ActionError(502, f"herdr could not start {lead['name']} (workspace '{label}' is left open): "
                                   f"{(err or out).strip()[:160]}")
        self._event("action", "action.chat_start", f"Jay started {lead['name']} from Messages",
                    project=self._proj_key(conv), agent_id=pane_id,
                    data={"kind": "chat_start", "conversation": conv, "overBudget": bool(over)})
        await self.resync("action")
        delivery = "queued"
        if self.chat.unseen(conv, "jay"):
            delivery = await self._chat_deliver(conv)
        return {"ok": True, "started": True, "lead": self._lead_public(self.chat_lead(conv)), "delivery": delivery}
