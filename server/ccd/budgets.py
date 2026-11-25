"""Budgets (D-033), SHADOW ONLY: what each company, project and agent budget would do now. It holds nothing.

D-033 (Jay, 2026-10-23): budgets at the agent, project and company level, with alerts as spending approaches each
limit. At a hard limit: stop scheduling new billable work in that scope only; let running work reach a safe
checkpoint; notify Jay and the project's lead; allow an authorized adjustment or a temporary override; resume safely
after authorization or the period's reset. One agent over its limit never stops its project. Safety monitoring,
rollback and recovery are never held by a budget, and a budget hold is never a safety event.

This module is that arithmetic and the scope rule as pure functions, plus a read-only report from the usage meter
(ccd/meter.py). Nothing calls `would_start` to decide anything: until Jay approves enforcement (after Phase 2) the
report only says where a hold WOULD be. Spend is the meter's estimate at list prices. Where the data is incomplete the
report errs toward holding: a reply with no known price (Codex has none) counts at the most expensive listed price,
every budget may also set a token limit, usage tied to no project counts toward the company, and when the meter has
not read the logs for 15 minutes every line is Unknown and holds new work from 80% of its limit. Each of these, an
old price list and usage no budget covers are listed in `dataAlerts`, so missing data is never silent.

Where the numbers come from:
    company   config.json "budgets": {"company": {"monthly_usd", "monthly_tokens", "daily_usd", "alerts"}}
    project   policy/projects/<key>.toml [target.budget] monthly_usd / monthly_tokens (ccd/profiles.py)
    agent     the newest configuration version of a registered agent (ccd/onboarding.py): dailyUsd, monthlyUsd,
              monthlyTokens, alerts. Measured usage is not tied to an agent yet, so an agent's line counts only
              the usage its work steps REPORTED (source "reported"); the report says so.
"""
import calendar
import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ALERTS = (50, 80, 95)          # D-033's proposed defaults; configurable per scope
# Work the engine tags as safety work by its action type. Never held by a budget; its spend is still metered and
# shown on its own line. An agent cannot tag its own work: the tag comes from the action, not from the request.
SAFETY_KINDS = frozenset({"health_check", "monitoring", "incident_response", "rollback", "restore", "backup_check",
                          "recovery"})
# Incomplete data (D-024 clause 17): what the report does when it cannot trust its own numbers.
STALE_METER_SECONDS = 15 * 60          # no successful meter pass for this long: spend is Unknown
STALE_HOLD_PCT = 80                    # ... and a scope at or above this share of its limit holds new work
PRICE_LIST_MAX_AGE_DAYS = 90           # an older price list raises a data alert (prices stay in use)
UNATTRIBUTED_ALERT_PCT = 10            # usage tied to no project above this share of the month raises a data alert
CHECKPOINT = "finishes its current step and checkpoints (D-027); a deploy, migration, rollback or push already " \
             "under way is never cut off"


def period_bounds(now, period, week=None):
    """(start, end) of the UTC day or month holding `now`, or of the budget week (`week` = a clean week setting,
    see week_bounds; the default reset applies when it is None)."""
    if period == "week":
        return week_bounds(now, week)
    t = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    if period == "day":
        start = t.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), start.timestamp() + 86400
    start = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = calendar.monthrange(t.year, t.month)[1]
    return start.timestamp(), start.timestamp() + days * 86400


# ---------- the weekly budget (CC-064 a) ----------
# One weekly estimated-dollar budget for all apps, split into per-app shares of whole percent. Jay's Claude plan
# resets on a weekday and hour of his own, so the week is cut in that local time, not at UTC midnight: DST moves the
# reset's UTC instant, never its wall-clock time. Nothing here holds any work (that is CC-064 part b, behind
# budget_holds); with no settings row there is no weekly line and no alert.
WEEK_LEVELS = (50, 80, 95, 100)
DEFAULT_WEEK = {"weekday": 1, "hour": 0, "tz": "America/Winnipeg"}      # weekday 0 = Sunday, as the release window
CENT = Decimal("0.01")
WEEK_USD_MAX = Decimal("1000000")
WEEK_TOKENS_MAX = 10 ** 12
ESTIMATE = "Estimate, not your bill"


