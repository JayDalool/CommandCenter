"""Project Operating Profiles: how much autonomy each project has (policy/README.md, v2 Phase 1).

    policy/projects/<key>.toml    one profile per registered project
    policy/decisions/D-NNN.toml   Jay's policy decisions, cited by profiles
    policy/examples/*.toml        validated, never loaded as a project

A profile has two halves. `[enforced]` is what Command Center does TODAY; it must equal ccd/registry.py, and
`drift()` reports any difference (the registry still drives behaviour, unchanged). `[target]` is the policy Jay
decided; nothing here enforces it. The Autonomy Engine reads it in shadow mode (decision D-008).

Loading never raises: a file that cannot be read or does not match SCHEMA is reported with every error and its
profile is `valid: False` (the engine treats an invalid profile as the most restrictive). Unknown sections and
keys are errors, so a typo never silently means "no rule". Every file's SHA-256 is recorded, and `fingerprint`
covers all of them, so any change to policy is visible in the audit trail.

TOML is read with the standard library's `tomllib`: ccd gains no dependency. Pure apart from `load()` reading
the folder; `validate_*` take plain dicts.
"""
import datetime
import hashlib
import re
import tomllib
from pathlib import Path

from . import registry

POLICY_DIR = Path(__file__).resolve().parents[2] / "policy"
SCHEMA_VERSION = 1

MODES = ("experimental_autonomy", "autonomous_product", "controlled_production", "restricted", "paused")
LEARNING = ("off", "contextual", "deep")
DECISION_RE = re.compile(r"^D-\d{3}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
GLOB_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\s\\]*[^/\s\\]$")   # repo-relative, not ending in "/"
WINDOW_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([01]\d|2[0-3]):[0-5]\d [A-Za-z]+(?:/[A-Za-z_]+)+$")

CONDITIONS = ("ci_green", "review_approved_at_head", "risk_at_most_medium", "security_pass_if_required",
              "no_personal_data_trigger", "plan_approved_if_required", "merged", "verify_pass", "health_ok",
              "auto_rollback")
PLAN_TRIGGERS = ("always", "risk_high", "risk_at_least_medium", "ui_change_major", "ui_change_client_visible",
                 "workflow_change", "api_change", "migration")
RELEASE_CONDITIONS = ("risk_low", "no_migration", "no_meaningful_downtime", "low_blast_radius",
                      "no_client_workflow_change")
PERSONAL_DATA = ("data_model_change", "retention", "privacy", "encryption", "deletion",
                 "health_or_personal_data_handling", "authentication", "irreversible_migration")
HUMAN_ACTIONS = ("change_policy", "change_agent_permissions")
NODES = ("server", "laptop", "gpu", "cloud")
CAPABILITIES = ("health_checks", "auto_rollback")


# A tiny declarative schema: each value is a checker (value) -> error text or None.
def _enum(*allowed):
    return lambda v: None if isinstance(v, str) and v in allowed else f"must be one of {', '.join(allowed)}"


def _list_of(*allowed):
    def check(v):
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return "must be a list of strings"
        bad = [x for x in v if allowed and x not in allowed]
        if bad:
            return f"unknown value(s) {', '.join(bad)}; allowed: {', '.join(allowed)}"
        if len(set(v)) != len(v):
            return "has duplicates"
        return None
    return check


def _strings(pattern=None, limit=40):
    def check(v):
        if not isinstance(v, list) or len(v) > limit or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in v):
            return f"must be a list of at most {limit} short strings"
        if pattern is not None:
            bad = [x for x in v if not pattern.match(x)]
            if bad:
                return f"badly formed: {', '.join(bad)}"
        return None
    return check


def _bool(v):
    return None if isinstance(v, bool) else "must be true or false"


def _text(limit=200):
    return lambda v: None if isinstance(v, str) and len(v) <= limit else f"must be text of at most {limit} characters"


def _int(lo, hi):
    return lambda v: None if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else \
        f"must be a whole number from {lo} to {hi}"


