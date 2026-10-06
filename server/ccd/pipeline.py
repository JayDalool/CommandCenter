"""The ticket pipeline: PLAN → BUILD → REVIEW → MERGE → VERIFY → DONE (plans/TICKET-PIPELINE-V1.md).

Durable work state lives in tasks.db (`ticket_work`, `ticket_findings`), so a new
coordinator can resume any ticket without a transcript. Every op validates the
ticket's current state and refuses (409) rather than skipping a stage; each one is
one transaction with its status change and an audit event.

Stages map onto the canonical statuses — there is no second status set:

    PLAN    INBOX PROPOSED RESEARCHING READY_TO_IMPLEMENT
    BUILD   IN_PROGRESS
    REVIEW  IN_REVIEW
    MERGE   READY_TO_MERGE
    VERIFY  VERIFYING
    DONE    DONE

Owner gates are conditional (`policy()`): a plan gate only for risky or ambiguous
tickets, a merge gate per project merge policy, UI/deploy gates from the ticket's
flags. Automatic moves come only from deterministic signals: an agent recording a
stage result through this module, or ccd's GitHub poll (PR head, CI, merge).
"""
import json
import re
import time

from . import registry
from .tasks import TaskError, _printable

STAGES = ("PLAN", "BUILD", "REVIEW", "MERGE", "VERIFY", "DONE")
STAGE_OF = {"INBOX": "PLAN", "PROPOSED": "PLAN", "RESEARCHING": "PLAN", "READY_TO_IMPLEMENT": "PLAN",
            "IN_PROGRESS": "BUILD", "IN_REVIEW": "REVIEW", "READY_TO_MERGE": "MERGE", "VERIFYING": "VERIFY",
            "DONE": "DONE"}
# Where a resolved failure returns the ticket to.
RESUME_STATUS = {"PLAN": "RESEARCHING", "BUILD": "IN_PROGRESS", "REVIEW": "IN_REVIEW", "MERGE": "IN_REVIEW",
                 "VERIFY": "VERIFYING"}
PLAN_GATE_LABELS = {"security", "migration", "destructive", "architecture", "product-decision", "ambiguous",
                    "financial", "legal", "gate:plan"}
GATES = ("plan", "merge", "ui", "deploy", "failure")
OWNER_GATES = ("plan", "ui", "deploy", "failure", "merge")
ROLE_NAMES = ("coordinator", "planner", "implementer", "reviewer", "verifier")
MAX_LANES = 2
MAX_REVIEW_CYCLES = 2
SHA_RE = re.compile(r"^[0-9a-f]{40}$")   # the full PR head commit: no prefix can match another head
SLUG_RE = r"[a-z0-9][a-z0-9-]{0,60}"
META_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,79}$")
CATEGORY_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


def _now():
    return time.time()


def stage_of(status):
    return STAGE_OF.get(status)


def policy(ticket, project_key=None):
    """Which owner gates this ticket needs. Derived from flags, labels, type and the project registry."""
    labels = set(ticket.get("labels") or [])
    # tasks.get() reports flags as needs_jay …; accept the label spelling (needs:jay) too.
    flags = {f.replace(":", "_").replace("-", "_") for f in ticket.get("flags") or []}
    reasons = sorted(labels & PLAN_GATE_LABELS)
    if "needs_jay" in flags:
        reasons.append("needs Jay")
    if "needs_legal" in flags:
        reasons.append("needs legal")
    if ticket.get("type") in ("SECURITY", "LEGAL"):
        reasons.append(ticket["type"].lower())
    merge = registry.pipeline_of(project_key or ticket.get("project")).get("merge", "owner")
    return {
        "plan": "owner" if reasons else "auto",
        "planReasons": reasons,
        "merge": merge,
        "ui": "needs_ui_review" in flags or ticket.get("type") == "DESIGN" or "ui" in labels,
        "deploy": "needs_deploy" in flags,
    }


def _text(v, limit, field, multiline=True):
    return _printable(str(v if v is not None else "").strip(), limit, field, multiline)


