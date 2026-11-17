// Team lead permissions (Jay, 2026-11-17): Settings › Team lead permissions lists every project with how much its
// lead approves without Jay (GET and PUT /api/lead-authority, ccd/lead_authority.py), and whether sensitive work still
// comes to him. Changing either is Jay's and needs Developer Unlock.
import { act, cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { developer, setDevSession } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import { leadHint } from "../src/hq/pages/Settings";
import type { LeadAuthorityProject, LeadAuthorityState, LeadLevel } from "../src/api/types";
import { state, tasks } from "./helpers";

const ORDER: LeadLevel[] = ["none", "low_risk", "merge", "merge_deploy", "all"];
function proj(level: LeadLevel, over: Partial<LeadAuthorityProject> = {}): LeadAuthorityProject {
  const n = ORDER.indexOf(level);
  return { level, keepSensitive: true, default: true, since: null, lowRiskPaths: false, paused: false, client: false,
    permissions: { merge_low_risk: n >= 1, merge: n >= 2, deploy: n >= 3, plan: n >= 4, ui: n >= 4 }, ...over };
}
function la(projects: Partial<Record<string, LeadAuthorityProject>> = {}, over: Partial<LeadAuthorityState> = {}): LeadAuthorityState {
  const base: Record<string, LeadAuthorityProject> = {
    samvision: proj("none"), gyst: proj("none"), mfe: proj("none"),
    gauzemate: proj("none", { client: true, paused: true }), commandcenter: proj("low_risk", { lowRiskPaths: true }),
  };
  return {
    projects: { ...base, ...projects } as Record<string, LeadAuthorityProject>,
    levels: [{ key: "none", label: "None" }, { key: "low_risk", label: "Merge low-risk" }, { key: "merge", label: "Merge all" },
      { key: "merge_deploy", label: "Merge and deploy" }, { key: "all", label: "All" }],
    mergeSwitch: { config: true, stopFile: false }, alwaysJay: ["ambiguous", "gate:plan", "legal", "product-decision"],
    sensitive: ["auth", "destructive", "financial", "migration", "personal-data", "privacy", "security"], ...over,
  };
}

function load() {
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}
const settle = async () => { for (let i = 0; i < 5; i++) await act(async () => {}); };
async function show() {
  location.hash = "#/settings?tab=leads";
  await loadHqFrame();
  render(<App />);
  await settle();
  return document.querySelector<HTMLElement>("#main")!;
}
const group = (main: HTMLElement) => main.querySelector<HTMLElement>("#set-lead-permissions")!;
const row = (main: HTMLElement, name: string, g = group(main)) => [...g.querySelectorAll<HTMLElement>(".hq-set-row")].find((r) => r.textContent!.startsWith(name))!;
const pressed = (r: HTMLElement) => within(r).getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  developer.set({ active: false, expiresAt: null, error: null });
  prefs.patch({ ui: "hq", style: "professional" });
});
afterEach(() => { cleanup(); setDevSession(null); vi.restoreAllMocks(); vi.unstubAllGlobals(); prefs.patch({ ui: "classic", style: "professional" }); });

describe("what each project's row says", () => {
  it("names what the level lets the lead do, and what still comes to Jay", () => {
    expect(leadHint(proj("none"))).toBe("You approve every merge and every live deploy.");
    expect(leadHint(proj("merge"))).toContain("Security, money, migrations and personal-data work still come to you.");
    expect(leadHint(proj("all", { keepSensitive: false }))).toBe("The lead approves plans, UI checks, merges and deploys. You only get "
      + "its questions about features. That includes security, money, migrations and personal-data work. A live project still releases on its release day.");
    expect(leadHint(proj("none", { client: true }))).toBe("A client's repository: Command Center never merges or deploys there.");
  });
});

describe("Settings › Team lead permissions", () => {
  it("lists every project at its level; low-risk only where there are low-risk paths; a client's repo stays at None", async () => {
    vi.spyOn(app.api, "leadAuthority").mockResolvedValue(la({ gyst: proj("all") }));
    load();
    const main = await show();
    expect(within(main).getByRole("heading", { name: "Team lead permissions" })).toBeInTheDocument();
    expect(pressed(row(main, "Command Center"))).toEqual(["Low-risk"]);
    expect(pressed(row(main, "GYST"))).toEqual(["All"]);
    expect(pressed(row(main, "SamVision"))).toEqual(["None"]);
    expect(within(row(main, "SamVision")).getByRole("button", { name: "Low-risk" })).toBeDisabled();
    expect(within(row(main, "Command Center")).getByRole("button", { name: "Low-risk" })).toBeEnabled();
    expect(within(row(main, "GauzeMate")).getByRole("button", { name: "Merge" })).toBeDisabled();
    const sens = main.querySelector<HTMLElement>("#set-lead-sensitive")!;
    expect(within(row(main, "GYST", sens)).getByRole("button", { name: "Ask me" })).toHaveAttribute("aria-pressed", "true");
    expect(sens.querySelectorAll(".hq-set-row")).toHaveLength(1);
    expect(group(main)).toHaveTextContent("Changing it needs Developer Unlock.");
  });

  it("says when a kill switch stops every merge", async () => {
    vi.spyOn(app.api, "leadAuthority").mockResolvedValue(la({}, { mergeSwitch: { config: false, stopFile: false } }));
    load();
    const main = await show();
    expect(within(main).getAllByRole("alert")[0]).toHaveTextContent("auto_merge: false");
  });

  it("locked: a press asks for Developer Unlock and sends nothing", async () => {
    vi.spyOn(app.api, "leadAuthority").mockResolvedValue(la());
    const set = vi.spyOn(app.api, "setLeadAuthority");
    const asked = vi.fn();
    window.addEventListener("cc:dev-unlock", asked);
    try {
      load();
      const main = await show();
      fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "All" }));
      await settle();
      expect(set).not.toHaveBeenCalled();
      expect(asked).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener("cc:dev-unlock", asked); }
  });

  it("unlocked: one press sets the level and the sensitive switch; a refusal is said", async () => {
    vi.spyOn(app.api, "leadAuthority").mockResolvedValue(la());
    const set = vi.spyOn(app.api, "setLeadAuthority").mockResolvedValueOnce(la({ gyst: proj("merge_deploy") }))
      .mockResolvedValueOnce(la({ gyst: proj("merge_deploy", { keepSensitive: false }) }))
      .mockRejectedValueOnce(new ApiError(409, "GauzeMate is a client's repository"));
    load();
    const main = await show();
    act(() => developer.set({ active: true, expiresAt: Date.now() / 1000 + 3600, error: null }));
    fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "Merge + deploy" }));
    await waitFor(() => expect(pressed(row(main, "GYST"))).toEqual(["Merge + deploy"]));
    const sens = main.querySelector<HTMLElement>("#set-lead-sensitive")!;
    fireEvent.click(within(row(main, "GYST", sens)).getByRole("button", { name: "Lead decides" }));
    await waitFor(() => expect(row(main, "GYST", sens)).toHaveTextContent("The lead decides it too."));
    fireEvent.click(within(row(main, "MFE")).getByRole("button", { name: "All" }));
    await settle();
    expect(set.mock.calls).toEqual([["gyst", { level: "merge_deploy" }], ["gyst", { keepSensitive: false }], ["mfe", { level: "all" }]]);
    expect(within(main).getByRole("alert")).toHaveTextContent("client's repository");
  });
});
