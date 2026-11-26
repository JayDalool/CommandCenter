"""Automatic release, slice 1: the dry run (CC-081; docs/adr/0010-automatic-release.md, proposed).

At each weekly release window it RECORDS, for GYST and Command Center only, what an automatic release would ship (the
emailed manifest of CC-078), whether it would be eligible and why not, and after the window what was actually
deployed. That is all it does. It deploys, restarts, approves, rolls back and changes no gate or status, ever: the
release stays Jay's Go Live press (README "No dangerous endpoints", ADR 0006). The real release is slices 2-3, each
Jay's own decision (question 230).

Switch (c8): config.json `auto_release`, read once at start. Only the exact string "dry_run" turns it on; unset,
"off", "on", true and anything else read as off and write nothing. While the stop file
<CCD_STATE_DIR>/auto-release.stop exists, or cannot be checked, it writes nothing either.

Ledger: ccd.db kv `auto_release:<project>` = {rows: newest first, hold, clearedAt}. A row is one phase of one window:
`pin` (the main sha when the digest went out), `decision` (at the window) and `outcome` (after it). Rows and the
`release.dry_run` ticket events hold ticket keys, short shas, fixed reason phrases and timestamps only: never a commit
subject or a ticket title (GYST holds health data).
"""
import asyncio
import calendar
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import time
import zoneinfo
from pathlib import Path

from . import registry
from . import release as release_mod
from .config import LEGACY, SHARE_DIR, STATE_DIR

log = logging.getLogger("ccd")

# c1: the only projects the dry run looks at. SamVision and MFE keep their client-impact and migration checks
# (policy/projects/*.toml release_window), so they never get a row, whatever the facts.
ALLOWED = ("gyst", "commandcenter")
# Command Center ships all of main, not single tickets (the Go Live script), so its commit range must carry only
# manifest tickets (c2). GYST has no release script yet; its range check comes with that GYST ticket.
RANGE_REF = {"commandcenter": "origin/main"}

OFF, DRY_RUN = "off", "dry_run"
STOP_FILE = Path(os.environ.get("CCD_AUTO_RELEASE_STOP", STATE_DIR / "auto-release.stop"))
# Where CC-063's release log and the slice-2 rehearsal log live: <dir>/<project>/{releases,rehearsals}.jsonl.
DEPLOYS_DIR = Path(os.environ.get("CCD_DEPLOYS_DIR", LEGACY / "deploys"))
WEB_CURRENT = Path(os.environ.get("CCD_WEB_DIR", SHARE_DIR / "web")) / "current"

KIND = "release.dry_run"        # deliberately not pipeline.*: nothing that counts pipeline steps may read it as one
ACTOR = "system:auto-release"
LEDGER_MAX = 36                 # 12 windows x (pin, decision, outcome)
GIT_TIMEOUT = 5                 # s; a git that hangs is a blocker, never a stuck loop
LOG_MAX = 256 * 1024            # bytes read from the end of a jsonl log
REV_RE = re.compile(r"^[0-9a-f]{7,40}$")
WINDOW_S = release_mod.WINDOW_HOURS * 3600

HELD = "last release failed: held until Jay clears it"


def mode_of(cfg):
    """`dry_run` only for exactly that string (security review condition 1); everything else is off and logged."""
    v = (cfg or {}).get("auto_release", OFF)
    if type(v) is str and v == DRY_RUN:
        return DRY_RUN
    if not (type(v) is str and v == OFF):
        log.warning(json.dumps({"msg": "config auto_release is not \"off\" or \"dry_run\"; read as off",
                                "type": type(v).__name__}))
    return OFF


def same_release(a, b):
    """Two window starts belong to one release when they are less than a window apart: a window Jay moves within
    the release is the same release (the CC-078 digest dedup uses the same rule), one moved to another day is not."""
    return abs(a - b) < WINDOW_S


# ----- reading files and git (run in a thread; never raise) -----

def run_git(root, args):
    """(returncode, stdout) of one git command: list argv, no shell, never a fetch (ccd reads what the checkout
    already has). Any failure or the timeout is returncode 1."""
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, p.stdout


