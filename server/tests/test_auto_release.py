"""Automatic release, slice 1: the dry run (CC-081, ccd/autorelease.py). It records what a release window would ship
and what happened; it never deploys, restarts, approves, rolls back or changes a gate. Synthetic tickets, shas and
logs only; git is a fake unless a test says otherwise, and nothing here opens a socket."""
import ast
import asyncio
import datetime
import json
import os
import subprocess
import tempfile
import types
import unittest
import zoneinfo
from pathlib import Path
from unittest import mock

from ccd import autorelease, config, flow, notify
from ccd.autorelease import ALLOWED, HELD, AutoRelease, eligibility
from ccd.pipeline import Pipeline
from ccd.release import Release
from ccd.store import Store
from ccd.tasks import TaskStore

WPG = zoneinfo.ZoneInfo("America/Winnipeg")
PROJECTS = [{"key": k, "name": k, "prefix": p} for k, p in
            (("gyst", "GYST"), ("commandcenter", "CC"), ("samvision", "SV"), ("mfe", "MFE"))]


def at(d, hh=0, mm=0):
    return datetime.datetime(2026, 11, d, hh, mm, tzinfo=WPG).timestamp()


W = at(18, 22)          # Wed 2026-11-18 22:00, the default window
DUE = at(17, 22)        # the digest went out 24 h before
MERGED = at(18, 9)      # before the noon cutoff: this window's
LIVE, PIN = "aaaaaaa", "bbbbbbb"
GOOD_CAPS = {"health_checks": True, "auto_rollback": True}
TITLE = "Synthetic title words that must never be stored"
SUBJECT = "secret subject words"


class FakePolicy:
    def __init__(self):
        self.caps = {k: dict(GOOD_CAPS) for k in ("gyst", "commandcenter", "samvision", "mfe")}

    def profile(self, key):
        return {"capabilities": self.caps[key]}


class FakeGit:
    """git rev-parse answers PIN; git log answers `self.log` lines (sha, subject)."""

    def __init__(self):
        self.calls = []
        self.log = []
        self.fail = set()

    def __call__(self, root, args):
        self.calls.append(list(args))
        if args[0] in self.fail:
            return 1, ""
        if args[0] == "rev-parse":
            return 0, PIN + "\n"
        return 0, "".join(f"{sha}\x1f{subject}\n" for sha, subject in self.log)


def run(coro):
    return asyncio.run(coro)


