"""Needs You v2 (v2 Phase 1, PR 6; docs/COMMANDCENTER_V2_DISCOVERY.md §11.2, §14.3).

One inbox over everything that waits on Jay. The QUEUE itself is unchanged: it is still ccd's `state.needs` (open
gates, open questions, ticket flags, merges, tasks, CI) plus blocked agents, assembled the same way the dashboard
and the bell assemble it, so the three can never disagree. This module only adds what v2 knows about each item:

    approval    the pending Approval record for a gate (PR 4): its subject hash, when it was asked, when it expires
                and whether it is overdue
    engine      what the Autonomy Engine (shadow, PR 3) last said about that gate: auto / jay / refuse, and its rule
    precedents  for open questions: earlier answered questions with the same wording in the same project
                (Decision records). Shown, never applied: applying a precedent is a behaviour change for later.

Read-only. Nothing here closes a gate, answers a question or changes what ccd does.
"""
import json
import re
import time

STOP = {"a", "an", "the", "to", "of", "for", "in", "on", "is", "are", "be", "we", "i", "it", "this", "that", "should",
        "do", "does", "you", "your", "please"}
MAX_PRECEDENTS = 3
MIN_WORDS = 3             # "Proceed?" or "OK?" is no basis for "asked before"
ENGINE_WINDOW = 30 * 86400


