"""Decision and Approval records (v2 Phase 1, PR 4; docs/COMMANDCENTER_V2_DISCOVERY.md §7, §11).

    Decision   an answered question or a policy decision, with who decided and why. Append-only: a change is a
               new Decision that supersedes the old one.
    Approval   one request for Jay to approve one thing, bound to a SUBJECT HASH (the reviewed head SHA for a
               merge, the plan's hash for a plan, the deploy request's hash for a deploy). States:
               pending → approved → consumed, or pending/approved → void (the subject changed or the gate closed
               without Jay) or pending → rejected. Single-use: consumed once. `expires_at` is recorded (72 h).

MIRROR MODE. Today's gates (ticket_work.gate) and ticket questions stay the source of truth and decide everything,
exactly as before. This module only records them: `observe()` runs after each pipeline step and turns its events
into records; `reconcile()` at start backfills open gates; `seed_policy()` loads Jay's policy decisions
(policy/decisions/D-NNN.toml) as the first Decision records. A failure here is logged and changes nothing. Later
phases make the Capability Broker consume Approvals; nothing here grants or refuses anything yet.
"""
import hashlib
import json
import time

APPROVAL_TTL = 72 * 3600
GATE_TYPES = ("plan", "merge", "ui", "deploy", "failure")
CONSUMED_BY = {"merge": ("pipeline.merged", "pipeline.auto_merged"), "deploy": ("pipeline.deployed",)}


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def subject_hash(gate, key, work):
    """What an approval of this gate is bound to. A merge approval covers exactly the reviewed head; a plan approval
    exactly this plan; a deploy approval exactly this request. Anything else changes the hash, so a stale approval
    can never cover a new subject."""
    work = work or {}
    if gate == "merge":
        return str((work.get("review") or {}).get("head") or "")
    if gate == "plan":
        return _sha({"key": key, "plan": work.get("plan") or {}})
    if gate == "deploy":
        d = work.get("deploy") or {}
        return _sha({"key": key, "deploy": {k: d.get(k) for k in ("env", "what", "verification", "requestedAt")}})
    return _sha({"key": key, "gate": gate, "reason": work.get("gateReason"), "at": work.get("updatedAt")})


