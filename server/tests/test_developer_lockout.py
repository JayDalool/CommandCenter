"""CC-032: tokenless /api/developer/redeem guesses must never lock Jay out of unlock or handoff."""
import json

from ccd import security

from .test_api import HOST, TOKEN, ApiBase

DEV = "d" * 43
BARE = {**HOST, "content-type": "application/json"}      # no ccd token, no Origin: any local uid


class RedeemNeverLocks(ApiBase):
    def equip(self, daemon):
        daemon.dev_gate = security.DeveloperGate(DEV)

    def redeem(self, code):
        return self.client.post("/api/developer/redeem", content=json.dumps({"code": code}), headers=BARE)

    def test_bare_redeem_guesses_do_not_lock_unlock_or_handoff(self):
        for i in range(10):
            self.assertEqual(self.redeem(f"guess-{i}").status_code, 403)     # refused every time, never 429
        r = self.post("/api/developer/unlock", {"token": DEV})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.post("/api/developer/handoff", {"token": DEV})
        self.assertEqual(r.status_code, 200, r.text)
        code = r.json()["code"]
        out = self.redeem(code)
        self.assertEqual(out.status_code, 200, out.text)
        self.assertEqual(out.json()["token"], TOKEN)

    def test_unlock_and_handoff_still_need_the_ccd_token(self):
        for path in ("/api/developer/unlock", "/api/developer/handoff"):
            r = self.client.post(path, content=json.dumps({"token": DEV}), headers=BARE)
            self.assertEqual(r.status_code, 401, path)
