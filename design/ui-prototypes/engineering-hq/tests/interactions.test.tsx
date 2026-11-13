// Controls found inert by the click-through audit (2026-10-25) must now do something visible.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "../src/App";
import { owners } from "../src/windows/manager";
import { org, seedOrg } from "../src/data/org";
import { chat, viewState } from "../src/data/live";
import { SEED_CHAT } from "../src/data/seed";
import { SETTINGS_SECTIONS } from "../src/pages/Settings";

const go = (h: string) => act(() => { location.hash = h; window.dispatchEvent(new HashChangeEvent("hashchange")); });

beforeEach(() => {
  org.set(seedOrg()); owners.set({}); viewState.set({}); chat.set(SEED_CHAT); sessionStorage.clear();
  vi.stubGlobal("open", vi.fn(() => ({ closed: false, focus: vi.fn(), close: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("engineering workbench", () => {
  it("task detail tabs each show their own content, and Review Plan opens the plan", () => {
    go("#/engineering");
    render(<App />);
    const detail = screen.getByRole("complementary", { name: "Task detail" });
    expect(within(detail).getByText("Why")).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole("tab", { name: "Checks" }));
    expect(within(detail).getByText("Independent review")).toBeInTheDocument();
    expect(within(detail).queryByText("Why")).toBeNull();
    fireEvent.click(within(detail).getByRole("tab", { name: "Activity" }));
    expect(within(detail).getByText(/created the task/)).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole("button", { name: /Review Plan/ }));
    expect(within(detail).getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    expect(within(detail).getByText("Pop out any tab")).toBeInTheDocument();
  });

  it("environment and assignee filters narrow the table; row checkboxes drive a selection bar", () => {
    go("#/engineering");
    render(<App />);
    const table = screen.getByRole("table");
    const before = within(table).getAllByRole("row").length;
    fireEvent.change(screen.getByLabelText("Environment"), { target: { value: "Staging" } });
    const staging = within(table).getAllByRole("row").length;
    expect(staging).toBeLessThan(before);
    fireEvent.change(screen.getByLabelText("Environment"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Assignee"), { target: { value: "pixel" } });
    for (const r of within(table).getAllByRole("row").slice(1)) expect(r).toHaveTextContent("Pixel");
    fireEvent.change(screen.getByLabelText("Assignee"), { target: { value: "all" } });
    fireEvent.click(screen.getByLabelText("Select SV-025"));
    expect(screen.getByRole("status")).toHaveTextContent("1 selected");
    fireEvent.click(screen.getByLabelText("Select all"));
    expect(screen.getByRole("status")).toHaveTextContent(`${before - 1} selected`);
    fireEvent.click(within(screen.getByRole("status")).getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(/selected$/)).toBeNull();
  });
});

describe("decisions evidence", () => {
  it("Logs, Screenshots, UI Findings and Files show different content", () => {
    go("#/decisions/sv-025");
    render(<App />);
    const ev = screen.getByRole("complementary", { name: "Evidence and context" });
    expect(within(ev).getByText("Relevant Logs")).toBeInTheDocument();
    fireEvent.click(within(ev).getByRole("tab", { name: "UI Findings" }));
    expect(within(ev).getByText(/Filter chips wrap early/)).toBeInTheDocument();
    expect(within(ev).queryByText("Relevant Logs")).toBeNull();
    fireEvent.click(within(ev).getByRole("tab", { name: "Files" }));
    expect(within(ev).getByText("review-notes.md")).toBeInTheDocument();
    fireEvent.click(within(ev).getByRole("tab", { name: "Screenshots" }));
    expect(within(ev).getByText("UI Screenshots")).toBeInTheDocument();
  });
});

describe("messages", () => {
  it("New Message offers Project Leads first and opens the chosen conversation", async () => {
    go("#/messages/sv-lead");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /New Message/ }));
    const menu = screen.getByRole("menu");
    const items = within(menu).getAllByRole("menuitem");
    expect(items[0]).toHaveTextContent("Project Lead");
    fireEvent.click(within(menu).getByText(/Pixel · UI Testing Lead/));
    expect(location.hash).toBe("#/messages/pixel");
  });
});

describe("settings", () => {
  it("every section opens from the sidebar and shows its own heading", () => {
    go("#/settings");
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    for (const s of SETTINGS_SECTIONS) {
      go(`#/settings/${s.id}`);
      expect(within(nav).getByRole("link", { name: new RegExp(s.label) })).toHaveAttribute("aria-current", "page");
      expect(document.querySelector(".set-h h1, .set-h h2")?.textContent).toContain(s.label);
    }
  });
});

describe("agent inspector", () => {
  it("closes the drawer when an action opens another page, so it never covers that page", () => {
    go("#/teams/samvision");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /^Nova, / }));
    const d = screen.getByRole("dialog", { name: "Agent details" });
    fireEvent.click(within(d).getByRole("button", { name: /Change model/ }));
    expect(screen.queryByRole("dialog", { name: "Agent details" })).toBeNull();
    expect(location.hash).toBe("#/onboard");
  });

  it("Chat with the agent closes the drawer and opens the conversation", () => {
    go("#/teams/samvision");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /^Claude, / }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Agent details" })).getByRole("button", { name: /Chat with Claude/ }));
    expect(screen.queryByRole("dialog", { name: "Agent details" })).toBeNull();
    expect(location.hash).toMatch(/^#\/messages\//);
  });
});
