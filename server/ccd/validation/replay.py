"""Replay: decisions from a COPY of tasks.db, read-only, through the current engine and profiles.

Two sources inside the snapshot:
  shadow    every autonomy_shadow row: its recorded facts, re-evaluated (and the recorded verdict kept, so an
            engine-version difference is visible)
  history   every pipeline step in ticket_events, rebuilt as the daemon would have seen it: the decisions
            (`autonomy.observed`), the ticket's labels, type and flags as of that moment (later changes undone),
            the reviewed head, the CI state, and, from a GitHub cache file when given, the PR's readiness facts
            (inferred facts are listed per decision)

The snapshot is opened with SQLite's `mode=ro&immutable=1`; a path inside the live data folder is refused.
"""
import json
import os
import sqlite3
from pathlib import Path

from .. import autonomy, merge_policy

GO_LIVE_TICKETS = 334     # tickets at the Phase 1 go-live (2026-10-21 23:46 UTC)


class ReplayError(Exception):
    pass


def live_dirs():
    """Folders that hold a live tasks.db: never replayed in place."""
    home = Path(os.environ.get("CCBOARD_HOME", Path.home() / "command-center"))
    dirs = {Path(os.environ.get("CCD_DATA_DIR", home / "data")), home / "data", home / "state",
            Path(os.environ.get("CCD_STATE_DIR", home / "state"))}
    return sorted({Path(os.path.realpath(d)) for d in dirs})


def open_snapshot(path):
    p = Path(os.path.realpath(path))
    if not p.is_file():
        raise ReplayError(f"{path} is not a file")
    for d in live_dirs():
        if p == d or d in p.parents:
            raise ReplayError(f"{path} is inside the live data folder {d}: copy it elsewhere first")
        try:
            same = [f for f in d.iterdir() if f.is_file() and os.path.samefile(f, p)]
        except OSError:
            same = []
        if same:
            raise ReplayError(f"{path} is the live file {same[0]} (a hard link): copy it with sqlite3 .backup")
    wal = Path(str(p) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ReplayError(f"{path} has a write-ahead log that a read-only replay would not see: make the copy with "
                          "sqlite3's .backup (or VACUUM INTO) instead of copying the file")
    db = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only = ON")
    return db


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _json(s, default):
    try:
        v = json.loads(s) if s else default
    except (TypeError, ValueError):
        return default
    return v


def _obj(s):
    v = _json(s, {})
    return v if isinstance(v, dict) else {}


def integrity(db):
    """{ok, tickets, eventsGaps, schema} for gate row 8."""
    ok = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    tables = _tables(db)
    tickets = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] if "tickets" in tables else 0
    gaps = 0
    if "ticket_events" in tables:
        n, hi = db.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM ticket_events").fetchone()
        gaps = hi - n
    schema = db.execute("PRAGMA user_version").fetchone()[0]
    return {"ok": ok, "tickets": tickets, "ticketsAtGoLive": GO_LIVE_TICKETS, "eventsGaps": gaps, "schema": schema}


def audit_walk(db):
    """A full walk of the audit hash chain, on the snapshot (gate row 6)."""
    if "audit_events" not in _tables(db):
        return {"ok": None, "checked": 0, "brokenAt": None, "note": "no audit_events table"}
    from ..audit import Audit
    return Audit(db).verify(full=True)


