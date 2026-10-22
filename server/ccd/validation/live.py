"""Live mode: GET requests to a running ccd, nothing else (the guard blocks every other method and host).

Reads the read-only routes the gate needs and returns them as they are; scoring happens in `gate`."""
import json
import time
import urllib.error
import urllib.request

ROUTES = {
    "health": "/api/health",
    "autonomy": "/api/autonomy",
    "profiles": "/api/profiles",
    "audit": "/api/audit?full=1&limit=1",
    "workers": "/api/workers",
    "nightShift": "/api/night-shift",
    "decisions": "/api/decisions?limit=1",
    "usage": "/api/usage?days=7",
    "activity": "/api/activity?limit=5&kind=merge.policy",
    "pipeline": "/api/activity?limit=200&kind=task.pipeline",
}


def fetch(base, token, timeout=20):
    """{route: {ok, status, ms, body | error}}."""
    out = {}
    host = base.split("://", 1)[-1].split("/", 1)[0]
    for name, path in ROUTES.items():
        req = urllib.request.Request(base.rstrip("/") + path, method="GET",
                                     headers={"X-CCD-Token": token or "", "Host": host, "Accept": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 — a GET to the given ccd only
                body = json.loads(r.read().decode("utf-8"))
                out[name] = {"ok": True, "status": r.status, "ms": round((time.monotonic() - t0) * 1000), "body": body}
        except urllib.error.HTTPError as e:
            out[name] = {"ok": False, "status": e.code, "ms": round((time.monotonic() - t0) * 1000),
                         "error": f"HTTP {e.code}"}
        except Exception as e:  # noqa: BLE001 — a route that cannot be read is "missing" evidence, never a pass
            out[name] = {"ok": False, "status": None, "ms": round((time.monotonic() - t0) * 1000),
                         "error": f"{type(e).__name__}: {str(e)[:120]}"}
    return out


def body(live, name):
    r = (live or {}).get(name) or {}
    return r.get("body") if r.get("ok") else None


def merge_policy_status(live):
    """'enabled' | 'disabled' | None: the newest merge.policy event ccd logged at start-up."""
    act = body(live, "activity") or {}
    events = act.get("events") if isinstance(act, dict) else act
    for e in events or []:
        if isinstance(e, dict) and e.get("kind") == "merge.policy":
            data = e.get("data")
            data = json.loads(data) if isinstance(data, str) else data
            return (data or {}).get("status")
    return None


# task.pipeline activity the daemon logs with no ticket event behind it (worktree cleanup, nudges, auto-merge reads)
NO_TICKET_EVENT = {"pipeline.worktree_removed", "pipeline.worktree_kept", "pipeline.answers_delivered",
                   "pipeline.session_left", "pipeline.auto_merge_unreadable"}


def newest_pipeline_step(live):
    """The newest pipeline step ccd logged that is also a ticket event: {"at", "key", "kind"}; {} when ccd logged
    none; None when it cannot be told (route unreadable, an unusable entry, or only non-ticket activity in the page).
    A replay copy that does not hold this step misses steps rows 7 and 8 must see."""
    act = body(live, "pipeline")
    events = act.get("events") if isinstance(act, dict) else None
    if not isinstance(events, list):
        return None
    if not events:
        return {}
    steps = []
    for e in events:
        if not isinstance(e, dict) or e.get("kind") != "task.pipeline":
            continue
        data = e.get("data")
        data = json.loads(data) if isinstance(data, str) else data
        kind = (data or {}).get("kind") if isinstance(data, dict) else None
        at = e.get("at")
        if not isinstance(kind, str) or not isinstance(at, (int, float)) or isinstance(at, bool):
            return None
        if kind in NO_TICKET_EVENT:
            continue
        if not isinstance(e.get("ref"), str) or not e["ref"]:
            return None
        steps.append({"at": float(at), "key": e["ref"], "kind": kind})
    return max(steps, key=lambda x: x["at"]) if steps else None
