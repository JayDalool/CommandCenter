"""Fleet report (CC-079): per-app account totals, read from each app's own read-only counts endpoint.

Only counts cross the wire. This module imports no subprocess, sqlite3 or database driver on purpose (a test
asserts it): it can ask an app a question over loopback HTTP and nothing else. The contract each app implements is
docs/fleet-contract.md; each app's endpoint is its own repository's change.
"""
import json
import os
import stat
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import registry

TIMEOUT_S = 3
MAX_BODY = 4096          # a counts reply is ~60 bytes; anything bigger is not the contract
CACHE_S = 60
ACTIVE_DAYS = 30
UNIT = "accounts (not people)"
# One written definition, shown beside every active number (c2). The app's reply must name the same window.
DEFINITION = (f"Active = an account that signed in or made an authenticated request in the last {ACTIVE_DAYS} days. "
              "Counts are accounts, not people: one person with two logins counts twice.")
KEYS = {"accounts", "active", "active_window_days"}

_lock = threading.Lock()
_cache = {"at": 0.0, "report": None}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect could send the bearer token to another host.
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _token(entry):
    path = Path(os.path.expanduser(entry.get("token_file") or ""))
    try:
        st = path.stat()
    except OSError:
        return None, "token file missing"
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return None, "token file must be 0600"
    try:
        return path.read_text().strip(), None
    except OSError:
        return None, "token file unreadable"


def _count(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10**9


def _fetch(entry):
    """One app's counts, or (None, reason). Reasons are fixed strings: a reply body is never echoed."""
    url = entry.get("url") or ""
    if not url.startswith("http://127.0.0.1:"):
        return None, "not a loopback url"
    token, why = _token(entry)
    if token is None:
        return None, why
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with _opener.open(req, timeout=TIMEOUT_S) as r:
            raw = r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        return None, f"refused (HTTP {e.code})"
    except (urllib.error.URLError, OSError, ValueError):
        return None, "no answer"
    if len(raw) > MAX_BODY:
        return None, "reply too large"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "reply not JSON"
    if not isinstance(data, dict) or set(data) != KEYS or not _count(data["accounts"]) \
            or not _count(data["active"]) or data["active"] > data["accounts"]:
        return None, "reply does not match the contract"
    if data["active_window_days"] != ACTIVE_DAYS:
        return None, "reply uses a different active definition"
    return {"accounts": data["accounts"], "active": data["active"]}, None


def build(apps=None, status_of=None, fetch=_fetch):
    """The report, uncached. `status_of(container)` is injected so this module never shells out."""
    apps = registry.fleet_apps() if apps is None else apps
    counted = {k: v for k, v in apps.items() if not v.get("single_user")}
    with ThreadPoolExecutor(max_workers=max(1, len(counted))) as pool:
        results = dict(zip(counted, pool.map(lambda k: fetch(counted[k]), counted)))
    rows, answered, silent = [], [], []
    acc = act = 0
    for k, (counts, why) in results.items():
        row = {"project": k, "name": registry.name_of(k), "unit": UNIT, "definition": DEFINITION}
        if counts:
            row.update(answered=True, **counts)
            answered.append(k)
            acc += counts["accounts"]
            act += counts["active"]
        else:
            row.update(answered=False, reason=why)
            silent.append(k)
        rows.append(row)
    single = []
    for k, v in apps.items():
        if v.get("single_user"):
            status = status_of(v["container"]) if status_of and v.get("container") else None
            health = "unknown" if not status else "healthy" if "(healthy)" in status else \
                "unhealthy" if "(unhealthy)" in status else "running"
            single.append({"project": k, "name": registry.name_of(k), "status": "single-user", "health": health})
    return {"at": time.time(), "unit": UNIT, "definition": DEFINITION, "apps": rows,
            "answered": answered, "didNotRespond": silent,
            # GYST is one user by design: listed on its own, never added into the account total.
            "singleUser": single,
            "total": {"label": UNIT, "accounts": acc, "active": act, "from": answered}}


def report(status_of=None, now=None):
    """The report, cached 60s so repeated questions do not hammer the apps."""
    with _lock:
        t = time.time() if now is None else now
        if _cache["report"] is None or t - _cache["at"] >= CACHE_S:
            _cache.update(at=t, report=build(status_of=status_of))
        return _cache["report"]
