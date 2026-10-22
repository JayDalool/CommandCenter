import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "../src/App";
import { owners } from "../src/windows/manager";
import { chat, viewState } from "../src/data/live";
import { SEED_CHAT } from "../src/data/seed";

const go = (h: string) => act(() => { location.hash = h; window.dispatchEvent(new HashChangeEvent("hashchange")); });
let open: ReturnType<typeof vi.fn>;
let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  owners.set({}); viewState.set({}); chat.set(SEED_CHAT); sessionStorage.clear();
  open = vi.fn(() => ({ closed: false, focus: vi.fn(), close: vi.fn() }));
  vi.stubGlobal("open", open);
  fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy);
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("navigation", () => {
  it("has the seven flagship pages and each renders its own page", () => {
    go("#/office");
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Pages" });
    for (const l of ["My Office", "Messages", "Decisions", "Teams", "Company", "Engineering", "Revenue"]) expect(within(nav).getByText(l)).toBeInTheDocument();
    const heads: Record<string, RegExp> = { office: /Good (morning|afternoon|evening)/, messages: /^Messages$/, decisions: /Rental comparison redesign/, teams: /SamVision/,
      topology: /Operations Topology/, engineering: /Engineering/, revenue: /^Revenue$/ };
    for (const [r, h] of Object.entries(heads)) { go(`#/${r}`); expect(screen.getAllByRole("heading", { level: 1 }).some((e) => h.test(e.textContent ?? ""))).toBe(true); }
  });
});

describe("pop out any tab", () => {
  it("every top-level page pops out, its tab and nav item are shaded, and Return here brings it back", () => {
    render(<App />);
    for (const p of ["office", "messages", "decisions", "teams", "topology", "engineering", "revenue"]) {
      go(`#/${p}`);
      fireEvent.click(screen.getAllByTestId(`pop-page:${p}`)[0]);
      // the window that opened it is not the owner → placeholder, shaded tab
      act(() => owners.set((o) => ({ ...o, [`page:${p}`]: { ...o[`page:${p}`], win: "other-window", beat: Date.now() } })));
      expect(screen.getByTestId(`placeholder-page:${p}`)).toHaveTextContent("This view is open in another window");
      expect(screen.getByTestId(`tab-page:${p}`)).toHaveClass("is-out");
      fireEvent.click(within(screen.getByTestId(`placeholder-page:${p}`)).getByRole("button", { name: /Return here/ }));
      expect(screen.queryByTestId(`placeholder-page:${p}`)).toBeNull();
      expect(screen.getByTestId(`tab-page:${p}`)).not.toHaveClass("is-out");
    }
    expect(open).toHaveBeenCalledTimes(7);
    expect(fetchSpy).not.toHaveBeenCalled();     // no backend call: nothing is started or stopped
  });

  it("a conversation pops out on its own; switching conversations in the main window still works", () => {
    go("#/messages/sv-lead");
    render(<App />);
    fireEvent.click(screen.getAllByTestId("pop-dm:sv-lead")[0]);
    act(() => owners.set((o) => ({ ...o, "dm:sv-lead": { ...o["dm:sv-lead"], win: "w2", beat: Date.now() } })));
    expect(screen.getByTestId("placeholder-dm:sv-lead")).toBeInTheDocument();
    go("#/messages/nova");
    expect(screen.getByRole("region", { name: /Conversation with Nova/ })).toBeInTheDocument();
    go("#/messages/sv-lead");
    expect(screen.getByTestId("placeholder-dm:sv-lead")).toBeInTheDocument();
  });

  it("a blocked pop-up leaves the page usable and explains what to do", () => {
    vi.stubGlobal("open", vi.fn(() => null));
    go("#/revenue");
    render(<App />);
    fireEvent.click(screen.getAllByTestId("pop-page:revenue")[0]);
    expect(screen.queryByTestId("placeholder-page:revenue")).toBeNull();
    expect(screen.getByText(/blocked the pop-out window/)).toBeInTheDocument();
  });

  it("Alt+Shift+O pops out the current tab from the keyboard", () => {
    go("#/teams");
    render(<App />);
    fireEvent.keyDown(window, { code: "KeyO", key: "O", altKey: true, shiftKey: true });
    expect(open).toHaveBeenCalledWith(expect.stringMatching(/#\/pop\/page%3Ateams$/), expect.any(String), expect.any(String));
  });
});

describe("pages", () => {
  it("project-lead chat sends once and keeps the draft per conversation", () => {
    vi.useFakeTimers();
    go("#/messages/sv-lead");
    render(<App />);
    const box = screen.getByLabelText("Message Claude");
    fireEvent.change(box, { target: { value: "Status update please" } });
    expect(viewState.get()["dm:sv-lead"].draft).toBe("Status update please");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    act(() => { vi.advanceTimersByTime(1000); });
    const mine = chat.get()["sv-lead"].filter((m) => m.text === "Status update please");
    expect(mine).toHaveLength(1);
    expect(chat.get()["sv-lead"].at(-1)?.from).toBe("claude");
    vi.useRealTimers();
  });

  it("a decision is recorded only through the confirm step, with actor and policy shown", () => {
    go("#/decisions");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Record decision: Option A/ }));
    const dlg = screen.getByRole("dialog", { name: "Confirm decision" });
    expect(dlg).toHaveTextContent("Jay (owner)");
    expect(dlg).toHaveTextContent("No merge, no deploy");
    fireEvent.click(within(dlg).getByRole("button", { name: "Record decision" }));
    expect(screen.getByText(/Decided: Option A/)).toBeInTheDocument();
  });

  it("topology filters, switches to table, and the inspector follows the selection", () => {
    go("#/topology");
    render(<App />);
    const canvas = screen.getByTestId("topology-canvas");
    expect(canvas.querySelectorAll(".k-project")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.click(screen.getByRole("button", { name: "GYST / LifeOps" }));
    expect(screen.getByTestId("topology-canvas").querySelectorAll(".k-project")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /GYST \/ LifeOps, healthy/ }));
    expect(screen.getByRole("complementary", { name: "Inspector" })).toHaveTextContent("Jay's personal LifeOps software");
    fireEvent.click(screen.getByRole("tab", { name: /Table/ }));
    expect(screen.getByRole("table")).toHaveTextContent("WorkerNode");
  });

  it("revenue says Not connected and shows no money until the fictional demo is switched on", () => {
    go("#/revenue");
    render(<App />);
    expect(screen.getByText("Revenue is not connected")).toBeInTheDocument();
    expect(document.querySelector(".page-revenue")!.textContent).not.toMatch(/\$\d/);
    fireEvent.click(screen.getByLabelText("Fictional demo"));
    expect(screen.getByText(/Every number on this page is FICTIONAL/)).toBeInTheDocument();
  });

  it("paused GauzeMate is shown as paused, never as working", () => {
    go("#/teams/gauzemate");
    render(<App />);
    expect(screen.getByText(/Jay paused GauzeMate until he adds designs and files/)).toBeInTheDocument();
    expect(document.querySelector(".team-graph")!.textContent).not.toMatch(/Working/);
  });
});
