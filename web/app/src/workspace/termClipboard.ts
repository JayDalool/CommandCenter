// Clipboard and input pacing for every browser terminal (Claude, Repo shell, Server shell).
//
// Why paste did not work: xterm.js maps every Ctrl+<letter> keydown to its C0 control
// byte — Ctrl+V became "\x16" — and then cancels the event, so the browser never fired
// the native `paste` event that xterm's own paste listener handles. The fix is not to
// read the clipboard ourselves: for the paste keys we tell xterm to step aside, the
// browser fires `paste` on xterm's focused textarea, and xterm does what a terminal
// should (CR line endings, bracketed paste when the program enabled it). Nothing here
// reads, logs or keeps clipboard contents.
//
// Copy: Ctrl+C copies only when text is selected; with no selection it still reaches
// the PTY as ^C (interrupt). So selecting Claude's output and pressing Ctrl+C never
// interrupts Claude.
import type { Terminal } from "@xterm/xterm";

export type KeyAction = "native-paste" | "copy" | "xterm";

/** What a keydown inside the terminal should do. Pure, for tests. */
export function terminalKeyAction(e: Pick<KeyboardEvent, "type" | "key" | "code" | "ctrlKey" | "shiftKey" | "altKey" | "metaKey">,
  hasSelection: boolean): KeyAction {
  if (e.type !== "keydown") return "xterm";
  // On a non-Latin layout (Arabic, Russian…) e.key is the layout's character, but xterm still
  // maps the physical key to a control byte, so fall back to the physical key (e.code).
  const k = /^[a-z]$/i.test(e.key) ? e.key.toLowerCase() : /^Key[A-Z]$/.test(e.code) ? e.code.slice(3).toLowerCase() : e.key.toLowerCase();
  const ctrlOnly = e.ctrlKey && !e.altKey && !e.metaKey;
  if (ctrlOnly && k === "v") return "native-paste";                                  // Ctrl+V, Ctrl+Shift+V
  if (e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey && e.key === "Insert") return "native-paste"; // Shift+Insert
  if (ctrlOnly && (k === "c" || e.key === "Insert") && hasSelection) return "copy";   // Ctrl+C / Ctrl+Insert with a selection
  return "xterm";                                                                    // everything else, incl. Ctrl+C with no selection
}

/** Install on a terminal. `copy` defaults to the async Clipboard API (127.0.0.1 is a secure context). */
export function installClipboard(t: Pick<Terminal, "attachCustomKeyEventHandler" | "hasSelection" | "getSelection" | "clearSelection">,
  copy: (text: string) => Promise<void> = (text) => navigator.clipboard.writeText(text)) {
  t.attachCustomKeyEventHandler((e) => {
    const action = terminalKeyAction(e, t.hasSelection());
    if (action === "native-paste") return false;   // xterm ignores the key; the browser's paste event follows
    if (action === "copy") {
      e.preventDefault();
      const text = t.getSelection();
      void copy(text).catch(() => undefined);
      t.clearSelection();                          // the next Ctrl+C interrupts again
      return false;
    }
    return true;
  });
}

// ---------- input pacing ----------
// ccd takes at most 64 KiB per input message and queues at most 256 KiB for a PTY that is
// not reading. A big paste is therefore sent in code-point-safe chunks, one at a time, with
// a short pause, and never more than MAX_PASTE in total (larger: refused with a visible note).
export const CHUNK_CHARS = 4096;        // ≤ 16 KiB of UTF-8 per message
export const MAX_PASTE = 1024 * 1024;   // characters
export const CHUNK_GAP_MS = 15;

/** Split without breaking a surrogate pair (emoji, rare scripts). Joining the parts gives the input back exactly. */
export function chunkInput(data: string, size = CHUNK_CHARS): string[] {
  if (data.length <= size) return [data];
  const out: string[] = [];
  let i = 0;
  while (i < data.length) {
    let end = Math.min(i + size, data.length);
    const c = data.charCodeAt(end - 1);
    if (end < data.length && end - i > 1 && c >= 0xd800 && c <= 0xdbff) end--;   // don't split a high surrogate from its pair
    out.push(data.slice(i, end));
    i = end;
  }
  return out;
}

/** An ordered sender: typing and pastes go out in order; large input is paced.
 *  One FIFO: keys typed during a paced paste (Ctrl+C too) go out after it — at most ~4 s for
 *  a 1 MiB paste. Chunks still queued when the socket is replaced go to the new socket. */
export function makeInputSender(send: (d: string) => boolean, note: (msg: string) => void,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms))) {
  const queue: string[] = [];
  let running = false;
  const pump = async () => {
    if (running) return;
    running = true;
    try {
      while (queue.length) {
        const part = queue.shift()!;
        if (!send(part)) { queue.length = 0; break; }   // socket gone: drop the rest, never resend later
        if (queue.length) await sleep(CHUNK_GAP_MS);
      }
    } finally {
      running = false;
    }
  };
  return (data: string) => {
    if (data.length > MAX_PASTE) {
      note(`\r\n\x1b[33m[paste not sent: ${Math.round(data.length / 1024)} KB is over the ${MAX_PASTE / 1024} KB limit]\x1b[0m\r\n`);
      return;
    }
    queue.push(...chunkInput(data));
    void pump();
  };
}
