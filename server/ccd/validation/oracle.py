"""An independent statement of the hard rules: what must be true before the target policy may say "auto".

This is deliberately NOT the engine. It is written from the agreed policy (profiles, D-005, D-007, D-008, Jay's
2026-10-22 decisions) without calling any autonomy.py helper, so a bug in the engine shows up as a disagreement
instead of being copied. It only ever answers "auto is not allowed, because …" (with a citation) or nothing.
It never says "auto": a clean oracle result only means none of these rules forbid it.

`requirement(action, profile, facts)` → {"must": None | "jay" | "refuse", "why": [(citation, text)]}.
"""
import re

from .. import merge_policy

SHA = re.compile(r"^[0-9a-f]{40}$")
BOUNDARY = {"destructive", "financial", "paid", "secrets", "credentials", "irreversible", "legal"}
RAISES_RISK = {"security", "migration", "destructive", "architecture", "financial", "legal", "risk:high"}
LIVE, NON_LIVE = {"live"}, {"preview", "dev"}

# Where each rule comes from. Every citation the oracle can give is listed here.
CITATIONS = {
    "O-PROFILE": "No valid profile: most restrictive (profiles.py; D-008).",
    "O-PAUSED": "A paused project refuses every action (profile mode = paused).",
    "O-RESTRICTED": "A restricted project needs Jay for every decision (L-04, Jay 2026-10-22).",
    "O-NEVER": "constraints.never cannot be checked by the engine, so merge and deploy need Jay (L-04).",
    "O-UNREADABLE": "Labels, flags or type that are missing or cannot be read cannot rule out a boundary (U-07).",
    "O-BOUNDARY": "Destructive, financial, paid, secrets, credentials, irreversible and legal work is human-only (U-07).",
    "O-FLAG": "A ticket flagged needs:jay or needs:legal needs Jay.",
    "O-READY": "An unattended merge needs an open PR that is not a draft, MERGEABLE, based on main, from this repo "
               "(U-01..U-04).",
    "O-HEAD": "The approving review must be for the PR's current head (U-05).",
    "O-CI": "CI must be green with at least one passing check (U-08).",
    "O-MERGE-POLICY": "The project's target merge policy does not allow an agent merge.",
    "O-FILES": "Unknown, partial, renamed or deleted file lists cannot rule out a protected path.",
    "O-RAILS": "Changes to Command Center's own rails need Jay (D-007; L-01 folder-level list).",
    "O-PERSONAL": "Personal-data paths and categories need Jay (D-005; L-02).",
    "O-ENV": "A deploy to an environment other than live, preview or dev, or one the profile does not name, needs "
             "Jay (U-06).",
    "O-DEPLOY-NEVER": "A project whose deploy policy is never, or allows no environment, refuses every deploy.",
    "O-LIVE": "An unattended live deploy needs every required condition, health checks, rollback, and no "
              "migration, downtime or client workflow change (L-05).",
    "O-REVIEW": "A codex or security review the profile requires must be recorded first.",
    "O-PLAN": "A plan trigger in the profile applies, or cannot be ruled out (Q-01: high risk in CommandCenter).",
}


def _as_set(v):
    return {str(x).strip().lower() for x in v} if isinstance(v, (list, tuple, set)) else set()


