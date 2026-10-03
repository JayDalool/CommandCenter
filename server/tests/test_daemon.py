"""The daemon against a fake herdr speaking the real protocol.

Each test pins one claim the live canary also has to prove.
"""
import asyncio
import unittest

from ccd.daemon import Daemon
from ccd.herdr import Herdr, HerdrError, parse_event, subscriptions_for
from ccd.store import Store

from .fake_herdr import FakeHerdr
from .helpers import FakeGitHub, cfg, fake_git, fake_host, new_db, wait_for


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeHerdr()
        await self.fake.start()
        self.gh = FakeGitHub()
        self.db = new_db()
        self.daemon = self.make()

    def make(self, **over):
        self.store = Store(self.db)
        return Daemon(cfg(**over), self.store, Herdr(self.fake.path, timeout=2.0), github_fn=self.gh,
                      host_fn=fake_host, git_fn=fake_git, oom_fn=lambda: 0)

    async def asyncTearDown(self):
        await self.daemon.stop()
        self.store.close()
        await self.fake.stop()

    async def ready(self):
        self.daemon.start()
        await wait_for(lambda: self.daemon.snap is not None and self.daemon.herdr_state["connected"]
                       and self.fake.subscriptions, what="daemon ready")
        await wait_for(lambda: self.daemon.git["asOf"] is not None, what="git poll")
        await self.settle()

    async def settle(self):
        self.daemon._dirty.set()
        before = self.daemon.snap
        await wait_for(lambda: self.daemon.snap is not before, what="rederive")

    def kinds(self, since=0):
        return [e["kind"] for e in self.store.since(since)]

    def agents(self):
        return {a["id"]: a for a in self.daemon.state()["agents"]}


class Bootstrap(Base):
    async def test_state_comes_from_session_snapshot(self):
        await self.ready()
        self.assertIn(("session.snapshot", {}), self.fake.calls)
        ags = self.agents()
        self.assertEqual(set(ags), {"wE:p2", "wE:p4"})

    async def test_samvision_and_gauzemate_detected_with_projects_and_roles(self):
        await self.ready()
        ags = self.agents()
        self.assertEqual((ags["wE:p2"]["agent_name"], ags["wE:p2"]["project"], ags["wE:p2"]["role"]),
                         ("samvision", "samvision", "coordinator"))
        self.assertEqual((ags["wE:p4"]["agent_name"], ags["wE:p4"]["project"], ags["wE:p4"]["role"]),
                         ("gauzemate", "gauzemate", "coordinator"))
        coord = self.daemon.state()["coordinators"]
        self.assertTrue(coord["samvision"]["canonical"])
        self.assertTrue(coord["gauzemate"]["canonical"])
        self.assertEqual(coord["gyst"]["status"], "offline")

    async def test_subscribes_to_status_changes_of_every_live_agent(self):
        await self.ready()
        self.assertEqual(self.fake.watched_panes(), {"wE:p2", "wE:p4"})

    async def test_no_terminal_titles_leave_the_daemon(self):
        await self.ready()
        import json
        blob = json.dumps(self.daemon.state())
        self.assertNotIn("What still needs my answer", blob)
        self.assertNotIn("terminal_title", blob)