def _list(v, field, items=20, limit=500):
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or len(v) > items:
        raise TaskError(400, f"{field} must be a list of at most {items} items")
    return [x for x in (_text(i, limit, field, multiline=False) for i in v) if x]


def clean_plan(raw):
    if not isinstance(raw, dict):
        raise TaskError(400, "plan must be an object")
    plan = {"summary": _text(raw.get("summary"), 2000, "summary"),
            "requirements": _list(raw.get("requirements"), "requirements"),
            "approach": _text(raw.get("approach"), 4000, "approach"),
            "affected": _list(raw.get("affected"), "affected", 40, 300),
            "risk": _text(raw.get("risk"), 1000, "risk"),
            "tests": _list(raw.get("tests"), "tests"),
            "questions": _list(raw.get("questions"), "questions")}
    if not plan["summary"]:
        raise TaskError(400, "a plan needs a summary")
    return plan


def _merge_ok(confirmed, head):
    """Jay's merge authorisation is for one head: it is recorded as merge:<sha>."""
    return bool(head) and f"merge:{head}" in confirmed


def _no_merge(confirmed):
    return [g for g in confirmed if g != "merge" and not g.startswith("merge:")]


def _meta(v, field):
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not META_RE.match(v):
        raise TaskError(400, f"{field} must be a short name (letters, digits, . _ : / @ + -)")
    return v