class Base(unittest.TestCase):
    MODE = "dry_run"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccd-autorel-")
        self.store = Store(os.path.join(self.tmp, "ccd.db"))
        self.addCleanup(self.store.close)
        self.ts = TaskStore(":memory:", PROJECTS)
        self.pipe = Pipeline(self.ts)
        self.rel = Release(os.path.join(self.tmp, "release.json"))
        self.pipe.releases = self.rel
        for p in ("gyst", "commandcenter", "samvision"):
            self.rel.set_live(p, True)
        self.policy = FakePolicy()
        self.git = FakeGit()
        self.deploys = Path(self.tmp) / "deploys"
        self.web = Path(self.tmp) / "web"
        (self.web / "releases").mkdir(parents=True)
        self.set_live_rev(f"20261111T010203Z-{LIVE}")
        self.stop = Path(self.tmp) / "auto-release.stop"
        self.pulled = set()
        self.ar = self.make()

    def make(self, mode=None):
        return AutoRelease(self.store, self.pipe, self.rel, self.policy, mode=mode or self.MODE,
                           projects=lambda: [p["key"] for p in PROJECTS], stop_file=self.stop,
                           deploys_dir=self.deploys, web_current=self.web / "current", git=self.git,
                           pulls=lambda project, window: set(self.pulled))

    def set_live_rev(self, name):
        cur = self.web / "current"
        if cur.is_symlink():
            cur.unlink()
        os.symlink(f"releases/{name}", cur)

    def log_line(self, project, name, row):
        d = self.deploys / project
        d.mkdir(parents=True, exist_ok=True)
        with open(d / name, "a") as f:
            f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")

    def rehearse(self, project="commandcenter", result="pass"):
        self.log_line(project, "rehearsals.jsonl", {"at": "2026-11-10T00:00:00Z", "result": result})

    def ticket(self, project="commandcenter", status="VERIFYING", deploy=True, verified=True, urgent=False,
               merged=MERGED):
        t, _ = self.ts.create(project, TITLE)
        d = {"env": "live", "requestedAt": merged, "approvedAt": None, "result": None} if deploy else None
        if d and urgent:
            d["urgent"] = True
        self.ts.db.execute("UPDATE tickets SET status=? WHERE key=?", (status, t["key"]))
        self.ts.db.execute("INSERT INTO ticket_work(ticket_id, merge, deploy, verification, updated_at) "
                           "VALUES (?,?,?,?,0)",
                           (t["id"], json.dumps({"at": merged}), json.dumps(d) if d else None,
                            json.dumps({"result": "pass"}) if verified else None))
        return t["key"]

    def set_deploy(self, key, **kw):
        tid = self.ts._id_of(key)
        d = json.loads(self.ts.db.execute("SELECT deploy FROM ticket_work WHERE ticket_id=?", (tid,)).fetchone()[0])
        d.update(kw)
        self.ts.db.execute("UPDATE ticket_work SET deploy=? WHERE ticket_id=?", (json.dumps(d), tid))

    def digest(self, keys, project="commandcenter", window=W, state="delivered", uncertain=False):
        self.store.put(f"release_mail:{project}", [{"window": window, "due": window - 86400, "state": state,
                                                    "uncertain": uncertain, "attempts": 1, "at": window - 86400,
                                                    "listed": {"scheduled": list(keys), "verified": [], "held": []}}])

    def ready(self, project="commandcenter", n=1):
        """n tickets that would release, their digest delivered, a rehearsal, and a range of their merges."""
        keys = [self.ticket(project) for _ in range(n)]
        self.digest(keys, project)
        self.rehearse(project)
        self.git.log = [(f"{i + 1:07x}", f"Merge pull request #{i} from JayDalool/{k}-work") for i, k in enumerate(keys)]
        return keys

    def tick(self, when, ar=None):
        run((ar or self.ar).tick(when))

    def through(self, keys=None):
        """The digest (pin) tick and the window tick."""
        self.tick(DUE + 60)
        self.tick(W + 60)

    def led(self, project="commandcenter"):
        return self.store.get(f"auto_release:{project}", None)[0]

    def rows(self, project="commandcenter", phase=None):
        led = self.led(project) or {"rows": []}
        return [r for r in led["rows"] if phase is None or r["phase"] == phase]

    def decision(self, project="commandcenter"):
        rows = self.rows(project, "decision")
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def events(self, key=None):
        q = "SELECT t.key, e.actor, e.kind, e.trigger, e.data FROM ticket_events e JOIN tickets t ON t.id=e.ticket_id " \
            "WHERE e.kind='release.dry_run'"
        return [r for r in self.ts.db.execute(q + " ORDER BY e.id") if key is None or r[0] == key]


