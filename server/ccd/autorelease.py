"""Automatic release, slice 1: the dry run (CC-081; docs/adr/0010-automatic-release.md, proposed).

At each weekly release window it RECORDS, for GYST and Command Center only, what an automatic release would ship (the
emailed manifest of CC-078), whether it would be eligible and why not, and after the window what was actually
deployed. That is all it does. It deploys, restarts, approves, rolls back and changes no gate or status, ever: the
release stays Jay's Go Live press (README "No dangerous endpoints", ADR 0006). The real release is slices 2-3, each
Jay's own decision (question 230).

Switch (c8): config.json `auto_release`, read once at start. Only the exact string "dry_run" turns it on; unset,
"off", "on", true and anything else read as off and write nothing. While the stop file
<CCD_STATE_DIR>/auto-release.stop exists, or cannot be checked, it writes nothing either.

Ledger: ccd.db kv `auto_release:<project>` = {rows: newest first, hold}. A row is one phase of one window: `decision`
(at the window) or `outcome` (after it). Rows and the `release.dry_run` ticket events hold ticket keys, short shas,
fixed reason phrases and timestamps only: never a commit subject, a ticket title or who deployed (GYST holds health
data). A failed-release hold has no clear in this slice: Jay's clear comes with slice 3.

All of a tick's work (files, git, both databases) runs in one worker thread on its own SQLite connections, with a
busy timeout, and the loop waits for it at most TICK_DEADLINE: a locked database or a stuck read never stalls ccd
(Codex review of CC-081, finding 8).
"""
import asyncio
import calendar
import datetime
import json
import logging
import os
import re
import sqlite3
import stat
import subprocess
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
# tickets that would release (c2). GYST has no release script yet; its range check comes with that GYST ticket.
RANGE_REF = {"commandcenter": "origin/main"}

OFF, DRY_RUN = "off", "dry_run"
STOP_FILE = Path(os.environ.get("CCD_AUTO_RELEASE_STOP", STATE_DIR / "auto-release.stop"))
# Where CC-063's release log and the slice-2 rehearsal log live: <dir>/<project>/{releases,rehearsals}.jsonl.
DEPLOYS_DIR = Path(os.environ.get("CCD_DEPLOYS_DIR", LEGACY / "deploys"))
WEB_CURRENT = Path(os.environ.get("CCD_WEB_DIR", SHARE_DIR / "web")) / "current"

KIND = "release.dry_run"        # deliberately not pipeline.*: nothing that counts pipeline steps may read it as one
LEDGER_MAX = 24                 # 12 windows x (decision, outcome)
GIT_TIMEOUT = 5                 # s; a git that hangs is a blocker, never a stuck loop
DB_TIMEOUT = 2.0                # s a worker statement waits for another writer before the tick gives up
TICK_DEADLINE = 30.0            # s the event loop waits for one tick's worker
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


def stopped(path):
    """The stop file is present, or its state cannot be told. Only "no such file" counts as absent: Path.exists
    swallows permission and I/O errors as False, which would fail open (Codex finding 2)."""
    try:
        os.stat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


