// Every route renders the same screen with the HQ preview on as in Classic: in Gate 0 the only difference is the
// "HQ preview" label at the foot of the navigation rail (none in the room and pane pop-outs, which have no rail).
// Navigation and its keys do not move.
import { act, cleanup, render } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { SCREENS } from "../src/lib/router";
import { NAV } from "../src/components/Shell";
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

/** The route's HTML with the label taken out, and whether there was one. Settings' Interface control naturally shows
 *  which mode is on, so its pressed state is left out too. React's generated ids are numbered per render. */
async function renderIn(route: string, ui: "classic" | "hq") {
  prefs.patch({ ui });
  location.hash = `#/${route}`;
  const view = render(<App />);
  await act(async () => {});
  const tag = view.container.querySelector(".hq-tag");
  tag?.remove();
  view.container.querySelectorAll('[aria-label="Interface"] button').forEach((b) => b.removeAttribute("aria-pressed"));
  const html = view.container.innerHTML.replace(/«r[0-9a-z]+»|:r[0-9a-z]+:/g, "«id»");
  view.unmount();
  return { html, label: tag !== null };
}

describe("both modes", () => {
  it.each([...SCREENS])("#/%s renders the same screen", async (route) => {
    const classic = await renderIn(route, "classic");
    const hq = await renderIn(route, "hq");
    expect(classic.label).toBe(false);
    expect(hq.label).toBe(!BARE.includes(route));
    expect(hq.html).toBe(classic.html);
    expect(hq.html.length).toBeGreaterThan(200);
  });

  it("keeps the navigation, its order and its keys", () => {
    expect(NAV.map((n) => `${n.id}:${n.key}`)).toEqual(["dashboard:1", "needs:0", "workspace:2", "tasks:3", "activity:4",
      "files:5", "settings:6"]);
  });
});
