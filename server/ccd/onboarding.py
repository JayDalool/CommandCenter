"""Agent and project onboarding: GROUNDWORK ONLY (D-024, proposed; tasks.db migration 10).

Jay (2026-10-23): build the policy-independent parts behind a disabled feature flag: agent registration records,
onboarding drafts, validation, audit trails and read-only APIs. Do not grant permissions, start agents, or enforce
a proposed policy as if it were approved. So this module stores and checks records, and decides nothing:

    drafts          an agent or project draft kept on the server while Jay works on it; reserves nothing
    registration    an agent's identity record: immutable `agent:<slug>` ID, status `registered` or `retired`, and
                    an append-only configuration version (role, model, budget, the permissions it REQUESTS)
    validation      the prototype's rules (design/ui-prototypes/engineering-hq/src/data/validate.ts), server-side:
                    ID format, reserved and retired IDs, duplicates, look-alike names, secrets refused, requested
                    permissions within each permission's hard ceiling, known projects and repositories
    events          one append-only `onboarding_events` row per change, in the same transaction; the HTTP write
                    itself is also in the hash-chained audit trail (ccd/audit.py), like every write

What it never does: there is no "active" status, no grant table and no credential. Registering an agent issues no
actor token, starts no session and changes nothing any other part of ccd reads. Requested permissions are data for
Jay to review; the Capability Broker does not read them. Project drafts cannot become projects here: the registry
stays code (ccd/registry.py) and a profile is a PR for Jay (D-007).

Off by default: `config.json` `"onboarding_groundwork": true` turns the routes on (read once at start). Every write
needs Jay with Developer Unlock (checked in daemon.py); any agent actor is refused here as well.
"""
import contextlib
import hashlib
import json
import re
import secrets
import time

from . import registry

OFF_MESSAGE = "onboarding groundwork is off (config.json onboarding_groundwork)"
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
NAME_RE = re.compile(r"^[^\W\d_](?:[^\W_]|[ .'-]){0,31}$")
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
DRAFT_RE = re.compile(r"^d-[0-9a-f]{12}$")
MAX_BODY = 32 * 1024          # bytes of JSON per draft
MAX_OPEN_DRAFTS = 25
KINDS = ("agent", "project")

# The same lists the prototype uses (src/data/catalog.ts). An ID here can never be an agent's.
RESERVED_IDS = ("jay", "admin", "root", "system", "ccd", "owner", "coordinator", "commandcenter", "all", "everyone",
                "unknown", "null", "undefined", "agent", "new", "bot", "server")
RESERVED_NAMES = ("jay", "commandcenter", "command center", "system", "admin")
PROVIDERS = {"anthropic": ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"), "openai": ("gpt-5-codex",)}
REASONING = ("low", "medium", "high", "max")
PROJECT_TYPES = ("personal", "client", "employer", "infra")
GRANTS = ("deny", "approval", "allow")
# permission → the most any agent setting can ever reach. Mirrors the prototype's PERMISSIONS. Requested
# permissions above a ceiling are refused; nothing here grants even what is within it.
CEILINGS = {
    "repo.read": "allow", "repo.branch": "allow", "repo.worktree": "allow", "repo.commit": "allow",
    "repo.push": "allow", "repo.pr": "allow", "repo.merge": "deny",
    "run.tests": "allow", "run.dev": "allow", "run.terminal": "allow", "run.browser": "allow", "run.ci": "approval",
    "prod.observe": "allow", "prod.diagnose": "approval", "prod.restart": "approval", "prod.deploy": "approval",
    "prod.rollback": "approval", "prod.browser_write": "deny",
    "data.dev_read": "allow", "data.dev_write": "approval", "data.prod": "deny",
    "infra.runners": "deny", "infra.dns": "deny", "infra.hosting": "deny", "infra.secrets": "deny",
    "infra.provision": "deny",
}
AGENT_KEYS = {"id", "name", "title", "spec", "template", "model", "requested", "budget", "projects", "reportsTo",
              "notes"}
PROJECT_KEYS = {"key", "name", "prefix", "repo", "type", "lead", "notes"}
BUDGET_KEYS = {"dailyUsd": 100_000, "monthlyUsd": 1_000_000, "monthlyTokens": 10 ** 12}

# Tokens, keys, passwords and credential URLs: the prototype's SECRET_RE. A draft that holds one is refused whole,
# so a secret is never stored, not even scrubbed.
SECRET_RE = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{10,}|\bsk-[A-Za-z0-9_-]{12,}|xox[abpr]-[A-Za-z0-9-]{8,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"
    r"|\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{4,})", re.IGNORECASE)


class OnboardingError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _clean(text, n):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or "")).strip()[:n]


