"""The Capability Broker — Phase 2 shadow step 3, RECORD ONLY (Jay 2026-10-25).

Phase 2's Broker is the one place that decides whether an action that exercises authority may happen: merging a PR,
approving a live deploy, typing into a Claude pane, writing to a repository. It grants only when all eight checks of
the design pass (docs/COMMANDCENTER_V2_DISCOVERY.md "Phase 2"):

    actor        who the request PROVES to be (ccd/identity.py resolve(); ccd itself is `system:ccd`)
    agent_grant  the verbs this agent may ever use          (no grants exist yet: unknown for an agent)
    project      the project's profile: present, valid, not paused
    task_mode    what the agent's current task allows       (not defined yet: unknown for an agent)
    node         the WorkerNode the action runs on          (today always the server itself)
    capability   whether this kind of actor may use the verb at all
    approval     the approval the verb needs (Jay's unlocked session, a recorded merge or deploy approval, or the
                 Autonomy Engine saying "auto")
    egress       data leaving the host                      (no verb here sends data out: not applicable)

Each term is "ok", "n/a" (does not apply to this actor or verb), "deny" or "unknown". Unknown always counts as deny,
so an action would be refused when any term is deny or unknown.

THIS MODULE REFUSES NOTHING. `check()` is pure; `Shadow.observe()` appends one `broker_observations` row (tasks.db v13,
its own hash chain) per decision, with `enforced` always 0 (the database refuses anything else), and never raises.
ccd records only while config.json sets `"phase2_broker_shadow": true` (default false). Every action goes ahead
exactly as before, whatever the record says.
"""
import contextvars
import hashlib
import json
import re
import time

VERSION = 1
TERMS = ("actor", "agent_grant", "project", "task_mode", "node", "capability", "approval", "egress")
RESULTS = ("ok", "n/a", "deny", "unknown")
GENESIS = "0" * 64
SYSTEM = "system:ccd"

# Verb -> the kinds of actor that may ever use it, and the approval it needs.
#   approval "jay"     Jay's live Developer Unlock session
#   approval "merge"   for Jay: his session; for ccd: the Autonomy Engine's verdict "auto" (a recorded single-use
#                      approval for the PR head is a Phase 2 item, not built)
#   approval "deploy"  Jay's recorded deploy approval for this ticket (the pipeline's deploy gate)
#   approval None      none beyond the other terms
# `writes_checkout`: the action writes inside Jay's own checkout. Phase 2 moves these to a mirror the Broker owns, so
# the capability term denies them for everyone (Track A).
VERBS = {
    "pr.merge":        {"who": ("jay", "system"), "approval": "merge"},
    "go_live.approve": {"who": ("jay",), "approval": "jay"},
    "deploy.request":  {"who": ("jay", "agent"), "approval": None},
    "deploy.record":   {"who": ("jay", "agent"), "approval": "deploy"},
    "pane.input":      {"who": ("jay", "agent"), "approval": None},
    "repo.write":      {"who": (), "approval": None, "writes_checkout": True},
    "worktree.remove": {"who": ("system",), "approval": None, "writes_checkout": True},
}
REASONS = ("unverified", "missing_header", "asserted_mismatch", "jay_without_unlock", "project_mismatch",
           "no_agent_grants", "no_profile", "project_paused", "no_task_mode", "unknown_node", "unknown_verb",
           "not_allowed_for_actor", "writes_jay_checkout", "no_jay_session", "engine_not_auto", "engine_unknown",
           "no_deploy_approval")
OBS_COLUMNS = ("at", "verb", "project", "target", "actor", "asserted", "via", "terms", "would_refuse", "reasons",
               "enforced", "version")
TARGET_MAX = 200

# The request behind the current call, set by api.py's BrokerContext for each API write: {developer, token,
# asserted}. None for what ccd does on its own (auto-merge, worktree cleanup), which is `system:ccd`.
REQUEST = contextvars.ContextVar("ccd_broker_request", default=None)


def kind_of(actor):
    if actor == "jay":
        return "jay"
    if actor == SYSTEM:
        return "system"
    if isinstance(actor, str) and actor.startswith("agent:"):
        return "agent"
    if isinstance(actor, str) and actor.startswith("svc:"):
        return "service"
    return "unknown"


def _term(result, reason=None):
    return {"result": result, "reason": reason}


