// Team lead permissions (Jay, 2026-11-17): Settings › Team lead permissions lists every project with how much its
// lead approves without Jay (GET and PUT /api/lead-authority, ccd/lead_authority.py), and Jay's rules for what still
// comes to him at every level. Changing a level is Jay's and needs Developer Unlock.
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
  return { level, default: true, since: null, lowRiskPaths: false, paused: false, client: false,
    permissions: { merge_low_risk: n >= 1, merge: n >= 2, deploy: n >= 3, plan: n >= 4, ui: n >= 4, release: n >= 4 }, ...over };
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
    mergeSwitch: { config: true, stopFile: false },
    alwaysJay: ["ambiguous", "data-access", "data-collect", "data-deletion", "data-sharing", "data-storage", "destructive",
      "feature:major", "gate:plan", "legal", "product-decision", "spend"],
    security: ["auth", "privacy", "security"], ...over,
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
    expect(leadHint(proj("merge"))).toContain("Major features, money and personal-data changes still come to you");
    expect(leadHint(proj("all"))).toBe("The lead approves plans, UI checks, merges and deploys. You only get its questions "
      + "about features. Major features, money and personal-data changes still come to you; security work goes to the "
      + "security specialist first. A live project still releases on its release day.");
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
    expect(group(main)).toHaveTextContent("Changing it needs Developer Unlock.");
  });

  it("lists Jay's rules: what still comes to him at every level, and how security goes", async () => {
    vi.spyOn(app.api, "leadAuthority").mockResolvedValue(la({ gyst: proj("all") }));
    load();
    const main = await show();
    const rules = main.querySelector<HTMLElement>("#set-lead-rules")!;
    expect([...rules.querySelectorAll(".hq-set-row b")].map((b) => b.textContent))
      .toEqual(["Major new features", "Money", "Personal data", "Legal and product questions", "Security"]);
    expect(row(main, "Money", rules)).toHaveTextContent("more tokens after running out");
    expect(row(main, "Personal data", rules)).toHaveTextContent("How long it is kept is the lead's.");
    expect(row(main, "Security", rules)).toHaveTextContent("You are shown the conclusion");
    expect(rules).toHaveTextContent("feature:major");
    expect(rules).toHaveTextContent("labelled auth, privacy, security");
    expect(within(rules).queryAllByRole("button")).toHaveLength(0);
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

  it("unlocked: one press sets the level; a refusal is said", async () => {
    vi.spyOn(app.api, "leadAuthority").mockResolvedValue(la());
    const set = vi.spyOn(app.api, "setLeadAuthority").mockResolvedValueOnce(la({ gyst: proj("merge_deploy") }))
      .mockRejectedValueOnce(new ApiError(409, "GauzeMate is a client's repository"));
    load();
    const main = await show();
    act(() => developer.set({ active: true, expiresAt: Date.now() / 1000 + 3600, error: null }));
    fireEvent.click(within(row(main, "GYST")).getByRole("button", { name: "Merge + deploy" }));
    await waitFor(() => expect(pressed(row(main, "GYST"))).toEqual(["Merge + deploy"]));
    fireEvent.click(within(row(main, "MFE")).getByRole("button", { name: "All" }));
    await settle();
    expect(set.mock.calls).toEqual([["gyst", { level: "merge_deploy" }], ["mfe", { level: "all" }]]);
    expect(within(main).getByRole("alert")).toHaveTextContent("client's repository");
  });
});
