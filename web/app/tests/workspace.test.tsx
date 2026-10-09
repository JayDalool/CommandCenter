/**
 * Workspace contract: Developer Unlock lives in memory only, write requests
 * carry the developer session header, uploads never send the token in a URL,
 * the old Console route opens Workspace, and the editor picks languages.
 */
import { Api } from "../src/api/client";
import { setToken, clearToken } from "../src/api/auth";
import { devSession, setDevSession, developer } from "../src/api/developer";
import { parse } from "../src/lib/router";
import { NAV } from "../src/components/Shell";
import { languageOf } from "../src/workspace/Editor";
import { jsonResponse } from "./helpers";

const TOKEN = "k".repeat(43);
const DEV = "s".repeat(43);

describe("Developer Unlock", () => {
  beforeEach(() => { clearToken(); setDevSession(null); localStorage.clear(); sessionStorage.clear(); });

  it("keeps the session for this browser session only: sessionStorage, never localStorage (spec §27)", () => {
    setDevSession(DEV, 3600);
    expect(devSession()).toBe(DEV);
    expect(developer.get().active).toBe(true);
    expect(JSON.stringify({ ...localStorage })).not.toContain(DEV);
    expect(sessionStorage.getItem("ccd.dev")).toContain(DEV);
    setDevSession(null);
    expect(sessionStorage.getItem("ccd.dev")).toBeNull();
  });

  it("sends X-CCD-Developer with writes once unlocked, and drops it when ccd says it expired", async () => {
    setToken(TOKEN);
    setDevSession(DEV, 3600);
    const seen: RequestInit[] = [];
    const api = new Api(async (_u, init) => { seen.push(init!); return jsonResponse({ ok: false, error: "Developer Unlock required" }, 403); });
    await expect(api.saveFile("samvision", "a.py", "x", null)).rejects.toThrow("Developer Unlock required");
    expect((seen[0].headers as Record<string, string>)["X-CCD-Developer"]).toBe(DEV);
    expect(devSession()).toBeNull();
    expect(developer.get().active).toBe(false);
  });

  it("never puts a token in a request URL", async () => {
    setToken(TOKEN);
    setDevSession(DEV, 3600);
    const urls: string[] = [];
    const api = new Api(async (u) => { urls.push(String(u)); return jsonResponse({ entries: [] }); });
    await api.listDir("samvision", "src");
    await api.readFile("samvision", "src/a.py");
    await api.unlock("t".repeat(43)).catch(() => undefined);
    for (const u of urls) { expect(u).not.toContain(TOKEN); expect(u).not.toContain(DEV); }
  });
});

describe("navigation", () => {
  it("has one Workspace entry and no Console entry; the old route still resolves", () => {
    const ids = NAV.map((n) => n.id);
    expect(ids).toEqual(["dashboard", "workspace", "tasks", "activity", "files", "settings"]);
    expect(parse("#/console?tab=repo").screen).toBe("console");
    expect(parse("#/workspace?project=samvision&ticket=SV-056").params.get("ticket")).toBe("SV-056");
  });
});

describe("editor", () => {
  it("chooses a language from the file name", () => {
    expect(languageOf("src/a.py")).toBe("python");
    expect(languageOf("web/App.tsx")).toBe("typescript");
    expect(languageOf("Dockerfile")).toBe("dockerfile");
    expect(languageOf("notes.unknownext")).toBe("plaintext");
  });
});

describe("editor models", () => {
  it("gives every opened tab a fresh version and disposes without a mounted editor", async () => {
    const { nextVersion, disposeModel, hasModel } = await import("../src/workspace/Editor");
    const a = nextVersion(), b = nextVersion();
    expect(b).toBeGreaterThan(a);
    disposeModel("samvision:never-opened.txt");  // no editor mounted: must not throw
    expect(hasModel("samvision:never-opened.txt")).toBe(false);
  });
});
