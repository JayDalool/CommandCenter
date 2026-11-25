"""Fleet report (CC-079): fake loopback apps, never a real database or customer data."""
import ast
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ccd import fleet, registry

GOOD = {"accounts": 12, "active": 7, "active_window_days": 30}


class FakeApp:
    """A loopback server answering `body` (bytes) with `status`, or sleeping `delay`."""
    def __init__(self, body=None, status=200, delay=0, token="tok"):
        outer = self
        outer.seen = []
        outer.body = json.dumps(GOOD).encode() if body is None else body

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(self.headers.get("Authorization"))
                if delay:
                    threading.Event().wait(delay)
                if self.headers.get("Authorization") != f"Bearer {token}":
                    self.send_response(401); self.end_headers(); return
                self.send_response(status); self.end_headers()
                try:
                    self.wfile.write(outer.body)
                except OSError:
                    pass

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/api/internal/fleet/v1/accounts"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown(); self.srv.server_close()


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apps = []
        fleet._cache.update(at=0.0, report=None)

    def tearDown(self):
        for a in self.apps:
            a.close()
        self.tmp.cleanup()

    def entry(self, app, name="a", mode=0o600, token="tok"):
        self.apps.append(app)
        p = Path(self.tmp.name) / f"{name}.token"
        p.write_text(token)
        os.chmod(p, mode)
        return {"url": app.url, "token_file": str(p)}

    def test_totals_definition_and_labels(self):
        apps = {"samvision": self.entry(FakeApp(), "sv"),
                "mfe": self.entry(FakeApp(json.dumps({"accounts": 3, "active": 1, "active_window_days": 30}).encode()), "mfe")}
        r = fleet.build(apps)
        self.assertEqual(r["total"]["accounts"], 15)
        self.assertEqual(r["total"]["active"], 8)
        self.assertEqual(r["total"]["label"], "accounts (not people)")
        self.assertEqual(sorted(r["answered"]), ["mfe", "samvision"])
        self.assertEqual(r["didNotRespond"], [])
        for row in r["apps"]:
            self.assertIn("last 30 days", row["definition"])
            self.assertEqual(row["unit"], "accounts (not people)")
        self.assertIn("accounts, not people", r["definition"])

    def test_bad_apps_listed_without_echoing_their_reply(self):
        secret = b'{"accounts": 1, "active": 1, "active_window_days": 30, "email": "x@example.invalid"}'
        apps = {
            "samvision": self.entry(FakeApp(secret), "sv"),                                # extra key
            "mfe": self.entry(FakeApp(delay=fleet.TIMEOUT_S + 1), "mfe"),                  # timed out
            "gyst2": self.entry(FakeApp(status=500, body=b"boom secret"), "g2"),           # refused
            "big": self.entry(FakeApp(b"x" * 5000), "big"),
            "win": self.entry(FakeApp(json.dumps({"accounts": 1, "active": 1, "active_window_days": 7}).encode()), "win"),
            "wrongtok": self.entry(FakeApp(token="other"), "wt"),
            "perm": self.entry(FakeApp(), "perm", mode=0o644),
            "noreply": {"url": "http://127.0.0.1:1/x", "token_file": str(Path(self.tmp.name) / "perm.token")},
        }
        r = fleet.build(apps)
        self.assertEqual(r["answered"], [])
        self.assertEqual(len(r["didNotRespond"]), 8)
        self.assertEqual(r["total"]["accounts"], 0)
        blob = json.dumps(r)
        self.assertNotIn("example.invalid", blob)
        self.assertNotIn("boom", blob)
        reasons = {a["project"]: a["reason"] for a in r["apps"]}
        self.assertIn("contract", reasons["samvision"])
        self.assertEqual(reasons["perm"], "token file must be 0600")

    def test_partial_answer_names_who_answered(self):
        apps = {"samvision": self.entry(FakeApp(), "sv"), "mfe": self.entry(FakeApp(status=500), "mfe")}
        r = fleet.build(apps)
        self.assertEqual(r["answered"], ["samvision"])
        self.assertEqual(r["didNotRespond"], ["mfe"])
        self.assertEqual(r["total"]["from"], ["samvision"])

    def test_gyst_single_user_outside_the_total(self):
        apps = {"samvision": self.entry(FakeApp(), "sv"), "gyst": {"single_user": True, "container": "gyst-lifeops"}}
        r = fleet.build(apps, status_of=lambda c: "Up 22 hours (healthy)" if c == "gyst-lifeops" else None)
        self.assertEqual(r["total"]["accounts"], 12)
        self.assertEqual(r["singleUser"], [{"project": "gyst", "name": "GYST / LifeOps",
                                            "status": "single-user", "health": "healthy"}])
        self.assertNotIn("gyst", [a["project"] for a in r["apps"]])
        self.assertEqual(fleet.build(apps, status_of=lambda c: None)["singleUser"][0]["health"], "unknown")

    def test_cache_for_sixty_seconds(self):
        app = FakeApp(); apps = {"samvision": self.entry(app, "sv")}
        orig = registry.fleet_apps
        registry.fleet_apps = lambda: apps
        try:
            a = fleet.report(now=1000.0); b = fleet.report(now=1030.0)
            self.assertIs(a, b); self.assertEqual(len(app.seen), 1)
            fleet.report(now=1061.0); self.assertEqual(len(app.seen), 2)
        finally:
            registry.fleet_apps = orig

    def test_registry_entries(self):
        e = registry.fleet_apps()
        self.assertEqual(set(e), {"samvision", "mfe", "gyst"})
        self.assertTrue(e["gyst"]["single_user"])
        for k in ("samvision", "mfe"):
            self.assertTrue(e[k]["url"].startswith("http://127.0.0.1:"))

    def test_fleet_module_imports_no_shell_or_database(self):
        tree = ast.parse(Path(fleet.__file__).read_text())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0:
                names.add((n.module or "").split(".")[0])
        self.assertFalse(names & {"subprocess", "sqlite3", "psycopg", "psycopg2", "pymysql", "sqlalchemy", "os.system"})


if __name__ == "__main__":
    unittest.main()
