"""Remote access over Tailscale Serve (security.remote_origins, api.Guard): ccd accepts a tailnet address only when
config.json names it exactly, never anything wider, and refuses a request that came through Tailscale Funnel."""
import unittest

from ccd import security

from .test_api import AUTH, PORT, ApiBase

TAILNET = "https://jay-server.tail1a2b3.ts.net"
REMOTE = {"host": "jay-server.tail1a2b3.ts.net", "x-ccd-token": AUTH["x-ccd-token"], "origin": TAILNET}


class RemoteOrigins(unittest.TestCase):
    def test_only_exact_https_tailnet_origins_are_accepted(self):
        ok, bad = security.remote_origins([TAILNET, " HTTPS://Jay-Server.Tail1a2b3.TS.NET ", "https://phone.tail1a2b3.ts.net"])
        self.assertEqual(ok, [TAILNET, "https://phone.tail1a2b3.ts.net"])
        self.assertEqual(bad, [])

    def test_everything_wider_or_different_is_refused(self):
        for o in ("http://jay-server.tail1a2b3.ts.net", "https://jay-server.tail1a2b3.ts.net/", "https://jay-server.tail1a2b3.ts.net:8443",
                  "https://jay-server.tail1a2b3.ts.net/api", "https://*.ts.net", "https://ts.net", "https://evil.example",
                  "https://jay-server.ts.net.evil.example", "https://user@jay-server.tail1a2b3.ts.net", "https://-x.ts.net",
                  "jay-server.tail1a2b3.ts.net", "", 7, None, {"origin": TAILNET}):
            ok, bad = security.remote_origins([o])
            self.assertEqual(ok, [], repr(o))
            self.assertEqual(len(bad), 1, repr(o))

    def test_absent_or_empty_means_none(self):
        self.assertEqual(security.remote_origins(None), ([], []))
        self.assertEqual(security.remote_origins([]), ([], []))
        self.assertEqual(security.remote_origins(TAILNET), ([TAILNET], []))

    def test_loopback_stays_and_each_origin_adds_one_host(self):
        self.assertEqual(security.allowed_hosts(PORT), {f"127.0.0.1:{PORT}", f"localhost:{PORT}"})
        self.assertEqual(security.allowed_hosts(PORT, [TAILNET]),
                         {f"127.0.0.1:{PORT}", f"localhost:{PORT}", "jay-server.tail1a2b3.ts.net"})
        self.assertEqual(security.allowed_origins(PORT, [TAILNET]),
                         {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", TAILNET})


class NotConfigured(ApiBase):
    def test_a_tailnet_address_is_refused_unless_named(self):
        self.assertEqual(self.client.get("/api/state", headers=REMOTE).status_code, 403)
        self.assertEqual(self.client.get("/api/state", headers=AUTH).status_code, 200)


class Configured(ApiBase):
    def equip(self, daemon):
        daemon.cfg["remote_origins"] = [TAILNET, "https://evil.example"]

    def setUp(self):
        with self.assertLogs("ccd", "WARNING") as logs:
            super().setUp()
        self.assertTrue(any("remote_origins entries refused" in m and "evil.example" in m for m in logs.output))

    def test_the_named_address_works_with_the_token(self):
        self.assertEqual(self.client.get("/api/state", headers=REMOTE).status_code, 200)
        self.assertEqual(self.client.get("/api/state", headers={k: v for k, v in REMOTE.items() if k != "x-ccd-token"})
                         .status_code, 401)
        self.assertEqual(self.client.get("/api/state", headers=AUTH).status_code, 200)

    def test_other_hosts_and_origins_are_still_refused(self):
        for h in ({"host": "other.tail1a2b3.ts.net"}, {"origin": "https://other.tail1a2b3.ts.net"},
                  {"origin": "http://jay-server.tail1a2b3.ts.net"}, {"host": "evil.example"}, {"origin": "https://evil.example"},
                  {"host": "jay-server.tail1a2b3.ts.net:443"}):
            self.assertEqual(self.client.get("/api/state", headers={**REMOTE, **h}).status_code, 403, h)

    def test_funnel_is_refused_on_every_address(self):
        for base in (REMOTE, AUTH):
            r = self.client.get("/api/state", headers={**base, "tailscale-funnel-request": "?1"})
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json()["error"], "not served to the public internet")
        self.assertEqual(self.client.get("/api/health", headers={**REMOTE, "tailscale-funnel-request": "?1"}).status_code, 403)

    def test_the_event_stream_works_over_the_named_address_only(self):
        with self.client.websocket_connect("/api/events", headers=REMOTE) as ws:
            self.assertIsNotNone(ws)
        from starlette.websockets import WebSocketDisconnect
        for h in ({"host": "other.tail1a2b3.ts.net"}, {"origin": "https://other.tail1a2b3.ts.net"},
                  {"tailscale-funnel-request": "?1"}):
            with self.assertRaises(WebSocketDisconnect, msg=h) as cm:
                with self.client.websocket_connect("/api/events", headers={**REMOTE, **h}) as ws:
                    ws.receive_text()
            self.assertEqual(cm.exception.code, 4403, h)


if __name__ == "__main__":
    unittest.main()
