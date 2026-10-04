/**
 * Clipboard in the browser terminals (Claude, Repo shell, Server shell share one component).
 * Root cause pinned here: xterm turns Ctrl+V into "\x16" and cancels the key, so the browser never
 * fires `paste`. Our key handler steps xterm aside for the paste keys; xterm's own paste listener
 * then delivers the text (bracketed when the program asked for it). Copy happens only with a selection.
 */
import { render, waitFor, act } from "@testing-library/react";
import { vi } from "vitest";
import { terminalKeyAction, installClipboard, chunkInput, makeInputSender, MAX_PASTE } from "../src/workspace/termClipboard";

const key = (k: string, mods: Partial<KeyboardEvent> = {}, code = "") =>
  ({ type: "keydown", key: k, code, ctrlKey: false, shiftKey: false, altKey: false, metaKey: false, ...mods }) as KeyboardEvent;

describe("terminal key decisions", () => {
  it("lets the browser paste on Ctrl+V, Ctrl+Shift+V and Shift+Insert", () => {
    expect(terminalKeyAction(key("v", { ctrlKey: true }), false)).toBe("native-paste");
    expect(terminalKeyAction(key("V", { ctrlKey: true, shiftKey: true }), false)).toBe("native-paste");
    expect(terminalKeyAction(key("Insert", { shiftKey: true }), false)).toBe("native-paste");
  });
  it("copies with a selection, interrupts without one", () => {
    expect(terminalKeyAction(key("c", { ctrlKey: true }), true)).toBe("copy");
    expect(terminalKeyAction(key("c", { ctrlKey: true }), false)).toBe("xterm");          // ^C reaches the PTY
    expect(terminalKeyAction(key("C", { ctrlKey: true, shiftKey: true }), true)).toBe("copy");
  });
  it("leaves every other terminal key to xterm", () => {
    for (const k of [key("d", { ctrlKey: true }), key("z", { ctrlKey: true }), key("Escape"), key("ArrowUp"), key("Tab"),
      key("Enter"), key("a"), key("v", { altKey: true }), key("v", { ctrlKey: true, metaKey: true })]) {
      expect(terminalKeyAction(k, false)).toBe("xterm");
    }
    expect(terminalKeyAction({ ...key("v", { ctrlKey: true }), type: "keyup" } as KeyboardEvent, false)).toBe("xterm");
  });
});

describe("installClipboard", () => {
  function fakeTerm(selection = "") {
    let handler: ((e: KeyboardEvent) => boolean) | null = null;
    const t = {
      attachCustomKeyEventHandler: (h: (e: KeyboardEvent) => boolean) => { handler = h; },
      hasSelection: () => selection.length > 0, getSelection: () => selection, clearSelection: vi.fn(),
    };
    return { t, press: (e: KeyboardEvent) => handler!(e) };
  }
  it("Ctrl+V: xterm steps aside and nothing is read or prevented by us", () => {
    const { t, press } = fakeTerm();
    const copy = vi.fn(async () => {});
    installClipboard(t, copy);
    const e = { ...key("v", { ctrlKey: true }), preventDefault: vi.fn() } as unknown as KeyboardEvent;
    expect(press(e)).toBe(false);
    expect(e.preventDefault).not.toHaveBeenCalled();   // the browser must still fire its paste event
    expect(copy).not.toHaveBeenCalled();
  });
  it("Ctrl+C with a selection copies exactly the selection and does not interrupt", () => {
    const { t, press } = fakeTerm("Claude said:\nexact text");
    const copy = vi.fn(async (_s: string) => {});
    installClipboard(t, copy);
    const e = { ...key("c", { ctrlKey: true }), preventDefault: vi.fn() } as unknown as KeyboardEvent;
    expect(press(e)).toBe(false);                      // xterm does not send ^C
    expect(copy).toHaveBeenCalledWith("Claude said:\nexact text");
    expect(t.clearSelection).toHaveBeenCalled();
  });
  it("Ctrl+C without a selection is left to xterm (^C to the PTY)", () => {
    const { t, press } = fakeTerm("");
    const copy = vi.fn(async () => {});
    installClipboard(t, copy);
    expect(press(key("c", { ctrlKey: true }))).toBe(true);
    expect(copy).not.toHaveBeenCalled();
  });
});

