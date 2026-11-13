"""HQ next (ccd/hq.py, contracts.md 1-3): milestones, the overnight briefing, project logos."""
import io
import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from ccd import hq as hq_mod
from ccd import milestone_cli, security

from .test_api import ApiBase, AUTH, JSON

DEV_SECRET = "d" * 43
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
SVG = b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"
LEAD = dict(JSON, **{"x-ccd-actor": "agent:lead-samvision"})
OTHER_LEAD = dict(JSON, **{"x-ccd-actor": "agent:lead-gyst"})
WORKER = dict(JSON, **{"x-ccd-actor": "agent:coordinator"})


class HqBase(ApiBase):
    def equip(self, daemon):
        self.base = tempfile.mkdtemp(prefix="hq-")
        daemon.hq = hq_mod.HqStore(os.path.join(self.base, "hq.db"), os.path.join(self.base, "project-logos"))
        daemon.dev_gate = security.DeveloperGate(DEV_SECRET)

    def tearDown(self):
        super().tearDown()
        self.daemon.hq.close()
        shutil.rmtree(self.base)

    def unlock(self):
        r = self.client.post("/api/developer/unlock", content=json.dumps({"token": DEV_SECRET}), headers=JSON)
        self.assertEqual(r.status_code, 200)
        return dict(JSON, **{"x-ccd-developer": r.json()["session"]})

    def send(self, method, path, body=None, headers=JSON):
        return self.client.request(method, path, content=json.dumps(body if body is not None else {}),
                                   headers=headers)

    def events(self, prefix):
        return [e for e in self.store.since(0) if e["kind"].startswith(prefix)]