ENFORCED = {
    "merge": _enum("owner", "low-risk"),
    "night": _enum("normal", "careful"),
    "paused": _text(),
    "max_lanes": _int(1, 8),
    "ui_fix": _enum("ask", "auto"),
}
TARGET = {
    "plan_approval": {"required_for": _list_of(*PLAN_TRIGGERS), "package": _enum("none", "standard", "full"),
                      "reviewers": _list_of("claude", "codex")},
    "review": {"claude": _enum("always", "never"),
               "codex": _enum("never", "always", "on_risk_high", "on_plan_package"),
               "security": _enum("never", "always", "on_trigger")},
    "merge": {"policy": _enum("auto", "owner", "release_train", "low-risk"), "requires": _list_of(*CONDITIONS)},
    "deploy": {"policy": _enum("auto", "release_window", "jay_confirms", "never"),
               "env": _enum("live", "preview", "none"), "requires": _list_of(*CONDITIONS)},
    "release": {"windows": _strings(WINDOW_RE, 14), "unattended_when": _list_of(*RELEASE_CONDITIONS),
                "unattended_requires": _list_of(*CAPABILITIES),
                "otherwise": _enum("prepare_and_hold_for_jay"), "client_note": _enum("required", "optional", "none")},
    "personal_data": {"require_approval_for": _list_of(*PERSONAL_DATA),
                      "auto_allowed": _enum("reversible_tested_fix_on_existing_personal_data", "none"),
                      "trigger_paths": _strings(GLOB_RE)},
    "small_safe_changes": {"batch": _bool, "max_risk": _enum("low")},
    "constraints": {"never": _strings()},
    "notify": {"release": _enum("concise", "summary", "none"),
               "needs_you": _enum("slack_immediate", "slack_titles_redacted", "ui_only")},
    "self_protection": {"require_jay_for_paths": _strings(GLOB_RE), "require_jay_for_actions": _list_of(*HUMAN_ACTIONS)},
    "execution": {"allowed_nodes": _list_of(*NODES), "preferred_node": _enum(*NODES),
                  "repo_storage": _enum("server", "laptop_only"),
                  "server_clone": _enum("allowed", "requires_jay", "prohibited"),
                  "secrets": _enum("server_scoped", "laptop_only"),
                  "model_providers": _list_of("anthropic", "openai")},
    "artifacts": {"store": _enum("server", "laptop_only"),
                  "drive_mirror": _enum("never", "releases_only", "plan_packages_and_releases"),
                  "control_plane_metadata": _list_of("title", "status", "hash", "size")},
}
TOP = {"schema", "project", "mode", "decisions", "learning", "enforced", "target", "capabilities"}
DECISION_KEYS = {"id": _text(8), "schema": _int(1, 1), "date": _text(10), "decided_by": _enum("jay"),
                 "source": _text(300), "projects": _strings(), "question": _text(400), "decision": _text(2000),
                 "rationale": _text(800), "rules": _strings(limit=20), "reconsider": _text(300),
                 "supersedes": _text(8)}
DECISION_REQUIRED = ("id", "schema", "date", "decided_by", "projects", "question", "decision", "rationale")


def _check_table(where, table, spec, errors, required=()):
    if not isinstance(table, dict):
        errors.append(f"{where} must be a table")
        return
    for k in required:
        if k not in table:
            errors.append(f"{where}.{k} is missing")
    for k, v in table.items():
        if k not in spec:
            errors.append(f"{where}.{k} is not a known key")
            continue
        rule = spec[k]
        if isinstance(rule, dict):
            _check_table(f"{where}.{k}", v, rule, errors)
        else:
            why = rule(v)
            if why:
                errors.append(f"{where}.{k} {why}")


def validate_decision(d, name=None):
    """Errors in one decision record (a plain dict), as short sentences."""
    errors = []
    if not isinstance(d, dict):
        return ["the decision is not a table"]
    _check_table("decision", d, DECISION_KEYS, errors, DECISION_REQUIRED)
    if isinstance(d.get("id"), str) and not DECISION_RE.match(d["id"]):
        errors.append("decision.id must look like D-001")
    if name and d.get("id") != name:
        errors.append(f"decision.id {d.get('id')!r} does not match its file name {name}")
    if "supersedes" in d and not DECISION_RE.match(str(d["supersedes"])):
        errors.append("decision.supersedes must name a decision like D-001")
    try:
        datetime.date.fromisoformat(d["date"]) if isinstance(d.get("date"), str) else None
    except ValueError:
        errors.append("decision.date must be a date like 2026-10-21")
    if isinstance(d.get("projects"), list):
        bad = [x for x in d["projects"] if x not in registry.PROJECTS and x not in ("all", "restricted")]
        if bad:
            errors.append(f"decision.projects names unknown project(s) {', '.join(map(str, bad))}")
    return errors