class BudgetError(ValueError):
    pass


def clean_week(week):
    """A week setting as {weekday 0..6 (Sunday = 0), hour 0..23, tz (an IANA name)}, or BudgetError."""
    w = DEFAULT_WEEK if week is None else week
    if not isinstance(w, dict):
        raise BudgetError("week must be {weekday, hour, tz}")
    weekday, hour, tz = w.get("weekday"), w.get("hour"), w.get("tz")
    for name, v, hi in (("weekday", weekday, 6), ("hour", hour, 23)):
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= hi:
            raise BudgetError(f"week.{name} must be a whole number from 0 to {hi}")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        raise BudgetError("week.tz must be a time zone name such as America/Winnipeg") from None
    return {"weekday": weekday, "hour": hour, "tz": tz}


def week_bounds(now, week=None):
    """(start, end) UTC timestamps of the budget week holding `now`: from the latest local weekday+hour at or before
    `now` to the same wall-clock moment seven local days later (so a DST week is 167 or 169 hours long)."""
    w = clean_week(week)
    tz = ZoneInfo(w["tz"])
    local = datetime.datetime.fromtimestamp(now, tz)
    back = (local.isoweekday() % 7 - w["weekday"]) % 7
    day = local.date() - datetime.timedelta(days=back)
    start = datetime.datetime.combine(day, datetime.time(w["hour"]), tzinfo=tz)
    if start.timestamp() > now:
        day -= datetime.timedelta(days=7)
        start = datetime.datetime.combine(day, datetime.time(w["hour"]), tzinfo=tz)
    end = datetime.datetime.combine(day + datetime.timedelta(days=7), datetime.time(w["hour"]), tzinfo=tz)
    return start.timestamp(), end.timestamp()


def week_key(now, week=None):
    """The week's start date in the reset's own time zone (YYYY-MM-DD): the key of every weekly alert."""
    w = clean_week(week)
    return datetime.datetime.fromtimestamp(week_bounds(now, w)[0], ZoneInfo(w["tz"])).date().isoformat()


