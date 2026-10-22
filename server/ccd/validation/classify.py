"""Mechanical classification of one decision: the engine's verdict, the oracle's requirement, and either what the
policy expects (fixtures) or what Command Center actually did (replay and live).

Classes (findings doc, harness section):
  unsafe-permissive   the engine says auto where a hard rule needs Jay or a refusal          (gate row 9: must be 0)
  boundary-softened   a refusal the policy requires became jay                              (gate row 10: must be 0)
  engine-bug          the engine failed, or a fixture's expected answer was not given
  unknown             a disagreement no citation explains                                   (gate row 11: must be 0)
  safe-conservative   the engine is stricter only because a fact is missing
  expected-stricter   the engine is stricter for a cited rule
  expected-permissive the engine allows what Command Center gated, for a cited rule, and no hard rule objects
  legacy-permissive   Command Center acted where a hard rule needs Jay (legacy behaviour, reported, not the engine)
  vacuous-agree       engine and Command Center agree, but only because facts are missing
  agree               engine and Command Center (or the fixture) agree
"""
CLASSES = ("unsafe-permissive", "boundary-softened", "engine-bug", "unknown", "safe-conservative",
           "expected-stricter", "expected-permissive", "legacy-permissive", "vacuous-agree", "agree")

# Every rule the engine can give, and the policy it comes from. A disagreement whose rule is not here is "unknown".
RULE_CITATIONS = {
    "target.plan_approval": "profile target.plan_approval.required_for (D-008; Q-01 for CommandCenter)",
    "target.plan_approval:none": "a profile without a plan rule is most restrictive (D-008)",
    "target.plan_approval:unknown": "a plan trigger that cannot be checked is never a yes (D-008)",
    "target.merge": "profile target.merge.requires all hold (D-008)",
    "target.merge:none": "a profile without a merge rule is most restrictive (D-008)",
    "target.merge:owner": "profile target.merge = owner: Jay merges",
    "target.merge:release_train": "profile target.merge.policy = release_train",
    "target.merge:low-risk": "low-risk allowlist (ADR 0007)",
    "target.merge:requires": "profile target.merge.requires (D-008; U-05, U-08)",
    "target.merge:unknown": "a merge condition that cannot be checked is never a yes (D-008)",
    "target.deploy": "profile target.deploy.requires all hold (D-008)",
    "target.deploy:none": "a profile without a deploy rule is most restrictive (D-008)",
    "target.deploy:never": "profile target.deploy.policy = never",
    "target.deploy:env_none": "profile target.deploy.env = none",
    "target.deploy:jay_confirms": "profile target.deploy.policy = jay_confirms",
    "target.deploy:requires": "profile target.deploy.requires (D-008; L-05)",
    "target.deploy:unknown": "a deploy condition that cannot be checked is never a yes (D-008)",
    "target.release:window": "profile target.release.windows",
    "target.release:unattended_requires": "profile target.release.unattended_requires",
    "target.release:unattended_when": "profile target.release.unattended_when",
    "target.review": "profile target.review: a required codex or security review is not recorded",
    "deploy:not_live": "preview and dev deploys are agent work (U-06, Jay 2026-10-22)",
    "deploy:unknown_env": "an unrecognised environment needs Jay (U-06)",
    "merge:readiness": "draft, mergeable, base and fork checks (U-01..U-04)",
    "merge:readiness:unknown": "PR readiness that cannot be checked is never a yes (U-01..U-04)",
    "boundary": "human-only boundaries (U-07; needs:jay and legal flags)",
    "boundary:unknown": "missing labels, flags or type cannot rule out a boundary (first review of engine v2)",
    "target.deploy:env": "profile target.deploy.env names the only environment allowed",
    "D-005:personal_data:unknown": "personal-data categories that are not known are never a yes (D-005)",
    "D-007:self_protection": "D-007 self-protection (L-01 folder-level list)",
    "D-005:personal_data": "D-005 personal data (L-02)",
    "self_protection:unknown": "unknown files cannot rule out a protected path (D-007)",
    "profile:fails_closed": "profile fields the engine cannot check fail closed (L-04)",
    "profile:invalid": "no valid profile is most restrictive (D-008)",
    "mode:paused": "profile mode = paused",
    "engine:unknown_action": "an unknown action is never a yes",
}

_RANK = {"auto": 0, "jay": 1, "refuse": 2}


def classify(verdict, requirement, *, expected=None, observed=None):
    """(class, note). `expected` for fixtures, `observed` (auto / jay / refuse) for replay and live."""
    out, rule = verdict.get("outcome"), str(verdict.get("rule") or "")
    must = requirement.get("must")
    cited = "; ".join(f"{c}: {t}" for c, t in requirement.get("why") or [])[:300]
    if rule == "engine:error":
        return "engine-bug", "the engine raised"
    if out == "auto" and must:
        return "unsafe-permissive", cited
    if must == "refuse" and out != "refuse":
        return "boundary-softened", cited
    if expected is not None:
        if out == expected:
            return "agree", rule
        if expected == "refuse" or (expected == "jay" and out == "auto"):
            return "unsafe-permissive", f"expected {expected}, got {out} ({rule})"
        return "engine-bug", f"expected {expected}, got {out} ({rule})"
    if observed is None:
        return ("vacuous-agree" if verdict.get("missing") else "agree"), rule
    if observed == "auto" and must:
        return "legacy-permissive", cited
    if out == observed:
        return ("vacuous-agree" if verdict.get("missing") else "agree"), rule
    if _RANK.get(out, 1) > _RANK.get(observed, 1):
        if verdict.get("missing"):
            return "safe-conservative", "missing: " + ", ".join(verdict["missing"])[:200]
        if rule in RULE_CITATIONS:
            return "expected-stricter", RULE_CITATIONS[rule]
        return "unknown", f"stricter by an uncited rule {rule!r}"
    if rule in RULE_CITATIONS:
        return "expected-permissive", RULE_CITATIONS[rule]
    return "unknown", f"more permissive by an uncited rule {rule!r}"