def validate_profile(p, decisions=None, name=None, registered=True):
    """Errors in one profile (a plain dict). `decisions`: id → decision dict, to check what the profile cites.
    `registered`: the profile must belong to a registry project (False for policy/examples)."""
    errors = []
    if not isinstance(p, dict):
        return ["the profile is not a table"]
    for k in p:
        if k not in TOP:
            errors.append(f"{k} is not a known section or key")
    for k in TOP:
        if k not in p:
            errors.append(f"{k} is missing")
    if errors:
        return errors
    if p["schema"] != SCHEMA_VERSION:
        errors.append(f"schema must be {SCHEMA_VERSION}")
    key = p["project"]
    if not isinstance(key, str) or not KEY_RE.match(key):
        errors.append("project must be a lower-case project key")
    elif name and key != name:
        errors.append(f"project {key!r} does not match its file name {name}")
    elif registered and key not in registry.PROJECTS:
        errors.append(f"project {key} has no row in ccd/registry.py")
    if p["mode"] not in MODES:
        errors.append(f"mode must be one of {', '.join(MODES)}")
    if p["learning"] not in LEARNING:
        errors.append(f"learning must be one of {', '.join(LEARNING)}")
    why = _strings(DECISION_RE, 50)(p["decisions"])
    if why:
        errors.append(f"decisions {why}")
    elif len(set(p["decisions"])) != len(p["decisions"]):
        errors.append("decisions has duplicates")
    elif decisions is not None:
        for d in p["decisions"]:
            rec = decisions.get(d)
            if rec is None:
                errors.append(f"decisions: {d} does not exist in policy/decisions")
                continue
            if rec.get("valid") is False:
                errors.append(f"decisions: {d} is itself invalid")
                continue
            scope = rec.get("projects") if isinstance(rec.get("projects"), list) else []
            if not ("all" in scope or key in scope or (p["mode"] == "restricted" and "restricted" in scope)):
                errors.append(f"decisions: {d} does not apply to {key}")
    _check_table("enforced", p["enforced"], ENFORCED, errors, tuple(ENFORCED))
    _check_table("target", p["target"], TARGET, errors)
    _check_table("capabilities", p["capabilities"], {c: _bool for c in CAPABILITIES}, errors, CAPABILITIES)
    if errors:
        return errors
    # Rules across sections.
    t, enf = p["target"], p["enforced"]
    for section in ("merge", "deploy"):
        if section in t and "policy" not in t[section]:
            errors.append(f"target.{section}.policy is missing")
    if p["mode"] == "paused":
        if not enf["paused"]:
            errors.append("a paused profile needs enforced.paused (the reason)")
        if t:
            errors.append("a paused profile has no target policy until Jay decides one")
    elif enf["paused"]:
        errors.append(f"enforced.paused is set but mode is {p['mode']}, not paused")
    ex = t.get("execution") or {}
    if ex.get("preferred_node") and ex.get("allowed_nodes") and ex["preferred_node"] not in ex["allowed_nodes"]:
        errors.append("target.execution.preferred_node is not in allowed_nodes")
    if p["mode"] == "restricted":
        if ex.get("allowed_nodes") != ["laptop"] or ex.get("repo_storage") != "laptop_only" \
                or ex.get("secrets") != "laptop_only" or ex.get("server_clone") == "allowed":
            errors.append("a restricted profile keeps nodes, repo storage and secrets laptop-only and never allows "
                          "a server clone without Jay (D-002)")
        if (t.get("artifacts") or {}).get("store") != "laptop_only":
            errors.append("a restricted profile stores artifacts on the laptop only")
    for flag in (t.get("release") or {}).get("unattended_requires") or ():
        if flag not in p["capabilities"]:
            errors.append(f"target.release.unattended_requires names an unknown capability {flag}")
    return errors


def _read(path):
    raw = path.read_bytes()
    return raw, hashlib.sha256(raw).hexdigest(), tomllib.loads(raw.decode("utf-8"))


def enforced_now(key):
    """What the registry makes Command Center do today, in the shape of a profile's [enforced] section."""
    from . import pipeline   # import here: pipeline imports registry, profiles is imported early
    pol = registry.pipeline_of(key)
    # The registry's raw value: a value the pipeline does not know (it treats it as "owner") still shows as drift.
    return {"merge": pol.get("merge", "owner"),
            "night": registry.night_mode(key), "paused": registry.paused(key) or "",
            "max_lanes": int(pol.get("max_lanes") or pipeline.MAX_LANES), "ui_fix": registry.ui_fix(key)}


def drift(key, profile):
    """Where a profile's [enforced] section disagrees with the registry: [{field, profile, registry}]."""
    if not profile or not isinstance(profile.get("enforced"), dict):
        return []
    now = enforced_now(key)
    return [{"field": f, "profile": profile["enforced"].get(f), "registry": v}
            for f, v in now.items() if profile["enforced"].get(f) != v]


