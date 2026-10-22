"""The Autonomy Engine, in SHADOW MODE (v2 Phase 1, decision D-008).

For each decision Command Center makes today (accept a plan, merge a PR, deploy), the engine works out what
the project's AGREED TARGET policy (`[target]` in policy/projects/<key>.toml) would have done, and the daemon
records that next to what Command Center actually did. Nothing reads the engine's answer to act on it: merge,
deploy and gates are decided exactly as before, by the registry and the pipeline. Disagreements are the
evidence Jay needs before any of the target policy is switched on.

    evaluate(action, profile, facts) -> verdict     pure: plain dicts in, a plain dict out
    Shadow(db)                                      the append-only record in tasks.db (migration 6)

Outcomes:  "auto"    the target policy lets an agent do it without Jay
           "jay"     the target policy needs Jay (or a fact it needs is not known: unknown never means yes)
           "refuse"  nobody does it (the project is paused, or the policy says never)

The engine is conservative by construction. A missing or invalid profile means "jay". A condition that needs a
fact Command Center does not have yet (a risk assessment, the changed files) is listed in `missing` and makes the
answer "jay", never "auto". Human-only boundaries (a needs:jay or needs:legal flag, a LEGAL ticket, a destructive,
financial, paid, secrets, credentials or irreversible label) are "jay" whatever the profile says. A change to any
path in `self_protection.require_jay_for_paths` is "jay" (D-007).

Engine v2 (Phase 1 safety patch): an "auto" merge also needs the PR to be ready (not a draft, mergeable, based on
main, from this repository, reviewed at its current head, at least one passing check); every deploy goes through the
deploy rules, an unknown environment is "jay"; a profile field the engine cannot check never lets a verdict be
"auto" (`FIELDS` lists how each profile key is handled, and a test keeps that list complete).
"""
import json
import re
import time

from . import merge_policy, pipeline

ENGINE_VERSION = 2
ACTIONS = ("plan", "merge", "deploy")
OUTCOMES = ("auto", "jay", "refuse")
RISKS = ("low", "medium", "high")
GH_FILE_LIMIT = 100    # `gh pr view --json files` lists at most this many
HIGH_RISK_LABELS = {"security", "migration", "destructive", "architecture", "financial", "legal"}
# Jay's human-only boundaries as ticket labels: "jay" for every action, whatever the profile says.
BOUNDARY_LABELS = {"destructive", "financial", "paid", "secrets", "credentials", "irreversible", "legal"}
LIVE_ENVS = ("live",)
NON_LIVE_ENVS = ("preview", "dev")
MAIN = "main"
# How each profile `[target]` key is handled. "enforced": the engine reads it. "fails_closed": the engine cannot
# check it, so an action it covers is never "auto". "inert": it cannot make a verdict more permissive (it is read
# by something else, or only ever narrows). tests/test_autonomy.py fails when a schema key is missing here.
FIELDS = {
    "plan_approval": "enforced", "merge": "enforced", "deploy": "enforced", "self_protection": "enforced",
    "personal_data": "enforced", "release": "enforced", "constraints": "fails_closed",
    "budget": "inert", "review": "inert", "notify": "inert", "execution": "inert", "artifacts": "inert",
    "small_safe_changes": "inert",
}
MODES_HANDLED = {"paused": "refuse", "restricted": "never auto", "experimental_autonomy": "profile",
                 "autonomous_product": "profile", "controlled_production": "profile"}


def _lower(values):
    """Labels and flags compared case-insensitively: `Legal` and `NEEDS:JAY` are not a way around a boundary."""
    return {str(v).strip().lower() for v in values or () if v is not None} if isinstance(values, (list, tuple, set)) \
        else set()


def _flags(facts):
    return {f.replace(":", "_").replace("-", "_") for f in _lower(facts.get("flags"))}


def _labels(facts):
    return _lower(facts.get("labels"))


def _type(facts):
    return str(facts.get("type") or "").strip().upper()


def _matches(path, patterns):
    """`path` matches any of the profile's glob patterns (same glob rules as the merge policy)."""
    if not merge_policy.safe_path(path):
        return True     # an odd path is treated as matching: never a reason to say yes
    return any(re.match(r"^(?:.*/)?" + merge_policy._glob(p) + "$" if "/" not in p else "^" + merge_policy._glob(p) + "$",
                        path) for p in patterns)


