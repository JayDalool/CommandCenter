/**
 * The Workspace layout: one sidebar (Explorer / Source control / Search) picked from an activity bar,
 * diffs and files in the main area, Claude only in the dock. Monaco and xterm are stubbed.
 */
import { render, screen, within, fireEvent, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

const reveal = vi.fn();
vi.mock("../src/workspace/Editor", () => ({
  CodeEditor: ({ path }: { path: string }) => <div data-testid="editor">{path}</div>,
  disposeModel: () => {}, nextVersion: () => 1, revealLine: (...a: unknown[]) => reveal(...a), hasModel: () => false, languageOf: () => "plaintext",
}));
vi.mock("../src/workspace/Terminal", () => ({ TerminalView: ({ label }: { label: string }) => <div data-testid="term">{label}</div> }));

import { app, initial } from "../src/store/app";
import { prefs, parsePrefs } from "../src/lib/prefs";
import { Files as Workspace, workspaceTabs } from "../src/screens/Files";
import { buildItems } from "../src/components/CommandPalette";
import { state, tasks } from "./helpers";
import type { ScmStatus } from "../src/api/types";

const scm: ScmStatus = { project: "samvision", clean: false,
  branch: { head: "main", upstream: null, ahead: 0, behind: 0, oid: "abc" },
  staged: [{ path: "b.py", orig: null, code: "M", status: "M.", protected: false }],
  unstaged: [{ path: "a.py", orig: null, code: "M", status: ".M", protected: false }], untracked: [], conflicts: [] };

beforeEach(() => {
  vi.restoreAllMocks();
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true, taskProjects: t.projects, meta: t.meta });
  location.hash = "#/files?project=samvision";
  prefs.patch({ wsSide: "explorer", wsExplorerOpen: true, wsTermOpen: true, wsMax: "none", consoleTab: "claude" });
  workspaceTabs.set(() => ({ tabs: [], views: [], active: null }));
  reveal.mockReset();
  vi.spyOn(app.api, "workspaceProjects").mockResolvedValue({ projects: [{ key: "samvision", name: "SamVision", prefix: "SV", root: "/x", exists: true,
    branch: "main", github: { owner: "o", repo: "r", slug: "o/r", url: "https://github.com/o/r" }, coordinator: null }] });
  vi.spyOn(app.api, "listDir").mockResolvedValue({ project: "samvision", path: "", crumbs: [], truncated: false, git: true,
    entries: [{ name: "a.py", kind: "file", size: 3, mtime: 1, protected: false, link: false }] });
  vi.spyOn(app.api, "readFile").mockImplementation(async (project: string, path: string) => ({ project, path, size: 3, mtime: 1, mode: "644", kind: "text", text: "x=1", sha: "s" }));
  vi.spyOn(app.api, "scmStatus").mockResolvedValue(scm);
  vi.spyOn(app.api, "scmDiff").mockImplementation(async (project: string, path: string, staged: boolean) => ({ project, path, staged, diff: "@@ -1 +1 @@\n-a\n+b", truncated: false, binary: false }));
  vi.spyOn(app.api, "searchText").mockResolvedValue({ project: "samvision", query: "hello", files: 1, truncated: false,
    matches: [{ path: "a.py", line: 7, text: "hello world", ranges: [[0, 5]] }] });
});

const mainArea = () => screen.getByRole("region", { name: "Main area" });
const sidebar = () => document.querySelector<HTMLElement>(".ws-sidebar")!;
async function ready() { render(<Workspace />); await screen.findByRole("navigation", { name: "Activity bar" }); }

