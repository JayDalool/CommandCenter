"""The delivery flow: nine stages, three sizes, seats and hand-offs (docs/flow, the shared flow contract).

This module only READS. It derives where a ticket is in the nine-stage flow from what the pipeline already
records (the canonical status, `ticket_work`, the new `ticket_flow` row and the ticket's events). The ops that move
a ticket live in pipeline.py, as before; there is no second status set.

    #  stage        seat            canonical status while in it
    1  intake       lead            INBOX, PROPOSED
    2  investigate  investigator    RESEARCHING, no plan waiting for review
    3  techReview   techReviewer    RESEARCHING, plan recorded and waiting for (or approved by) the technical reviewer
    4  build        developer       READY_TO_IMPLEMENT, IN_PROGRESS
    5  userCheck    userReviewer    IN_REVIEW, user check not passed on the current head
    6  codeReview   codeReviewer    IN_REVIEW, user check passed (or not on the route)
    7  merge        jay             READY_TO_MERGE
    8  release      verifier        VERIFYING
    9  done         lead            DONE

Routes by size. A ticket nobody has sized yet ("Not sized") keeps the steps it had before the flow existed: no
technical review, no user check. Sizing it (intake, or the `criteria` op) puts it on its route.

    small     intake > build > codeReview > merge > release > done      (+ userCheck when policy().ui)
    standard  all nine
    risky     all nine; Jay approves the plan after techReview and approves the release
"""
import json
import time

STAGES = ("intake", "investigate", "techReview", "build", "userCheck", "codeReview", "merge", "release", "done")
SIZES = ("small", "standard", "risky")
SEATS = ("lead", "investigator", "techReviewer", "developer", "userReviewer", "designReviewer", "codeReviewer",
         "verifier")
SEAT_OF = {"intake": "lead", "investigate": "investigator", "techReview": "techReviewer", "build": "developer",
           "userCheck": "userReviewer", "codeReview": "codeReviewer", "merge": "jay", "release": "verifier",
           "done": "lead"}
# Each seat is a pipeline role (pipeline.ROLE_NAMES); an agent takes a seat with `pipeline_cli role KEY --role R`.
ROLE_OF = {"lead": "coordinator", "investigator": "planner", "techReviewer": "tech-reviewer",
           "developer": "implementer", "userReviewer": "user-reviewer", "designReviewer": "design-reviewer",
           "codeReviewer": "reviewer", "verifier": "verifier"}
SEAT_OF_ROLE = {r: s for s, r in ROLE_OF.items()}
REVIEW_STAGES = ("techReview", "userCheck", "codeReview")
WORK_STAGES = ("investigate", "techReview", "build", "userCheck", "codeReview")     # stages 2-6: these go stale
STALE_AFTER = 48 * 3600
UNSEATED_AFTER = 4 * 3600         # finishing first: a review nobody has taken for this long holds new work
MAX_INVESTIGATE = 2
MAX_CRITERIA = 20
MAX_REQUIREMENTS = 20
STALE_KIND = "pipeline.flow_stale"
LEGACY_ROUTE = ("intake", "investigate", "build", "codeReview", "merge", "release", "done")
CLOSED = ("DONE", "DENIED", "CANCELLED")


def _now():
    return time.time()


def effective_size(size, pol):
    """The size the route uses. A ticket whose labels/flags/type open the plan gate (policy().plan == "owner") is
    risky whatever was typed; a ticket nobody sized reads as standard."""
    if pol.get("plan") == "owner":
        return "risky"
    return size if size in SIZES else "standard"


def shown_size(size, pol):
    """`size` / `flow.size` as the API returns them: null while nobody has sized the ticket (the UI says "Not sized"),
    except that a ticket the policy makes risky always says so."""
    if pol.get("plan") == "owner":
        return "risky"
    return size if size in SIZES else None


def route(size, pol):
    """The stages this ticket goes through, in order. `size` is the stored size (None = not sized)."""
    if size not in SIZES:       # not sized: today's steps (a risky-by-policy ticket still has its plan gate)
        return LEGACY_ROUTE
    eff = effective_size(size, pol)
    if eff == "small":
        out = ["intake", "build"] + (["userCheck"] if pol.get("ui") else []) + ["codeReview", "merge", "release", "done"]
        return tuple(out)
    return STAGES