def _glob_re(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return ("^" if "/" in pattern else "^(?:.*/)?") + out + "$"


def _odd(path):
    return (not isinstance(path, str) or not path or path.startswith(("/", "./")) or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/")) or any(c.isspace() for c in path))


def protected(path, patterns):
    """`path` is covered by one of `patterns`; an odd path always counts as covered."""
    return _odd(path) or any(re.match(_glob_re(str(p)), path) for p in patterns or ())


def _files(facts, patterns, cite, what, why):
    files = facts.get("files")
    if not patterns:
        return
    if not isinstance(files, list) or len(files) >= 100:
        why.append(("O-FILES", f"{what}: the changed files are not fully known"))
        return
    for f in files:
        path = f.get("path") if isinstance(f, dict) else f
        if isinstance(f, dict) and f.get("changeType") not in (None, "ADDED", "MODIFIED"):
            why.append(("O-FILES", f"{what}: {path!r} is renamed, copied or deleted"))
        elif protected(path, patterns):
            why.append((cite, f"{what}: {path!r}"))


def requirement(action, profile, facts):
    facts = facts if isinstance(facts, dict) else {}
    why = []

    def done(must):
        return {"must": must if why or must == "refuse" else None, "why": why}

    if not isinstance(profile, dict):
        why.append(("O-PROFILE", "no valid profile"))
        return done("jay")
    if profile.get("mode") == "paused":
        why.append(("O-PAUSED", "the project is paused"))
        return done("refuse")
    t = profile.get("target") or {}
    dep = t.get("deploy") if isinstance(t.get("deploy"), dict) else {}
    if action == "deploy" and (dep.get("policy") == "never" or dep.get("env") == "none"):
        why.append(("O-DEPLOY-NEVER", "this project is never deployed by an agent"))
        return done("refuse")
    if action not in ("plan", "merge", "deploy"):
        why.append(("O-PROFILE", f"unknown action {action!r}"))
        return done("jay")
    if profile.get("mode") == "restricted":
        why.append(("O-RESTRICTED", "the project is restricted"))
    never = (t.get("constraints") or {}).get("never") if isinstance(t.get("constraints"), dict) else None
    if never and action in ("merge", "deploy"):
        why.append(("O-NEVER", "the profile has constraints.never"))
    for key in ("labels", "flags"):
        v = facts.get(key)
        if not isinstance(v, (list, tuple, set)) or not all(isinstance(x, str) for x in v):
            why.append(("O-UNREADABLE", f"{key} missing or cannot be read"))
    if "type" not in facts or not isinstance(facts.get("type"), (str, type(None))):
        why.append(("O-UNREADABLE", "type missing or cannot be read"))
    labels, flags = _as_set(facts.get("labels")), _as_set(facts.get("flags"))
    typ = str(facts.get("type") or "").strip().upper()
    if labels & BOUNDARY or typ == "LEGAL":
        why.append(("O-BOUNDARY", ", ".join(sorted(labels & BOUNDARY)) or "type LEGAL"))
    flags |= {x.replace(":", "_") for x in labels if x in ("needs:jay", "needs:legal")}
    if flags & {"needs_jay", "needs_legal"}:
        why.append(("O-FLAG", ", ".join(sorted(flags & {"needs_jay", "needs_legal"}))))
    high = bool(labels & RAISES_RISK) or typ in ("SECURITY", "LEGAL")
    files = facts.get("files")
    low = bool(facts.get("project")) and isinstance(files, list) and bool(files) and not merge_policy.file_reasons(
        facts["project"], files, facts.get("additions"), facts.get("deletions"))

    if action == "plan":
        pa = t.get("plan_approval")
        triggers = pa.get("required_for") if isinstance(pa, dict) else None
        if not isinstance(pa, dict):
            why.append(("O-PLAN", "no plan approval rule"))
        for trig in triggers or ():
            if trig == "always":
                why.append(("O-PLAN", "every plan needs Jay"))
            elif trig in ("risk_high", "risk_at_least_medium") and (high or not low):
                why.append(("O-PLAN", f"{trig}: the risk is high or not known to be low"))
            elif trig == "migration" and "migration" in labels:
                why.append(("O-PLAN", "a migration"))
            elif trig in ("ui_change_major", "ui_change_client_visible", "workflow_change", "api_change"):
                why.append(("O-PLAN", f"{trig} cannot be ruled out"))
            elif trig not in ("risk_high", "risk_at_least_medium", "migration"):
                why.append(("O-PLAN", f"unknown trigger {trig!r}"))
        return done("jay")

    sp = t.get("self_protection") if isinstance(t.get("self_protection"), dict) else {}
    pd = t.get("personal_data") if isinstance(t.get("personal_data"), dict) else {}
    if action == "deploy":
        env = facts.get("env")
        env = "live" if env is None else str(env).strip().lower()
        if env not in LIVE | NON_LIVE or dep.get("env") not in (None, "live", env):
            why.append(("O-ENV", f"environment {facts.get('env')!r}"))
            return done("jay")
        if env in NON_LIVE:
            return done("jay")
        _files(facts, sp.get("require_jay_for_paths"), "O-RAILS", "Command Center's rails", why)
        _files(facts, pd.get("trigger_paths"), "O-PERSONAL", "personal-data code", why)
        _categories(facts, pd, why)
        caps = profile.get("capabilities") or {}
        if dep.get("policy") != "auto" or dep.get("jay_confirms"):
            why.append(("O-LIVE", f"deploy policy {dep.get('policy')!r}"))
        need = list(dep.get("requires") or [])
        rh, ph = facts.get("review_head"), facts.get("pr_head")
        ok = {"merged": facts.get("merged") is True, "verify_pass": facts.get("verified") is True,
              "health_ok": caps.get("health_checks") is True, "auto_rollback": caps.get("auto_rollback") is True,
              "ci_green": facts.get("ci") == "green" and facts.get("ci_passed") is not False,
              "review_approved_at_head": facts.get("review_at_head") is True and isinstance(rh, str)
              and isinstance(ph, str) and bool(SHA.fullmatch(rh)) and rh == ph,
              "risk_at_most_medium": not high and low,
              "security_pass_if_required": not (typ == "SECURITY" or "security" in labels),
              "no_personal_data_trigger": True,      # checked by the personal-data paths and categories below
              "plan_approved_if_required": facts.get("plan_accepted") is True}
        for c in need:
            if not ok.get(c, False):
                why.append(("O-LIVE", f"{c} does not hold"))
        for fact in ("no_migration", "no_downtime", "no_client_workflow_change"):
            if facts.get(fact) is not True:
                why.append(("O-LIVE", f"{fact} is not known to hold"))
        rel = t.get("release") if isinstance(t.get("release"), dict) else {}
        for c in rel.get("unattended_requires") or ():
            if caps.get(c) is not True:
                why.append(("O-LIVE", f"release needs {c}"))
        when = {"risk_low": not high and low, "no_migration": facts.get("no_migration") is True,
                "no_meaningful_downtime": facts.get("no_downtime") is True,
                "no_client_workflow_change": facts.get("no_client_workflow_change") is True,
                "low_blast_radius": facts.get("low_blast_radius") is True}
        for c in rel.get("unattended_when") or ():
            if not when.get(c, False):
                why.append(("O-LIVE", f"release condition {c} is not known to hold"))
        return done("jay")

    # merge
    mp = t.get("merge") if isinstance(t.get("merge"), dict) else {}
    if mp.get("policy") not in ("auto", "low-risk"):
        why.append(("O-MERGE-POLICY", f"merge policy {mp.get('policy') if mp else t.get('merge')!r}"))
    if mp.get("policy") == "low-risk" and not low:
        why.append(("O-MERGE-POLICY", "not every file is on the low-risk allowlist"))
    if "risk_at_most_medium" in (mp.get("requires") or ()) and (high or not low):
        why.append(("O-MERGE-POLICY", "the risk is high or not known"))
    if facts.get("state") != "OPEN":
        why.append(("O-READY", f"state is {facts.get('state')!r}"))
    if facts.get("draft") is not False:
        why.append(("O-READY", "the PR may be a draft"))
    if facts.get("mergeable") != "MERGEABLE":
        why.append(("O-READY", f"mergeable is {facts.get('mergeable')!r}"))
    if facts.get("base") != "main":
        why.append(("O-READY", f"base is {facts.get('base')!r}"))
    if facts.get("cross_repo") is not False:
        why.append(("O-READY", "the PR may come from a fork"))
    rh, ph = facts.get("review_head"), facts.get("pr_head")
    if facts.get("review_at_head") is not True or not (isinstance(rh, str) and isinstance(ph, str)
                                                       and SHA.match(rh) and rh == ph):
        why.append(("O-HEAD", "no approving review for the PR's current head"))
    if not (facts.get("ci") == "green" and facts.get("ci_passed") is True):
        why.append(("O-CI", f"ci {facts.get('ci')!r}, passed {facts.get('ci_passed')!r}"))
    rv = t.get("review") if isinstance(t.get("review"), dict) else {}
    for who in ("codex", "security"):
        v = rv.get(who, "never")
        if v == "on_risk_high" and (high or not low):
            why.append(("O-REVIEW", f"{who} review on high or unknown risk"))
        elif v == "on_trigger" and (typ == "SECURITY" or "security" in labels):
            why.append(("O-REVIEW", f"{who} review is triggered"))
        elif v not in ("never", "on_risk_high", "on_trigger"):
            why.append(("O-REVIEW", f"{who} review {v!r}"))
    _files(facts, sp.get("require_jay_for_paths"), "O-RAILS", "Command Center's rails", why)
    _files(facts, pd.get("trigger_paths"), "O-PERSONAL", "personal-data code", why)
    _categories(facts, pd, why)
    return done("jay")


def _categories(facts, pd, why):
    cats = _as_set(pd.get("require_approval_for"))
    if cats:
        got = facts.get("personal_data")
        if not isinstance(got, (list, tuple, set)) or _as_set(got) & cats:
            why.append(("O-PERSONAL", "personal-data categories are touched or not known"))
