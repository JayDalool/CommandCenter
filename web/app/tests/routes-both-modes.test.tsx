// Every route shows the same screen with the HQ preview on as in Classic, except where HQ has its own page for the
// address (hq/pages, HQ_PAGES). HQ puts its own frame around it (sidebar, top bar, tabs: hq/frame), with the
// "HQ preview" label at the foot of its sidebar; the screen itself, inside #main, is Classic's, unchanged. The room and
// pane pop-outs have no frame in either mode, so they match whole. Navigation and its keys do not move.
import { act, cleanup, render } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { SCREENS } from "../src/lib/router";
import { NAV, loadHqFrame } from "../src/components/Shell";
import { HQ_NAV, HQ_NAV_LOW } from "../src/hq/frame/nav";
import { HQ_PAGES } from "../src/hq/pages";
import { state, tasks } from "./helpers";

const BARE = ["room", "pane"];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
  vi.stubGlobal("fetch", () => new Promise(() => {}));  // nothing answers: every screen renders from the store
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

const ids = (html: string) => html.replace(/«r[0-9a-z]+»|:r[0-9a-z]+:/g, "«id»");

/** The screen's HTML (#main), the whole window's, and what frames it. React's generated ids are numbered per render;
 *  Settings' Interface control naturally shows which mode is on, so its pressed state is left out. */
async function renderIn(route: string, ui: "classic" | "hq") {
  prefs.patch({ ui });
  location.hash = `#/${route}`;
  if (ui === "hq") await loadHqFrame();
  const view = render(<App />);
  await act(async () => {});
  const c = view.container;
  c.querySelectorAll('[aria-label="Interface"] button').forEach((b) => b.removeAttribute("aria-pressed"));
  const out = {
    screen: ids(c.querySelector("#main")?.innerHTML ?? ""),
    whole: ids(c.innerHTML),
    rail: c.querySelector(".rail") !== null,
    frame: c.querySelector(".hq-side") !== null,
    label: c.querySelector(".hq-side .hq-tag") !== null,
    anyLabel: c.querySelector(".hq-tag") !== null,
    hqPage: c.querySelector("#main > .hq-page") !== null,
  };
  view.unmount();
  return out;
}

describe("both modes", () => {
  it.each([...SCREENS])("#/%s shows the same screen", async (route) => {
    const classic = await renderIn(route, "classic");
    const hq = await renderIn(route, "hq");
    expect(classic.anyLabel).toBe(false);
    expect(classic.frame).toBe(false);
    expect(classic.hqPage).toBe(false);
    expect(hq.hqPage).toBe(route in HQ_PAGES);
    if (!(route in HQ_PAGES)) expect(hq.screen).toBe(classic.screen);
    expect(hq.screen.length).toBeGreaterThan(50);
    expect(hq.whole.length).toBeGreaterThan(200);
    if (BARE.includes(route)) {
      expect(hq.whole).toBe(classic.whole);
      expect(hq.anyLabel).toBe(false);
    } else {
      expect(classic.rail).toBe(true);
      expect({ rail: hq.rail, frame: hq.frame, label: hq.label }).toEqual({ rail: false, frame: true, label: true });
    }
  });

  it("keeps the navigation, its order and its keys", () => {
    expect(NAV.map((n) => `${n.id}:${n.key}`)).toEqual(["dashboard:1", "needs:0", "workspace:2", "tasks:3", "activity:4",
      "files:5", "settings:6"]);
  });

  it("HQ's sidebar opens the same screens with the same keys", () => {
    const classic = Object.fromEntries(NAV.map((n) => [n.id, n.key]));
    const hq = [...HQ_NAV, ...HQ_NAV_LOW];
    expect(hq.map((n) => n.id).sort()).toEqual(NAV.map((n) => n.id).sort());
    for (const n of hq) expect(`${n.id}:${n.key}`).toBe(`${n.id}:${classic[n.id]}`);
  });
});