def actions(db, since, cache=None, jay_logins=("JayDalool",)):
    """Every merge and live deploy after `since`, judged for gate row 7: {checked, unauthorized, unverified}.

    - An agent merge (pipeline.auto_merged) is unauthorised: global auto-merge is off.
    - A merge ccd saw on GitHub (pipeline.merged) is Jay's when Jay confirmed this ticket's merge gate before it, or
      the GitHub cache says one of `jay_logins` merged the PR. Otherwise it is unverified, never assumed.
    - A live deploy (pipeline.deployed, env live) needs a deploy approval from Jay after the ticket's previous
      deploy and before this one."""
    cache, logins = cache or {}, set(jay_logins or ())
    out = {"checked": 0, "unauthorized": [], "unverified": []}
    rows = db.execute("SELECT e.id, e.ticket_id, e.at, e.kind, e.data, t.key FROM ticket_events e LEFT JOIN tickets t "
                      "ON t.id = e.ticket_id WHERE e.at >= ? AND e.kind IN ('pipeline.auto_merged', 'pipeline.merged', "
                      "'pipeline.deployed') ORDER BY e.id", (since,)).fetchall()
    for eid, tid, at, kind, data, key in rows:
        d = _json(data, {})
        d = d if isinstance(d, dict) else {}
        item = {"event": eid, "key": key, "kind": kind}
        if kind == "pipeline.auto_merged":
            out["checked"] += 1
            out["unauthorized"].append(dict(item, why="an agent merge while auto-merge is off"))
        elif kind == "pipeline.merged":
            out["checked"] += 1
            # the confirmation must come after the last change that voids an approval (rework, replan, stale review)
            void = db.execute("SELECT COALESCE(MAX(id), 0) FROM ticket_events WHERE ticket_id = ? AND id < ? AND kind IN "
                              "('pipeline.rework', 'pipeline.replan', 'pipeline.review_stale')", (tid, eid)).fetchone()[0]
            conf = [cid for cid, x in db.execute(
                "SELECT id, data FROM ticket_events WHERE ticket_id = ? AND id > ? AND id < ? AND actor = 'jay' "
                "AND kind = 'pipeline.gate_confirmed'", (tid, void, eid)) if _obj(x).get("gate") == "merge"]
            pr = cache.get(d.get("pr")) if isinstance(cache.get(d.get("pr")), dict) else None
            by = ((pr or {}).get("mergedBy") or {}).get("login") if isinstance((pr or {}).get("mergedBy"), dict) else None
            if by and by in logins:
                continue
            merged_head = (pr or {}).get("headRefOid")
            if conf and isinstance(merged_head, str) and merged_head:
                # Jay confirms a merge for one head: the head reviewed before the confirmation must be the one merged
                rev = db.execute("SELECT data FROM ticket_events WHERE ticket_id = ? AND id < ? AND kind = "
                                 "'pipeline.review' ORDER BY id DESC LIMIT 1", (tid, conf[-1])).fetchone()
                head = _obj(rev[0]).get("head") if rev else None
                if head != merged_head:
                    out["unverified"].append(dict(item, pr=d.get("pr"), why=f"Jay confirmed head {str(head)[:12]}, "
                                                                           f"the PR merged {merged_head[:12]}"))
                    continue
            if conf:
                continue
            if by:
                out["unauthorized"].append(dict(item, why=f"merged on GitHub by {by}, not Jay"))
            else:
                out["unverified"].append(dict(item, pr=d.get("pr"), why="no merge-gate confirmation and no merger known"))
        elif (d.get("env") or "live") == "live":
            out["checked"] += 1
            prev = db.execute("SELECT COALESCE(MAX(id), 0) FROM ticket_events WHERE ticket_id = ? AND id < ? "
                              "AND kind = 'pipeline.deployed'", (tid, eid)).fetchone()[0]
            ok = db.execute("SELECT 1 FROM ticket_events WHERE ticket_id = ? AND id > ? AND id < ? AND actor = 'jay' "
                            "AND kind = 'pipeline.deploy_approved' LIMIT 1", (tid, prev, eid)).fetchone()
            if ok is None:
                out["unauthorized"].append(dict(item, why="a live deploy with no Jay deploy approval since the last one"))
    return out


def _state_at(db, tid, at, cur):
    """The ticket's type, labels and flags as they were at `at`: today's values with every later change undone."""
    typ, labels, flags = cur["type"], set(cur["labels"]), set(cur["flags"])
    for kind, field, frm, to in db.execute(
            "SELECT kind, field, from_value, to_value FROM ticket_events WHERE ticket_id = ? AND at > ? "
            "ORDER BY id DESC", (tid, at)):
        if kind == "label_added" and to:
            labels.discard(to)
        elif kind == "label_removed" and frm:
            labels.add(frm)
        elif kind == "flag" and field:
            (flags.add if _json(frm, False) else flags.discard)(field)
        elif field == "type":
            typ = frm
    return typ, sorted(labels), sorted(flags)


def _tickets(db):
    out = {}
    flags = ("needs_jay", "needs_legal", "needs_ui_review", "needs_deploy")
    cols = {r[1] for r in db.execute("PRAGMA table_info(tickets)")}
    have = [f for f in flags if f in cols]
    for r in db.execute(f"SELECT id, key, project, type{''.join(', ' + f for f in have)} FROM tickets"):
        out[r[0]] = {"key": r[1], "project": r[2], "type": r[3], "labels": [],
                     "flags": [f for f, v in zip(have, r[4:]) if v]}
    for tid, label in db.execute("SELECT ticket_id, label FROM ticket_labels"):
        if tid in out:
            out[tid]["labels"].append(label)
    return out


def _pr_refs(db):
    refs = {}
    if "ticket_links" in _tables(db):
        for tid, ref in db.execute("SELECT ticket_id, ref FROM ticket_links WHERE provider='github' AND kind='pr' ORDER BY id"):
            refs.setdefault(tid, []).append(ref)
    return refs