class Pipeline:
    """Ops over one TaskStore. Methods return (ticket, changes, events)."""

    def __init__(self, store, max_lanes=MAX_LANES):
        self.ts = store
        self.db = store.db
        self.max_lanes = max_lanes

    # ---------- reading ----------

    def _row(self, tid):
        r = self.db.execute("SELECT plan, plan_state, gate, gate_reason, confirmed, worktree, roles, review_verdict, "
                            "review_head, review_cycles, verification, handoff, blocked, merge, updated_at, review_pr "
                            "FROM ticket_work WHERE ticket_id=?", (tid,)).fetchone()
        if not r:
            return None
        j = lambda v, d: json.loads(v) if v else d  # noqa: E731
        return {"plan": j(r[0], {}), "planState": r[1], "gate": r[2], "gateReason": r[3], "confirmed": j(r[4], []),
                "worktree": r[5], "roles": j(r[6], {}),
                "review": {"verdict": r[7], "head": r[8], "cycles": r[9], "pr": r[15]},
                "verification": j(r[10], None), "handoff": j(r[11], None), "blocked": j(r[12], None),
                "merge": j(r[13], None), "updatedAt": r[14]}

    DEV_ROLES = ("planner", "implementer", "reviewer", "verifier")

    def recorded(self, ids):
        """{ticket id: {"roles", "review"}} for the tickets that have pipeline work, in ONE query.

        Only what a pipeline step recorded: roles by name (model + time), and the review verdict/head.
        """
        ids = list(ids)
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for tid, roles, verdict, head in self.db.execute(
                    "SELECT ticket_id, roles, review_verdict, review_head FROM ticket_work WHERE ticket_id IN (%s)"
                    % ",".join("?" * len(chunk)), chunk).fetchall():
                have = json.loads(roles) if roles else {}
                out[tid] = {"roles": {r: {"model": have[r].get("model"), "at": have[r].get("at")}
                                      for r in self.DEV_ROLES if isinstance(have.get(r), dict)},
                            "review": {"verdict": verdict, "head": head} if verdict or head else None}
        return out

    def work(self, key):
        """Everything a coordinator needs to resume this ticket, in one object."""
        t = self.ts.get(key)
        tid = self.ts._id_of(key)
        w = self._row(tid) or {"plan": {}, "planState": "none", "gate": None, "gateReason": None, "confirmed": [],
                               "worktree": None, "roles": {}, "review": {"verdict": None, "head": None, "cycles": 0, "pr": None},
                               "verification": None, "handoff": None, "blocked": None, "merge": None, "updatedAt": None}
        stage = stage_of(t["status"]) or ((w.get("blocked") or {}).get("stage") if t["status"] == "BLOCKED" else None)
        findings = [{"at": a, "source": s, "scope": sc, "category": c, "summary": m, "head": h} for a, s, sc, c, m, h in
                    self.db.execute("SELECT at, source, scope, category, summary, head FROM ticket_findings "
                                    "WHERE ticket_id=? ORDER BY id", (tid,)).fetchall()]
        prs = [link["ref"] for link in t.get("links") or [] if link.get("provider") == "github" and link.get("kind") == "pr"]
        return dict(w, key=t["key"], status=t["status"], stage=stage, branch=t.get("branch"), prs=prs,
                    policy=policy(t), stages=self._stages(t["status"], stage), findings=findings)

    @staticmethod
    def _stages(status, stage):
        """PLAN … VERIFY as done / active / todo (BLOCKED marks its stage blocked)."""
        if status == "DONE":
            return [{"stage": s, "state": "done"} for s in STAGES[:-1]]
        at = STAGES.index(stage) if stage in STAGES else -1
        out = []
        for i, s in enumerate(STAGES[:-1]):
            state = "done" if i < at else "todo"
            if i == at:
                state = "blocked" if status == "BLOCKED" else "active"
            out.append({"stage": s, "state": state})
        return out

    def needs(self):
        """Open owner gates, for the one Needs Jay queue."""
        rows = self.db.execute(
            "SELECT t.key, t.project, t.title, t.status, w.gate, w.gate_reason, w.updated_at FROM ticket_work w "
            "JOIN tickets t ON t.id=w.ticket_id WHERE w.gate IS NOT NULL AND t.archived=0 "
            "AND t.status NOT IN ('DONE','DENIED','CANCELLED') ORDER BY w.updated_at").fetchall()
        what = {"plan": "Plan needs approval", "merge": "Ready to merge", "ui": "UI review",
                "deploy": "Deploy approval", "failure": "Blocked"}
        return [{"project": p, "ref": k, "text": f"{what[g]}: {reason or title}"[:300], "kind": "gate", "gate": g,
                 "url": None, "flags": [f"gate:{g}"], "status": st, "since": at}
                for k, p, title, st, g, reason, at in rows]

    def participating(self, key):
        """In the pipeline: an accepted plan or a recorded review. Its review state then belongs to the
        pipeline only — GitHub's reviewDecision never promotes it."""
        r = self.db.execute("SELECT plan_state, review_head FROM ticket_work w JOIN tickets t ON t.id=w.ticket_id "
                            "WHERE t.key=?", (str(key).upper(),)).fetchone()
        return bool(r) and (r[0] in ("proposed", "accepted") or r[1] is not None)

    def lanes(self):
        return self.db.execute(
            "SELECT COUNT(*) FROM tickets t JOIN ticket_work w ON w.ticket_id=t.id "
            "WHERE t.status='IN_PROGRESS' AND w.worktree IS NOT NULL").fetchone()[0]

    # ---------- writing ----------

    def _tx(self, key, actor, fn):
        """Run fn(tid, ticket, work, at) in one transaction; it returns (status_fields, work_fields, events)."""
        at = _now()
        self.ts._begin()
        try:
            tid = self.ts._id_of(key)
            t = self.ts.get(key)
            w = self._row(tid)
            if w is None:
                self.db.execute("INSERT INTO ticket_work(ticket_id, updated_at) VALUES (?,?)", (tid, at))
                w = self._row(tid)
            fields, work, events = fn(tid, t, w, at)
            changes = self.ts._apply(tid, fields, actor, at, trigger=events[0][1] if events else None) if fields else []
            if work:
                cols = ", ".join(f"{c}=?" for c in work)
                vals = [v if v is None or isinstance(v, (str, int, float)) else json.dumps(v) for v in work.values()]
                self.db.execute(f"UPDATE ticket_work SET {cols}, updated_at=? WHERE ticket_id=?", (*vals, at, tid))
            for kind, text, data in events:
                self.ts._audit(tid, actor, kind, trigger=text, data=data, at=at)
            self.ts._touch(tid, at)
            self.ts._commit()
        except BaseException:
            self.ts._rollback()
            raise
        return self.ts.get(key), changes, events

    @staticmethod
    def _need(t, statuses, op):
        if t["status"] not in statuses:
            raise TaskError(409, f"{t['key']} is {t['status']}; {op} needs {' or '.join(statuses)}")

    @staticmethod
    def _role(w, role, model=None, session=None, at=None):
        roles = dict(w["roles"])
        roles[role] = {"model": _meta(model, "model"), "session": _meta(session, "session"), "at": at}
        return roles

    def plan(self, key, raw, actor, model=None, session=None):
        plan = clean_plan(raw)

        def fn(tid, t, w, at):
            self._need(t, ("INBOX", "PROPOSED", "RESEARCHING", "READY_TO_IMPLEMENT"), "a plan")
            pol = policy(t)
            # A new plan needs a new approval: Jay approved the plan he saw, not this one. And a ticket
            # whose plan ever needed Jay keeps needing him ("owner:plan" is sticky), whatever its labels say now.
            sticky = "owner:plan" in w["confirmed"] or w["gate"] == "plan"
            confirmed = [g for g in w["confirmed"] if g != "plan"]
            work = {"plan": plan, "roles": self._role(w, "planner", model, session, at), "confirmed": confirmed}
            events = [("pipeline.plan", "plan recorded", {"owner": pol["plan"] == "owner"})]
            # Only Jay closes an open plan gate: a policy that has since become "auto" never does.
            if pol["plan"] == "owner" or sticky:
                reason = ", ".join(pol["planReasons"]) or "this ticket's plan needed Jay before"
                work.update(plan_state="proposed", gate="plan", gate_reason=reason,
                            confirmed=sorted(set(confirmed) | {"owner:plan"}))
                events.append(("pipeline.gate_opened", "plan gate: " + reason, {"gate": "plan"}))
                return ({"status": "RESEARCHING"} if t["status"] != "RESEARCHING" else {}), work, events
            work.update(plan_state="accepted", gate=None, gate_reason=None)
            events.append(("pipeline.plan_accepted", "plan accepted (no owner gate)", {}))
            return ({"status": "READY_TO_IMPLEMENT"} if t["status"] != "READY_TO_IMPLEMENT" else {}), work, events
        return self._tx(key, actor, fn)

    def start(self, key, branch, worktree, actor, model=None, session=None):
        def fn(tid, t, w, at):
            self._need(t, ("READY_TO_IMPLEMENT",), "start")
            if w["planState"] != "accepted":
                raise TaskError(409, f"{t['key']} has no accepted plan")
            if not isinstance(branch, str) or not re.match(rf"^{re.escape(t['key'])}-{SLUG_RE}$", branch):
                raise TaskError(400, f"branch must be {t['key']}-<short-slug> (lowercase, digits, hyphens)")
            if not isinstance(worktree, str) or not worktree.startswith("/") or len(worktree) > 300 \
                    or not re.match(r"^/[A-Za-z0-9._/-]+$", worktree) or "/../" in worktree + "/":
                raise TaskError(400, "worktree must be an absolute path")
            if self.lanes() >= self.max_lanes:
                raise TaskError(409, f"{self.max_lanes} implementation lanes are already running; wait for one to finish")
            work = {"worktree": worktree, "roles": self._role(w, "implementer", model, session, at)}
            return ({"status": "IN_PROGRESS", "branch": branch}, work,
                    [("pipeline.started", f"implementation started on {branch}", {"branch": branch})])
        return self._tx(key, actor, fn)

    def review(self, key, verdict, head, actor, findings=(), model=None, session=None, pr=None):
        if verdict not in ("APPROVE", "REQUEST_CHANGES"):
            raise TaskError(400, "verdict must be APPROVE or REQUEST_CHANGES")
        if not isinstance(head, str) or not SHA_RE.match(head):
            raise TaskError(400, "head must be the PR head commit SHA")
        rows = [self._finding(f) for f in (findings or [])]

        def fn(tid, t, w, at):
            self._need(t, ("IN_REVIEW", "READY_TO_MERGE"), "a review")
            roles = self._role(w, "reviewer", model, session, at)
            for f in rows:
                self.db.execute("INSERT INTO ticket_findings(ticket_id, at, source, scope, category, summary, head) "
                                "VALUES (?,?,?,?,?,?,?)", (tid, at, "review", f["scope"], f["category"], f["summary"], head))
            if verdict == "REQUEST_CHANGES":
                cycles = w["review"]["cycles"] + 1
                work = {"review_verdict": verdict, "review_head": head, "review_pr": (pr or {}).get("ref"),
                        "review_cycles": cycles, "roles": roles, "confirmed": _no_merge(w["confirmed"])}
                if w["gate"] == "merge":
                    work.update(gate=None, gate_reason=None)
                events = [("pipeline.review", f"changes requested at {head[:7]} (cycle {cycles})",
                           {"verdict": verdict, "head": head, "cycles": cycles, "findings": len(rows)})]
                status = {"status": "IN_REVIEW"} if t["status"] != "IN_REVIEW" else {}
                if cycles >= MAX_REVIEW_CYCLES:
                    reason = f"{cycles} review cycles requested changes"
                    work.update(gate="failure", gate_reason=reason, blocked={"stage": "REVIEW", "reason": reason, "at": at})
                    events.append(("pipeline.blocked", reason, {"stage": "REVIEW"}))
                    status = {"status": "BLOCKED"}
                return status, work, events
            work = {"review_verdict": verdict, "review_head": head, "review_pr": (pr or {}).get("ref"), "roles": roles}
            events = [("pipeline.review", f"approved at {head[:7]}", {"verdict": verdict, "head": head})]
            status = {}
            if t["status"] == "READY_TO_MERGE" and head != w["review"]["head"]:
                # A new head: re-decide from IN_REVIEW; a merge gate for the old head closes.
                status = {"status": "IN_REVIEW"}
                if w["gate"] == "merge":
                    work.update(gate=None, gate_reason=None)
                t = dict(t, status="IN_REVIEW")
            st2, more, ev = self._ready(t, dict(w, gate=work.get("gate", w["gate"]),
                                                review={"verdict": verdict, "head": head, "pr": (pr or {}).get("ref"),
                                                        "cycles": w["review"]["cycles"]}), pr)
            status = st2 or status
            work.update(more)
            return status, work, events + ev
        return self._tx(key, actor, fn)

    def _ready(self, t, w, pr):
        """IN_REVIEW → READY_TO_MERGE when the recorded approval covers the PR's current head and CI is green."""
        rv = w["review"]
        if t["status"] != "IN_REVIEW" or rv["verdict"] != "APPROVE" or not pr:
            return {}, {}, []
        if rv.get("pr") and pr.get("ref") != rv["pr"]:
            return {}, {}, []   # another PR on this ticket says nothing about the reviewed one
        if pr.get("head") != rv["head"] or not pr.get("ciGreen") or pr.get("draft"):
            return {}, {}, []
        work, events = {}, [("pipeline.ready_to_merge", f"approved head {rv['head'][:7]} with green checks", {})]
        if policy(t)["merge"] == "owner" and not _merge_ok(w["confirmed"], rv["head"]):
            work = {"gate": "merge", "gate_reason": f"PR {pr.get('ref') or ''} approved and green".strip()}
            events.append(("pipeline.gate_opened", "merge gate", {"gate": "merge"}))
        return {"status": "READY_TO_MERGE"}, work, events

    def sync_pr(self, key, pr):
        """ccd's GitHub poll, per linked PR: promote a covered approval, or invalidate a stale one."""
        def fn(tid, t, w, at):
            rv = w["review"]
            if rv.get("pr") and pr.get("ref") != rv["pr"]:
                return {}, {}, []
            if t["status"] == "READY_TO_MERGE" and rv["verdict"] == "APPROVE" and pr.get("head") \
                    and pr["head"] != rv["head"]:
                # The head stays recorded (the ticket is still in the pipeline); the approval and any
                # merge authorisation were for the old head, so both go.
                work = {"review_verdict": None, "confirmed": _no_merge(w["confirmed"]),
                        "gate": None if w["gate"] == "merge" else w["gate"],
                        "gate_reason": None if w["gate"] == "merge" else w["gateReason"]}
                return {"status": "IN_REVIEW"}, work, [("pipeline.review_stale",
                                                        f"new PR head {pr['head'][:7]}; approval was for {rv['head'][:7]}",
                                                        {"head": pr["head"]})]
            if t["status"] == "READY_TO_MERGE" and rv["verdict"] == "APPROVE" and (not pr.get("ciGreen") or pr.get("draft")):
                why = "checks are not green" if not pr.get("ciGreen") else "the PR is a draft again"
                work = {"gate": None, "gate_reason": None} if w["gate"] == "merge" else {}
                return {"status": "IN_REVIEW"}, work, [("pipeline.not_ready", f"back to review: {why}", {})]
            return self._ready(t, w, pr)
        t = self.ts.get(key)
        if t["status"] not in ("IN_REVIEW", "READY_TO_MERGE"):
            return t, [], []
        return self._tx(key, "system:automation", fn)

    def merged(self, key, pr_ref, sha=None):
        """A linked PR merged (the GitHub poll moved the ticket to VERIFYING): record it, close the merge gate."""
        def fn(tid, t, w, at):
            work = {"merge": {"pr": pr_ref, "sha": sha, "at": at}}
            if w["gate"] == "merge":
                work.update(gate=None, gate_reason=None)
            events = [("pipeline.merged", f"{pr_ref} merged", {"pr": pr_ref, "sha": sha})]
            rv = w["review"]
            if rv["verdict"] != "APPROVE":
                events.append(("pipeline.unreviewed_merge", f"{pr_ref} merged without a recorded approval", {}))
            return {}, work, events
        t = self.ts.get(key)
        tid = self.ts._id_of(key)
        if t["status"] != "VERIFYING" or ((self._row(tid) or {}).get("merge") or {}).get("pr") == pr_ref:
            return t, [], []
        return self._tx(key, "system:automation", fn)

    def verify(self, key, result, evidence, actor, model=None, session=None):
        if result not in ("pass", "fail"):
            raise TaskError(400, "result must be pass or fail")
        evidence = _text(evidence, 2000, "evidence")
        if not evidence:
            raise TaskError(400, "say what was verified")

        def fn(tid, t, w, at):
            self._need(t, ("VERIFYING",), "verification")
            work = {"verification": {"result": result, "evidence": evidence, "at": at, "by": actor},
                    "roles": self._role(w, "verifier", model, session, at)}
            if result == "fail":
                reason = f"verification failed: {evidence}"[:300]
                work.update(gate="failure", gate_reason=reason, blocked={"stage": "VERIFY", "reason": reason, "at": at})
                return {"status": "BLOCKED"}, work, [("pipeline.blocked", reason, {"stage": "VERIFY"})]
            status, more, events = self._after_verify(t, w)
            work.update(more)
            return status, work, [("pipeline.verified", "verification passed", {})] + events
        return self._tx(key, actor, fn)

    def _after_verify(self, t, w):
        pol = policy(t)
        for g, on in (("ui", pol["ui"]), ("deploy", pol["deploy"])):
            if on and g not in w["confirmed"]:
                return {}, {"gate": g, "gate_reason": "verified; owner check left"}, \
                    [("pipeline.gate_opened", f"{g} gate", {"gate": g})]
        return {"status": "DONE"}, {"gate": None, "gate_reason": None}, [("pipeline.done", "done", {})]

    def confirm(self, key, gate, actor):
        """Jay closes an owner gate. Only `jay` (and the API also requires Developer Unlock)."""
        if actor != "jay":
            raise TaskError(403, "only Jay closes an owner gate")
        if gate not in GATES:
            raise TaskError(400, f"gate must be one of {', '.join(GATES)}")

        def fn(tid, t, w, at):
            if w["gate"] != gate:
                raise TaskError(409, f"{t['key']} has no open {gate} gate")
            add = {f"merge:{w['review']['head']}"} if gate == "merge" else {gate} - {"failure"}
            confirmed = sorted(set(w["confirmed"]) | add)
            work = {"confirmed": confirmed, "gate": None, "gate_reason": None}
            events = [("pipeline.gate_confirmed", f"Jay confirmed the {gate} gate", {"gate": gate})]
            if gate == "plan":
                work["plan_state"] = "accepted"
                return {"status": "READY_TO_IMPLEMENT"}, work, events
            if gate == "failure":
                stage = (w["blocked"] or {}).get("stage") or "PLAN"
                if stage == "BUILD" and self.lanes() >= self.max_lanes:
                    raise TaskError(409, f"{self.max_lanes} implementation lanes are running; resume this one later")
                work.update(blocked=None, review_cycles=0 if stage == "REVIEW" else w["review"]["cycles"])
                return {"status": RESUME_STATUS.get(stage, "RESEARCHING")}, work, events
            if gate in ("ui", "deploy") and t["status"] == "VERIFYING" and (w["verification"] or {}).get("result") == "pass":
                status, more, ev = self._after_verify(t, dict(w, confirmed=confirmed))
                work.update(more)
                return status, work, events + ev
            return {}, work, events
        return self._tx(key, actor, fn)

    def handoff(self, key, body, actor):
        if not isinstance(body, dict):
            raise TaskError(400, "handoff must be an object")
        h = {k: _text(body.get(k), 2000, k) for k in ("done", "decisions", "next", "blockers")}
        if not any(h.values()):
            raise TaskError(400, "a handoff says at least one of done, decisions, next, blockers")
        return self._tx(key, actor, lambda tid, t, w, at: ({}, {"handoff": dict(h, at=at, by=actor)},
                                                          [("pipeline.handoff", "handoff updated", {})]))

    def block(self, key, reason, actor):
        reason = _text(reason, 300, "reason", multiline=False)
        if not reason:
            raise TaskError(400, "say why it is blocked")

        def fn(tid, t, w, at):
            stage = stage_of(t["status"])
            if not stage or stage == "DONE":
                raise TaskError(409, f"{t['key']} is {t['status']}; nothing to block")
            return {"status": "BLOCKED"}, {"gate": "failure", "gate_reason": reason,
                                           "blocked": {"stage": stage, "reason": reason, "at": at}}, \
                [("pipeline.blocked", reason, {"stage": stage})]
        return self._tx(key, actor, fn)

    def role(self, key, role, actor, model=None, session=None):
        if role not in ROLE_NAMES:
            raise TaskError(400, f"role must be one of {', '.join(ROLE_NAMES)}")
        return self._tx(key, actor, lambda tid, t, w, at: ({}, {"roles": self._role(w, role, model, session, at)},
                                                          [("pipeline.role", f"{role} reported", {"role": role})]))

    @staticmethod
    def _finding(f):
        if not isinstance(f, dict):
            raise TaskError(400, "each finding is an object")
        scope = f.get("scope", "in")
        cat = f.get("category") or "general"
        if scope not in ("in", "out") or not isinstance(cat, str) or not CATEGORY_RE.match(cat):
            raise TaskError(400, "finding scope is in|out; category is a short lowercase word")
        summary = _text(f.get("summary"), 2000, "summary")
        if not summary:
            raise TaskError(400, "a finding needs a summary")
        return {"scope": scope, "category": cat, "summary": summary}

    def finding(self, key, f, actor, source="review"):
        if source not in ("review", "owner", "verifier"):
            raise TaskError(400, "source must be review, owner or verifier")
        row = self._finding(f)

        def fn(tid, t, w, at):
            self.db.execute("INSERT INTO ticket_findings(ticket_id, at, source, scope, category, summary) "
                            "VALUES (?,?,?,?,?,?)", (tid, at, source, row["scope"], row["category"], row["summary"]))
            return {}, {}, [("pipeline.finding", f"{source} finding ({row['scope']} scope)", {"category": row["category"]})]
        return self._tx(key, actor, fn)