def risk_of(facts):
    """The change's risk, or None when Command Center cannot tell yet (no risk classifier exists; Phase 2).

    Only signals that RAISE risk are taken from labels (anyone who can label a ticket could otherwise claim
    `risk:low`): a high-risk label, `risk:high`, or a SECURITY / LEGAL type. Low risk comes only from ccd's own
    allowlist classifier (ADR 0007), never from a label."""
    labels = _labels(facts)
    if labels & HIGH_RISK_LABELS or "risk:high" in labels or _type(facts) in ("SECURITY", "LEGAL"):
        return "high"
    files = facts.get("files")
    if facts.get("project") and isinstance(files, list) and files and not merge_policy.file_reasons(
            facts["project"], files, facts.get("additions"), facts.get("deletions")):
        return "low"    # every file is on the project's low-risk allowlist (ADR 0007)
    return None


def _verdict(outcome, rule, reasons=(), missing=()):
    return {"outcome": outcome, "rule": rule, "reasons": list(reasons)[:6], "missing": sorted(set(missing)),
            "engine": ENGINE_VERSION, "enforced": False}


def _boundaries(facts):
    """Human-only boundaries that hold whatever a profile says."""
    out = []
    for key in ("labels", "flags"):
        if facts.get(key) is not None and not isinstance(facts.get(key), (list, tuple, set)):
            out.append(f"the ticket's {key} cannot be read, so a human-only boundary cannot be ruled out")
    flags = _flags(facts)
    if "needs_jay" in flags:
        out.append("the ticket is flagged needs:jay")
    labels = _labels(facts)
    if "needs_legal" in flags or _type(facts) == "LEGAL" or "legal" in labels:
        out.append("legal or compliance needs Jay")
    hit = sorted((labels & BOUNDARY_LABELS) - {"legal"})
    if hit:
        out.append(f"a human-only boundary: {', '.join(hit)}")
    return out


def _paths(facts, patterns, what):
    """(reasons, missing) for a rule that needs Jay when a changed file matches `patterns`."""
    if not patterns:
        return [], []
    files = facts.get("files")
    if not isinstance(files, list):
        return [], ["changed files"]
    if len(files) >= GH_FILE_LIMIT:   # gh lists at most 100 files: a protected one may be past the end
        return [], ["the complete list of changed files"]
    moved = [f.get("path") for f in files if isinstance(f, dict) and f.get("changeType") not in ("ADDED", "MODIFIED")]
    if moved:   # a rename shows only its new path; the old one may be protected
        return [f"{what}: it renames, copies or deletes files ({', '.join(map(str, moved[:3]))})"], []
    hit = [f.get("path") if isinstance(f, dict) else f for f in files]
    hit = [p for p in hit if _matches(p, patterns)]
    return ([f"{what}: {', '.join(map(str, hit[:3]))}"] if hit else []), []


def _conditions(requires, facts, profile):
    """(unmet reasons, missing facts) for a list of policy conditions."""
    unmet, missing = [], []
    risk = risk_of(facts)
    caps = profile.get("capabilities") or {}
    for c in requires or ():
        if c == "ci_green":
            if facts.get("ci") is None:
                missing.append("ci")
            elif facts["ci"] == "none":
                unmet.append("the PR has no CI checks")        # no checks is not green (ADR 0007 says so too)
            elif facts["ci"] != "green":
                unmet.append(f"CI is {facts['ci']}")
            elif facts.get("ci_passed") is False:
                unmet.append("no CI check passed (every check was skipped)")
            elif facts.get("ci_passed") is not True:
                missing.append("a passing CI check")
        elif c == "review_approved_at_head":
            if facts.get("review_at_head") is not True:
                unmet.append("no approving review at the PR head")
            else:
                why, gap = _same_head(facts)
                unmet += why
                missing += gap
        elif c == "risk_at_most_medium":
            if risk is None:
                missing.append("risk")
            elif risk == "high":
                unmet.append("the change is high risk")
        elif c == "security_pass_if_required":
            if _type(facts) == "SECURITY" or "security" in _labels(facts):
                missing.append("security review")      # no security review is recorded yet
        elif c == "no_personal_data_trigger":
            pass                                       # checked by the personal_data rule, with the paths
        elif c == "plan_approved_if_required":
            if facts.get("plan_accepted") is not True:
                unmet.append("the plan was not accepted")
        elif c == "merged":
            if facts.get("merged") is not True:
                unmet.append("not merged yet")
        elif c == "verify_pass":
            if facts.get("verified") is not True:
                unmet.append("not verified")
        elif c == "health_ok":
            if not caps.get("health_checks"):
                unmet.append("health checks do not exist yet")
        elif c == "auto_rollback":
            if not caps.get("auto_rollback"):
                unmet.append("automatic rollback does not exist yet")
        else:
            missing.append(c)                          # a condition this engine version does not know
    return unmet, missing


