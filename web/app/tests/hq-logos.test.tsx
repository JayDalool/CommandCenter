// Project logos (hq/logos.tsx, Settings › Appearance › Project logos; ccd/hq.py). ccd lists which projects have one
// and serves the bytes; the page shows each from one blob: URL, changes one only with Developer Unlock, and shows
// nothing in its place for a project that has none.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { developer } from "../src/api/developer";
import { Api, ApiError } from "../src/api/client";
import { setToken, clearToken } from "../src/api/auth";
import { logos, refreshLogos, resetLogos } from "../src/hq/logos";
import type { ChatConversation, ChatOverview, ProjectLogo } from "../src/api/types";
import { ev, jsonResponse, state, tasks } from "./helpers";

const meta = (sha: string, mime = "image/png"): ProjectLogo => ({ mime, sha256: sha, updatedAt: 1794549789 });
const conv = (id: string, name: string, kind: "cto" | "project" = "project"): ChatConversation => ({ id, name, kind, unread: 0, waiting: 0, last: null,
  nudges: { count: 0, lastAt: null }, lead: { name: id, state: "ready", status: "idle", running: true, idle: true, paused: false } });
const OVERVIEW: ChatOverview = { canStart: true, unread: 0, limits: { text: 16000, fileBytes: 20 << 20, filesPerMessage: 10 },
  conversations: [conv("cto", "CTO", "cto"), conv("samvision", "SamVision"), conv("gyst", "GYST")] };

let list: Record<string, ProjectLogo>;
let made: string[], revoked: string[];

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-13T09:30:00") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}
const settle = async () => { for (let i = 0; i < 5; i++) await act(async () => {}); };
async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  await settle();
  return document.querySelector<HTMLElement>("#main")!;
}
const shown = (el: ParentNode) => [...el.querySelectorAll<HTMLImageElement>("img.hq-logo")].map((i) => `${i.dataset.project} ${i.getAttribute("src")}`);
const png = (name = "logo.png", size = 2048, type = "image/png") => new File([new Uint8Array(size)], name, { type });