class Events(Base):
    async def test_status_change_event_is_published(self):
        await self.ready()
        q = self.daemon.subscribe()
        await self.fake.push_status("wE:p2", "working")
        ev = await asyncio.wait_for(q.get(), 3)
        while ev["kind"] != "agent.state_changed":
            ev = await asyncio.wait_for(q.get(), 3)
        self.assertEqual((ev["agentId"], ev["data"]["from"], ev["data"]["to"]), ("wE:p2", "idle", "working"))
        await wait_for(lambda: self.agents()["wE:p2"]["status"] == "working", what="state follows the event")
        self.assertGreaterEqual(self.daemon.state()["seq"], ev["seq"],
                                "a state that shows the change covers the event that announced it")

    async def test_state_seq_never_skips_an_unreflected_event(self):
        await self.ready()
        await self.fake.push_status("wE:p4", "working")
        await wait_for(lambda: "agent.state_changed" in self.kinds(), what="event logged")
        st = self.daemon.state()
        # Either the state already shows the change, or the event is after st["seq"] and will replay.
        ev = next(e for e in self.store.since(0) if e["kind"] == "agent.state_changed")
        reflected = {a["id"]: a["status"] for a in st["agents"]}["wE:p4"] == "working"
        self.assertTrue(reflected or ev["seq"] > st["seq"])

    async def test_blocked_event_never_carries_the_question(self):
        await self.ready()
        self.fake.tails["wE:p4"] = "Do you want to read /srv/private/1234 Main St listing.csv?"
        await self.fake.push_status("wE:p4", "blocked")
        await wait_for(lambda: "agent.blocked" in self.kinds(), what="blocked event")
        await self.settle()
        ev = next(e for e in self.store.since(0) if e["kind"] == "agent.blocked")
        self.assertNotIn("Main St", ev["text"] + str(ev["data"]))
        self.assertIn("blocked:wE:p4", {a["id"] for a in self.daemon.state()["alerts"]})

    async def test_new_agent_is_found_and_subscription_reopened(self):
        await self.ready()
        self.fake.add_agent("wE:p9", "/srv/server/worktrees/samvisionai/SV-056", name="sv-056")
        await self.fake.push("pane_agent_detected", {"pane_id": "wE:p9", "workspace_id": "wE"})
        await wait_for(lambda: "wE:p9" in self.fake.watched_panes(), what="resubscribe with the new pane")
        await self.settle()
        lane = self.agents()["wE:p9"]
        self.assertEqual((lane["project"], lane["role"]), ("samvision", "lane"))
        self.assertIn("agent.started", self.kinds())

    async def test_status_events_apply_immediately_not_at_reconcile(self):
        """Live bug: dotted event names were ignored, so changes waited for the 30 s reconcile."""
        self.daemon = self.make(reconcile_seconds=60)
        await self.ready()
        q = self.daemon.subscribe()
        t0 = asyncio.get_running_loop().time()
        await self.fake.push_status("wE:p2", "working")
        while True:
            ev = await asyncio.wait_for(q.get(), 3)
            if ev["kind"] == "agent.state_changed":
                break
        self.assertLess(asyncio.get_running_loop().time() - t0, 2.0, "pushed, not waited for")

    async def test_reconcile_catches_a_change_that_sent_no_event(self):
        await self.ready()
        self.fake.set_status("wE:p4", "done")  # no event pushed
        await wait_for(lambda: self.agents()["wE:p4"]["status"] == "done", timeout=3, what="reconcile")


class Reconnect(Base):
    async def test_dropped_subscription_reconnects_and_resyncs(self):
        await self.ready()
        reconnects = self.daemon.herdr_state["reconnects"]
        await self.fake.drop_subscriptions()
        self.fake.set_status("wE:p2", "working")  # changed while ccd was not listening
        await wait_for(lambda: self.daemon.herdr_state["reconnects"] > reconnects, what="reconnect")
        await wait_for(lambda: self.fake.subscriptions, what="resubscribed")
        await self.settle()
        self.assertEqual(self.agents()["wE:p2"]["status"], "working")
        changed = [e for e in self.store.since(0) if e["kind"] == "agent.state_changed"]
        self.assertTrue(any(e["agentId"] == "wE:p2" and e["data"]["to"] == "working" for e in changed))

    async def test_herdr_gone_degrades_cleanly_and_recovers(self):
        await self.ready()
        await self.fake.stop()
        await wait_for(lambda: not self.daemon.herdr_state["ok"], what="herdr marked down")
        await self.settle()
        st = self.daemon.state()
        self.assertTrue(st["herdr_error"].startswith("herdr unreachable"))
        self.assertEqual({a["status"] for a in st["agents"]}, {"unknown"}, "last known agents, state unknown")
        self.assertEqual(len(st["projects"][3]["prs"]), 3, "GitHub data keeps flowing")
        self.assertIn("daemon:herdr", {a["id"] for a in st["alerts"]})
        self.assertIn("daemon.herdr_lost", self.kinds())
        await self.fake.start()
        await wait_for(lambda: self.daemon.herdr_state["ok"], timeout=8, what="herdr back")
        await self.settle()
        self.assertEqual(self.agents()["wE:p2"]["status"], "idle")
        self.assertNotIn("daemon:herdr", {a["id"] for a in self.daemon.state()["alerts"]})

    async def test_protocol_mismatch_falls_back_to_snapshot_polling(self):
        self.fake.protocol = 23
        self.daemon.start()
        await wait_for(lambda: self.daemon.snap is not None and self.daemon.herdr_state["ok"], what="ready")
        self.assertIn("snapshot polling only", self.daemon.herdr_state["warning"])
        self.assertEqual(self.fake.subscriptions, [], "events are not trusted across protocol versions")