class Flag(Base):
    def test_default_is_off(self):
        self.assertEqual(config.DEFAULTS["auto_release"], "off")
        self.assertEqual(autorelease.mode_of(config.DEFAULTS), "off")

    def test_only_the_exact_string_dry_run_turns_it_on(self):
        for v in ("off", "on", True, 1, "DRY_RUN", " dry_run", "dry_run ", "junk", None, ["dry_run"], {"x": 1}):
            with self.subTest(v=v), self.assertLogs("ccd", "WARNING") if v != "off" else _nolog():
                self.assertEqual(autorelease.mode_of({"auto_release": v}), "off")
        self.assertEqual(autorelease.mode_of({}), "off")
        self.assertEqual(autorelease.mode_of({"auto_release": "dry_run"}), "dry_run")

    def test_off_on_and_junk_write_no_row_and_no_event(self):
        keys = self.ready()
        for v in (None, "off", "on", True, "DRY_RUN", "junk"):
            with self.subTest(v=v):
                with self.assertLogs("ccd", "WARNING") if v not in (None, "off") else _nolog():
                    mode = autorelease.mode_of({} if v is None else {"auto_release": v})
                ar = self.make(mode)
                self.tick(DUE + 60, ar)
                self.tick(W + 60, ar)
                self.tick(W + 3 * 3600, ar)
                self.assertIsNone(self.led())
                self.assertEqual(self.events(), [])
        self.through()
        self.assertEqual(self.decision()["items"][0]["key"], keys[0])

    def test_a_stop_file_writes_nothing(self):
        self.ready()
        self.stop.write_text("")
        self.through()
        self.tick(W + 3 * 3600)
        self.assertEqual((self.led(), self.events()), (None, []))
        self.assertTrue(self.ar.public(["commandcenter"])["stopped"])

    def test_a_stop_file_that_cannot_be_checked_counts_as_present(self):
        self.ready()
        with mock.patch.object(Path, "exists", side_effect=OSError("EACCES")):
            self.through()
        self.assertEqual((self.led(), self.events()), (None, []))


class _nolog:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AllowList(Base):
    def test_the_allow_list_is_exactly_gyst_and_commandcenter(self):
        self.assertEqual(ALLOWED, ("gyst", "commandcenter"))

    def test_other_projects_are_never_eligible_whatever_the_facts(self):
        good = {"capabilities": GOOD_CAPS, "rehearsal": "pass", "held": False, "range": None}
        f = {"K-1": {"status": "VERIFYING", "env": "live", "requested": True, "result": None, "urgent": False,
                     "verified": True, "heldUntil": None}}
        for p in ("samvision", "mfe", "gauzemate"):
            r = eligibility(p, ["K-1"], f, good)
            self.assertEqual((r["eligible"], r["blockers"]), (False, ["not on the automatic release list"]))
        for p in ALLOWED:
            self.assertTrue(eligibility(p, ["K-1"], f, good)["eligible"])

    def test_samvision_live_with_a_digest_gets_no_row(self):
        key = self.ticket("samvision")
        self.digest([key], "samvision")
        self.through()
        self.assertIsNone(self.led("samvision"))
        self.assertEqual(self.events(), [])

    def test_a_project_that_is_not_live_gets_no_row(self):
        self.ready("gyst")
        self.rel.set_live("gyst", False)
        self.through()
        self.assertIsNone(self.led("gyst"))


