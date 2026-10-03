/**
 * The browser client's half of the ccd auth contract, pinned.
 *
 * ccd reads the token from the `X-CCD-Token` header (HTTP) or the
 * `ccd-token.<token>` subprotocol (WebSocket) — see server/ccd/api.py. It never
 * reads `Authorization`, and the token must never reach a URL. The Connect
 * screen must also name the token file of the ccd that served the page: the dev
 * preview and the live daemon have different tokens, and offering the wrong file
 * produces "ccd refused that token." from a client that is otherwise correct.
 *
 * @vitest-environment-options { "url": "http://127.0.0.1:7788/" }
 */
import { render, screen } from "@testing-library/react";
import { Api } from "../src/api/client";
import { setToken, clearToken } from "../src/api/auth";
import { Live, WS_PROTOCOL } from "../src/api/live";
import { commands, tokenFile, servedPort, prefs, LIVE_TOKEN_FILE, DEV_TOKEN_FILE } from "../src/lib/prefs";
import { Connect } from "../src/screens/Connect";
import { app, initial } from "../src/store/app";
import { FakeSocket, jsonResponse } from "./helpers";

const TOKEN = "k".repeat(43);

describe("ccd auth contract: HTTP", () => {
  beforeEach(() => clearToken());

  it("authenticates with X-CCD-Token and never with Authorization", async () => {
    setToken(TOKEN);
    const seen: [string, RequestInit][] = [];
    const api = new Api(async (u, init) => { seen.push([String(u), init!]); return jsonResponse({ seq: 1 }); });
    await api.state();
    await api.comment("CC-001", "hello");
    for (const [url, init] of seen) {
      const headers = init.headers as Record<string, string>;
      expect(headers["X-CCD-Token"]).toBe(TOKEN);
      expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("authorization");
      expect(url).not.toContain(TOKEN);
      expect(url).not.toContain("token=");
      expect(init.credentials).toBe("omit");
    }
  });

  it("sends no token header at all when there is none to send", async () => {
    let init: RequestInit | undefined;
    const api = new Api(async (_u, i) => { init = i; return jsonResponse({ ok: false, error: "token required" }, 401); });
    await expect(api.state()).rejects.toMatchObject({ status: 401 });
    expect(Object.keys(init!.headers as Record<string, string>)).toEqual([]);
  });
});

describe("ccd auth contract: WebSocket", () => {
  beforeEach(() => { FakeSocket.reset(); vi.useFakeTimers(); });
  afterEach(() => vi.useRealTimers());

  it("offers the token as a subprotocol, not in the URL", () => {
    const live = new Live({ onEvent: () => {}, onLost: () => {}, onStatus: () => {} },
      { token: () => TOKEN, WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
        url: "ws://127.0.0.1:7788/api/events" });
    live.start(7);
    const s = FakeSocket.last();
    expect(s.protocols).toEqual([WS_PROTOCOL, `ccd-token.${TOKEN}`]);
    expect(s.url).not.toContain(TOKEN);
    expect(s.url).not.toContain("token=");
    live.stop();
  });
});

describe("Connect names the token file of the ccd that served the page", () => {
  beforeEach(() => { app.store.set({ ...initial, auth: "needed" }); prefs.patch({ sshHost: "jay-server" }); });

  it("the preview on 7788 asks for the dev token, not the live one", () => {
    expect(servedPort()).toBe("7788");
    render(<Connect />);
    const text = screen.getByLabelText("ccd token").closest("form")!.textContent ?? "";
    expect(text).toContain(`cat ${DEV_TOKEN_FILE}`);
    expect(text).not.toContain(LIVE_TOKEN_FILE);
    expect(text).toContain("-L 7788:127.0.0.1:7788");
  });

  it("the live daemon on 7777 asks for the live token", () => {
    expect(tokenFile("7777")).toBe(LIVE_TOKEN_FILE);
    expect(tokenFile("7788")).toBe(DEV_TOKEN_FILE);
    expect(tokenFile("5173")).toBe(DEV_TOKEN_FILE);
    expect(commands.token("jay-server", "7777")).toBe(`ssh jay-server cat ${LIVE_TOKEN_FILE} | clip`);
    expect(commands.tunnel("jay-server", "7777")).toBe("ssh -N -L 7777:127.0.0.1:7777 jay-server");
  });
});