def _plan(t, facts):
    pa = t.get("plan_approval")
    if pa is None:
        return _verdict("jay", "target.plan_approval:none", ["the profile has no plan approval rule"])
    labels = _labels(facts)
    risk = risk_of(facts)
    hits, missing = [], []
    for trig in pa.get("required_for") or []:
        if trig == "always":
            hits.append("every plan needs Jay")
        elif trig == "risk_high":
            if risk is None:
                missing.append("risk")
            elif risk == "high":
                hits.append("high risk")
        elif trig == "risk_at_least_medium":
            if risk is None:
                missing.append("risk")
            elif risk in ("medium", "high"):
                hits.append(f"{risk} risk")
        elif trig == "migration":
            if "migration" in labels:
                hits.append("a migration")
        elif trig in ("ui_change_client_visible", "ui_change_major"):
            if "ui" in labels or _type(facts) == "DESIGN" or "needs_ui_review" in _flags(facts):
                hits.append("a UI change")
            else:
                missing.append("ui impact")
        elif trig in ("workflow_change", "api_change"):
            missing.append(trig.replace("_", " "))    # nothing classifies this yet
        else:
            missing.append(str(trig))                 # a trigger this engine version does not know: never a yes
    if hits:
        return _verdict("jay", "target.plan_approval", hits)
    if missing:
        return _verdict("jay", "target.plan_approval:unknown", ["a plan trigger cannot be checked yet"], missing)
    return _verdict("auto", "target.plan_approval", ["no plan trigger applies"])


def _merge(t, facts, profile):
    m = t.get("merge")
    if m is None:
        return _verdict("jay", "target.merge:none", ["the profile has no merge rule"])
    pol = m.get("policy")
    if pol == "owner":
        return _verdict("jay", "target.merge:owner", ["Jay merges this project's PRs"])
    if pol == "release_train":
        return _verdict("jay", "target.merge:release_train", ["merges wait for the release train"])
    if pol == "low-risk":
        if risk_of(facts) == "low":
            return _verdict("auto", "target.merge:low-risk", ["every file is on the low-risk allowlist"])
        return _verdict("jay", "target.merge:low-risk", ["not every file is on the low-risk allowlist"],
                        [] if isinstance(facts.get("files"), list) else ["changed files"])
    unmet, missing = _conditions(m.get("requires") or [], facts, profile)
    if unmet:
        return _verdict("jay", "target.merge:requires", unmet, missing)
    if missing:
        return _verdict("jay", "target.merge:unknown", ["a merge condition cannot be checked yet"], missing)
    return _verdict("auto", "target.merge", ["every merge condition holds"])


def _same_head(facts):
    """(unmet, missing): the approving review is for the PR's CURRENT head (a review of an older head is not one)."""
    rh, ph = facts.get("review_head"), facts.get("pr_head")
    ok = [isinstance(h, str) and pipeline.SHA_RE.match(h) for h in (rh, ph)]
    if not all(ok):
        return [], ["the PR head the review is for"]
    return ([] if rh == ph else ["the approving review is for an older head of the PR"]), []


def _readiness(facts):
    """(unmet, missing): the PR itself can be merged as reviewed. Always required for an "auto" merge, whatever
    the profile says (the same checks as ADR 0007 rule 5 in merge_policy.classify). Unknown is never ready."""
    unmet, missing = [], []
    draft = facts.get("draft")
    if draft is None:
        missing.append("whether the PR is a draft")
    elif draft is not False:
        unmet.append("the PR is a draft")
    m = facts.get("mergeable")
    if m is None or m == "UNKNOWN":
        missing.append("whether GitHub can merge the PR")
    elif m != "MERGEABLE":
        unmet.append(f"the PR is not mergeable ({str(m).lower()[:40]})")
    base = facts.get("base")
    if base is None:
        missing.append("the PR's base branch")
    elif base != MAIN:
        unmet.append(f"the PR targets {str(base)[:60]}, not {MAIN}")
    fork = facts.get("cross_repo")
    if fork is None:
        missing.append("whether the PR comes from a fork")
    elif fork is not False:
        unmet.append("the PR comes from a fork")
    why, gap = _same_head(facts)
    return unmet + why, missing + gap


