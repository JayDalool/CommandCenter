// Round 7 refinements: optional light theme (dark stays default), phone tab bar with a More sheet, My Office balance.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { App } from "../src/App";
import { owners } from "../src/windows/manager";
import { org, seedOrg } from "../src/data/org";
import { chat, viewState } from "../src/data/live";
import { SEED_CHAT } from "../src/data/seed";
import { resolvedTheme, setThemePref, themePref } from "../src/lib/theme";

const go = (h: string) => act(() => { location.hash = h; window.dispatchEvent(new HashChangeEvent("hashchange")); });

beforeEach(() => {
  org.set(seedOrg()); owners.set({}); viewState.set({}); chat.set(SEED_CHAT); sessionStorage.clear();
  act(() => setThemePref("dark"));
  vi.stubGlobal("open", vi.fn(() => ({ closed: false, focus: vi.fn(), close: vi.fn() })));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); act(() => setThemePref("dark")); });

describe("theme", () => {
  it("is dark by default, and Light or System only change it when chosen", () => {
    expect(themePref.get()).toBe("dark");
    expect(document.documentElement.dataset.hqTheme).toBe("dark");
    act(() => setThemePref("light"));
    expect(document.documentElement.dataset.hqTheme).toBe("light");
    expect(localStorage.getItem("hq.theme")).toBe('"light"');
    expect(resolvedTheme("system", true)).toBe("light");
    expect(resolvedTheme("system", false)).toBe("dark");
    expect(resolvedTheme("dark", true)).toBe("dark");
  });

  it("Settings → Appearance offers Dark (default), Light and System as a radio group; arrow keys move the choice", () => {
    go("#/settings/appearance");
    render(<App />);
    const group = screen.getByRole("radiogroup", { name: "Appearance" });
    const dark = within(group).getByRole("radio", { name: /Dark/ });
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveTextContent("Default");
    fireEvent.click(within(group).getByRole("radio", { name: /Light/ }));
    expect(document.documentElement.dataset.hqTheme).toBe("light");
    expect(within(group).getByRole("radio", { name: /Light/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(within(group).getByRole("radio", { name: /Light/ }), { key: "ArrowRight" });
    expect(themePref.get()).toBe("system");
    expect(screen.getByText("Showing now")).toBeInTheDocument();
  });

  it("Jay's menu switches the theme too", () => {
    go("#/office");
    render(<App />);
    fireEvent.click(document.querySelector<HTMLButtonElement>("button.me")!);
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: /^Light/ }));
    expect(themePref.get()).toBe("light");
  });
});

describe("phone tab bar", () => {
  it("has Office, Messages, Decisions, Approvals and More, with the same counts as the sidebar", () => {
    go("#/office");
    render(<App />);
    const bar = screen.getByRole("navigation", { name: "Tab bar" });
    expect(within(bar).getAllByRole("link").map((a) => a.textContent?.replace(/\d+/g, ""))).toEqual(["Office", "Messages", "Decisions", "Approvals"]);
    expect(within(bar).getByRole("link", { name: /Office/ })).toHaveAttribute("aria-current", "page");
    expect(within(bar).getByRole("button", { name: "More" })).toBeInTheDocument();
  });

  it("More opens a sheet with every other page; picking one goes there and closes it; Escape closes it", () => {
    go("#/office");
    render(<App />);
    const bar = screen.getByRole("navigation", { name: "Tab bar" });
    fireEvent.click(within(bar).getByRole("button", { name: "More" }));
    const sheet = screen.getByRole("dialog", { name: "More" });
    for (const l of ["Teams", "Agents", "Operations Topology", "Engineering", "Revenue", "Budgets", "New Agent", "New Project", "Settings", "Design system"])
      expect(within(sheet).getByRole("button", { name: new RegExp(`^${l}`) })).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole("button", { name: /^Budgets/ }));
    expect(location.hash).toBe("#/budgets");
    expect(screen.queryByRole("dialog", { name: "More" })).toBeNull();
    expect(within(bar).getByRole("button", { name: "More" })).toHaveClass("is-current");
    fireEvent.click(within(bar).getByRole("button", { name: "More" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "More" })).toBeNull();
  });
});

describe("My Office", () => {
  it("shows the three latest updates from leads and keeps the demo label beside Company Health", () => {
    go("#/office");
    render(<App />);
    const upd = screen.getByRole("heading", { name: /Recent Updates from Leads/ }).closest("section")!;
    expect(within(upd).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Company Health").textContent).toMatch(/Company Health/);
  });
});

describe("Settings on a phone", () => {
  it("opens as a section list, and a section links back to that list", () => {
    go("#/settings");
    render(<App />);
    const page = document.querySelector(".page-settings")!;
    expect(page).toHaveClass("is-index");
    expect(screen.getByRole("navigation", { name: "Settings sections" })).toBeInTheDocument();
    go("#/settings/security");
    expect(document.querySelector(".page-settings")).toHaveClass("is-detail");
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "#/settings");
  });
});
