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

    GET   /api/development           ticket → branch → commits → PR → CI → review → merge → verify
    GET   /api/tasks                 every ticket (compact), projects, vocabulary
    POST  /api/tasks                 create a ticket (project + title; the rest optional)
    GET   /api/tasks/import-preview  what importing INDEX.md / issues / MY_ACTIONS WOULD do; writes nothing
    GET   /api/tasks/{key}           one ticket: relations, subtasks, links, notes, timeline
    PATCH /api/tasks/{key}           change fields (audited per field)
    GET   /api/tasks/{key}/context   the ticket as an agent brief ("work CC-012")
    POST  /api/tasks/{key}/comments  add a note
    POST  /api/tasks/{key}/relations add/remove blocks, blocked_by, related, duplicates
    POST  /api/tasks/{key}/links     add/remove an external link (a PR, a legacy ID)

    GET   /api/development/{key}/commits  the commits on a ticket's branch, with GitHub links

  Workspace (roots come from the project registry; the browser names a key, never a path)
    GET   /api/workspace/projects    registered projects: root, branch, GitHub identity, coordinator
    GET   /api/files/list            one folder, lazily (?project=&path=&git=1)
    GET   /api/files/read            one text file for the editor, with its sha (or metadata if binary/large)
    GET   /api/files/download        one file, as an attachment
    POST  /api/files/save            DEVELOPER. atomic replace, refused if changed since opened
    POST  /api/files/upload          DEVELOPER. octet-stream into a folder; fail/replace/rename on a clash
    GET   /api/attachments           a ticket's or project's attachments (?owner=ticket|project&key=)
    POST  /api/attachments           DEVELOPER. octet-stream; stored outside every repository
    GET   /api/attachments/{id}/download   always application/octet-stream + attachment
    DELETE /api/attachments/{id}     DEVELOPER. remove (audited; contents never recorded)
    GET   /api/developer             is this tab's developer session active?
    POST  /api/developer/unlock      developer token → a short-lived in-memory session id
    POST  /api/developer/lock        end that session
    GET   /api/desktop/launcher      the Windows launcher's version, SHA-256 and build commit
    GET   /api/desktop/launcher/download  CommandCenter.exe, as an attachment

  DEVELOPER routes need the ccd token AND `X-CCD-Developer: <session>` from
  /api/developer/unlock. The ordinary ccd token alone can never write a file.

    GET   /, /assets/*               the built web UI (web/app/dist), when present. Public
                                     code only; every /api path except health needs the token.

There is deliberately no endpoint for merge, deploy, production commands,
--apply, secrets, Docker, destructive git, or config and rule changes. A test
asserts this route table exactly, so adding one is a visible, reviewed change.
"""
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from starlette.responses import StreamingResponse

from . import registry, security
from .attachments import content_disposition
from .daemon import ActionError
from .files import FileError

NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
WS_PROTOCOL = "ccd.v1"
WS_TOKEN_PREFIX = "ccd-token."
WRITE_METHODS = ("POST", "PATCH", "PUT", "DELETE")
# The only routes that take a raw byte body instead of JSON. application/octet-stream
# is not a CORS-safelisted type either, so a cross-site page still needs a preflight.
STREAM_PATHS = ("/api/files/upload", "/api/attachments")
DEV_HEADER = "x-ccd-developer"


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
                    headers.get("content-type", "").split(";")[0].strip() != "application/json" and not (
                        path in STREAM_PATHS and scope.get("method") == "POST" and
                        headers.get("content-type", "").split(";")[0].strip() == "application/octet-stream"):
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

    def actor_of(request):
        """Who a write is recorded as. Default jay. An agent may say `X-CCD-Actor: agent:<name>`.

        Self-asserted, not authentication: anything holding the token could claim
        any actor. It keeps honest agents' writes from being filed under Jay.
        """
        a = request.headers.get("x-ccd-actor") or "jay"
        if not re.match(r"^(jay|agent:[a-z0-9_:-]{1,64})$", a):
            raise ActionError(400, "X-CCD-Actor must be jay or agent:<name>")
        return a

    def guarded(fn):
        async def handler(request):
            try:
                body = await _body(request) if request.method in WRITE_METHODS else None
                request.state.actor = actor_of(request)
                return _json(await fn(request, body), 201 if request.method == "POST" and fn is create_task else 200)
            except ActionError as e:
                return _json({"ok": False, "error": e.message}, e.status)
        return handler

    async def list_tasks(request, _):
        q = request.query_params
        return daemon.task_list(project=q.get("project") or None, include_archived=q.get("archived") == "1")

    async def create_task(request, body):
        return daemon.task_create(body, request.state.actor)

    async def import_preview(request, _):
        daemon._need_tasks()
        return await asyncio.to_thread(daemon.task_import_preview)

    async def get_task(request, _):
        return daemon.task_get(request.path_params["key"])

    async def development(request, _):
        return daemon.development(project=request.query_params.get("project") or None)

    async def patch_task(request, body):
        return daemon.task_update(request.path_params["key"], body, request.state.actor)

    async def task_context(request, _):
        return daemon.task_context(request.path_params["key"])

    async def comment_task(request, body):
        return daemon.task_comment(request.path_params["key"], body.get("body"), request.state.actor)

    async def relate_task(request, body):
        return daemon.task_relate(request.path_params["key"], str(body.get("kind") or ""),
                                  str(body.get("target") or ""), bool(body.get("remove")),
                                  request.state.actor)

    async def link_task(request, body):
        return daemon.task_link(request.path_params["key"], body, request.state.actor)

    # ---------- workspace, files, attachments, developer unlock ----------

    files = getattr(daemon, "files", None)
    attach = getattr(daemon, "attachments", None)
    gate = getattr(daemon, "dev_gate", None)

    def _err(e):
        if isinstance(e, FileError):
            return _json({"ok": False, "error": e.message, **e.extra}, e.status)
        return _json({"ok": False, "error": e.message}, e.status)

    def developer(request):
        if gate is None or not gate.check(request.headers.get(DEV_HEADER) or ""):
            raise ActionError(403, "Developer Unlock required")

    def ws_route(fn, dev=False):
        async def handler(request):
            try:
                if files is None or attach is None:
                    raise ActionError(503, "workspace is not configured")
                if dev:
                    developer(request)
                request.state.actor = actor_of(request)
                result = await fn(request)
                return result if not isinstance(result, dict) else _json(result)
            except (ActionError, FileError) as e:
                return _err(e)
        return handler

    def _stream_fd(fd, size, name, ctype="application/octet-stream"):
        def gen():
            with open(fd, "rb", closefd=True) as f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    yield chunk
        return StreamingResponse(gen(), media_type=ctype, headers={
            **NO_STORE, "Content-Disposition": content_disposition(name), "Content-Length": str(size),
            "Content-Security-Policy": "default-src 'none'; sandbox", "X-Frame-Options": "DENY"})

    def _length(request):
        raw = request.headers.get("content-length")
        return int(raw) if raw and raw.isdigit() else None

    async def ws_projects(request):
        return await asyncio.to_thread(daemon.workspace_projects)

    async def dev_commits(request):
        return await asyncio.to_thread(daemon.dev_commits, request.path_params["key"])

    async def files_list(request):
        q = request.query_params
        return await asyncio.to_thread(files.list, q.get("project"), q.get("path", ""), q.get("git") == "1")

    async def files_read(request):
        q = request.query_params
        return await asyncio.to_thread(files.read, q.get("project"), q.get("path", ""))

    async def files_download(request):
        q = request.query_params
        fd, size, name = await asyncio.to_thread(files.open_download, q.get("project"), q.get("path", ""))
        return _stream_fd(fd, size, name)

    async def files_save(request):
        body = await _body(request)
        base = body.get("baseSha")
        if base is not None and not (isinstance(base, str) and re.match(r"^[0-9a-f]{64}$", base)):
            raise ActionError(400, "baseSha must be a sha256 or null")
        out = await asyncio.to_thread(files.save, str(body.get("project") or ""), body.get("path"), body.get("text"),
                                      base)
        daemon._event("files", "file.saved", f"{out['project']}: saved {out['path']}"[:300], project=out["project"],
                      data={"path": out["path"], "size": out["size"]})
        return out

    async def files_upload(request):
        q = request.query_params
        out = await files.upload(q.get("project"), q.get("dir", ""), q.get("name"), request.stream(),
                                 conflict=q.get("conflict") or "fail", length=_length(request))
        daemon._event("files", "file.uploaded", f"{out['project']}: uploaded {out['path']}"[:300],
                      project=out["project"], data={"path": out["path"], "size": out["size"]})
        return out

    def _owner(q):
        kind, key = q.get("owner") or "", (q.get("key") or "").strip()
        if kind == "ticket":
            ts = daemon._need_tasks()
            if not ts.exists(key):
                raise ActionError(404, f"no ticket {key}")
            return kind, ts.get(key)["key"]
        if kind == "project":
            if key not in {p["key"] for p in daemon.cfg["projects"]} | set(registry.PROJECTS):
                raise ActionError(404, f"no project {key}")
            return kind, key
        raise ActionError(400, "owner must be ticket or project")

    async def attach_list(request):
        kind, key = _owner(request.query_params)
        return {"owner": kind, "key": key, "attachments": attach.list(kind, key)}

    def _attach_audit(kind, key, verb, row, actor):
        data = {"id": row["id"], "name": row["name"], "size": row["size"]}
        if kind == "ticket":
            daemon.tasks.note(key, f"attachment_{verb}", actor, data)
            daemon._task_event("task.updated", daemon.tasks.get(key), f"attachment {verb}: {row['name']}"[:200],
                               {"kind": "attachments"})
        else:
            daemon._event("files", f"attachment.{verb}", f"{key}: attachment {verb}: {row['name']}"[:300],
                          project=key, data=data)

    async def attach_add(request):
        kind, key = _owner(request.query_params)
        row = await attach.add(kind, key, request.query_params.get("name"), request.stream(), request.state.actor,
                               length=_length(request))
        _attach_audit(kind, key, "added", row, request.state.actor)
        return row

    async def attach_download(request):
        fd, row = await asyncio.to_thread(attach.open, request.path_params["aid"])
        return _stream_fd(fd, row["size"], row["name"])

    async def attach_remove(request):
        row = attach.get(request.path_params["aid"])
        attach.remove(row["id"], request.state.actor)
        _attach_audit(row["ownerKind"], row["ownerKey"], "removed", row, request.state.actor)
        return {"ok": True, "id": row["id"]}

    async def dev_status(request):
        sid = request.headers.get(DEV_HEADER) or ""
        active = bool(gate and gate.check(sid))
        return _json({"active": active, "expiresIn": gate.expires_in(sid) if active else None,
                      "configured": gate is not None})

    async def dev_unlock(request):
        try:
            body = await _body(request)
        except ActionError as e:
            return _err(e)
        if gate is None:
            return _json({"ok": False, "error": "developer unlock is not configured"}, 503)
        sid, problem = gate.unlock(body.get("token"))
        if not sid:
            return _json({"ok": False, "error": problem}, 429 if "too many" in problem else 403)
        daemon._event("security", "developer.unlocked", "Developer Mode unlocked")
        return _json({"ok": True, "session": sid, "expiresIn": gate.expires_in(sid)})

    async def dev_lock(request):
        if gate is not None:
            gate.lock(request.headers.get(DEV_HEADER) or "")
        return _json({"ok": True})

    def _launcher_meta():
        d = getattr(daemon, "launcher_dir", None)
        try:
            meta = json.loads(Path(d, "launcher.json").read_text()) if d else None
        except (OSError, ValueError):
            meta = None
        exe = Path(d, "CommandCenter.exe") if d else None
        if not meta or not exe or not exe.is_file():
            return None, None
        keep = {k: meta.get(k) for k in ("version", "sha256", "commit", "built_at", "size")}
        return keep, exe

    async def launcher_info(request):
        meta, _ = await asyncio.to_thread(_launcher_meta)
        return _json({"available": bool(meta), **(meta or {})})

    async def launcher_download(request):
        meta, exe = await asyncio.to_thread(_launcher_meta)
        if not meta:
            return _json({"ok": False, "error": "the launcher has not been built on this server"}, 404)
        fd = os.open(exe, os.O_RDONLY)
        return _stream_fd(fd, os.fstat(fd).st_size, "CommandCenter.exe")

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
        Route("/api/development", guarded(development), methods=["GET"]),
        Route("/api/tasks", guarded(list_tasks), methods=["GET"]),
        Route("/api/tasks", guarded(create_task), methods=["POST"]),
        Route("/api/tasks/import-preview", guarded(import_preview), methods=["GET"]),
        Route("/api/tasks/{key}", guarded(get_task), methods=["GET"]),
        Route("/api/tasks/{key}", guarded(patch_task), methods=["PATCH"]),
        Route("/api/tasks/{key}/context", guarded(task_context), methods=["GET"]),
        Route("/api/tasks/{key}/comments", guarded(comment_task), methods=["POST"]),
        Route("/api/tasks/{key}/relations", guarded(relate_task), methods=["POST"]),
        Route("/api/tasks/{key}/links", guarded(link_task), methods=["POST"]),
        Route("/api/development/{key}/commits", ws_route(dev_commits), methods=["GET"]),
        Route("/api/workspace/projects", ws_route(ws_projects), methods=["GET"]),
        Route("/api/files/list", ws_route(files_list), methods=["GET"]),
        Route("/api/files/read", ws_route(files_read), methods=["GET"]),
        Route("/api/files/download", ws_route(files_download), methods=["GET"]),
        Route("/api/files/save", ws_route(files_save, dev=True), methods=["POST"]),
        Route("/api/files/upload", ws_route(files_upload, dev=True), methods=["POST"]),
        Route("/api/attachments", ws_route(attach_list), methods=["GET"]),
        Route("/api/attachments", ws_route(attach_add, dev=True), methods=["POST"]),
        Route("/api/attachments/{aid}/download", ws_route(attach_download), methods=["GET"]),
        Route("/api/attachments/{aid}", ws_route(attach_remove, dev=True), methods=["DELETE"]),
        Route("/api/developer", dev_status, methods=["GET"]),
        Route("/api/developer/unlock", dev_unlock, methods=["POST"]),
        Route("/api/developer/lock", dev_lock, methods=["POST"]),
        Route("/api/desktop/launcher", launcher_info, methods=["GET"]),
        Route("/api/desktop/launcher/download", launcher_download, methods=["GET"]),
    ]
    mounts = []
    ui = ui_dir() if ui is None else ui
    if ui and Path(ui, "index.html").is_file():
        mounts.append(Mount("/", app=UiFiles(ui, port), name="ui"))
    app = Starlette(routes=routes + mounts, lifespan=lifespan)
    app.state.routes_table = routes
    return Guard(app, token, port), app
