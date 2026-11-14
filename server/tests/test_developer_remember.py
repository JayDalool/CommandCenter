"""Contract §6: Developer Unlock lasts. Sessions survive a ccd restart as HMACs only, "Remember this device" lasts
30 days with no idle limit, "Lock all devices" ends every one, and the terminal and file writes still need the secret
typed within 8 hours."""
import json
import os
import shutil
import stat
import tempfile
import unittest

from ccd import identity, security
from ccd.files import Roots
from ccd import attachments as attach_mod

from .test_api import JSON, TOKEN, ApiBase

DEV = "d" * 43
HOUR = 3600
DAY = 86400


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="devsess-")
        self.path = os.path.join(self.dir, "data", "developer-sessions.json")
        self.now = [1_800_000_000.0]

    def tearDown(self):
        shutil.rmtree(self.dir)

    def gate(self, secret=DEV):
        return security.DeveloperGate(secret, clock=lambda: self.now[0], path=self.path)


class Persistence(Base):
    def test_an_unlock_survives_a_restart_and_the_file_holds_no_secret(self):
        g = self.gate()
        sid, _ = g.unlock(DEV)
        rid, _ = g.unlock(DEV, remember=True, label="Chrome on Windows")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        raw = open(self.path).read()
        self.assertNotIn(sid, raw)
        self.assertNotIn(rid, raw)
        self.assertNotIn(DEV, raw)
        again = self.gate()                                         # ccd restarted
        self.assertTrue(again.check(sid))
        self.assertTrue(again.check(rid))
        self.assertEqual(sorted(d["label"] for d in again.devices()), ["Browser", "Chrome on Windows"])

    def test_a_new_developer_token_ends_every_saved_session(self):
        g = self.gate()
        sid, _ = g.unlock(DEV, remember=True)
        other = self.gate("e" * 43)
        self.assertFalse(other.check(sid))
        self.assertEqual(other.devices(), [])

    def test_lock_and_lock_all_reach_the_disk(self):
        g = self.gate()
        a, _ = g.unlock(DEV, remember=True)
        b, _ = g.unlock(DEV)
        g.lock(a)
        self.assertFalse(self.gate().check(a))
        self.assertTrue(self.gate().check(b))
        code, _ = g.handoff(DEV)
        self.assertEqual(g.lock_all(), 2)                           # b and the SSH session
        self.assertIsNone(g.redeem(code)[0])                        # an unredeemed code goes too
        self.assertFalse(self.gate().check(b))
        self.assertEqual(json.load(open(self.path))["sessions"], [])

    def test_an_edited_file_cannot_stretch_a_session(self):
        g = self.gate()
        sid, _ = g.unlock(DEV)                                      # plain: 8 h, 2 h idle
        data = json.load(open(self.path))
        data["sessions"][0].update(ttl=10 ** 9, idle=None, made=self.now[0] + 10 * DAY)
        with open(self.path, "w") as f:
            json.dump(data, f)
        self.assertFalse(self.gate().check(sid))                   # a time from the future is not believed
        data["sessions"][0].update(made=self.now[0], kind="nonsense")
        with open(self.path, "w") as f:
            json.dump(data, f)
        self.assertFalse(self.gate().check(sid))
        data["sessions"][0].update(kind="plain")
        with open(self.path, "w") as f:
            json.dump(data, f)
        self.now[0] += 3 * HOUR                                     # past the plain idle limit, whatever the file says
        self.assertFalse(self.gate().check(sid))

    def test_an_entry_written_without_the_secret_matches_nothing(self):
        g = self.gate()
        g.unlock(DEV)
        forged = security.DeveloperGate("x" * 43, clock=lambda: self.now[0])._key("my-own-id")
        data = json.load(open(self.path))
        data["sessions"].append(dict(data["sessions"][0], key=forged, kind="remember"))
        with open(self.path, "w") as f:
            json.dump(data, f)
        self.assertFalse(self.gate().check("my-own-id"))

    def test_a_file_others_can_read_is_ignored(self):
        g = self.gate()
        sid, _ = g.unlock(DEV, remember=True)
        os.chmod(self.path, 0o644)
        again = self.gate()
        self.assertFalse(again.check(sid))
        self.assertIn("permissions", again.save_error)
        again.unlock(DEV)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_a_broken_file_starts_empty(self):
        os.makedirs(os.path.dirname(self.path))
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd, b"{not json")
        os.close(fd)
        g = self.gate()
        self.assertEqual(g.devices(), [])
        self.assertTrue(g.unlock(DEV)[0])