# ----- reading files and git (worker thread; never raise) -----

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
    """The JSON object rows of a jsonl file (its last LOG_MAX bytes), in file order; a line that is not one is {}.
    Missing, or not a regular file, = []. Opened non-blocking and checked before reading, so a FIFO or device put
    there cannot hang the worker."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return []
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return []
        os.lseek(fd, max(0, st.st_size - LOG_MAX), os.SEEK_SET)
        chunks, left = [], LOG_MAX
        while left > 0:
            b = os.read(fd, min(65536, left))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
    except OSError:
        return []
    finally:
        os.close(fd)
    lines = b"".join(chunks).decode("utf-8", "replace").splitlines()
    if st.st_size > LOG_MAX:
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
    """(last healthy, last failed or inconclusive) from CC-063's releases.jsonl, as unix times or None. No healthy
    row (the file absent included) is "no health check recorded", a blocker, never healthy. A failed row with no
    readable time counts as failing now (fail closed)."""
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


def pinned_rev(root, ref, at, git=run_git):
    """Question 230: the commit `ref` pointed at when the digest was delivered (at `at`), from the checkout's reflog:
    the newest entry at or before then. Never the ref as it is now, so a merge after delivery cannot slip in (Codex
    finding 4). None (a blocker) when the reflog does not reach back that far or cannot be read."""
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return None
    code, out = git(root, ["reflog", "show", "--date=unix", "--format=%h%x1f%gd", f"refs/remotes/{ref}"])
    if code != 0:
        return None
    for line in out.splitlines():           # newest first
        sha, _, sel = line.partition("\x1f")
        m = re.search(r"@\{(\d+)\}$", sel)
        if m and int(m.group(1)) <= at:
            if not REV_RE.match(sha):
                return None
            code, out = git(root, ["rev-parse", "--short=7", "--verify", "-q", f"{sha}^{{commit}}"])
            rev = out.strip()
            return rev if code == 0 and REV_RE.match(rev) else None
    return None


def commit_range(root, live, target, git=run_git):
    """{mainline, all}: [(sha7, [ticket keys])] of the commits in live..target, main's own (first parent) and every
    commit a merge carries, or None when git fails. Subjects are read here to find keys and dropped: never stored."""
    if not (live and target and REV_RE.match(live) and REV_RE.match(target)):
        return None
    key_re = re.compile(rf"\b({registry.board_id_pattern()}-\d+)\b")
    out = {}
    for name, extra in (("mainline", ["--first-parent"]), ("all", [])):
        code, text = git(root, ["log", *extra, "--format=%h%x1f%s", f"{live}..{target}"])
        if code != 0:
            return None
        out[name] = [(sha[:7], sorted(set(key_re.findall(subject))))
                     for sha, _, subject in (line.partition("\x1f") for line in text.splitlines())]
    return out


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
    rehearsal, health (a healthy release recorded), held, invalid (manifest keys outside the project), range
    ({"error"} or {"mainline", "all"} for a range project, else None) and pulled keys."""
    blockers = []
    if project not in ALLOWED:
        blockers.append("not on the automatic release list")
    if manifest is None:
        blockers.append("no manifest emailed")
    elif not manifest:
        blockers.append("nothing scheduled")
    if p.get("invalid"):
        blockers.append("manifest names a ticket outside the project")
    caps = p.get("capabilities") or {}
    if caps.get("health_checks") is not True:
        blockers.append("health checks not configured")
    if caps.get("auto_rollback") is not True:
        blockers.append("rollback not configured")
    if p.get("rehearsal") is None:
        blockers.append("no rehearsal recorded")
    elif p["rehearsal"] != "pass":
        blockers.append("last rehearsal failed")
    if not p.get("health"):
        blockers.append("no health check recorded")
    if p.get("held"):
        blockers.append(HELD)
    rng = p.get("range")
    if rng is not None and rng.get("error"):
        blockers.append(rng["error"])
        rng = None
    pulled = set(p.get("pulled") or ())
    shipped = {k for _sha, keys in rng["all"] for k in keys} if rng else None
    reasons = {}
    for key in manifest or ():
        r = item_reasons(facts.get(key), key in pulled)
        if not r and shipped is not None and key not in shipped:
            r = ["not in the pinned range"]     # ready, but main as pinned does not carry it
        reasons[key] = r
    if rng:
        # Main ships whole: every ticket any shipped commit names must be one that would release, including what a
        # manifest ticket's merge carries in (Codex finding 5), and main's own commits must each name a ticket.
        ready = {k for k, r in reasons.items() if not r}
        for sha, keys in rng["mainline"]:
            if not keys:
                blockers.append(f"unlisted change {sha}/no key")
        for sha, keys in rng["all"]:
            blockers += [f"{'held' if k in reasons else 'unlisted'} change {sha}/{k}" for k in keys if k not in ready]
    blockers = list(dict.fromkeys(blockers))
    items = [{"key": k, "would": "hold" if r or blockers else "release", "reasons": r} for k, r in reasons.items()]
    return {"eligible": not blockers and any(i["would"] == "release" for i in items), "blockers": blockers,
            "items": items}


def _note(row, item):
    """The fixed text of one ticket's note for a ledger row, rebuilt the same way on every delivery attempt."""
    if row["phase"] == "decision":
        if item["would"] == "release":
            return f"would release in {row['local']}"
        return f"would hold: {'; '.join(item['reasons'] + row['blockers'])}"
    return "not released" if item["result"] == "none" else f"released: {item['result']}"


# ----- the dry run -----

def _connect(path):
    db = sqlite3.connect(str(path), timeout=DB_TIMEOUT, isolation_level=None, check_same_thread=False)
    db.execute(f"PRAGMA busy_timeout={int(DB_TIMEOUT * 1000)}")
    return db


