// SSH sign-in (server/ccd/signin.py, scripts/cc-session). CommandCenter.exe proves it is Jay with its SSH
// key login, asks the server for a one-time code, and opens http://127.0.0.1:7777/#/?signin=<code>.
// Here the page trades that code — once, within two minutes — for the ccd token and a day-long Developer
// session: nothing to paste, nothing to unlock. The code is removed from the address before anything else.
import { setToken } from "./auth";
import { setDevSession } from "./developer";

export function takeSigninCode(): string | null {
  const m = /[?&]signin=([A-Za-z0-9_-]{20,128})/.exec(location.hash);
  if (!m) return null;
  const rest = location.hash.replace(/([?&])signin=[A-Za-z0-9_-]+&?/, "$1").replace(/[?&]$/, "");
  history.replaceState(null, "", `${location.pathname}${location.search}${rest === "#/" ? "#/dashboard" : rest || "#/dashboard"}`);
  return m[1];
}

/** Redeem a code from the address, if there is one. Resolves with an error message, or null. */
export async function redeemSignin(fetchImpl: typeof fetch = (...a) => fetch(...a)): Promise<string | null> {
  const code = takeSigninCode();
  if (!code) return null;
  try {
    const res = await fetchImpl("/api/developer/redeem", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }), cache: "no-store", credentials: "omit" });
    const data = await res.json().catch(() => ({})) as { token?: string; session?: string; expiresIn?: number; error?: string };
    if (!res.ok || !data.token || !data.session) return data.error ?? `sign-in failed (HTTP ${res.status})`;
    setToken(data.token, false);
    setDevSession(data.session, data.expiresIn ?? null);
    return null;
  } catch {
    return "ccd unreachable during sign-in";
  }
}
