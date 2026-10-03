"""A herdr server that speaks the real 0.9.3 wire protocol, for tests.

It serves a snapshot you control, keeps subscriptions open, pushes events on
demand, records every call, and can drop every connection or go away entirely
— which is how the reconnect and resync paths are proven without touching the
real herdr.
"""
import asyncio
import copy
import json
import os
import tempfile
import threading
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load_snapshot(name="snapshot_named.json"):
    return json.loads((FIXTURES / name).read_text())["result"]["snapshot"]


class FakeHerdr:
    def __init__(self, snapshot=None, protocol=22):
        self.snapshot = copy.deepcopy(snapshot if snapshot is not None else load_snapshot())
        self.protocol = protocol
        self.calls = []
        self.subscriptions = []        # list of (subscription list, writer)
        self.tails = {}                # pane_id -> text
        self.fail_methods = {}         # method -> (code, message)
        self.dir = tempfile.mkdtemp(prefix="fake-herdr-")
        self.path = os.path.join(self.dir, "herdr.sock")
        self.loop = None
        self.server = None
        self._thread = None

    # ---------- lifecycle ----------

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.server = await asyncio.start_unix_server(self._client, path=self.path)

    async def stop(self):
        await self.drop_subscriptions()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def start_in_thread(self):
        """Run on its own loop in a thread (for Starlette's TestClient, which owns another loop)."""
        ready = threading.Event()

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.start())
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        ready.wait(5)
        return self

    def run(self, coro_fn, *args):
        """Call an async method of this fake from another thread and wait for it."""
        return asyncio.run_coroutine_threadsafe(coro_fn(*args), self.loop).result(5)

    def stop_thread(self):
        if self.loop and self._thread:
            self.run(self.stop)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(5)

    # ---------- controls ----------

    def agent(self, pane_id):
        return next(a for a in self.snapshot["agents"] if a["pane_id"] == pane_id)

    def pane(self, pane_id):
        return next(p for p in self.snapshot["panes"] if p["pane_id"] == pane_id)

    def set_status(self, pane_id, status):
        self.agent(pane_id)["agent_status"] = status
        self.pane(pane_id)["agent_status"] = status

    def add_agent(self, pane_id, cwd, name=None, status="idle", workspace_id="wE"):
        pane = {"pane_id": pane_id, "workspace_id": workspace_id, "tab_id": f"{workspace_id}:t1",
                "agent_status": status, "cwd": cwd, "foreground_cwd": cwd, "terminal_title_stripped": "x"}
        agent = dict(pane, agent="claude",
                     agent_session={"agent": "claude", "kind": "id", "source": "herdr:claude", "value": f"s-{pane_id}"})
        if name:
            agent["name"] = name
        self.snapshot["panes"].append(pane)
        self.snapshot["agents"].append(agent)

    def remove_agent(self, pane_id):
        self.snapshot["agents"] = [a for a in self.snapshot["agents"] if a["pane_id"] != pane_id]
        self.snapshot["panes"] = [p for p in self.snapshot["panes"] if p["pane_id"] != pane_id]

    async def push(self, event, data):
        """Send one event line to every open subscription."""
        line = (json.dumps({"event": event, "data": dict(data, type=event)}) + "\n").encode()
        for _, w in list(self.subscriptions):
            try:
                w.write(line)
                await w.drain()
            except (ConnectionError, OSError):
                pass

    async def push_status(self, pane_id, status):
        """Exactly what herdr 0.9.3 sends: a DOTTED name, unlike structural events."""
        self.set_status(pane_id, status)
        line = (json.dumps({"data": {"agent": "claude", "agent_status": status, "pane_id": pane_id,
                                     "workspace_id": "wE"}, "event": "pane.agent_status_changed"}) + "\n").encode()
        for _, w in list(self.subscriptions):
            try:
                w.write(line)
                await w.drain()
            except (ConnectionError, OSError):
                pass

    async def drop_subscriptions(self):
        for _, w in list(self.subscriptions):
            w.close()
        self.subscriptions.clear()

    def watched_panes(self):
        """pane_ids the latest subscription asked status changes for."""
        if not self.subscriptions:
            return set()
        subs = self.subscriptions[-1][0]
        return {s["pane_id"] for s in subs if s.get("type") == "pane.agent_status_changed"}

    # ---------- protocol ----------

    async def _client(self, reader, writer):
        keep = False
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                req = json.loads(line)
                method, params, rid = req.get("method"), req.get("params") or {}, req.get("id")
                self.calls.append((method, params))
                if method in self.fail_methods:
                    code, msg = self.fail_methods[method]
                    reply = {"id": rid, "error": {"code": code, "message": msg}}
                elif method == "ping":
                    reply = {"id": rid, "result": {"type": "pong", "version": "0.9.3", "protocol": self.protocol}}
                elif method == "session.snapshot":
                    reply = {"id": rid, "result": {"type": "session_snapshot", "snapshot": copy.deepcopy(self.snapshot)}}
                elif method == "events.subscribe":
                    self.subscriptions.append((params.get("subscriptions") or [], writer))
                    reply = {"id": rid, "result": {"type": "subscription_started"}}
                    keep = True
                elif method == "agent.read":
                    target = params.get("target")
                    a = next((x for x in self.snapshot["agents"] if target in (x["pane_id"], x.get("name"))), None)
                    if a is None:
                        reply = {"id": rid, "error": {"code": "agent_not_found", "message": f"agent target {target} not found"}}
                    else:
                        text = self.tails.get(a["pane_id"], "line one\nline two")
                        reply = {"id": rid, "result": {"type": "agent_read", "read": {
                            "pane_id": a["pane_id"], "workspace_id": "wE", "tab_id": "wE:t1", "source": "recent",
                            "format": "text", "text": text, "revision": 1, "truncated": False}}}
                elif method in ("agent.focus", "agent.prompt", "pane.send_text", "pane.send_keys"):
                    reply = {"id": rid, "result": {"type": "ok"}}
                else:
                    reply = {"id": rid, "error": {"code": "unknown_method", "message": method}}
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
                if keep:
                    # A subscription holds the connection until it is dropped.
                    while not writer.is_closing():
                        if await reader.read(1) == b"":
                            break
                    break
        except (ConnectionError, OSError, json.JSONDecodeError):
            pass
        finally:
            self.subscriptions = [(s, w) for s, w in self.subscriptions if w is not writer]
            if not writer.is_closing():
                writer.close()
