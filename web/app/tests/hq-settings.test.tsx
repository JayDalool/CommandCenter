// HQ's Settings (hq/pages/Settings.tsx) on the test fixture: eleven sections, Classic's section ids still land in the
// right place (and HQ's land somewhere sensible in Classic), and the controls change only what Classic's did: this
// browser's preferences, its remembered window places and the Developer Unlock session. No demo or sample data.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { jayQueue } from "../src/tickets/model";
import { classicTab } from "../src/screens/Settings";
import { SECTIONS, settingsSection } from "../src/hq/pages/Settings";
import { popped, resetWindows, savePlace } from "../src/hq/windows/manager";
import { state, tasks } from "./helpers";
import { developer } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import type { NotifyState } from "../src/api/types";

function load() {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
}

async function show(hash: string) {
  location.hash = hash;
  await loadHqFrame();
  render(<App />);
  for (let i = 0; i < 3; i++) await act(async () => {});
  return document.querySelector<HTMLElement>("#main > .hq-settings")!;
}
const nav = (page: HTMLElement) => within(page).getByRole("navigation", { name: "Settings sections" });
const current = (page: HTMLElement) => nav(page).querySelector('[aria-current="page"] b')?.textContent;
const title = (page: HTMLElement) => page.querySelector("#hq-set-title")?.textContent;

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq", theme: "dark" });
  localStorage.clear();
  resetWindows();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", theme: "dark" }); });

