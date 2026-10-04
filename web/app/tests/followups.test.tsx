/** CC-010 follow-ups: helper textareas are not drafts, the herdr-busy detector only reads the
 *  attach preamble, and the editor never says "reloading" unless a reload started. */
import { render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { vi } from "vitest";

const h = vi.hoisted(() => ({ started: false }));

vi.mock("../src/workspace/monaco", () => ({
  get monaco(): never { throw new TypeError("Failed to fetch dynamically imported module: /assets/monaco-x.js"); },
}));
vi.mock("../src/lib/stale", async (orig) => {
  const m = await orig<typeof import("../src/lib/stale")>();
  return { ...m, recoverFromChunkError: (e: unknown) => m.recoverFromChunkError(e, async () => h.started) };
});

import { hasUnsavedWork } from "../src/lib/stale";
import { busyDetector } from "../src/workspace/Terminal";
import { CodeEditor, type EditorHandle } from "../src/workspace/Editor";

describe("hasUnsavedWork ignores editor and terminal helper textareas", () => {
  afterEach(() => { document.body.innerHTML = ""; });
  it("Monaco's and xterm's hidden textareas do not count, a real draft does", () => {
    document.body.innerHTML = `<div class="monaco-editor"><textarea class="inputarea">x</textarea></div>
      <div class="xterm"><textarea class="xterm-helper-textarea">y</textarea><textarea>z</textarea></div>
      <textarea class="xterm-helper-textarea">q</textarea>`;
    for (const t of Array.from(document.querySelectorAll("textarea"))) t.value = "typed";
    expect(hasUnsavedWork()).toBe(false);
    const draft = document.createElement("textarea");
    draft.value = "commit message";
    document.body.append(draft);
    expect(hasUnsavedWork()).toBe(true);
  });
});

describe("busyDetector", () => {
  const enc = (s: string) => new TextEncoder().encode(s);
  it("sees the refusal in the preamble, even split across chunks", () => {
    const d = busyDetector();
    expect(d(enc("herdr: pane w1:p2 already has an at"))).toBe(false);
    expect(d(enc("tached client\r\n"))).toBe(true);
  });
  it("ignores the same text once Claude has printed a lot of other output", () => {
    const d = busyDetector(8 * 1024);
    expect(d(enc("x".repeat(9000)))).toBe(false);
    expect(d(enc("the pane already has an attached client"))).toBe(false);
  });
});

describe("CodeEditor stale-build message", () => {
  const mount = () => render(<CodeEditor path="a.py" text="" version={1} theme="dark"
    handle={createRef<EditorHandle | null>() as React.RefObject<EditorHandle | null>} onChange={() => {}} onSave={() => {}} />);
  it("does not claim to be reloading when the reload was declined", async () => {
    h.started = false;
    mount();
    await screen.findByText(/reload to continue/);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/reloading/)).toBeNull();
  });
  it("says reloading once a reload actually started", async () => {
    h.started = true;
    mount();
    await waitFor(() => expect(screen.getByText(/reloading to the new version/)).toBeTruthy());
  });
});
