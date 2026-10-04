import { lazyOnce } from "../src/workspace/Editor";

describe("lazy chunk loader", () => {
  it("retries after a failed import and shares one in-flight load", async () => {
    let calls = 0;
    let fail = true;
    const load = lazyOnce(async () => {
      calls++;
      if (fail) throw new TypeError("Failed to fetch dynamically imported module: /assets/monaco-s93JKSES.js");
      return { editor: {} };
    }, (m) => !!m?.editor);
    await expect(load()).rejects.toThrow(/dynamically imported module/);
    fail = false;
    const [a, b] = await Promise.all([load(), load()]);   // second open after the failure: works
    expect(a).toBe(b);
    expect(calls).toBe(2);
    await load();
    expect(calls).toBe(2);                                // cached once it succeeded
  });

  it("treats a module that resolved empty as a failure (Vite's cancelled preloadError)", async () => {
    let calls = 0;
    const load = lazyOnce(async () => { calls++; return calls === 1 ? undefined : { editor: {} }; },
      (m: { editor?: unknown } | undefined) => !!m?.editor);
    await expect(load()).rejects.toThrow(/dynamically imported module/);
    await expect(load()).resolves.toEqual({ editor: {} });
  });
});
