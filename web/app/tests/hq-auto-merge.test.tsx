// Auto-merge per repository (Jay, 2026-11-25) in HQ: Settings › Operating profiles lists every project with an
// Off/On switch for ccd merging its small low-risk PRs by itself (GET and PUT /api/auto-merge, ccd/merge_switch.py).
// On needs Developer Unlock, off does not. A repository that can never auto-merge has its switch disabled with the
// reason. An older ccd has no auto-merge route, and then the group is not shown.
import { act, cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { developer, setDevSession } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import { autoMergeHint } from "../src/hq/pages/Settings";
import type { AutoMergeProject, AutoMergeState } from "../src/api/types";
import { state, tasks } from "./helpers";

const off: AutoMergeProject = { on: false, source: "config", at: null, by: null, available: true, why: null, stopped: false };
function am(projects: Record<string, Partial<AutoMergeProject>> = {}, extra: Partial<AutoMergeState> = {}): AutoMergeState {
  return {
    projects: Object.fromEntries(["samvision", "gyst", "mfe", "gauzemate", "commandcenter"].map((k) => [k, {
      ...off, ...(k === "gauzemate" ? { available: false, why: "a client's repository: Jay merges every PR (D-024)" } : {}),
      ...projects[k] }])),
    stopped: false, problem: null, limits: { files: 10, lines: 300 }, ...extra,
  };
}

function load() {
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
const group = (main: HTMLElement) => main.querySelector<HTMLElement>("#set-auto-merge");
const row = (main: HTMLElement, name: string) => [...group(main)!.querySelectorAll<HTMLElement>(".hq-set-row")].find((r) => r.textContent!.startsWith(name))!;

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  vi.spyOn(app.api, "workMode").mockRejectedValue(new ApiError(404, "not found"));
  developer.set({ active: false, expiresAt: null, error: null });
  prefs.patch({ ui: "hq", style: "professional" });
});
afterEach(() => { cleanup(); setDevSession(null); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", style: "professional" }); });

describe("what each repository's row says", () => {
  it("off, on, stopped, and a repository that cannot auto-merge", () => {
    expect(autoMergeHint(off)).toBe("Off. Every ready PR waits for you to merge it.");
    expect(autoMergeHint({ ...off, on: true })).toBe("On. Small low-risk PRs merge once reviewed and green; the rest wait for you.");
    expect(autoMergeHint({ ...off, on: true, stopped: true })).toBe("On, but this repository's stop file is there, so nothing merges.");
    expect(autoMergeHint({ ...off, available: false, why: "the project is paused" })).toBe("Off. The project is paused.");
  });
});

describe("Settings › Operating profiles › Auto-merge", () => {
  it("is not there on an older ccd", async () => {
    vi.spyOn(app.api, "autoMerge").mockRejectedValue(new ApiError(404, "not found"));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(group(main)).toBeNull();
  });

  it("lists every repository with its switch, and a repository that cannot is disabled with the reason", async () => {
    vi.spyOn(app.api, "autoMerge").mockResolvedValue(am({ commandcenter: { on: true, source: "settings" } }));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(within(group(main)!).getByRole("heading", { name: "Auto-merge" })).toBeInTheDocument();
    expect(within(row(main, "Command Center")).getByRole("button", { name: "On" })).toHaveAttribute("aria-pressed", "true");
    expect(within(row(main, "SamVision")).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
    expect(within(row(main, "GauzeMate")).getByRole("button", { name: "On" })).toBeDisabled();
    expect(row(main, "GauzeMate")).toHaveTextContent("Off. A client's repository");
    expect(group(main)).toHaveTextContent("at most 10 files and 300 lines");
    expect(group(main)).toHaveTextContent("It never deploys.");
  });

  it("says when the stop file stops everything", async () => {
    vi.spyOn(app.api, "autoMerge").mockResolvedValue(am({}, { stopped: true }));
    load();
    const main = await show("#/settings?tab=profiles");
    expect(group(main)).toHaveTextContent("The stop file is there, so nothing merges by itself in any repository.");
  });

  it("locked: switching on asks for Developer Unlock and sends nothing; switching off goes out at once", async () => {
    vi.spyOn(app.api, "autoMerge").mockResolvedValue(am({ commandcenter: { on: true } }));
    const set = vi.spyOn(app.api, "setAutoMerge").mockResolvedValue(am());
    const asked = vi.fn();
    window.addEventListener("cc:dev-unlock", asked);
    try {
      load();
      const main = await show("#/settings?tab=profiles");
      expect(group(main)).toHaveTextContent("Switching on needs Developer Unlock.");
      fireEvent.click(within(row(main, "SamVision")).getByRole("button", { name: "On" }));
      await settle();
      expect(set).not.toHaveBeenCalled();
      expect(asked).toHaveBeenCalledTimes(1);
      fireEvent.click(within(row(main, "Command Center")).getByRole("button", { name: "Off" }));
      await waitFor(() => expect(within(row(main, "Command Center")).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true"));
      expect(set.mock.calls).toEqual([["commandcenter", false]]);
    } finally { window.removeEventListener("cc:dev-unlock", asked); }
  });

  it("unlocked: one press switches a repository on; a refusal is said", async () => {
    vi.spyOn(app.api, "autoMerge").mockResolvedValue(am());
    const set = vi.spyOn(app.api, "setAutoMerge").mockResolvedValueOnce(am({ mfe: { on: true, source: "settings" } }))
      .mockRejectedValueOnce(new ApiError(409, "gyst cannot auto-merge: this repository has no low-risk rules yet"));
    load();
    const main = await show("#/settings?tab=profiles");
    act(() => developer.set({ active: true, expiresAt: Date.now() / 1000 + 3600, error: null }));
    fireEvent.click(within(row(main, "MFE")).getByRole("button", { name: "On" }));
    await waitFor(() => expect(within(row(main, "MFE")).getByRole("button", { name: "On" })).toHaveAttribute("aria-pressed", "true"));
    expect(set.mock.calls).toEqual([["mfe", true]]);
    fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "On" }));
    await settle();
    expect(within(group(main)!).getByRole("alert")).toHaveTextContent("no low-risk rules yet");
    expect(within(row(main, "GYST")).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
  });
});
