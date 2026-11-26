"""Automatic release, slice 1: the dry run (CC-081, ccd/autorelease.py). It records what a release window would ship
and what happened; it never deploys, restarts, approves, rolls back or changes a gate. Synthetic tickets, shas and
logs only; git is a fake unless a test builds a throwaway repository, and nothing here opens a socket."""
import ast
import asyncio
import datetime
import http.client
import json
import os
import smtplib
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import types
import unittest
import urllib.request
import zoneinfo
from pathlib import Path
from unittest import mock

from ccd import autorelease, chat, config, flow, herdr, notify
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
SENT = DUE + 5          # ... and was delivered here
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
    """reflog answers `self.reflog` [(sha, unix)] newest first; rev-parse echoes the sha it is asked to verify;
    log answers main's own commits `self.log`, plus `self.carried` without --first-parent."""

    def __init__(self):
        self.calls = []
        self.log = []
        self.carried = []
        self.reflog = [(PIN, DUE - 3600)]
        self.fail = set()

    def __call__(self, root, args):
        self.calls.append(list(args))
        if args[0] in self.fail:
            return 1, ""
        if args[0] == "reflog":
            return 0, "".join(f"{sha}\x1forigin/main@{{{int(t)}}}\n" for sha, t in self.reflog)
        if args[0] == "rev-parse":
            return 0, args[-1].split("^")[0] + "\n"
        lines = self.log + ([] if "--first-parent" in args else self.carried)
        return 0, "".join(f"{sha}\x1f{subject}\n" for sha, subject in lines)