describe("input pacing", () => {
  const multiline = "Please inspect these files:\r\rsrc/app.py\rsrc/api.py\r\rThen:\r1. run tests\r2. explain failures\r3. do not deploy";
  it("chunks rejoin to the exact input, never splitting a surrogate pair", () => {
    const text = ("مرحبا 👋 code:\tdef f():\r    return 1\r").repeat(800);
    const parts = chunkInput(text, 100);
    expect(parts.join("")).toBe(text);
    for (const p of parts) expect(/^[\udc00-\udfff]/.test(p)).toBe(false);
    expect(chunkInput(multiline)).toEqual([multiline]);
  });
  it("sends multiline, Unicode and long input intact, in order, with no Enter added", async () => {
    const sent: string[] = [];
    const sender = makeInputSender((d) => { sent.push(d); return true; }, () => {}, async () => {});
    const unicode = "شكرا — 日本語 — ✓";
    const long = "x".repeat(50_000);
    sender(multiline); sender(unicode); sender(long);
    await waitFor(() => expect(sent.join("")).toBe(multiline + unicode + long));
    expect(sent.join("").endsWith("\r")).toBe(false);
    expect(Math.max(...sent.map((s) => s.length))).toBeLessThanOrEqual(4096);
  });
  it("refuses an oversized paste visibly instead of truncating it", () => {
    const sent: string[] = [];
    const notes: string[] = [];
    const sender = makeInputSender((d) => { sent.push(d); return true; }, (m) => notes.push(m), async () => {});
    sender("y".repeat(MAX_PASTE + 1));
    expect(sent).toEqual([]);
    expect(notes[0]).toMatch(/paste not sent/);
  });
  it("never logs what is pasted", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m));
    const sender = makeInputSender(() => true, () => {}, async () => {});
    sender("secret-looking paste");
    await new Promise((r) => setTimeout(r, 0));
    for (const s of spies) { expect(s).not.toHaveBeenCalled(); s.mockRestore(); }
  });
});

// ---------- the real TerminalView, for all three terminal kinds ----------
const terms: { handler: ((e: KeyboardEvent) => boolean) | null; data: ((d: string) => void) | null }[] = [];
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 80; rows = 24; options: Record<string, unknown> = {};
    rec = { handler: null as ((e: KeyboardEvent) => boolean) | null, data: null as ((d: string) => void) | null };
    constructor() { terms.push(this.rec); }
    loadAddon() {} open() {} focus() {} reset() {} write() {} dispose() {} clearSelection() {}
    hasSelection() { return false; } getSelection() { return ""; }
    attachCustomKeyEventHandler(h: (e: KeyboardEvent) => boolean) { this.rec.handler = h; }
    onData(cb: (d: string) => void) { this.rec.data = cb; return { dispose() {} }; }
    onBinary() { return { dispose() {} }; }
  },
}));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: class { fit() {} } }));
vi.mock("@xterm/addon-search", () => ({ SearchAddon: class { findNext() {} findPrevious() {} } }));
vi.mock("@xterm/xterm/css/xterm.css", () => ({}));

describe("TerminalView paste in Claude, Repo shell and Server shell", () => {
  const sockets: { url: string; sent: string[] }[] = [];
  beforeEach(() => {
    terms.length = 0;
    sockets.length = 0;
    class FakeWS {
      static OPEN = 1;
      readyState = 1; binaryType = ""; onmessage = null; onclose = null;
      rec = { url: "", sent: [] as string[] };
      constructor(url: string) { this.rec.url = url; sockets.push(this.rec); }
      send(d: string) { this.rec.sent.push(d); }
      close() {}
    }
    vi.stubGlobal("WebSocket", FakeWS);
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  });
  afterEach(() => vi.unstubAllGlobals());

  for (const name of ["claude:SV", "repo:SV", "server"]) {
    it(`${name}: Ctrl+V is left to the browser and pasted text reaches the PTY unchanged`, async () => {
      const { setToken } = await import("../src/api/auth");
      const { setDevSession } = await import("../src/api/developer");
      const { TerminalView } = await import("../src/workspace/Terminal");
      setToken("t".repeat(43));
      setDevSession("s".repeat(43), 3600);
      render(<TerminalView name={name} label={name} active theme="dark" />);
      await waitFor(() => expect(terms.length).toBe(1));
      const rec = terms[0];
      expect(rec.handler!({ ...key("v", { ctrlKey: true }), preventDefault() {} } as unknown as KeyboardEvent)).toBe(false);
      await waitFor(() => expect(sockets.length).toBe(1));
      expect(sockets[0].url).toContain(`/api/pty/${encodeURIComponent(name)}`);
      // what xterm's own paste listener emits for a bracketed multiline paste
      const pasted = "\x1b[200~line one\rline two\x1b[201~";
      act(() => rec.data!(pasted));
      await waitFor(() => expect(sockets[0].sent.map((s) => JSON.parse(s).d).join("")).toBe(pasted));
      setDevSession(null);
    });
  }
});