class Remember(Base):
    def test_a_remembered_device_lasts_thirty_days_with_no_idle_limit(self):
        g = self.gate()
        sid, _ = g.unlock(DEV, remember=True)
        self.now[0] += 10 * DAY                                     # ten days untouched
        self.assertTrue(g.check(sid))
        self.assertTrue(self.gate().check(sid))                     # and across a restart
        self.now[0] += 20 * DAY + 1
        self.assertFalse(g.check(sid))
        self.assertEqual(self.gate().devices(), [])

    def test_a_plain_unlock_keeps_todays_limits(self):
        g = self.gate()
        sid, _ = g.unlock(DEV)
        self.assertEqual(g.describe(sid)["idleLimit"], g.IDLE)
        self.assertFalse(g.describe(sid)["remembered"])
        self.now[0] += g.IDLE + 1
        self.assertFalse(g.check(sid))

    def test_terminal_and_file_writes_need_the_secret_within_eight_hours(self):
        g = self.gate()
        sid, _ = g.unlock(DEV, remember=True)
        self.now[0] += 7 * HOUR
        self.assertTrue(g.check(sid, fresh=True))
        self.now[0] += 2 * HOUR
        self.assertTrue(g.check(sid))                               # approvals and steering: still unlocked
        self.assertFalse(g.check(sid, fresh=True))                  # a shell or a file write: not any more
        self.assertTrue(g.needs_reentry(sid))
        self.assertEqual(g.expires_in(sid, fresh=True), 0)
        same, _ = g.unlock(DEV, remember=True, current=sid)        # typing it again re-proves the same session
        self.assertEqual(same, sid)
        self.assertTrue(g.check(sid, fresh=True))
        self.assertEqual(len(g.devices()), 1)

    def test_a_wrong_secret_never_reproves_and_still_counts(self):
        g = self.gate()
        sid, _ = g.unlock(DEV, remember=True)
        self.now[0] += 9 * HOUR
        for _ in range(5):
            self.assertIsNone(g.unlock("wrong", remember=True, current=sid)[0])
        self.assertIn("too many", g.unlock(DEV, remember=True, current=sid)[1])
        self.assertFalse(g.check(sid, fresh=True))

    def test_plain_and_ssh_sessions_are_never_stale_for_the_terminal(self):
        g = self.gate()
        sid, _ = g.unlock(DEV)
        code, _ = g.handoff(DEV)
        ssh, _ = g.redeem(code)
        self.now[0] += g.IDLE - 60
        self.assertTrue(g.check(sid, fresh=True))
        self.now[0] += 9 * HOUR - g.IDLE
        self.assertTrue(g.check(ssh, fresh=True))                   # SSH sign-in keeps its whole 12 h day

    def test_unlocking_again_on_a_device_replaces_its_plain_session(self):
        g = self.gate()
        a, _ = g.unlock(DEV)
        b, _ = g.unlock(DEV, current=a)
        self.assertNotEqual(a, b)
        self.assertFalse(g.check(a))
        self.assertEqual(len(g.devices()), 1)
        c, _ = g.unlock(DEV, remember=True, current=b)              # ticking "remember" upgrades it in place
        self.assertEqual(c, b)
        self.assertTrue(g.describe(c)["remembered"])

    def test_devices_never_show_a_session_id(self):
        g = self.gate()
        sid, _ = g.unlock(DEV, remember=True, label="Phone\x1b[31m  red")
        devices = g.devices(sid)
        self.assertEqual(devices[0]["label"], "Phone [31m red")      # control characters gone, the rest is text
        self.assertTrue(devices[0]["current"])
        self.assertNotIn(sid, json.dumps(devices))
        self.assertNotIn(g._key(sid), json.dumps(devices))

    def test_identity_peek_does_not_refresh(self):
        g = self.gate()
        sid, _ = g.unlock(DEV)
        used = g.devices()[0]["lastUsedAt"]
        self.now[0] += 100
        self.assertTrue(identity.developer_session_valid(g, sid))
        self.assertEqual(g.devices()[0]["lastUsedAt"], used)


