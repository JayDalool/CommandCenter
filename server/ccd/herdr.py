"""herdr socket client. The ONLY module in ccd that speaks herdr's protocol.

Protocol (herdr 0.9.3, protocol 22), verified against the live server:

  * newline-delimited JSON over the unix socket ~/.config/herdr/herdr.sock
  * request  {"id": str, "method": str, "params": {...}}
  * response one line, {"id", "result": {...}} or {"id", "error": {"code", "message"}}
  * events.subscribe keeps its connection open. First line is
    {"result": {"type": "subscription_started"}}, then one line per event:
    {"event": "pane_focused", "data": {"type": "pane_focused", "pane_id": ...}}

Events carry NO sequence number, so a dropped connection can lose events with
no way to tell which. ccd therefore treats every (re)connect as a gap and
resyncs from session.snapshot, and also reconciles on a timer.

ccd never owns a pane. It reads (snapshot, agent.read) and, for the few
allowed actions, writes keystrokes into an agent that already exists
(agent.focus, pane.send_text, pane.send_keys, agent.prompt). It never
starts, stops, splits, closes or moves anything.
"""
import asyncio
import itertools
import json

PROTOCOL = 22

# Structural changes: who exists, where. Each one triggers a debounced resync.
STRUCTURAL = ("pane.created", "pane.closed", "pane.updated", "pane.exited", "pane.agent_detected",
              "pane.moved", "workspace.created", "workspace.closed", "workspace.renamed",
              "workspace.moved", "tab.created", "tab.closed", "tab.moved")

# Methods ccd may call. Anything else is refused before it reaches the socket.
ALLOWED_METHODS = frozenset({
    "ping", "session.snapshot", "events.subscribe",
    "agent.read", "agent.focus", "agent.prompt",
    "pane.send_text", "pane.send_keys",
})


class HerdrError(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


class Herdr:
    def __init__(self, path, timeout=5.0):
        self.path = str(path)
        self.timeout = timeout
        self._ids = itertools.count(1)

    async def _open(self):
        return await asyncio.wait_for(
            asyncio.open_unix_connection(self.path, limit=32 * 1024 * 1024), self.timeout)

    def _request(self, method, params):
        if method not in ALLOWED_METHODS:
            raise HerdrError(f"ccd may not call {method}", "not_allowed")
        return (json.dumps({"id": f"ccd:{next(self._ids)}", "method": method,
                            "params": params or {}}) + "\n").encode()

    @staticmethod
    def _result(line):
        if not line:
            raise HerdrError("herdr closed the connection", "closed")
        msg = json.loads(line)
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            raise HerdrError(str(err.get("message", ""))[:200], str(err.get("code", "")))
        return msg.get("result") or {}

    async def call(self, method, params=None):
        payload = self._request(method, params)
        reader, writer = await self._open()
        try:
            writer.write(payload)
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), self.timeout)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
        return self._result(line)

    async def ping(self):
        return await self.call("ping")

    async def snapshot(self):
        """The bare snapshot body: {workspaces, tabs, panes, agents, layouts, ...}."""
        result = await self.call("session.snapshot")
        snap = result.get("snapshot")
        if not isinstance(snap, dict):
            raise HerdrError("session.snapshot returned no snapshot", "bad_shape")
        return snap

    async def subscribe(self, subscriptions):
        """Open a subscription. Returns (reader, writer) positioned after the start line."""
        payload = self._request("events.subscribe", {"subscriptions": subscriptions})
        reader, writer = await self._open()
        try:
            writer.write(payload)
            await writer.drain()
            first = await asyncio.wait_for(reader.readline(), self.timeout)
            result = self._result(first)
            if result.get("type") != "subscription_started":
                raise HerdrError(f"unexpected subscribe reply {str(result)[:120]}", "bad_shape")
        except BaseException:
            writer.close()
            raise
        return reader, writer

    async def read_tail(self, target, lines):
        result = await self.call("agent.read", {"target": target, "source": "recent",
                                                "lines": int(lines), "strip_ansi": True})
        read = result.get("read") or {}
        return {"text": read.get("text") or "", "pane_id": read.get("pane_id") or target,
                "truncated": bool(read.get("truncated"))}

    async def focus(self, target):
        return await self.call("agent.focus", {"target": target})

    async def send_answer(self, pane_id, text):
        """Type an answer into a BLOCKED agent and press Enter.

        agent.prompt refuses blocked agents by design (agent_blocked), so an
        answer to an approval or question dialog goes in as keystrokes.
        """
        await self.call("pane.send_text", {"pane_id": pane_id, "text": text})
        await self.call("pane.send_keys", {"pane_id": pane_id, "keys": ["Enter"]})

    async def prompt(self, target, text):
        """Submit a prompt to an idle agent (herdr rejects a blocked one)."""
        return await self.call("agent.prompt", {"target": target, "text": text})


def subscriptions_for(agent_pane_ids):
    """Structural events for everything, status changes for each live agent.

    herdr requires a pane_id on pane.agent_status_changed, so the list is
    rebuilt (and the subscription reopened) whenever the set of agents changes.
    """
    subs = [{"type": t} for t in STRUCTURAL]
    subs += [{"type": "pane.agent_status_changed", "pane_id": p} for p in sorted(agent_pane_ids)]
    return subs


def parse_event(line):
    """One subscription line → (event_name, data), or None for noise.

    herdr spells event names two ways on the same connection: structural
    events arrive as `pane_created`, filtered subscription events as
    `pane.agent_status_changed` (verified live). Names are normalised to the
    underscore form so both reach the same handler.
    """
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict) or "event" not in msg:
        return None
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    return str(msg["event"]).replace(".", "_"), data
