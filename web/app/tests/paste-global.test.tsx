/**
 * Ctrl+V outside the terminal belongs to whatever has focus: no app-wide shortcut handler
 * (the shell's, the Workspace's) may swallow it — not in a plain input, not in the command
 * palette, not in Monaco's input area.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { app, initial } from "../src/store/app";
import { AppShell } from "../src/components/Shell";
import { Workspace } from "../src/screens/Workspace";
import { state, tasks } from "./helpers";

beforeEach(() => {
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta, conn: { status: "live", lastMessageAt: Date.now(), attempt: 0 } });
  vi.spyOn(app.api, "workspaceProjects").mockResolvedValue({ projects: [{ key: "samvision", name: "SamVision", prefix: "SV",
    root: "/srv/x", exists: true, branch: "main", github: null, coordinator: null }] });
  vi.spyOn(app.api, "listDir").mockResolvedValue({ project: "samvision", path: "", crumbs: [], entries: [], truncated: false, git: false });
  vi.spyOn(app.api, "development").mockResolvedValue({ rows: [], seq: 0, gitAsOf: null, stages: [], notes: [] });
  location.hash = "#/workspace?project=samvision";
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const ctrlV = { key: "v", code: "KeyV", ctrlKey: true };

describe("Ctrl+V outside the terminal is never hijacked", () => {
  it("plain input, Monaco's input area, and the page itself keep their paste", async () => {
    render(<AppShell flush><Workspace /><input aria-label="plain" /><textarea aria-label="monaco-like" className="inputarea" /></AppShell>);
    await screen.findByLabelText("Workspace project");   // the Workspace (and its key handler) is mounted
    // fireEvent returns false when a handler called preventDefault
    expect(fireEvent.keyDown(screen.getByLabelText("plain"), ctrlV)).toBe(true);
    expect(fireEvent.keyDown(screen.getByLabelText("monaco-like"), ctrlV)).toBe(true);
    expect(fireEvent.keyDown(document.body, ctrlV)).toBe(true);
    expect(fireEvent.keyDown(document.body, { key: "V", code: "KeyV", ctrlKey: true, shiftKey: true })).toBe(true);
    expect(fireEvent.keyDown(document.body, { key: "Insert", code: "Insert", shiftKey: true })).toBe(true);
  });

  it("the command palette input keeps Ctrl+V", async () => {
    render(<AppShell flush><div /></AppShell>);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByRole("combobox");
    expect(fireEvent.keyDown(input, ctrlV)).toBe(true);
  });
});