class Manifest(Base):
    def test_no_digest_a_failed_or_an_uncertain_one_means_no_manifest_emailed(self):
        key = self.ticket()
        self.rehearse()
        for name, setup in (("none", lambda: None),
                            ("failed", lambda: self.digest([key], state="failed")),
                            ("uncertain", lambda: self.digest([key], state="failed", uncertain=True))):
            with self.subTest(name):
                self.store.put("auto_release:commandcenter", {"rows": []})
                self.store.put("release_mail:commandcenter", [])
                setup()
                self.through()
                d = self.decision()
                self.assertIn("no manifest emailed", d["blockers"])
                self.assertEqual((d["eligible"], d["items"]), (False, []))
        self.assertEqual(self.events(), [])

    def test_only_digest_items_are_judged_and_an_unlisted_or_keyless_change_blocks(self):
        listed = self.ready()[0]
        other = self.ticket()       # merged and waiting, but not on the emailed manifest
        self.git.log += [("ccccccc", f"Merge pull request #9 from JayDalool/{other}-late"),
                         ("ddddddd", "Merge pull request #10 from JayDalool/claude/no-ticket")]
        self.through()
        d = self.decision()
        self.assertEqual([i["key"] for i in d["items"]], [listed])
        self.assertIn(f"unlisted change ccccccc/{other}", d["blockers"])
        self.assertIn("unlisted change ddddddd/no key", d["blockers"])
        self.assertFalse(d["eligible"])
        self.assertEqual(self.events(other), [])

    def test_a_pulled_item_is_held(self):
        keys = self.ready(n=2)
        self.pulled = {keys[1]}
        self.git.log = self.git.log[:1]
        self.through()
        d = self.decision()
        self.assertEqual([(i["key"], i["would"], i["reasons"]) for i in d["items"]],
                         [(keys[0], "release", []), (keys[1], "hold", ["pulled from the release"])])

    def test_a_pulled_item_still_in_the_range_blocks(self):
        keys = self.ready(n=2)
        self.pulled = {keys[1]}
        self.through()
        self.assertIn(f"unlisted change 0000002/{keys[1]}", self.decision()["blockers"])

    def test_the_range_is_live_to_the_sha_pinned_when_the_digest_went_out(self):
        self.ready()
        self.through()
        d = self.decision()
        self.assertEqual((d["live"], d["target"], d["eligible"]), (LIVE, PIN, True), d)
        self.assertIn(["log", "--first-parent", "--format=%h%x1f%s", f"{LIVE}..{PIN}"], self.git.calls)
        pin = self.rows(phase="pin")
        self.assertEqual([(r["window"], r["at"]) for r in pin], [(W, DUE + 60)])

    def test_no_pin_before_the_window_is_a_blocker(self):
        self.ready()
        self.tick(W + 60)           # ccd was down from the digest until the window
        self.assertIn("no sha pinned at digest time", self.decision()["blockers"])


class Readiness(Base):
    def test_capabilities_and_rehearsal_are_each_a_blocker(self):
        self.ready()
        self.policy.caps["commandcenter"] = {"health_checks": False, "auto_rollback": False}
        (self.deploys / "commandcenter" / "rehearsals.jsonl").unlink()
        self.through()
        d = self.decision()
        self.assertEqual(d["blockers"], ["health checks not configured", "rollback not configured",
                                         "no rehearsal recorded"])
        self.assertEqual(d["items"][0]["would"], "hold")

    def test_a_failed_rehearsal_blocks(self):
        self.ready()
        self.rehearse(result="fail")
        self.through()
        self.assertEqual(self.decision()["blockers"], ["last rehearsal failed"])

    def test_a_forged_rehearsal_pass_with_capabilities_false_is_not_eligible(self):
        self.ready()
        self.policy.caps["commandcenter"] = {"health_checks": False, "auto_rollback": True}
        self.through()
        d = self.decision()
        self.assertEqual((d["eligible"], d["blockers"]), (False, ["health checks not configured"]))

    def test_all_present_is_eligible(self):
        key = self.ready()[0]
        self.through()
        d = self.decision()
        self.assertEqual((d["eligible"], d["blockers"], d["items"]),
                         (True, [], [{"key": key, "would": "release", "reasons": []}]))
        ev = self.events(key)
        self.assertEqual([(e[1], e[2]) for e in ev], [("system:auto-release", "release.dry_run")])
        self.assertTrue(ev[0][3].startswith("would release in Wed 2026-11-18 22:00 "), ev[0][3])


class SeparateFromMerge(Base):
    def test_autorelease_does_not_import_merge_policy_or_anything_that_acts(self):
        src = Path(autorelease.__file__).read_text()
        names = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[-1] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names |= {a.name for a in node.names} | {(node.module or "").split(".")[-1]}
        for bad in ("merge_policy", "broker", "herdr", "chat", "leadchat", "notify", "urllib", "http", "socket",
                    "smtplib", "releasemail"):
            self.assertNotIn(bad, names)
        for word in ("go-live", "systemctl", "deploy-web"):
            self.assertNotIn(word, src)

    def test_a_merge_ready_ticket_without_verification_is_held(self):
        self.ready()
        key = self.ticket(verified=False)
        self.digest([key])
        self.git.log = [("1234567", f"Merge pull request #3 from JayDalool/{key}-x")]
        self.through()
        d = self.decision()
        self.assertEqual(d["items"], [{"key": key, "would": "hold", "reasons": ["verification has not passed"]}])

    def test_an_eligible_item_needs_no_merge_readiness_facts(self):
        key = self.ready()[0]
        facts = self.pipe.release_facts("commandcenter", [key], W + 60)["items"][key]
        self.assertFalse({"review", "ci", "gate", "merge", "mergeable"} & set(facts))
        self.assertEqual(autorelease.item_reasons(facts, False), [])