class Milestones(HqBase):
    def add(self, project="samvision", track="technical", title="Set up the backend", headers=JSON, **kw):
        return self.send("POST", f"/api/milestones/{project}", dict(track=track, title=title, **kw), headers)

    def test_every_task_project_appears_with_empty_tracks(self):
        body = self.get("/api/milestones").json()
        keys = {p["key"] for p in self.daemon._projects()}
        self.assertEqual(set(body["projects"]), keys)
        self.assertIn("commandcenter", keys)                    # a ticket-only project too
        self.assertEqual(body["projects"]["gyst"], {"technical": [], "business": [], "revision": 0})

    def test_jay_adds_both_tracks_in_display_order(self):
        r = self.add(due="2026-12-01", note="Postgres, then the API")
        self.assertEqual(r.status_code, 200, r.text)
        m = r.json()["milestone"]
        self.assertRegex(m["id"], r"^m_[0-9a-f]{12}$")
        self.assertEqual({k: m[k] for k in ("title", "state", "due", "note", "doneAt", "by")},
                         {"title": "Set up the backend", "state": "todo", "due": "2026-12-01",
                          "note": "Postgres, then the API", "doneAt": None, "by": "jay"})
        self.assertNotIn("track", m)
        self.add(title="Set up the frontend")
        self.add(track="business", title="Contact the lawyer")
        r = self.add(track="business", title="Send the email to the client")
        self.assertEqual(r.json()["revision"], 4)
        sv = self.get("/api/milestones").json()["projects"]["samvision"]
        self.assertEqual([m["title"] for m in sv["technical"]], ["Set up the backend", "Set up the frontend"])
        self.assertEqual([m["title"] for m in sv["business"]], ["Contact the lawyer", "Send the email to the client"])
        self.assertEqual(sv["revision"], 4)

    def test_state_changes_set_and_clear_done_at(self):
        mid = self.add().json()["milestone"]["id"]
        r = self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "doing"})
        self.assertEqual((r.json()["milestone"]["state"], r.json()["milestone"]["doneAt"]), ("doing", None))
        before = time.time()
        r = self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "done", "title": "Backend is up"})
        m = r.json()["milestone"]
        self.assertEqual((m["state"], m["title"]), ("done", "Backend is up"))
        self.assertGreaterEqual(m["doneAt"], before)
        r = self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "todo", "due": None, "note": ""})
        self.assertEqual((r.json()["milestone"]["doneAt"], r.json()["milestone"]["note"]), (None, None))

    def test_validation(self):
        for body, status in (({"track": "legal", "title": "x"}, 400), ({"track": "technical"}, 400),
                             ({"track": "technical", "title": "   "}, 400),
                             ({"track": "technical", "title": "x" * 141}, 400),
                             ({"track": "technical", "title": "bell\x07"}, 400),
                             ({"track": "technical", "title": "rotate token: abcdef123456"}, 400),
                             ({"track": "technical", "title": "ok", "due": "2026-02-30"}, 400),
                             ({"track": "technical", "title": "ok", "due": "next week"}, 400),
                             ({"track": "technical", "title": "ok", "note": "n" * 501}, 400),
                             ({"track": "technical", "title": "ok", "note": "password: hunter22"}, 400),
                             ({"track": "technical", "title": "ok", "owner": "jay"}, 400)):
            r = self.send("POST", "/api/milestones/samvision", body)
            self.assertEqual(r.status_code, status, (body, r.text))
        self.assertEqual(self.add(project="nosuch").status_code, 404)
        self.assertEqual(self.add(title="x" * 140).status_code, 200)
        mid = self.add().json()["milestone"]["id"]
        self.assertEqual(self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "blocked"}).status_code, 400)
        self.assertEqual(self.send("PATCH", f"/api/milestones/samvision/{mid}", {}).status_code, 400)
        self.assertEqual(self.send("PATCH", f"/api/milestones/samvision/{mid}", {"track": "business"}).status_code, 400)
        self.assertEqual(self.send("PATCH", f"/api/milestones/gyst/{mid}", {"state": "done"}).status_code, 404)
        self.assertEqual(self.send("PATCH", "/api/milestones/samvision/m_000000000000", {"state": "done"}).status_code,
                         404)

    def test_a_lead_writes_only_its_own_technical_milestones(self):
        r = self.add(headers=LEAD, title="Ship the mobile layout")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["milestone"]["by"], "agent:lead-samvision")
        mid = r.json()["milestone"]["id"]
        self.assertEqual(self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "done"}, LEAD).status_code,
                         200)
        self.assertEqual(self.add(headers=LEAD, track="business").status_code, 403)
        self.assertEqual(self.add(headers=OTHER_LEAD).status_code, 403)
        self.assertEqual(self.add(headers=WORKER).status_code, 403)
        biz = self.add(track="business", title="Contact the lawyer").json()["milestone"]["id"]
        self.assertEqual(self.send("PATCH", f"/api/milestones/samvision/{biz}", {"state": "done"}, LEAD).status_code,
                         403)
        self.assertEqual(self.send("DELETE", f"/api/milestones/samvision/{mid}", None, LEAD).status_code, 403)
        rev = self.get("/api/milestones").json()["projects"]["samvision"]["revision"]
        self.assertEqual(self.send("PUT", "/api/milestones/samvision/order",
                                   {"track": "technical", "ids": [mid], "revision": rev}, LEAD).status_code, 403)
        self.assertEqual(self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "todo"}, OTHER_LEAD).status_code,
                         403)

    def test_remove_and_reorder_with_a_revision(self):
        a = self.add(title="A").json()["milestone"]["id"]
        b = self.add(title="B").json()["milestone"]["id"]
        c = self.add(title="C").json()["milestone"]["id"]
        rev = self.get("/api/milestones").json()["projects"]["samvision"]["revision"]
        r = self.send("PUT", "/api/milestones/samvision/order", {"track": "technical", "ids": [c, a, b], "revision": rev})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["revision"], rev + 1)
        sv = self.get("/api/milestones").json()["projects"]["samvision"]
        self.assertEqual([m["title"] for m in sv["technical"]], ["C", "A", "B"])
        # a stale list is refused, and so is anything but every id once
        stale = self.send("PUT", "/api/milestones/samvision/order", {"track": "technical", "ids": [a, b, c], "revision": rev})
        self.assertEqual(stale.status_code, 409)
        for ids in ([a, b], [a, b, c, c], [a, b, "m_000000000000"]):
            r = self.send("PUT", "/api/milestones/samvision/order",
                          {"track": "technical", "ids": ids, "revision": rev + 1})
            self.assertEqual(r.status_code, 400, ids)
        self.assertEqual(self.send("PUT", "/api/milestones/samvision/order",
                                   {"track": "technical", "ids": [a, b, c], "revision": "1"}).status_code, 400)
        r = self.send("DELETE", f"/api/milestones/samvision/{a}")
        self.assertEqual(r.json(), {"ok": True, "revision": rev + 2})
        self.assertEqual(self.send("DELETE", f"/api/milestones/samvision/{a}").status_code, 404)
        self.assertEqual([m["title"] for m in self.get("/api/milestones").json()["projects"]["samvision"]["technical"]],
                         ["C", "B"])

    def test_events_carry_ids_never_titles_or_notes(self):
        mid = self.add(title="Call the bank about SECRETPLAN", note="the NOTEWORDS").json()["milestone"]["id"]
        self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "doing"})
        self.send("PATCH", f"/api/milestones/samvision/{mid}", {"state": "done"})
        self.send("DELETE", f"/api/milestones/samvision/{mid}")
        evs = self.events("milestone.")
        self.assertEqual([e["kind"] for e in evs], ["milestone.added", "milestone.changed", "milestone.done",
                                                    "milestone.removed"])
        for e in evs:
            self.assertEqual(e["project"], "samvision")
            self.assertEqual((e["data"]["id"], e["data"]["track"]), (mid, "technical"))
            self.assertNotIn("SECRETPLAN", json.dumps(e))
            self.assertNotIn("NOTEWORDS", json.dumps(e))
        self.assertEqual(evs[2]["data"]["state"], "done")

    def test_writes_are_audited_and_the_store_is_private(self):
        self.add()
        self.assertEqual(os.stat(os.path.join(self.base, "hq.db")).st_mode & 0o777, 0o600)
        rows = self.daemon.audit.list(limit=20)
        rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
        self.assertTrue(any("/api/milestones/samvision" in json.dumps(r) for r in rows), rows)

    def test_off_when_not_configured(self):
        self.daemon.hq.close()
        saved, self.daemon.hq = self.daemon.hq, None
        try:
            self.assertEqual(self.get("/api/milestones").status_code, 503)
            self.assertEqual(self.get("/api/projects/logos").status_code, 503)
        finally:
            self.daemon.hq = hq_mod.HqStore(os.path.join(self.base, "hq.db"), os.path.join(self.base, "project-logos"))


