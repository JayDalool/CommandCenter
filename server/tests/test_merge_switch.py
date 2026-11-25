"""Jay's per-repository auto-merge switch (ccd/merge_switch.py, Settings › Auto-merge): the stored file and how it
fails closed, that it wins over config.json and takes effect without a restart, and who may press it over HTTP."""
import json
import os
import stat
import tempfile
import unittest

from ccd import registry
from ccd.merge_switch import MergeSwitch, MergeSwitchError

from .test_api import JSON, ApiBase
from .test_auto_merge import Base


def tmp_path():
    return os.path.join(tempfile.mkdtemp(prefix="switch-"), "auto-merge.json")


class Store(unittest.TestCase):
    def test_no_file_means_config_decides(self):
        s = MergeSwitch(tmp_path())
        self.assertIsNone(s.problem)
        self.assertIsNone(s.get("commandcenter"))
        self.assertTrue(s.effective("commandcenter", ["commandcenter"]))
        self.assertFalse(s.effective("mfe", ["commandcenter"]))

    def test_the_switch_wins_over_config_both_ways_and_survives_a_restart(self):
        p = tmp_path()
        s = MergeSwitch(p)
        s.set("commandcenter", False, now=100)
        s.set("mfe", True, now=101)
        again = MergeSwitch(p)
        self.assertFalse(again.effective("commandcenter", ["commandcenter"]))
        self.assertTrue(again.effective("mfe", []))
        self.assertEqual(again.get("mfe"), {"on": True, "at": 101, "by": "jay"})
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual([n for n in os.listdir(os.path.dirname(p)) if n.startswith(".")], [])   # no temp file left

    def test_a_damaged_file_switches_every_project_off(self):
        for text in ("{not json", "[]", json.dumps({"projects": {"mfe": {"on": "yes"}}}),
                     json.dumps({"projects": {"../x": {"on": True}}}), json.dumps({"projects": []})):
            p = tmp_path()
            with open(p, "w") as f:
                f.write(text)
            s = MergeSwitch(p)
            self.assertTrue(s.problem, text)
            self.assertNotIn("yes", s.problem)              # never the file's own text
            self.assertFalse(s.effective("commandcenter", ["commandcenter"]), text)

    def test_repairing_a_damaged_file_with_one_press_keeps_the_others_off(self):
        p = tmp_path()
        with open(p, "w") as f:
            f.write("{oops")
        s = MergeSwitch(p)
        s.set("mfe", True, known=["commandcenter", "mfe", "gyst"])
        self.assertIsNone(s.problem)
        self.assertTrue(s.effective("mfe", []))
        self.assertFalse(s.effective("commandcenter", ["commandcenter"]))   # written as off, not handed to config
        self.assertEqual(MergeSwitch(p).get("gyst")["on"], False)

    def test_bad_input_is_refused(self):
        s = MergeSwitch(tmp_path())
        with self.assertRaises(MergeSwitchError):
            s.set("../etc", True)
        with self.assertRaises(MergeSwitchError):
            s.set("mfe", "on")