def _env(facts):
    """'live' | 'preview' | 'dev' | None (an environment the engine does not know: never a yes)."""
    env = facts.get("env")
    if env is None:
        return "live"                 # a deploy that does not say where is treated as live
    env = str(env).strip().lower()
    return env if env in LIVE_ENVS + NON_LIVE_ENVS else None


def _deploy(t, facts, profile, env):
    d = t.get("deploy")
    if d is None:
        return _verdict("jay", "target.deploy:none", ["the profile has no deploy rule"])
    pol = d.get("policy")
    if pol == "never":
        return _verdict("refuse", "target.deploy:never", ["this project is never deployed by an agent"])
    if d.get("env") == "none":
        return _verdict("refuse", "target.deploy:env_none", ["the profile allows no deployment environment"])
    if env is None:
        return _verdict("jay", "deploy:unknown_env", [f"unknown deployment environment {str(facts.get('env'))[:40]!r}: "
                                                      "it may be production"])
    if env != "live":
        return _verdict("auto", "deploy:not_live", [f"a {env} deployment"])
    if pol == "jay_confirms":
        return _verdict("jay", "target.deploy:jay_confirms", ["Jay confirms every live deployment"])
    unmet, missing = _conditions(d.get("requires") or [], facts, profile)
    if pol == "release_window":
        rel = t.get("release") or {}
        caps = profile.get("capabilities") or {}
        lacking = [c for c in rel.get("unattended_requires") or [] if not caps.get(c)]
        if lacking:   # D-004: until health checks and rollback exist, a release window means release-READY
            return _verdict("jay", "target.release:unattended_requires",
                            [f"unattended release needs {', '.join(lacking)}, not built yet"] + unmet, missing)
        return _verdict("jay", "target.release:window", ["deploys go out in the release window"] + unmet, missing)
    if unmet:
        return _verdict("jay", "target.deploy:requires", unmet, missing)
    # An unattended live deploy also needs to know it has no migration, no downtime and no client-workflow change.
    for fact, what in (("no_migration", "whether it runs a migration"), ("no_downtime", "whether it causes downtime"),
                       ("no_client_workflow_change", "whether it changes a client workflow")):
        if facts.get(fact) is False:
            unmet.append(what.replace("whether it ", "it "))
        elif facts.get(fact) is not True:
            missing.append(what)
    if unmet:
        return _verdict("jay", "target.deploy:requires", unmet, missing)
    if missing:
        return _verdict("jay", "target.deploy:unknown", ["a deploy condition cannot be checked yet"], missing)
    return _verdict("auto", "target.deploy", ["every deploy condition holds"])


def _personal_data(t, facts):
    """(reasons, missing): D-005 categories (retention, privacy, deletion, …) that need approval. Paths are checked
    separately; a category needs the `personal_data` fact (the categories a change touches), unknown is not none."""
    want = (t.get("personal_data") or {}).get("require_approval_for") or []
    if not want:
        return [], []
    got = facts.get("personal_data")
    if not isinstance(got, (list, tuple)):
        return [], ["which personal-data categories it touches"]
    hit = sorted(set(map(str, got)) & set(want))
    return ([f"it touches personal data: {', '.join(hit)}"] if hit else []), []


def _closed(profile, t, action):
    """Why the profile does not allow an "auto" verdict for this action at all: fields the engine cannot check."""
    if profile.get("mode") == "restricted":
        return "the project is restricted: every decision needs Jay"
    never = (t.get("constraints") or {}).get("never") or []
    if never and action in ("merge", "deploy"):
        return f"the profile forbids {', '.join(map(str, never[:3]))}, which the engine cannot check"
    return None


def evaluate(action, profile, facts):
    """What the agreed target policy says about one decision. Pure; never raises on odd input."""
    try:
        return _evaluate(action, profile, facts)
    except Exception as e:  # noqa: BLE001 — an engine bug is never a yes
        return _verdict("jay", "engine:error", [f"the engine failed ({type(e).__name__})"])