class Outcome(Base):
    def test_after_the_window_one_outcome_row_and_one_event_per_item(self):
        a, b, c = self.ready(n=3)
        self.through()
        self.set_deploy(a, result="pass", deployedAt=W + 600, deployedBy="jay")
        self.set_deploy(b, result="fail", deployedAt=W + 900, deployedBy="agent:coordinator")
        self.tick(W + 2 * 3600 - 1)
        self.assertEqual(self.rows(phase="outcome"), [])
        self.tick(W + 2 * 3600)
        self.tick(W + 3 * 3600)
        out = self.rows(phase="outcome")
        self.assertEqual(len(out), 1)
        self.assertEqual([(i["key"], i["result"], i["by"]) for i in out[0]["items"]],
                         [(a, "pass", "jay"), (b, "fail", "agent:coordinator"), (c, "none", None)])
        texts = {k: [e[3] for e in self.events(k)] for k in (a, b, c)}
        self.assertEqual(texts[a][1:], ["released by jay: pass"])
        self.assertEqual(texts[b][1:], ["released by agent:coordinator: fail"])
        self.assertEqual(texts[c][1:], ["not released"])


class Hold(Base):
    def test_a_failed_or_inconclusive_release_since_the_last_pass_holds_the_project(self):
        for result in ("failed", "inconclusive"):
            with self.subTest(result):
                self.setUp()
                self.ready()
                self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-10T00:00:00Z", "result": "healthy"})
                self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-11T00:00:00Z", "result": result})
                self.through()
                self.assertIn(HELD, self.decision()["blockers"])

    def test_a_ticket_deployed_fail_holds_the_project(self):
        self.ready()
        old = self.ticket()
        self.set_deploy(old, result="fail", deployedAt=at(11, 23), deployedBy="jay")
        self.through()
        self.assertIn(HELD, self.decision()["blockers"])

    def test_a_pass_after_the_failure_before_it_was_seen_is_not_held(self):
        self.ready()
        self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-10T00:00:00Z", "result": "failed"})
        self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-11T00:00:00Z", "result": "healthy"})
        self.through()
        self.assertNotIn(HELD, self.decision()["blockers"])

    def test_the_hold_is_sticky_until_jay_clears_it(self):
        self.ready()
        self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-11T00:00:00Z", "result": "failed"})
        self.tick(DUE + 60)
        self.assertTrue(self.led()["hold"])
        (self.deploys / "commandcenter" / "releases.jsonl").unlink()     # deleting the log clears nothing
        self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-12T00:00:00Z", "result": "healthy"})
        self.tick(W + 60)
        self.assertIn(HELD, self.decision()["blockers"])
        self.assertIsNotNone(self.ar.public(["commandcenter"])["projects"]["commandcenter"]["held"])
        autorelease.clear_hold(self.store, "commandcenter", now=W + 3 * 3600)
        self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-11T00:00:00Z", "result": "failed"})
        self.tick(W + 3 * 3600 + 60)
        self.assertIsNone(self.led()["hold"])        # a failure Jay already cleared does not hold again

    def test_an_absent_release_log_is_no_health_check_never_healthy(self):
        self.assertEqual(autorelease.release_log("commandcenter", self.deploys), (None, None))
        self.log_line("commandcenter", "releases.jsonl", "not json")
        good, bad = autorelease.release_log("commandcenter", self.deploys)
        self.assertIsNone(good)
        self.assertIsNotNone(bad)

    def test_clear_hold_cli_refuses_other_projects(self):
        with self.assertRaises(ValueError):
            autorelease.clear_hold(self.store, "samvision")


