"""The browser client and ccd must agree on how the token travels.

The web UI is the only client of this API, and it is written in another
language, so nothing but a test keeps the two halves in step. This reads the
header name and WebSocket subprotocol out of web/app/src and drives the real
guarded app with them. If either side changes alone, this fails.

ccd's contract (server/ccd/api.py):
    HTTP        X-CCD-Token: <token>
    WebSocket   Sec-WebSocket-Protocol: ccd.v1, ccd-token.<token>
There is deliberately no `Authorization: Bearer` support.
"""
import re
import unittest
from pathlib import Path

from ccd.api import WS_PROTOCOL, WS_TOKEN_PREFIX

from .test_api import HOST, TOKEN, ApiBase

WEB = Path(__file__).resolve().parents[2] / "web" / "app" / "src"


def source(rel):
    return (WEB / rel).read_text()


class BrowserAuthContract(ApiBase):
    def test_the_client_sends_the_header_ccd_reads(self):
        """The literal header name in client.ts, used against the live app."""
        header = re.search(r'headers\["([A-Za-z0-9-]+)"\] = token', source("api/client.ts"))
        self.assertIsNotNone(header, "api/client.ts no longer sets a token header")
        name = header.group(1)
        self.assertEqual(name.lower(), "x-ccd-token")
        r = self.client.get("/api/state", headers={**HOST, name: TOKEN})
        self.assertEqual(r.status_code, 200)

    def test_the_client_names_the_subprotocol_ccd_reads(self):
        """The literal subprotocol in live.ts, used against the live app."""
        proto = re.search(r"WS_PROTOCOL = \"([^\"]+)\"", source("api/live.ts"))
        offered = re.search(r"`([A-Za-z0-9.-]+\.)\$\{token\}`", source("api/live.ts"))
        self.assertIsNotNone(proto, "api/live.ts no longer declares WS_PROTOCOL")
        self.assertIsNotNone(offered, "api/live.ts no longer offers the token as a subprotocol")
        self.assertEqual(proto.group(1), WS_PROTOCOL)
        self.assertEqual(offered.group(1), WS_TOKEN_PREFIX)
        headers = {**HOST, "sec-websocket-protocol": f"{proto.group(1)}, {offered.group(1)}{TOKEN}"}
        with self.client.websocket_connect("/api/events", headers=headers) as ws:
            self.assertEqual(ws.receive_json()["type"], "hello")
        wrong = {**HOST, "sec-websocket-protocol": f"{proto.group(1)}, bearer.{TOKEN}"}
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/api/events", headers=wrong) as ws:
                ws.receive_json()

    def test_authorization_bearer_is_not_a_way_in(self):
        """If anyone switches the client to Bearer, every request 401s. Pin it."""
        r = self.client.get("/api/state", headers={**HOST, "authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("authorization", source("api/client.ts").lower())

    def test_the_client_never_puts_the_token_in_an_http_url(self):
        joined = source("api/client.ts") + source("store/app.ts")
        self.assertNotRegex(joined, r"token=\$\{|\?token=|&token=")


if __name__ == "__main__":
    unittest.main()