def user_check_passed(f):
    uc = (f or {}).get("userCheck") or {}
    return uc.get("result") == "pass"


def current(t, w, f, rt):
    """The stage key the ticket is in now (or was in when it got blocked), or None for DENIED / CANCELLED."""
    st = t["status"]
    if st in ("DENIED", "CANCELLED"):
        return None
    if st == "BLOCKED":
        b = w.get("blocked") or {}
        if b.get("flowStage") in STAGES:
            return b["flowStage"]
        return {"PLAN": "techReview" if (f or {}).get("reviewDue") and "techReview" in rt else "investigate",
                "BUILD": "build", "REVIEW": "codeReview", "MERGE": "merge", "VERIFY": "release"}.get(b.get("stage"),
                                                                                                    "investigate")
    if st in ("INBOX", "PROPOSED"):
        return "intake"
    if st == "RESEARCHING":
        if "techReview" in rt and ((f or {}).get("reviewDue") or w.get("gate") == "plan"):
            return "techReview"
        return "investigate"
    if st in ("READY_TO_IMPLEMENT", "IN_PROGRESS"):
        return "build"
    if st == "IN_REVIEW":
        return "userCheck" if "userCheck" in rt and not user_check_passed(f) else "codeReview"
    return {"READY_TO_MERGE": "merge", "VERIFYING": "release", "DONE": "done"}.get(st)


def _coarse(status):
    return {"INBOX": "intake", "PROPOSED": "intake", "RESEARCHING": "investigate", "READY_TO_IMPLEMENT": "build",
            "IN_PROGRESS": "build", "IN_REVIEW": "codeReview", "READY_TO_MERGE": "merge", "VERIFYING": "release",
            "DONE": "done"}.get(status)


# ccd's own words for each step. `note` never carries agent text (that stays in plan, findings and evidence).
NOTES = {
    "intake": "Sized and sent on", "plan_review": "Plan recorded for technical review", "plan_accepted": "Plan accepted",
    "plan_gate": "Plan waits for Jay", "approved": "Technical review approved the plan",
    "plan_sent_back": "Technical review sent the plan back", "jay_plan": "Jay approved the plan",
    "started": "Implementation started", "to_review": "Pull request in review", "user_pass": "User check passed",
    "user_fail": "User check failed", "user_stale": "New commits: the user check runs again",
    "changes": "Code review asked for changes", "ready": "Code review approved; ready to merge",
    "not_ready": "Back to code review", "merged": "Merged", "done": "Closed", "blocked": "Blocked",
    "resumed": "Jay cleared the blocker", "rework": "Back to build", "replan": "Back to investigation",
    "moved": "Moved by hand",
}


