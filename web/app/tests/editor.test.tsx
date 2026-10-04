/**
 * The editor's lazy load: mounting CodeEditor loads Monaco once, opens a file as a model,
 * opens a second file in the same editor. (Recovery from a failed chunk load is covered in
 * stale.test.ts; the loader no longer caches a failed import.)
 */
import { render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { vi } from "vitest";

const created: { value: string; lang: string }[] = [];
let setModelCalls = 0;

vi.mock("../src/workspace/monaco", () => {
  const model = (value: string, lang: string) => {
    const m = { value, lang, getValue: () => m.value, setValue: (v: string) => { m.value = v; }, dispose: () => {},
      onDidChangeContent: () => ({ dispose() {} }) };
    created.push({ value, lang });
    return m;
  };
  let current: unknown = null;
  return {
    monaco: {
      KeyMod: { CtrlCmd: 1 }, KeyCode: { KeyS: 2 },
      editor: {
        create: () => ({ addCommand() {}, dispose() {}, getModel: () => current, setModel: (m: unknown) => { current = m; setModelCalls++; },
          layout() {}, revealLineInCenter() {}, setPosition() {}, focus() {} }),
        createModel: model, setTheme() {},
      },
    },
  };
});

import { CodeEditor, type EditorHandle } from "../src/workspace/Editor";

describe("CodeEditor lazy load", () => {
  it("mounts Monaco, opens a file, then a second file in the same editor", async () => {
    const handle = createRef<EditorHandle | null>() as React.RefObject<EditorHandle | null>;
    const { rerender } = render(<CodeEditor path="samvision:src/a.py" text={"print(1)\n"} version={1} theme="dark"
      handle={handle} onChange={() => {}} onSave={() => {}} />);
    await waitFor(() => expect(created.some((c) => c.lang === "python")).toBe(true));
    expect(screen.queryByText(/Editor failed to load/)).toBeNull();
    rerender(<CodeEditor path="samvision:web/b.ts" text={"export {}\n"} version={2} theme="dark"
      handle={handle} onChange={() => {}} onSave={() => {}} />);
    await waitFor(() => expect(created.some((c) => c.lang === "typescript")).toBe(true));
    expect(setModelCalls).toBeGreaterThanOrEqual(2);
    expect(handle.current?.value("samvision:src/a.py")).toBe("print(1)\n");
  });
});