class Api(ApiBase):
    def equip(self, daemon):
        self.base = tempfile.mkdtemp(prefix="devapi-")
        self.root = os.path.join(self.base, "repo")
        os.makedirs(self.root)
        daemon.files = Roots({"samvision": self.root}, upload_max=4096)
        daemon.attachments = attach_mod.Attachments(os.path.join(self.base, "att.db"),
                                                    os.path.join(self.base, "blobs"), 4096)
        self.now = [1_800_000_000.0]
        daemon.dev_gate = security.DeveloperGate(DEV, clock=lambda: self.now[0],
                                                 path=os.path.join(self.base, "developer-sessions.json"))

    def tearDown(self):
        super().tearDown()
        self.daemon.attachments.close()
        shutil.rmtree(self.base)

    def unlock(self, **body):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV, **body}),
                             headers=dict(JSON, **{"user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0"}))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_unlock_says_which_kind_it_gave(self):
        plain = self.unlock()
        self.assertEqual((plain["remembered"], plain["idleLimit"]), (False, 2 * HOUR))
        kept = self.unlock(remember=True)
        self.assertEqual((kept["remembered"], kept["idleLimit"]), (True, None))
        self.assertEqual(kept["expiresIn"], 30 * DAY)
        self.assertEqual(kept["reenterIn"], 8 * HOUR)
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV, "remember": "yes"}),
                             headers=JSON)
        self.assertEqual(r.status_code, 400)
        st = self.client.get("/api/developer", headers=dict(JSON, **{"x-ccd-developer": kept["session"]})).json()
        self.assertEqual((st["active"], st["remembered"]), (True, True))

    def test_devices_and_lock_all_need_a_developer_session(self):
        self.assertEqual(self.client.get("/api/developer/devices", headers=JSON).status_code, 403)
        self.assertEqual(self.client.post("/api/developer/lock-all", content="{}", headers=JSON).status_code, 403)
        a = self.unlock(remember=True)["session"]
        b = self.unlock(label="Phone")["session"]
        dev = dict(JSON, **{"x-ccd-developer": a})
        devices = self.client.get("/api/developer/devices", headers=dev).json()["devices"]
        self.assertEqual(sorted(d["label"] for d in devices), ["Chrome on Windows", "Phone"])
        self.assertNotIn(a, json.dumps(devices))
        r = self.client.post("/api/developer/lock-all", content="{}", headers=dev)
        self.assertEqual(r.json(), {"ok": True, "ended": 2})
        for sid in (a, b):
            self.assertFalse(self.client.get("/api/developer",
                                             headers=dict(JSON, **{"x-ccd-developer": sid})).json()["active"])

    def test_a_stale_remembered_device_must_reenter_to_write_files(self):
        sid = self.unlock(remember=True)["session"]
        dev = dict(JSON, **{"x-ccd-developer": sid})
        body = json.dumps({"project": "samvision", "path": "a", "kind": "dir"})
        self.now[0] += 9 * HOUR
        r = self.client.post("/api/files/mkdir", content=body, headers=dev)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json().get("reenter"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "a")))
        st = self.client.get("/api/developer", headers=dev).json()
        self.assertEqual((st["active"], st["reenterIn"]), (True, 0))
        again = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV, "remember": True}),
                                 headers=dev).json()
        self.assertEqual(again["session"], sid)
        r = self.client.post("/api/files/mkdir", content=body, headers=dev)
        self.assertNotEqual(r.status_code, 403, r.text)

    def test_the_ccd_token_is_never_a_developer_session(self):
        self.unlock(remember=True)
        bad = dict(JSON, **{"x-ccd-developer": TOKEN})
        self.assertEqual(self.client.post("/api/developer/lock-all", content="{}", headers=bad).status_code, 403)


if __name__ == "__main__":
    unittest.main()
