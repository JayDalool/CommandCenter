"""phase1-readiness: gather the evidence, classify every decision, score the 15 gate rows, write the report.

Exit codes: 0 PASS, 1 FAIL (some row fails or has no evidence), 2 cannot run (bad input, or the write guard's
self-check did not block everything).

The report is deterministic for the same inputs and `--now`: rows, decisions and counts are sorted, and the only
clock reading is `now`.
"""
import json
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import autonomy, profiles, tasks
from . import classify, fixtures, guard, live as live_mod, oracle, replay

PHASE1_GO_LIVE = "2026-10-21T23:46:00Z"     # the Phase 1 go-live restart (commit 4fa7b8b)
OLD_COMMIT = "a0e90e5"                      # the commit before Phase 1: must refuse a v9 tasks.db
MIN_HOURS, MIN_ENGINE_HOURS, MAX_REMINDERS = 72, 24, 6
REGRESSIONS = tuple(f"U-0{i}" for i in range(1, 9)) + tuple(f"L-0{i}" for i in range(1, 6)) + ("Q-01",)
GATE_TITLES = {
    1: "Live runtime", 2: "Night shift", 3: "Restart and durability", 4: "Restore and rollback", 5: "Profile drift",
    6: "Audit chain", 7: "Unauthorized actions", 8: "Data regressions", 9: "Unsafe-permissive",
    10: "Boundary-softened", 11: "Unknown disagreements", 12: "Coverage", 13: "Engine bugs", 14: "Legacy unchanged",
    15: "Harness",
}


class CannotRun(Exception):
    pass


def _ts(text):
    if text in (None, ""):
        return None
    if isinstance(text, (int, float)):
        return float(text)
    return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()


def _iso(t):
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(n, status, evidence):
    return {"row": n, "gate": GATE_TITLES[n], "status": status, "evidence": evidence}


def _decide(rows):
    for r in rows:
        r["classified"] = classify.classify(r["verdict"], r["oracle"], expected=r.get("expected"),
                                            observed=r.get("observed"))
    return rows


def _evaluate(decisions, policy):
    for d in decisions:
        prof = fixtures.profile_for(policy, d["project"]) if d.get("profile", "unset") == "unset" else d["profile"]
        d.setdefault("verdict", autonomy.evaluate(d["action"], prof, d["facts"]))
        d["oracle"] = oracle.requirement(d["action"], prof, d["facts"])
        d.pop("profile", None)
    return _decide(decisions)


def restore_drill(backup, scratch):
    """Copy the backup into `scratch`, migrate the copy to this ccd's schema, check it. The original is only read."""
    src = Path(backup)
    if not src.is_file():
        return {"pass": False, "error": f"{backup} is not a file"}
    copy = Path(scratch) / "restore-drill.db"
    with open(src, "rb") as a, open(copy, "wb") as b:
        shutil.copyfileobj(a, b)
    db = sqlite3.connect(str(copy))
    try:
        before = db.execute("PRAGMA user_version").fetchone()[0]
        applied = tasks.migrate(db)
        after = db.execute("PRAGMA user_version").fetchone()[0]
        ok = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        n = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        newer = _refuses_newer(db)
    finally:
        db.close()
    passed = ok and after == tasks.SCHEMA_VERSION and n >= replay.GO_LIVE_TICKETS and newer
    return {"pass": passed, "from": before, "to": after, "applied": applied, "integrity": ok, "tickets": n,
            "refusesNewerSchema": newer}


def _refuses_newer(db):
    """This ccd refuses a tasks.db newer than itself (the property the rollback to a0e90e5 relies on)."""
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute(f"PRAGMA user_version = {tasks.SCHEMA_VERSION + 1}")
        tasks.migrate(probe)
        return False
    except RuntimeError:
        return True
    finally:
        probe.close()


