/**
 * The terminal dock after the cleanup: Claude · Project · Server, browser terminals by default,
 * Windows Terminal only under ⋯, and the Claude tab following ccd's one coordinator resolver
 * (ready → attach, found → Adopt, multiple → pick, none → say so). xterm is stubbed.
 */
import { render, screen, within, fireEvent, waitFor, act } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("../src/workspace/Editor", () => ({
  CodeEditor: () => <div />, disposeModel: () => {}, nextVersion: () => 1, revealLine: () => {}, hasModel: () => false, languageOf: () => "plaintext",
}));
vi.mock("../src/workspace/Terminal", () => ({
  TerminalView: ({ name, info, menu }: { name: string; info?: React.ReactNode; menu?: { label: string; href?: string; hidden?: boolean }[] }) =>
    <div data-testid="term" data-name={name}>
      <span data-testid="info">{info}</span>
      {(menu ?? []).filter((m) => !m.hidden).map((m) => <a key={m.label} data-testid="menu" href={m.href}>{m.label}</a>)}
    </div>,
}));

import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { Workspace, workspaceTabs } from "../src/screens/Workspace";
import { developer } from "../src/api/developer";
import { state, tasks } from "./helpers";
import type { Coordinator } from "../src/api/types";

const PROJECTS = [
  { key: "samvision", name: "SamVision", prefix: "SV", root: "/srv/server/apps/samvisionai", exists: true, branch: "main", github: null, coordinator: null },
  { key: "gyst", name: "GYST / LifeOps", prefix: "GYST", root: "/srv/server/repos/gyst-lifeops", exists: true, branch: "master", github: null, coordinator: null },
];

function setCoord(key: string, c: Partial<Coordinator>) {
  const st = app.store.get().state!;
  app.store.patch({ state: { ...st, coordinators: { ...st.coordinators, [key]: { name: key, paneId: null, status: "offline", canonical: false, ...c } } } });
}

beforeEach(() => {
  vi.restoreAllMocks();
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true, taskProjects: t.projects, meta: t.meta });
  prefs.patch({ wsSide: "explorer", wsExplorerOpen: true, wsTermOpen: true, wsMax: "none", consoleTab: "claude" });
  workspaceTabs.set(() => ({ tabs: [], views: [], active: null }));
  vi.spyOn(app.api, "workspaceProjects").mockResolvedValue({ projects: PROJECTS });
  vi.spyOn(app.api, "listDir").mockResolvedValue({ project: "samvision", path: "", crumbs: [], truncated: false, git: true, entries: [] });
  developer.set({ active: true } as never);
});

async function open(hash: string) {
  location.hash = hash;
  render(<Workspace />);
  await screen.findByRole("navigation", { name: "Activity bar" });
}
const terms = () => screen.queryAllByTestId("term").map((t) => t.getAttribute("data-name"));