def check(verb, who, project=None, profile=None, approval=None, node="server"):
    """The Broker's decision for one action, computed and returned, never enforced.

    `who`: identity.resolve(...) for an API request, or {"resolvedActor": "system:ccd", "via": "system",
    "reasons": []} for ccd itself. `profile`: "ok" | "paused" | "missing" (None when the verb names no project).
    `approval`: facts for the approval term: {"developer": bool} and, for a merge by ccd, {"engine": "auto"|"jay"|
    "refuse"|None}; for deploy.record, {"deployApproved": bool}. `node`: where the action runs ("server" today).

    Returns {verb, actor, kind, terms{term: {result, reason}}, wouldRefuse, reasons["term:reason"], enforced}."""
    who = who or {}
    approval = approval or {}
    actor = who.get("resolvedActor") or "unknown"
    kind = kind_of(actor)
    spec = VERBS.get(verb)
    terms = {}
    if kind == "system":
        terms["actor"] = _term("ok")
    elif who.get("reasons"):
        terms["actor"] = _term("deny", next((r for r in who["reasons"] if r in REASONS), "unverified"))
    else:
        terms["actor"] = _term("ok")
    terms["agent_grant"] = _term("unknown", "no_agent_grants") if kind == "agent" else _term("n/a")
    if project is None:
        terms["project"] = _term("n/a")
    elif profile == "ok":
        terms["project"] = _term("ok")
    elif profile == "paused":
        terms["project"] = _term("deny", "project_paused")
    else:
        terms["project"] = _term("unknown", "no_profile")
    terms["task_mode"] = _term("unknown", "no_task_mode") if kind == "agent" else _term("n/a")
    terms["node"] = _term("ok") if node == "server" else _term("unknown", "unknown_node")
    if spec is None:
        terms["capability"] = _term("deny", "unknown_verb")
    elif spec.get("writes_checkout"):
        terms["capability"] = _term("deny", "writes_jay_checkout")
    elif kind in spec["who"]:
        terms["capability"] = _term("ok")
    else:
        terms["capability"] = _term("deny", "not_allowed_for_actor")
    need = spec["approval"] if spec else None
    dev = bool(approval.get("developer")) and actor == "jay"
    if need is None:
        terms["approval"] = _term("n/a")
    elif need == "jay":
        terms["approval"] = _term("ok") if dev else _term("deny", "no_jay_session")
    elif need == "merge":
        if kind == "system":
            engine = approval.get("engine")
            terms["approval"] = _term("ok") if engine == "auto" else \
                _term("unknown", "engine_unknown") if engine is None else _term("deny", "engine_not_auto")
        else:
            terms["approval"] = _term("ok") if dev else _term("deny", "no_jay_session")
    else:   # deploy
        terms["approval"] = _term("ok") if approval.get("deployApproved") else _term("deny", "no_deploy_approval")
    terms["egress"] = _term("n/a")
    reasons = [f"{t}:{terms[t]['reason']}" for t in TERMS if terms[t]["result"] in ("deny", "unknown")]
    return {"verb": verb, "actor": actor, "kind": kind, "terms": terms, "wouldRefuse": bool(reasons),
            "reasons": reasons, "enforced": False}


def system_who():
    return {"resolvedActor": SYSTEM, "assertedActor": None, "via": "system", "reasons": []}


def _canon(row):
    return json.dumps([row[c] for c in OBS_COLUMNS], separators=(",", ":"), default=str)


