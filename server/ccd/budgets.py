"""Budgets (D-033), SHADOW ONLY: what each company, project and agent budget would do now. It holds nothing.

D-033 (Jay, 2026-10-23): budgets at the agent, project and company level, with alerts as spending approaches each
limit. At a hard limit: stop scheduling new billable work in that scope only; let running work reach a safe
checkpoint; notify Jay and the project's lead; allow an authorized adjustment or a temporary override; resume safely
after authorization or the period's reset. One agent over its limit never stops its project. Safety monitoring,
rollback and recovery are never held by a budget, and a budget hold is never a safety event.

This module is that arithmetic and the scope rule as pure functions, plus a read-only report from the usage meter
(ccd/meter.py). Nothing calls `would_start` to decide anything: until Jay approves enforcement (after Phase 2) the
report only says where a hold WOULD be. Spend is the meter's estimate at list prices; Codex has no price, so every
budget may also set a token limit, and unpriced replies are counted on their own.

Where the numbers come from:
    company   config.json "budgets": {"company": {"monthly_usd", "monthly_tokens", "daily_usd", "alerts"}}
    project   policy/projects/<key>.toml [target.budget] monthly_usd / monthly_tokens (ccd/profiles.py)
    agent     the newest configuration version of a registered agent (ccd/onboarding.py): dailyUsd, monthlyUsd,
              monthlyTokens, alerts. Measured usage is not tied to an agent yet, so an agent's line counts only
              the usage its work steps REPORTED (source "reported"); the report says so.
"""
import calendar
import datetime

DEFAULT_ALERTS = (50, 75, 90)
# Work the engine tags as safety work by its action type. Never held by a budget; its spend is still metered and
# shown on its own line. An agent cannot tag its own work: the tag comes from the action, not from the request.
SAFETY_KINDS = frozenset({"health_check", "monitoring", "incident_response", "rollback", "restore", "backup_check",
                          "recovery"})
CHECKPOINT = "finishes its current step and checkpoints (D-027); a deploy, migration, rollback or push already " \
             "under way is never cut off"


def period_bounds(now, period):
    """(start, end) of the UTC day or month holding `now`."""
    t = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    if period == "day":
        start = t.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), start.timestamp() + 86400
    start = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = calendar.monthrange(t.year, t.month)[1]
    return start.timestamp(), start.timestamp() + days * 86400


def effective_limit(limit, override=None, now=None):
    """A limit plus a temporary override that has not expired. override = {"usd", "tokens", "until"}. An expired
    override ends by itself; an override never lowers a limit and never removes it."""
    out = dict(limit or {})
    if override and now is not None and now < (override.get("until") or 0):
        for k in ("usd", "tokens"):
            extra = override.get(k)
            if out.get(k) is not None and isinstance(extra, (int, float)) and extra > 0:
                out[k] = out[k] + extra
    return out


def assess(spent_usd, spent_tokens, limit, alerts=DEFAULT_ALERTS, elapsed=None):
    """One budget line. `limit` = {"usd": number or None, "tokens": number or None}; a limit of 0 allows no billable
    work at all. `elapsed`: how much of the period has passed (0..1), for the run-rate warning.

    state: none (no limit set) | ok | alert (an alert threshold crossed) | hold (at or over the hard limit)."""
    pcts = []
    for spent, cap in ((spent_usd or 0, (limit or {}).get("usd")), (spent_tokens or 0, (limit or {}).get("tokens"))):
        if cap is None:
            continue
        pcts.append(100.0 if cap <= 0 else 100.0 * spent / cap)
    if not pcts:
        return {"state": "none", "pct": None, "threshold": None, "onCourseToHold": False}
    pct = max(pcts)
    crossed = [a for a in sorted(alerts or DEFAULT_ALERTS) if pct >= a]
    state = "hold" if pct >= 100 else "alert" if crossed else "ok"
    on_course = bool(state != "hold" and elapsed and 0 < elapsed < 1 and pct / elapsed >= 100)
    return {"state": state, "pct": round(pct, 1), "threshold": crossed[-1] if crossed else None,
            "onCourseToHold": on_course}


