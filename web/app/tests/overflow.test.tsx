/** The ⋯ menu: keyboard-complete, focus always returns to ⋯, hidden items never render. */
import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { Overflow } from "../src/components/Overflow";
import { parsePrefs } from "../src/lib/prefs";

it("opens on click, arrows move and wrap, Escape closes and returns focus", () => {
  render(<Overflow label="Server actions" items={[{ label: "One", onSelect: () => {} }, { label: "Hidden", hidden: true },
    { label: "Two", href: "commandcenter://terminal/server" }]} />);
  const btn = screen.getByRole("button", { name: "Server actions" });
  fireEvent.click(btn);
  expect(btn).toHaveAttribute("aria-expanded", "true");
  const items = screen.getAllByRole("menuitem");
  expect(items.map((i) => i.textContent)).toEqual(["One", "Two"]);
  expect(document.activeElement).toBe(items[0]);
  fireEvent.keyDown(items[0], { key: "ArrowDown" });
  expect(document.activeElement).toBe(items[1]);
  fireEvent.keyDown(items[1], { key: "ArrowDown" });
  expect(document.activeElement).toBe(items[0]);
  fireEvent.keyDown(items[0], { key: "ArrowUp" });
  expect(document.activeElement).toBe(items[1]);
  fireEvent.keyDown(items[1], { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(btn);
});

it("choosing an action closes the menu, runs it once and returns focus; outside click closes", () => {
  const run = vi.fn();
  render(<><Overflow label="Actions" items={[{ label: "Do it", onSelect: run }]} /><p>outside</p></>);
  const btn = screen.getByRole("button", { name: "Actions" });
  fireEvent.click(btn);
  fireEvent.click(screen.getByRole("menuitem", { name: "Do it" }));
  expect(run).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(btn);
  fireEvent.click(btn);
  fireEvent.mouseDown(screen.getByText("outside"));
  expect(screen.queryByRole("menu")).toBeNull();
});

it("renders nothing when every item is hidden", () => {
  const { container } = render(<Overflow label="x" items={[{ label: "a", hidden: true }]} />);
  expect(container.innerHTML).toBe("");
});

it("stored prefs from the old quick console are dropped", () => {
  const p = parsePrefs(JSON.stringify({ consoleOpen: true, consoleAgent: "wE:p2", consoleFull: true, consoleFollow: false, theme: "light" }));
  expect(p.theme).toBe("light");
  for (const k of ["consoleOpen", "consoleAgent", "consoleFull", "consoleFollow"]) expect(k in p).toBe(false);
});