def _norm(name):
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _dist(a, b):
    """Edit distance, for "these two names are easy to confuse"."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def secret_paths(value, path="body"):
    """Where in a JSON value something looks like a credential (keys and values both)."""
    out = []
    if isinstance(value, str):
        if SECRET_RE.search(value):
            out.append(path)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += secret_paths(v, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, v in value.items():
            if SECRET_RE.search(str(k)):
                out.append(f"{path}.<key>")
            out += secret_paths(v, f"{path}.{k}")
    return out


def _slug_of(agent_id):
    s = str(agent_id or "")
    return s[6:] if s.startswith("agent:") else s


class Issues:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, field, code, message):
        self.errors.append({"field": field, "code": code, "message": message})

    def warn(self, field, code, message):
        self.warnings.append({"field": field, "code": code, "message": message})

    def out(self):
        return {"ok": not self.errors, "errors": self.errors, "warnings": self.warnings}


def _text(issues, body, key, n, label, required=False):
    v = body.get(key)
    if v is None or v == "":
        if required:
            issues.error(key, "required", f"{label} is required.")
        return ""
    if not isinstance(v, str) or len(v) > n:
        issues.error(key, "bad_text", f"{label} must be text of at most {n} characters.")
        return ""
    return v


def validate_agent(body, agents, open_drafts=(), token_actors=()):
    """The prototype's agent rules. `agents`: [(id, display_name, status)] registered or retired; `open_drafts`:
    other open agent drafts' bodies; `token_actors`: actors that hold actor tokens today. Pure; writes nothing."""
    v = Issues()
    if not isinstance(body, dict):
        v.error("body", "bad_body", "An agent draft must be an object.")
        return v.out()
    for k in sorted(set(body) - AGENT_KEYS):
        v.error(k, "unknown_field", f"{k} is not an agent field.")
    for p in secret_paths(body):
        v.error(p, "secret", "This looks like a credential. Never put tokens, keys or passwords in a draft.")

    slug = _text(v, body, "id", 38, "The ID", required=True)
    slug = _slug_of(slug)
    by_id = {a[0]: a for a in agents}
    if slug:
        if not SLUG_RE.match(slug):
            v.error("id", "bad_id", "The ID must start with a letter and use only lowercase letters, numbers and "
                                    "hyphens (2 to 32 characters).")
        elif slug in RESERVED_IDS:
            v.error("id", "reserved_id", f'The ID "{slug}" is reserved for the system.')
        elif f"agent:{slug}" in by_id:
            a = by_id[f"agent:{slug}"]
            if a[2] == "retired":
                v.error("id", "retired_id", f'The ID "{slug}" belonged to {a[1]}, who was retired. IDs are never '
                                            "reused, so old records stay attributed.")
            else:
                v.error("id", "duplicate_id", f'The ID "{slug}" is already registered to {a[1]}.')
        elif any(_slug_of((d or {}).get("id")) == slug for d in open_drafts if isinstance(d, dict)):
            v.warn("id", "draft_id", f'Another open draft also uses the ID "{slug}".')
        if SLUG_RE.match(slug) and f"agent:{slug}" in token_actors:
            v.warn("id", "token_actor", f"An actor token already names agent:{slug}; registering ties that history "
                                        "to this record. No token is issued or changed.")

    name = _text(v, body, "name", 32, "The display name", required=True)
    if name:
        n = _norm(name)
        live = [a for a in agents if a[2] == "registered"]
        if not NAME_RE.match(name.strip()):
            v.error("name", "bad_name", "The name must start with a letter and use letters, numbers, spaces, dots, "
                                        "apostrophes or hyphens (up to 32 characters).")
        elif n in RESERVED_NAMES:
            v.error("name", "reserved_name", f'"{name}" is reserved. Choose another name.')
        elif any(_norm(a[1]) == n for a in live):
            v.error("name", "duplicate_name", f"{name} already exists. Two agents can't share a display name.")
        else:
            letters = re.sub(r"[^a-z]", "", n)
            close = next((a for a in live if _dist(_norm(a[1]), n) <= 1
                          or (letters and re.sub(r"[^a-z]", "", _norm(a[1])) == letters)), None)
            if close:
                v.warn("name", "confusable_name", f'"{name}" is easy to confuse with {close[1]} ({close[0]}).')
            gone = next((a for a in agents if a[2] == "retired" and _norm(a[1]) == n), None)
            if gone:
                v.warn("name", "retired_name", f"A retired agent was also called {gone[1]} ({gone[0]}).")

    _text(v, body, "title", 60, "The role title", required=True)
    _text(v, body, "template", 40, "The template")
    _text(v, body, "spec", 2000, "The specialisation")
    _text(v, body, "notes", 2000, "Notes")

    model = body.get("model")
    if model is not None:
        if not isinstance(model, dict) or set(model) - {"provider", "model", "reasoning"}:
            v.error("model", "bad_model", "model must be {provider, model, reasoning}.")
        else:
            prov, mid, reas = model.get("provider"), model.get("model"), model.get("reasoning")
            if prov not in PROVIDERS:
                v.error("model.provider", "bad_model", f"provider must be one of {', '.join(PROVIDERS)}.")
            elif mid not in PROVIDERS[prov]:
                v.error("model.model", "bad_model", f"{prov} models here are {', '.join(PROVIDERS[prov])}.")
            if reas is not None and reas not in REASONING:
                v.error("model.reasoning", "bad_model", f"reasoning must be one of {', '.join(REASONING)}.")

    req = body.get("requested")
    if req is not None:
        if not isinstance(req, dict):
            v.error("requested", "bad_requested", "requested must map permission → deny, approval or allow.")
        else:
            for perm, grant in sorted(req.items()):
                if perm not in CEILINGS:
                    v.error(f"requested.{perm}", "unknown_permission", f"{perm} is not a known permission.")
                elif grant not in GRANTS:
                    v.error(f"requested.{perm}", "bad_grant", "A permission is deny, approval or allow.")
                elif GRANTS.index(grant) > GRANTS.index(CEILINGS[perm]):
                    v.error(f"requested.{perm}", "ceiling_exceeded",
                            f"{perm} can be at most {CEILINGS[perm]}; no setting can raise a hard ceiling.")

    budget = body.get("budget")
    if budget is not None:
        _budget(v, budget)

    projects = body.get("projects")
    if projects is not None:
        if not isinstance(projects, list) or len(projects) > 20 or not all(isinstance(p, str) for p in projects):
            v.error("projects", "bad_projects", "projects must be a list of project keys.")
        else:
            for p in projects:
                if registry.project(p) is None:
                    v.error("projects", "unknown_project", f"{p} is not a registered project.")
                elif registry.paused(p):
                    v.warn("projects", "paused_project", f"{registry.name_of(p)} is paused; no agent works on it.")

    rt = body.get("reportsTo")
    if rt is not None and rt != "jay":
        live_ids = {a[0] for a in agents if a[2] == "registered"}
        if slug and rt == f"agent:{slug}":
            v.error("reportsTo", "self_report", "An agent cannot report to itself.")
        elif not isinstance(rt, str) or rt not in live_ids:
            v.error("reportsTo", "bad_reports_to", "reportsTo must be jay or a registered agent's ID.")
    return v.out()