def signature(text):
    """A question's wording reduced to what matters for 'asked before?': lower-case words with filler words
    dropped. Ticket keys, version numbers and the like stay in (they are often what tells two questions apart).
    Two questions match only when their signatures are equal and have at least MIN_WORDS words."""
    words = [w for w in re.findall(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", str(text or "").lower()) if w not in STOP]
    return " ".join(words) if len(words) >= MIN_WORDS else ""


def _item_id(n):
    return f"{n.get('kind')}:{n.get('project')}:{n.get('ref')}"


def _reconsider_ok(value, now):
    if not value:
        return True
    from .ledger import _date_ts
    ts = _date_ts(value)
    return ts is None or ts > now


# The question is found by its primary key (the text comparison keeps the match exact); test_inbox checks the plan.
ANSWERED_SQL = ("SELECT d.id, d.project, t.key, d.question, d.decision, d.decided_at, d.decided_by, d.reconsider, "
                "q.kind, q.options, q.purpose FROM decisions d LEFT JOIN tickets t ON t.id = d.ticket_id "
                "LEFT JOIN ticket_questions q ON q.id = CAST(d.source_ref AS INTEGER) "
                "AND CAST(q.id AS TEXT) = d.source_ref WHERE d.source = 'question' ORDER BY d.id DESC LIMIT 2000")


class Inbox:
    def __init__(self, db, clock=time.time):
        self.db = db
        self.clock = clock

    def _approvals(self):
        """Pending approvals by (ticket key, gate)."""
        out = {}
        for aid, key, project, gate, subj, req, exp in self.db.execute(
                "SELECT a.id, t.key, a.project, a.subject_type, a.subject_hash, a.requested_at, a.expires_at "
                "FROM approvals a JOIN tickets t ON t.id = a.ticket_id WHERE a.state = 'pending' ORDER BY a.id"):
            out[(key, gate)] = {"id": aid, "project": project, "gate": gate, "subjectHash": subj, "requestedAt": req,
                                "expiresAt": exp}
        return out

    def _engine(self, now):
        """The newest shadow verdict per (ticket key, action) from the last 30 days (the `at` index keeps it cheap)."""
        out = {}
        for key, action, engine, observed, rule, agree, at in self.db.execute(
                "SELECT t.key, s.action, s.engine, s.observed, s.rule, s.agree, s.at FROM autonomy_shadow s "
                "JOIN tickets t ON t.id = s.ticket_id WHERE s.id IN (SELECT MAX(id) FROM autonomy_shadow "
                "WHERE at > ? AND ticket_id IS NOT NULL GROUP BY ticket_id, action)", (now - ENGINE_WINDOW,)):
            out[(key, action)] = {"engine": engine, "observed": observed, "rule": rule, "agree": bool(agree), "at": at}
        return out

    def _open_questions(self, keys):
        out = {}
        if not keys:
            return out
        marks = ",".join("?" * len(keys))
        for key, qid, text, kind, options, purpose in self.db.execute(
                f"SELECT t.key, q.id, q.text, q.kind, q.options, q.purpose FROM ticket_questions q "
                f"JOIN tickets t ON t.id = q.ticket_id WHERE q.answered_at IS NULL AND t.key IN ({marks}) "
                f"ORDER BY q.batch, q.position", list(keys)):
            out.setdefault(key, []).append((qid, text, kind, _options(options), purpose))
        return out

    def _answered(self):
        """Current answered-question Decisions (not task-check proposals), grouped by signature, with the original
        question's kind and options so a precedent is only offered for the same kind of ask."""
        superseded = {r[0] for r in self.db.execute("SELECT supersedes FROM decisions WHERE supersedes IS NOT NULL")}
        by_sig = {}
        for did, project, key, question, decision, at, by, reconsider, kind, options, purpose in self.db.execute(
                ANSWERED_SQL):
            if did in superseded or purpose == "stale":
                continue
            sig = signature(question)
            if sig:
                by_sig.setdefault(sig, []).append({"id": did, "project": project, "key": key, "question": question,
                                                   "decision": decision, "decidedAt": at, "decidedBy": by,
                                                   "reconsider": reconsider, "kind": kind,
                                                   "options": _options(options)})
        return by_sig

    def enrich(self, needs):
        """`needs`: ccd's state.needs. Returns {items: {item id: extra}, orphans, counts}."""
        now = self.clock()
        approvals, engine = self._approvals(), self._engine(now)
        items, placed = {}, set()
        # A ticket with open questions shows only its questions item (Pipeline.needs), so its gate's approval
        # rides on that item instead of looking like an orphan.
        q_item = {n.get("ref"): n for n in needs if n.get("kind") == "questions"}
        questions = self._open_questions(sorted(k for k in q_item if k))
        answered = self._answered() if questions else {}
        hits = 0

        def approval(key, gate):
            a = approvals.get((key, gate))
            if a is None:
                return None
            placed.add((key, gate))
            return dict(a, overdue=a["expiresAt"] is not None and a["expiresAt"] < now)

        for n in needs:
            kind, key = n.get("kind"), n.get("ref")
            extra = {}
            if kind == "gate":
                gate = n.get("gate")
                a = approval(key, gate)
                if a:
                    extra["approval"] = a
                e = engine.get((key, gate))
                if e:
                    extra["engine"] = e
            elif kind == "questions":
                behind = [g for (k, g) in approvals if k == key]
                if behind:
                    extra["approval"] = approval(key, behind[0])
                found = []
                for qid, text, qkind, options, purpose in questions.get(key, []):
                    if purpose == "stale":
                        continue
                    sig = signature(text)
                    prior = [d for d in answered.get(sig, [])
                             if d["key"] != key and d["project"] == n.get("project")
                             and d["kind"] == qkind and d["options"] == options
                             and _reconsider_ok(d["reconsider"], now)][:MAX_PRECEDENTS]
                    if prior:
                        found.append({"questionId": qid, "question": text, "precedents": prior})
                if found:
                    extra["precedents"] = found
                    hits += len(found)
            if extra:
                items[_item_id(n)] = extra
        orphans = [dict(a, key=k) for (k, g), a in approvals.items() if (k, g) not in placed]
        overdue = sum(1 for x in items.values() if (x.get("approval") or {}).get("overdue"))
        return {"items": items, "orphans": orphans,
                "counts": {"approvals": len(approvals), "overdue": overdue, "precedentHits": hits,
                           "orphans": len(orphans)}}


def _options(raw):
    try:
        v = json.loads(raw or "[]")
        return sorted(str(x) for x in v) if isinstance(v, list) else []
    except ValueError:
        return []


def plain(obj):
    """JSON-safe copy (the shadow rule text and decisions are already plain; this guards future fields)."""
    return json.loads(json.dumps(obj, default=str))
