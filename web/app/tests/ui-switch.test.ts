// ?ui=hq and ?ui=classic (lib/uiSwitch.ts): the choice is saved and `ui` leaves the address; everything else in the
// address, the SSH sign-in code in the hash above all, is kept exactly.
import { takeUiFromUrl } from "../src/lib/uiSwitch";
import { prefs } from "../src/lib/prefs";

function open(search: string, hash = "#/dashboard", pathname = "/") {
  const urls: string[] = [];
  const hist = { state: { keep: 1 }, replaceState(s: unknown, _t: string, url?: string | URL | null) {
    expect(s).toEqual({ keep: 1 });
    urls.push(String(url));
  } };
  return { ui: takeUiFromUrl({ search, hash, pathname }, hist), urls };
}

beforeEach(() => prefs.patch({ ui: "classic" }));
afterAll(() => prefs.patch({ ui: "classic" }));

describe("?ui= in the address", () => {
  it("?ui=hq turns the HQ preview on and leaves the address without ui", () => {
    expect(open("?ui=hq")).toEqual({ ui: "hq", urls: ["/#/dashboard"] });
    expect(prefs.get().ui).toBe("hq");
    expect(document.documentElement.dataset.ui).toBe("hq");
  });

  it("?ui=classic goes back to Classic", () => {
    prefs.patch({ ui: "hq" });
    expect(open("?ui=classic")).toEqual({ ui: "classic", urls: ["/#/dashboard"] });
    expect(prefs.get().ui).toBe("classic");
    expect(document.documentElement.hasAttribute("data-ui")).toBe(false);
  });

  it("keeps every other parameter as written, the path, and the whole hash with the sign-in code", () => {
    expect(open("?a=1&ui=hq&b=two%20words&c", "#/?signin=AbC-123_xyz", "/app/").urls)
      .toEqual(["/app/?a=1&b=two%20words&c#/?signin=AbC-123_xyz"]);
    expect(open("?ui=classic", "#/workspace?project=gyst&ui=hq").urls).toEqual(["/#/workspace?project=gyst&ui=hq"]);
  });

  it("ignores any other value, from either mode, but still takes it out of the address", () => {
    for (const from of ["classic", "hq"] as const) {
      for (const bad of ["?ui=HQ", "?ui=", "?ui", "?ui=hq%20", "?ui=1", "?ui=%3Cscript%3E"]) {
        prefs.patch({ ui: from });
        expect(open(bad), bad).toEqual({ ui: null, urls: ["/#/dashboard"] });
        expect(prefs.get().ui, `${bad} from ${from}`).toBe(from);
      }
    }
  });

  it("keeps empty parameters as written", () => {
    expect(open("?a=1&&ui=hq&b").urls).toEqual(["/?a=1&&b#/dashboard"]);
  });

  it("does nothing when the address has no ui", () => {
    expect(open("")).toEqual({ ui: null, urls: [] });
    expect(open("?a=1&build=ui")).toEqual({ ui: null, urls: [] });
  });
});