class GitHub(Base):
    async def test_failure_keeps_last_good_data(self):
        await self.ready()
        self.assertEqual(len(self.daemon.state()["projects"][3]["prs"]), 3)
        self.gh.fail = True
        await self.daemon.poll_github_once()
        await self.settle()
        st = self.daemon.state()
        self.assertEqual([p["number"] for p in st["projects"][3]["prs"]], [23, 25, 26])
        self.assertIn("could not resolve host", st["sources"]["github"]["gauzemate"]["error"])
        self.assertIsNotNone(st["sources"]["github"]["gauzemate"]["asOf"])
        self.assertNotIn("pr.closed", self.kinds(), "a failed poll must not read as PRs closing")
        self.assertIn("daemon.github_failed", self.kinds())

    async def test_changes_become_events(self):
        await self.ready()
        from .helpers import pr
        self.gh.data["gauzemate"]["prs"] = [pr(23, ci="FAILURE"), pr(25), pr(27)]
        await self.daemon.poll_github_once()
        await self.settle()
        k = self.kinds()
        self.assertIn("pr.opened", k)
        self.assertIn("pr.closed", k)
        self.assertIn("pr.ci_changed", k)

    async def test_github_arriving_after_the_first_derive_is_not_news(self):
        """Live bug found on first start: every open PR and task was announced as new."""
        import threading
        gate = threading.Event()
        real = self.gh

        def slow(project):
            gate.wait(5)
            return real(project)

        self.daemon.github_fn = slow
        self.daemon.start()
        await wait_for(lambda: self.daemon.snap is not None and self.daemon.herdr_state["connected"],
                       what="first derive, before GitHub")
        self.assertIsNone(self.daemon.gh["gauzemate"]["data"])
        gate.set()
        await wait_for(lambda: self.daemon.gh["gauzemate"]["data"] is not None, what="GitHub answered")
        await self.settle()
        noise = [e["kind"] for e in self.store.since(0)
                 if e["kind"] in ("pr.opened", "jay.action_required", "ci.main_changed", "task.stage_changed")]
        self.assertEqual(noise, [])
        from .helpers import pr
        self.gh.data["gauzemate"]["prs"].append(pr(30))      # and a real change still gets through
        await self.daemon.poll_github_once()
        await self.settle()
        self.assertIn("pr.opened", self.kinds())

    async def test_one_call_per_repo_per_poll(self):
        await self.ready()
        n = self.gh.calls
        await self.daemon.poll_github_once()
        self.assertEqual(self.gh.calls - n, 4)


class Restart(Base):
    async def test_restart_reconstructs_state_and_continues_seq(self):
        await self.ready()
        seq_before = self.daemon.seq
        agents_before = self.agents()
        await self.daemon.stop()
        self.store.close()
        self.fake.set_status("wE:p4", "working")  # happened while ccd was down
        self.daemon = self.make()
        self.gh.fail = True                       # and GitHub is down at start
        await self.ready()
        self.assertGreater(self.daemon.seq, seq_before, "seq continues from the log")
        self.assertEqual(set(self.agents()), set(agents_before))
        self.assertEqual(self.agents()["wE:p4"]["status"], "working")
        ev = [e for e in self.store.since(seq_before) if e["kind"] == "agent.state_changed"]
        self.assertTrue(any(e["agentId"] == "wE:p4" for e in ev), "downtime change is reported")
        self.assertEqual(len(self.daemon.state()["projects"][3]["prs"]), 3, "last-good GitHub data from SQLite")

    async def test_stopping_ccd_sends_nothing_to_herdr(self):
        await self.ready()
        n = len(self.fake.calls)
        await self.daemon.stop()
        mutating = [m for m, _ in self.fake.calls[n:] if m not in ("ping", "session.snapshot", "agent.read")]
        self.assertEqual(mutating, [])


class Protocol(unittest.IsolatedAsyncioTestCase):
    async def test_methods_outside_the_allowlist_never_reach_the_socket(self):
        fake = FakeHerdr()
        await fake.start()
        h = Herdr(fake.path)
        for method in ("pane.close", "pane.split", "agent.start", "worktree.remove", "server.stop", "pane.run"):
            with self.assertRaises(HerdrError):
                await h.call(method, {})
        self.assertEqual(fake.calls, [])
        await fake.stop()

    async def test_herdr_errors_surface_with_their_code(self):
        fake = FakeHerdr()
        await fake.start()
        with self.assertRaises(HerdrError) as cm:
            await Herdr(fake.path).read_tail("wE:nope", 5)
        self.assertEqual(cm.exception.code, "agent_not_found")
        await fake.stop()

    def test_event_parsing(self):
        self.assertEqual(parse_event(b'{"event":"pane_focused","data":{"pane_id":"wE:p1"}}'),
                         ("pane_focused", {"pane_id": "wE:p1"}))
        # Captured from the live herdr: subscription events use dots.
        live = b'{"data":{"agent":"claude","agent_status":"idle","pane_id":"wE:p2","workspace_id":"wE"},' \
               b'"event":"pane.agent_status_changed"}'
        self.assertEqual(parse_event(live)[0], "pane_agent_status_changed")
        self.assertIsNone(parse_event(b'{"id":"x","result":{}}'))
        self.assertIsNone(parse_event(b"not json"))

    def test_subscription_list_names_each_agent(self):
        subs = subscriptions_for({"wE:p4", "wE:p2"})
        self.assertIn({"type": "pane.agent_status_changed", "pane_id": "wE:p2"}, subs)
        self.assertIn({"type": "pane.created"}, subs)


if __name__ == "__main__":
    unittest.main()