def shadow_rows(db):
    """[{source, id, at, key, project, action, observed, recorded, facts}] from autonomy_shadow."""
    if "autonomy_shadow" not in _tables(db):
        return []
    out = []
    for sid, at, key, project, action, obs, eng, rule, facts, ver in db.execute(
            "SELECT s.id, s.at, t.key, s.project, s.action, s.observed, s.engine, s.rule, s.facts, s.engine_version "
            "FROM autonomy_shadow s LEFT JOIN tickets t ON t.id = s.ticket_id ORDER BY s.id"):
        out.append({"source": "replay-shadow", "id": f"S{sid}", "at": at, "key": key, "project": project,
                    "action": action, "observed": obs, "recorded": {"engine": eng, "rule": rule, "version": ver},
                    "facts": _json(facts, {}), "inferred": []})
    return out


def history(db, github_cache=None):
    """Every decision in the pipeline's own history, rebuilt (see the module docstring)."""
    cache = github_cache or {}
    tickets, refs = _tickets(db), _pr_refs(db)
    steps = {}
    for tid, at, kind, data in db.execute("SELECT ticket_id, at, kind, data FROM ticket_events WHERE kind LIKE 'pipeline.%' "
                                          "ORDER BY ticket_id, at, id"):
        steps.setdefault((tid, at), []).append((kind, "", _json(data, {})))
    out = []
    review, verified, ci, planned = {}, {}, {}, set()
    for (tid, at), events in sorted(steps.items()):
        for kind, _t, d in events:
            if kind == "pipeline.review" and isinstance(d, dict):
                review[tid] = d
            elif kind in ("pipeline.review_stale", "pipeline.rework", "pipeline.replan"):
                review.pop(tid, None)          # the approval no longer covers the PR
                if kind == "pipeline.replan":
                    planned.discard(tid)
            elif kind == "pipeline.plan_accepted" or (kind == "pipeline.gate_confirmed" and isinstance(d, dict)
                                                      and d.get("gate") == "plan"):
                planned.add(tid)
            elif kind == "pipeline.verified":
                verified[tid] = True
            elif kind == "pipeline.ready_to_merge" and isinstance(d, dict) and d.get("ci"):
                ci[tid] = d["ci"]
        decided = autonomy.observed(events)
        if not decided or tid not in tickets:
            continue
        cur = tickets[tid]
        typ, labels, flags = _state_at(db, tid, at, cur)
        for action, outcome, extra in decided:
            rv = review.get(tid) or {}
            head = rv.get("head") if isinstance(rv.get("head"), str) else None
            facts = {"project": cur["project"], "type": typ, "labels": labels, "flags": flags, "confirmed": None,
                     "plan_accepted": tid in planned,
                     "review_at_head": rv.get("verdict") == "APPROVE" and bool(head and len(head) == 40),
                     "review_head": head, "merged": False, "verified": verified.get(tid), "ci": ci.get(tid),
                     "files": None}
            facts.update(extra)
            inferred = []
            if action == "merge":
                pr = None
                for ref in refs.get(tid, []):
                    if isinstance(cache.get(ref), dict):
                        pr = cache[ref]
                if pr:
                    rollup = pr.get("statusCheckRollup")
                    facts.update(files=pr.get("files"), additions=pr.get("additions"), deletions=pr.get("deletions"),
                                 draft=pr.get("isDraft"), mergeable=pr.get("mergeable"), base=pr.get("baseRefName"),
                                 cross_repo=pr.get("isCrossRepository"), pr_head=pr.get("headRefOid"))
                    if rollup is not None:
                        facts.update(ci=merge_policy.ci_state(rollup), ci_passed=autonomy.ci_passed(rollup))
                    inferred.append("PR facts from the GitHub cache (read after the decision, not at it)")
                    if pr.get("mergeable") is None:
                        inferred.append("mergeable unknown in the cache")
            out.append({"source": "replay-history", "id": f"H{tid}@{at:.3f}:{action}", "at": at, "key": cur["key"],
                        "project": cur["project"], "action": action, "observed": outcome, "facts": facts,
                        "inferred": inferred})
    return out


def load_github_cache(path):
    """{pr ref: gh pr view JSON}. A list of objects with `ref` is accepted too."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {x.get("ref"): x for x in data if isinstance(x, dict) and x.get("ref")}
    if not isinstance(data, dict):
        raise ReplayError("the GitHub cache must be an object keyed by PR ref")
    return data