describe("activity bar", () => {
  it("switches the sidebar mode and collapses when the active mode is clicked again", async () => {
    const user = userEvent.setup();
    await ready();
    const bar = screen.getByRole("navigation", { name: "Activity bar" });
    const btn = (n: string) => within(bar).getByRole("button", { name: n });
    expect(btn("Explorer")).toHaveAttribute("aria-pressed", "true");
    expect(btn("Source control")).toHaveAttribute("aria-pressed", "false");
    await user.click(btn("Source control"));
    expect(prefs.get().wsSide).toBe("scm");
    expect(btn("Source control")).toHaveAttribute("aria-pressed", "true");
    expect(btn("Explorer")).toHaveAttribute("aria-pressed", "false");
    await user.click(btn("Search"));
    expect(prefs.get().wsSide).toBe("search");
    await user.click(btn("Search"));
    expect(prefs.get().wsExplorerOpen).toBe(false);
    expect(sidebar()).not.toBeVisible();
    expect(btn("Search")).toHaveAttribute("aria-pressed", "false");
    await user.click(btn("Explorer"));
    expect(prefs.get().wsExplorerOpen).toBe(true);
    expect(prefs.get().wsSide).toBe("explorer");
  });

  it("Ctrl+B toggles the sidebar and Ctrl+Shift+F opens Search with the query focused", async () => {
    await ready();
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(prefs.get().wsExplorerOpen).toBe(false);
    fireEvent.keyDown(window, { key: "F", ctrlKey: true, shiftKey: true });
    expect(prefs.get().wsSide).toBe("search");
    expect(prefs.get().wsExplorerOpen).toBe(true);
    await waitFor(() => expect(screen.getByLabelText("Search text")).toHaveFocus());
  });

  it("explorer is the default mode and opens a file into the main area", async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(await screen.findByRole("treeitem", { name: /a\.py/ }));
    await waitFor(() => expect(within(mainArea()).getByRole("tab", { name: /a\.py/ })).toBeInTheDocument());
    expect(screen.getByTestId("editor")).toHaveTextContent("samvision:a.py");
  });
});

describe("source control in the sidebar", () => {
  it("a changed file opens its diff as a tab in the main area; staged ones say so", async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(screen.getByRole("button", { name: "Source control" }));
    const side = within(sidebar());
    await user.click(await side.findByRole("button", { name: /a\.py/ }));
    expect(await within(mainArea()).findByRole("tab", { name: /a\.py \(diff\)/ })).toHaveAttribute("aria-selected", "true");
    expect(await within(mainArea()).findByLabelText("Diff of a.py")).toBeInTheDocument();
    await user.click(side.getByRole("button", { name: /b\.py/ }));
    expect(await within(mainArea()).findByRole("tab", { name: /b\.py \(staged\)/ })).toBeInTheDocument();
    expect(app.api.scmDiff).toHaveBeenCalledWith("samvision", "b.py", true);
    expect(side.getByRole("button", { name: "Stage all" })).toBeInTheDocument();
    expect(side.getByLabelText("Commit message")).toBeInTheDocument();
  });
});

describe("search in the sidebar", () => {
  it("a hit opens the file in the main editor at its line; regex is off", async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(screen.getByRole("button", { name: "Search" }));
    const side = within(sidebar());
    expect(side.getByRole("button", { name: /Regular expression/ })).toBeDisabled();
    await user.type(side.getByLabelText("Search text"), "hello{Enter}");
    await user.click(await side.findByRole("button", { name: /hello world/ }));
    await waitFor(() => expect(within(mainArea()).getByRole("tab", { name: /a\.py/ })).toBeInTheDocument());
    expect(reveal).toHaveBeenCalledWith("samvision:a.py", 7);
    expect(app.api.searchText).toHaveBeenCalledWith("samvision", "hello", expect.objectContaining({ regex: false }), expect.anything());
  });
});