def _evaluate(action, profile, facts):
    facts = facts if isinstance(facts, dict) else {}
    if action not in ACTIONS:
        return _verdict("jay", "engine:unknown_action", [f"the engine does not know the action {action!r}"])
    if not isinstance(profile, dict):
        return _verdict("jay", "profile:invalid", ["the project's profile is missing or invalid"])
    if profile.get("mode") == "paused":
        return _verdict("refuse", "mode:paused", [f"{facts.get('project') or 'the project'} is paused"])
    t = profile.get("target") or {}
    if action == "deploy" and ((t.get("deploy") or {}).get("policy") == "never" or (t.get("deploy") or {}).get("env") == "none"):
        return _deploy(t, facts, profile, _env(facts))     # "never" refuses before anything can soften it to "jay"
    hard = _boundaries(facts)
    if hard:
        return _verdict("jay", "boundary", hard)
    v = _decide(action, t, facts, profile)
    if v["outcome"] == "auto":
        why = _closed(profile, t, action)
        if why:
            return _verdict("jay", "profile:fails_closed", [why])
    return v


def _decide(action, t, facts, profile):
    if action == "plan":
        return _plan(t, facts)
    env = _env(facts) if action == "deploy" else "live"
    if action == "deploy" and env != "live":
        return _deploy(t, facts, profile, env)              # unknown env: "jay"; preview/dev: no path rules
    sp = t.get("self_protection") or {}
    why, missing = _paths(facts, sp.get("require_jay_for_paths") or [], "it changes Command Center's own rails")
    if why:
        return _verdict("jay", "D-007:self_protection", why)
    pd = t.get("personal_data") or {}
    why2, missing2 = _paths(facts, pd.get("trigger_paths") or [], "it touches personal-data code")
    if why2:
        return _verdict("jay", "D-005:personal_data", why2)
    v = _merge(t, facts, profile) if action == "merge" else _deploy(t, facts, profile, env)
    extra = missing + missing2
    if extra and v["outcome"] == "auto":
        return _verdict("jay", "self_protection:unknown", ["the changed files are not known, so the protected "
                                                           "paths cannot be ruled out"], extra)
    if extra:
        v["missing"] = sorted(set(v["missing"]) | set(extra))
    if action == "merge" and v["outcome"] == "auto":
        why3, missing3 = _personal_data(t, facts)
        if why3:
            return _verdict("jay", "D-005:personal_data", why3)
        unmet, gap = _readiness(facts)
        if unmet:
            return _verdict("jay", "merge:readiness", unmet, gap)
        if missing3 or gap:
            return _verdict("jay", "merge:readiness:unknown", ["the PR's readiness cannot be checked"], missing3 + gap)
    return v


def ci_passed(rollup):
    """True when at least one check passed and none failed or is pending; False when checks exist but none passed
    (every one skipped or neutral); None when unknown. Stricter than merge_policy.ci_state, which counts an
    all-skipped rollup as green (left as is: it decides today's auto-merge)."""
    if not isinstance(rollup, list) or not rollup:
        return None
    states = [str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() if isinstance(c, dict) else "?"
              for c in rollup]
    if any(s not in ("SUCCESS", "NEUTRAL", "SKIPPED") for s in states):
        return None
    return "SUCCESS" in states


# ---------- what Command Center actually did: read from the pipeline's own events ----------

def observed(events):
    """[(action, outcome, facts_extra)] for the decisions in one pipeline step's events, in order, at most one per
    action. A merge gate or a deploy gate means Jay; ccd's own merge, an accepted plan or a non-live deploy means
    auto. Everything else (a review, a block, a UI gate) is not a decision this engine compares."""
    out = {}
    tried = False   # ccd decided to merge and gh refused: the merge gate that follows is not "ccd asked Jay"
    for kind, _text, data in events or ():
        data = data if isinstance(data, dict) else {}
        if kind == "pipeline.plan_accepted":
            out.setdefault("plan", ("auto", {}))
        elif kind in ("pipeline.auto_merged", "pipeline.auto_merge_failed"):
            tried = True
            out["merge"] = ("auto", {"ci": data["ci"]} if data.get("ci") else {})
        elif kind == "pipeline.deploy_requested":
            env = data.get("env")
            out.setdefault("deploy", ("jay" if env == "live" else "auto", {"env": env}))
        elif kind == "pipeline.gate_opened" and data.get("gate") in ACTIONS and not (data["gate"] == "merge" and tried):
            out[data["gate"]] = ("jay", dict(out.get(data["gate"], (None, {}))[1]))
    return [(a, o, x) for a, (o, x) in out.items()]


