/**
 * The terminal header shows state and only the action that state needs:
 * live → a dot, nothing to press; disconnected → Reconnect; ended → New session.
 * Find, Detach and Close session live under ⋯. Locked → one Unlock, nothing else.
 */
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 80; rows = 24; options: Record<string, unknown> = {};
    loadAddon() {} open() {} focus() {} reset() {} write() {} dispose() {} clearSelection() {}
    hasSelection() { return false; } getSelection() { return ""; }
    attachCustomKeyEventHandler() {}
    onData() { return { dispose() {} }; }
    onBinary() { return { dispose() {} }; }
  },
}));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: class { fit() {} } }));
vi.mock("@xterm/addon-search", () => ({ SearchAddon: class { findNext() {} findPrevious() {} } }));
vi.mock("@xterm/xterm/css/xterm.css", () => ({}));

import { TerminalView } from "../src/workspace/Terminal";
import { setToken } from "../src/api/auth";
import { developer, setDevSession } from "../src/api/developer";
import { app } from "../src/store/app";

type Sock = { onmessage: ((e: { data: unknown }) => void) | null; onclose: ((e: { code: number; reason?: string }) => void) | null; readyState: number };
const socks: Sock[] = [];

beforeEach(() => {
  socks.length = 0;
  class FakeWS {
    static OPEN = 1;
    readyState = 1; binaryType = ""; onmessage = null; onclose = null;
    constructor() { socks.push(this as unknown as Sock); }
    send() {}
    close() {}
  }
  vi.stubGlobal("WebSocket", FakeWS);
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  setToken("t".repeat(43));
});
afterEach(() => { vi.unstubAllGlobals(); setDevSession(null); });

const hello = () => act(() => socks.at(-1)!.onmessage!({ data: JSON.stringify({ t: "hello", cwd: "/srv/x" }) }));

it("live: a dot and the context; Reconnect appears only after a disconnect", async () => {
  setDevSession("s".repeat(43), 3600);
  render(<TerminalView name="repo:SV" label="Project · SamVision" active theme="dark" info="/srv/x · main" />);
  await waitFor(() => expect(socks.length).toBe(1));
  hello();
  expect(screen.getByRole("status", { name: "live" })).toBeInTheDocument();
  expect(screen.getByText("/srv/x · main")).toBeInTheDocument();
  for (const n of ["Reconnect", "Detach", "Close session", "Maximize", "Retry", "New session"])
    expect(screen.queryByRole("button", { name: n })).toBeNull();
  act(() => socks[0].onclose!({ code: 1006 }));
  expect(screen.getByText("DETACHED")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(socks.length).toBe(2));
});

it("Find, Detach and Close session are under ⋯, with extra items after them", async () => {
  setDevSession("s".repeat(43), 3600);
  render(<TerminalView name="server" label="Server" active theme="dark"
    menu={[{ label: "Open in Windows Terminal", href: "commandcenter://terminal/server" }]} />);
  await waitFor(() => expect(socks.length).toBe(1));
  hello();
  fireEvent.click(screen.getByRole("button", { name: "Server actions" }));
  expect(screen.getAllByRole("menuitem").map((m) => m.textContent))
    .toEqual(["Find in output", "Detach this view", "Open in Windows Terminal", "Close session…"]);
  expect(screen.getByRole("menuitem", { name: "Open in Windows Terminal" })).toHaveAttribute("href", "commandcenter://terminal/server");
  fireEvent.click(screen.getByRole("menuitem", { name: "Find in output" }));
  expect(screen.getByRole("textbox", { name: "Find in Server output" })).toBeInTheDocument();
});

it("ended: New session; Close session is gone", async () => {
  setDevSession("s".repeat(43), 3600);
  render(<TerminalView name="server" label="Server" active theme="dark" />);
  await waitFor(() => expect(socks.length).toBe(1));
  hello();
  act(() => socks[0].onmessage!({ data: JSON.stringify({ t: "exit", code: 0 }) }));
  expect(screen.getByRole("button", { name: "New session" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Server actions" }));
  expect(screen.queryByRole("menuitem", { name: "Close session…" })).toBeNull();
});

it("locked: one Unlock and no connection attempt", () => {
  render(<TerminalView name="server" label="Server" active theme="dark" />);
  expect(screen.getByText("DEVELOPER LOCKED")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Unlock" })).toHaveLength(1);
  expect(screen.queryByText(/A real shell runs commands/)).toBeNull();
  expect(socks.length).toBe(0);
});

it("a session ccd no longer knows: the tab locks and shows Unlock, not DETACHED", async () => {
  setDevSession("s".repeat(43), 3600);
  render(<TerminalView name="repo:CC" label="Project · Command Center" active theme="dark" />);
  await waitFor(() => expect(socks.length).toBe(1));
  act(() => socks[0].onclose!({ code: 4403, reason: "Developer Unlock required" }));
  expect(developer.get().active).toBe(false);
  expect(screen.getByText("DEVELOPER LOCKED")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument();
  expect(screen.queryByText("DETACHED")).toBeNull();
});

it("other refusals keep the developer session", async () => {
  setDevSession("s".repeat(43), 3600);
  render(<TerminalView name="claude:XX" label="Claude" active theme="dark" />);
  await waitFor(() => expect(socks.length).toBe(1));
  act(() => socks[0].onclose!({ code: 4404, reason: "unknown terminal" }));
  expect(developer.get().active).toBe(true);
  expect(screen.getByText("REFUSED")).toBeInTheDocument();
});

it("Close session asks in the app's dialog (with the caller's wording); Cancel keeps it, confirm closes once", async () => {
  const native = vi.spyOn(window, "confirm");
  const close = vi.spyOn(app.api, "ptyClose").mockResolvedValue({ ok: true } as never);
  setDevSession("s".repeat(43), 3600);
  render(<TerminalView name="claude:SV" label="Claude" active theme="dark" closeText="Close this view of SV-071's Claude? Only the attach client closes." />);
  await waitFor(() => expect(socks.length).toBe(1));
  hello();
  const open = () => { fireEvent.click(screen.getByRole("button", { name: "Claude actions" })); fireEvent.click(screen.getByRole("menuitem", { name: "Close session…" })); };
  open();
  expect(screen.getByRole("dialog", { name: "Close session?" })).toHaveTextContent("Close this view of SV-071's Claude? Only the attach client closes.");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(close).not.toHaveBeenCalled();
  open();
  fireEvent.click(screen.getByRole("dialog").querySelector<HTMLButtonElement>("button.is-danger")!);
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  expect(close).toHaveBeenCalledWith("claude:SV");
  await waitFor(() => expect(screen.getByText("SESSION ENDED")).toBeInTheDocument());
  expect(native).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});