class Base(unittest.TestCase):
    MODE = "dry_run"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccd-autorel-")
        self.store = Store(os.path.join(self.tmp, "ccd.db"))
        self.addCleanup(self.store.close)
        self.ts = TaskStore(os.path.join(self.tmp, "tasks.db"), PROJECTS)
        self.addCleanup(self.ts.close)
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
        return AutoRelease(self.store, self.pipe, self.rel, self.policy, mode=mode or self.MODE, stop_file=self.stop,
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

    def healthy(self, project="commandcenter", when="2026-11-01T00:00:00Z"):
        self.log_line(project, "releases.jsonl", {"at": when, "result": "healthy"})

    def ticket(self, project="commandcenter", status="VERIFYING", deploy=True, verified=True, merged=MERGED):
        t, _ = self.ts.create(project, TITLE)
        d = {"env": "live", "requestedAt": merged, "approvedAt": None, "result": None} if deploy else None
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

    def digest(self, keys, project="commandcenter", window=W, state="delivered", uncertain=False, sent=SENT):
        self.store.put(f"release_mail:{project}", [{
            "window": window, "due": window - 86400, "state": state, "uncertain": uncertain, "attempts": 1,
            "at": window - 86400, "sentAt": sent if state == "delivered" else None,
            "listed": {"scheduled": list(keys), "verified": [], "held": []}}])

    def ready(self, project="commandcenter", n=1):
        """n tickets that would release: their digest delivered, a rehearsal, a healthy release on record, and
        main (as pinned) carrying exactly their merges."""
        keys = [self.ticket(project) for _ in range(n)]
        self.digest(keys, project)
        self.rehearse(project)
        self.healthy(project)
        self.git.log = [(f"{i + 1:07x}", f"Merge pull request #{i} from JayDalool/{k}-work") for i, k in enumerate(keys)]
        return keys

    def tick(self, when, ar=None):
        (ar or self.ar).run(ALLOWED, when)

    def through(self):
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


class _nolog:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


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
                self.tick(W + 60, ar)
                self.tick(W + 3 * 3600, ar)
                run_async(ar.tick(ALLOWED, W + 60))
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
        """Real filesystem errors, not a mock: Path.exists() says False for both, which would fail open."""
        self.ready()
        plain = Path(self.tmp) / "plain"
        plain.write_text("")
        loop = Path(self.tmp) / "loop"
        os.symlink(loop, loop)
        for path in (plain / "auto-release.stop", loop):        # ENOTDIR, ELOOP
            with self.subTest(str(path)):
                self.assertFalse(path.exists())
                self.ar.stop_file = path
                self.through()
                self.assertEqual((self.led(), self.events()), (None, []))
                self.assertTrue(self.ar.stopped)
        self.ar.stop_file = self.stop
        self.through()
        self.assertFalse(self.ar.stopped)
        self.decision()


class AllowList(Base):
    def test_the_allow_list_is_exactly_gyst_and_commandcenter(self):
        self.assertEqual(ALLOWED, ("gyst", "commandcenter"))

    def test_other_projects_are_never_eligible_whatever_the_facts(self):
        good = {"capabilities": GOOD_CAPS, "rehearsal": "pass", "health": True, "held": False, "range": None}
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
        self.healthy()
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

    def test_a_pulled_item_is_held_and_its_merge_in_the_range_blocks(self):
        keys = self.ready(n=2)
        self.pulled = {keys[1]}
        self.through()
        d = self.decision()
        self.assertEqual([(i["key"], i["reasons"]) for i in d["items"]],
                         [(keys[0], []), (keys[1], ["pulled from the release"])])
        self.assertIn(f"held change 0000002/{keys[1]}", d["blockers"])

    def test_keys_outside_the_project_are_never_stored_or_written_to(self):
        sv = self.ticket("samvision")
        cc = self.ready()[0]
        self.digest([cc, sv, "GYST-001", "not a key", "CC-999"])
        self.through()
        d = self.decision()
        self.assertEqual([i["key"] for i in d["items"]], [cc, "CC-999"])
        self.assertIn("manifest names a ticket outside the project", d["blockers"])
        self.assertEqual(d["items"][1]["reasons"], ["ticket not found"])
        stored = json.dumps(self.led())
        self.assertNotIn(sv, stored)
        self.assertNotIn("not a key", stored)
        self.assertEqual(self.events(sv), [])
        self.assertEqual([e[0] for e in self.events()], [cc])
        db = sqlite3.connect(self.ts.path, isolation_level=None)
        self.addCleanup(db.close)
        self.assertFalse(Pipeline.release_dry_run(db, "commandcenter", sv, "x", {"window": W, "phase": "decision"}))
        self.assertEqual(self.events(sv), [])


class Range(Base):
    def test_the_range_is_live_to_main_as_it_was_when_the_digest_was_delivered(self):
        self.ready()
        self.git.reflog = [("eeeeeee", SENT + 30), (PIN, DUE - 3600)]     # a fetch after delivery moved origin/main
        self.through()
        d = self.decision()
        self.assertEqual((d["live"], d["target"], d["eligible"]), (LIVE, PIN, True), d)
        self.assertIn(["log", "--first-parent", "--format=%h%x1f%s", f"{LIVE}..{PIN}"], self.git.calls)

    def test_no_reflog_entry_at_delivery_holds(self):
        self.ready()
        for reflog in ([("eeeeeee", SENT + 30)], []):
            with self.subTest(reflog):
                self.store.put("auto_release:commandcenter", {"rows": []})
                self.git.reflog = reflog
                self.through()
                d = self.decision()
                self.assertIn("no sha pinned at digest time", d["blockers"])
                self.assertIsNone(d["target"])

    def test_a_held_manifest_ticket_in_the_range_blocks_the_whole_release(self):
        ready, held = self.ready(n=2)
        tid = self.ts._id_of(held)
        self.ts.db.execute("UPDATE ticket_work SET verification=NULL WHERE ticket_id=?", (tid,))
        self.through()
        d = self.decision()
        self.assertFalse(d["eligible"])
        self.assertIn(f"held change 0000002/{held}", d["blockers"])
        self.assertEqual([i["would"] for i in d["items"]], ["hold", "hold"])

    def test_what_a_manifest_merge_carries_in_is_checked(self):
        key = self.ready()[0]
        other = self.ticket()
        self.git.carried = [("fffffff", f"{other}: slipped in through the branch"), ("1111111", "Review fixes")]
        self.through()
        d = self.decision()
        self.assertIn(f"unlisted change fffffff/{other}", d["blockers"])
        self.assertNotIn("unlisted change 1111111/no key", d["blockers"])    # a branch's own keyless commits are its
        self.assertEqual(d["items"], [{"key": key, "would": "hold", "reasons": []}])

    def test_a_ready_ticket_that_main_as_pinned_does_not_carry_is_held(self):
        keys = self.ready(n=2)
        self.git.log = self.git.log[:1]
        self.through()
        d = self.decision()
        self.assertEqual(d["items"][1]["reasons"], ["not in the pinned range"])

    def test_a_real_repository_where_main_moves_after_delivery(self):
        repo = Path(self.tmp) / "repo"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.invalid")

        def git(*args, when=None):
            e = dict(env, **({"GIT_COMMITTER_DATE": f"@{int(when)} +0000"} if when else {}))
            return subprocess.run(["git", "-C", str(repo), *args], env=e, check=True, capture_output=True,
                                  text=True).stdout.strip()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        key = self.ready()[0]
        late = self.ticket()
        git("commit", "-q", "--allow-empty", "-m", "base")
        base = git("rev-parse", "--short=7", "HEAD")
        git("commit", "-q", "--allow-empty", "-m", f"Merge pull request #1 from JayDalool/{key}-work")
        first = git("rev-parse", "HEAD")
        git("update-ref", "-m", "fetch", "refs/remotes/origin/main", first, when=DUE - 600)
        git("commit", "-q", "--allow-empty", "-m", f"Merge pull request #2 from JayDalool/{late}-late")
        git("update-ref", "-m", "fetch", "refs/remotes/origin/main", git("rev-parse", "HEAD"), when=SENT + 600)
        self.set_live_rev(f"20261111T010203Z-{base}")
        self.ar.git = autorelease.run_git
        with mock.patch.object(autorelease.registry, "root_of", return_value=str(repo)):
            self.through()
        d = self.decision()
        self.assertEqual((d["target"], d["blockers"], d["eligible"]), (first[:7], [], True), d)


class Readiness(Base):
    def test_capabilities_rehearsal_and_health_are_each_a_blocker(self):
        self.ready()
        self.policy.caps["commandcenter"] = {"health_checks": False, "auto_rollback": False}
        (self.deploys / "commandcenter" / "rehearsals.jsonl").unlink()
        (self.deploys / "commandcenter" / "releases.jsonl").unlink()
        self.through()
        d = self.decision()
        self.assertEqual(d["blockers"], ["health checks not configured", "rollback not configured",
                                         "no rehearsal recorded", "no health check recorded"])
        self.assertEqual((d["eligible"], d["items"][0]["would"]), (False, "hold"))

    def test_a_missing_release_log_alone_blocks_the_recorded_decision(self):
        self.ready()
        (self.deploys / "commandcenter" / "releases.jsonl").unlink()
        self.through()
        d = self.decision()
        self.assertEqual((d["eligible"], d["blockers"]), (False, ["no health check recorded"]))

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
                    "smtplib", "releasemail", "store"):
            self.assertNotIn(bad, names)
        for word in ("go-live", "systemctl", "deploy-web"):
            self.assertNotIn(word, src)

    def test_a_merge_ready_ticket_without_verification_is_held(self):
        self.ready()
        key = self.ticket(verified=False)
        self.digest([key])
        self.git.log = [("1234567", f"Merge pull request #3 from JayDalool/{key}-x")]
        self.through()
        self.assertEqual(self.decision()["items"],
                         [{"key": key, "would": "hold", "reasons": ["verification has not passed"]}])

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
        self.assertEqual(out[0]["items"], [{"key": a, "result": "pass", "at": W + 600},
                                           {"key": b, "result": "fail", "at": W + 900},
                                           {"key": c, "result": "none", "at": None}])
        self.assertEqual(set(out[0]), {"phase", "window", "at", "items", "delivered"})
        texts = {k: [e[3] for e in self.events(k)] for k in (a, b, c)}
        self.assertEqual((texts[a][1:], texts[b][1:], texts[c][1:]),
                         (["released: pass"], ["released: fail"], ["not released"]))
        stored = json.dumps(self.led()) + json.dumps([list(e) for e in self.events()])
        self.assertNotIn("jay", stored.replace("Jay", ""))
        self.assertNotIn("agent:coordinator", stored)
        api = self.ar.public(["commandcenter"])["projects"]["commandcenter"]["outcome"]
        self.assertEqual(api["items"], out[0]["items"])


