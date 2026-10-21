"""Worker nodes (ccd/workers.py, tasks.db migration 8): the server registers itself; other nodes enrol, wait for
Jay, heartbeat with their own token and can be revoked for good. Nothing is scheduled on a node yet."""
import json
import os
import sqlite3
import tempfile
import unittest

from ccd import workers
from ccd.config import task_projects
from ccd.daemon import ActionError, Daemon
from ccd.store import Store
from ccd.tasks import TaskStore

from .helpers import cfg, new_db

LAPTOP = {"os": "linux", "arch": "x86_64", "tools": ["git", "claude"], "repos": ["employer-java"]}


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class Model(unittest.TestCase):
    def setUp(self):
        self.ts = TaskStore(os.path.join(tempfile.mkdtemp(prefix="wk-"), "tasks.db"), task_projects(cfg()))
        self.clock = Clock()
        self.w = workers.Workers(self.ts.db, clock=self.clock)

    def test_the_server_registers_itself_once_and_heartbeats_on_a_cadence(self):
        self.w.register_server("0.4.0", {"os": "linux", "tools": ["git"], "repos": ["commandcenter"]})
        self.w.register_server("0.4.1", {"os": "linux", "tools": ["git", "gh"], "repos": ["commandcenter"]})
        [n] = self.w.list()
        self.assertEqual((n["id"], n["kind"], n["status"], n["version"], n["capabilities"]["tools"]),
                         ("server", "server", "online", "0.4.1", ["git", "gh"]))
        self.assertEqual([e["kind"] for e in self.w.events()], ["registered"])
        self.clock.t += 10
        self.assertFalse(self.w.server_heartbeat())
        self.clock.t += workers.HEARTBEAT_EVERY
        self.assertTrue(self.w.server_heartbeat())
        self.clock.t += workers.ONLINE_FOR + 1
        self.assertEqual(self.w.list()[0]["status"], "offline")

    def test_a_node_enrols_waits_for_jay_heartbeats_with_its_own_token_and_can_be_revoked_for_good(self):
        out = self.w.enrol("laptop", "laptop", LAPTOP, "1.0", "jay")
        token = out["token"]
        self.assertEqual(out["status"], "pending")
        row = self.ts.db.execute("SELECT token_sha FROM worker_nodes WHERE id='laptop'").fetchone()[0]
        self.assertNotIn(token, row)                                          # only the hash is kept
        self.assertEqual(self.w.heartbeat("laptop", token)["status"], "pending")
        self.assertEqual(self.w.node("laptop")["status"], "pending")         # pending never shows online
        for bad in ("nope", "", None, token + "x"):
            with self.assertRaises(workers.WorkerError) as e:
                self.w.heartbeat("laptop", bad)
            self.assertEqual(e.exception.status, 401)
        with self.assertRaises(workers.WorkerError):
            self.w.approve("laptop", "agent:coordinator")                     # a node or agent never approves
        self.w.approve("laptop", "jay")
        self.w.heartbeat("laptop", token, {"tools": ["git"]}, "1.1")
        n = self.w.node("laptop")
        self.assertEqual((n["status"], n["approvedBy"], n["version"], n["capabilities"]), ("online", "jay", "1.1", {"tools": ["git"]}))
        self.w.revoke("laptop", "jay", "lost")
        with self.assertRaises(workers.WorkerError) as e:
            self.w.heartbeat("laptop", token)
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(workers.WorkerError):
            self.w.enrol("laptop", "laptop", LAPTOP, "1.0", "jay")            # a revoked name is not reused
        self.assertEqual([e["kind"] for e in reversed(self.w.events())], ["enrolled", "approved", "revoked"])

    def test_enrolment_input_is_checked(self):
        for args in (("server", "laptop"), ("Bad Name", "laptop"), ("x", "laptop"), ("gpu-1", "server"),
                     ("gpu-1", "mainframe")):
            with self.assertRaises(workers.WorkerError, msg=args):
                self.w.enrol(*args, {}, "1", "jay")
        for caps in ("x", {"tools": "git"}, {"tools": ["ok", "no spaces"]}, {"os": "x" * 41}):
            with self.assertRaises(workers.WorkerError, msg=caps):
                self.w.enrol("gpu-1", "gpu", caps, "1", "jay")
        self.assertEqual(workers.clean_caps({"tools": ["git", "git"], "evil": 1}), {"tools": ["git"]})

    def test_the_schema_keeps_nodes_honest(self):
        self.w.register_server("1", {})
        out = self.w.enrol("laptop", "laptop", {}, "1", "jay")
        db = self.ts.db
        for sql in ("DELETE FROM worker_nodes WHERE id='laptop'",
                    "UPDATE worker_nodes SET status='active', approved_by='agent:x' WHERE id='laptop'",
                    "UPDATE worker_nodes SET status='active' WHERE id='laptop'",          # active needs Jay
                    "UPDATE worker_nodes SET token_sha='x' WHERE id='laptop'",
                    "UPDATE worker_events SET kind='approved'", "DELETE FROM worker_events"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql)
        self.w.revoke("laptop", "jay")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE worker_nodes SET status='active', approved_by='jay' WHERE id='laptop'")
        with self.assertRaises(workers.WorkerError):
            self.w.revoke("server", "jay")
        self.assertTrue(out["token"])


class InTheDaemon(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(new_db())
        self.ts = TaskStore(os.path.join(tempfile.mkdtemp(prefix="wkd-"), "tasks.db"), task_projects(cfg()))
        self.d = Daemon(cfg(), self.store, None, tasks=self.ts)

    async def asyncTearDown(self):
        self.store.close()

    async def test_start_registers_the_server_and_approval_needs_jay_and_developer_unlock(self):
        self.d._workers_start()
        self.assertEqual([n["id"] for n in self.d.workers_state()["nodes"]], ["server"])
        self.assertTrue(any(e["kind"] == "worker.server" for e in self.store.since(0)))
        out = self.d.worker_enrol({"id": "laptop", "kind": "laptop", "capabilities": LAPTOP}, "jay")
        self.assertTrue(any(e["kind"] == "worker.enrolled" and e["severity"] == "action" for e in self.store.since(0)))
        for actor, dev in (("jay", False), ("agent:coordinator", True)):
            with self.assertRaises(ActionError) as e:
                self.d.act_worker("approve", "laptop", actor, developer=dev)
            self.assertEqual(e.exception.status, 403)
        self.assertEqual(self.d.act_worker("approve", "laptop", "jay", developer=True)["state"], "active")
        self.assertEqual(self.d.worker_heartbeat("laptop", out["token"], {})["status"], "active")
        with self.assertRaises(ActionError) as e:
            self.d.worker_heartbeat("laptop", "wrong", {})
        self.assertEqual(e.exception.status, 401)

    async def test_a_broken_workers_table_never_stops_ccd(self):
        self.d.workers.register_server = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        self.d._workers_start()
        self.d.workers.server_heartbeat = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        self.d._workers_beat()

    async def test_no_task_system(self):
        d = Daemon(cfg(), self.store, None)
        self.assertEqual(d.workers_state()["available"], False)
        d._workers_start()
        with self.assertRaises(ActionError):
            d.worker_enrol({"id": "laptop", "kind": "laptop"}, "jay")


if __name__ == "__main__":
    unittest.main()
