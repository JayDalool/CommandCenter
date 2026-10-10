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
MERGE_POLICIES = ("owner", "low-risk")   # registry pipeline "merge"; "owner" is the default
AUTO_MERGE_KINDS = ("pipeline.auto_merge_held", "pipeline.auto_merged", "pipeline.auto_merge_failed")
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
    if merge not in MERGE_POLICIES:     # the retired "auto", or a typo: Jay accepts
        merge = "owner"
    return {
        "plan": "owner" if reasons else "auto",
        "planReasons": reasons,
        "merge": merge,
        "ui": "needs_ui_review" in flags or ticket.get("type") == "DESIGN" or "ui" in labels,
        "deploy": "needs_deploy" in flags,
    }


CLOSED_STATUSES = ("DONE", "DENIED", "CANCELLED")
HOLDING_GATES = ("plan", "failure")       # jay_first: Jay's decisions that hold a ticket (questions too)
STALE_OPTIONS = ("Cancel it", "Keep it")   # the task check's question; "Cancel it" cancels the ticket
# The ten stages Jay sees (spec §24). The canonical statuses stay as they are underneath.
VISIBLE_STAGES = ("Planning", "Implementing", "Reviewing", "UI Testing", "Verifying", "Ready to Merge", "Deploying",
                  "Needs Jay", "Blocked", "Closed")


def visible_stage(t, w=None):
    """One of VISIBLE_STAGES for a ticket and (optionally) its work state."""
    w = w or {}
    st = t["status"]
    gate = w.get("gate")
    if st in CLOSED_STATUSES:
        return "Closed"
    if st == "BLOCKED" or gate == "failure":
        return "Blocked"
    if w.get("openQuestions") or gate in ("plan", "merge", "ui", "deploy"):
        return "Needs Jay"
    flags = set(t.get("flags") or [])
    if "needs_jay" in flags and st in ("INBOX", "PROPOSED"):
        return "Needs Jay"
    d = w.get("deploy") or {}
    if d.get("approvedAt") and not d.get("result"):
        return "Deploying"
    stage = STAGE_OF.get(st)
    if stage == "PLAN":
        return "Planning"
    if stage == "BUILD":
        return "Implementing"
    if stage == "REVIEW":
        return "Reviewing"
    if stage == "MERGE":
        return "Ready to Merge"
    if stage == "VERIFY":
        pol = w.get("policy") or policy(t)
        return "UI Testing" if pol["ui"] and not w.get("verification") else "Verifying"
    return "Planning"