class Hold(Base):
    def test_a_failed_or_inconclusive_release_since_the_last_pass_holds_the_project(self):
        for result in ("failed", "inconclusive"):
            with self.subTest(result):
                self.setUp()
                self.ready()
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
        self.healthy(when="2026-11-11T00:00:00Z")
        self.through()
        self.assertNotIn(HELD, self.decision()["blockers"])

    def test_the_hold_is_sticky_and_this_slice_has_no_clear(self):
        self.ready()
        self.log_line("commandcenter", "releases.jsonl", {"at": "2026-11-11T00:00:00Z", "result": "failed"})
        self.tick(DUE + 60)
        self.assertTrue(self.led()["hold"])
        (self.deploys / "commandcenter" / "releases.jsonl").unlink()     # deleting the log clears nothing
        self.healthy(when="2026-11-12T00:00:00Z")                         # nor does a forged healthy line
        self.tick(W + 60)
        self.assertIn(HELD, self.decision()["blockers"])
        self.assertIsNotNone(self.ar.public(["commandcenter"])["projects"]["commandcenter"]["held"])
        self.assertFalse(hasattr(autorelease, "clear_hold"))
        self.assertFalse(hasattr(autorelease, "main"))

    def test_an_absent_or_unreadable_release_log(self):
        self.assertEqual(autorelease.release_log("commandcenter", self.deploys), (None, None))
        self.log_line("commandcenter", "releases.jsonl", "not json")
        good, bad = autorelease.release_log("commandcenter", self.deploys)
        self.assertIsNone(good)
        self.assertIsNotNone(bad)