class Ledger:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock

    # ---------- decisions ----------

    def add_decision(self, *, project, question, decision, decided_by, source, source_ref, ticket_id=None,
                     options=(), rationale="", via=None, rules=(), reconsider=None, evidence=(), profile_hash=None,
                     decided_at=None, ref=None):
        """Insert a Decision unless the same (source, source_ref, content) is already recorded. A changed one
        supersedes the latest for that source_ref. Returns the row id (new or existing)."""
        body = {"question": question, "decision": decision, "options": list(options), "rationale": rationale,
                "rules": list(rules), "reconsider": reconsider, "decided_by": decided_by}
        sha = _sha(body)
        row = self.db.execute("SELECT id, content_sha FROM decisions WHERE source=? AND source_ref=? "
                              "ORDER BY id DESC LIMIT 1", (source, source_ref)).fetchone()
        if row and row[1] == sha:
            return row[0]
        with self.db:
            cur = self.db.execute(
                "INSERT INTO decisions (ref, project, ticket_id, question, options, decision, rationale, decided_by, via, "
                "rules, reconsider, evidence, decided_at, recorded_at, supersedes, source, source_ref, content_sha, "
                "profile_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref, project, ticket_id, str(question)[:1000], json.dumps(list(options))[:4000], str(decision)[:4000],
                 str(rationale or "")[:2000], decided_by, via, json.dumps(list(rules))[:4000], reconsider,
                 json.dumps(list(evidence))[:2000], decided_at or self.clock(), self.clock(),
                 row[0] if row else None, source, str(source_ref), sha, profile_hash))
        return cur.lastrowid

    def seed_policy(self, policy):
        """Jay's policy decisions (policy/decisions/*.toml, valid ones) as Decision records. Idempotent."""
        n = 0
        for key, d in sorted(policy.decisions.items()):
            if not d.get("valid"):
                continue
            projects = d.get("projects") or []
            before = self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            self.add_decision(project=",".join(projects), question=d["question"], decision=d["decision"],
                              decided_by="jay", source="policy", source_ref=key, ref=key,
                              rationale=d.get("rationale") or "", via="policy-file", rules=d.get("rules") or (),
                              reconsider=d.get("reconsider"), evidence=[d.get("source") or "", d.get("sha256") or ""],
                              profile_hash=policy.fingerprint, decided_at=_date_ts(d.get("date")))
            n += self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] - before
        return n

    def record_answers(self, ticket_id, project, profile_hash=None):
        """Every answered question on a ticket that has no Decision yet."""
        for qid, text, kind, options, answer, at, by in self.db.execute(
                "SELECT id, text, kind, options, answer, answered_at, answered_by FROM ticket_questions "
                "WHERE ticket_id=? AND answered_at IS NOT NULL ORDER BY id", (ticket_id,)).fetchall():
            if self.db.execute("SELECT 1 FROM decisions WHERE source='question' AND source_ref=?", (str(qid),)).fetchone():
                continue
            self.add_decision(project=project, ticket_id=ticket_id, question=text, decision=answer,
                              options=json.loads(options or "[]"), decided_by=by or "jay", via="answer",
                              source="question", source_ref=qid, decided_at=at, profile_hash=profile_hash,
                              rationale=f"{kind} question")

    # ---------- approvals ----------

    def _open_approval(self, ticket_id, project, gate):
        return self.db.execute("SELECT id, state, subject_hash FROM approvals WHERE ticket_id=? AND subject_type=? "
                               "AND state IN ('pending', 'approved') ORDER BY id DESC LIMIT 1",
                               (ticket_id, gate)).fetchone()

    def request(self, ticket_id, project, gate, subject, reason, by="system:pipeline", profile_hash=None):
        """A pending Approval for an open gate (one per ticket and gate at a time)."""
        cur = self._open_approval(ticket_id, project, gate)
        if cur and cur[1] == "pending" and cur[2] == subject:
            return cur[0]
        if cur:
            self._set(cur[0], "void", reason="a new request replaced it")
        now = self.clock()
        with self.db:
            c = self.db.execute(
                "INSERT INTO approvals (project, ticket_id, subject_type, subject_hash, action, required, state, reason, "
                "requested_at, requested_by, expires_at, profile_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (project, ticket_id, gate, subject, f"close the {gate} gate", "jay", "pending", str(reason or "")[:300],
                 now, by, now + APPROVAL_TTL, profile_hash))
        return c.lastrowid

    def _set(self, aid, state, by=None, via=None, reason=None):
        now = self.clock()
        cols = {"approved": "decided_at=?, decided_by=?, via=?", "rejected": "decided_at=?, decided_by=?, via=?",
                "consumed": "consumed_at=?", "void": "voided_at=?, void_reason=?"}[state]
        args = {"approved": (now, by, via), "rejected": (now, by, via), "consumed": (now,), "void": (now, reason)}[state]
        with self.db:
            self.db.execute(f"UPDATE approvals SET state=?, {cols} WHERE id=?", (state, *args, aid))

    def observe(self, ticket_id, project, key, work, events, profile_hash=None):
        """Mirror one pipeline step. `work` is pipeline.work(key) AFTER the step."""
        kinds = [k for k, _t, _d in events or ()]
        for kind, _text, data in events or ():
            data = data if isinstance(data, dict) else {}
            gate = data.get("gate")
            if kind == "pipeline.gate_opened" and gate in GATE_TYPES:
                self.request(ticket_id, project, gate, subject_hash(gate, key, work), work.get("gateReason"),
                             profile_hash=profile_hash)
            elif kind == "pipeline.gate_confirmed" and gate in GATE_TYPES:
                cur = self._open_approval(ticket_id, project, gate)
                if cur is None:   # opened before this ledger existed and not backfilled: record it now
                    aid = self.request(ticket_id, project, gate, subject_hash(gate, key, work), "recorded at approval",
                                       by="system:backfill", profile_hash=profile_hash)
                    cur = (aid, "pending", None)
                if cur[1] == "pending":
                    self._set(cur[0], "approved", by="jay", via="ui")
                if gate not in CONSUMED_BY:   # plan / ui / failure: Jay's confirmation IS the action
                    self._set(cur[0], "consumed")
        for gate, done in CONSUMED_BY.items():
            if any(k in done for k in kinds):
                cur = self._open_approval(ticket_id, project, gate)
                if cur and cur[1] == "approved":
                    self._set(cur[0], "consumed")
        # Void what no longer matches: a pending approval whose gate closed without Jay, an approved merge whose
        # head moved before it was used.
        for aid, gate, state, subj in self.db.execute(
                "SELECT id, subject_type, state, subject_hash FROM approvals WHERE ticket_id=? "
                "AND state IN ('pending', 'approved')", (ticket_id,)).fetchall():
            if state == "pending" and work.get("gate") != gate:
                self._set(aid, "void", reason="the gate closed without an approval (" + ", ".join(kinds[:3]) + ")")
            elif state == "approved" and gate == "merge" and subj != subject_hash("merge", key, work):
                self._set(aid, "void", reason="the PR head changed after the approval")
        if "pipeline.answered" in kinds:
            self.record_answers(ticket_id, project, profile_hash)

    def reconcile(self, open_gates, profile_hash=None):
        """At start: a pending Approval for every open gate that has none (gates opened before this ledger)."""
        n = 0
        for ticket_id, project, key, work in open_gates:
            gate = work.get("gate")
            if gate in GATE_TYPES and self._open_approval(ticket_id, project, gate) is None:
                self.request(ticket_id, project, gate, subject_hash(gate, key, work), work.get("gateReason"),
                             by="system:backfill", profile_hash=profile_hash)
                n += 1
        return n

    # ---------- read ----------

    def decisions(self, project=None, limit=100):
        q = ("SELECT d.id, d.ref, d.project, t.key, d.question, d.options, d.decision, d.rationale, d.decided_by, d.via, "
             "d.reconsider, d.decided_at, d.supersedes, d.source, d.source_ref, d.content_sha FROM decisions d "
             "LEFT JOIN tickets t ON t.id = d.ticket_id")
        args = []
        if project:
            q += " WHERE (',' || d.project || ',') LIKE ?"
            args.append(f"%,{project},%")
        q += " ORDER BY d.id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        superseded = {r[0] for r in self.db.execute("SELECT supersedes FROM decisions WHERE supersedes IS NOT NULL")}
        return [{"id": r[0], "ref": r[1], "project": r[2], "key": r[3], "question": r[4], "options": json.loads(r[5]),
                 "decision": r[6], "rationale": r[7], "decidedBy": r[8], "via": r[9], "reconsider": r[10],
                 "decidedAt": r[11], "supersedes": r[12], "source": r[13], "sourceRef": r[14], "sha256": r[15],
                 "current": r[0] not in superseded}
                for r in self.db.execute(q, args).fetchall()]

    def approvals(self, state=None, limit=100):
        q = ("SELECT a.id, a.project, t.key, a.subject_type, a.subject_hash, a.action, a.state, a.reason, a.requested_at, "
             "a.requested_by, a.expires_at, a.decided_at, a.decided_by, a.via, a.consumed_at, a.voided_at, a.void_reason "
             "FROM approvals a LEFT JOIN tickets t ON t.id = a.ticket_id")
        args = []
        if state:
            q += " WHERE a.state = ?"
            args.append(state)
        q += " ORDER BY a.id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        now = self.clock()
        return [{"id": r[0], "project": r[1], "key": r[2], "subject": r[3], "subjectHash": r[4], "action": r[5],
                 "state": r[6], "reason": r[7], "requestedAt": r[8], "requestedBy": r[9], "expiresAt": r[10],
                 "overdue": r[6] == "pending" and r[10] is not None and r[10] < now,
                 "decidedAt": r[11], "decidedBy": r[12], "via": r[13], "consumedAt": r[14], "voidedAt": r[15],
                 "voidReason": r[16]}
                for r in self.db.execute(q, args).fetchall()]

    def counts(self):
        return {s: n for s, n in self.db.execute("SELECT state, COUNT(*) FROM approvals GROUP BY state")}


def _date_ts(s):
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(s)).replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None