def _budget(v, budget):
    if not isinstance(budget, dict):
        v.error("budget", "bad_budget", "budget must be an object.")
        return
    for k in sorted(set(budget) - set(BUDGET_KEYS) - {"alerts"}):
        v.error(f"budget.{k}", "unknown_field", f"{k} is not a budget field.")
    for k, cap in BUDGET_KEYS.items():
        x = budget.get(k)
        if x is not None and (isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= cap):
            v.error(f"budget.{k}", "bad_budget", f"{k} must be a number from 0 to {cap}.")
    alerts = budget.get("alerts")
    if alerts is not None:
        if not isinstance(alerts, list) or not 1 <= len(alerts) <= 5 \
                or not all(isinstance(a, int) and not isinstance(a, bool) and 1 <= a <= 99 for a in alerts) \
                or alerts != sorted(set(alerts)):
            v.error("budget.alerts", "bad_budget", "alerts are 1 to 5 rising percentages between 1 and 99.")


def validate_project(body, open_drafts=()):
    """The prototype's project identity rules against the registry. Pure; writes nothing."""
    v = Issues()
    if not isinstance(body, dict):
        v.error("body", "bad_body", "A project draft must be an object.")
        return v.out()
    for k in sorted(set(body) - PROJECT_KEYS):
        v.error(k, "unknown_field", f"{k} is not a project field.")
    for p in secret_paths(body):
        v.error(p, "secret", "This looks like a credential. Never put tokens, keys or passwords in a draft.")
    others = [d for d in open_drafts if isinstance(d, dict)]

    key = _text(v, body, "key", 32, "The project key", required=True)
    if key:
        if not SLUG_RE.match(key):
            v.error("key", "bad_key", "The key must start with a letter and use lowercase letters, numbers and "
                                      "hyphens (2 to 32 characters).")
        elif key in RESERVED_IDS:
            v.error("key", "reserved_key", f'"{key}" is reserved.')
        elif registry.project(key) is not None:
            v.error("key", "duplicate_key", f"{key} is already a registered project.")
        elif any(d.get("key") == key for d in others):
            v.warn("key", "draft_key", f"Another open project draft also uses the key {key}.")

    name = _text(v, body, "name", 40, "The project name", required=True)
    if name and any(_norm(p["name"]) == _norm(name) for p in registry.PROJECTS.values()):
        v.error("name", "duplicate_name", f"A project called {name} already exists.")

    prefix = _text(v, body, "prefix", 6, "The ticket prefix", required=True)
    if prefix:
        if not registry.PREFIX_RE.match(prefix):
            v.error("prefix", "bad_prefix", "The prefix is 2 to 6 capital letters or digits, starting with a letter.")
        elif registry.resolve_prefix(prefix) is not None:
            _, owner, legacy = registry.resolve_prefix(prefix)
            v.error("prefix", "prefix_taken", f"{prefix} belongs to {registry.name_of(owner)}"
                                              f"{' as a retired prefix' if legacy else ''}; prefixes are never reused.")
        elif any(prefix.upper() == b.upper() or b.upper().startswith(prefix.upper() + "-")
                 for b in registry.BOARD_ID_PREFIXES):
            v.error("prefix", "prefix_taken", f"{prefix} is used by legacy board IDs.")
        elif any(str(d.get("prefix") or "").upper() == prefix.upper() for d in others):
            v.warn("prefix", "draft_prefix", f"Another open project draft also uses the prefix {prefix}.")

    repo = _text(v, body, "repo", 140, "The repository")
    if repo:
        if not REPO_RE.match(repo):
            v.error("repo", "bad_repo", "The repository is owner/name, with no URL, token or path.")
        else:
            bound = next((k for k in registry.PROJECTS if (registry.github_of(k) or "").lower() == repo.lower()), None)
            if bound:
                v.error("repo", "repo_already_bound", f"{repo} already belongs to {registry.name_of(bound)}.")

    t = body.get("type")
    if t is not None and t not in PROJECT_TYPES:
        v.error("type", "bad_type", f"type must be one of {', '.join(PROJECT_TYPES)}.")
    elif t in ("client", "employer"):
        v.warn("type", "laptop_only", "Client and employer projects onboard laptop-only and directed; no push or PR "
                                      "during onboarding (D-025).")
    _text(v, body, "lead", 38, "The lead")
    _text(v, body, "notes", 2000, "Notes")
    return v.out()


