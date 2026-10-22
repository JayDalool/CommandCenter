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