def facts_of(ticket, work, extra=None):
    """The facts the engine reads, from tasks.get() and pipeline.work(). `extra`: what a caller knows besides (the
    PR read at the reviewed head: files, draft, mergeable, base, cross_repo, pr_head, ci, ci_passed; the deploy env).
    `review_at_head` only says an approving review exists; the engine compares `review_head` with `pr_head` itself,
    and without `pr_head` the review is never taken to be for the current head."""
    ticket, work = ticket or {}, work or {}
    rv = work.get("review") or {}
    head = rv.get("head") if isinstance(rv.get("head"), str) else None
    f = {"project": ticket.get("project"), "type": ticket.get("type"), "labels": list(ticket.get("labels") or []),
         "flags": list(ticket.get("flags") or []),
         "plan_accepted": work.get("planState") == "accepted",
         "review_at_head": rv.get("verdict") == "APPROVE" and bool(pipeline.SHA_RE.match(head or "")),
         "review_head": head,
         "merged": bool(work.get("merge")),
         "verified": ((work.get("verification") or {}).get("result") == "pass") if work.get("verification") else None,
         "ci": None, "files": None}
    f.update(extra or {})
    return f


# ---------- the record ----------

class Shadow:
    """The append-only shadow record (tasks.db `autonomy_shadow`, migration 6). One row per decision: what
    Command Center did, what the engine says the target policy would have done, and whether they agree."""

    def __init__(self, db):
        self.db = db

    def record(self, ticket_id, project, action, observed_outcome, verdict, facts, fingerprint, at=None):
        f = {k: v for k, v in (facts or {}).items() if k != "files"}
        files = (facts or {}).get("files")
        if isinstance(files, list):
            f["files"] = [x.get("path") if isinstance(x, dict) else x for x in files][:50]
        with self.db:
            self.db.execute(
                "INSERT INTO autonomy_shadow (at, ticket_id, project, action, observed, engine, agree, rule, reasons, "
                "missing, facts, policy, engine_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (at or time.time(), ticket_id, project, action, observed_outcome, verdict["outcome"],
                 int(observed_outcome == verdict["outcome"]), verdict["rule"][:80],
                 json.dumps(verdict["reasons"])[:2000], json.dumps(verdict["missing"])[:500],
                 json.dumps(f, default=str)[:4000], str(fingerprint or "")[:64], ENGINE_VERSION))

    def summary(self, since=None, recent=50, engine=ENGINE_VERSION):
        """Counts per project and action, and the most recent disagreements, for ONE engine version (the current
        one by default): verdicts of an older engine are known to differ (v1 said "auto" in cases v2 fixed), so they
        are never mixed in; `older` says how many rows were left out."""
        since = since if since is not None else 0
        rows = self.db.execute(
            "SELECT project, action, observed, engine, COUNT(*) FROM autonomy_shadow WHERE at >= ? AND engine_version = ? "
            "GROUP BY project, action, observed, engine ORDER BY project, action", (since, engine)).fetchall()
        counts = {}
        for project, action, obs, eng, n in rows:
            c = counts.setdefault(project, {}).setdefault(action, {"total": 0, "agree": 0, "pairs": {}})
            c["total"] += n
            c["agree"] += n if obs == eng else 0
            c["pairs"][f"{obs}->{eng}"] = n
        missing = {}
        for (m,) in self.db.execute("SELECT missing FROM autonomy_shadow WHERE at >= ? AND engine_version = ? "
                                    "AND missing != '[]'", (since, engine)):
            for x in json.loads(m):
                missing[x] = missing.get(x, 0) + 1
        dis = [{"id": r[0], "at": r[1], "key": r[2], "project": r[3], "action": r[4], "observed": r[5],
                "engine": r[6], "rule": r[7], "reasons": json.loads(r[8]), "missing": json.loads(r[9])}
               for r in self.db.execute(
                   "SELECT s.id, s.at, t.key, s.project, s.action, s.observed, s.engine, s.rule, s.reasons, s.missing "
                   "FROM autonomy_shadow s LEFT JOIN tickets t ON t.id = s.ticket_id "
                   "WHERE s.agree = 0 AND s.at >= ? AND s.engine_version = ? ORDER BY s.id DESC LIMIT ?",
                   (since, engine, recent))]
        older = self.db.execute("SELECT COUNT(*) FROM autonomy_shadow WHERE at >= ? AND engine_version != ?",
                                (since, engine)).fetchone()[0]
        total = sum(c["total"] for p in counts.values() for c in p.values())
        agree = sum(c["agree"] for p in counts.values() for c in p.values())
        return {"mode": "shadow", "engine": engine, "total": total, "agree": agree,
                "disagree": total - agree, "counts": counts, "missing": missing, "disagreements": dis, "older": older}