class Onboarding:
    def __init__(self, db, clock=time.time, enabled=False):
        self.db = db
        self.clock = clock
        self.enabled = enabled is True

    # ---------- plumbing (workers.py's pattern) ----------

    @contextlib.contextmanager
    def _tx(self):
        """A record and its event land together or not at all (tasks.db runs in autocommit mode)."""
        if self.db.in_transaction:
            self.db.execute("SAVEPOINT onboarding_tx")
            try:
                yield
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK TO onboarding_tx")
                    self.db.execute("RELEASE onboarding_tx")
                raise
            self.db.execute("RELEASE onboarding_tx")
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _event(self, subject, kind, data=None):
        text = json.dumps(data or {})
        if len(text) > 2000:
            text = json.dumps({"truncated": True, "bytes": len(text)})
        self.db.execute("INSERT INTO onboarding_events (subject, at, kind, actor, data) VALUES (?,?,?,?,?)",
                        (subject, self.clock(), kind, "jay", text))

    def require_on(self):
        if not self.enabled:
            raise OnboardingError(404, OFF_MESSAGE)

    def _jay(self, actor, what):
        self.require_on()
        if actor != "jay":
            raise OnboardingError(403, f"only Jay can {what}; an agent never onboards itself or another agent")

    def _agents(self):
        return [tuple(r) for r in self.db.execute("SELECT id, display_name, status FROM agent_registrations")]

    def _open_bodies(self, kind, except_id=None):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT body FROM onboarding_drafts WHERE kind=? AND state='open' AND id IS NOT ?", (kind, except_id))]

    def _token_actors(self):
        out = set()
        for sql in ("SELECT DISTINCT actor FROM actor_tokens",
                    "SELECT DISTINCT subject FROM identity_tokens WHERE kind='agent'"):      # v11 typed tokens
            try:
                out |= {r[0] for r in self.db.execute(sql)}
            except Exception:  # noqa: BLE001 — a hint only (an older schema has no identity_tokens)
                pass
        return out

    def validate(self, kind, body, except_id=None):
        """Read-only: the errors and warnings a draft has now. Saving a draft never needs it to be valid."""
        self.require_on()
        if kind == "agent":
            return validate_agent(body, self._agents(), self._open_bodies("agent", except_id), self._token_actors())
        if kind == "project":
            return validate_project(body, self._open_bodies("project", except_id))
        raise OnboardingError(400, "kind must be agent or project")

    @staticmethod
    def _storable(body):
        """What a draft must be to be stored at all: an object, small, and holding nothing that looks secret."""
        if not isinstance(body, dict):
            raise OnboardingError(400, "body must be an object")
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
        if len(raw.encode()) > MAX_BODY:
            raise OnboardingError(413, f"a draft is at most {MAX_BODY // 1024} KB")
        hits = secret_paths(body)
        if hits:
            raise OnboardingError(400, f"{hits[0]} looks like a credential; nothing was stored. Never put tokens, "
                                       "keys or passwords in a draft.")
        return raw

    # ---------- drafts ----------

    def create_draft(self, kind, body, actor):
        self._jay(actor, "start an onboarding draft")
        if kind not in KINDS:
            raise OnboardingError(400, "kind must be agent or project")
        raw = self._storable(body)
        if self.db.execute("SELECT COUNT(*) FROM onboarding_drafts WHERE state='open'").fetchone()[0] >= MAX_OPEN_DRAFTS:
            raise OnboardingError(429, f"{MAX_OPEN_DRAFTS} drafts are already open; finish or discard some first")
        did, now = "d-" + secrets.token_hex(6), self.clock()
        with self._tx():
            self.db.execute("INSERT INTO onboarding_drafts (id, kind, state, body, body_sha, revision, created_at, "
                            "created_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            (did, kind, "open", raw, _sha(body), 1, now, "jay", now))
            self._event(f"draft:{did}", "draft_created", {"kind": kind, "bodySha": _sha(body)})
        return self.draft(did)

    def _open_draft(self, did):
        if not isinstance(did, str) or not DRAFT_RE.match(did):
            raise OnboardingError(404, "no such draft")
        row = self.db.execute("SELECT kind, state, revision, body FROM onboarding_drafts WHERE id=?", (did,)).fetchone()
        if row is None:
            raise OnboardingError(404, "no such draft")
        if row[1] != "open":
            raise OnboardingError(409, f"that draft is {row[1]}; a closed draft is final")
        return row

    @staticmethod
    def _revision(revision, current):
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise OnboardingError(400, "revision must be the draft's current revision number")
        if revision != current:
            raise OnboardingError(409, f"the draft changed (revision {current}); reload it and try again")

    def update_draft(self, did, body, revision, actor):
        self._jay(actor, "change an onboarding draft")
        row = self._open_draft(did)
        self._revision(revision, row[2])
        raw = self._storable(body)
        with self._tx():
            n = self.db.execute("UPDATE onboarding_drafts SET body=?, body_sha=?, revision=revision + 1, updated_at=? "
                                "WHERE id=? AND state='open' AND revision=?",
                                (raw, _sha(body), self.clock(), did, revision)).rowcount
            if n != 1:
                raise OnboardingError(409, "the draft changed; reload it and try again")
            self._event(f"draft:{did}", "draft_updated", {"revision": revision + 1, "bodySha": _sha(body)})
        return self.draft(did)

    def discard_draft(self, did, actor, reason=""):
        self._jay(actor, "discard an onboarding draft")
        self._open_draft(did)
        with self._tx():
            self.db.execute("UPDATE onboarding_drafts SET state='discarded', closed_at=MAX(?, created_at) WHERE id=?",
                            (self.clock(), did))
            self._event(f"draft:{did}", "draft_discarded", {"reason": _clean(reason, 200)})
        return self.draft(did)

    # ---------- registration ----------

    def register_agent(self, did, revision, acknowledge, actor):
        """An open agent draft becomes an identity record: `registered`, config version 1. Issues nothing."""
        self._jay(actor, "register an agent")
        kind, _state, rev, raw = self._open_draft(did)
        if kind != "agent":
            raise OnboardingError(409, "only an agent draft can be registered; a project becomes a project through "
                                       "the registry and a profile PR for Jay")
        self._revision(revision, rev)
        body = json.loads(raw)
        result = self.validate("agent", body, except_id=did)
        if result["errors"]:
            first = result["errors"][0]
            raise OnboardingError(409, f"fix the draft first: {first['message']} "
                                       f"({len(result['errors'])} problem(s); see /api/onboarding/validate)")
        ack = set(acknowledge) if isinstance(acknowledge, list) and all(isinstance(a, str) for a in acknowledge) \
            else set()
        missing = sorted({w["code"] for w in result["warnings"]} - ack)
        if missing:
            raise OnboardingError(409, f"acknowledge these warnings first: {', '.join(missing)}")
        aid = f"agent:{_slug_of(body['id'])}"
        config = {k: body[k] for k in sorted(body) if k not in ("id", "name")}
        now = self.clock()
        with self._tx():
            self.db.execute("INSERT INTO agent_registrations (id, display_name, status, created_at, created_by, "
                            "from_draft) VALUES (?,?,?,?,?,?)", (aid, body["name"].strip(), "registered", now, "jay", did))
            self.db.execute("INSERT INTO agent_config_versions (agent_id, version, config, config_sha, created_at, "
                            "created_by, note) VALUES (?,?,?,?,?,?,?)",
                            (aid, 1, json.dumps(config, sort_keys=True), _sha(config), now, "jay", "registered"))
            self.db.execute("UPDATE onboarding_drafts SET state='registered', result=?, closed_at=MAX(?, created_at) "
                            "WHERE id=? AND state='open' AND revision=?", (aid, now, did, revision))
            self._event(aid, "registered", {"draft": did, "version": 1, "configSha": _sha(config),
                                            "acknowledged": sorted(ack & {w["code"] for w in result["warnings"]})})
            self._event(f"draft:{did}", "registered", {"agent": aid})
        return self.agent(aid)

    def retire_agent(self, agent_id, actor, reason=""):
        """Final for that ID: it is never reused. Retiring revokes nothing because registering issued nothing."""
        self._jay(actor, "retire an agent")
        aid = f"agent:{_slug_of(agent_id)}"
        row = self.db.execute("SELECT status FROM agent_registrations WHERE id=?", (aid,)).fetchone()
        if row is None:
            raise OnboardingError(404, f"no registered agent {aid}")
        if row[0] == "retired":
            raise OnboardingError(409, f"{aid} is already retired")
        with self._tx():
            self.db.execute("UPDATE agent_registrations SET status='retired', retired_at=MAX(?, created_at), "
                            "retired_by='jay' WHERE id=?", (self.clock(), aid))
            self._event(aid, "retired", {"reason": _clean(reason, 200)})
        return self.agent(aid)

    # ---------- reads ----------

    def agents(self):
        self.require_on()
        out = []
        for r in self.db.execute(
                "SELECT a.id, a.display_name, a.status, a.created_at, a.retired_at, a.from_draft, "
                "(SELECT MAX(version) FROM agent_config_versions v WHERE v.agent_id = a.id) "
                "FROM agent_registrations a ORDER BY a.created_at, a.id"):
            out.append({"id": r[0], "name": r[1], "status": r[2], "createdAt": r[3], "retiredAt": r[4],
                        "fromDraft": r[5], "version": r[6], "active": False, "credentials": None})
        return out

    def agent(self, agent_id):
        self.require_on()
        aid = f"agent:{_slug_of(agent_id)}"
        base = next((a for a in self.agents() if a["id"] == aid), None)
        if base is None:
            raise OnboardingError(404, f"no registered agent {aid}")
        versions = [{"version": r[0], "config": json.loads(r[1]), "configSha": r[2], "createdAt": r[3],
                     "createdBy": r[4], "note": r[5]}
                    for r in self.db.execute("SELECT version, config, config_sha, created_at, created_by, note "
                                             "FROM agent_config_versions WHERE agent_id=? ORDER BY version", (aid,))]
        return dict(base, versions=versions, events=self.events(subject=aid))

    def drafts(self, state=None):
        self.require_on()
        if state is not None and state not in ("open", "registered", "discarded"):
            raise OnboardingError(400, "state must be open, registered or discarded")
        q = "SELECT id FROM onboarding_drafts" + (" WHERE state=?" if state else "") + " ORDER BY updated_at DESC LIMIT 200"
        return [self.draft(r[0], with_validation=False) for r in self.db.execute(q, (state,) if state else ())]

    def draft(self, did, with_validation=True):
        self.require_on()
        if not isinstance(did, str) or not DRAFT_RE.match(did):
            raise OnboardingError(404, "no such draft")
        r = self.db.execute("SELECT id, kind, state, body, body_sha, revision, created_at, updated_at, closed_at, result "
                            "FROM onboarding_drafts WHERE id=?", (did,)).fetchone()
        if r is None:
            raise OnboardingError(404, "no such draft")
        out = {"id": r[0], "kind": r[1], "state": r[2], "body": json.loads(r[3]), "bodySha": r[4], "revision": r[5],
               "createdAt": r[6], "updatedAt": r[7], "closedAt": r[8], "result": r[9]}
        if with_validation and r[2] == "open":
            out["validation"] = self.validate(r[1], out["body"], except_id=r[0])
        return out

    def events(self, subject=None, limit=100):
        self.require_on()
        limit = max(1, min(int(limit), 500))
        q, args = "SELECT id, subject, at, kind, actor, data FROM onboarding_events", []
        if subject:
            q += " WHERE subject=?"
            args.append(subject)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [{"id": r[0], "subject": r[1], "at": r[2], "kind": r[3], "actor": r[4], "data": _loads(r[5])}
                for r in self.db.execute(q, args)]

    def agent_budgets(self):
        """registered agent → the budget in its newest configuration version (for the shadow budget report)."""
        self.require_on()
        out = {}
        for aid, config in self.db.execute(
                "SELECT a.id, v.config FROM agent_registrations a JOIN agent_config_versions v ON v.agent_id = a.id "
                "WHERE a.status = 'registered' AND v.version = (SELECT MAX(version) FROM agent_config_versions w "
                "WHERE w.agent_id = a.id)"):
            b = (_loads(config) or {}).get("budget")
            if isinstance(b, dict) and b:
                out[aid] = b
        return out

    def summary(self):
        self.require_on()
        counts = {"registered": 0, "retired": 0}
        for status, n in self.db.execute("SELECT status, COUNT(*) FROM agent_registrations GROUP BY status"):
            counts[status] = n
        drafts = {s: n for s, n in self.db.execute("SELECT state, COUNT(*) FROM onboarding_drafts GROUP BY state")}
        return {"enabled": True, "mode": "groundwork", "agents": counts, "drafts": drafts,
                "permissions": [{"id": k, "ceiling": c} for k, c in CEILINGS.items()],
                "note": "Records only. Registering an agent issues no credential and starts nothing; requested "
                        "permissions are not granted; nothing here is enforced (D-024 is proposed)."}


def _loads(text):
    try:
        v = json.loads(text or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {"unreadable": True}