def handoffs(events, rt, created_at=None):
    """[{at, stage, kind, from, to, by, note}] oldest first, from the ticket's events
    ([(at, actor, kind, field, from_value, to_value, data)] in id order). Also returns, per stage, when the ticket
    last entered it ({stage: at}) and who/when last moved it on ({stage: (by, at)})."""
    out, entered, left = [], {"intake": created_at}, {}
    cur = "intake"
    pipeline_at = {e[0] for e in events if str(e[2]).startswith("pipeline.")}

    def seat(stage):
        return SEAT_OF.get(stage) if stage else None

    def add(at, kind, to, by, note, frm_stage=None):
        nonlocal cur
        frm_stage = frm_stage or cur
        if kind == "advanced" and frm_stage:
            left[frm_stage] = (by, at)
        out.append({"at": at, "stage": frm_stage, "kind": kind, "from": seat(frm_stage),
                    "to": seat(to) if kind != "blocked" else None, "by": by, "note": NOTES[note]})
        if to:
            if to != frm_stage or kind in ("sentBack", "resumed"):
                entered[to] = at
            cur = to

    for at, actor, kind, field, frm, to, data in events:
        try:
            d = json.loads(data or "{}") if isinstance(data, str) else (data or {})
        except ValueError:
            d = {}
        if kind == "pipeline.intake":
            add(at, "advanced", d.get("to") or "investigate", actor, "intake")
        elif kind == "pipeline.plan" and d.get("review"):
            add(at, "advanced", "techReview", actor, "plan_review")
        elif kind == "pipeline.plan_accepted":
            add(at, "advanced", "build", actor, "plan_accepted")
        elif kind == "pipeline.plan_reviewed":
            if d.get("verdict") == "APPROVE":
                if d.get("gate"):
                    out.append({"at": at, "stage": "techReview", "kind": "advanced", "from": "techReviewer",
                                "to": "jay", "by": actor, "note": NOTES["plan_gate"]})
                    left["techReview"] = (actor, at)
                else:
                    add(at, "advanced", "build", actor, "approved")
            elif not d.get("blocked"):
                add(at, "sentBack", "investigate", actor, "plan_sent_back")
        elif kind == "pipeline.gate_opened" and d.get("gate") == "plan" and cur != "techReview":
            out.append({"at": at, "stage": cur, "kind": "advanced", "from": seat(cur), "to": "jay", "by": actor,
                        "note": NOTES["plan_gate"]})
        elif kind == "pipeline.gate_confirmed" and d.get("gate") == "plan":
            add(at, "advanced", "build", actor, "jay_plan")
        elif kind == "pipeline.gate_confirmed" and d.get("gate") == "failure":
            add(at, "resumed", cur, actor, "resumed")
        elif kind == "pipeline.started":
            out.append({"at": at, "stage": "build", "kind": "advanced", "from": "lead", "to": "developer",
                        "by": actor, "note": NOTES["started"]})
            entered["build"] = entered.get("build") or at
            cur = "build"
        elif kind == "pipeline.user_checked":
            if d.get("result") == "pass":
                add(at, "advanced", "codeReview", actor, "user_pass", "userCheck")
            elif not d.get("blocked"):
                add(at, "sentBack", "build", actor, "user_fail", "userCheck")
        elif kind == "pipeline.user_check_stale":
            add(at, "sentBack", "userCheck", actor, "user_stale")
        elif kind == "pipeline.review" and d.get("verdict") == "REQUEST_CHANGES" and not d.get("blocked"):
            out.append({"at": at, "stage": "codeReview", "kind": "sentBack", "from": "codeReviewer",
                        "to": "developer", "by": actor, "note": NOTES["changes"]})
        elif kind == "pipeline.ready_to_merge":
            add(at, "advanced", "merge", actor, "ready")
        elif kind in ("pipeline.review_stale", "pipeline.not_ready"):
            add(at, "sentBack", "userCheck" if "userCheck" in rt and d.get("userCheck") else "codeReview", actor,
                "not_ready")
        elif kind == "pipeline.merged" and cur != "release":     # the poll's status move may have said it
            add(at, "advanced", "release", actor, "merged")
        elif kind == "pipeline.done":
            add(at, "advanced", "done", actor, "done")
        elif kind == "pipeline.blocked":
            add(at, "blocked", None, actor, "blocked")
        elif kind == "pipeline.rework" and d.get("via") != "userCheck":     # a failed user check said it already
            add(at, "sentBack", "build", actor, "rework")
        elif kind == "pipeline.replan":
            add(at, "sentBack", "investigate", actor, "replan")
        elif field == "status" and kind == "status" and at not in pipeline_at:
            # A move nobody recorded as a pipeline step: the GitHub poll (a PR opened, merged) or Jay by hand.
            if frm == "IN_PROGRESS" and to == "IN_REVIEW":
                add(at, "advanced", "userCheck" if "userCheck" in rt else "codeReview", actor, "to_review")
            elif to == "VERIFYING" and frm in ("IN_REVIEW", "READY_TO_MERGE"):
                add(at, "advanced", "release", actor, "merged")
            elif to == "BLOCKED":
                add(at, "blocked", None, actor, "blocked")
            elif to in ("DENIED", "CANCELLED"):
                continue
            else:
                a, b = _coarse(frm), _coarse(to)
                if b is None:
                    continue
                if a is None:          # out of BLOCKED by hand
                    add(at, "resumed", b, actor, "resumed")
                elif STAGES.index(b) > STAGES.index(a):
                    add(at, "advanced", b, actor, "moved", a)
                elif STAGES.index(b) < STAGES.index(a):
                    add(at, "sentBack", b, actor, "moved", a)
    return out, entered, left