describe("Claude tab follows the one resolver", () => {
  it("ready: attaches the existing coordinator, compact header, Windows Terminal only under ⋯", async () => {
    setCoord("samvision", { state: "ready", paneId: "wE:p2", status: "idle", name: "samvision", candidates: [] });
    await open("#/workspace?project=samvision&tab=claude");
    expect(terms()).toEqual(["claude:SV"]);
    expect(screen.getByTestId("info").textContent).toMatch(/^samvision · \S+ · idle$/);
    const menu = screen.getAllByTestId("menu");
    expect(menu.map((m) => m.textContent)).toEqual(["Open in Windows Terminal", "Show in herdr"]);
    expect(menu[0].getAttribute("href")).toBe("commandcenter://terminal/claude?project=SV");
    for (const gone of ["Mirror", "Read now", "Open native terminal", "Browser shell instead", "Coordinator", "Pane", "Session"])
      expect(screen.queryByText(gone)).toBeNull();
  });

  it("blocked shows a small BLOCKED tag", async () => {
    setCoord("samvision", { state: "ready", paneId: "wE:p2", status: "blocked", candidates: [] });
    await open("#/workspace?project=samvision&tab=claude");
    expect(within(screen.getByTestId("info")).getByText("BLOCKED")).toBeInTheDocument();
  });

  it("found: says COORDINATOR FOUND (never 'no coordinator'), Adopt binds it, then the terminal attaches", async () => {
    setCoord("gyst", { state: "found", candidates: [{ paneId: "w9:p1", sessionId: "4de6de1b-3cc5-4846-9382-3f5a361bec11", status: "idle" }] });
    const adopt = vi.spyOn(app.api, "adoptCoordinator").mockResolvedValue({ ok: true } as never);
    await open("#/workspace?project=gyst&tab=claude");
    expect(screen.getByText("COORDINATOR FOUND")).toBeInTheDocument();
    expect(screen.queryByText(/NO COORDINATOR/)).toBeNull();
    expect(terms()).toEqual([]);                                  // nothing attaches on cwd alone
    fireEvent.click(screen.getByRole("button", { name: "Adopt" }));
    await waitFor(() => expect(adopt).toHaveBeenCalledWith("gyst", "4de6de1b-3cc5-4846-9382-3f5a361bec11"));
    act(() => setCoord("gyst", { state: "ready", paneId: "w9:p1", status: "idle", candidates: [] }));  // the next snapshot
    expect(terms()).toEqual(["claude:GYST"]);
  });

  it("a successful Adopt keeps the button disabled, so a double click sends one request", async () => {
    setCoord("gyst", { state: "found", candidates: [{ paneId: "w9:p1", sessionId: "4de6de1b-3cc5-4846-9382-3f5a361bec11", status: "idle" }] });
    vi.spyOn(app, "action").mockResolvedValue(true);
    await open("#/workspace?project=gyst&tab=claude");
    const btn = screen.getByRole("button", { name: "Adopt" });
    fireEvent.click(btn);
    await waitFor(() => expect(btn).toBeDisabled());
    fireEvent.click(btn);
    expect(app.action).toHaveBeenCalledTimes(1);
  });

  it("a failed Adopt re-enables the button", async () => {
    setCoord("gyst", { state: "found", candidates: [{ paneId: "w9:p1", sessionId: "4de6de1b-3cc5-4846-9382-3f5a361bec11", status: "idle" }] });
    vi.spyOn(app, "action").mockResolvedValue(false);
    await open("#/workspace?project=gyst&tab=claude");
    const btn = screen.getByRole("button", { name: "Adopt" });
    fireEvent.click(btn);
    await waitFor(() => expect(app.action).toHaveBeenCalled());
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("found while Developer Mode is locked asks to unlock instead of adopting", async () => {
    developer.set({ active: false } as never);
    setCoord("gyst", { state: "found", candidates: [{ paneId: "w9:p1", sessionId: "4de6de1b-3cc5-4846-9382-3f5a361bec11", status: "idle" }] });
    const adopt = vi.spyOn(app.api, "adoptCoordinator");
    const unlock = vi.fn();
    window.addEventListener("cc:dev-unlock", unlock);
    await open("#/workspace?project=gyst&tab=claude");
    fireEvent.click(screen.getByRole("button", { name: "Adopt" }));
    window.removeEventListener("cc:dev-unlock", unlock);
    expect(unlock).toHaveBeenCalled();
    expect(adopt).not.toHaveBeenCalled();
  });

  it("multiple: lists the sessions and Jay picks one", async () => {
    setCoord("gyst", { state: "multiple", candidates: [
      { paneId: "w9:p1", sessionId: "aaaaaaaa-0000-0000-0000-000000000001", status: "idle" },
      { paneId: "wB:p1", sessionId: "bbbbbbbb-0000-0000-0000-000000000002", status: "working" }] });
    const adopt = vi.spyOn(app.api, "adoptCoordinator").mockResolvedValue({ ok: true } as never);
    await open("#/workspace?project=gyst&tab=claude");
    expect(screen.getByText("MULTIPLE CLAUDE SESSIONS")).toBeInTheDocument();
    const pick = screen.getByRole("list", { name: "Choose the coordinator" });
    expect(within(pick).getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(within(pick).getAllByRole("button", { name: "Use this one" })[1]);
    await waitFor(() => expect(adopt).toHaveBeenCalledWith("gyst", "bbbbbbbb-0000-0000-0000-000000000002"));
    expect(terms()).toEqual([]);
  });

  it("none: NO COORDINATOR, nothing attaches, nothing is started", async () => {
    setCoord("gyst", { state: "none", candidates: [] });
    const adopt = vi.spyOn(app.api, "adoptCoordinator");
    await open("#/workspace?project=gyst&tab=claude");
    expect(screen.getByText("NO COORDINATOR")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adopt" })).toBeNull();
    expect(terms()).toEqual([]);
    expect(adopt).not.toHaveBeenCalled();
  });
});

describe("Project and Server open straight into a browser terminal", () => {
  it("Project: repo:<PREFIX> rooted in the project, native only under ⋯", async () => {
    await open("#/workspace?project=samvision&tab=repo");
    expect(terms()).toContain("repo:SV");
    expect(screen.getByTestId("info").textContent).toBe("/srv/server/apps/samvisionai · main");
    expect(screen.getAllByTestId("menu").map((m) => [m.textContent, m.getAttribute("href")]))
      .toEqual([["Open in Windows Terminal", "commandcenter://terminal/repo?project=SV"]]);
    expect(screen.queryByText("RECOMMENDED")).toBeNull();
    expect(screen.queryByRole("button", { name: "Browser shell instead" })).toBeNull();
  });

  it("Server: the server terminal, native only under ⋯", async () => {
    await open("#/workspace?project=samvision&tab=server");
    expect(terms()).toContain("server");
    expect(screen.getAllByTestId("menu").map((m) => m.getAttribute("href"))).toEqual(["commandcenter://terminal/server"]);
  });

  it("switching project switches the Project terminal and the Claude context; nothing from the old project shows", async () => {
    setCoord("samvision", { state: "ready", paneId: "wE:p2", status: "idle", candidates: [] });
    setCoord("gyst", { state: "none", candidates: [] });
    await open("#/workspace?project=samvision&tab=repo");
    expect(terms()).toContain("repo:SV");
    fireEvent.change(screen.getByRole("combobox", { name: "Workspace project" }), { target: { value: "gyst" } });
    await waitFor(() => expect(terms()).toContain("repo:GYST"));
    expect(terms()).not.toContain("repo:SV");
  });
});

describe("the top bar is project · ticket · branch", () => {
  it("no GitHub slug, no Go-to-file button in the bar (Ctrl+P and the palette still open it)", async () => {
    await open("#/workspace?project=samvision");
    const bar = document.querySelector(".ws-bar")!;
    expect(bar.textContent).toMatch(/Project.*Ticket.*Branch/);
    expect(within(bar as HTMLElement).queryByRole("button", { name: /Go to file/ })).toBeNull();
    expect(within(bar as HTMLElement).queryByText(/↗/)).toBeNull();
  });
});