class Dedup(Base):
    def test_a_restart_mid_window_writes_no_second_decision(self):
        key = self.ready()[0]
        self.through()
        self.ar = self.make()       # a restart: a new AutoRelease on the same ccd.db
        self.tick(W + 120)
        self.tick(W + 600)
        self.decision()
        self.assertEqual(len(self.events(key)), 1)

    def test_a_window_moved_within_the_release_writes_nothing_more(self):
        self.ready()
        self.through()
        self.rel.set_window(3, "23:00")
        self.tick(W + 3600 + 60)
        self.decision()

    def test_a_window_moved_to_another_day_gets_its_own_decision(self):
        self.ready()
        self.through()
        self.rel.set_window(4, "22:00")          # Thursday
        self.tick(at(19, 22, 1))
        self.assertEqual([r["window"] for r in self.rows(phase="decision")], [at(19, 22), W])

    def test_a_failed_digest_gives_one_no_manifest_row_and_no_retry_duplicate(self):
        key = self.ticket()
        self.digest([key], state="failed")
        self.through()
        self.tick(W + 120)
        self.digest([key], state="failed")
        self.tick(W + 180)
        d = self.decision()
        self.assertIn("no manifest emailed", d["blockers"])


class Safety(Base):
    def test_a_full_eligible_step_calls_nothing_that_acts(self):
        keys = self.ready(n=2)
        self.ar.git = autorelease.run_git            # the real runner, over a patched subprocess
        calls = []
        log = "".join(f"{i + 1:07x}\x1f{s}\n" for i, (_sha, s) in enumerate(self.git.log))

        def fake_run(argv, **kw):
            calls.append((argv, kw))
            self.assertNotIn("shell", kw)
            out = PIN + "\n" if "rev-parse" in argv else log
            return subprocess.CompletedProcess(argv, 0, out, "")

        def boom(*a, **k):
            raise AssertionError("the dry run must not act")
        acting = [mock.patch.object(Pipeline, n, boom) for n in
                  ("_tx", "confirm", "deploy_request", "deployed", "deploy_go", "deploy_plan", "auto_merged", "verify")
                  if hasattr(Pipeline, n)]
        acting.append(mock.patch.object(TaskStore, "_apply", boom))
        acting.append(mock.patch.object(TaskStore, "_touch", boom))
        for p in acting:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(autorelease.subprocess, "run", fake_run):
            self.through()
            self.tick(W + 3 * 3600)
        self.assertTrue(self.decision()["eligible"])
        self.assertEqual(len(self.rows(phase="outcome")), 1)
        self.assertEqual(len(self.events()), 4)
        for argv, kw in calls:
            self.assertEqual(argv[0], "git")
            self.assertIsInstance(argv, list)
            self.assertNotIn("fetch", argv)
            self.assertIn(argv[3], ("rev-parse", "log"))
            self.assertEqual(kw.get("timeout"), autorelease.GIT_TIMEOUT)
        self.assertTrue(all(self.ts.get(k)["status"] == "VERIFYING" for k in keys))

    def test_a_bad_live_name_never_reaches_git(self):
        self.ready()
        for name in (f"20261111T010203Z-{LIVE}-dirty", "20261111T010203Z-xyz1234", "20261111T010203Z--rf",
                     "20261111T010203Z-", "no-stamp-here"):
            with self.subTest(name):
                self.store.put("auto_release:commandcenter", {"rows": []})
                self.git.calls.clear()
                self.set_live_rev(name)
                self.through()
                self.assertIn("cannot tell live", self.decision()["blockers"])
                self.assertFalse([c for c in self.git.calls if c[0] == "log"])

    def test_a_git_failure_is_cannot_read_range(self):
        self.ready()
        self.git.fail = {"log"}
        self.through()
        self.assertIn("cannot read range", self.decision()["blockers"])

    def test_a_git_timeout_is_cannot_read_range(self):
        self.ready()
        self.tick(DUE + 60)
        with mock.patch.object(autorelease.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["git"], autorelease.GIT_TIMEOUT)):
            self.ar.git = autorelease.run_git
            self.tick(W + 60)
        self.assertIn("cannot read range", self.decision()["blockers"])

    def test_events_change_no_status_gate_or_idle_and_are_not_counted(self):
        keys = self.ready()

        def snap():
            return (self.ts.db.execute("SELECT key, status, updated_at FROM tickets ORDER BY id").fetchall(),
                    self.ts.db.execute("SELECT * FROM ticket_work ORDER BY ticket_id").fetchall(),
                    [flow.idle_since(self.pipe._events(self.ts._id_of(k))) for k in keys])
        before = snap()
        self.through()
        self.tick(W + 3 * 3600)
        self.assertEqual(len(self.events()), 2)
        self.assertEqual(snap(), before)
        self.assertTrue(all(not e[2].startswith("pipeline.") for e in self.events()))
        fake = types.SimpleNamespace(d=types.SimpleNamespace(tasks=self.ts))
        self.assertEqual(notify.Notifier._day_events(fake, 0), {})
        marks = self.pipe.compact([self.ts._id_of(k) for k in keys])
        self.assertFalse(any(m.get("idleSince") for m in marks.values()))     # no pipeline step was recorded

    def test_rows_and_events_hold_no_title_or_commit_subject(self):
        self.ready("commandcenter")
        self.git.log = [(sha, f"{s} {SUBJECT}") for sha, s in self.git.log]
        self.ready("gyst")
        self.through()
        self.tick(W + 3 * 3600)
        stored = json.dumps([self.led("commandcenter"), self.led("gyst")])
        stored += json.dumps([list(e) for e in self.events()])
        self.assertNotIn(TITLE, stored)
        self.assertNotIn(SUBJECT, stored)
        self.assertNotIn("Synthetic", stored)