class Dedup(Base):
    def test_a_restart_mid_window_writes_no_second_decision(self):
        key = self.ready()[0]
        self.through()
        self.ar = self.make()       # a restart: a new AutoRelease on the same databases
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
        self.assertIn("no manifest emailed", self.decision()["blockers"])

    def test_a_partial_event_write_is_finished_after_a_restart_never_duplicated(self):
        keys = self.ready(n=3)
        real = Pipeline.release_dry_run
        calls = []

        def flaky(db, project, key, text, data):
            calls.append(key)
            if len(calls) == 2:
                raise sqlite3.OperationalError("disk I/O error")
            return real(db, project, key, text, data)
        with mock.patch.object(Pipeline, "release_dry_run", staticmethod(flaky)), self.assertLogs("ccd", "WARNING"):
            self.through()
        self.assertEqual([e[0] for e in self.events()], keys[:1])
        self.assertFalse(self.decision()["delivered"])
        self.ar = self.make()       # a restart
        self.tick(W + 120)
        self.tick(W + 180)
        self.assertEqual(sorted(e[0] for e in self.events()), sorted(keys))
        self.assertTrue(self.decision()["delivered"])


class Responsive(Base):
    def test_a_locked_database_and_a_fifo_log_never_stall_the_loop(self):
        keys = self.ready()
        log = self.deploys / "commandcenter" / "releases.jsonl"
        log.unlink()
        os.mkfifo(log)                  # opening this for a blocking read would hang until a writer comes
        locker = sqlite3.connect(self.ts.path, isolation_level=None)
        self.addCleanup(locker.close)
        locker.execute("BEGIN IMMEDIATE")           # another writer holds tasks.db
        gaps = []

        async def main():
            last = time.monotonic()

            async def beat():
                nonlocal last
                while True:
                    await asyncio.sleep(0.01)
                    now = time.monotonic()
                    gaps.append(now - last)
                    last = now
            b = asyncio.create_task(beat())
            t0 = time.monotonic()
            await self.ar.tick(ALLOWED, W + 60)
            took = time.monotonic() - t0
            b.cancel()
            return took
        with mock.patch.object(autorelease, "DB_TIMEOUT", 0.5), self.assertLogs("ccd", "WARNING"):
            took = asyncio.run(main())
        self.assertLess(took, 5)
        self.assertLess(max(gaps), 0.25, "the event loop stalled")
        self.assertIn("no health check recorded", self.decision()["blockers"])
        self.assertEqual(self.events(), [])
        locker.execute("ROLLBACK")
        self.tick(W + 120)                          # the lock is gone: the notes are finished
        self.assertEqual([e[0] for e in self.events()], keys)

    def test_a_tick_past_its_deadline_returns_and_the_next_is_skipped(self):
        gate = threading.Event()
        runs = []

        def slow(*a):
            runs.append(a)
            gate.wait(5)
        self.ar.run = slow

        async def main():
            t0 = time.monotonic()
            await self.ar.tick(ALLOWED, W + 60)
            took, busy = time.monotonic() - t0, self.ar._busy
            await self.ar.tick(ALLOWED, W + 60)
            gate.set()
            for _ in range(100):
                if not self.ar._busy:
                    break
                await asyncio.sleep(0.01)
            return took, busy
        with mock.patch.object(autorelease, "TICK_DEADLINE", 0.2), self.assertLogs("ccd", "WARNING"):
            took, busy = asyncio.run(main())
        self.assertLess(took, 1)
        self.assertTrue(busy)
        self.assertEqual(len(runs), 1)
        self.assertFalse(self.ar._busy)


