// Settings › General › Interface, and the navigation rail's "HQ preview" label with Back to Classic.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Settings } from "../src/screens/Settings";
import { HqPreviewTag } from "../src/components/HqPreview";
import { prefs } from "../src/lib/prefs";

beforeEach(() => { location.hash = "#/settings"; prefs.patch({ ui: "classic" }); });
afterAll(() => prefs.patch({ ui: "classic" }));

describe("Interface in Settings", () => {
  it("shows Classic chosen by default, with the help text", () => {
    render(<Settings />);
    const row = screen.getByRole("group", { name: "Interface" });
    expect(within(row).getByRole("button", { name: "Classic" })).toHaveAttribute("aria-pressed", "true");
    expect(within(row).getByRole("button", { name: "HQ preview" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/HQ preview is the new design, rolled out page by page\. Every page and control works the same\./))
      .toBeInTheDocument();
  });

  it("HQ preview shows the label; Back to Classic removes it", () => {
    render(<><HqPreviewTag /><Settings /></>);
    const row = screen.getByRole("group", { name: "Interface" });
    expect(screen.queryByRole("button", { name: "Back to Classic" })).toBeNull();

    fireEvent.click(within(row).getByRole("button", { name: "HQ preview" }));
    expect(prefs.get().ui).toBe("hq");
    expect(document.documentElement.dataset.ui).toBe("hq");
    expect(document.querySelector(".hq-tag")).toHaveTextContent("HQ preview");

    fireEvent.click(screen.getByRole("button", { name: "Back to Classic" }));
    expect(prefs.get().ui).toBe("classic");
    expect(document.documentElement.hasAttribute("data-ui")).toBe(false);
    expect(document.querySelector(".hq-tag")).toBeNull();
    expect(within(row).getByRole("button", { name: "Classic" })).toHaveAttribute("aria-pressed", "true");
  });

  it("Back to Classic leaves keyboard focus in the rail, on the first button below the label", () => {
    prefs.patch({ ui: "hq" });
    render(<aside className="rail"><HqPreviewTag /><div className="rail-foot"><button type="button">Commands</button></div></aside>);
    const back = screen.getByRole("button", { name: "Back to Classic" });
    back.focus();
    fireEvent.click(back);
    expect(document.querySelector(".hq-tag")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Commands" }));
  });

  it("the icons-only rail shows HQ, named for what it does", () => {
    prefs.patch({ ui: "hq" });
    render(<HqPreviewTag mini />);
    fireEvent.click(screen.getByRole("button", { name: "HQ preview. Back to Classic" }));
    expect(prefs.get().ui).toBe("classic");
    expect(document.querySelector(".hq-tag")).toBeNull();
  });
});