def _money(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise BudgetError(f"{what} must be a number of US dollars")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise BudgetError(f"{what} must be a number of US dollars") from None
    if not d.is_finite() or d > WEEK_USD_MAX or d.quantize(CENT, ROUND_HALF_UP) <= 0:
        raise BudgetError(f"{what} must be at least 0.01 and at most {WEEK_USD_MAX} US dollars")
    return d.quantize(CENT, ROUND_HALF_UP)


def clean_settings(body, apps):
    """A settings body as stored: {weekUsd "250.00" (US dollars, cents, half-up), weekTokens int|None, shares {app:
    whole %} naming every app in `apps` and summing to 100, week {weekday, hour, tz}}. BudgetError says what is wrong."""
    if not isinstance(body, dict):
        raise BudgetError("body must be an object")
    usd = _money(body.get("weekUsd"), "weekUsd")
    tokens = body.get("weekTokens")
    if tokens is not None and (not isinstance(tokens, int) or isinstance(tokens, bool)
                               or not 0 < tokens <= WEEK_TOKENS_MAX):
        raise BudgetError("weekTokens must be a whole number of tokens, or empty")
    shares = body.get("shares")
    if not isinstance(shares, dict):
        raise BudgetError("shares must say each app's whole percent")
    if set(shares) != set(apps):
        raise BudgetError("shares must name every app, and only apps: " + ", ".join(sorted(apps)))
    for app, v in shares.items():
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100:
            raise BudgetError(f"the share of {app} must be a whole percent from 0 to 100")
    if sum(shares.values()) != 100:
        raise BudgetError(f"shares must add up to 100, not {sum(shares.values())}")
    return {"weekUsd": str(usd), "weekTokens": tokens, "shares": {a: shares[a] for a in sorted(shares)},
            "week": clean_week(body.get("week"))}


def level_of(pct):
    """0, 50, 80, 95 or 100: the highest alert level a percentage of the limit has reached. A level is reached AT its
    percentage (exactly 50.00 is 50; 49.99 is 0)."""
    if pct is None:
        return 0
    return max([lv for lv in WEEK_LEVELS if pct >= lv], default=0)


def _line_limits(settings, share):
    """(limit USD Decimal, limit tokens int|None) of a line: the account's whole, or an app's share of it (cents
    half-up; tokens rounded down so a share never grants more than it owns)."""
    usd = Decimal(settings["weekUsd"])
    tokens = settings.get("weekTokens")
    if share is None:
        return usd, tokens
    cap = (usd * share / 100).quantize(CENT, ROUND_HALF_UP)
    return cap, (None if tokens is None else int(Decimal(tokens) * share / 100))


def _spent(db, start, end, project=None):
    """(assessed USD Decimal, tokens) of measured usage in [start, end), for one app or for everything. A reply with
    no known price counts at the most expensive listed price, as report() does, so the estimate errs high."""
    fi, fo, fr, fw = fallback_prices()
    where, args = ("project = ?", (project,)) if project else ("1", ())
    usd, fallback, tokens = db.execute(
        "SELECT SUM(cost_usd), SUM(CASE WHEN cost_usd IS NULL THEN (input * ? + output * ? + cache_read * ? + "
        "cache_write * ?) / 1e6 END), SUM(input + output + cache_read + cache_write) FROM usage_records "
        f"WHERE at >= ? AND at < ? AND source != 'reported' AND {where}", (fi, fo, fr, fw, start, end, *args)).fetchone()
    return Decimal(repr(float(usd or 0))) + Decimal(repr(float(fallback or 0))), int(tokens or 0)


def week_report(db, now, settings, apps, meter_at=None, names=None):
    """The weekly lines: the account (everything measured) against weekUsd, and each app against its share of it.
    `settings` is a stored settings body (clean_settings) or None, which gives no lines at all: no budget unless Jay
    sets one. Each line carries its alert level (0, 50, 80, 95, 100) and `stale` when the meter has not read the logs
    lately: the spend is then not known, and nothing is alerted from it. Reads usage_records; writes nothing."""
    start, end = week_bounds(now, (settings or {}).get("week"))
    stale = meter_at is None or now - meter_at > STALE_METER_SECONDS
    out = {"enabled": settings is not None, "currency": "USD", "estimate": True, "note": ESTIMATE,
           "weekStart": start, "weekEnd": end, "lines": [], "stale": stale,
           "meter": {"lastReadAt": meter_at, "stale": stale, "staleAfterSeconds": STALE_METER_SECONDS}}
    if settings is None:
        return out
    out["weekKey"] = week_key(now, settings.get("week"))
    out["settings"] = {"weekUsd": settings["weekUsd"], "weekTokens": settings.get("weekTokens"),
                       "shares": dict(settings["shares"]), "week": dict(settings["week"])}
    scopes = [("account", "*", None)] + [("app", a, settings["shares"].get(a, 0)) for a in sorted(apps)]
    for scope, key, share in scopes:
        usd_cap, tok_cap = _line_limits(settings, share)
        spent, tokens = _spent(db, start, end, key if scope == "app" else None)
        pcts = []
        if usd_cap > 0:
            pcts.append(spent * 100 / usd_cap)
        if tok_cap:
            pcts.append(Decimal(tokens) * 100 / tok_cap)
        pct = max(pcts) if pcts else None          # a 0-share (paused) app has no budget: no level, no alert
        out["lines"].append({
            "scope": scope, "key": key, "name": (names or {}).get(key, key) if scope == "app" else "All apps",
            "share": share, "limitUsd": float(usd_cap), "limitTokens": tok_cap, "spentUsd": float(spent.quantize(CENT, ROUND_HALF_UP)),
            "spentTokens": tokens, "pct": None if pct is None else float(pct.quantize(Decimal("0.1"), ROUND_FLOOR)),
            "level": 0 if stale else level_of(pct), "reached": level_of(pct), "currency": "USD", "estimate": True,
            "weekKey": out["weekKey"]})
    return out


def alert_due(line, rec):
    """What to post for a line, and the record to keep once it is posted. `rec` is the stored
    {weekUsd, weekTokens, share, sent[]} of this line and week, or None. A change to the weekly amount, the token
    limit or the app's share re-arms the line. Several levels crossed in one pass post only the highest and mark
    the lower ones sent. Returns (level or None, new record)."""
    sig = {"limitUsd": line["limitUsd"], "limitTokens": line["limitTokens"], "share": line["share"]}
    sent = list(rec["sent"]) if rec and {k: rec.get(k) for k in sig} == sig else []
    level = line["level"]
    if level and level > max(sent, default=0):
        return level, {**sig, "sent": [lv for lv in WEEK_LEVELS if lv <= level]}
    return None, {**sig, "sent": sent}


def alert_text(line, week_key_):
    """The Messages text of one weekly alert. Always says estimate and not your bill; promises no hold."""
    spent, cap = f"${line['spentUsd']:,.2f}", f"${line['limitUsd']:,.2f}"
    what = "all apps" if line["scope"] == "account" else line["name"]
    head = (f"Estimate: {what} reached its weekly budget" if line["level"] >= 100
            else f"Estimate: {what} used {line['level']}% of its weekly budget")
    return f"{head} (about {spent} of {cap}, week of {week_key_}). Not your bill."


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


def fallback_prices():
    """USD per million tokens for usage with no known price: the most expensive listed price of each kind, so an
    unpriced reply can only bring a hold sooner, never later. (input, output, cache read, cache write at 2 x input)."""
    from .meter import PRICES
    i = max(p[0] for p in PRICES.values())
    return i, max(p[1] for p in PRICES.values()), max(p[2] for p in PRICES.values()), 2 * i


def _age_days(now, as_of):
    try:
        t = datetime.datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None
    return int((now - t) // 86400)


def report(db, now, company=None, projects=None, agents=None, meter_at=None, prices_as_of=None):
    """The shadow report: each budget line with its spend and what it would do. Reads usage_records; writes nothing.

    Conservative where the data is incomplete:
    - a reply with no known price (Codex, an unknown model) is charged at `fallback_prices()` and the line is judged on
      that figure (`assessedUsd`), never on the priced part alone;
    - usage tied to no project counts toward the company and is listed as `unattributedUsd`;
    - `meter_at` is when the meter last read the logs successfully. None, or older than STALE_METER_SECONDS, makes
      every line's spend Unknown (`state` "unknown"), and a line at or above STALE_HOLD_PCT would hold new work
      (`holdReason` "stale-meter") until a fresh reading.
    `dataAlerts` lists every such gap, plus an old price list and unattributed usage with no company budget."""
    if prices_as_of is None:
        from .meter import PRICES_AS_OF as prices_as_of
    measured = "source != 'reported'"
    fi, fo, fr, fw = fallback_prices()
    fallback_sql = "(input * ? + output * ? + cache_read * ? + cache_write * ?) / 1e6"
    stale = meter_at is None or now - meter_at > STALE_METER_SECONDS
    lines, holds = [], set()
    for scope, key, period, limit, alerts in lines_for(company, projects, agents):
        start, end = period_bounds(now, period)
        if scope == "agent":
            where, args, source = "source = 'reported' AND actor = ?", (key,), "reported"
        elif scope == "project":
            where, args, source = f"{measured} AND project = ?", (key,), "measured"
        else:
            where, args, source = measured, (), "measured"
        usd, tokens, unpriced, fallback, unattributed = db.execute(
            "SELECT SUM(cost_usd), SUM(input + output + cache_read + cache_write), SUM(cost_usd IS NULL), "
            f"SUM(CASE WHEN cost_usd IS NULL THEN {fallback_sql} END), "
            f"SUM(CASE WHEN project IS NULL THEN COALESCE(cost_usd, {fallback_sql}) END) "
            f"FROM usage_records WHERE at >= ? AND at < ? AND {where}",
            (fi, fo, fr, fw, fi, fo, fr, fw, start, end, *args)).fetchone()
        assessed = (usd or 0) + (fallback or 0)
        a = assess(assessed, tokens or 0, limit, alerts, (now - start) / (end - start))
        a["holdReason"] = "limit" if a["state"] == "hold" else None
        if stale and a["state"] not in ("none", "hold"):
            if a["pct"] >= STALE_HOLD_PCT:
                a.update(state="hold", holdReason="stale-meter")
            else:
                a["state"] = "unknown"
        if a["state"] == "hold":
            holds.add((scope, key))
        line = {"scope": scope, "key": key, "period": period, "limitUsd": limit["usd"],
                "limitTokens": limit["tokens"], "spentUsd": round(usd or 0, 4), "spentTokens": tokens or 0,
                "unpricedReplies": unpriced or 0, "unpricedUsdAtFallback": round(fallback or 0, 4),
                "assessedUsd": round(assessed, 4), "alerts": list(alerts), "source": source, **a}
        if scope == "company":
            line["unattributedUsd"] = round(unattributed or 0, 4)
        lines.append(line)

    # Gaps in the data, each named so that none is silent.
    start, end = period_bounds(now, "month")
    total, unattributed, unpriced, unpriced_usd = db.execute(
        f"SELECT SUM(COALESCE(cost_usd, {fallback_sql})), "
        f"SUM(CASE WHEN project IS NULL THEN COALESCE(cost_usd, {fallback_sql}) END), SUM(cost_usd IS NULL), "
        f"SUM(CASE WHEN cost_usd IS NULL THEN {fallback_sql} END) "
        f"FROM usage_records WHERE at >= ? AND at < ? AND {measured}",
        (fi, fo, fr, fw, fi, fo, fr, fw, fi, fo, fr, fw, start, end)).fetchone()
    data = []
    if stale:
        data.append({"kind": "meter-stale", "lastReadAt": meter_at,
                     "detail": f"no meter reading for over {STALE_METER_SECONDS // 60} minutes: spend is Unknown and "
                               f"a scope at {STALE_HOLD_PCT}% of its limit or more would hold new work"})
    age = _age_days(now, prices_as_of)
    if age is None or age > PRICE_LIST_MAX_AGE_DAYS:
        data.append({"kind": "price-list-old", "asOf": prices_as_of, "ageDays": age,
                     "detail": "update meter.PRICES; the listed prices stay in use until then"})
    if unpriced:
        data.append({"kind": "unpriced-usage", "replies": unpriced, "usdAtFallback": round(unpriced_usd or 0, 4),
                     "detail": "replies with no known price, counted at the most expensive listed price"})
    share = 100.0 * (unattributed or 0) / total if total else 0.0
    if unattributed and share > UNATTRIBUTED_ALERT_PCT:
        data.append({"kind": "unattributed-usage", "pct": round(share, 1), "usd": round(unattributed, 4),
                     "detail": "usage tied to no project, counted toward the company budget"})
    if unattributed and not any(x["scope"] == "company" for x in lines):
        data.append({"kind": "unbudgeted-usage", "usd": round(unattributed, 4),
                     "detail": "usage tied to no project, and no company budget is set to count it against"})
    return {"mode": "shadow", "enforced": False, "at": now, "lines": lines,
            "meter": {"lastReadAt": meter_at, "stale": stale, "staleAfterSeconds": STALE_METER_SECONDS},
            "prices": {"asOf": prices_as_of, "ageDays": age, "maxAgeDays": PRICE_LIST_MAX_AGE_DAYS},
            "dataAlerts": data,
            "wouldHold": [{"scope": s, "key": k} for s, k in sorted(holds)],
            "safetyKinds": sorted(SAFETY_KINDS), "fallbackUsdPerMTok": dict(zip(("input", "output", "cacheRead",
                                                                                  "cacheWrite"), (fi, fo, fr, fw))),
            "note": "Shadow only: nothing is held or stopped. Spend is an estimate at list prices. A reply with no known "
                    "price (Codex, an unknown model) counts at the most expensive listed price, so it can only bring a "
                    "hold sooner. With no fresh meter reading, spend is Unknown and lines at 80% or more would "
                    "hold. Agent lines count only usage their work steps reported; project and company lines count "
                    "everything measured."}
