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

  const up = async () => true, down = async () => false;

  it("reloads once, never in a loop", async () => {
    const s = new Mem();
    let reloads = 0;
    expect(await reloadOnce(1_000_000, s, () => reloads++, up)).toBe(true);
    expect(await reloadOnce(1_010_000, s, () => reloads++, up)).toBe(false);   // same failure again → no loop
    expect(await reloadOnce(1_070_001, s, () => reloads++, up)).toBe(true);    // a later, separate update
    expect(reloads).toBe(2);
  });

  it("never reloads over unsaved work, without storage, or when the server is down", async () => {
    let reloads = 0;
    const off = registerUnsaved(() => true);
    expect(await reloadOnce(5_000_000, new Mem(), () => reloads++, up)).toBe(false);
    off();
    expect(await reloadOnce(5_000_000, null, () => reloads++, up)).toBe(false);         // no way to remember → no auto reload
    expect(await reloadOnce(5_000_000, new Mem(), () => reloads++, down)).toBe(false);  // offline is not an update
    const ta = document.createElement("textarea");
    ta.value = "half-written commit message";
    document.body.appendChild(ta);
    expect(await reloadOnce(9_000_000, new Mem(), () => reloads++, up)).toBe(false);
    ta.remove();
    expect(reloads).toBe(0);
  });

  it("flags the window as updated for the banner", () => {
    const off = registerUnsaved(() => true);  // keep jsdom from navigating
    expect(handleChunkError(new TypeError("Failed to fetch dynamically imported module: /assets/monaco-x.js"))).toBe(true);
    expect(staleBuild.get().updated).toBe(true);
    expect(handleChunkError(new Error("ccd unreachable"))).toBe(false);
    off();
  });
});
