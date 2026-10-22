"""Seeded property check: schema-valid profile variants x fact sets, the engine against the independent oracle.

`problems(seed, n)` returns every distinct case where the engine says "auto" but a hard rule needs Jay, or a
required refusal became anything else. Deterministic for a seed; no I/O beyond reading policy/."""
import copy
import random

from .. import autonomy, profiles
from . import fixtures, oracle

ENUMS = {
    ("merge", "policy"): ("auto", "owner", "release_train", "low-risk"),
    ("deploy", "policy"): ("auto", "release_window", "jay_confirms", "never"),
    ("deploy", "env"): ("live", "preview", "none"),
    ("review", "codex"): ("never", "always", "on_risk_high", "on_plan_package"),
    ("review", "security"): ("never", "always", "on_trigger"),
    ("review", "claude"): ("always", "never"),
}
LISTS = {
    ("merge", "requires"): profiles.CONDITIONS, ("deploy", "requires"): profiles.CONDITIONS,
    ("plan_approval", "required_for"): profiles.PLAN_TRIGGERS,
    ("release", "unattended_when"): profiles.RELEASE_CONDITIONS,
    ("release", "unattended_requires"): profiles.CAPABILITIES,
    ("personal_data", "require_approval_for"): profiles.PERSONAL_DATA,
}


def _facts():
    r = fixtures.ready
    live = dict(env="live", merged=True, verified=True, no_migration=True, no_downtime=True,
                no_client_workflow_change=True, low_blast_radius=True, personal_data=[])
    return [r(), r(env="preview"), r(env="dev"), r(**live), r(personal_data=[]), r(labels=["security"]),
            r(plan_accepted=False), r(files=None), r(verified=False), r(type="SECURITY"), r(labels=["ui"]),
            r(flags=["needs_ui_review"]),
            r(files=[{"path": "db/migrations/1.sql", "changeType": "ADDED", "additions": 1, "deletions": 0}])]


def problems(seed=1, n=2000, policy=None):
    policy = policy or profiles.load()
    rnd = random.Random(seed)
    bases = sorted(policy.profiles) + ["example-restricted"]
    pool = _facts()
    out, checked = {}, 0
    for _ in range(n):
        base = rnd.choice(bases)
        prof = copy.deepcopy(fixtures.profile_for(policy, base))
        if prof is None:
            continue
        t = prof.setdefault("target", {})
        for (k, sub), vals in sorted(ENUMS.items()):
            if rnd.random() < 0.5 and (k not in t or isinstance(t[k], dict)):
                t.setdefault(k, {})[sub] = rnd.choice(vals)
        for (k, sub), vals in sorted(LISTS.items()):
            if rnd.random() < 0.5 and (k not in t or isinstance(t[k], dict)):
                t.setdefault(k, {})[sub] = rnd.sample(list(vals), rnd.randint(0, min(3, len(vals))))
        if rnd.random() < 0.5:
            prof["capabilities"] = {"health_checks": True, "auto_rollback": True}
        if rnd.random() < 0.3:
            prof["mode"] = rnd.choice(profiles.MODES)
        if profiles.validate_profile(prof, policy.decisions, base, base in policy.profiles):
            continue
        facts = dict(copy.deepcopy(rnd.choice(pool)), project=base)
        for action in autonomy.ACTIONS:
            checked += 1
            v = autonomy.evaluate(action, prof, facts)
            req = oracle.requirement(action, prof, facts)
            if (v["outcome"] == "auto" and req["must"]) or (req["must"] == "refuse" and v["outcome"] != "refuse"):
                key = (action, v["rule"], tuple(sorted({c for c, _t in req["why"]})))
                out.setdefault(key, {"action": action, "rule": v["rule"], "why": req["why"][:4],
                                     "target": prof.get("target"), "facts": facts})
    return {"checked": checked, "problems": list(out.values())}
