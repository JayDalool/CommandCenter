"""The HTTP and WebSocket surface. This file IS the list of what ccd can do.

    GET  /api/health                 no token; booleans, ages and counters only
    GET  /api/state                  full bootstrap
    GET  /api/activity               event history
    GET  /api/agents/{id}/tail       on-demand pane output, redacted, never stored
    WS   /api/events?since=<seq>     replay from the log, then live
    POST /api/action/answer          type an answer into a BLOCKED agent
    POST /api/action/focus           focus an agent's pane
    POST /api/action/ack             acknowledge an alert
    POST /api/action/dispatch        send a task to an idle coordinator (guarded)

There is deliberately no endpoint for merge, deploy, production commands,
--apply, secrets, Docker, destructive git, or config and rule changes. A test
asserts this route table exactly, so adding one is a visible, reviewed change.
"""
import asyncio
import json
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import security
from .daemon import ActionError

NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _json(data, status=200):
    return JSONResponse(data, status_code=status, headers=NO_STORE)


class Guard:
    """Host, Origin, token and content-type checks, for HTTP and WebSocket alike."""

    def __init__(self, app, token, port):
        self.app = app
        self.token = token
        self.hosts = security.allowed_hosts(port)
        self.origins = security.allowed_origins(port)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        path = scope.get("path", "")
        problem = None
        if headers.get("host", "") not in self.hosts:
            problem = (403, "bad Host header")
        elif headers.get("origin") and headers["origin"] not in self.origins:
            problem = (403, "cross-origin request refused")
        elif path != "/api/health":
            presented = headers.get("x-ccd-token")
            if not presented and scope["type"] == "websocket":
                presented = (parse_qs(scope.get("query_string", b"").decode()).get("token") or [""])[0]
            if not security.token_ok(self.token, presented):
                problem = (401, "token required")
            elif scope["type"] == "http" and scope.get("method") == "POST" and \
                    not headers.get("content-type", "").split(";")[0].strip() == "application/json":
                problem = (415, "actions take application/json")
        if problem is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if problem[0] == 401 else 4403})
            return
        await _json({"ok": False, "error": problem[1]}, problem[0])(scope, receive, send)


def create_app(daemon, token, port, lifespan=None):
    async def health(request):
        return _json(daemon.health())

    async def state(request):
        if daemon.snap is None:
            return _json({"ok": False, "error": "warming up", "health": daemon.health(short=True)}, 503)
        return _json(daemon.state())

    async def activity(request):
        q = request.query_params
        try:
            limit = int(q.get("limit", "100"))
            before = int(q["before"]) if "before" in q else None
            since = int(q["since"]) if "since" in q else None
        except ValueError:
            return _json({"ok": False, "error": "limit/before/since must be integers"}, 400)
        if since is not None:
            events = daemon.store.since(since, limit=max(1, min(limit, 1000)))
        else:
            events = daemon.store.recent(limit=limit, before=before, kind=q.get("kind"), project=q.get("project"))
        return _json({"seq": daemon.seq, "events": events})

    async def tail(request):
        try:
            lines = int(request.query_params.get("lines", "40"))
        except ValueError:
            return _json({"ok": False, "error": "lines must be an integer"}, 400)
        try:
            return _json(await daemon.tail(request.path_params["agent_id"], lines))
        except ActionError as e:
            return _json({"ok": False, "error": e.message}, e.status)

    async def _body(request):
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ActionError(400, "body must be JSON")
        if not isinstance(data, dict):
            raise ActionError(400, "body must be a JSON object")
        return data

    def action(fn):
        async def handler(request):
            try:
                return _json(await fn(await _body(request)))
            except ActionError as e:
                return _json({"ok": False, "error": e.message}, e.status)
        return handler

    async def answer(body):
        return await daemon.act_answer(str(body.get("agentId", "")), body.get("text"))

    async def focus(body):
        return await daemon.act_focus(str(body.get("agentId", "")))

    async def ack(body):
        return await daemon.act_ack(body.get("alertId"))

    async def dispatch(body):
        return await daemon.act_dispatch(str(body.get("project", "")), body.get("taskId"),
                                         str(body.get("verb", "")), body.get("note", ""))

    async def events(ws: WebSocket):
        await ws.accept()
        q = daemon.subscribe()
        try:
            raw = ws.query_params.get("since")
            current = daemon.seq
            last = current
            if raw is None:
                await ws.send_json({"type": "hello", "seq": current})
            else:
                try:
                    since = int(raw)
                except ValueError:
                    since = -1
                first = daemon.store.first_seq()
                if since < 0 or since > current or (first and since < first - 1):
                    await ws.send_json({"type": "events_lost", "seq": current,
                                        "reason": "since is outside the retained log; refetch /api/state"})
                else:
                    last = since
                    while True:
                        batch = daemon.store.since(last, limit=1000)
                        for ev in batch:
                            await ws.send_json({"type": "event", "event": ev})
                            last = ev["seq"]
                        if len(batch) < 1000:
                            break
                    await ws.send_json({"type": "replay_done", "seq": last})
            while True:
                if q.lost:
                    q.lost = False
                    await ws.send_json({"type": "events_lost", "seq": daemon.seq,
                                        "reason": "client fell behind; refetch /api/state"})
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "ping", "seq": daemon.seq})
                    continue
                if ev["seq"] <= last:
                    continue  # already sent during replay
                last = ev["seq"]
                await ws.send_json({"type": "event", "event": ev})
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            pass
        finally:
            daemon.unsubscribe(q)

    routes = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/state", state, methods=["GET"]),
        Route("/api/activity", activity, methods=["GET"]),
        Route("/api/agents/{agent_id}/tail", tail, methods=["GET"]),
        WebSocketRoute("/api/events", events),
        Route("/api/action/answer", action(answer), methods=["POST"]),
        Route("/api/action/focus", action(focus), methods=["POST"]),
        Route("/api/action/ack", action(ack), methods=["POST"]),
        Route("/api/action/dispatch", action(dispatch), methods=["POST"]),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.routes_table = routes
    return Guard(app, token, port), app
