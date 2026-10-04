import { isChunkLoadError, reloadOnce, registerUnsaved, staleBuild, handleChunkError } from "../src/lib/stale";

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

describe("stale build recovery", () => {
  it("recognises chunk-load failures from every browser, and nothing else", () => {
    for (const m of ["TypeError: Failed to fetch dynamically imported module: http://127.0.0.1:7777/assets/monaco-s93JKSES.js",
      "TypeError: Importing a module script failed.", "TypeError: error loading dynamically imported module", "Unable to preload CSS for /assets/x.css"]) {
      expect(isChunkLoadError(new TypeError(m.replace(/^TypeError: /, "")))).toBe(true);
    }
    for (const m of ["ccd unreachable", "HTTP 404", "the file changed on disk", ""]) expect(isChunkLoadError(new Error(m))).toBe(false);
  });

  it("reloads once, never in a loop", () => {
    const s = new Mem();
    let reloads = 0;
    expect(reloadOnce(1_000_000, s, () => reloads++)).toBe(true);
    expect(reloadOnce(1_010_000, s, () => reloads++)).toBe(false);   // 10 s later: same failure again → no loop
    expect(reloadOnce(1_070_001, s, () => reloads++)).toBe(true);    // a later, separate update may reload again
    expect(reloads).toBe(2);
  });

  it("never reloads over unsaved work", () => {
    const off = registerUnsaved(() => true);
    let reloads = 0;
    expect(reloadOnce(5_000_000, new Mem(), () => reloads++)).toBe(false);
    expect(reloads).toBe(0);
    off();
  });

  it("flags the window as updated for the banner", () => {
    const off = registerUnsaved(() => true);  // keep jsdom from navigating
    expect(handleChunkError(new TypeError("Failed to fetch dynamically imported module: /assets/monaco-x.js"))).toBe(true);
    expect(staleBuild.get().updated).toBe(true);
    expect(handleChunkError(new Error("ccd unreachable"))).toBe(false);
    off();
  });
});