class Policy:
    """Everything under policy/, read once. `profiles[key]` = {profile, file, sha256, valid, errors, drift}."""

    def __init__(self, root=POLICY_DIR):
        self.root = Path(root)
        self.decisions, self.profiles, self.examples, self.errors = {}, {}, {}, []
        self._load()

    def _load(self):
        hashes = []
        for path in sorted((self.root / "decisions").glob("*.toml")):
            try:
                _, sha, d = _read(path)
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                self.errors.append(f"decisions/{path.name}: cannot read ({type(e).__name__}: {e})")
                continue
            hashes.append((f"decisions/{path.name}", sha))
            try:
                errs = validate_decision(d, path.stem)
            except Exception as e:  # noqa: BLE001 — a validator bug must never stop ccd starting
                errs = [f"cannot validate ({type(e).__name__})"]
            if errs:
                self.errors += [f"decisions/{path.name}: {e}" for e in errs]
            self.decisions[path.stem] = dict(d, sha256=sha, valid=not errs, errors=errs)
        for k, d in self.decisions.items():
            sup = d.get("supersedes")
            if d["valid"] and sup is not None and sup not in self.decisions:
                d["valid"], d["errors"] = False, [f"decision.supersedes names {sup}, which does not exist"]
                self.errors.append(f"decisions/{k}.toml: {d['errors'][0]}")
        for folder, out, registered in (("projects", self.profiles, True), ("examples", self.examples, False)):
            for path in sorted((self.root / folder).glob("*.toml")):
                rec = {"file": f"policy/{folder}/{path.name}", "profile": None, "sha256": None}
                try:
                    _, rec["sha256"], rec["profile"] = _read(path)
                    rec["errors"] = validate_profile(rec["profile"], self.decisions, path.stem, registered)
                except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                    rec["errors"] = [f"cannot read ({type(e).__name__}: {e})"]
                except Exception as e:  # noqa: BLE001 — a validator bug must never stop ccd starting
                    rec["errors"] = [f"cannot validate ({type(e).__name__})"]
                rec["valid"] = not rec["errors"]
                rec["drift"] = drift(path.stem, rec["profile"]) if registered and rec["valid"] else []
                if rec["sha256"]:
                    hashes.append((rec["file"][len("policy/"):], rec["sha256"]))
                out[path.stem] = rec
        for key in registry.PROJECTS:
            if key not in self.profiles:
                self.errors.append(f"projects/{key}.toml is missing: every registered project needs a profile")
        self.fingerprint = hashlib.sha256("\n".join(f"{n} {h}" for n, h in sorted(hashes)).encode()).hexdigest()

    def profile(self, key):
        """The valid profile of a project, or None (missing or invalid: the engine treats that as most restrictive)."""
        rec = self.profiles.get(key)
        return rec["profile"] if rec and rec["valid"] else None

    def problems(self):
        """Every load error, invalid profile and drift, as short sentences (empty when policy is healthy)."""
        out = list(self.errors)
        for key, rec in self.profiles.items():
            out += [f"{rec['file']}: {e}" for e in rec["errors"]]
            out += [f"{rec['file']}: enforced.{d['field']} is {d['profile']!r} but the registry says {d['registry']!r}"
                    for d in rec["drift"]]
        for key, rec in self.examples.items():
            out += [f"{rec['file']}: {e}" for e in rec["errors"]]
        return out

    def summary(self):
        """For GET /api/profiles and Settings → Policies. Read-only; holds no secret. Always JSON-safe, even for
        an invalid file (a TOML date or time becomes its ISO text)."""
        return _plain({
            "fingerprint": self.fingerprint,
            "problems": self.problems(),
            "projects": {k: {"name": registry.name_of(k), "file": r["file"], "sha256": r["sha256"], "valid": r["valid"], "errors": r["errors"],
                             "drift": r["drift"], "mode": (r["profile"] or {}).get("mode"),
                             "decisions": (r["profile"] or {}).get("decisions") or [],
                             "learning": (r["profile"] or {}).get("learning"),
                             "enforced": (r["profile"] or {}).get("enforced") or {},
                             "target": (r["profile"] or {}).get("target") or {},
                             "capabilities": (r["profile"] or {}).get("capabilities") or {}}
                         for k, r in sorted(self.profiles.items())},
            "decisions": {k: {f: d.get(f) for f in ("id", "date", "decided_by", "projects", "question", "decision",
                                                    "rationale", "rules", "reconsider", "supersedes", "valid")}
                          for k, d in sorted(self.decisions.items())},
        })


def _plain(v):
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def load(root=POLICY_DIR):
    return Policy(root)