def holder(stage, roles, since):
    """Who has the ticket now: the agent that took the stage's seat after the ticket entered the stage."""
    s = SEAT_OF.get(stage)
    role = ROLE_OF.get(s)
    r = (roles or {}).get(role) if role else None
    if not isinstance(r, dict) or not r.get("at"):
        return None
    if since is not None and r["at"] < since:
        return None
    return {"seat": s, "session": r.get("session"), "since": r["at"]}


def view(t, w, f, events, pol, open_children=0, now=None):
    """The `flow` object of GET /api/tasks/{key}/work, and the `handoffs` list."""
    now = _now() if now is None else now
    f = f or {}
    rt = route(f.get("size"), pol)
    hs, entered, left = handoffs(events, rt, t.get("createdAt"))
    cur = current(t, w, f, rt)
    since = entered.get(cur) if cur else None
    if cur and since is None:
        since = t.get("createdAt")
    hold = holder(cur, w.get("roles"), since) if cur and t["status"] not in ("BLOCKED",) + CLOSED else None
    gate = w.get("gate")
    v = w.get("verification") or {}
    d = w.get("deploy") or {}
    waiting = None
    if gate or w.get("openQuestions"):
        waiting = "jay"
    elif t["status"] == "VERIFYING" and v.get("result") == "pass" and not (d.get("requestedAt") and d.get("result") != "pass"):
        waiting = "lead"    # verified: the lead writes the closing note (or children are still open)
    elif cur == "intake":
        waiting = "lead"
    elif cur in REVIEW_STAGES and hold is None and t["status"] != "BLOCKED":
        waiting = "reviewer"
    stages = []
    at_i = STAGES.index(cur) if cur in STAGES else -1
    roles = w.get("roles") or {}
    for i, s in enumerate(STAGES):
        seat = SEAT_OF[s]
        sess = (roles.get(ROLE_OF.get(seat)) or {}).get("session") if ROLE_OF.get(seat) else None
        if s not in rt:
            state = "skipped"
        elif t["status"] == "DONE" or i < at_i:
            state = "done"
        elif i == at_i:
            state = "blocked" if t["status"] == "BLOCKED" else ("done" if s == "done" else "active")
        else:
            state = "todo"
        by, at = None, None
        if state == "done" and s in left:
            by, at = left[s]
        elif state in ("active", "blocked"):
            at = since
            if hold:
                by = hold["session"]
        stages.append({"stage": s, "state": state, "seat": seat, "by": by,
                       "session": sess if state in ("done", "active", "blocked") else None, "at": at})
    nxt = None
    if cur in rt and cur != "done":
        n = rt[rt.index(cur) + 1]
        nxt = {"stage": n, "seat": SEAT_OF[n]}
    rounds = 0
    if cur == "techReview":
        rounds = int((f.get("rounds") or {}).get("techReview") or 0)
    elif cur == "userCheck":
        rounds = int((f.get("rounds") or {}).get("userCheck") or 0)
    elif cur == "codeReview":
        rounds = int((w.get("review") or {}).get("cycles") or 0)
    idle = idle_since(events, t.get("createdAt"))
    stale = is_stale(cur, t["status"], waiting, idle, now)
    out = {"size": shown_size(f.get("size"), pol), "stage": cur, "stages": stages, "holder": hold, "next": nxt,
           "waitingOn": waiting, "rounds": rounds, "idleSince": idle, "stale": stale,
           "route": list(rt), "openChildren": open_children}
    return out, [{k: h[k] for k in ("at", "stage", "kind", "from", "to", "by", "note")} for h in hs]


def idle_since(events, created_at=None):
    """The time of the ticket's last pipeline step or status move (ccd's own stale mark does not count)."""
    last = created_at
    for at, _actor, kind, field, *_ in events:
        if kind == STALE_KIND:
            continue
        if str(kind).startswith("pipeline.") or field == "status":
            last = at if last is None else max(last, at)
    return last


def is_stale(stage, status, waiting, idle, now):
    """Stale: in stages 2-6, nothing recorded for 48 hours, and not waiting on Jay (his queue is not idle work)."""
    return bool(stage in WORK_STAGES and status not in ("BLOCKED",) + CLOSED and waiting != "jay"
                and idle is not None and now - idle > STALE_AFTER)