describe("HQ Settings", () => {
  it("lists the eleven sections in the prototype's order, each at its own address, General first", async () => {
    load();
    const page = await show("#/settings");
    const links = within(nav(page)).getAllByRole("link");
    expect(links.map((a) => a.querySelector("b")?.textContent)).toEqual(["General", "Appearance", "Notifications",
      "Windows & monitors", "Security", "Connections", "Operating profiles", "Workers", "Audit and usage",
      "Other destinations", "Help & shortcuts"]);
    expect(links.map((a) => a.getAttribute("href"))).toEqual(SECTIONS.map((s) => `#/settings?tab=${s.id}`));
    expect(page).toHaveClass("is-index");
    expect(current(page)).toBe("General");
    expect(title(page)).toBe("General");
  });

  it("opens each section from its address", async () => {
    load();
    for (const s of SECTIONS) {
      const page = await show(`#/settings?tab=${s.id}`);
      expect(page).toHaveClass("is-detail");
      expect(current(page)).toBe(s.label);
      expect(title(page)).toBe(s.label);
      cleanup();
    }
  });

  it("opens every Classic section id in the HQ section that holds it, at that part", async () => {
    load();
    const want: [string, string, string | null][] = [["general", "General", null], ["desktop", "Connections", "desktop"],
      ["developer", "Security", "unlock"], ["connection", "Connections", "browser"], ["policies", "Operating profiles", "policies"],
      ["decisions", "Operating profiles", "decisions"], ["workers", "Workers", "workers"], ["audit", "Audit and usage", "audit"],
      ["usage", "Audit and usage", "usage"], ["import", "General", "import"], ["diagnostics", "Other destinations", null]];
    for (const [tab, label, part] of want) {
      const page = await show(`#/settings?tab=${tab}`);
      expect(current(page), tab).toBe(label);
      if (part) expect(page.querySelector(`#set-${part}`), tab).not.toBeNull();
      cleanup();
    }
    expect(settingsSection("nonsense")).toEqual({ id: "general", part: null });
  });

  it("each HQ section id opens a Classic section, and Classic's own ids are unchanged", () => {
    expect(SECTIONS.map((s) => classicTab(s.id))).toEqual(["general", "general", "general", "general", "developer",
      "connection", "policies", "workers", "audit", "diagnostics", "general"]);
    for (const t of ["general", "desktop", "developer", "connection", "policies", "decisions", "workers", "audit", "usage",
      "import", "diagnostics"]) expect(classicTab(t)).toBe(t);
    expect(classicTab(null)).toBe("general");
    expect(classicTab("nonsense")).toBe("general");
  });

  it("General switches the interface and sets the SSH host, as Classic's General does", async () => {
    load();
    const page = await show("#/settings?tab=general");
    const host = within(page).getByRole("textbox", { name: "SSH host alias used in copied commands" });
    fireEvent.change(host, { target: { value: "jay server;rm" } });
    expect(prefs.get().sshHost).toBe("jayserverrm");
    fireEvent.click(within(within(page).getByRole("group", { name: "Interface" })).getByRole("button", { name: "Classic" }));
    expect(prefs.get().ui).toBe("classic");
  });

  it("Appearance picks the theme by click or arrow keys, and the row density", async () => {
    load();
    const page = await show("#/settings?tab=appearance");
    const group = within(page).getByRole("radiogroup", { name: "Theme" });
    const radio = (n: string) => within(group).getByRole("radio", { name: new RegExp(`^${n}`) });
    expect(radio("Dark")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(radio("Light"));
    expect(prefs.get().theme).toBe("light");
    expect(radio("Light")).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(radio("Light"), { key: "ArrowRight" });
    expect(prefs.get().theme).toBe("system");
    expect(document.activeElement).toBe(radio("Match system"));
    expect(within(page).getByText("Showing now")).toBeInTheDocument();
    fireEvent.keyDown(radio("Match system"), { key: "ArrowRight" });
    expect(prefs.get().theme).toBe("dark");
    fireEvent.click(within(within(page).getByRole("group", { name: "Row density" })).getByRole("button", { name: "Compact" }));
    expect(prefs.get().density).toBe("compact");
    prefs.patch({ density: "comfortable" });
  });

  it("Notifications counts what waits from the Decisions queue", async () => {
    load();
    const page = await show("#/settings?tab=notifications");
    const n = jayQueue(app.store.get().state, undefined, app.store.get().tickets).length;
    expect(n).toBeGreaterThan(0);
    expect(within(page).getByRole("link", { name: `${n} items in Decisions` })).toHaveAttribute("href", "#/needs");
    expect(within(page).getByText("Reading the alert settings…")).toBeInTheDocument();
  });

  const NOTIFY: NotifyState = {
    settings: { slack: false, ntfy: false, quietStart: "22:00", quietEnd: "07:00", summaryAt: "07:00",
      timezone: "America/Winnipeg", replyScope: "answers_low_risk" },
    status: { slack: "off", socket: "off", ntfy: "off", lastError: null, lastSentAt: null },
    configured: { slackTokens: true, slackTokensError: null, jayMemberId: false, ntfy: true },
    channels: { cto: "cto" }, clientProjects: ["gauzemate"], slackGates: ["failure", "ui"], quietNow: false, held: 0,
  };

  it("Slack and phone show ccd's settings and what is not set up, and changes ask for Developer Unlock", async () => {
    load();
    developer.set({ active: false, expiresAt: null, error: null });
    vi.spyOn(app.api, "notify").mockResolvedValue(NOTIFY);
    const put = vi.spyOn(app.api, "setNotify").mockResolvedValue(NOTIFY);
    const asked = vi.fn();
    window.addEventListener("cc:dev-unlock", asked);
    const page = await show("#/settings?tab=notifications");
    expect(within(page).getByText("Your Slack member ID is not in config.json")).toBeInTheDocument();
    expect(within(page).getByLabelText("Quiet hours start")).toHaveValue("22:00");
    expect(within(page).getByRole("button", { name: "Send a test" })).toBeDisabled();
    fireEvent.click(within(within(page).getByRole("group", { name: "Slack" })).getByRole("button", { name: "On" }));
    expect(asked).toHaveBeenCalledTimes(1);
    expect(put).not.toHaveBeenCalled();
    window.removeEventListener("cc:dev-unlock", asked);
  });

  it("Slack and phone save one change at a time once unlocked", async () => {
    load();
    developer.set({ active: true, expiresAt: null, error: null });
    vi.spyOn(app.api, "notify").mockResolvedValue(NOTIFY);
    const put = vi.spyOn(app.api, "setNotify").mockResolvedValue({ ...NOTIFY, settings: { ...NOTIFY.settings, ntfy: true } });
    const page = await show("#/settings?tab=notifications");
    await act(async () => { fireEvent.click(within(within(page).getByRole("group", { name: "Phone alerts" })).getByRole("button", { name: "On" })); });
    expect(put).toHaveBeenCalledWith({ ntfy: true });
    expect(within(page).getByRole("button", { name: "Send a test" })).toBeEnabled();
    const end = within(page).getByLabelText("Quiet hours end");
    fireEvent.change(end, { target: { value: "06:30" } });
    await act(async () => { fireEvent.blur(end); });
    expect(put).toHaveBeenLastCalledWith({ quietEnd: "06:30" });
    developer.set({ active: false, expiresAt: null, error: null });
  });

  it("Slack and phone say so when this ccd has no alerts, or has them switched off", async () => {
    load();
    vi.spyOn(app.api, "notify").mockRejectedValueOnce(new ApiError(404, "not found"))
      .mockRejectedValueOnce(new ApiError(503, "notifications are not set up in this ccd"));
    let page = await show("#/settings?tab=notifications");
    expect(within(page).getByText("This ccd has no Slack or phone alerts yet.")).toBeInTheDocument();
    cleanup();
    page = await show("#/settings?tab=notifications");
    expect(within(page).getByText("Alerts are not set up in this ccd.")).toBeInTheDocument();
  });

  it("a time that was not saved goes back to ccd's, locked or refused", async () => {
    load();
    developer.set({ active: false, expiresAt: null, error: null });
    vi.spyOn(app.api, "notify").mockResolvedValue(NOTIFY);
    const put = vi.spyOn(app.api, "setNotify").mockRejectedValue(new ApiError(400, "quietEnd must be HH:MM (24-hour)"));
    const page = await show("#/settings?tab=notifications");
    const end = within(page).getByLabelText("Quiet hours end");
    fireEvent.change(end, { target: { value: "06:30" } });
    await act(async () => { fireEvent.blur(end); });
    expect(put).not.toHaveBeenCalled();
    expect(end).toHaveValue("07:00");
    act(() => developer.set({ active: true, expiresAt: null, error: null }));
    fireEvent.change(end, { target: { value: "06:30" } });
    await act(async () => { fireEvent.blur(end); });
    expect(put).toHaveBeenCalledWith({ quietEnd: "06:30" });
    expect(end).toHaveValue("07:00");
    expect(within(page).getByRole("status")).toHaveTextContent("quietEnd must be HH:MM (24-hour)");
    developer.set({ active: false, expiresAt: null, error: null });
  });

  it("the test says which part failed", async () => {
    load();
    developer.set({ active: true, expiresAt: null, error: null });
    const on = { ...NOTIFY, settings: { ...NOTIFY.settings, slack: true, ntfy: true } };
    vi.spyOn(app.api, "notify").mockResolvedValue(on);
    vi.spyOn(app.api, "notifyTest")
      .mockResolvedValueOnce({ ok: true, slack: false, ntfy: true, status: { ...on.status, lastError: "not_in_channel" } })
      .mockResolvedValueOnce({ ok: true, slack: true, ntfy: false, status: { ...on.status, lastError: "ntfy: HTTP 429" } })
      // An error left over from before the test (ccd clears it when a test starts; this pins that the page ignores one
      // anyway when both channels worked).
      .mockResolvedValueOnce({ ok: true, slack: true, ntfy: true, status: { ...on.status, lastError: "bot not in #gyst", lastSentAt: 1 } });
    const page = await show("#/settings?tab=notifications");
    const send = within(page).getByRole("button", { name: "Send a test" });
    const said = () => within(page).getByRole("status");
    await act(async () => { fireEvent.click(send); });
    expect(said()).toHaveTextContent("Slack message failed. Phone push sent. Error: not_in_channel");
    await act(async () => { fireEvent.click(send); });
    expect(said()).toHaveTextContent("Slack message sent. Phone push failed. Error: ntfy: HTTP 429");
    await act(async () => { fireEvent.click(send); });
    expect(said()).toHaveTextContent(/^Slack message sent\. Phone push sent\.$/);
    expect(said()).toHaveClass("t-ok");
    developer.set({ active: false, expiresAt: null, error: null });
  });

  it("the reply rule is built from ccd's gates and names the client projects", async () => {
    load();
    vi.spyOn(app.api, "notify").mockResolvedValue(NOTIFY);
    const page = await show("#/settings?tab=notifications");
    const gauze = app.store.get().state!.projectsConfig.find((p) => p.key === "gauzemate")?.name ?? "gauzemate";
    expect(within(page).getByText(`Answers, plus clearing a blocker or accepting a UI review. Never a plan, merge or deploy. ${gauze} is a client project: replies there are passed on as text and never answer or approve.`)).toBeInTheDocument();
  });

  it("Windows lists pop-outs with Return here, and forgets the remembered places", async () => {
    load();
    savePlace("needs", { x: 1920, y: 0, w: 1280, h: 900 });
    popped.set({ projects: { at: Date.now(), place: { x: 0, y: 0, w: 1200, h: 800 } } });
    const page = await show("#/settings?tab=windows");
    const own = within(page).getByRole("region", { name: "In their own windows" });
    expect(within(own).getByText("Company")).toBeInTheDocument();
    fireEvent.click(within(own).getByRole("button", { name: "Return here" }));
    expect(popped.get()).toEqual({});
    expect(within(own).getByText("No page is in its own window")).toBeInTheDocument();

    const places = within(page).getByRole("region", { name: "Remembered places" });
    expect(within(places).getByText("1280 × 900 at 1920, 0")).toBeInTheDocument();
    fireEvent.click(within(places).getByRole("button", { name: "Forget" }));
    expect(localStorage.getItem("cc.hq.windows")).toBeNull();
    expect(within(places).getByText("None yet")).toBeInTheDocument();
    expect(within(page).getByText("Not in this browser")).toBeInTheDocument();   // jsdom has no Window Management API
  });

  it("Security opens the Unlock dialog, which asks for the token itself", async () => {
    load();
    const page = await show("#/settings?tab=security");
    expect(within(page).getByText("Locked")).toBeInTheDocument();
    fireEvent.click(within(page).getByRole("button", { name: "Unlock…" }));
    await act(async () => {});
    expect(document.querySelector("[role=dialog]")).not.toBeNull();
  });

  it("Help lists the digit keys from the sidebar, and no section shows demo or sample data", async () => {
    load();
    let page = await show("#/settings?tab=help");
    expect(within(page).getByText(/1 My Office · 2 Workspace · 3 Engineering · 4 Activity · 5 Files · 6 Settings & more · 0 Decisions/))
      .toBeInTheDocument();
    cleanup();
    for (const s of SECTIONS) {
      page = await show(`#/settings?tab=${s.id}`);
      expect(page.textContent, s.id).not.toMatch(/\b(demo|sample|prototype|mock)\b/i);
      cleanup();
    }
  });
});