class Api(Base):
    def daemon(self, **over):
        from ccd.daemon import Daemon
        from .helpers import cfg
        store = Store(os.path.join(self.tmp, "real.db"))
        self.addCleanup(store.close)
        return Daemon(cfg(meter={"enabled": False}, release_path=os.path.join(self.tmp, "release.json"),
                          work_mode_path=os.path.join(self.tmp, "wm.json"), **over), store, None, tasks=self.ts)

    def test_release_state_reads_only_the_ledger_and_shows_gyst_and_commandcenter(self):
        d = self.daemon(auto_release="dry_run")
        d.auto_release.store.put("auto_release:commandcenter", {"rows": [
            {"phase": "decision", "window": W, "at": W + 60, "eligible": False, "blockers": ["no manifest emailed"],
             "items": [], "live": None, "target": None}], "hold": None})

        def boom(*a, **k):
            raise AssertionError("GET /api/release must read the ledger only")
        with mock.patch.object(autorelease.subprocess, "run", boom), mock.patch("os.readlink", boom), \
                mock.patch("builtins.open", boom), mock.patch.object(Path, "exists", boom):
            r = d.release_state(now=W)
        a = r["autoRelease"]
        self.assertEqual((a["mode"], sorted(a["projects"])), ("dry_run", ["commandcenter", "gyst"]))
        self.assertEqual(a["projects"]["commandcenter"]["wouldRelease"]["blockers"], ["no manifest emailed"])
        self.assertIsNone(a["projects"]["gyst"]["wouldRelease"])

    def test_auto_release_is_off_in_a_daemon_by_default(self):
        d = self.daemon()
        self.assertEqual(d.release_state(now=W)["autoRelease"]["mode"], "off")


if __name__ == "__main__":
    unittest.main()