def needs_acceptance(t, w):
    """Gate 3 — Jay accepts before a merge when the project says so ("owner"), the change is user-facing or UI,
    the ticket is flagged needs:jay, or its plan changed after it was approved (a re-plan). A "low-risk"
    project needs no acceptance up front: ccd's classifier decides at merge time and opens the merge gate
    itself (Pipeline.hold_merge) when the PR does not qualify."""
    pol = policy(t)
    flags = {f.replace(":", "_").replace("-", "_") for f in t.get("flags") or []}
    return pol["merge"] == "owner" or pol["ui"] or "needs_jay" in flags or "owner:accept" in (w.get("confirmed") or [])


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
        # Whether ccd's auto-merge is switched on (config.json `auto_merge`, set by the daemon). While it is off,
        # a "low-risk" project behaves like "owner": a ready PR opens a merge gate for Jay.
        self.auto_merge = False

    # ---------- reading ----------

    def _row(self, tid):
        r = self.db.execute("SELECT plan, plan_state, gate, gate_reason, confirmed, worktree, roles, review_verdict, "
                            "review_head, review_cycles, verification, handoff, blocked, merge, updated_at, review_pr, "
                            "writer, checkpoint, deploy, released FROM ticket_work WHERE ticket_id=?", (tid,)).fetchone()
        if not r:
            return None
        j = lambda v, d: json.loads(v) if v else d  # noqa: E731
        return {"plan": j(r[0], {}), "planState": r[1], "gate": r[2], "gateReason": r[3], "confirmed": j(r[4], []),
                "worktree": r[5], "roles": j(r[6], {}),
                "review": {"verdict": r[7], "head": r[8], "cycles": r[9], "pr": r[15]},
                "verification": j(r[10], None), "handoff": j(r[11], None), "blocked": j(r[12], None),
                "merge": j(r[13], None), "updatedAt": r[14], "writer": r[16], "checkpoint": j(r[17], None),
                "deploy": j(r[18], None), "released": j(r[19], None)}

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
                               "verification": None, "handoff": None, "blocked": None, "merge": None, "updatedAt": None,
                               "writer": None, "checkpoint": None, "deploy": None, "released": None}
        stage = stage_of(t["status"]) or ((w.get("blocked") or {}).get("stage") if t["status"] == "BLOCKED" else None)
        findings = [{"at": a, "source": s, "scope": sc, "category": c, "summary": m, "head": h} for a, s, sc, c, m, h in
                    self.db.execute("SELECT at, source, scope, category, summary, head FROM ticket_findings "
                                    "WHERE ticket_id=? ORDER BY id", (tid,)).fetchall()]
        prs = [link["ref"] for link in t.get("links") or [] if link.get("provider") == "github" and link.get("kind") == "pr"]
        questions = self.questions(tid)
        evidence = [{"id": i, "at": a, "actor": ac, "stage": st, "kind": k, "ref": ref, "note": n}
                    for i, a, ac, st, k, ref, n in self.db.execute(
                        "SELECT id, at, actor, stage, kind, ref, note FROM ticket_evidence WHERE ticket_id=? ORDER BY id",
                        (tid,)).fetchall()]
        out = dict(w, key=t["key"], status=t["status"], stage=stage, branch=t.get("branch"), prs=prs,
                   policy=policy(t), stages=self._stages(t["status"], stage), findings=findings,
                   questions=questions, openQuestions=sum(1 for q in questions if q["answer"] is None),
                   evidence=evidence)
        out["visibleStage"] = visible_stage(t, out)
        return out

    def questions(self, tid):
        return [{"id": i, "batch": b, "position": pos, "text": tx, "kind": k, "options": json.loads(o or "[]"),
                 "askedAt": aa, "askedBy": ab, "answer": an, "answeredAt": at, "answeredBy": by, "purpose": pu}
                for i, b, pos, tx, k, o, aa, ab, an, at, by, pu in self.db.execute(
                    "SELECT id, batch, position, text, kind, options, asked_at, asked_by, answer, answered_at, answered_by, "
                    "purpose FROM ticket_questions WHERE ticket_id=? ORDER BY batch, position", (tid,)).fetchall()]

    def compact(self, ids):
        """{ticket id: {gate, openQuestions, deploy}} for the ticket list, in two queries."""
        ids = list(ids)
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for tid, gate, reason, deploy, verification in self.db.execute(
                    f"SELECT ticket_id, gate, gate_reason, deploy, verification FROM ticket_work WHERE ticket_id IN ({marks})",
                    chunk):
                d = json.loads(deploy) if deploy else None
                v = json.loads(verification) if verification else None
                out[tid] = {"gate": gate, "gateReason": reason, "openQuestions": 0,
                            "deploy": {k: d.get(k) for k in ("env", "requestedAt", "approvedAt", "result")} if d else None,
                            "verification": {"result": v.get("result")} if v else None}
            for tid, n in self.db.execute(f"SELECT ticket_id, COUNT(*) FROM ticket_questions WHERE answered_at IS NULL "
                                          f"AND ticket_id IN ({marks}) GROUP BY ticket_id", chunk):
                out.setdefault(tid, {"gate": None, "gateReason": None, "deploy": None, "verification": None})["openQuestions"] = n
        return out

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
        out = [{"project": p, "ref": k, "text": f"{what[g]}: {reason or title}"[:300], "kind": "gate", "gate": g,
                "url": None, "flags": [f"gate:{g}"], "status": st, "since": at}
               for k, p, title, st, g, reason, at in rows]
        gated = {o["ref"] for o in out}
        for k, p, title, st, n, stale, at in self.db.execute(
                "SELECT t.key, t.project, t.title, t.status, COUNT(*), SUM(q.purpose IS 'stale'), MIN(q.asked_at) "
                "FROM ticket_questions q JOIN tickets t ON t.id=q.ticket_id WHERE q.answered_at IS NULL AND t.archived=0 "
                "AND t.status NOT IN ('DONE','DENIED','CANCELLED') GROUP BY t.id ORDER BY MIN(q.asked_at)").fetchall():
            text = (f"Task check — still needed? {title}" if stale == n
                    else f"Claude needs {n} answer{'s' if n > 1 else ''}: {title}")
            item = {"project": p, "ref": k, "text": text[:300], "kind": "questions", "gate": None, "questions": n,
                    "stale": bool(stale), "url": None, "flags": ["questions"] + (["stale"] if stale else []),
                    "status": st, "since": at}
            if k in gated:   # one item per ticket: the questions come first, they are what unblocks it
                out = [o for o in out if o["ref"] != k]
            out.append(item)
        return out

    def gate_counts(self):
        """Two integers for the unauthenticated /api/health (the desktop launcher reads them): how many owner
        gates are open, and the id of the newest pipeline.gate_opened / pipeline.blocked event (ticket_events
        is append-only, so the id only grows). Counts only: no keys, titles or reasons."""
        (n,) = self.db.execute(
            "SELECT COUNT(*) FROM ticket_work w JOIN tickets t ON t.id=w.ticket_id WHERE w.gate IS NOT NULL "
            "AND t.archived=0 AND t.status NOT IN ('DONE','DENIED','CANCELLED')").fetchone()
        # no index on kind: SQLite reads ticket_events backwards from the newest id and stops at the first match
        r = self.db.execute("SELECT id FROM ticket_events WHERE kind IN ('pipeline.gate_opened','pipeline.blocked') "
                            "ORDER BY id DESC LIMIT 1").fetchone()
        return {"open": int(n), "last": int(r[0]) if r else 0}

    def held(self, key):
        """What makes this ticket wait for Jay (registry `jay_first`, default on): an open question for Jay, a
        plan to approve or a blocker only he can clear — on this ticket, or on an open ticket it is blocked by.
        Every other ticket goes ahead. Sign-offs on finished work (merge acceptance, UI review, live deploy) do
        not hold; a blocking ticket that needs a lawyer (needs:legal, type LEGAL) waits on the lawyer, not Jay."""
        t = self.db.execute("SELECT id, key, project FROM tickets WHERE key=?", (str(key).upper(),)).fetchone()
        if not t or not registry.pipeline_of(t[2]).get("jay_first", True):
            return []
        blockers = {k for (k,) in self.db.execute(
            "SELECT b.key FROM ticket_relations r JOIN tickets b ON b.id=r.src_id WHERE r.dst_id=? AND r.kind='blocks' "
            "AND b.status NOT IN ('DONE','DENIED','CANCELLED') AND b.needs_legal=0 AND COALESCE(b.type,'')!='LEGAL'",
            (t[0],))}
        refs = blockers | {t[1]}
        return [n for n in self.needs() if n["ref"] in refs
                and (n["kind"] == "questions" or n.get("gate") in HOLDING_GATES)]

    def participating(self, key):
        """In the pipeline: an accepted plan or a recorded review. Its review state then belongs to the
        pipeline only — GitHub's reviewDecision never promotes it."""
        r = self.db.execute("SELECT plan_state, review_head FROM ticket_work w JOIN tickets t ON t.id=w.ticket_id "
                            "WHERE t.key=?", (str(key).upper(),)).fetchone()
        return bool(r) and (r[0] in ("proposed", "accepted") or r[1] is not None)

    def review_head(self, key):
        """The PR head a review was last recorded at, or None before any review."""
        r = self.db.execute("SELECT review_head FROM ticket_work w JOIN tickets t ON t.id=w.ticket_id "
                            "WHERE t.key=?", (str(key).upper(),)).fetchone()
        return r[0] if r else None

    def rework_prs(self, key):
        """The open PRs {(ref, head)} recorded by the ticket's latest rework, or None if it never had one."""
        r = self.db.execute("SELECT e.data FROM ticket_events e JOIN tickets t ON t.id=e.ticket_id "
                            "WHERE t.key=? AND e.kind='pipeline.rework' ORDER BY e.id DESC LIMIT 1",
                            (str(key).upper(),)).fetchone()
        if not r:
            return None
        prs = json.loads(r[0] or "{}").get("prs") or []
        return {(p.get("ref"), p.get("head")) for p in prs if isinstance(p, dict)}

    def new_head(self, key, pr):
        """True when this (PR, head) is one the pipeline has not already dealt with: not the reviewed head, and
        not an open PR recorded when the ticket was last sent back to implementation. Only such a head or
        PR sends a reworked ticket back to IN_REVIEW. (As in sync_pr, an unrecorded review PR matches any PR.)"""
        if (pr.get("ref"), pr.get("head")) in (self.rework_prs(key) or ()):
            return False
        r = self.db.execute("SELECT review_head, review_pr FROM ticket_work w JOIN tickets t ON t.id=w.ticket_id "
                            "WHERE t.key=?", (str(key).upper(),)).fetchone()
        if not r or not r[0]:
            return True
        return not (pr.get("head") == r[0] and (not r[1] or pr.get("ref") == r[1]))

    def lanes(self, project):
        """Implementation lanes running in one project: its tickets IN_PROGRESS with a worktree."""
        return self.db.execute(
            "SELECT COUNT(*) FROM tickets t JOIN ticket_work w ON w.ticket_id=t.id "
            "WHERE t.status='IN_PROGRESS' AND w.worktree IS NOT NULL AND t.project=?", (project,)).fetchone()[0]

    def lane_limit(self, project):
        """At most this many implementation lanes per project (registry pipeline `max_lanes`, else the default)."""
        return int(registry.pipeline_of(project).get("max_lanes") or self.max_lanes)

    def _lane_free(self, t, what="wait for one to finish"):
        limit = self.lane_limit(t["project"])
        if self.lanes(t["project"]) >= limit:
            raise TaskError(409, f"{limit} implementation lanes are already running in {t['project']}; {what}")

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
            self._lane_free(t)
            held = self.held(t["key"])
            if held:
                refs = ", ".join(sorted({h["ref"] for h in held}))
                raise TaskError(409, f"{t['key']} waits for Jay: open question(s) or decision(s) on {refs[:200]}. "
                                     f"Leave it for him and take another task.")
            # The implementation runs in the ticket's task session (spec §8) unless another is named, so the
            # implementer always has a recorded session a reviewer must differ from.
            work = {"worktree": worktree, "roles": self._role(w, "implementer", model, session or t["key"].lower(), at)}
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
            impl = (w["roles"].get("implementer") or {})
            if verdict == "APPROVE":
                own = {x for x in (impl.get("session"), t["key"].lower(), t["key"]) if x}
                if actor == "agent:implementer" or (session and session in own):
                    raise TaskError(409, "the implementer cannot approve its own work; a fresh reviewer must")
                if not session:
                    raise TaskError(400, "say which fresh reviewer session approves (--session)")
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

    def _gate_due(self, t, w, head):
        """Jay must accept this merge and has not: the project is `owner`, or the ticket needs acceptance, or the
        project is `low-risk` while ccd's auto-merge is switched off; and no `merge:<head>` approval is recorded."""
        low_risk_off = policy(t)["merge"] == "low-risk" and not self.auto_merge
        return (needs_acceptance(t, w) or low_risk_off) and not _merge_ok(w["confirmed"], head)

    def _ready(self, t, w, pr):
        """IN_REVIEW → READY_TO_MERGE when the recorded approval covers the PR's current head and CI is green."""
        rv = w["review"]
        if t["status"] != "IN_REVIEW" or rv["verdict"] != "APPROVE" or not pr:
            return {}, {}, []
        if rv.get("pr") and pr.get("ref") != rv["pr"]:
            return {}, {}, []   # another PR on this ticket says nothing about the reviewed one
        if pr.get("head") != rv["head"] or not pr.get("ciGreen") or pr.get("draft"):
            return {}, {}, []
        # "–" (no checks configured) counts as ready, but the record must not call it green.
        none = bool(pr.get("ciNone"))
        work, events = {}, [("pipeline.ready_to_merge",
                             f"approved head {rv['head'][:7]} with {'no CI checks' if none else 'green checks'}",
                             {"ci": "none" if none else "green"})]
        if self._gate_due(t, w, rv["head"]):
            work = {"gate": "merge",
                    "gate_reason": f"PR {pr.get('ref') or ''} approved and {'has no CI checks' if none else 'green'}".strip()}
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
            if t["status"] == "READY_TO_MERGE" and rv["verdict"] == "APPROVE" and pr.get("head") == rv["head"] \
                    and not w["gate"] and self._gate_due(t, w, rv["head"]):
                # Ready before the rules changed (or before auto-merge was switched off): the merge gate that
                # `_ready` opens only on the IN_REVIEW → READY_TO_MERGE move is opened now, so it is in Needs Jay.
                none = bool(pr.get("ciNone"))
                return {}, {"gate": "merge", "gate_reason": f"PR {pr.get('ref') or ''} approved and "
                                                            f"{'has no CI checks' if none else 'green'}".strip()}, \
                    [("pipeline.gate_opened", "merge gate", {"gate": "merge"})]
            return self._ready(t, w, pr)
        t = self.ts.get(key)
        if t["status"] not in ("IN_REVIEW", "READY_TO_MERGE"):
            return t, [], []
        return self._tx(key, "system:automation", fn)

    def merge_candidates(self, project):
        """Keys of the project's tickets ccd's auto-merge should look at: READY_TO_MERGE, no gate open, an
        approving review recorded, Jay's `merge:<head>` decision not given, and nothing recorded yet for that
        reviewed head (a hold, a merge or a failure is final for a head: only a new head, which needs a new review,
        makes it a candidate again)."""
        out = []
        for key, tid, head, confirmed in self.db.execute(
                "SELECT t.key, t.id, w.review_head, w.confirmed FROM tickets t JOIN ticket_work w ON w.ticket_id=t.id "
                "WHERE t.project=? AND t.status='READY_TO_MERGE' AND t.archived=0 AND w.gate IS NULL "
                "AND w.review_verdict='APPROVE' AND w.review_head IS NOT NULL ORDER BY t.id", (project,)).fetchall():
            if _merge_ok(json.loads(confirmed) if confirmed else [], head):
                continue    # Jay already decided about this head (he closed a merge gate): ccd does not second-guess
            if not self.auto_merge_marked(tid, head):
                out.append(key)
        return out

    def auto_merge_marked(self, tid, head):
        """True when the latest auto-merge event on this ticket (held, merged or failed) is for this head."""
        marks = ",".join("?" * len(AUTO_MERGE_KINDS))
        r = self.db.execute(f"SELECT data FROM ticket_events WHERE ticket_id=? AND kind IN ({marks}) "
                            "ORDER BY id DESC LIMIT 1", (tid, *AUTO_MERGE_KINDS)).fetchone()
        return bool(r) and json.loads(r[0] or "{}").get("head") == head

    def hold_merge(self, key, head, reason, failed=False):
        """ccd's auto-merge would not (or could not) merge this ticket's PR at `head`: open a merge gate in Needs
        Jay with the reason and record why. Never reopens a gate that is already open, and does nothing when
        `head` is not the reviewed head any more or the ticket has left READY_TO_MERGE."""
        reason = _text(re.sub(r"[\x00-\x1f\x7f]+", " ", str(reason or "")).strip()[:280], 280, "reason",
                       multiline=False) or "no reason given"
        kind = "pipeline.auto_merge_failed" if failed else "pipeline.auto_merge_held"
        said = "auto-merge failed" if failed else "auto-merge held"

        def fn(tid, t, w, at):
            if t["status"] != "READY_TO_MERGE" or w["gate"] or w["review"]["head"] != head:
                return {}, {}, []
            return {}, {"gate": "merge", "gate_reason": f"{said}: {reason}"[:300]}, \
                [(kind, f"{said} at {str(head)[:7]}: {reason}", {"head": head, "reason": reason}),
                 ("pipeline.gate_opened", "merge gate", {"gate": "merge"})]
        return self._tx(key, "system:auto-merge", fn)

    def auto_merged(self, key, head, pr_ref, ci):
        """ccd merged the PR (gh succeeded). Records it; the ticket moves to VERIFYING when the GitHub poll sees the
        merge, through `merged()` as for any merge. `ci` is "none" or "green": the text never says green for none."""
        checks = "no CI checks" if ci == "none" else "CI green"
        return self._tx(key, "system:auto-merge", lambda tid, t, w, at: (
            {}, {}, [("pipeline.auto_merged", f"{pr_ref} merged by ccd at {str(head)[:7]} ({checks})",
                      {"head": head, "pr": pr_ref, "ci": ci})]))

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
        d = w.get("deploy") or {}
        if d.get("requestedAt") and d.get("result") != "pass":
            # A live deployment was asked for: the ticket closes only once it is deployed and verified live.
            # Its deploy gate (if Jay has not approved yet) stays open.
            return {}, {}, []
        return {"status": "DONE"}, {"gate": None, "gate_reason": None}, [("pipeline.done", "done", {})]

    def confirm(self, key, gate, actor, via=None):
        """Jay closes an owner gate. Only `jay` (and the API also requires Developer Unlock). `via="go-live"` marks a
        live-deploy approval given by Go Live: approvedBy "jay:go-live", and the event says the deploy was approved
        for a PREPARED deploy that Jay confirms in the coordinator's pane. The record still permits `deployed`
        (the pane confirmation is Jay's, and nothing here can check it)."""
        if actor != "jay":
            raise TaskError(403, "only Jay closes an owner gate")
        if gate not in GATES:
            raise TaskError(400, f"gate must be one of {', '.join(GATES)}")
        by = f"{actor}:{via}" if via else actor
        said = ("approved for a prepared deploy (Jay confirms in the pane)" if via == "go-live"
                else "Jay approved the live deployment")

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
                if stage == "BUILD":
                    self._lane_free(t, "resume this one later")
                work.update(blocked=None, review_cycles=0 if stage == "REVIEW" else w["review"]["cycles"])
                return {"status": RESUME_STATUS.get(stage, "RESEARCHING")}, work, events
            if gate == "deploy" and not (w["deploy"] or {}).get("requestedAt"):
                # The deploy gate came from the ticket's needs:deploy flag, with no request yet: Jay's
                # approval IS the request. Nothing is deployed by clicking — the agent deploys next, records
                # it with `deployed --env live`, and only then does the ticket close.
                work["deploy"] = {"env": "live", "what": t["title"], "verification": (w["verification"] or {}).get("evidence") or "",
                                  "requestedAt": at, "requestedBy": "policy:needs_deploy", "approvedAt": at,
                                  "approvedBy": by, "result": None}
                events.append(("pipeline.deploy_approved", said, {}))
                return {}, work, events
            if gate == "deploy" and (w["deploy"] or {}).get("requestedAt") and not (w["deploy"] or {}).get("result"):
                # Jay approved a live deployment that has not happened yet: the agent deploys next and
                # records it with `deployed`; the ticket closes only after that, verified live.
                work["deploy"] = dict(w["deploy"], approvedAt=at, approvedBy=by)
                events.append(("pipeline.deploy_approved", said, {}))
                return {}, work, events
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

    EXPLAIN = ("what", "why", "action", "impact", "technical")

    def block(self, key, reason, actor, explain=None):
        """Blocked, explained for a manager first (what happened, why it matters, recommended action,
        estimated impact) with the technical details kept underneath."""
        reason = _text(reason, 300, "reason", multiline=False)
        if not reason:
            raise TaskError(400, "say why it is blocked")
        if explain is not None and not isinstance(explain, dict):
            raise TaskError(400, "explain must be an object")
        more = {k: _text((explain or {}).get(k), 4000 if k == "technical" else 2000, k) for k in self.EXPLAIN}
        more = {k: v for k, v in more.items() if v}

        def fn(tid, t, w, at):
            stage = stage_of(t["status"])
            if not stage or stage == "DONE":
                raise TaskError(409, f"{t['key']} is {t['status']}; nothing to block")
            return {"status": "BLOCKED"}, {"gate": "failure", "gate_reason": reason,
                                           "blocked": dict(more, stage=stage, reason=reason, at=at)}, \
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

    # ---------- the control room (plans/COMMAND-CENTER-CONTROL-ROOM.md) ----------

    QUESTION_KINDS = ("text", "choice", "yesno")
    EVIDENCE_KINDS = ("screenshot", "image", "link", "file", "test", "pr", "ci", "deploy", "note")
    WRITERS = ("claude", "codex", "jay", "none")
    DEPLOY_ENVS = ("live", "preview", "dev")
    MAX_QUESTIONS = 10

    def _open(self, t, op):
        if t["status"] in CLOSED_STATUSES:
            raise TaskError(409, f"{t['key']} is {t['status']}; {op} needs an open ticket")

    def ask(self, key, questions, actor):
        """Claude needs answers: one batch of structured questions. Waiting never ends the task session."""
        if isinstance(questions, (str, dict)):
            questions = [questions]
        if not isinstance(questions, list) or not 1 <= len(questions) <= self.MAX_QUESTIONS:
            raise TaskError(400, f"questions must be a list of 1–{self.MAX_QUESTIONS}")
        rows = []
        for q in questions:
            q = {"text": q} if isinstance(q, str) else q
            if not isinstance(q, dict):
                raise TaskError(400, "each question is text or {text, kind, options}")
            text = _text(q.get("text"), 1000, "question")
            kind = q.get("kind") or ("choice" if q.get("options") else "text")
            if not text or kind not in self.QUESTION_KINDS:
                raise TaskError(400, "a question needs text; kind is text, choice or yesno")
            options = _list(q.get("options"), "options", 8, 200) if kind == "choice" else []
            if kind == "choice" and len(options) < 2:
                raise TaskError(400, "a choice question needs at least two options")
            rows.append((text, kind, options))

        def fn(tid, t, w, at):
            self._open(t, "a question")
            batch = (self.db.execute("SELECT MAX(batch) FROM ticket_questions WHERE ticket_id=?", (tid,)).fetchone()[0]
                     or 0) + 1
            for i, (text, kind, options) in enumerate(rows):
                self.db.execute("INSERT INTO ticket_questions(ticket_id, batch, position, text, kind, options, asked_at, "
                                "asked_by) VALUES (?,?,?,?,?,?,?,?)", (tid, batch, i, text, kind, json.dumps(options), at, actor))
            n = len(rows)
            return {}, {}, [("pipeline.questions", f"Claude needs {n} answer{'s' if n > 1 else ''}",
                             {"batch": batch, "count": n})]
        return self._tx(key, actor, fn)

    def stale(self, key, reason, actor):
        """The task check: Claude thinks this task is no longer needed. Jay gets one question — Cancel it or
        Keep it — and only his answer changes anything (daemon.task_answers cancels on "Cancel it")."""
        reason = _text(reason, 300, "reason", multiline=False)
        if not reason:
            raise TaskError(400, "reason required: why this task is stale (what replaced it, or that it is done)")

        def fn(tid, t, w, at):
            self._open(t, "a stale proposal")
            if self.db.execute("SELECT 1 FROM ticket_questions WHERE ticket_id=? AND purpose='stale' "
                               "AND answered_at IS NULL", (tid,)).fetchone():
                raise TaskError(409, f"{t['key']} already has an open stale proposal for Jay")
            batch = (self.db.execute("SELECT MAX(batch) FROM ticket_questions WHERE ticket_id=?", (tid,)).fetchone()[0]
                     or 0) + 1
            self.db.execute("INSERT INTO ticket_questions(ticket_id, batch, position, text, kind, options, asked_at, "
                            "asked_by, purpose) VALUES (?,?,0,?,'choice',?,?,?,'stale')",
                            (tid, batch, f"Task check: Claude thinks this task is no longer needed — {reason}",
                             json.dumps(list(STALE_OPTIONS)), at, actor))
            return {}, {}, [("pipeline.stale", f"proposed as stale: {reason}", {"batch": batch})]
        return self._tx(key, actor, fn)

    def answer(self, key, answers, actor):
        """Jay's answers. Only Jay; each question once. Returns (ticket, changes, events)."""
        if actor != "jay":
            raise TaskError(403, "only Jay answers questions")
        if not isinstance(answers, list) or len(answers) > 50:
            raise TaskError(400, "answers must be a list of {id, answer}")
        clean = []
        for a in answers:
            if not isinstance(a, dict) or not isinstance(a.get("id"), int):
                raise TaskError(400, "each answer is {id, answer}")
            text = _text(a.get("answer"), 4000, "answer")
            if not text:
                raise TaskError(400, "an answer cannot be empty")
            clean.append((a["id"], text))

        def fn(tid, t, w, at):
            self._open(t, "an answer")
            for qid, text in clean:
                row = self.db.execute("SELECT kind, options, answered_at FROM ticket_questions WHERE id=? AND ticket_id=?",
                                      (qid, tid)).fetchone()
                if not row:
                    raise TaskError(404, f"no question {qid} on {t['key']}")
                if row[2] is not None:
                    raise TaskError(409, f"question {qid} is already answered")
                if row[0] == "yesno" and text.lower() not in ("yes", "no") and not text.lower().startswith("other:"):
                    raise TaskError(400, f"question {qid} is yes / no (or Other: …)")
                self.db.execute("UPDATE ticket_questions SET answer=?, answered_at=?, answered_by=? WHERE id=?",
                                (text, at, actor, qid))
            left = self.db.execute("SELECT COUNT(*) FROM ticket_questions WHERE ticket_id=? AND answered_at IS NULL",
                                   (tid,)).fetchone()[0]
            ev = [("pipeline.answered", f"Jay answered {len(clean)} question{'s' if len(clean) != 1 else ''}"
                   + ("" if left else " — all answered"), {"count": len(clean), "left": left})] if clean else []
            return {}, {}, ev
        return self._tx(key, actor, fn)

    def replan(self, key, reason, actor):
        """Back to Planning: invalid assumptions, architecture, security or a major scope change.
        The approval, any merge authorisation and the accepted plan go; Jay accepts before the merge."""
        reason = _text(reason, 300, "reason", multiline=False)
        if not reason:
            raise TaskError(400, "say why it goes back to planning")

        def fn(tid, t, w, at):
            self._open(t, "a re-plan")
            confirmed = sorted(set(_no_merge(w["confirmed"])) - {"plan", "ui", "deploy"} | {"owner:accept"})
            work = {"plan_state": "proposed", "review_verdict": None, "confirmed": confirmed, "blocked": None,
                    "gate": None, "gate_reason": None, "verification": None, "deploy": None}
            status = {"status": "RESEARCHING"} if t["status"] != "RESEARCHING" else {}
            return status, work, [("pipeline.replan", f"back to planning: {reason}", {"from": t["status"]})]
        return self._tx(key, actor, fn)

    def rework(self, key, reason, actor, open_prs=()):
        """Back to Implementation: an ordinary defect found in review, UI testing or verification.

        `open_prs` ({ref, head} of the ticket's open PRs, from ccd's last GitHub poll) goes into the rework
        event: those PRs are what the rework was about, so only a different head or PR returns the ticket to review."""
        prs = [{"ref": str(p.get("ref")), "head": str(p.get("head") or "")} for p in open_prs or ()
               if isinstance(p, dict) and p.get("ref")]
        reason = _text(reason, 300, "reason", multiline=False)
        if not reason:
            raise TaskError(400, "say what needs fixing")

        def fn(tid, t, w, at):
            self._need(t, ("IN_REVIEW", "READY_TO_MERGE", "VERIFYING", "BLOCKED"), "rework")
            if w["planState"] != "accepted":
                raise TaskError(409, f"{t['key']} has no accepted plan; re-plan instead")
            self._lane_free(t)
            # The change is being rewritten: an approval, a verification, a UI acceptance or a live-deploy
            # approval was for the old one, and an open UI / deploy / merge / failure gate no longer applies.
            work = {"review_verdict": None, "confirmed": [g for g in _no_merge(w["confirmed"]) if g not in ("ui", "deploy")],
                    "blocked": None, "verification": None, "deploy": None}
            if w["gate"] in ("merge", "failure", "ui", "deploy"):
                work.update(gate=None, gate_reason=None)
            return {"status": "IN_PROGRESS"}, work, [("pipeline.rework", f"back to implementation: {reason}",
                                                      {"from": t["status"], "prs": prs})]
        return self._tx(key, actor, fn)

    def evidence(self, key, kind, ref, note, actor, stage=None):
        if kind not in self.EVIDENCE_KINDS:
            raise TaskError(400, f"kind must be one of {', '.join(self.EVIDENCE_KINDS)}")
        ref = _text(ref, 500, "ref", multiline=False)
        note = _text(note, 2000, "note") or None
        if not ref:
            raise TaskError(400, "evidence needs a ref (a link, a file name, a test name …)")
        if stage is not None and stage not in STAGES:
            raise TaskError(400, f"stage must be one of {', '.join(STAGES)}")

        def fn(tid, t, w, at):
            st = stage or stage_of(t["status"]) or (w.get("blocked") or {}).get("stage")
            self.db.execute("INSERT INTO ticket_evidence(ticket_id, at, actor, stage, kind, ref, note) VALUES (?,?,?,?,?,?,?)",
                            (tid, at, actor, st, kind, ref, note))
            return {}, {}, [("pipeline.evidence", f"{kind} evidence: {ref}"[:200], {"kind": kind, "stage": st})]
        return self._tx(key, actor, fn)

    CHECKPOINT_TEXT = ("reason", "branch", "worktree", "dirty", "tests", "decisions", "blocker", "remaining")

    def _checkpoint(self, raw):
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise TaskError(400, "checkpoint must be an object")
        cp = {k: _text(raw.get(k), 2000, k) for k in self.CHECKPOINT_TEXT}
        commit = raw.get("commit")
        if commit not in (None, "") and (not isinstance(commit, str) or not re.match(r"^[0-9a-f]{7,40}$", commit)):
            raise TaskError(400, "checkpoint commit must be a SHA")
        cp["commit"] = commit or ""
        cp["changed"] = _list(raw.get("changed"), "changed", 200, 300)
        if not (cp["remaining"] or cp["reason"]):
            raise TaskError(400, "a checkpoint says why it was taken and what remains")
        return cp

    def writer(self, key, owner, actor, checkpoint=None):
        """Only ONE writer owns a worktree. Handing it over from another writer needs a checkpoint, so the
        next one (Claude after a Codex limit) resumes from the current state instead of starting again."""
        if owner not in self.WRITERS:
            raise TaskError(400, f"writer must be one of {', '.join(self.WRITERS)}")
        cp = self._checkpoint(checkpoint)

        def fn(tid, t, w, at):
            self._open(t, "a writer change")
            cur = w.get("writer")
            if cur and cur != owner and owner != "none" and cp is None:
                raise TaskError(409, f"{cur} owns the worktree; hand it over with a checkpoint")
            work = {"writer": None if owner == "none" else owner}
            text = f"{owner} owns the worktree" if owner != "none" else "worktree released"
            if cp is not None:
                work["checkpoint"] = dict(cp, at=at, by=actor, frm=cur, to=owner)
                text += f" (checkpoint from {cur or 'no writer'})"
            return {}, work, [("pipeline.writer", text, {"from": cur, "to": owner, "checkpoint": cp is not None})]
        return self._tx(key, actor, fn)

    def deploy_request(self, key, env, what, verification, actor):
        """Ask before deploying. A LIVE deployment opens the deploy gate: Jay is told and approves first."""
        if env not in self.DEPLOY_ENVS:
            raise TaskError(400, f"env must be one of {', '.join(self.DEPLOY_ENVS)}")
        what = _text(what, 2000, "what")
        verification = _text(verification, 2000, "verification")
        if not what:
            raise TaskError(400, "say what will go live")

        def fn(tid, t, w, at):
            self._need(t, ("VERIFYING",), "a deployment (after the merge)")
            if w["gate"] not in (None, "deploy"):
                raise TaskError(409, f"{t['key']} has an open {w['gate']} gate")
            cur = w.get("deploy") or {}
            if cur.get("env") == "live" and cur.get("requestedAt") and not cur.get("result") and env != "live":
                raise TaskError(409, "a live deployment is waiting for Jay; it cannot be replaced by a "
                                     f"{env} request")
            d = {"env": env, "what": what, "verification": verification, "requestedAt": at, "requestedBy": actor,
                 "approvedAt": None, "result": None}
            if env != "live":   # preview / dev follow the configured automation
                d.update(approvedAt=at, approvedBy="policy")
                return {}, {"deploy": d}, [("pipeline.deploy_requested", f"{env} deployment requested", {"env": env})]
            work = {"deploy": d, "gate": "deploy", "gate_reason": "Ready for live deployment",
                    "confirmed": [g for g in w["confirmed"] if g != "deploy"]}
            return {}, work, [("pipeline.deploy_requested", "live deployment waiting for Jay", {"env": env}),
                              ("pipeline.gate_opened", "deploy gate", {"gate": "deploy"})]
        return self._tx(key, actor, fn)

    def deployed(self, key, env, result, evidence, actor):
        """The deployment happened. A live one only after Jay approved it; then verify live, then close."""
        if result not in ("pass", "fail"):
            raise TaskError(400, "result must be pass or fail")
        evidence = _text(evidence, 2000, "evidence")
        if not evidence:
            raise TaskError(400, "say how the deployment was verified")

        def fn(tid, t, w, at):
            self._need(t, ("VERIFYING",), "a deployment record")
            d = w.get("deploy") or {}
            if not d.get("requestedAt") or d.get("env") != env:
                raise TaskError(409, f"no {env} deployment was requested for {t['key']}")
            if not d.get("approvedAt"):
                raise TaskError(409, "Jay has not approved this live deployment")
            d = dict(d, result=result, evidence=evidence, deployedAt=at, deployedBy=actor)
            self.db.execute("INSERT INTO ticket_evidence(ticket_id, at, actor, stage, kind, ref, note) VALUES (?,?,?,?,?,?,?)",
                            (tid, at, actor, "VERIFY", "deploy", f"{env} deployment {result}", evidence))
            work = {"deploy": d}
            if result == "fail":
                # A failed deployment needs a fresh request and, for live, Jay's fresh approval for the next try.
                work["deploy"] = dict(d, approvedAt=None)
                reason = f"{env} deployment failed: {evidence}"[:300]
                work.update(gate="failure", gate_reason=reason, blocked={"stage": "VERIFY", "reason": reason, "at": at})
                return {"status": "BLOCKED"}, work, [("pipeline.blocked", reason, {"stage": "VERIFY"})]
            events = [("pipeline.deployed", f"{env} deployment done and verified", {"env": env})]
            if (w["verification"] or {}).get("result") == "pass":
                status, more, ev = self._after_verify(t, dict(w, deploy=d))
                work.update(more)
                return status, work, events + ev
            return {}, work, events
        return self._tx(key, actor, fn)

    def release(self, key, summary, actor="system:automation"):
        """The ticket closed: record what was released (sessions, writer). The worktree is never deleted here."""
        def fn(tid, t, w, at):
            if w.get("released"):
                return {}, {}, []
            return {}, {"writer": None, "released": dict(summary, at=at)}, [
                ("pipeline.released", "task sessions released", {k: summary.get(k) for k in ("ptys", "claude")})]
        return self._tx(key, actor, fn)
