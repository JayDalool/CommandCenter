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

    GET   /api/tasks                 every ticket (compact), projects, vocabulary
    POST  /api/tasks                 create a ticket (project + title; the rest optional)
    GET   /api/tasks/import-preview  what importing INDEX.md / issues / MY_ACTIONS WOULD do; writes nothing
    GET   /api/tasks/{key}           one ticket: relations, subtasks, links, notes, timeline
    PATCH /api/tasks/{key}           change fields (audited per field)
    GET   /api/tasks/{key}/context   the ticket as an agent brief ("work CC-012")
    POST  /api/tasks/{key}/comments  add a note
    POST  /api/tasks/{key}/relations add/remove blocks, blocked_by, related, duplicates
    POST  /api/tasks/{key}/links     add/remove an external link (a PR, a legacy ID)

    GET   /, /assets/*               the built web UI (web/app/dist), when present. Public
                                     code only; every /api path except health needs the token.

There is deliberately no endpoint for merge, deploy, production commands,
--apply, secrets, Docker, destructive git, or config and rule changes. A test
asserts this route table exactly, so adding one is a visible, reviewed change.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import security
from .daemon import ActionError

NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
WS_PROTOCOL = "ccd.v1"
WS_TOKEN_PREFIX = "ccd-token."
WRITE_METHODS = ("POST", "PATCH", "PUT", "DELETE")


def ws_token_from_protocols(header):
    """A browser cannot set headers on a WebSocket, so the UI offers the token as a
    subprotocol (`ccd-token.<token>`) next to `ccd.v1`. It never appears in a URL,
    in history, or in uvicorn's path log."""
    for item in (header or "").split(","):
        item = item.strip()
        if item.startswith(WS_TOKEN_PREFIX):
            return item[len(WS_TOKEN_PREFIX):]
    return ""


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
        elif (path.startswith("/api/") or path == "/api" or scope["type"] == "websocket") and path != "/api/health":
            presented = headers.get("x-ccd-token")
            if not presented and scope["type"] == "websocket":
                presented = ws_token_from_protocols(headers.get("sec-websocket-protocol")) or \
                    (parse_qs(scope.get("query_string", b"").decode()).get("token") or [""])[0]
            if not security.token_ok(self.token, presented):
                problem = (401, "token required")
            elif scope["type"] == "http" and scope.get("method") in WRITE_METHODS and \
                    not headers.get("content-type", "").split(";")[0].strip() == "application/json":
                problem = (415, "actions take application/json")
        elif scope["type"] == "http" and scope.get("method") not in ("GET", "HEAD"):
            problem = (405, "the UI is read-only files")
        if problem is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if problem[0] == 401 else 4403})
            return
        await _json({"ok": False, "error": problem[1]}, problem[0])(scope, receive, send)


class UiFiles:
    """The built UI with strict headers. Same origin as the API, so no CORS and no proxy."""

    def __init__(self, directory, port):
        self.files = StaticFiles(directory=str(directory), html=True)
        self.headers = [
            (b"content-security-policy", (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                f"connect-src 'self' ws://127.0.0.1:{port} ws://localhost:{port}; font-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'").encode()),
            (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer"),
            (b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-cache"),
        ]

    async def __call__(self, scope, receive, send):
        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                msg = dict(msg, headers=list(msg.get("headers", [])) + self.headers)
            await send(msg)
        await self.files(scope, receive, send_with_headers)


def ui_dir():
    return Path(__file__).resolve().parents[2] / "web" / "app" / "dist"


def create_app(daemon, token, port, lifespan=None, ui=None):
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

    async def ack(body):
        return await daemon.act_ack(body.get("alertId"))

    async def dispatch(body):
        return await daemon.act_dispatch(str(body.get("project", "")), body.get("taskId"),
                                         str(body.get("verb", "")), body.get("note", ""))

    async def focus_any(body):
        if body.get("workspaceId") or body.get("tabId"):
            return await daemon.act_focus_layout(body.get("workspaceId"), body.get("tabId"))
        return await daemon.act_focus(str(body.get("agentId", "")))

    # ---------- tickets ----------

    def guarded(fn):
        async def handler(request):
            try:
                body = await _body(request) if request.method in WRITE_METHODS else None
                return _json(await fn(request, body), 201 if request.method == "POST" and fn is create_task else 200)
            except ActionError as e:
                return _json({"ok": False, "error": e.message}, e.status)
        return handler

    async def list_tasks(request, _):
        q = request.query_params
        return daemon.task_list(project=q.get("project") or None, include_archived=q.get("archived") == "1")

    async def create_task(request, body):
        return daemon.task_create(body)

    async def import_preview(request, _):
        daemon._need_tasks()
        return await asyncio.to_thread(daemon.task_import_preview)

    async def get_task(request, _):
        return daemon.task_get(request.path_params["key"])

    async def patch_task(request, body):
        return daemon.task_update(request.path_params["key"], body)

    async def task_context(request, _):
        return daemon.task_context(request.path_params["key"])

    async def comment_task(request, body):
        return daemon.task_comment(request.path_params["key"], body.get("body"))

    async def relate_task(request, body):
        return daemon.task_relate(request.path_params["key"], str(body.get("kind") or ""),
                                  str(body.get("target") or ""), bool(body.get("remove")))

    async def link_task(request, body):
        return daemon.task_link(request.path_params["key"], body)

    async def events(ws: WebSocket):
        offered = [p.strip() for p in (ws.headers.get("sec-websocket-protocol") or "").split(",")]
        await ws.accept(subprotocol=WS_PROTOCOL if WS_PROTOCOL in offered else None)
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
        Route("/api/action/focus", action(focus_any), methods=["POST"]),
        Route("/api/action/ack", action(ack), methods=["POST"]),
        Route("/api/action/dispatch", action(dispatch), methods=["POST"]),
        Route("/api/tasks", guarded(list_tasks), methods=["GET"]),
        Route("/api/tasks", guarded(create_task), methods=["POST"]),
        Route("/api/tasks/import-preview", guarded(import_preview), methods=["GET"]),
        Route("/api/tasks/{key}", guarded(get_task), methods=["GET"]),
        Route("/api/tasks/{key}", guarded(patch_task), methods=["PATCH"]),
        Route("/api/tasks/{key}/context", guarded(task_context), methods=["GET"]),
        Route("/api/tasks/{key}/comments", guarded(comment_task), methods=["POST"]),
        Route("/api/tasks/{key}/relations", guarded(relate_task), methods=["POST"]),
        Route("/api/tasks/{key}/links", guarded(link_task), methods=["POST"]),
    ]
    mounts = []
    ui = ui_dir() if ui is None else ui
    if ui and Path(ui, "index.html").is_file():
        mounts.append(Mount("/", app=UiFiles(ui, port), name="ui"))
    app = Starlette(routes=routes + mounts, lifespan=lifespan)
    app.state.routes_table = routes
    return Guard(app, token, port), app
