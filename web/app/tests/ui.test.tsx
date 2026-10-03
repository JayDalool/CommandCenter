import { render, screen, within, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { app, initial } from "../src/store/app";
import { prefs } from "../src/lib/prefs";
import { AppShell, OfflineBanner, FreshnessBar } from "../src/components/Shell";
import { DataTable } from "../src/components/DataTable";
import { CommandPalette, buildItems, rank } from "../src/components/CommandPalette";
import { Tasks } from "../src/screens/Tasks";
import { Overview } from "../src/screens/Overview";
import { Workspaces } from "../src/screens/Workspaces";
import { NewTicket } from "../src/components/NewTicket";
import { state, tasks } from "./helpers";

function load(over: Partial<typeof initial> = {}) {
  const t = tasks();
  app.store.set({ ...initial, auth: "ok", state: state(), stateAt: Date.now(), tickets: t.tickets, ticketsLoaded: true,
    taskProjects: t.projects, meta: t.meta, conn: { status: "live", lastMessageAt: Date.now(), attempt: 0 }, ...over });
}

beforeEach(() => { location.hash = ""; load(); prefs.patch({ consoleOpen: false }); });

describe("DataTable keyboard", () => {
  it("j/k move, Enter opens, roving tabindex", async () => {
    const rows = [{ k: "A" }, { k: "B" }, { k: "C" }];
    const opened: string[] = [];
    let selected: string | null = "A";
    const { rerender } = render(<DataTable label="t" rows={rows} rowKey={(r) => r.k} selected={selected}
      columns={[{ id: "k", header: "K", cell: (r) => r.k }]} onSelect={(k) => { selected = k; }} onActivate={(k) => opened.push(k)} />);
    const trs = screen.getAllByRole("row").slice(1);
    expect(trs.map((r) => r.tabIndex)).toEqual([0, -1, -1]);
    trs[0].focus();
    fireEvent.keyDown(trs[0], { key: "j" });
    expect(selected).toBe("B");
    rerender(<DataTable label="t" rows={rows} rowKey={(r) => r.k} selected={selected}
      columns={[{ id: "k", header: "K", cell: (r) => r.k }]} onSelect={(k) => { selected = k; }} onActivate={(k) => opened.push(k)} />);
    fireEvent.keyDown(screen.getAllByRole("row")[2], { key: "Enter" });
    expect(opened).toEqual(["B"]);
    expect(screen.getByRole("table", { name: "t" })).toBeInTheDocument();
  });
});

describe("command palette", () => {
  it("finds a project, its agent, its tasks and the safe actions", () => {
    const items = buildItems(() => {});
    const r = rank(items, "samvision");
    const kinds = r.map((i) => `${i.kind} ${i.label}`);
    expect(kinds).toContain("PROJECT SamVision");
    expect(kinds).toContain("ACTION Focus SamVision coordinator");
    expect(kinds.some((k) => k.startsWith("AGENT SamVision / samvision"))).toBe(true);
    expect(rank(items, "SV-056")[0].label).toMatch(/^SV-056/);
    expect(rank(items, "#94").some((i) => i.kind === "PR")).toBe(true);
  });
  it("has no merge or deploy action", () => {
    const actions = buildItems(() => {}).filter((i) => i.kind === "ACTION" || i.kind === "GO");
    expect(actions.some((a) => /merge|deploy|delete|restart/i.test(a.label))).toBe(false);
  });
  it("arrow keys and Enter run the highlighted item", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CommandPalette onClose={onClose} onNewTask={() => {}} />);
    await user.type(screen.getByRole("combobox"), "server");
    const opts = screen.getAllByRole("option");
    expect(opts[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    expect(onClose).toHaveBeenCalled();
    expect(location.hash).toBe("#/server");
  });
});

describe("global keyboard", () => {
  it("N opens capture, Ctrl+K the palette, digits navigate", async () => {
    const user = userEvent.setup();
    render(<AppShell><div>content</div></AppShell>);
    await user.keyboard("n");
    expect(screen.getByRole("dialog", { name: "New task" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.keyboard("4");
    expect(location.hash).toBe("#/tasks");
  });
});

describe("fast capture", () => {
  it("project + title + Enter creates the ticket", async () => {
    const user = userEvent.setup();
    const created = { ...tasks().tickets[0], key: "CC-005", project: "commandcenter", title: "Write the docs", description: "",
      relations: { blocks: [], blocked_by: [], related: [], duplicates: [], duplicated_by: [] }, subtaskList: [], comments: [], timeline: [] };
    const spy = vi.spyOn(app.api, "createTask").mockResolvedValue(created as never);
    const onClose = vi.fn();
    render(<NewTicket onClose={onClose} defaults={{ project: "commandcenter" }} />);
    await user.keyboard("Write the docs{Enter}");
    expect(spy).toHaveBeenCalledWith({ project: "commandcenter", title: "Write the docs" });
    expect(onClose).toHaveBeenCalled();
    expect(app.data.tickets[0].key).toBe("CC-005");
    spy.mockRestore();
  });
});

describe("tasks screen", () => {
  it("lists open tickets with the required columns", () => {
    location.hash = "#/tasks";
    render(<Tasks />);
    const table = screen.getByRole("table", { name: "Tasks" });
    const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent?.replace(/[↑↓\s]/g, ""));
    expect(heads).toEqual(["ID", "Title", "Status", "Pri", "Project", "Assignee", "Updated", "PR", "Flags"]);
    expect(within(table).getByText("SV-056")).toBeInTheDocument();
    expect(within(table).queryByText("SV-050")).toBeNull();  // DONE is hidden by default
  });
  it("project filter and instant search", async () => {
    const user = userEvent.setup();
    location.hash = "#/tasks";
    render(<Tasks />);
    await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), "gauzemate");
    const rows = within(screen.getByRole("table", { name: "Tasks" })).getAllByRole("row").slice(1);
    expect(rows.every((r) => /GM-/.test(r.textContent ?? ""))).toBe(true);
    await user.type(screen.getByRole("searchbox"), "lawyer");
    expect(within(screen.getByRole("table", { name: "Tasks" })).getAllByRole("row")).toHaveLength(2);
  });
  it("pipeline shows compact rows per status", () => {
    location.hash = "#/tasks?view=board";
    render(<Tasks />);
    const board = screen.getByRole("list", { name: "Pipeline" });
    const inProgress = within(board).getByRole("listitem", { name: /In progress/ });
    expect(within(inProgress).getByText("CC-001")).toBeInTheDocument();
    const review = within(board).getByRole("listitem", { name: /In review/ });
    expect(within(review).getByText("SV-056")).toBeInTheDocument();  // moved by PR #94 automation in the fixture
  });
  it("needs-Jay view aggregates every project", () => {
    location.hash = "#/tasks?view=jay";
    render(<Tasks />);
    const t = screen.getByRole("table", { name: "Needs Jay" });
    expect(within(t).getByText("ANSWER")).toBeInTheDocument();
    expect(within(t).getByText("SV-014")).toBeInTheDocument();
    expect(within(t).getByText("GM-004")).toBeInTheDocument();
  });
});

describe("overview", () => {
  it("answers the five questions and lists needs, agents, pipeline, server, activity", () => {
    render(<Overview />);
    const glance = screen.getByRole("region", { name: "At a glance" });
    expect(within(glance).getByText(/waiting for an answer/)).toBeInTheDocument();
    for (const name of ["Needs Jay", "Active agents", "Task pipeline", "Server health", "Recent activity"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
  });
});

describe("offline and freshness", () => {
  it("offline shows OFFLINE with the last update time and keeps the data", () => {
    const at = new Date(2026, 9, 3, 22, 41, 32).getTime();
    load({ conn: { status: "offline", lastMessageAt: null, attempt: 3 }, stateAt: at });
    render(<OfflineBanner />);
    const b = screen.getByRole("status");
    expect(b).toHaveTextContent("Offline");
    expect(b).toHaveTextContent("22:41:32");
    expect(app.data.state).not.toBeNull();
  });
  it("the status line names every source", () => {
    render(<FreshnessBar />);
    const bar = screen.getByRole("contentinfo", { name: "Source freshness" });
    for (const s of ["HERDR", "GITHUB", "HOST", "TASKS", "CCD"]) expect(bar).toHaveTextContent(s);
  });
});

describe("workspaces", () => {
  it("draws herdr panes from the layout and never offers a fake shell", async () => {
    const user = userEvent.setup();
    location.hash = "#/workspaces/wE";
    render(<Workspaces />);
    const canvas = screen.getByRole("group", { name: /Layout of tab/ });
    const blocked = within(canvas).getByRole("button", { name: /gauzemate, blocked/ });
    await user.click(blocked);
    expect(screen.getByText(/Should I keep initials/)).toBeInTheDocument();
    expect(screen.getByText("ssh -t jay-server herdr agent attach gauzemate")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /terminal|shell/i })).toBeNull();
  });
});

describe("quick console", () => {
  it("is labelled read-only and offers the real attach command", async () => {
    vi.spyOn(app.api, "tail").mockResolvedValue({ agentId: "wE:p2", name: "samvision", lines: 60, text: "✓ tests passed", redactions: 0, truncated: false });
    prefs.patch({ consoleOpen: true, consoleAgent: "wE:p2" });
    render(<AppShell><div /></AppShell>);
    expect(await screen.findByText("READ-ONLY TAIL")).toBeInTheDocument();
    expect(await screen.findByText("✓ tests passed")).toBeInTheDocument();
    expect(screen.getByText("ssh -t jay-server herdr agent attach samvision")).toBeInTheDocument();
    await act(async () => { prefs.patch({ consoleOpen: false }); });
  });
});

describe("review fixes", () => {
  it("a dialog keeps focus in its field when the parent re-renders", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<NewTicket onClose={() => {}} defaults={{ project: "commandcenter" }} />);
    const pri = screen.getByRole("combobox", { name: "Priority" });
    pri.focus();
    rerender(<NewTicket onClose={() => {}} defaults={{ project: "commandcenter" }} />);
    await act(async () => { load(); });
    expect(document.activeElement).toBe(pri);
    void user;
  });
  it("Ctrl+K and Enter on a link inside a row do not drive the table", () => {
    const opened: string[] = [];
    let selected = "A";
    render(<DataTable label="t" rows={[{ k: "A" }, { k: "B" }]} rowKey={(r) => r.k} selected={selected}
      columns={[{ id: "k", header: "K", cell: (r) => <a href="#x">{r.k}</a> }]} onSelect={(k) => { selected = k; }} onActivate={(k) => opened.push(k)} />);
    const row = screen.getAllByRole("row")[1];
    fireEvent.keyDown(row, { key: "k", ctrlKey: true });
    fireEvent.keyDown(within(row).getByRole("link"), { key: "Enter" });
    expect(selected).toBe("A");
    expect(opened).toEqual([]);
  });
});
