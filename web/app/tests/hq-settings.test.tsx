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
import { developer, setDevSession } from "../src/api/developer";
import { ApiError } from "../src/api/client";
import type { DevDevice, NotifyState } from "../src/api/types";

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

  // Developer Unlock that lasts (flow contract §6): what ccd says about this session, the devices holding one, and
  // the button that ends them all. An older ccd says nothing about remembering, and nothing about devices is shown.
  describe("Security: remembered devices", () => {
    const NOW = Date.parse("2026-10-27T15:00:00Z") / 1000;
    const DEVICES: DevDevice[] = [
      { id: "d1", label: "Chrome on Windows", kind: "remember", remembered: true, createdAt: NOW - 86400, lastUsedAt: NOW - 20,
        expiresAt: NOW + 29 * 86400, current: true },
      { id: "d2", label: "Safari on iPhone", kind: "remember", remembered: true, createdAt: NOW - 5 * 86400, lastUsedAt: NOW - 3 * 3600,
        expiresAt: NOW + 25 * 86400, current: false },
      { id: "d3", label: "SSH sign-in", kind: "ssh", remembered: false, createdAt: NOW - 3600, lastUsedAt: NOW - 600,
        expiresAt: NOW + 11 * 3600, current: false },
    ];
    const status = (extra: object) => vi.spyOn(app.api, "developerStatus").mockResolvedValue({ active: false, expiresIn: null, tokenFile: null, ...extra });
    const SID = "s".repeat(43);
    afterEach(() => { act(() => setDevSession(null)); });

    it("an older ccd: no device list, and the session is said to end with a ccd restart", async () => {
      load();
      status({});
      const devices = vi.spyOn(app.api, "devices");
      const page = await show("#/settings?tab=security");
      expect(within(page).queryByRole("heading", { name: "Unlocked devices" })).toBeNull();
      expect(within(page).getByText(/8 hours in all, or a ccd restart/)).toBeInTheDocument();
      expect(devices).not.toHaveBeenCalled();
    });

    it("locked: the list is not asked for", async () => {
      load();
      status({ remembered: false });
      const devices = vi.spyOn(app.api, "devices");
      const page = await show("#/settings?tab=security");
      expect(within(page).getByRole("heading", { name: "Unlocked devices" })).toBeInTheDocument();
      expect(within(page).getByText("Not shown while locked")).toBeInTheDocument();
      expect(within(page).getByText(/Reloads, pop-outs and a ccd restart keep it/)).toBeInTheDocument();
      expect(within(page).queryByRole("button", { name: "Lock all devices…" })).toBeNull();
      expect(devices).not.toHaveBeenCalled();
    });

    it("a remembered device: says so, lists every device with this one marked, and never shows a session id", async () => {
      load();
      setDevSession(SID, 29 * 86400, true);
      status({ active: true, expiresIn: 29 * 86400, remembered: true, reenterIn: 5 * 3600 });
      vi.spyOn(app.api, "devices").mockResolvedValue({ devices: DEVICES });
      const page = await show("#/settings?tab=security");
      expect(within(page).getByText("Unlocked, remembered")).toBeInTheDocument();
      expect(within(page).getByText(/Open for another 5 hours/)).toBeInTheDocument();
      expect(within(page).queryByRole("button", { name: "Type the token…" })).toBeNull();
      expect(within(page).getByText(/30 days after this device was remembered/)).toBeInTheDocument();
      const group = within(page).getByRole("heading", { name: "Unlocked devices" }).closest("section")!;
      const rows = [...group.querySelectorAll(".hq-set-row")].map((r) => r.textContent);
      expect(rows[0]).toMatch(/^Chrome on Windows This device/);
      expect(rows[0]).toContain("Remembered for 30 days · last used just now · ends in 29 days");
      expect(rows[1]).toContain("Safari on iPhone");
      expect(rows[1]).toContain("last used 3h ago · ends in 25 days");
      expect(rows[1]).not.toContain("This device");
      expect(rows[2]).toContain("Signed in with SSH · last used 10m ago · ends in 11 hours");
      expect(page.textContent).not.toContain(SID);
    });

    it("the token is too old for terminals: a button to type it again", async () => {
      load();
      setDevSession(SID, 29 * 86400, true);
      status({ active: true, expiresIn: 29 * 86400, remembered: true, reenterIn: 0 });
      vi.spyOn(app.api, "devices").mockResolvedValue({ devices: DEVICES.slice(0, 1) });
      const page = await show("#/settings?tab=security");
      expect(within(page).getByText(/typed more than 8 hours ago/)).toBeInTheDocument();
      fireEvent.click(within(page).getByRole("button", { name: "Type the token…" }));
      await act(async () => {});
      expect(document.querySelector("[role=dialog]")).toHaveTextContent(/more than 8 hours since the developer token was typed/);
    });

    it("Lock all devices asks first, then ends every session and locks this browser", async () => {
      load();
      setDevSession(SID, 29 * 86400, true);
      status({ active: true, expiresIn: 29 * 86400, remembered: true, reenterIn: 5 * 3600 });
      vi.spyOn(app.api, "devices").mockResolvedValue({ devices: DEVICES });
      const lockAll = vi.spyOn(app.api, "lockAll").mockResolvedValue({ ok: true, ended: 3 });
      const toast = vi.spyOn(app, "toast");
      const page = await show("#/settings?tab=security");
      fireEvent.click(within(page).getByRole("button", { name: "Lock all devices…" }));
      const dialog = within(document.querySelector<HTMLElement>("[role=dialog]")!);
      fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
      expect(lockAll).not.toHaveBeenCalled();
      expect(developer.get().active).toBe(true);

      fireEvent.click(within(page).getByRole("button", { name: "Lock all devices…" }));
      fireEvent.click(within(document.querySelector<HTMLElement>("[role=dialog]")!).getByRole("button", { name: "Lock all devices" }));
      for (let i = 0; i < 3; i++) await act(async () => {});
      expect(lockAll).toHaveBeenCalledTimes(1);
      expect(developer.get().active).toBe(false);
      expect(localStorage.getItem("ccd.dev")).toBeNull();
      expect(toast).toHaveBeenCalledWith("Developer Mode locked on every device (3 sessions ended)");
      expect(within(page).getByText("Not shown while locked")).toBeInTheDocument();
    });

    it("a refused Lock all devices says so and keeps this browser unlocked", async () => {
      load();
      setDevSession(SID, 3600);
      status({ active: true, expiresIn: 3600, remembered: false, reenterIn: 3600 });
      vi.spyOn(app.api, "devices").mockResolvedValue({ devices: [] });
      vi.spyOn(app.api, "lockAll").mockRejectedValue(new ApiError(0, "ccd unreachable"));
      const toast = vi.spyOn(app, "toast");
      const page = await show("#/settings?tab=security");
      expect(within(page).getByText("Unlocked")).toBeInTheDocument();
      expect(within(page).queryByText("Terminals and file changes")).toBeNull();   // only a remembered device has that row
      fireEvent.click(within(page).getByRole("button", { name: "Lock all devices…" }));
      fireEvent.click(within(document.querySelector<HTMLElement>("[role=dialog]")!).getByRole("button", { name: "Lock all devices" }));
      for (let i = 0; i < 3; i++) await act(async () => {});
      expect(toast).toHaveBeenCalledWith("Could not lock all devices: ccd unreachable", "bad");
      expect(developer.get().active).toBe(true);
    });
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
