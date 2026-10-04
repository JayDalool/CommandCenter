import { nativeUri } from "../src/workspace/Native";

describe("native terminal links", () => {
  it("names only an action and a registered-shaped prefix", () => {
    expect(nativeUri("claude", "SV")).toBe("commandcenter://terminal/claude?project=SV");
    expect(nativeUri("repo", "GZ")).toBe("commandcenter://terminal/repo?project=GZ");
    expect(nativeUri("repo", "GYST")).toBe("commandcenter://terminal/repo?project=GYST");
    expect(nativeUri("server")).toBe("commandcenter://terminal/server");
    expect(nativeUri("server", "SV")).toBe("commandcenter://terminal/server");
  });
  it("refuses anything that is not a prefix", () => {
    for (const bad of [null, "", "sv", "SV;calc", "SV&cmd=x", "../etc", "/srv", "S", "TOOLONGX", "SV ", "SV\n"]) {
      expect(nativeUri("repo", bad as string | null)).toBeNull();
      expect(nativeUri("claude", bad as string | null)).toBeNull();
    }
  });
});
