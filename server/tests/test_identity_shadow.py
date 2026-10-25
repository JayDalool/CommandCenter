"""Phase 2 shadow step 1 (Jay, 2026-10-25): typed identity tokens and the resolvedActor record.

Everything here records; nothing refuses. Jay: "No request may be refused merely because the new Phase 2 check would
deny it. Record would-refuse instead." The tests show the typed tokens, the legacy path, each would-refuse reason, the
observation chain, that `enforced` cannot be anything but 0, and that writes go through exactly as before."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from ccd import audit, identity, pipeline_cli, security
from ccd.daemon import Daemon
from ccd.store import Store

from .helpers import cfg, new_db
from .test_audit import DEV, TOKEN, Clock, tasks_db

LEGACY = "cca_" + "a_" + "L" * 41          # a pre-Phase-2 token whose random part happens to start "a_"


def add_legacy(db, token=LEGACY, actor="agent:old", expires=4_102_444_800):
    cur = db.execute("INSERT INTO actor_tokens (actor, token_sha, issued_at, issued_by, expires_at) "
                     "VALUES (?, ?, 0, 'jay', ?)", (actor, hashlib.sha256(token.encode()).hexdigest(), expires))
    return cur.lastrowid


class TypedTokens(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.clock = Clock()
        self.t = identity.ActorTokens(self.ts.db, self.clock)

    def test_agent_and_service_tokens_are_typed_by_prefix(self):
        a = self.t.issue("agent:coder", "jay")
        s = self.t.issue("svc:ccd-backup", "jay", project="commandcenter")
        self.assertEqual((a["kind"], a["token"][:6], len(a["token"])), ("agent", "cca_a_", 49))
        self.assertEqual((s["kind"], s["token"][:6], s["project"]), ("service", "cca_s_", "commandcenter"))
        hit = self.t.lookup(s["token"])
        self.assertEqual((hit["actor"], hit["kind"], hit["project"], hit["legacy"]),
                         ("svc:ccd-backup", "service", "commandcenter", False))
        self.assertEqual(hit["fingerprint"], s["fingerprint"])
        self.assertEqual(self.t.verify(a["token"]), "agent:coder")
        swapped = "cca_s_" + a["token"][6:]                                   # the prefix is part of the token
        self.assertIsNone(self.t.lookup(swapped))
        for bad in (None, 12, "", "cca_a_short", a["token"] + "x", a["token"][:-1], "x" * 200):
            self.assertIsNone(self.t.lookup(bad), bad)

    def test_issue_refuses_bad_subjects_projects_and_issuers(self):
        for bad in ("jay", "svc:", "svc:A", "svc:a b", "service:x", "agent:", None):
            with self.assertRaises(identity.IdentityError, msg=bad):
                self.t.issue(bad, "jay")
        for bad in ("", "Sam", "a b", "x" * 41, 7, "../etc"):
            with self.assertRaises(identity.IdentityError, msg=bad):
                self.t.issue("agent:coder", "jay", project=bad)
        with self.assertRaises(identity.IdentityError) as e:
            self.t.issue("svc:ccd", "svc:ccd")
        self.assertEqual(e.exception.status, 403)

    def test_legacy_tokens_still_verify_list_with_negative_ids_and_revoke(self):
        lid = add_legacy(self.ts.db)
        hit = self.t.lookup(LEGACY)
        self.assertEqual((hit["actor"], hit["kind"], hit["legacy"], hit["project"]), ("agent:old", "agent", True, None))
        typed = self.t.issue("agent:new", "jay")
        rows = {r["id"]: r for r in self.t.list()}
        self.assertEqual((rows[-lid]["legacy"], rows[-lid]["actor"], rows[-lid]["status"]), (True, "agent:old", "active"))
        self.assertFalse(rows[typed["id"]]["legacy"])
        self.assertEqual(self.t.revoke(-lid, "jay")["status"], "revoked")
        self.assertIsNone(self.t.lookup(LEGACY))
        self.assertEqual(self.t.verify(typed["token"]), "agent:new")           # the typed token of the same id lives
        with self.assertRaises(identity.IdentityError) as e:
            self.t.revoke(0, "jay")
        self.assertEqual(e.exception.status, 404)

    def test_expired_and_revoked_typed_tokens_prove_nothing(self):
        out = self.t.issue("svc:x", "jay", 1)
        self.clock.t += 86401
        self.assertIsNone(self.t.lookup(out["token"]))
        other = self.t.issue("svc:y", "jay")
        self.t.revoke(other["id"], "jay")
        self.assertIsNone(self.t.lookup(other["token"]))


class Resolve(unittest.TestCase):
    AGENT = {"actor": "agent:coder", "kind": "agent", "project": None, "fingerprint": "abcd-ef01", "legacy": False}

    def reasons(self, *a, **kw):
        out = identity.resolve(*a, **kw)
        self.assertFalse(out["enforced"])
        self.assertEqual(out["wouldRefuse"], bool(out["reasons"]))
        return out["resolvedActor"], out["reasons"]

    def test_each_reason(self):
        self.assertEqual(self.reasons("jay", True, None), ("jay", []))
        self.assertEqual(self.reasons(None, True, None), ("jay", []))                  # header missing, but unlocked
        self.assertEqual(self.reasons(None, False, None), ("unknown", ["missing_header", "unverified",
                                                                       "jay_without_unlock"]))
        self.assertEqual(self.reasons("jay", False, None), ("unknown", ["unverified", "jay_without_unlock"]))
        self.assertEqual(self.reasons("agent:coder", False, None), ("unknown", ["unverified"]))
        self.assertEqual(self.reasons("agent:coder", False, self.AGENT), ("agent:coder", []))
        self.assertEqual(self.reasons(None, False, self.AGENT), ("agent:coder", ["missing_header", "asserted_mismatch",
                                                                                "jay_without_unlock"]))
        self.assertEqual(self.reasons("agent:other", False, self.AGENT), ("agent:coder", ["asserted_mismatch"]))
        self.assertEqual(self.reasons("jay", False, self.AGENT), ("agent:coder", ["asserted_mismatch",
                                                                                 "jay_without_unlock"]))
        self.assertEqual(self.reasons("agent:x", True, None), ("jay", ["asserted_mismatch"]))

    def test_project_binding(self):
        bound = dict(self.AGENT, project="gyst")
        self.assertEqual(self.reasons("agent:coder", False, bound, "gyst"), ("agent:coder", []))
        self.assertEqual(self.reasons("agent:coder", False, bound, None), ("agent:coder", []))   # not known: no claim
        self.assertEqual(self.reasons("agent:coder", False, bound, "samvision"), ("agent:coder", ["project_mismatch"]))
        out = identity.resolve("agent:coder", False, bound, "samvision")
        self.assertEqual((out["tokenProject"], out["tokenKind"], out["tokenFingerprint"]), ("gyst", "agent", "abcd-ef01"))
        # Developer Unlock wins; a token sent alongside it is not what the write is resolved by
        out = identity.resolve("jay", True, bound, "samvision")
        self.assertEqual((out["via"], out["tokenProject"], out["reasons"]), ("developer", None, []))


class Observations(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.a = audit.Audit(self.ts.db, Clock())

    def rec(self, who, **kw):
        base = dict(actor="jay", verified=False, via="none", method="POST", path="/api/tasks", status=201)
        return self.a.record(identity=who, **dict(base, **kw))

    def test_each_write_gets_a_chained_observation_naming_its_audit_row(self):
        sha1 = self.rec(identity.resolve(None, False, None))
        self.a.record(actor="system", verified=True, via="system", method="SYSTEM", path="pipeline", status=200)
        sha2 = self.rec(identity.resolve("jay", True, None))
        rows = self.ts.db.execute("SELECT audit_id, audit_sha, would_refuse, reasons, enforced "
                                  "FROM identity_observations ORDER BY audit_id").fetchall()
        self.assertEqual([(r[1], r[2], r[4]) for r in rows], [(sha1, 1, 0), (sha2, 0, 0)])
        self.assertEqual(json.loads(rows[0][3]), ["missing_header", "unverified", "jay_without_unlock"])
        self.assertEqual(self.a.verify_identity(full=True), {"ok": True, "checked": 2, "brokenAt": None, "full": True})
        events = self.a.list()
        self.assertEqual([e["identity"] and e["identity"]["resolvedActor"] for e in events], ["jay", None, "unknown"])
        s = self.a.identity_summary(since=0)
        self.assertEqual((s["total"], s["wouldRefuse"], s["missingHeader"], s["enforced"]), (2, 1, 1, False))
        self.assertEqual(s["byReason"]["unverified"], 1)
        self.assertEqual(s["byResolved"], {"unknown": 1, "jay": 1})

    def test_the_table_refuses_enforced_and_edits(self):
        self.rec(identity.resolve(None, False, None))
        for sql in ("UPDATE identity_observations SET would_refuse=0", "DELETE FROM identity_observations"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.ts.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ts.db.execute("INSERT INTO identity_observations (audit_id, audit_sha, resolved_actor, via, "
                               "would_refuse, enforced, prev_sha, sha) VALUES (999, ?, 'jay', 'none', 1, 1, ?, 'x')",
                               ("0" * 64, "0" * 64))
        bad = dict(identity.resolve("jay", True, None), enforced=True)     # whatever the caller says, 0 is stored
        self.rec(bad)
        self.assertEqual(self.ts.db.execute("SELECT MAX(enforced) FROM identity_observations").fetchone()[0], 0)

    def test_an_edited_observation_breaks_its_chain(self):
        self.rec(identity.resolve(None, False, None))
        self.rec(identity.resolve("jay", True, None))
        self.ts.db.execute("DROP TRIGGER identity_observations_append_only_u")   # someone editing the file directly
        self.ts.db.execute("UPDATE identity_observations SET would_refuse=0, reasons='[]' WHERE audit_id=1")
        out = self.a.verify_identity(full=True)
        self.assertEqual((out["ok"], out["brokenAt"]), (False, 1))

    def test_a_bad_shadow_record_never_costs_the_audit_row(self):
        sha = self.rec({"resolvedActor": "jay", "via": "bogus", "reasons": []})
        self.assertEqual(self.ts.db.execute("SELECT sha FROM audit_events").fetchone()[0], sha)
        self.assertEqual(self.ts.db.execute("SELECT COUNT(*) FROM identity_observations").fetchone()[0], 0)
        self.assertEqual(self.a.identity_errors, 1)
        self.assertTrue(self.a.verify(full=True)["ok"])


class OverHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from starlette.testclient import TestClient
        from ccd.api import create_app
        self.store = Store(new_db())
        self.ts = tasks_db()
        self.d = Daemon(cfg(meter={"enabled": False}, phase2_identity_shadow=True), self.store, None, tasks=self.ts)
        self.d.dev_gate = security.DeveloperGate(DEV)
        guarded, _app = create_app(self.d, TOKEN, 7799)
        self.c = TestClient(guarded, base_url="http://127.0.0.1:7799")
        self.h = {"x-ccd-token": TOKEN}
        r = self.c.post("/api/developer/unlock", headers=self.h, json={"token": DEV})
        self.dev = dict(self.h, **{"x-ccd-developer": r.json()["session"]})

    async def asyncTearDown(self):
        self.store.close()

    def issue(self, **body):
        r = self.c.post("/api/actors/issue", headers=self.dev, json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_writes_that_would_be_refused_still_succeed_and_are_recorded(self):
        svc = self.issue(actor="svc:ccd")
        agent = self.issue(actor="agent:coder")
        bound = self.issue(actor="agent:gyst-only", project="gyst")
        cases = [
            ({}, ["missing_header", "unverified", "jay_without_unlock"]),
            ({"x-ccd-actor": "jay"}, ["unverified", "jay_without_unlock"]),
            ({"x-ccd-actor": "agent:coder", "x-ccd-actor-token": agent["token"]}, []),
            ({"x-ccd-actor": "jay", "x-ccd-actor-token": agent["token"]}, ["asserted_mismatch", "jay_without_unlock"]),
            ({"x-ccd-actor": "agent:gyst-only", "x-ccd-actor-token": bound["token"]}, ["project_mismatch"]),
            ({"x-ccd-actor-token": svc["token"]}, ["missing_header", "asserted_mismatch", "jay_without_unlock"]),
            ({"x-ccd-actor": "agent:coder", "x-ccd-actor-token": "cca_a_" + "x" * 43}, ["unverified"]),
        ]
        for extra, reasons in cases:
            with self.subTest(extra=extra):
                r = self.c.post("/api/tasks", headers=dict(self.h, **extra),
                                json={"project": "samvision", "title": "shadow"})
                self.assertEqual(r.status_code, 201)                          # never refused
                e = self.d.audit.list(limit=1)[0]
                self.assertEqual(e["identity"]["reasons"], reasons)
                self.assertFalse(e["identity"]["enforced"])
        state = self.c.get("/api/audit", headers=self.h).json()
        self.assertTrue(state["identityChain"]["ok"])
        self.assertEqual(state["identityErrors"], 0)
        self.assertGreaterEqual(state["identity"]["wouldRefuse"], 5)
        self.assertFalse(state["identity"]["enforced"])
        dump = "\n".join(str(r) for r in self.ts.db.execute("SELECT * FROM identity_observations"))
        for tok in (svc["token"], agent["token"], bound["token"]):
            self.assertNotIn(tok, dump)
        # Unchanged behaviour: X-CCD-Actor still accepts only jay or agent:<name>; svc:<name> is a token subject only.
        r = self.c.post("/api/tasks", headers=dict(self.h, **{"x-ccd-actor": "svc:ccd"}),
                        json={"project": "samvision", "title": "x"})
        self.assertEqual(r.status_code, 400)

    def test_with_the_switch_off_nothing_is_observed(self):
        ts = tasks_db()
        d = Daemon(cfg(meter={"enabled": False}), self.store, None, tasks=ts)
        self.assertFalse(d.identity_shadow_on)
        d.audit_write("POST", "/api/tasks", 201, "jay", {"project": "samvision"}, False, None, asserted=None)
        self.assertEqual(ts.db.execute("SELECT COUNT(*) FROM identity_observations").fetchone()[0], 0)
        self.assertEqual(d.audit.list(limit=1)[0]["identity"], None)
        self.assertFalse(d.audit_state()["identityShadow"])

    def test_issue_and_revoke_typed_and_legacy_over_http(self):
        out = self.issue(actor="svc:backup", project="commandcenter", ttlDays=3)
        self.assertEqual((out["kind"], out["project"]), ("service", "commandcenter"))
        self.assertEqual(self.c.post("/api/actors/issue", headers=self.dev,
                                     json={"actor": "svc:x", "project": "Not A Key"}).status_code, 400)
        lid = add_legacy(self.ts.db)
        listed = self.c.get("/api/actors", headers=self.h).json()
        self.assertNotIn(out["token"], json.dumps(listed))
        r = self.c.post("/api/actors/revoke", headers=self.dev, json={"id": -lid})
        self.assertEqual((r.status_code, r.json()["legacy"], r.json()["status"]), (200, True, "revoked"))


class CliHeader(unittest.TestCase):
    def sent(self, env):
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout):
            seen.update({k.lower(): v for k, v in req.header_items()})
            return Resp(b"{}")
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("urllib.request.urlopen", fake):
            for k in ("CCD_ACTOR_TOKEN", "CCD_ACTOR_TOKEN_FILE"):
                if k not in env:
                    os.environ.pop(k, None)
            pipeline_cli.call("POST", "/api/tasks", {}, actor="agent:coder", port=1, token="t")
        return seen.get("x-ccd-actor-token")

    def test_the_cli_sends_the_token_from_env_or_file_and_never_a_bad_one(self):
        tok = "cca_a_" + "k" * 43
        self.assertEqual(self.sent({"CCD_ACTOR_TOKEN": tok}), tok)
        path = os.path.join(tempfile.mkdtemp(prefix="tok-"), "token")
        with open(path, "w") as f:
            f.write(tok + "\n")
        self.assertEqual(self.sent({"CCD_ACTOR_TOKEN_FILE": path}), tok)
        self.assertIsNone(self.sent({}))
        self.assertIsNone(self.sent({"CCD_ACTOR_TOKEN_FILE": path + ".missing"}))
        self.assertIsNone(self.sent({"CCD_ACTOR_TOKEN": "x" * 101}))
        self.assertIsNone(self.sent({"CCD_ACTOR_TOKEN": "cca_a_é"}))


if __name__ == "__main__":
    unittest.main()