describe("claude only in the dock", () => {
  it("has no Claude tab in the main area; the dock is Claude, Project and Server", async () => {
    await ready();
    expect(within(mainArea()).queryByRole("tab", { name: /claude/i })).toBeNull();
    expect(within(mainArea()).queryByText("Claude")).toBeNull();
    const dock = screen.getByRole("tablist", { name: "Terminal" });
    expect(within(dock).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Claude", "Project", "Server"]);
  });
});

describe("diff freshness", () => {
  it("a diff tab re-reads after stage and after unstage", async () => {
    const user = userEvent.setup();
    vi.spyOn(app, "action").mockImplementation(async (fn: () => Promise<unknown>) => { await fn(); return true; });
    vi.spyOn(app.api, "scm").mockResolvedValue({} as never);
    app.store.patch({});
    const { setDevSession } = await import("../src/api/developer");
    setDevSession("s".repeat(43), 3600);
    await ready();
    await user.click(screen.getByRole("button", { name: "Source control" }));
    await user.click(await within(sidebar()).findByRole("button", { name: /a\.py/ }));
    await within(mainArea()).findByLabelText("Diff of a.py");
    const calls = () => (app.api.scmDiff as unknown as { mock: { calls: unknown[][] } }).mock.calls.length;
    const before = calls();
    await user.click(within(sidebar()).getByRole("button", { name: "Stage" }));
    await waitFor(() => expect(calls()).toBeGreaterThan(before));
    const mid = calls();
    await user.click(within(sidebar()).getAllByRole("button", { name: "Unstage" })[0]);
    await waitFor(() => expect(calls()).toBeGreaterThan(mid));
    setDevSession(null);
  });
});

describe("legacy events and addresses", () => {
  const send = (detail: Record<string, unknown>) => act(() => { window.dispatchEvent(new CustomEvent("cc:workspace", { detail })); });
  it("{main:'scm'} opens Source control and {main:'dev'} opens Development", async () => {
    await ready();
    send({ main: "scm" });
    expect(prefs.get().wsSide).toBe("scm");
    send({ main: "dev" });
    expect(await within(mainArea()).findByRole("tab", { name: /Development/ })).toBeInTheDocument();
  });
  it("?view=search opens the Search sidebar", async () => {
    location.hash = "#/files?project=samvision&view=search";
    await ready();
    await waitFor(() => expect(prefs.get().wsSide).toBe("search"));
  });
});

describe("palette events", () => {
  const send = (detail: Record<string, unknown>) => act(() => { window.dispatchEvent(new CustomEvent("cc:workspace", { detail })); });
  it("routes side, search, dev, term and goto", async () => {
    await ready();
    send({ side: "scm" });
    expect(prefs.get().wsSide).toBe("scm");
    send({ side: "search", search: true });
    expect(prefs.get().wsSide).toBe("search");
    await waitFor(() => expect(screen.getByLabelText("Search text")).toHaveFocus());
    send({ dev: true });
    expect(await within(mainArea()).findByRole("tab", { name: /Development/ })).toHaveAttribute("aria-selected", "true");
    send({ term: "server" });
    expect(prefs.get().consoleTab).toBe("server");
    send({ goto: true });
    expect(await screen.findByRole("dialog", { name: "Go to file" })).toBeInTheDocument();
  });

  it("the palette offers every Workspace action and each dispatches the new event shape", () => {
    location.hash = "#/files";
    vi.useFakeTimers();
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener("cc:workspace", on);
    const items = buildItems(() => {});
    const by = (l: string) => items.find((i) => i.kind === "ACTION" && i.label === l)!;
    for (const l of ["Explorer", "Source Control", "Search", "Go to file", "Open Claude", "Open Project terminal", "Open Server terminal", "Development", "Open GitHub", "Open PR"])
      expect(by(l), l).toBeTruthy();
    for (const l of ["Explorer", "Source Control", "Search", "Go to file", "Open Claude", "Open Project terminal", "Open Server terminal", "Development"]) by(l).run();
    vi.advanceTimersByTime(100);
    window.removeEventListener("cc:workspace", on);
    vi.useRealTimers();
    expect(seen).toEqual([{ side: "explorer" }, { side: "scm" }, { side: "search", search: true }, { goto: true },
      { term: "claude" }, { term: "repo" }, { term: "server" }, { dev: true }]);
  });

  it("Open GitHub opens the current project's repository", () => {
    location.hash = "#/files?project=samvision";
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const st = state();
    st.projects.find((p) => p.key === "samvision")!.repoUrl = "https://github.com/o/r";
    app.store.patch({ state: st });
    const url = "https://github.com/o/r";
    buildItems(() => {}).find((i) => i.label === "Open GitHub")!.run();
    expect(open).toHaveBeenCalledWith(url, "_blank", "noopener,noreferrer");
  });
});

describe("prefs migration", () => {
  it("maps the old center view onto the sidebar mode and drops wsMain", () => {
    expect(parsePrefs(JSON.stringify({ wsMain: "scm" })).wsSide).toBe("scm");
    expect(parsePrefs(JSON.stringify({ wsMain: "search" })).wsSide).toBe("search");
    for (const m of ["editor", "claude", "dev"]) expect(parsePrefs(JSON.stringify({ wsMain: m })).wsSide).toBe("explorer");
    expect(parsePrefs(JSON.stringify({ wsMain: "scm", wsSide: "search" })).wsSide).toBe("search");
    expect(parsePrefs(JSON.stringify({ wsSide: "bogus" })).wsSide).toBe("explorer");
    expect("wsMain" in parsePrefs(JSON.stringify({ wsMain: "scm" }))).toBe(false);
    expect(parsePrefs("not json").wsSide).toBe("explorer");
    expect(parsePrefs(null).wsExplorerW).toBe(260);
  });
});

describe("explorer operations (CC-040)", () => {
  const file = (path: string) => ({ project: "samvision", path, size: 3, mtime: 1, mode: "644", kind: "text" as const, text: "x=1", sha: "s" });
  const tab = (path: string, dirty = false) => ({ path: `samvision:${path}`, file: file(path), text: "x=1", version: 1, dirty, conflict: null });
  const root = (...names: [string, "file" | "dir"][]) => ({ project: "samvision", path: "", crumbs: [], truncated: false, git: true,
    entries: names.map(([name, kind]) => ({ name, kind, size: 3, mtime: 1, protected: false, link: false })) });
  async function dev() {
    const { setDevSession } = await import("../src/api/developer");
    setDevSession("s".repeat(43), 3600);
    return () => setDevSession(null);
  }
  const menuOn = async (user: ReturnType<typeof userEvent.setup>, name: RegExp, item: string) => {
    fireEvent.contextMenu(await screen.findByRole("treeitem", { name }));
    await user.click(await screen.findByRole("menuitem", { name: item }));
  };

  it("a new file shows in the listing at once, without a refresh", async () => {
    const user = userEvent.setup();
    const off = await dev();
    const confirm = vi.spyOn(window, "confirm");
    const save = vi.spyOn(app.api, "saveFile").mockResolvedValue({ sha: "n", size: 0, mtime: 2 } as never);
    await ready();
    await screen.findByRole("treeitem", { name: /a\.py/ });
    const listDir = app.api.listDir as unknown as { mock: { calls: unknown[][] } };
    const before = listDir.mock.calls.length;
    (app.api.listDir as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(root(["a.py", "file"], ["new.txt", "file"]));
    await menuOn(user, /a\.py/, "New file…");
    await user.type(screen.getByLabelText("Name"), "new.txt");
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(save).toHaveBeenCalledWith("samvision", "new.txt", "", null);
    expect(await screen.findByRole("treeitem", { name: /new\.txt/ })).toBeInTheDocument();
    expect(listDir.mock.calls.length).toBeGreaterThan(before);
    expect(confirm).not.toHaveBeenCalled();
    off();
  });

  it("deleting an open file closes its tab; Cancel and Esc do not delete", async () => {
    const user = userEvent.setup();
    const off = await dev();
    const confirm = vi.spyOn(window, "confirm");
    const rm = vi.spyOn(app.api, "removePath").mockResolvedValue({ path: "a.py", deleted: "a.py" });
    workspaceTabs.set(() => ({ tabs: [tab("a.py")], views: [], active: "samvision:a.py" }));
    await ready();
    expect(within(mainArea()).getByRole("tab", { name: /a\.py/ })).toBeInTheDocument();
    await menuOn(user, /a\.py/, "Delete…");
    const dlg = await screen.findByRole("dialog", { name: "Delete file?" });
    await user.click(within(dlg).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await menuOn(user, /a\.py/, "Delete…");
    await screen.findByRole("dialog", { name: "Delete file?" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(rm).not.toHaveBeenCalled();
    expect(within(mainArea()).getByRole("tab", { name: /a\.py/ })).toBeInTheDocument();
    await menuOn(user, /a\.py/, "Delete…");
    await user.click(within(await screen.findByRole("dialog", { name: "Delete file?" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(rm).toHaveBeenCalledWith("samvision", "a.py"));
    await waitFor(() => expect(within(mainArea()).queryByRole("tab", { name: /a\.py/ })).toBeNull());
    expect(within(mainArea()).getByText("No file open")).toBeInTheDocument();
    expect(workspaceTabs.get().tabs).toEqual([]);
    expect(confirm).not.toHaveBeenCalled();
    off();
  });

  it("deleting a folder closes tabs of files inside it and keeps the others; says when one is unsaved", async () => {
    const user = userEvent.setup();
    const off = await dev();
    vi.spyOn(app.api, "listDir").mockResolvedValue(root(["a.py", "file"], ["src", "dir"]));
    const rm = vi.spyOn(app.api, "removePath").mockResolvedValue({ path: "src", deleted: "src" });
    workspaceTabs.set(() => ({ tabs: [tab("a.py"), tab("src/deep/x.py", true), tab("srcs/y.py")], views: [], active: "samvision:src/deep/x.py" }));
    await ready();
    await menuOn(user, /^src/, "Delete folder…");
    const dlg = await screen.findByRole("dialog", { name: "Delete folder?" });
    expect(dlg).toHaveTextContent("unsaved changes; they are lost");
    await user.click(within(dlg).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(rm).toHaveBeenCalledWith("samvision", "src"));
    await waitFor(() => expect(workspaceTabs.get().tabs.map((t) => t.path)).toEqual(["samvision:a.py", "samvision:srcs/y.py"]));
    expect(workspaceTabs.get().active).toBe("samvision:srcs/y.py");
    off();
  });

  it("a failed delete keeps the tab", async () => {
    const user = userEvent.setup();
    const off = await dev();
    vi.spyOn(app.api, "removePath").mockRejectedValue(new Error("nope"));
    workspaceTabs.set(() => ({ tabs: [tab("a.py")], views: [], active: "samvision:a.py" }));
    await ready();
    await menuOn(user, /a\.py/, "Delete…");
    await user.click(within(await screen.findByRole("dialog", { name: "Delete file?" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(app.api.removePath).toHaveBeenCalled());
    await waitFor(() => expect(app.store.get().toast?.text).toBe("nope"));
    expect(workspaceTabs.get().tabs).toHaveLength(1);
    off();
  });

  it("closing a dirty tab asks in the dialog: Close closes, Cancel keeps", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    workspaceTabs.set(() => ({ tabs: [tab("a.py", true)], views: [], active: "samvision:a.py" }));
    await ready();
    const closeBtn = () => within(mainArea()).getByRole("button", { name: /close/i });
    await user.click(closeBtn());
    await user.click(within(await screen.findByRole("dialog", { name: "Close with unsaved changes?" })).getByRole("button", { name: "Cancel" }));
    expect(workspaceTabs.get().tabs).toHaveLength(1);
    await user.click(closeBtn());
    await user.click(within(await screen.findByRole("dialog", { name: "Close with unsaved changes?" })).getByRole("button", { name: "Close anyway" }));
    expect(workspaceTabs.get().tabs).toEqual([]);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("reloading a dirty tab asks in the dialog: Cancel keeps the edits, Discard reloads", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    workspaceTabs.set(() => ({ tabs: [tab("a.py", true)], views: [], active: "samvision:a.py" }));
    await ready();
    const reads = () => (app.api.readFile as unknown as { mock: { calls: unknown[][] } }).mock.calls.length;
    const before = reads();
    await user.click(within(mainArea()).getByRole("button", { name: "Reload" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Discard unsaved changes?" })).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(reads()).toBe(before);
    expect(workspaceTabs.get().tabs[0].dirty).toBe(true);
    await user.click(within(mainArea()).getByRole("button", { name: "Reload" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Discard unsaved changes?" })).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(reads()).toBe(before + 1));
    await waitFor(() => expect(workspaceTabs.get().tabs[0].dirty).toBe(false));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("deleting a file only closes this project's tabs, not another project's at the same path", async () => {
    const user = userEvent.setup();
    const off = await dev();
    vi.spyOn(app.api, "removePath").mockResolvedValue({ path: "a.py", deleted: "a.py" });
    const other = { path: "other:a.py", file: { ...file("a.py"), project: "other" }, text: "x=1", version: 1, dirty: false, conflict: null };
    workspaceTabs.set(() => ({ tabs: [tab("a.py"), other], views: [], active: "samvision:a.py" }));
    await ready();
    await menuOn(user, /a\.py/, "Delete…");
    await user.click(within(await screen.findByRole("dialog", { name: "Delete file?" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(workspaceTabs.get().tabs.map((t) => t.path)).toEqual(["other:a.py"]));
    off();
  });
});