class Shadow:
    """The append-only record of Broker decisions in tasks.db (migration 13)."""

    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock
        self.errors = 0               # decisions that could not be recorded
        self._good = (0, GENESIS, 0)  # (last checked id, its sha, rows checked)
        self._broken = None

    def observe(self, verb, project, target, who, decision):
        """Append one decision. Never raises: a failure is counted in `errors`."""
        try:
            row = {"at": self.clock(), "verb": str(verb)[:40],
                   "project": None if project is None else re.sub(r"[^a-z0-9-]", "?", str(project))[:40],
                   "target": str(target or "")[:TARGET_MAX],
                   "actor": str(decision.get("actor") or "unknown")[:80],
                   "asserted": None if not (who or {}).get("assertedActor") else str(who["assertedActor"])[:80],
                   "via": str((who or {}).get("via") or "none")[:20],
                   "terms": json.dumps({t: decision["terms"][t] for t in TERMS}, sort_keys=True),
                   "would_refuse": 1 if decision.get("wouldRefuse") else 0,
                   "reasons": json.dumps(list(decision.get("reasons") or [])), "enforced": 0, "version": VERSION}
            own = not self.db.in_transaction
            self.db.execute("BEGIN IMMEDIATE" if own else "SAVEPOINT broker_obs")
            try:
                prev = self.db.execute("SELECT sha FROM broker_observations ORDER BY id DESC LIMIT 1").fetchone()
                prev_sha = prev[0] if prev else GENESIS
                sha = hashlib.sha256((prev_sha + _canon(row)).encode()).hexdigest()
                self.db.execute(f"INSERT INTO broker_observations ({', '.join(OBS_COLUMNS)}, prev_sha, sha) VALUES "
                                f"({', '.join('?' * (len(OBS_COLUMNS) + 2))})",
                                (*[row[c] for c in OBS_COLUMNS], prev_sha, sha))
                self.db.execute("COMMIT" if own else "RELEASE broker_obs")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK" if own else "ROLLBACK TO broker_obs")
                    if not own:
                        self.db.execute("RELEASE broker_obs")
                raise
        except Exception:  # noqa: BLE001 — a shadow record must never break the action
            self.errors += 1

    def verify(self, full=False):
        """Walk the chain: {ok, checked, brokenAt, full}."""
        if not full and self._broken is not None:
            return {"ok": False, "checked": self._good[2], "brokenAt": self._broken, "full": False}
        start, prev, n = (0, GENESIS, 0) if full else self._good
        if start and self.db.execute("SELECT 1 FROM broker_observations WHERE id=? AND sha=?",
                                     (start, prev)).fetchone() is None:
            start, prev, n = 0, GENESIS, 0
        for r in self.db.execute(f"SELECT id, {', '.join(OBS_COLUMNS)}, prev_sha, sha FROM broker_observations "
                                 f"WHERE id > ? ORDER BY id", (start,)):
            row = dict(zip(OBS_COLUMNS, r[1:1 + len(OBS_COLUMNS)]))
            if r[-2] != prev or hashlib.sha256((prev + _canon(row)).encode()).hexdigest() != r[-1]:
                self._broken = r[0]
                return {"ok": False, "checked": n, "brokenAt": r[0], "full": full}
            prev, n, start = r[-1], n + 1, r[0]
        self._good, self._broken = (start, prev, n), None
        return {"ok": True, "checked": n, "brokenAt": None, "full": full}

    def summary(self, since=None):
        """Decisions in the window (default 30 days): totals, by verb, by reason, by term."""
        since = since if since is not None else self.clock() - 30 * 86400
        verbs, reasons, terms, total, refuse = {}, {}, {}, 0, 0
        for verb, would, rs, ts, n in self.db.execute(
                "SELECT verb, would_refuse, reasons, terms, COUNT(*) FROM broker_observations WHERE at >= ? "
                "GROUP BY verb, would_refuse, reasons, terms", (since,)):
            v = verbs.setdefault(verb, {"total": 0, "wouldRefuse": 0})
            v["total"] += n
            total += n
            if would:
                v["wouldRefuse"] += n
                refuse += n
            for r in json.loads(rs or "[]"):
                reasons[r] = reasons.get(r, 0) + n
            for t, d in (json.loads(ts or "{}")).items():
                c = terms.setdefault(t, {k: 0 for k in RESULTS})
                if d.get("result") in c:
                    c[d["result"]] += n
        return {"since": since, "total": total, "wouldRefuse": refuse, "byVerb": verbs, "byReason": reasons,
                "byTerm": terms, "enforced": False}

    def recent(self, limit=50):
        rows = self.db.execute(f"SELECT id, {', '.join(OBS_COLUMNS)} FROM broker_observations ORDER BY id DESC LIMIT ?",
                               (max(1, min(int(limit), 500)),)).fetchall()
        out = []
        for r in rows:
            d = dict(zip(OBS_COLUMNS, r[1:]))
            out.append({"id": r[0], "at": d["at"], "verb": d["verb"], "project": d["project"], "target": d["target"],
                        "actor": d["actor"], "asserted": d["asserted"], "via": d["via"],
                        "terms": json.loads(d["terms"]), "wouldRefuse": bool(d["would_refuse"]),
                        "reasons": json.loads(d["reasons"]), "enforced": False})
        return out