def live_rev(current=None):
    """The live Command Center build's commit from web/current -> releases/<stamp>-<rev>, read as the Go Live script
    reads it; None when it cannot be told. `-dirty`, a non-hex rev or one starting with '-' never reaches git argv."""
    try:
        name = os.path.basename(os.readlink(current or WEB_CURRENT))
    except OSError:
        return None
    parts = name.split("-")
    return parts[1] if len(parts) == 2 and REV_RE.match(parts[1]) else None


def _tail_rows(path):
    """The JSON object rows of a jsonl file (the last LOG_MAX bytes), in file order. A line that is not one is
    {} (an unreadable row is not proof of anything). Missing file = []."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - LOG_MAX))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = raw.splitlines()
    if size > LOG_MAX:
        lines = lines[1:]           # the first line was cut
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            row = {}
        out.append(row if isinstance(row, dict) else {})
    return out


def _when(row):
    """A row's time as unix seconds: a number, or CC-063's "YYYY-MM-DDTHH:MM:SSZ"; None when it has neither."""
    at = row.get("at")
    if isinstance(at, (int, float)) and not isinstance(at, bool):
        return float(at)
    try:
        return float(calendar.timegm(time.strptime(str(at), "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


def release_log(project, base=None):
    """(last healthy, last failed or inconclusive) from CC-063's releases.jsonl, as unix times or None. Absent
    means "no health check recorded", never healthy. A failed row with no readable time counts as failing now
    (fail closed: it holds until the line is fixed and Jay clears it)."""
    good = bad = None
    for row in _tail_rows(Path(base or DEPLOYS_DIR) / project / "releases.jsonl"):
        at = _when(row)
        if row.get("result") == "healthy" and at is not None:
            good = at if good is None else max(good, at)
        elif row.get("result") != "healthy":
            at = time.time() if at is None else at
            bad = at if bad is None else max(bad, at)
    return good, bad


def rehearsal(project, base=None):
    """The newest rehearsal row's result ("pass", anything else), or None when none is recorded (c3: absent is a
    blocker, never assumed)."""
    rows = _tail_rows(Path(base or DEPLOYS_DIR) / project / "rehearsals.jsonl")
    if not rows:
        return None
    return "pass" if rows[-1].get("result") == "pass" else "fail"


def head_rev(root, ref, git=run_git):
    code, out = git(root, ["rev-parse", "--short=7", "--verify", "-q", f"{ref}^{{commit}}"])
    rev = out.strip()
    return rev if code == 0 and REV_RE.match(rev) else None


def commit_range(root, live, target, git=run_git):
    """[(sha7, [ticket keys])] of main's own commits in live..target (first parent, so a merge counts once with its
    branch name), or None when git fails. Subjects are read here to find keys and dropped: never stored."""
    if not (live and target and REV_RE.match(live) and REV_RE.match(target)):
        return None
    code, out = git(root, ["log", "--first-parent", "--format=%h%x1f%s", f"{live}..{target}"])
    if code != 0:
        return None
    key_re = re.compile(rf"\b({registry.board_id_pattern()}-\d+)\b")
    out_rows = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\x1f")
        out_rows.append((sha[:7], sorted(set(key_re.findall(subject)))))
    return out_rows


# ----- deciding (pure) -----

def item_reasons(f, pulled):
    """Why one manifest ticket would not release in the window that is open now ([] = it would). Release facts
    only: no merge readiness (c4)."""
    if pulled:
        return ["pulled from the release"]
    if f is None:
        return ["ticket not found"]
    if f["status"] != "VERIFYING":
        return ["not merged and verifying"]
    if f["env"] != "live" or not f["requested"]:
        return ["no live deploy requested"]
    if f["result"]:
        return ["already deployed"]
    out = []
    if f["urgent"]:
        out.append("urgent deploy has no window")
    if not f["verified"]:
        out.append("verification has not passed")
    if f["heldUntil"]:
        out.append("waits for a later window")
    return out


def eligibility(project, manifest, facts, p):
    """{eligible, blockers, items: [{key, would, reasons}]} for one window. `manifest` is the digest's scheduled keys
    (None: no manifest emailed); `facts` Pipeline.release_facts items; `p` the project facts: capabilities,
    rehearsal, held, range ({"error"} or {"commits"} for a range project, else None) and pulled keys."""
    blockers = []
    if project not in ALLOWED:
        blockers.append("not on the automatic release list")
    if manifest is None:
        blockers.append("no manifest emailed")
    elif not manifest:
        blockers.append("nothing scheduled")
    caps = p.get("capabilities") or {}
    if caps.get("health_checks") is not True:
        blockers.append("health checks not configured")
    if caps.get("auto_rollback") is not True:
        blockers.append("rollback not configured")
    if p.get("rehearsal") is None:
        blockers.append("no rehearsal recorded")
    elif p["rehearsal"] != "pass":
        blockers.append("last rehearsal failed")
    if p.get("held"):
        blockers.append(HELD)
    rng = p.get("range")
    if rng is not None:
        if rng.get("error"):
            blockers.append(rng["error"])
        else:
            # A pulled ticket whose merge is still in the range would ship anyway: it counts as unlisted.
            listed = set(manifest or ()) - set(p.get("pulled") or ())
            for sha, keys in rng["commits"]:
                if not keys:
                    blockers.append(f"unlisted change {sha}/no key")
                blockers += [f"unlisted change {sha}/{k}" for k in keys if k not in listed]
    items = []
    for key in manifest or ():
        reasons = item_reasons(facts.get(key), key in (p.get("pulled") or ()))
        items.append({"key": key, "would": "hold" if reasons or blockers else "release", "reasons": reasons})
    return {"eligible": not blockers and any(i["would"] == "release" for i in items), "blockers": blockers,
            "items": items}


# ----- the dry run -----

class AutoRelease:
    """Owned by the daemon. `tick(now)` is called from its periodic loop; `public()` serves GET /api/release from the
    ledger alone (no file or git IO)."""

    def __init__(self, store, pipeline, releases, policy, *, mode=OFF, projects=None, stop_file=None,
                 deploys_dir=None, web_current=None, git=run_git, pulls=None):
        self.store, self.pipeline, self.releases, self.policy = store, pipeline, releases, policy
        self.mode = mode
        self.projects = projects or (lambda: list(ALLOWED))
        self.stop_file = Path(stop_file or STOP_FILE)
        self.deploys_dir = Path(deploys_dir or DEPLOYS_DIR)
        self.web_current = Path(web_current or WEB_CURRENT)
        self.git = git
        # CC-088 (sent corrections and pulls) has no source yet: until it lands nothing is pulled.
        self.pulls = pulls or (lambda project, window: set())
        self.stopped = self.is_stopped()

    def is_stopped(self):
        """The stop file exists. Anything but "does not exist" counts as stopped (fail closed)."""
        try:
            return self.stop_file.exists()
        except OSError:
            return True

    def on(self):
        """Whether the dry run may write now: exactly dry_run and no stop file. Checked before every write."""
        self.stopped = self.is_stopped()
        return self.mode == DRY_RUN and not self.stopped

    # ----- ledger -----

    def ledger(self, project):
        led = self.store.get(f"auto_release:{project}", None)[0]
        if not isinstance(led, dict):
            led = {}
        return {"rows": list(led.get("rows") or []), "hold": led.get("hold"), "clearedAt": led.get("clearedAt")}

    def _save(self, project, led):
        led["rows"] = led["rows"][:LEDGER_MAX]
        self.store.put(f"auto_release:{project}", led)

    @staticmethod
    def _find(led, phase, window):
        return next((r for r in led["rows"] if r["phase"] == phase and same_release(r["window"], window)), None)

    # ----- one tick -----

    async def tick(self, now=None):
        if not self.on():
            return
        now = time.time() if now is None else now
        known = set(self.projects())
        for p in ALLOWED:
            if p not in known or registry.paused(p) or not self.releases.live(p):
                continue            # a paused or not-live project gets no row
            try:
                await self._project(p, now)
            except Exception as e:  # noqa: BLE001 — one project's failure must not stop the other, or ccd
                log.warning(json.dumps({"msg": "auto-release dry run failed", "project": p,
                                        "error": type(e).__name__}))

    async def _project(self, p, now):
        led = self.ledger(p)
        facts = self.pipeline.release_facts(p, [], now)
        good, bad = await asyncio.to_thread(release_log, p, self.deploys_dir)
        self._hold(p, led, good, bad, facts, now)
        await self._pin(p, led, now)
        await self._decide(p, led, now)
        self._outcomes(p, led, now)

    def _hold(self, p, led, good, bad, facts, now):
        """c6: a failed or inconclusive release (CC-063's log, or a ticket's live deploy recorded fail) newer than the
        last pass and than Jay's last clear holds the project. Sticky: once held, only Jay's clear-hold lifts it, so
        deleting the log or appending a healthy line (both agent-writable) changes nothing."""
        if led["hold"]:
            return
        last_good = max([t for t in (good, facts["lastPass"]) if t is not None], default=None)
        last_bad = max([t for t in (bad, facts["lastFail"]) if t is not None], default=None)
        if last_bad is None or (last_good is not None and last_good >= last_bad):
            return
        if led["clearedAt"] is not None and last_bad <= led["clearedAt"]:
            return
        if not self.on():
            return
        led["hold"] = {"since": last_bad, "at": now}
        self._save(p, led)

    async def _pin(self, p, led, now):
        """Question 230: release the main sha recorded when the digest went out, so a merge after the digest never
        joins the release. Pinned once per release, only before the window opens."""
        ref = RANGE_REF.get(p)
        digest = (self.store.get(f"release_mail:{p}", [])[0] or [None])[0]
        if not ref or not isinstance(digest, dict) or digest.get("state") != "delivered" or digest.get("uncertain"):
            return
        w = digest.get("window")
        if not isinstance(w, (int, float)) or now >= w or self._find(led, "pin", w):
            return
        target = await asyncio.to_thread(head_rev, registry.root_of(p), ref, self.git)
        if target is None or not self.on():
            return              # nothing pinned: tried again next tick; at the window, no pin is a blocker
        led["rows"].insert(0, {"phase": "pin", "window": w, "at": now, "target": target})
        self._save(p, led)

    def _manifest(self, p, window):
        """The digest's scheduled keys for this release, or None ("no manifest emailed": no row, a failed send, or
        one that may not have gone out)."""
        rows = self.store.get(f"release_mail:{p}", [])[0] or []
        row = next((r for r in rows if isinstance(r, dict) and isinstance(r.get("window"), (int, float))
                    and same_release(r["window"], window)), None)
        if not row or row.get("state") != "delivered" or row.get("uncertain"):
            return None
        return [k for k in (row.get("listed") or {}).get("scheduled") or [] if isinstance(k, str)]

    def _range(self, p, led, window):
        if p not in RANGE_REF:
            return None, None, None
        pin = self._find(led, "pin", window)
        live = live_rev(self.web_current)
        if live is None:
            return {"error": "cannot tell live"}, None, None
        if not pin:
            return {"error": "no sha pinned at digest time"}, live[:7], None
        commits = commit_range(registry.root_of(p), live, pin["target"], self.git)
        if commits is None:
            return {"error": "cannot read range"}, live[:7], pin["target"]
        return {"commits": commits}, live[:7], pin["target"]

    async def _decide(self, p, led, now):
        start, _cut = release_mod.next_window(self.releases.window, now)
        newest = next((r for r in led["rows"] if r["phase"] == "decision"), None)
        if newest and same_release(newest["window"], start):
            return              # c7: once per release, across restarts and a window moved within the release
        if not (start <= now < start + WINDOW_S):
            return
        manifest = self._manifest(p, start)
        pulled = self.pulls(p, start)
        reh = await asyncio.to_thread(rehearsal, p, self.deploys_dir)
        rng, live, target = await asyncio.to_thread(self._range, p, led, start)
        facts = self.pipeline.release_facts(p, manifest or [], now)
        prof = self.policy.profile(p) if self.policy is not None else None
        result = eligibility(p, manifest, facts["items"], {
            "capabilities": (prof or {}).get("capabilities") or {}, "rehearsal": reh, "held": bool(led["hold"]),
            "range": rng, "pulled": pulled})
        if not self.on():
            return
        led["rows"].insert(0, dict(result, phase="decision", window=start, at=now, manifest=manifest is not None,
                                   live=live, target=target))
        # The row first: a crash between it and the events can lose an event, never write one twice.
        self._save(p, led)
        when = self._local(start)
        for it in result["items"]:
            text = (f"would release in {when}" if it["would"] == "release"
                    else f"would hold: {'; '.join(it['reasons'] + result['blockers'])}")
            self._event(it["key"], text, {"window": start, "phase": "decision", "would": it["would"]})

    def _outcomes(self, p, led, now):
        """c5: after the window, what actually happened to each item, from its deploy record."""
        for dec in [r for r in led["rows"] if r["phase"] == "decision"]:
            w = dec["window"]
            if now < w + WINDOW_S or self._find(led, "outcome", w):
                continue
            facts = self.pipeline.release_facts(p, [i["key"] for i in dec["items"]], now)["items"]
            items = []
            for it in dec["items"]:
                f = facts.get(it["key"]) or {}
                done = f.get("env") == "live" and f.get("result") in ("pass", "fail") and (f.get("deployedAt") or 0) >= w
                items.append({"key": it["key"], "result": f["result"] if done else "none",
                              "by": f.get("deployedBy") if done else None, "at": f.get("deployedAt") if done else None})
            if not self.on():
                return
            led["rows"].insert(0, {"phase": "outcome", "window": w, "at": now, "items": items})
            self._save(p, led)
            for it in items:
                text = f"released by {it['by']}: {it['result']}" if it["result"] != "none" else "not released"
                self._event(it["key"], text, {"window": w, "phase": "outcome", "result": it["result"]})

    def _event(self, key, text, data):
        try:
            self.pipeline.release_dry_run(key, text, data)
        except Exception as e:  # noqa: BLE001 — a ticket that disappeared loses its note, nothing else
            log.warning(json.dumps({"msg": "auto-release event not written", "ticket": key, "error": type(e).__name__}))

    def _local(self, ts):
        tz = zoneinfo.ZoneInfo(self.releases.window.get("tz") or release_mod.DEFAULT_WINDOW["tz"])
        return datetime.datetime.fromtimestamp(ts, tz).strftime("%a %Y-%m-%d %H:%M %Z")

    # ----- reading -----

    def public(self, projects):
        """GET /api/release autoRelease: the newest decision as `wouldRelease` (a dry-run record, never a go), the
        newest outcome and the hold, from the kv ledger only."""
        out = {"mode": self.mode, "stopped": self.stopped, "projects": {}}
        for p in ALLOWED:
            if p not in projects:
                continue
            led = self.ledger(p)
            dec = next((r for r in led["rows"] if r["phase"] == "decision"), None)
            outc = next((r for r in led["rows"] if r["phase"] == "outcome"), None)
            out["projects"][p] = {
                "wouldRelease": {k: dec.get(k) for k in ("window", "at", "eligible", "blockers", "items", "live",
                                                          "target")} if dec else None,
                "outcome": {k: outc.get(k) for k in ("window", "at", "items")} if outc else None,
                "held": led["hold"]}
        return out


def clear_hold(store, project, now=None):
    """Jay's clear of a c6 hold (docs/runbooks/auto-release.md): failures up to now no longer hold the project."""
    if project not in ALLOWED:
        raise ValueError(f"{project} is not on the automatic release list")
    key = f"auto_release:{project}"
    led = store.get(key, None)[0]
    led = led if isinstance(led, dict) else {"rows": []}
    led.update(hold=None, clearedAt=time.time() if now is None else now)
    store.put(key, led)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "clear-hold":
        print("usage: python -m ccd.autorelease clear-hold <gyst|commandcenter>", file=sys.stderr)
        return 2
    from .store import Store
    store = Store(STATE_DIR / "ccd.db")
    try:
        clear_hold(store, argv[1])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        store.close()
    print(f"{argv[1]}: auto-release hold cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