beforeEach(() => {
  resetLogos();
  list = { samvision: meta("a".repeat(64)), gauzemate: meta("b".repeat(64), "image/webp") };
  made = []; revoked = [];
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  vi.spyOn(app.api, "logos").mockImplementation(async () => JSON.parse(JSON.stringify(list)));
  vi.spyOn(app.api, "logoBlob").mockImplementation(async (_p, mime) => new Blob([new Uint8Array(4)], { type: mime }));
  vi.spyOn(app.api, "chat").mockResolvedValue(OVERVIEW);
  URL.createObjectURL = vi.fn((b: Blob) => { const u = `blob:${made.length + 1}:${b.type}`; made.push(u); return u; });
  URL.revokeObjectURL = vi.fn((u: string) => { revoked.push(u); });
  developer.set({ active: false, expiresAt: null, error: null });
  prefs.patch({ ui: "hq", style: "professional" });
});
afterEach(() => { cleanup(); resetLogos(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional" }); });

describe("the logo list", () => {
  it("makes one blob per logo, of the type ccd stored, and keeps it while the sha is the same", async () => {
    await refreshLogos();
    expect(app.api.logoBlob).toHaveBeenCalledTimes(2);
    expect(logos.get()).toMatchObject({ state: "ok", urls: { samvision: "blob:1:image/png", gauzemate: "blob:2:image/webp" } });
    await refreshLogos();
    expect(app.api.logoBlob).toHaveBeenCalledTimes(2);
    expect(revoked).toEqual([]);

    // one replaced, one removed: only the changed one is fetched again, and the two old pictures are let go
    list = { samvision: meta("c".repeat(64), "image/jpeg") };
    await refreshLogos();
    expect(app.api.logoBlob).toHaveBeenCalledTimes(3);
    expect(logos.get().urls).toEqual({ samvision: "blob:3:image/jpeg" });
    expect(revoked.sort()).toEqual(["blob:1:image/png", "blob:2:image/webp"]);
  });

  it("shows only the three picture types, and no logo for one whose bytes cannot be read", async () => {
    list = { samvision: meta("a".repeat(64), "image/svg+xml"), gyst: meta("d".repeat(64), "text/html"), mfe: meta("e".repeat(64)), gauzemate: meta("b".repeat(64)) };
    vi.mocked(app.api.logoBlob).mockImplementation(async (p, mime) => { if (p === "mfe") throw new ApiError(404, "gone"); return new Blob([], { type: mime }); });
    await refreshLogos();
    expect(Object.keys(logos.get().urls)).toEqual(["gauzemate"]);
    expect(app.api.logoBlob).not.toHaveBeenCalledWith("samvision", expect.anything());
  });

  it("a server without the route shows none; a later failure keeps what is showing", async () => {
    vi.mocked(app.api.logos).mockRejectedValueOnce(new ApiError(404, "not found"));
    await refreshLogos();
    expect(logos.get()).toMatchObject({ state: "none", urls: {} });
    resetLogos();
    await refreshLogos();
    vi.mocked(app.api.logos).mockRejectedValueOnce(new ApiError(0, "ccd unreachable"));
    await refreshLogos();
    expect(logos.get()).toMatchObject({ state: "ok", urls: { samvision: expect.stringMatching(/^blob:/) } });
    expect(revoked).toEqual([]);
  });

  it("asks ccd with the token, uploads raw bytes with the Developer session, and removes with a JSON DELETE", async () => {
    setToken("a".repeat(43));
    const calls: [string, string, Record<string, string>, unknown][] = [];
    const api = new Api(async (u, i) => { calls.push([i?.method ?? "GET", String(u), i!.headers as Record<string, string>, i?.body]); return jsonResponse({ ok: true }); });
    await api.logos();
    expect((await api.logoBlob("samvision", "image/png")).type).toBe("image/png");
    const file = png();
    await api.logoPut("samvision", file);
    await api.logoRemove("samvision");
    expect(calls.map(([m, u]) => `${m} ${u}`)).toEqual(["GET /api/projects/logos", "GET /api/projects/samvision/logo",
      "PUT /api/projects/samvision/logo", "DELETE /api/projects/samvision/logo"]);
    expect(calls.every(([, u, h]) => h["X-CCD-Token"] === "a".repeat(43) && !u.includes("a".repeat(43)))).toBe(true);
    expect(calls[2][2]["Content-Type"]).toBe("application/octet-stream");
    expect(calls[2][3]).toBe(file);
    expect([calls[3][2]["Content-Type"], calls[3][3]]).toEqual(["application/json", "{}"]);
    const refused = new Api(async () => jsonResponse({ ok: false, error: "not an image ccd accepts" }, 415));
    await expect(refused.logoPut("samvision", file)).rejects.toMatchObject({ status: 415, message: "not an image ccd accepts" });
    clearToken();
  });
});

describe("logos on the pages", () => {
  it("My Office and Teams show a project's logo beside its name, and nothing for a project without one", async () => {
    load();
    let main = await show("#/dashboard");
    const card = (name: string) => [...main.querySelectorAll<HTMLElement>(".hq-proj")].find((c) => c.querySelector("b")?.textContent === name)!;
    expect(shown(card("SamVision"))).toEqual(["samvision blob:1:image/png"]);
    expect(card("SamVision").querySelector("img")).toHaveAttribute("alt", "");
    expect(shown(card("GYST"))).toEqual([]);
    // one list and one blob per logo, however many places show it
    expect(app.api.logos).toHaveBeenCalledTimes(1);
    expect(app.api.logoBlob).toHaveBeenCalledTimes(2);
    cleanup();

    main = await show("#/agents");
    expect(shown(main.querySelector(".hq-teams")!)).toEqual(expect.arrayContaining(["samvision blob:1:image/png", "gauzemate blob:2:image/webp"]));
    expect(app.api.logos).toHaveBeenCalledTimes(1);
  });

  it("Messages shows the logo in place of the two letters, the lead's face in Childish mode, and letters when there is no logo", async () => {
    load();
    const main = await show("#/messages");
    const rows = () => within(within(main).getByRole("navigation", { name: "Conversations" })).getAllByRole("button");
    expect(rows().map((r) => r.querySelector(".hq-chat-av")?.textContent ?? shown(r)[0])).toEqual(["CTO", "samvision blob:1:image/png", "GY"]);
    act(() => prefs.patch({ style: "childish" }));
    expect(rows().every((r) => r.querySelector(".hq-face") && !r.querySelector("img.hq-logo, .hq-chat-av"))).toBe(true);
  });

  it("reloads the list when ccd says a logo changed", async () => {
    load();
    const main = await show("#/dashboard");
    list = { ...list, gyst: meta("f".repeat(64)) };
    act(() => app.store.set((d) => ({ ...d, activity: [ev(970, "logo.changed", { project: "gyst" }), ...d.activity] })));
    await settle();
    expect(app.api.logos).toHaveBeenCalledTimes(2);
    expect(shown(main.querySelector(".hq-office-projects")!)).toContain("gyst blob:3:image/png");
  });
});

describe("Settings › Appearance › Project logos", () => {
  const group = (main: HTMLElement) => main.querySelector<HTMLElement>("#set-logos")!;
  const input = (main: HTMLElement, name: string | RegExp) => within(group(main)).getByLabelText(name) as HTMLInputElement;

  it("lists every project with what it has, and a locked browser gets the Unlock dialog instead of a change", async () => {
    load();
    const main = await show("#/settings?tab=appearance");
    const rows = [...group(main).querySelectorAll<HTMLElement>(".hq-set-row")];
    expect(rows).toHaveLength(5);
    const sv = rows.find((r) => r.textContent!.includes("SamVision"))!;
    expect(sv).toHaveTextContent(/PNG, added \w+ \d+/);
    expect(shown(sv)).toEqual(["samvision blob:1:image/png"]);
    expect(rows.find((r) => r.textContent!.includes("GYST"))).toHaveTextContent("No logo");
    expect(group(main)).toHaveTextContent("Changing one needs Developer Unlock.");

    const put = vi.spyOn(app.api, "logoPut"), remove = vi.spyOn(app.api, "logoRemove");
    const asked = vi.fn();
    window.addEventListener("cc:dev-unlock", asked);
    expect(fireEvent.click(input(main, "Replace the SamVision logo"))).toBe(false);   // the file dialog does not open
    fireEvent.click(within(group(main)).getByRole("button", { name: "Remove the SamVision logo" }));
    fireEvent.change(input(main, "Replace the SamVision logo"), { target: { files: [png()] } });   // dropped on it
    expect(asked).toHaveBeenCalledTimes(3);
    expect(put).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
    window.removeEventListener("cc:dev-unlock", asked);
  });

  it("unlocked: uploads the chosen picture, shows ccd's answer, and removes", async () => {
    load();
    developer.set({ active: true, expiresAt: null, error: null });
    const main = await show("#/settings?tab=appearance");
    const file = png("gyst.png");
    const put = vi.spyOn(app.api, "logoPut").mockImplementation(async (p) => { list = { ...list, [p]: meta("9".repeat(64)) }; return { ok: true, ...list[p] }; });
    expect(fireEvent.click(input(main, /^Choose the GYST/))).toBe(true);
    fireEvent.change(input(main, /^Choose the GYST/), { target: { files: [file] } });
    await settle();
    expect(put).toHaveBeenCalledWith("gyst", file);
    expect(shown(group(main))).toContain("gyst blob:3:image/png");
    expect(within(group(main)).getByLabelText(/^Replace the GYST/)).toBeInTheDocument();

    const remove = vi.spyOn(app.api, "logoRemove").mockImplementation(async (p) => { const { [p]: _gone, ...rest } = list; list = rest; return { ok: true }; });
    fireEvent.click(within(group(main)).getByRole("button", { name: /^Remove the GYST/ }));
    await settle();
    expect(remove).toHaveBeenCalledWith("gyst");
    expect(shown(group(main)).some((x) => x.startsWith("gyst "))).toBe(false);
    // the Remove button is gone with the logo, so focus goes to the row's own picker
    expect(document.activeElement).toBe(input(main, /^Choose the GYST/));
  });

  it("stops a file ccd would refuse before sending it, and shows ccd's own refusal when it comes", async () => {
    load();
    developer.set({ active: true, expiresAt: null, error: null });
    const main = await show("#/settings?tab=appearance");
    const put = vi.spyOn(app.api, "logoPut").mockRejectedValue(new ApiError(415, "PNG, JPEG or WebP only"));
    const pick = (f: File) => { fireEvent.change(input(main, /^Choose the GYST/), { target: { files: [f] } }); };
    pick(png("logo.svg", 100, "image/svg+xml"));
    expect(within(group(main)).getByRole("alert")).toHaveTextContent("Choose a PNG, JPEG or WebP image.");
    pick(png("big.png", 600 * 1024));
    expect(within(group(main)).getByRole("alert")).toHaveTextContent("That image is 600 KB. The limit is 512 KB.");
    expect(put).not.toHaveBeenCalled();
    pick(png("renamed.png"));
    await settle();
    expect(put).toHaveBeenCalledTimes(1);
    expect(within(group(main)).getByRole("alert")).toHaveTextContent("PNG, JPEG or WebP only");
  });

  it("says so on a server that has no logos yet", async () => {
    vi.mocked(app.api.logos).mockRejectedValue(new ApiError(404, "not found"));
    load();
    const main = await show("#/settings?tab=appearance");
    expect(main).toHaveTextContent("This server does not have project logos yet");
    expect(main.querySelector("#set-logos input[type=file]")).toBeNull();
  });
});
