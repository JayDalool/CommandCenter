// An HQ page that throws shows the Classic screen at the same address, and says so (hq/frame/Frame.tsx, HqBoundary).
import { act, cleanup, render } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { loadHqFrame } from "../src/components/Shell";
import { state, tasks } from "./helpers";

vi.mock("../src/hq/pages/live", () => ({ useHqData: () => { throw new Error("page bug"); } }));

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

it("My Office falls back to the Classic Dashboard if it throws, and the frame stays", async () => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-27T15:00:00Z") });
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  vi.spyOn(app, "boot").mockResolvedValue(undefined);
  const toast = vi.spyOn(app, "toast").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta });
  prefs.patch({ ui: "hq" });
  location.hash = "#/dashboard";
  await loadHqFrame();
  render(<App />);
  await act(async () => {});
  expect(document.querySelector("#main > .hq-office")).toBeNull();
  expect(document.querySelector(".dash-top")).not.toBeNull();
  expect(document.querySelector(".hq-side")).not.toBeNull();
  expect(toast).toHaveBeenCalledWith(expect.stringMatching(/Classic screen is shown/), "bad");
});
