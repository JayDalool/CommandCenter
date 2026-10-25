"""Phase 2 shadow step 2 (Jay, 2026-10-25): worker node keys and signed heartbeats, RECORDED ONLY.

Jay: "No request may be refused merely because the new Phase 2 check would deny it. Record would-refuse instead."
These tests show the key at enrolment, approval and revocation following the node, each would-refuse reason, the
observation chain, that `enforced` cannot be anything but 0, and that every answer is exactly what it was before."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ccd import nodekeys, workers
from ccd.config import task_projects
from ccd.daemon import ActionError, Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db

PATH = "/api/workers/heartbeat"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def tasks_db():
    return TaskStore(os.path.join(tempfile.mkdtemp(prefix="nk-"), "tasks.db"), task_projects(cfg()))


class Signing(unittest.TestCase):
    def test_message_is_canonical_and_the_header_round_trips(self):
        key = Ed25519PrivateKey.generate()
        a = nodekeys.message("post", PATH, "laptop", 5, "n" * 16, {"b": 1, "a": [2]})
        b = nodekeys.message("POST", PATH, "laptop", 5, "n" * 16, {"a": [2], "b": 1})
        self.assertEqual(a, b)
        self.assertNotEqual(a, nodekeys.message("POST", PATH, "laptop", 5, "n" * 16, {"a": [2], "b": 2}))
        hdr = nodekeys.sign_header(key, "POST", PATH, "laptop", {"x": 1}, ts=7, nonce="m" * 20)
        ts, nonce, sig = nodekeys.parse(hdr)
        self.assertEqual((ts, nonce, len(sig)), (7, "m" * 20, 64))
        for bad in (None, "", "v2 ts=1 nonce=" + "n" * 16 + " sig=" + "s" * 86, hdr + " ", hdr.replace("ts=7", "ts=x"),
                    "v1 ts=1 nonce=short sig=" + "s" * 86, hdr[:-1]):
            if bad == hdr + " ":
                continue                      # surrounding space is stripped
            self.assertIsNone(nodekeys.parse(bad), bad)

    def test_public_keys_and_fingerprints(self):
        key = Ed25519PrivateKey.generate()
        text = nodekeys.public_text(key)
        self.assertEqual(len(text), 43)
        self.assertIsNotNone(nodekeys.public_key(text))
        self.assertRegex(nodekeys.key_fingerprint(text), r"^[0-9a-f]{4}(-[0-9a-f]{4}){3}$")
        for bad in (None, 7, "", "x" * 42, "x" * 44, "!" * 43):
            self.assertIsNone(nodekeys.public_key(bad), bad)

    def test_init_writes_a_private_key_only_its_owner_can_read_and_never_overwrites(self):
        d = os.path.join(tempfile.mkdtemp(prefix="nkk-"), "key")
        text, fp = nodekeys.init(d)
        self.assertEqual(os.stat(os.path.join(d, "node.key")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        self.assertEqual(nodekeys.public_text(nodekeys.load(d)), text)
        self.assertEqual(nodekeys.key_fingerprint(text), fp)
        with self.assertRaises(FileExistsError):
            nodekeys.init(d)
        self.assertEqual(nodekeys.main(["show", "--dir", d]), 0)


class Model(unittest.TestCase):
    def setUp(self):
        self.ts = tasks_db()
        self.clock = Clock()
        self.k = nodekeys.NodeKeys(self.ts.db, self.clock)
        self.w = workers.Workers(self.ts.db, self.clock, keys=self.k)
        self.key = Ed25519PrivateKey.generate()
        self.tok = self.w.enrol("laptop", "laptop", {}, "1", "jay")["token"]
        self.fp = self.k.add("laptop", nodekeys.public_text(self.key), "jay")

    def check(self, header, body=None, token_ok=True, node="laptop"):
        return self.k.check(node, "POST", PATH, header, body or {}, self.w.state(node), token_ok)["reasons"]

    def signed(self, body=None, **kw):
        return nodekeys.sign_header(self.key, "POST", PATH, "laptop", body or {}, ts=kw.pop("ts", self.clock()), **kw)

    def test_each_reason(self):
        self.assertEqual(self.check(None), ["node_pending", "unsigned", "key_not_approved"])
        self.w.approve("laptop", "jay")
        self.assertTrue(self.k.key("laptop")["approved"])                    # the key follows the node's approval
        self.assertEqual(self.check(self.signed()), [])
        self.assertEqual(self.check(None), ["unsigned"])
        self.assertEqual(self.check("v1 nonsense"), ["malformed"])
        self.assertEqual(self.check(self.signed(), body={"version": "tampered"}), ["bad_signature"])
        other = nodekeys.sign_header(Ed25519PrivateKey.generate(), "POST", PATH, "laptop", {}, ts=self.clock())
        self.assertEqual(self.check(other), ["bad_signature"])
        self.assertEqual(self.check(self.signed(ts=self.clock() - 61)), ["stale_timestamp"])
        self.assertEqual(self.check(self.signed(ts=self.clock() + 61)), ["stale_timestamp"])
        replay = self.signed(nonce="r" * 20)
        self.assertEqual(self.check(replay), [])
        self.assertEqual(self.check(replay), ["replayed_nonce"])
        self.clock.t += nodekeys.NONCE_TTL + 1                               # remembered for NONCE_TTL, then pruned
        self.assertEqual(self.check(nodekeys.sign_header(self.key, "POST", PATH, "laptop", {}, ts=self.clock(),
                                                         nonce="r" * 20)), [])
        self.assertEqual(self.check(self.signed(), token_ok=False), ["bad_node_token"])
        self.w.revoke("laptop", "jay")
        self.assertIsNone(self.k.key("laptop"))                              # revoking the node revokes its key
        self.assertEqual(self.check(self.signed()), ["node_revoked", "no_key"])
        self.assertEqual(self.check(None, node="ghost"), ["unsigned", "no_key"])

    def test_a_bad_signature_never_burns_a_nonce(self):
        self.w.approve("laptop", "jay")
        forged = nodekeys.sign_header(Ed25519PrivateKey.generate(), "POST", PATH, "laptop", {}, ts=self.clock(),
                                      nonce="z" * 20)
        self.check(forged)
        self.assertEqual(self.check(self.signed(nonce="z" * 20)), [])

    def test_schema_keeps_keys_as_history(self):
        self.w.approve("laptop", "jay")
        for sql in ("DELETE FROM node_keys", "UPDATE node_keys SET public_key='" + "A" * 43 + "'",
                    "UPDATE node_keys SET approved_at=NULL, approved_by=NULL", "UPDATE node_keys SET added_by='x'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.ts.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):                      # one live key per node
            self.k.add("laptop", nodekeys.public_text(Ed25519PrivateKey.generate()), "jay")
        with self.assertRaises(sqlite3.DatabaseError):
            self.ts.db.execute("INSERT OR REPLACE INTO node_keys (id, node_id, public_key, key_fp, added_at, added_by) "
                               "SELECT id, node_id, public_key, key_fp, added_at, added_by FROM node_keys")
        with self.assertRaises(sqlite3.IntegrityError):                      # an agent never adds a key
            self.ts.db.execute("INSERT INTO node_keys (node_id, public_key, key_fp, added_at, added_by) VALUES "
                               "('laptop', ?, '0000-0000-0000-0000', 0, 'agent:x')", ("B" * 43,))
        self.assertIsNone(self.k.add("laptop", "not a key", "jay"))

    def test_observations_are_a_chain_that_refuses_enforced_and_edits(self):
        self.k.observe("laptop", "heartbeat", 200, self.k.check("laptop", "POST", PATH, None, {}, "pending"))
        self.k.observe("laptop", "enrol", 200, {"reasons": ["no_key", "made_up"]})
        rows = self.ts.db.execute("SELECT kind, would_refuse, reasons, enforced FROM node_observations").fetchall()
        self.assertEqual([(r[0], r[1], r[3]) for r in rows], [("heartbeat", 1, 0), ("enrol", 1, 0)])
        self.assertEqual(json.loads(rows[1][2]), ["no_key"])                 # unknown reasons are dropped
        self.assertEqual(self.k.verify(full=True)["ok"], True)
        for sql in ("UPDATE node_observations SET would_refuse=0", "DELETE FROM node_observations"):
            with self.assertRaises(sqlite3.DatabaseError):
                self.ts.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ts.db.execute("INSERT INTO node_observations (at, node_id, kind, outcome, signed, verified, "
                               "would_refuse, enforced, prev_sha, sha) VALUES (0, 'x', 'enrol', 200, 0, 0, 0, 1, 'p', 's')")
        self.ts.db.execute("DROP TRIGGER node_observations_append_only_u")
        self.ts.db.execute("UPDATE node_observations SET would_refuse=0 WHERE id=1")
        self.assertEqual(self.k.verify(full=True)["brokenAt"], 1)
        s = self.k.summary(since=0)
        self.assertEqual((s["total"], s["enforced"], s["nodes"]["laptop"]["byReason"]["no_key"]), (2, False, 1))

    def test_a_failing_observation_is_counted_not_raised(self):
        self.ts.db.execute("DROP TABLE node_observations")
        self.k.observe("laptop", "heartbeat", 200, {"reasons": []})
        self.assertEqual(self.k.errors, 1)


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(new_db())
        self.ts = tasks_db()
        self.d = Daemon(cfg(phase2_node_shadow=True), self.store, None, tasks=self.ts)
        self.key = Ed25519PrivateKey.generate()

    async def asyncTearDown(self):
        self.store.close()

    def obs(self):
        return [(r[0], r[1], json.loads(r[2])) for r in self.ts.db.execute(
            "SELECT kind, outcome, reasons FROM node_observations ORDER BY id")]

    async def test_enrol_records_the_key_and_answers_as_before(self):
        out = self.d.worker_enrol({"id": "laptop", "kind": "laptop", "publicKey": nodekeys.public_text(self.key)}, "jay")
        self.assertEqual(out["keyFingerprint"], self.d.workers_state()["nodes"][0]["key"]["fingerprint"])
        bad = self.d.worker_enrol({"id": "gpu-1", "kind": "gpu", "publicKey": "nope"}, "jay")   # still enrolled
        self.assertEqual((bad["status"], "keyFingerprint" in bad), ("pending", False))
        self.d.worker_enrol({"id": "cloud-1", "kind": "cloud"}, "jay")
        self.assertEqual(self.obs(), [("enrol", 200, []), ("enrol", 200, ["bad_key"]), ("enrol", 200, ["no_key"])])

    async def test_heartbeats_that_would_be_refused_still_answer_exactly_as_before(self):
        out = self.d.worker_enrol({"id": "laptop", "kind": "laptop", "publicKey": nodekeys.public_text(self.key)}, "jay")
        tok = out["token"]
        self.assertEqual(self.d.worker_heartbeat("laptop", tok, {})["status"], "pending")      # unsigned, pending
        self.d.act_worker("approve", "laptop", "jay", developer=True)
        sig = nodekeys.sign_header(self.key, "POST", PATH, "laptop", {"version": "2"})
        self.assertEqual(self.d.worker_heartbeat("laptop", tok, {"version": "2"}, signature=sig)["status"], "active")
        with self.assertRaises(ActionError) as e:                            # wrong token: refused as before
            self.d.worker_heartbeat("laptop", "wrong", {"version": "2"}, signature=sig)
        self.assertEqual(e.exception.status, 401)
        self.assertEqual([o[1:] for o in self.obs()[1:]], [
            (200, ["node_pending", "unsigned", "key_not_approved"]), (200, []), (401, ["bad_node_token", "replayed_nonce"])])
        state = self.d.workers_state()
        self.assertTrue(state["nodeShadow"])
        self.assertTrue(state["shadow"]["chain"]["ok"])
        self.assertFalse(state["shadow"]["enforced"])

    async def test_a_broken_shadow_check_never_touches_the_heartbeat(self):
        tok = self.d.worker_enrol({"id": "laptop", "kind": "laptop"}, "jay")["token"]
        with mock.patch.object(self.d.node_keys, "check", side_effect=RuntimeError("boom")):
            self.assertEqual(self.d.worker_heartbeat("laptop", tok, {})["status"], "pending")
        self.assertEqual(self.d.node_keys.errors, 1)

    async def test_with_the_switch_off_nothing_is_recorded_and_a_key_is_ignored(self):
        d = Daemon(cfg(), self.store, None, tasks=self.ts)
        self.assertFalse(d.node_shadow_on)
        out = d.worker_enrol({"id": "laptop", "kind": "laptop", "publicKey": nodekeys.public_text(self.key)}, "jay")
        self.assertNotIn("keyFingerprint", out)
        d.worker_heartbeat("laptop", out["token"], {})
        for t in ("node_keys", "node_observations", "node_nonces"):
            self.assertEqual(self.ts.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0)
        self.assertNotIn("shadow", d.workers_state())


class OverHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from starlette.testclient import TestClient
        from ccd.api import create_app
        self.store = Store(new_db())
        self.ts = tasks_db()
        self.d = Daemon(cfg(phase2_node_shadow=True), self.store, None, tasks=self.ts)
        guarded, _app = create_app(self.d, "t" * 43, 7799)
        self.c = TestClient(guarded, base_url="http://127.0.0.1:7799")
        self.h = {"x-ccd-token": "t" * 43}

    async def asyncTearDown(self):
        self.store.close()

    def test_the_signature_header_is_checked_over_the_real_path_and_body(self):
        key = Ed25519PrivateKey.generate()
        out = self.c.post("/api/workers/enrol", headers=self.h,
                          json={"id": "laptop", "kind": "laptop", "publicKey": nodekeys.public_text(key)}).json()
        self.d.act_worker("approve", "laptop", "jay", developer=True)
        body = {"version": "3", "capabilities": {"os": "linux"}}
        sig = nodekeys.sign_header(key, "POST", PATH, "laptop", body)
        h = dict(self.h, **{"x-ccd-node": f"laptop {out['token']}", "x-ccd-node-signature": sig})
        self.assertEqual(self.c.post(PATH, headers=h, json=body).status_code, 200)
        r = self.c.post(PATH, headers=dict(h, **{"x-ccd-node-signature": "garbage"}), json=body)
        self.assertEqual(r.status_code, 200)                                 # never refused
        reasons = [json.loads(x[0]) for x in self.ts.db.execute("SELECT reasons FROM node_observations ORDER BY id")]
        self.assertEqual(reasons[-2:], [[], ["malformed"]])


if __name__ == "__main__":
    unittest.main()