class AutoRelease:
    """Owned by the daemon. `tick(known)` is awaited from its periodic loop and runs `run()` in a worker thread;
    `public()` serves GET /api/release from the kv ledger alone (no file or git IO)."""

    def __init__(self, store, pipeline, releases, policy, *, mode=OFF, stop_file=None, deploys_dir=None,
                 web_current=None, git=run_git, pulls=None):
        self.store, self.pipeline, self.releases, self.policy = store, pipeline, releases, policy
        self.mode = mode
        self.stop_file = Path(stop_file or STOP_FILE)
        self.deploys_dir = Path(deploys_dir or DEPLOYS_DIR)
        self.web_current = Path(web_current or WEB_CURRENT)
        self.git = git
        # CC-088 (sent corrections and pulls) has no source yet: until it lands nothing is pulled.
        self.pulls = pulls or (lambda project, window: set())
        self.stopped = None         # the stop file as the last tick saw it (GET reports it without a stat)
        self._busy = False

    def on(self):
        """Whether the dry run may write now: exactly dry_run and no stop file. Checked before every write."""
        self.stopped = stopped(self.stop_file)
        return self.mode == DRY_RUN and not self.stopped

    async def tick(self, known=ALLOWED, now=None):
        """One tick, off the event loop. A worker still running from an earlier tick (past the deadline) means this
        one is skipped, never a second worker."""
        if self.mode != DRY_RUN or self._busy:
            return
        self._busy = True
        fut = asyncio.ensure_future(asyncio.to_thread(self.run, list(known), now))
        fut.add_done_callback(self._done)
        try:
            await asyncio.wait_for(asyncio.shield(fut), TICK_DEADLINE)
        except TimeoutError:
            log.warning(json.dumps({"msg": "auto-release tick past its deadline; it finishes in the background"}))

    def _done(self, fut):
        self._busy = False
        if not fut.cancelled() and fut.exception() is not None:
            log.warning(json.dumps({"msg": "auto-release tick failed", "error": type(fut.exception()).__name__}))

    def run(self, known=ALLOWED, now=None):
        """The whole tick, blocking: meant for a worker thread. Its own connections, closed at the end."""
        if not self.on():
            return
        now = time.time() if now is None else now
        kv, tdb = _connect(self.store.path), _connect(self.pipeline.ts.path)
        try:
            for p in ALLOWED:
                if p not in known or registry.paused(p) or not self.releases.live(p):
                    continue            # a paused or not-live project gets no row
                try:
                    self._project(kv, tdb, p, now)
                except Exception as e:  # noqa: BLE001 — one project's failure must not stop the other, or ccd
                    log.warning(json.dumps({"msg": "auto-release dry run failed", "project": p,
                                            "error": type(e).__name__}))
        finally:
            kv.close()
            tdb.close()

    # ----- ledger -----

    @staticmethod
    def _kv(db, key, default=None):
        row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def ledger(self, project, db=None):
        led = self._kv(db or self.store.db, f"auto_release:{project}")
        led = led if isinstance(led, dict) else {}
        return {"rows": list(led.get("rows") or []), "hold": led.get("hold")}

    def _save(self, db, project, led):
        led["rows"] = led["rows"][:LEDGER_MAX]
        db.execute("INSERT INTO kv(key, value, at) VALUES (?,?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value, at=excluded.at",
                   (f"auto_release:{project}", json.dumps(led), time.time()))

    # ----- one project -----

    def _project(self, kv, tdb, p, now):
        led = self.ledger(p, kv)
        facts = self.pipeline.release_facts(p, [], now, db=tdb)
        good, bad = release_log(p, self.deploys_dir)
        self._hold(kv, p, led, good, bad, facts, now)
        self._decide(kv, tdb, p, led, good, now)
        self._outcomes(kv, tdb, p, led, now)
        self._deliver(kv, tdb, p, led)

    def _hold(self, kv, p, led, good, bad, facts, now):
        """c6: a failed or inconclusive release (CC-063's log, or a ticket's live deploy recorded fail) newer than the
        last pass holds the project. Sticky: deleting the log or appending a healthy line (both agent-writable)
        changes nothing. No clear in this slice: Jay's clear is slice 3 (Codex finding 1)."""
        if led["hold"]:
            return
        last_good = max([t for t in (good, facts["lastPass"]) if t is not None], default=None)
        last_bad = max([t for t in (bad, facts["lastFail"]) if t is not None], default=None)
        if last_bad is None or (last_good is not None and last_good >= last_bad) or not self.on():
            return
        led["hold"] = {"since": last_bad, "at": now}
        self._save(kv, p, led)

    def _manifest(self, kv, p, window):
        """(keys, invalid count, sentAt) of the delivered digest for this release, or (None, 0, None): no manifest
        emailed (no row, a failed send, or one that may not have gone out). Keys are this project's own shape only;
        anything else is counted, never stored (Codex finding 6)."""
        rows = self._kv(kv, f"release_mail:{p}", [])
        row = next((r for r in rows if isinstance(r, dict) and isinstance(r.get("window"), (int, float))
                    and same_release(r["window"], window)), None) if isinstance(rows, list) else None
        if not row or row.get("state") != "delivered" or row.get("uncertain"):
            return None, 0, None
        shape = re.compile(rf"^{re.escape(registry.prefix_of(p))}-[0-9]{{1,6}}$")
        listed = (row.get("listed") or {}).get("scheduled") or []
        keys = list(dict.fromkeys(k for k in listed if isinstance(k, str) and shape.match(k)))
        return keys, sum(1 for k in listed if not (isinstance(k, str) and shape.match(k))), row.get("sentAt")

    def _range(self, p, sent_at):
        if p not in RANGE_REF:
            return None, None, None
        live = live_rev(self.web_current)
        if live is None:
            return {"error": "cannot tell live"}, None, None
        target = pinned_rev(registry.root_of(p), RANGE_REF[p], sent_at, self.git)
        if target is None:
            return {"error": "no sha pinned at digest time"}, live[:7], None
        rng = commit_range(registry.root_of(p), live, target, self.git)
        return (rng or {"error": "cannot read range"}), live[:7], target

    def _decide(self, kv, tdb, p, led, good, now):
        start, _cut = release_mod.next_window(self.releases.window, now)
        newest = next((r for r in led["rows"] if r["phase"] == "decision"), None)
        if newest and same_release(newest["window"], start):
            return              # c7: once per release, across restarts and a window moved within the release
        if not (start <= now < start + WINDOW_S):
            return
        manifest, invalid, sent_at = self._manifest(kv, p, start)
        rng, live, target = self._range(p, sent_at)
        facts = self.pipeline.release_facts(p, manifest or [], now, db=tdb)
        prof = self.policy.profile(p) if self.policy is not None else None
        result = eligibility(p, manifest, facts["items"], {
            "capabilities": (prof or {}).get("capabilities") or {}, "rehearsal": rehearsal(p, self.deploys_dir),
            "health": good is not None, "held": bool(led["hold"]), "invalid": invalid, "range": rng,
            "pulled": self.pulls(p, start)})
        if not self.on():
            return
        led["rows"].insert(0, dict(result, phase="decision", window=start, at=now, manifest=manifest is not None,
                                   live=live, target=target, local=self._local(start), delivered=False))
        self._save(kv, p, led)

    def _outcomes(self, kv, tdb, p, led, now):
        """c5: after the window, what actually happened to each item, from its deploy record: the fixed result and
        its time, never who deployed (Codex finding 7)."""
        for dec in [r for r in led["rows"] if r["phase"] == "decision"]:
            w = dec["window"]
            if now < w + WINDOW_S or any(r["phase"] == "outcome" and same_release(r["window"], w)
                                         for r in led["rows"]):
                continue
            facts = self.pipeline.release_facts(p, [i["key"] for i in dec["items"]], now, db=tdb)["items"]
            items = []
            for it in dec["items"]:
                f = facts.get(it["key"]) or {}
                done = f.get("env") == "live" and f.get("result") in ("pass", "fail") and (f.get("deployedAt") or 0) >= w
                items.append({"key": it["key"], "result": f["result"] if done else "none",
                              "at": f["deployedAt"] if done else None})
            if not self.on():
                return
            led["rows"].insert(0, {"phase": "outcome", "window": w, "at": now, "items": items, "delivered": False})
            self._save(kv, p, led)

    def _deliver(self, kv, tdb, p, led):
        """The ticket notes of every row not yet marked delivered. The row is committed first and each note is
        written at most once (Pipeline.release_dry_run checks), so a crash or a failed insert anywhere is finished
        by a later tick, never duplicated (Codex finding 9)."""
        for row in led["rows"]:
            if row.get("delivered") or row["phase"] not in ("decision", "outcome"):
                continue
            for it in row["items"]:
                if not self.on():
                    return
                self.pipeline.release_dry_run(tdb, p, it["key"], _note(row, it),
                                              {"window": row["window"], "phase": row["phase"],
                                               **({"would": it["would"]} if row["phase"] == "decision"
                                                  else {"result": it["result"]})})
            row["delivered"] = True
            self._save(kv, p, led)

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