def run_async(coro):
    return asyncio.run(coro)


class Tripwire:
    def __init__(self, hits, name):
        self._hits, self._name = hits, name

    def __getattr__(self, attr):
        self._hits.append(f"{self._name}.{attr}")
        raise AssertionError(f"the dry run touched {self._name}.{attr}")


class WithDaemon(Base):
    def daemon(self, **over):
        from ccd.daemon import Daemon
        from .helpers import cfg
        store = Store(os.path.join(self.tmp, "real.db"))
        self.addCleanup(store.close)
        return Daemon(cfg(meter={"enabled": False}, release_path=os.path.join(self.tmp, "release.json"),
                          work_mode_path=os.path.join(self.tmp, "wm.json"), **over), store, None, tasks=self.ts)


class Safety(WithDaemon):
    def test_the_daemon_tick_never_reaches_anything_that_acts_even_when_it_fails(self):
        from ccd.daemon import Daemon
        keys = self.ready(n=2)
        d = self.daemon(auto_release="dry_run")
        ar = d.auto_release
        ar.stop_file, ar.deploys_dir, ar.web_current, ar.git = self.stop, self.deploys, self.web / "current", self.git
        ar.policy = self.policy
        d.store.put("release_mail:commandcenter", self.store.get("release_mail:commandcenter")[0])
        hits = []
        d.herdr = Tripwire(hits, "herdr")
        d.notifier = Tripwire(hits, "notifier")

        def boom(name):
            def f(*a, **k):
                hits.append(name)
                raise AssertionError(f"the dry run called {name}")
            return f
        wires = [(herdr.Herdr, "_open"), (herdr.Herdr, "call"), (chat.Chat, "add"), (notify.SlackWeb, "post"),
                 (notify.Notifier, "post"), (notify.Notifier, "push"), (smtplib, "SMTP"), (smtplib, "SMTP_SSL"),
                 (urllib.request, "urlopen"), (http.client.HTTPConnection, "request"),
                 (socket, "create_connection"), (subprocess, "Popen"), (Daemon, "_event"), (Store, "append"),
                 (Pipeline, "_tx"), (Pipeline, "confirm"), (Pipeline, "deploy_request"), (Pipeline, "deployed"),
                 (Pipeline, "deploy_go"), (Pipeline, "deploy_plan"), (Pipeline, "verify"), (TaskStore, "_apply"),
                 (TaskStore, "_touch")]
        before_events = d.store.last_seq()

        def snap():
            return (self.ts.db.execute("SELECT key, status, updated_at FROM tickets ORDER BY id").fetchall(),
                    self.ts.db.execute("SELECT * FROM ticket_work ORDER BY ticket_id").fetchall(),
                    [flow.idle_since(self.pipe._events(self.ts._id_of(k))) for k in keys])
        before = snap()
        patches = [mock.patch.object(obj, name, boom(f"{getattr(obj, '__name__', obj)}.{name}")) for obj, name in wires]
        for p in patches:
            p.start()
        try:
            run_async(d.auto_release_tick(W + 60))
            run_async(d.auto_release_tick(W + 3 * 3600))
            with mock.patch.object(Pipeline, "release_facts", side_effect=RuntimeError("boom")), \
                    self.assertLogs("ccd", "WARNING"):
                run_async(d.auto_release_tick(W + 7 * 86400 + 60))
        finally:
            for p in patches:
                p.stop()
            d.herdr = d.notifier = None
        self.assertEqual(hits, [])
        led = d.store.get("auto_release:commandcenter")[0]
        self.assertTrue([r for r in led["rows"] if r["phase"] == "decision"][-1]["eligible"])
        self.assertEqual(len(self.events()), 4)
        self.assertEqual(d.store.last_seq(), before_events)        # no daemon event, so nothing for Slack to post
        self.assertEqual(snap(), before)
        self.assertTrue(all(not e[2].startswith("pipeline.") for e in self.events()))
        fake = types.SimpleNamespace(d=types.SimpleNamespace(tasks=self.ts))
        self.assertEqual(notify.Notifier._day_events(fake, 0), {})
        brief = d.briefing(now=time.time() + 1)        # the notes are stamped with the real clock: count them
        cc = next(p for p in brief["projects"] if p["key"] == "commandcenter")
        self.assertEqual((cc["merged"], cc["done"], cc["deploys"], cc["highlights"]), (0, 0, 0, []))
        self.assertFalse(any(m.get("idleSince") for m in self.pipe.compact([self.ts._id_of(k) for k in keys]).values()))

    def test_a_full_eligible_step_runs_only_read_only_git(self):
        self.ready(n=2)
        self.ar.git = autorelease.run_git            # the real runner, over a patched subprocess
        calls = []
        log = "".join(f"{sha}\x1f{s}\n" for sha, s in self.git.log)

        def fake_run(argv, **kw):
            calls.append((argv, kw))
            out = (f"{PIN}\x1forigin/main@{{{int(DUE - 3600)}}}\n" if argv[3] == "reflog"
                   else PIN + "\n" if argv[3] == "rev-parse" else log)
            return subprocess.CompletedProcess(argv, 0, out, "")
        with mock.patch.object(autorelease.subprocess, "run", fake_run):
            self.through()
        self.assertTrue(self.decision()["eligible"])
        for argv, kw in calls:
            self.assertIsInstance(argv, list)
            self.assertEqual(argv[0], "git")
            self.assertNotIn("fetch", argv)
            self.assertIn(argv[3], ("reflog", "rev-parse", "log"))
            self.assertNotIn("shell", kw)
            self.assertEqual(kw.get("timeout"), autorelease.GIT_TIMEOUT)

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
                self.assertEqual(self.git.calls, [])

    def test_a_git_failure_or_timeout_is_cannot_read_range(self):
        self.ready()
        self.git.fail = {"log"}
        self.through()
        self.assertIn("cannot read range", self.decision()["blockers"])
        self.store.put("auto_release:commandcenter", {"rows": []})
        self.ar.git = autorelease.run_git

        def slow_log(argv, **kw):
            if argv[3] == "log":
                raise subprocess.TimeoutExpired(argv, kw["timeout"])
            out = f"{PIN}\x1forigin/main@{{{int(DUE - 3600)}}}\n" if argv[3] == "reflog" else PIN + "\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        with mock.patch.object(autorelease.subprocess, "run", slow_log):
            self.through()
        self.assertIn("cannot read range", self.decision()["blockers"])

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


class Api(WithDaemon):
    def test_release_state_reads_only_the_ledger_and_shows_gyst_and_commandcenter(self):
        d = self.daemon(auto_release="dry_run")
        d.store.put("auto_release:commandcenter", {"rows": [
            {"phase": "decision", "window": W, "at": W + 60, "eligible": False, "blockers": ["no manifest emailed"],
             "items": [], "live": None, "target": None}], "hold": None})

        def boom(*a, **k):
            raise AssertionError("GET /api/release must read the ledger only")
        with mock.patch.object(autorelease.subprocess, "run", boom), mock.patch("os.readlink", boom), \
                mock.patch("os.stat", boom), mock.patch("os.open", boom), mock.patch("builtins.open", boom):
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
