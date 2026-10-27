// The Interface preference (P0.2): Classic unless the stored value is exactly "hq", and switching touches nothing
// but cc.prefs and <html data-ui>.
import { vi } from "vitest";
import { apply, parsePrefs, prefs } from "../src/lib/prefs";

afterEach(() => { vi.restoreAllMocks(); prefs.patch({ ui: "classic" }); });

describe("the Interface preference", () => {
  it("is Classic unless the stored value is exactly \"hq\"", () => {
    expect(parsePrefs(null).ui).toBe("classic");
    expect(parsePrefs("{}").ui).toBe("classic");
    expect(parsePrefs("not json").ui).toBe("classic");
    for (const bad of ['"HQ"', "1", "null", "true", '"classic "', '"hq "', '["hq"]', '{"v":"hq"}',
      '"<img src=x onerror=alert(1)>"', '"javascript:alert(1)"']) {
      expect(parsePrefs(`{"ui":${bad}}`).ui, bad).toBe("classic");
    }
    expect(parsePrefs('{"ui":"hq"}').ui).toBe("hq");
  });

  it("leaves every other preference as it was stored", () => {
    const old = '{"theme":"light","density":"compact","railCollapsed":true,"wsLeft":"tasks","sshHost":"box"}';
    const { ui: a, ...before } = parsePrefs(old);
    const { ui: b, ...after } = parsePrefs(old.replace("{", '{"ui":"hq",'));
    expect([a, b]).toEqual(["classic", "hq"]);
    expect(after).toEqual(before);
  });

  it("apply() adds data-ui only for HQ, and theme and density stay as they are", () => {
    const root = document.documentElement;
    const base = { ...parsePrefs(null), theme: "light" as const, density: "compact" as const };
    apply(base);
    expect(root.getAttributeNames().sort()).toEqual(["data-density", "data-theme"]);
    apply({ ...base, ui: "hq" });
    expect(root.dataset).toMatchObject({ ui: "hq", theme: "light", density: "compact" });
    apply(base);
    expect(root.hasAttribute("data-ui")).toBe(false);
    expect(root.dataset).toMatchObject({ theme: "light", density: "compact" });
  });

  it("is saved with the other preferences in cc.prefs", () => {
    prefs.patch({ ui: "hq" });
    expect(JSON.parse(localStorage.getItem("cc.prefs")!).ui).toBe("hq");
    expect(document.documentElement.dataset.ui).toBe("hq");
    prefs.patch({ ui: "classic" });
    expect(JSON.parse(localStorage.getItem("cc.prefs")!).ui).toBe("classic");
    expect(document.documentElement.hasAttribute("data-ui")).toBe(false);
  });

  it("switching never reads or writes the token, the Developer session or Workspace layouts", () => {
    sessionStorage.setItem("ccd.token", "t".repeat(43));
    localStorage.setItem("cc.rooms", "[]");
    const touched: string[] = [];
    for (const method of ["getItem", "setItem", "removeItem"] as const) {
      const real = Storage.prototype[method] as (...a: unknown[]) => unknown;
      vi.spyOn(Storage.prototype, method).mockImplementation(function (this: Storage, ...a: unknown[]) {
        touched.push(String(a[0]));
        return real.apply(this, a);
      } as never);
    }
    prefs.patch({ ui: "hq" });
    prefs.patch({ ui: "classic" });
    expect(new Set(touched)).toEqual(new Set(["cc.prefs"]));
    vi.restoreAllMocks();
    expect(sessionStorage.getItem("ccd.token")).toBe("t".repeat(43));
    expect(localStorage.getItem("cc.rooms")).toBe("[]");
  });
});