class Logos(HqBase):
    def put(self, project, data, headers=None):
        h = dict(headers or AUTH, **{"content-type": "application/octet-stream"})
        return self.client.put(f"/api/projects/{project}/logo", content=data, headers=h)

    def test_upload_needs_jay_with_developer_unlock(self):
        self.assertEqual(self.put("samvision", PNG).status_code, 403)
        dev = self.unlock()
        self.assertEqual(self.put("samvision", PNG, dict(dev, **{"x-ccd-actor": "agent:lead-samvision"})).status_code,
                         403)
        r = self.put("samvision", PNG, dev)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["ok"], body["mime"]), (True, "image/png"))
        self.assertRegex(body["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.client.delete("/api/projects/samvision/logo", headers=JSON).status_code, 403)

    def test_types_come_from_the_bytes_and_size_is_capped(self):
        dev = self.unlock()
        for data, mime in ((PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")):
            r = self.put("gyst", data, dev)
            self.assertEqual(r.json()["mime"], mime, r.text)
        for data in (GIF, SVG, b"<html><script>x</script></html>", b"", b"MZ\x90\x00" * 10):
            self.assertEqual(self.put("mfe", data, dev).status_code, 415, data[:10])
        self.assertEqual(self.put("mfe", PNG + b"\x00" * hq_mod.LOGO_MAX, dev).status_code, 413)
        self.assertEqual(self.put("nosuch", PNG, dev).status_code, 404)
        self.assertEqual(self.client.put("/api/projects/mfe/logo", content=PNG,
                                         headers=dict(dev, **{"content-type": "image/png"})).status_code, 415)
        self.assertNotIn("mfe", self.get("/api/projects/logos").json())
        folder = os.path.join(self.base, "project-logos")
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        self.assertEqual(sorted(os.listdir(folder)), ["gyst"])          # refused uploads leave nothing

    def test_download_is_an_attachment_and_listing_lets_the_ui_cache(self):
        dev = self.unlock()
        self.assertEqual(self.get("/api/projects/samvision/logo").status_code, 404)
        sha = self.put("samvision", PNG, dev).json()["sha256"]
        r = self.get("/api/projects/samvision/logo")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PNG)
        self.assertEqual(r.headers["content-type"], "application/octet-stream")
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn("sandbox", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        listing = self.get("/api/projects/logos").json()
        self.assertEqual(set(listing), {"samvision"})
        self.assertEqual((listing["samvision"]["mime"], listing["samvision"]["sha256"]), ("image/png", sha))
        self.assertEqual(self.client.get("/api/projects/samvision/logo", headers={"host": AUTH["host"]}).status_code, 401)
        r = self.client.delete("/api/projects/samvision/logo", headers=dev)
        self.assertEqual(r.json(), {"ok": True})
        self.assertEqual(self.get("/api/projects/samvision/logo").status_code, 404)
        self.assertEqual(self.client.delete("/api/projects/samvision/logo", headers=dev).status_code, 404)
        self.assertEqual(self.get("/api/projects/logos").json(), {})
        self.assertEqual([e["kind"] for e in self.events("logo.")], ["logo.changed", "logo.removed"])

    def test_only_the_logo_put_takes_raw_bytes(self):
        dev = self.unlock()
        r = self.client.put("/api/milestones/samvision/order", content=PNG,
                            headers=dict(dev, **{"content-type": "application/octet-stream"}))
        self.assertEqual(r.status_code, 415)
        r = self.client.post("/api/projects/samvision/logo", content=PNG,
                             headers=dict(dev, **{"content-type": "application/octet-stream"}))
        self.assertEqual(r.status_code, 415)


class Briefing(HqBase):
    def test_quiet_window(self):
        body = self.get("/api/briefing").json()
        self.assertAlmostEqual(body["until"] - body["since"], 12 * 3600, delta=5)
        keys = [p["key"] for p in self.daemon._projects()]
        self.assertEqual([p["key"] for p in body["projects"]], keys)
        p = body["projects"][0]
        self.assertEqual(set(p), {"key", "name", "merged", "done", "failedChecks", "opened", "questionsAsked",
                                  "questionsAnswered", "deploys", "needsYou", "mainChecks", "spendUsd", "highlights"})
        self.assertIsNone(p["spendUsd"])                           # the meter has read nothing: null, not 0
        self.assertEqual(set(body["totals"]), {"merged", "done", "failedChecks", "opened", "questionsAsked",
                                               "questionsAnswered", "deploys", "needsYou"})
        self.assertIs(body["quiet"], True)

    def test_since_is_validated_and_clamped_to_retention(self):
        self.assertEqual(self.get("/api/briefing?since=yesterday").status_code, 400)
        self.assertEqual(self.get("/api/briefing?since=-5").status_code, 400)
        body = self.get("/api/briefing?since=0").json()
        keep = self.daemon.cfg["retention_days"] * 86400
        self.assertAlmostEqual(body["until"] - body["since"], keep, delta=5)
        future = self.get(f"/api/briefing?since={int(time.time()) + 9999}").json()
        self.assertLessEqual(future["since"], future["until"])

    def test_counts_and_highlights_from_tickets_and_the_event_log(self):
        d = self.daemon
        start = time.time() - 1
        t, _ = d.tasks.create("samvision", "Add the billing page")
        d.pipeline.ask(t["key"], [{"text": "Stripe or Paddle?", "kind": "text"}, "Monthly or yearly?"], "agent:coord")
        qs = [q["id"] for q in d.task_work(t["key"])["questions"]]
        d.pipeline.answer(t["key"], [{"id": qs[0], "answer": "Stripe"}], "jay")
        tid = d.tasks.db.execute("SELECT id FROM tickets WHERE key=?", (t["key"],)).fetchone()[0]
        for kind in ("pipeline.merged", "pipeline.auto_merged", "pipeline.deployed"):
            d.tasks.db.execute("INSERT INTO ticket_events(ticket_id, at, actor, kind) VALUES (?,?,?,?)",
                               (tid, time.time(), "agent:coord", kind))
        d.tasks.db.execute("INSERT INTO ticket_events(ticket_id, at, actor, kind) VALUES (?,?,?,?)",
                           (tid, start - 7 * 3600 * 24, "agent:coord", "pipeline.done"))   # outside the window
        d._event("github", "pr.opened", "PR #7 opened", project="samvision", ref="#7", data={"number": 7})
        d._event("github", "pr.ci_changed", "PR #7 checks ✓ → ✗", project="samvision", ref="#7",
                 data={"number": 7, "from": "✓", "to": "✗"})
        d._event("github", "pr.ci_changed", "PR #7 checks ✗ → ✓", project="samvision", ref="#7",
                 data={"number": 7, "from": "✗", "to": "✓"})
        d._event("tasks", "task.pipeline", f"{t['key']} merged", project="samvision", ref=t["key"],
                 data={"kind": "pipeline.merged"})
        d._event("tasks", "task.pipeline", f"{t['key']} plan recorded", project="samvision", ref=t["key"],
                 data={"kind": "pipeline.plan"})
        body = self.get(f"/api/briefing?since={int(start)}").json()
        sv = next(p for p in body["projects"] if p["key"] == "samvision")
        self.assertEqual({k: sv[k] for k in ("merged", "done", "deploys", "opened", "failedChecks", "questionsAsked",
                                             "questionsAnswered")},
                         {"merged": 1, "done": 0, "deploys": 1, "opened": 1, "failedChecks": 1, "questionsAsked": 2,
                          "questionsAnswered": 1})
        self.assertGreaterEqual(sv["needsYou"], 1)                 # one question still open
        kinds = [h["kind"] for h in sv["highlights"]]
        self.assertIn("pipeline.merged", kinds)
        self.assertIn("pr.opened", kinds)
        self.assertNotIn("pipeline.plan", kinds)
        self.assertEqual(kinds.count("pr.ci_changed"), 1)        # only the change to failing
        self.assertEqual(sv["highlights"], sorted(sv["highlights"], key=lambda h: -h["at"]))
        self.assertEqual(next(h for h in sv["highlights"] if h["kind"] == "pr.opened")["text"], "PR #7 opened")
        self.assertIs(body["quiet"], False)
        self.assertEqual(body["totals"]["merged"], 1)

    def test_highlights_are_at_most_eight(self):
        for i in range(12):
            self.daemon._event("github", "pr.opened", f"PR #{i} opened", project="gyst", ref=f"#{i}",
                               data={"number": i})
        gy = next(p for p in self.get("/api/briefing").json()["projects"] if p["key"] == "gyst")
        self.assertEqual(gy["opened"], 12)
        self.assertEqual([h["ref"] for h in gy["highlights"]], [f"#{i}" for i in range(11, 3, -1)])

    def test_client_projects_carry_ids_and_a_risk_line_only(self):
        self.daemon._event("tasks", "task.pipeline", "GM-9 merged: the intake form for Acme Dental", project="gauzemate",
                           ref="GM-9", data={"kind": "pipeline.merged"})
        self.daemon._event("tasks", "task.pipeline", "GM-9 gate opened: Acme legal review", project="gauzemate",
                           ref="GM-9", data={"kind": "pipeline.gate_opened"})
        gm = next(p for p in self.get("/api/briefing").json()["projects"] if p["key"] == "gauzemate")
        self.assertEqual([h["text"] for h in gm["highlights"]], ["GM-9 · waiting on you", "GM-9 · merged"])
        self.assertNotIn("Acme", json.dumps(gm))

    def test_milestone_done_is_a_highlight(self):
        r = self.send("POST", "/api/milestones/mfe", {"track": "business", "title": "Contact the lawyer"})
        self.send("PATCH", f"/api/milestones/mfe/{r.json()['milestone']['id']}", {"state": "done"})
        mfe = next(p for p in self.get("/api/briefing").json()["projects"] if p["key"] == "mfe")
        self.assertEqual([h["kind"] for h in mfe["highlights"]], ["milestone.done"])
        self.assertNotIn("lawyer", json.dumps(mfe))

    def test_spend_comes_from_the_meter_when_it_has_read(self):
        meter = self.daemon.meter
        if meter is None:
            self.skipTest("meter off in this config")
        now = time.time()
        cols = [r[1] for r in meter.db.execute("PRAGMA table_info(usage_records)")]
        row = {c: None for c in cols}
        row.update(at=now - 60, project="samvision", source="claude", cost_usd=1.25, input=1, output=1, cache_read=0,
                   cache_write=0)
        row = {k: v for k, v in row.items() if k in cols}
        for c in cols:
            if row.get(c) is None and c not in ("cost_usd", "ticket_key", "model", "project"):
                row[c] = 0 if c not in ("ref", "source", "path", "session", "actor") else f"x-{c}"
        meter.db.execute(f"INSERT INTO usage_records({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                         tuple(row.values()))
        self.daemon.meter_read_at = now
        projects = {p["key"]: p for p in self.get("/api/briefing").json()["projects"]}
        self.assertEqual(projects["samvision"]["spendUsd"], 1.25)
        self.assertEqual(projects["gyst"]["spendUsd"], 0.0)


class MilestoneCli(unittest.TestCase):
    def test_lead_cli_speaks_as_the_lead_on_the_technical_track(self):
        calls = []

        def fake(method, path, body=None, actor=None, **kw):
            calls.append((method, path, body, actor))
            if method == "GET":
                return 0, {"projects": {"samvision": {"technical": [
                    {"id": "m_0123456789ab", "title": "Backend", "state": "doing", "due": None}],
                    "business": [], "revision": 3}}}
            return 0, {"milestone": {"id": "m_0123456789ab", "title": "Backend"}, "revision": 4}
        out = io.StringIO()
        with mock.patch.object(milestone_cli, "call", fake), mock.patch.dict(os.environ, {"CCD_ACTOR": ""}), \
                redirect_stdout(out):
            self.assertEqual(milestone_cli.main(["list", "samvision"]), 0)
            self.assertEqual(milestone_cli.main(["add", "samvision", "Backend", "--due", "2026-12-01"]), 0)
            self.assertEqual(milestone_cli.main(["start", "samvision", "m_0123456789ab"]), 0)
            self.assertEqual(milestone_cli.main(["done", "samvision", "m_0123456789ab"]), 0)
        self.assertIn("[~] m_0123456789ab  Backend", out.getvalue())
        self.assertIn("none yet", out.getvalue())
        self.assertEqual({c[3] for c in calls}, {"agent:lead-samvision"})
        self.assertEqual(calls[1][1:3], ("/api/milestones/samvision",
                                         {"track": "technical", "title": "Backend", "due": "2026-12-01"}))
        self.assertEqual([c[2] for c in calls[2:]], [{"state": "doing"}, {"state": "done"}])


class Store(unittest.TestCase):
    def test_logo_folder_must_be_a_real_folder(self):
        base = tempfile.mkdtemp(prefix="hqs-")
        try:
            os.symlink("/tmp", os.path.join(base, "logos"))
            with self.assertRaises(OSError):
                hq_mod.HqStore(os.path.join(base, "hq.db"), os.path.join(base, "logos"))
        finally:
            shutil.rmtree(base)

    def test_sniff(self):
        self.assertEqual(hq_mod.sniff_logo(PNG[:16]), "image/png")
        self.assertIsNone(hq_mod.sniff_logo(GIF[:16]))
        self.assertIsNone(hq_mod.sniff_logo(SVG[:16]))
        self.assertTrue(stat.S_ISDIR(os.stat(tempfile.gettempdir()).st_mode))


if __name__ == "__main__":
    unittest.main()
