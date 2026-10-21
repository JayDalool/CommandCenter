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
answer "jay", never "auto". Human-only boundaries (a needs:jay or needs:legal flag, a LEGAL ticket) are "jay"
whatever the profile says. A change to any path in `self_protection.require_jay_for_paths` is "jay" (D-007).
"""
import json
import re
import time

from . import merge_policy, pipeline

ENGINE_VERSION = 1
ACTIONS = ("plan", "merge", "deploy")
OUTCOMES = ("auto", "jay", "refuse")
RISKS = ("low", "medium", "high")
GH_FILE_LIMIT = 100    # `gh pr view --json files` lists at most this many
HIGH_RISK_LABELS = {"security", "migration", "destructive", "architecture", "financial", "legal"}


def _flags(facts):
    return {str(f).replace(":", "_").replace("-", "_") for f in facts.get("flags") or []}


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
    labels = set(facts.get("labels") or [])
    if labels & HIGH_RISK_LABELS or "risk:high" in labels or facts.get("type") in ("SECURITY", "LEGAL"):
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
    flags = _flags(facts)
    if "needs_jay" in flags:
        out.append("the ticket is flagged needs:jay")
    if "needs_legal" in flags or facts.get("type") == "LEGAL" or "legal" in (facts.get("labels") or []):
        out.append("legal or compliance needs Jay")
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
    for c in requires:
        if c == "ci_green":
            if facts.get("ci") is None:
                missing.append("ci")
            elif facts["ci"] == "none":
                unmet.append("the PR has no CI checks")        # no checks is not green (ADR 0007 says so too)
            elif facts["ci"] != "green":
                unmet.append(f"CI is {facts['ci']}")
        elif c == "review_approved_at_head":
            if not facts.get("review_at_head"):
                unmet.append("no approving review at the PR head")
        elif c == "risk_at_most_medium":
            if risk is None:
                missing.append("risk")
            elif risk == "high":
                unmet.append("the change is high risk")
        elif c == "security_pass_if_required":
            if facts.get("type") == "SECURITY" or "security" in (facts.get("labels") or []):
                missing.append("security review")      # no security review is recorded yet
        elif c == "no_personal_data_trigger":
            pass                                       # checked by the personal_data rule, with the paths
        elif c == "plan_approved_if_required":
            if not facts.get("plan_accepted"):
                unmet.append("the plan was not accepted")
        elif c == "merged":
            if not facts.get("merged"):
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
    labels = set(facts.get("labels") or [])
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
            if "ui" in labels or facts.get("type") == "DESIGN" or "needs_ui_review" in _flags(facts):
                hits.append("a UI change")
            else:
                missing.append("ui impact")
        elif trig in ("workflow_change", "api_change"):
            missing.append(trig.replace("_", " "))    # nothing classifies this yet
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


def _deploy(t, facts, profile):
    d = t.get("deploy")
    if d is None:
        return _verdict("jay", "target.deploy:none", ["the profile has no deploy rule"])
    pol = d.get("policy")
    if pol == "never":
        return _verdict("refuse", "target.deploy:never", ["this project is never deployed by an agent"])
    if facts.get("env") and facts["env"] != "live":
        return _verdict("auto", "deploy:not_live", [f"a {facts['env']} deployment"])
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
    if missing:
        return _verdict("jay", "target.deploy:unknown", ["a deploy condition cannot be checked yet"], missing)
    return _verdict("auto", "target.deploy", ["every deploy condition holds"])


def evaluate(action, profile, facts):
    """What the agreed target policy says about one decision. Pure; never raises on odd input."""
    facts = facts if isinstance(facts, dict) else {}
    if action not in ACTIONS:
        return _verdict("jay", "engine:unknown_action", [f"the engine does not know the action {action!r}"])
    if not isinstance(profile, dict):
        return _verdict("jay", "profile:invalid", ["the project's profile is missing or invalid"])
    if profile.get("mode") == "paused":
        return _verdict("refuse", "mode:paused", [f"{facts.get('project') or 'the project'} is paused"])
    hard = _boundaries(facts)
    if hard:
        return _verdict("jay", "boundary", hard)
    t = profile.get("target") or {}
    if action == "merge" or (action == "deploy" and facts.get("env") in (None, "live")):
        sp = t.get("self_protection") or {}
        why, missing = _paths(facts, sp.get("require_jay_for_paths") or [], "it changes Command Center's own rails")
        if why:
            return _verdict("jay", "D-007:self_protection", why)
        pd = t.get("personal_data") or {}
        why2, missing2 = _paths(facts, pd.get("trigger_paths") or [], "it touches personal-data code")
        if why2:
            return _verdict("jay", "D-005:personal_data", why2)
        v = _merge(t, facts, profile) if action == "merge" else _deploy(t, facts, profile)
        extra = missing + missing2
        if extra and v["outcome"] == "auto":
            return _verdict("jay", "self_protection:unknown", ["the changed files are not known, so the protected "
                                                               "paths cannot be ruled out"], extra)
        if extra:
            v["missing"] = sorted(set(v["missing"]) | set(extra))
        return v
    return _plan(t, facts)


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
    """The facts the engine reads, from tasks.get() and pipeline.work(). `extra`: what a caller knows besides
    (the PR's changed files at auto-merge time, the deploy env)."""
    ticket, work = ticket or {}, work or {}
    rv = work.get("review") or {}
    f = {"project": ticket.get("project"), "type": ticket.get("type"), "labels": list(ticket.get("labels") or []),
         "flags": list(ticket.get("flags") or []),
         "plan_accepted": work.get("planState") == "accepted",
         "review_at_head": rv.get("verdict") == "APPROVE" and bool(pipeline.SHA_RE.match(str(rv.get("head") or ""))),
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

    def summary(self, since=None, recent=50):
        """Counts per project and action, and the most recent disagreements."""
        since = since if since is not None else 0
        rows = self.db.execute(
            "SELECT project, action, observed, engine, COUNT(*) FROM autonomy_shadow WHERE at >= ? "
            "GROUP BY project, action, observed, engine ORDER BY project, action", (since,)).fetchall()
        counts = {}
        for project, action, obs, eng, n in rows:
            c = counts.setdefault(project, {}).setdefault(action, {"total": 0, "agree": 0, "pairs": {}})
            c["total"] += n
            c["agree"] += n if obs == eng else 0
            c["pairs"][f"{obs}->{eng}"] = n
        missing = {}
        for (m,) in self.db.execute("SELECT missing FROM autonomy_shadow WHERE at >= ? AND missing != '[]'", (since,)):
            for x in json.loads(m):
                missing[x] = missing.get(x, 0) + 1
        dis = [{"id": r[0], "at": r[1], "key": r[2], "project": r[3], "action": r[4], "observed": r[5],
                "engine": r[6], "rule": r[7], "reasons": json.loads(r[8]), "missing": json.loads(r[9])}
               for r in self.db.execute(
                   "SELECT s.id, s.at, t.key, s.project, s.action, s.observed, s.engine, s.rule, s.reasons, s.missing "
                   "FROM autonomy_shadow s LEFT JOIN tickets t ON t.id = s.ticket_id "
                   "WHERE s.agree = 0 AND s.at >= ? ORDER BY s.id DESC LIMIT ?", (since, recent))]
        total = sum(c["total"] for p in counts.values() for c in p.values())
        agree = sum(c["agree"] for p in counts.values() for c in p.values())
        return {"mode": "shadow", "engine": ENGINE_VERSION, "total": total, "agree": agree,
                "disagree": total - agree, "counts": counts, "missing": missing, "disagreements": dis}