class TakesEffectAtOnce(Base):
    """The daemon: the switch changes what ccd merges on the next pass, with no restart."""

    def make(self, **over):
        over.setdefault("auto_merge_switch_path", self.switch_path)
        return super().make(**over)

    async def asyncSetUp(self):
        self.switch_path = tmp_path()
        await super().asyncSetUp()

    async def test_switching_on_in_settings_merges_without_a_restart(self):
        self.daemon = self.make(auto_merge=[])
        self.daemon.auto_merge_set("commandcenter", {"on": True}, "jay", developer=True)
        self.assertEqual(self.daemon.auto_merge_list, ["commandcenter"])
        k = self.ready()
        self.assertIsNone(self.daemon.pipeline.work(k)["gate"])
        await self.daemon._auto_merge()
        self.assertEqual(len(self.gh.of("merge")), 1)
        ev = self.events("merge.switch")
        self.assertEqual([(e["source"], e["project"], e["data"]["status"]) for e in ev],
                         [("security", "commandcenter", "on")])

    async def test_switching_off_beats_config_and_the_ready_pr_waits_for_jay(self):
        self.daemon = self.make(auto_merge=["commandcenter"])
        self.daemon.auto_merge_set("commandcenter", {"on": False}, "jay")      # off needs no Developer Unlock
        self.assertEqual((self.daemon.auto_merge_list, self.daemon.auto_merge_on), ([], False))
        k = self.ready()
        self.assertEqual(self.daemon.pipeline.work(k)["gate"], "merge")       # Jay's merge question, as `owner`
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.calls, [])
        st = self.daemon.auto_merge_state()["projects"]["commandcenter"]
        self.assertEqual((st["on"], st["source"], st["available"]), (False, "settings", True))

    async def test_the_switch_is_kept_across_a_restart(self):
        self.daemon = self.make(auto_merge=[])
        self.daemon.auto_merge_set("commandcenter", {"on": True}, "jay", developer=True)
        self.assertEqual(self.make(auto_merge=[]).auto_merge_list, ["commandcenter"])

    async def test_a_project_that_cannot_auto_merge_cannot_be_switched_on(self):
        from ccd.daemon import ActionError
        for key in ("gauzemate",):                                            # a client's repository, and paused
            with self.assertRaises(ActionError) as e:
                self.daemon.auto_merge_set(key, {"on": True}, "jay", developer=True)
            self.assertIn(e.exception.status, (404, 409))
        # A hand-edited file cannot do it either.
        with open(self.switch_path, "w") as f:
            json.dump({"projects": {"gauzemate": {"on": True}}}, f)
        self.assertNotIn("gauzemate", self.make().auto_merge_list)

    async def test_the_stop_file_still_stops_a_switched_on_project(self):
        self.daemon = self.make(auto_merge=[])
        self.daemon.auto_merge_set("commandcenter", {"on": True}, "jay", developer=True)
        k = self.ready()
        open(self.daemon.auto_merge_stop, "w").close()
        await self.daemon._auto_merge()
        self.assertEqual(self.gh.of("merge"), [])
        self.assertTrue(self.daemon.auto_merge_state()["stopped"])
        self.assertEqual(self.tickets.get(k)["status"], "READY_TO_MERGE")

    async def test_a_damaged_switch_file_is_said_at_start(self):
        with open(self.switch_path, "w") as f:
            f.write("{oops")
        d = self.make(auto_merge=["commandcenter"])
        self.assertEqual(d.auto_merge_list, [])                               # off, not back to config
        before = len(self.events("merge.config"))
        d._log_merge_policy()
        self.assertEqual(len(self.events("merge.config")), before + 1)


class SwitchApi(ApiBase):
    """Over HTTP: only Jay switches; on also needs Developer Unlock; off does not."""
    DEV = "d" * 43

    def equip(self, daemon):
        from ccd import security
        from ccd.merge_switch import MergeSwitch as MS
        daemon.dev_gate = security.DeveloperGate(self.DEV)
        daemon.merge_switch = MS(tmp_path())
        daemon._apply_auto_merge()

    def dev(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": self.DEV}), headers=JSON)
        return dict(JSON, **{"x-ccd-developer": r.json()["session"]})

    def put(self, project, on, headers=None):
        return self.client.put(f"/api/auto-merge/projects/{project}", content=json.dumps({"on": on}),
                               headers=headers or JSON)

    def test_state_lists_every_project_with_why_it_cannot(self):
        st = self.get("/api/auto-merge").json()
        self.assertTrue(st["projects"])
        self.assertFalse(st["stopped"])
        for key, row in st["projects"].items():
            self.assertIn(key, registry.PROJECTS)
            self.assertEqual(row["available"], row["why"] is None)
            self.assertEqual(row["source"], "config")

    def test_only_jay_switches_and_on_needs_developer_unlock(self):
        on_key = next((k for k, r in self.get("/api/auto-merge").json()["projects"].items() if r["available"]), None)
        if on_key is None:
            self.skipTest("no project in this test config can auto-merge")
        self.assertEqual(self.put(on_key, True).status_code, 403)                                    # locked
        self.assertEqual(self.put(on_key, True, {**JSON, "x-ccd-actor": "agent:coordinator"}).status_code, 403)
        self.assertEqual(self.put(on_key, False, {**JSON, "x-ccd-actor": "agent:coordinator"}).status_code, 403)
        dev = self.dev()
        self.assertEqual(self.put("nope", True, dev).status_code, 404)
        self.assertEqual(self.put(on_key, "yes", dev).status_code, 400)
        r = self.put(on_key, True, dev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["projects"][on_key]["on"], r.json()["projects"][on_key]["source"]), (True, "settings"))
        r = self.put(on_key, False)                                                                   # off: no unlock
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["projects"][on_key]["on"])
        data = [e["data"] for e in self.get("/api/activity?limit=50").json()["events"] if e["kind"] == "merge.switch"]
        self.assertEqual([d["status"] for d in data][:2], ["off", "on"])

    def test_a_project_that_cannot_auto_merge_is_refused(self):
        rows = self.get("/api/auto-merge").json()["projects"]
        no = next((k for k, r in rows.items() if not r["available"]), None)
        if no is None:
            self.skipTest("every project in this test config can auto-merge")
        r = self.put(no, True, self.dev())
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("cannot auto-merge", r.json()["error"])