def would_start(work, holds):
    """Would new work start under these holds? Pure; nothing calls it to decide anything yet.

    work = {"agent": "agent:<slug>" | None, "project": key | None, "kind": action type, "billable": bool}
    holds = {(scope, key)}: ("company", "*"), ("project", key), ("agent", "agent:<slug>")

    The scope rule: an agent's hold stops only that agent's new work; a project's hold only that project's; the
    company's all billable work. Safety work and work that costs nothing are never held."""
    if work.get("kind") in SAFETY_KINDS:
        return {"start": True, "heldBy": [], "reason": "safety work is never held by a budget"}
    if work.get("billable") is False:
        return {"start": True, "heldBy": [], "reason": "not billable"}
    mine = [("company", "*")]
    if work.get("project"):
        mine.append(("project", work["project"]))
    if work.get("agent"):
        mine.append(("agent", work["agent"]))
    held = [{"scope": s, "key": k} for s, k in mine if (s, k) in holds]
    if held:
        return {"start": False, "heldBy": held, "inProgress": CHECKPOINT,
                "reason": "over budget: " + ", ".join(f"{h['scope']} {h['key']}" for h in held)}
    return {"start": True, "heldBy": [], "reason": "within budget"}


def _limits(b, usd_key, tokens_key):
    usd, tokens = b.get(usd_key), b.get(tokens_key)
    ok = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0  # noqa: E731
    return {"usd": usd if ok(usd) else None, "tokens": tokens if ok(tokens) else None}


def _alerts(b):
    a = b.get("alerts")
    if isinstance(a, list) and a and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 99 for x in a):
        return tuple(sorted(set(a)))
    return DEFAULT_ALERTS


def lines_for(company=None, projects=None, agents=None):
    """Every configured budget as (scope, key, period, limit, alerts). Inputs as described in the module doc."""
    out = []
    c = company if isinstance(company, dict) else {}
    if c:
        out.append(("company", "*", "month", _limits(c, "monthly_usd", "monthly_tokens"), _alerts(c)))
        if c.get("daily_usd") is not None:
            out.append(("company", "*", "day", _limits(c, "daily_usd", "-"), _alerts(c)))
    for key, b in sorted((projects or {}).items()):
        if isinstance(b, dict) and b:
            out.append(("project", key, "month", _limits(b, "monthly_usd", "monthly_tokens"), _alerts(b)))
    for aid, b in sorted((agents or {}).items()):
        if not isinstance(b, dict) or not b:
            continue
        if b.get("monthlyUsd") is not None or b.get("monthlyTokens") is not None:
            out.append(("agent", aid, "month", _limits(b, "monthlyUsd", "monthlyTokens"), _alerts(b)))
        if b.get("dailyUsd") is not None:
            out.append(("agent", aid, "day", _limits(b, "dailyUsd", "-"), _alerts(b)))
    return [x for x in out if x[3]["usd"] is not None or x[3]["tokens"] is not None]


def report(db, now, company=None, projects=None, agents=None):
    """The shadow report: each budget line with its spend and what it would do. Reads usage_records; writes nothing."""
    measured = "source != 'reported'"
    lines, holds = [], set()
    for scope, key, period, limit, alerts in lines_for(company, projects, agents):
        start, end = period_bounds(now, period)
        if scope == "agent":
            where, args, source = "source = 'reported' AND actor = ?", (key,), "reported"
        elif scope == "project":
            where, args, source = f"{measured} AND project = ?", (key,), "measured"
        else:
            where, args, source = measured, (), "measured"
        usd, tokens, unpriced = db.execute(
            f"SELECT SUM(cost_usd), SUM(input + output + cache_read + cache_write), SUM(cost_usd IS NULL) "
            f"FROM usage_records WHERE at >= ? AND at < ? AND {where}", (start, end, *args)).fetchone()
        a = assess(usd or 0, tokens or 0, limit, alerts, (now - start) / (end - start))
        if a["state"] == "hold":
            holds.add((scope, key))
        lines.append({"scope": scope, "key": key, "period": period, "limitUsd": limit["usd"],
                      "limitTokens": limit["tokens"], "spentUsd": round(usd or 0, 4), "spentTokens": tokens or 0,
                      "unpricedReplies": unpriced or 0, "alerts": list(alerts), "source": source, **a})
    return {"mode": "shadow", "enforced": False, "at": now, "lines": lines,
            "wouldHold": [{"scope": s, "key": k} for s, k in sorted(holds)],
            "safetyKinds": sorted(SAFETY_KINDS),
            "note": "Shadow only: nothing is held or stopped. Spend is an estimate at list prices; Codex usage has no "
                    "price, so use token limits for it. Agent lines count only usage their work steps reported."}
