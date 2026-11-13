// HQ on a phone (hq/frame/TabBar.tsx): the tab bar's four pages and More, its counts (the same as the sidebar's and
// Jay's menu), and the More sheet: every other page by its own address, New task, Escape and focus back on More.
// Which widths show it is CSS (frame.css); e2e/hq-phone.spec.ts checks that in a browser.
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { jayQueue } from "../src/tickets/model";
import { buildDecisions } from "../src/hq/data";
import { state, tasks } from "./helpers";

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
}
const bar = () => within(document.querySelector<HTMLElement>("nav.hq-tabbar")!);
const sheet = () => document.querySelector<HTMLElement>(".hq-sheet");

beforeEach(() => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  prefs.patch({ ui: "hq", wsFocus: false });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic", wsFocus: false }); });

describe("HQ tab bar", () => {
  it("has Office, Messages, Decisions and Approvals by address, then More, with the sidebar's counts", async () => {
    load();
    await show("#/needs");
    const links = bar().getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Office", "#/dashboard"], ["Messages", "#/messages"],
      [expect.stringMatching(/Decisions/), "#/needs"], [expect.stringMatching(/Approvals/), "#/approvals"]]);
    const d = app.store.get();
    const needs = jayQueue(d.state).length, approvals = buildDecisions(d).summary.approvals;
    expect(needs).toBeGreaterThan(0);
    expect(bar().getByRole("link", { name: `Decisions, ${needs} waiting` })).toHaveAttribute("aria-current", "page");
    expect(bar().getByRole("link", { name: approvals ? `Approvals, ${approvals} waiting` : "Approvals" })).not.toHaveAttribute("aria-current");
    expect(bar().getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
  });

  it("marks More as where you are on a page outside the four", async () => {
    load();
    await show("#/settings");
    expect(bar().getAllByRole("link").filter((a) => a.hasAttribute("aria-current"))).toHaveLength(0);
    expect(bar().getByRole("button", { name: "More" })).toHaveClass("is-current");
  });

  it("More opens a sheet of every other page; a row closes it, Escape returns focus to More", async () => {
    load();
    await show("#/dashboard");
    const more = bar().getByRole("button", { name: "More" });
    more.focus();
    fireEvent.click(more);
    const dlg = within(sheet()!);
    expect(sheet()).toHaveAttribute("role", "dialog");
    expect(document.activeElement).toBe(dlg.getByRole("button", { name: "Done" }));
    expect(dlg.getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["#/agents", "#/projects", "#/tasks", "#/revenue",
      "#/budgets", "#/workspace", "#/activity", "#/files", "#/settings", "#/settings?tab=help"]);

    fireEvent.keyDown(sheet()!, { key: "Escape" });
    expect(sheet()).toBeNull();
    expect(document.activeElement).toBe(more);

    fireEvent.click(more);
    fireEvent.click(within(sheet()!).getByRole("link", { name: /^Teams/ }));
    expect(sheet()).toBeNull();
  });

  it("New task in More opens Classic's New task dialog", async () => {
    load();
    await show("#/dashboard");
    const asked = vi.fn();
    window.addEventListener("cc:new-task", asked);
    fireEvent.click(bar().getByRole("button", { name: "More" }));
    fireEvent.click(within(sheet()!).getByRole("button", { name: /^New task/ }));
    window.removeEventListener("cc:new-task", asked);
    expect(asked).toHaveBeenCalledTimes(1);
    expect(sheet()).toBeNull();
  });

  it("goes with the rest of the frame in Workspace Focus", async () => {
    load();
    prefs.patch({ wsFocus: true });
    await show("#/workspace");
    expect(document.querySelector("nav.hq-tabbar")).toBeNull();
  });
});