def run(opts):
    """opts: dict with fixtures, replay, github_cache, live, token, evidence, restore_backup, now, out, engine_live_at,
    go_live_at. Returns the report (the caller writes it)."""
    now = _ts(opts.get("now")) if opts.get("now") else time.time()
    out_dir = Path(opts["out"])
    scratch = Path(tempfile.mkdtemp(prefix="ccd-readiness-"))
    try:
        with guard.installed(write_dirs=[out_dir, scratch], live_url=opts.get("live")):
            checks = guard.self_check()
            if not all(c["blocked"] for c in checks):
                raise CannotRun("the write guard did not block: " +
                                ", ".join(c["probe"] for c in checks if not c["blocked"]))
            return _gather(opts, now, checks, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _gather(opts, now, checks, scratch):
    started = time.monotonic()
    evidence = {}
    if opts.get("evidence"):
        try:
            with open(opts["evidence"], encoding="utf-8") as fh:
                evidence = json.load(fh)
        except (OSError, ValueError) as e:
            raise CannotRun(f"cannot read the evidence file: {e}") from e
        if not isinstance(evidence, dict):
            raise CannotRun("the evidence file must be a JSON object")
    policy = profiles.load()
    report = {"tool": "phase1-readiness", "engine": autonomy.ENGINE_VERSION, "now": _iso(now),
              "policyFingerprint": policy.fingerprint, "guard": checks,
              "sources": {"fixtures": bool(opts.get("fixtures")), "replay": bool(opts.get("replay")),
                          "live": bool(opts.get("live"))}}
    decisions = []
    if opts.get("fixtures"):
        decisions += fixtures.run(policy)
    snap = None
    if opts.get("replay"):
        try:
            cache = replay.load_github_cache(opts["github_cache"]) if opts.get("github_cache") else None
            snap = replay.open_snapshot(opts["replay"])
        except (replay.ReplayError, OSError, ValueError, sqlite3.Error) as e:
            raise CannotRun(f"cannot replay: {e}") from e
        decisions += [dict(d, profile="unset") for d in replay.shadow_rows(snap) + replay.history(snap, cache)]
    _evaluate(decisions, policy)
    live = live_mod.fetch(opts["live"], _token(opts.get("token_file"))) if opts.get("live") else None

    report["decisions"] = _decision_counts(decisions, live)
    report["classes"] = _class_counts(decisions)
    report["findings"] = [_brief(d) for d in decisions if d["classified"][0] not in
                          ("agree", "vacuous-agree", "safe-conservative", "expected-stricter")][:200]
    report["coverage"] = _coverage(decisions)
    report["integrity"] = _integrity(snap, opts, now)
    report["drills"] = _drills(evidence, opts, scratch)
    report["runtime"] = _runtime(evidence, opts, now, live)
    report["nightShift"] = _night(evidence, live)
    report["live"] = _live_summary(live)
    report["performance"] = {"harnessSeconds": round(time.monotonic() - started, 2),
                             "liveMs": {k: v["ms"] for k, v in sorted((live or {}).items())}}
    report["gate"] = _gate(report, decisions, evidence, policy, live)
    report["result"] = "PASS" if all(r["status"] == "pass" for r in report["gate"]) else "FAIL"
    if snap is not None:
        snap.close()
    return report


def _token(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def _brief(d):
    cls, note = d["classified"]
    return {"id": d["id"], "source": d["source"], "project": d["project"], "action": d["action"],
            "observed": d.get("observed"), "expected": d.get("expected"), "engine": d["verdict"]["outcome"],
            "rule": d["verdict"]["rule"], "class": cls, "note": note, "inferred": d.get("inferred") or [],
            "recorded": d.get("recorded")}


def _decision_counts(decisions, live):
    counts = {}
    for d in decisions:
        c = counts.setdefault(d["source"], {}).setdefault(f"{d['project']}:{d['action']}", 0)
        counts[d["source"]][f"{d['project']}:{d['action']}"] = c + 1
    auto = live_mod.body(live, "autonomy")
    if isinstance(auto, dict):
        counts["live"] = {f"{p}:{a}": c.get("total", 0) for p, acts in sorted((auto.get("counts") or {}).items())
                          for a, c in sorted(acts.items())}
    return {s: dict(sorted(v.items())) for s, v in sorted(counts.items())}


def _class_counts(decisions):
    out = {s: {c: 0 for c in classify.CLASSES} for s in sorted({d["source"] for d in decisions})}
    for d in decisions:
        out[d["source"]][d["classified"][0]] += 1
    return out


def _coverage(decisions):
    hit = {c: sorted(d["id"] for d in decisions if d.get("class") == c) for c in fixtures.CLASSES}
    return {"classes": hit, "uncovered": sorted(c for c, ids in hit.items() if not ids),
            "replayDecisions": sum(1 for d in decisions if d["source"].startswith("replay"))}


def _integrity(snap, opts, now):
    if snap is None:
        return {"available": False}
    since = _ts(opts.get("go_live_at") or PHASE1_GO_LIVE)
    t0 = time.monotonic()
    walk = replay.audit_walk(snap)
    out = dict(replay.integrity(snap), available=True, auditWalk=walk,
               auditWalkMs=round((time.monotonic() - t0) * 1000), unauthorized=replay.unauthorized(snap, since))
    return out


def _drills(evidence, opts, scratch):
    d = dict(evidence.get("drills") or {})
    if opts.get("restore_backup"):
        try:
            d["restore"] = restore_drill(opts["restore_backup"], scratch)
        except Exception as e:  # noqa: BLE001 — a drill that cannot run is a failed drill
            d["restore"] = {"pass": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return d


def _runtime(evidence, opts, now, live):
    go = _ts(opts.get("go_live_at") or evidence.get("goLiveAt") or PHASE1_GO_LIVE)
    eng = _ts(opts.get("engine_live_at") or evidence.get("engineLiveAt"))
    health = live_mod.body(live, "health") or {}
    return {"goLiveAt": _iso(go), "hoursSinceGoLive": round((now - go) / 3600, 2),
            "engineLiveAt": _iso(eng), "hoursOnEngine": None if eng is None else round((now - eng) / 3600, 2),
            "earliestPass": _iso(max(go + MIN_HOURS * 3600, (eng or go) + MIN_ENGINE_HOURS * 3600)) if eng else None,
            "restarts": evidence.get("restarts"), "unexplainedExits": evidence.get("unexplainedExits"),
            "liveUptimeHours": round(health["uptimeS"] / 3600, 2) if isinstance(health.get("uptimeS"), (int, float))
            else None, "liveVersion": health.get("version")}


def _night(evidence, live):
    cycles = list((evidence.get("nightShift") or {}).get("cycles") or [])
    return {"cycles": cycles, "live": live_mod.body(live, "nightShift") is not None}


def _live_summary(live):
    if live is None:
        return {"available": False}
    auto = live_mod.body(live, "autonomy") or {}
    audit = live_mod.body(live, "audit") or {}
    prof = live_mod.body(live, "profiles") or {}
    workers = live_mod.body(live, "workers") or {}
    return {"available": True, "routes": {k: v["ok"] for k, v in sorted(live.items())},
            "engine": auto.get("engine"), "mode": auto.get("mode"), "total": auto.get("total"),
            "disagree": auto.get("disagree"), "disagreements": [
                {"id": x.get("id"), "project": x.get("project"), "action": x.get("action"),
                 "observed": x.get("observed"), "engine": x.get("engine"), "rule": x.get("rule"),
                 "cited": x.get("rule") in classify.RULE_CITATIONS} for x in auto.get("disagreements") or []],
            "auditChain": audit.get("chain"), "wouldRefuse": (audit.get("summary") or {}).get("wouldRefuse"),
            "profileProblems": prof.get("problems"), "mergePolicy": live_mod.merge_policy_status(live),
            "workersOnline": sum(1 for n in workers.get("nodes") or [] if n.get("status") == "online")}


def _count(decisions, cls):
    return sum(1 for d in decisions if d["classified"][0] == cls)


def _gate(report, decisions, evidence, policy, live):
    rows = []
    rt, src = report["runtime"], report["sources"]
    # 1 runtime
    if rt["hoursOnEngine"] is None:
        rows.append(_row(1, "missing", f"{rt['hoursSinceGoLive']} h since go-live; the final engine's go-live time "
                                       "is not given (--engine-live-at)"))
    else:
        ok = rt["hoursSinceGoLive"] >= MIN_HOURS and rt["hoursOnEngine"] >= MIN_ENGINE_HOURS
        rows.append(_row(1, "pass" if ok else "fail", f"{rt['hoursSinceGoLive']} h since go-live (need {MIN_HOURS}), "
                                                      f"{rt['hoursOnEngine']} h on engine v{autonomy.ENGINE_VERSION} "
                                                      f"(need {MIN_ENGINE_HOURS}); earliest pass {rt['earliestPass']}"))
    # 2 night shift
    cyc = report["nightShift"]["cycles"]
    if not cyc:
        rows.append(_row(2, "missing", "no night-shift cycle in the evidence file"))
    else:
        good = [c for c in cyc if c.get("withWork") and c.get("ended") in ("cutoff", "report")
                and isinstance(c.get("reminders"), int) and c["reminders"] <= MAX_REMINDERS]
        rows.append(_row(2, "pass" if good else "fail", f"{len(good)} of {len(cyc)} cycles had real work, ended at the "
                                                        f"cutoff or with a report, reminders ≤ {MAX_REMINDERS}"))
    # 3 restart drill, 4 restore + rollback
    dr = report["drills"]
    rows.append(_drill_row(3, dr.get("restart"), "restart drill"))
    restore, rollback = dr.get("restore"), dr.get("rollback")
    if restore is None or rollback is None:
        rows.append(_row(4, "missing", f"restore drill {'run' if restore else 'not run (--restore-backup)'}; rollback "
                                       f"drill ({OLD_COMMIT} refuses v9, boots on the backup) "
                                       f"{'given' if rollback else 'not in the evidence file'}"))
    else:
        ok = bool(restore.get("pass")) and bool(rollback.get("pass"))
        rows.append(_row(4, "pass" if ok else "fail", f"restore: {json.dumps(restore, sort_keys=True)[:200]}; "
                                                      f"rollback: {json.dumps(rollback, sort_keys=True)[:200]}"))
    # 5 profile drift
    problems = policy.problems()
    lp = (report["live"] or {}).get("profileProblems")
    if lp is None and live is not None:
        rows.append(_row(5, "missing", "the live profile summary could not be read"))
    else:
        bad = problems + list(lp or [])
        rows.append(_row(5, "fail" if bad else "pass", "; ".join(bad)[:300] or
                         f"0 drift and 0 load problems ({len(policy.profiles)} profiles"
                         f"{', live checked' if live is not None else ', repository only'})"))
    # 6 audit chain
    walks = [w for w in evidence.get("auditWalks") or [] if isinstance(w, dict)]
    integ = report["integrity"]
    if integ.get("available") and integ["auditWalk"].get("ok") is not None:
        walks.append({"when": "replay snapshot", "ok": integ["auditWalk"]["ok"]})
    chain = (report["live"] or {}).get("auditChain")
    if isinstance(chain, dict):
        walks.append({"when": "live", "ok": chain.get("ok")})
    have = {w.get("when") for w in walks}
    if any(w.get("ok") is False for w in walks):
        rows.append(_row(6, "fail", f"a full walk failed: {walks}"))
    elif not {"start", "after_restart", "end"} <= have:
        rows.append(_row(6, "missing", f"walks so far {sorted(map(str, have))}; need start, after_restart and end"))
    else:
        rows.append(_row(6, "pass", f"{len(walks)} full walks, all intact"))
    # 7 unauthorized actions, 8 data regressions
    if not integ.get("available"):
        rows.append(_row(7, "missing", "needs --replay"))
        rows.append(_row(8, "missing", "needs --replay"))
    else:
        un = integ["unauthorized"]
        rows.append(_row(7, "fail" if un else "pass", f"{len(un)} unauthorised merges or live deploys since go-live"
                                                     + (f": {un[:3]}" if un else "")))
        ok = integ["ok"] and integ["tickets"] >= replay.GO_LIVE_TICKETS and integ["eventsGaps"] == 0
        rows.append(_row(8, "pass" if ok else "fail", f"integrity {'ok' if integ['ok'] else 'FAILED'}, "
                                                      f"{integ['tickets']} tickets (go-live {replay.GO_LIVE_TICKETS}), "
                                                      f"{integ['eventsGaps']} ticket_events gaps, schema v{integ['schema']}"))
    # 9-11 classes
    live_uncited = [x for x in (report["live"] or {}).get("disagreements") or [] if not x["cited"]]
    for n, cls in ((9, "unsafe-permissive"), (10, "boundary-softened")):
        k = _count(decisions, cls)
        rows.append(_row(n, "fail" if k else "pass", f"{k} across {', '.join(s for s, on in src.items() if on) or 'no source'}"))
    k = _count(decisions, "unknown") + len(live_uncited)
    rows.append(_row(11, "fail" if k else "pass", f"{k} disagreements no citation explains"))
    # 12 coverage
    cov = report["coverage"]
    rows.append(_row(12, "fail" if cov["uncovered"] else "pass",
                     f"{len(fixtures.CLASSES) - len(cov['uncovered'])} of {len(fixtures.CLASSES)} sweep classes covered; "
                     f"{cov['replayDecisions']} replay decisions" +
                     (f"; uncovered: {cov['uncovered']}" if cov["uncovered"] else "")))
    # 13 engine bugs
    fx = [d for d in decisions if d["source"] == "fixture"]
    guarded = {d["regression"] for d in fx if d.get("regression")}
    broken = sorted({d["regression"] for d in fx if d.get("regression") and d["classified"][0] != "agree"})
    q01 = "risk_high" in ((policy.profile("commandcenter") or {}).get("target", {}).get("plan_approval") or {}).get(
        "required_for", [])
    missing_regs = sorted(set(REGRESSIONS) - guarded)
    bugs = _count(decisions, "engine-bug")
    if not fx:
        rows.append(_row(13, "missing", "needs --fixtures"))
    else:
        ok = not broken and not missing_regs and q01 and not bugs
        rows.append(_row(13, "pass" if ok else "fail",
                         f"regressions guarded {len(guarded & set(REGRESSIONS))}/{len(REGRESSIONS)}, failing {broken}, "
                         f"without a fixture {missing_regs}; Q-01 in the CommandCenter profile: {q01}; Q-02 deferred to "
                         f"Phase 2C by Jay (2026-10-22); engine bugs {bugs}"))
    # 14 legacy unchanged
    drift = [d for r in policy.profiles.values() for d in r.get("drift") or []]
    mp = (report["live"] or {}).get("mergePolicy")
    suites = evidence.get("suites") or {}
    parts = [f"auto-merge {mp or 'unknown'}", f"enforced = registry: {not drift}",
             f"suites green on {suites.get('commit') or '?'}: {suites.get('green')}"]
    if mp is None or suites.get("green") is None:
        rows.append(_row(14, "missing", "; ".join(parts) + " (needs --live and suites in the evidence file)"))
    else:
        ok = mp == "disabled" and not drift and suites.get("green") is True
        rows.append(_row(14, "pass" if ok else "fail", "; ".join(parts)))
    # 15 harness
    all_on = all(src.values())
    others = all(r["status"] == "pass" for r in rows)
    rows.append(_row(15, "pass" if all_on and others else ("missing" if not all_on else "fail"),
                     f"sources {src}; rows 1-14 {'all pass' if others else 'not all pass'}"))
    return rows


def _drill_row(n, d, what):
    if not isinstance(d, dict):
        return _row(n, "missing", f"no {what} in the evidence file")
    return _row(n, "pass" if d.get("pass") is True else "fail", json.dumps(d, sort_keys=True)[:300])


def markdown(report):
    """The human-readable mirror of readiness.json."""
    lines = [f"# Phase 1 readiness: {report['result']}", "",
             f"Run at {report['now']} with engine v{report['engine']}; policy {report['policyFingerprint'][:12]}; "
             f"sources: {', '.join(k for k, v in report['sources'].items() if v) or 'none'}.", "",
             "## Gate", "", "| # | Gate | Status | Evidence |", "|---|---|---|---|"]
    for r in report["gate"]:
        ev = str(r["evidence"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['row']} | {r['gate']} | {r['status'].upper()} | {ev} |")
    lines += ["", "## Decisions by class", "", "| Source | " + " | ".join(classify.CLASSES) + " |",
              "|---|" + "---|" * len(classify.CLASSES)]
    for s, c in report["classes"].items():
        lines.append(f"| {s} | " + " | ".join(str(c[k]) for k in classify.CLASSES) + " |")
    if report["findings"]:
        lines += ["", "## Decisions to look at", "", "| Id | Source | Project | Action | Observed | Class | Note |",
                  "|---|---|---|---|---|---|---|"]
        for f in report["findings"]:
            note = str(f["note"]).replace("|", "\\|")[:160]
            lines.append(f"| {f['id']} | {f['source']} | {f['project']} | {f['action']} | {f['observed'] or ''} | "
                         f"{f['class']} | {note} |")
    lines += ["", "## Write guard", ""] + [f"- {'blocked' if c['blocked'] else 'NOT BLOCKED'}: {c['probe']}"
                                           for c in report["guard"]]
    return "\n".join(lines) + "\n"


def write(report, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "readiness.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    with open(out / "readiness.md", "w", encoding="utf-8") as fh:
        fh.write(markdown(report))
    return out
