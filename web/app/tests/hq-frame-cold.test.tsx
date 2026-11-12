// The HQ frame when its chunk is not loaded yet (a cold start with HQ on, or the first switch in a window). Its own
// file so the frame module starts unloaded: hq-frame.test.tsx loads it before rendering.
import { useState } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { prefs } from "../src/lib/prefs";
import { AppShell } from "../src/components/Shell";

afterEach(() => { cleanup(); prefs.patch({ ui: "classic", wsFocus: false }); });

it("mounts the screen once when the frame finishes loading after the first render, across Workspace Focus", async () => {
  let mounts = 0;
  function Probe() { useState(() => { mounts++; return 0; }); return <p>screen</p>; }
  prefs.patch({ ui: "hq", wsFocus: false });
  location.hash = "#/workspace";
  render(<AppShell flush><Probe /></AppShell>);
  expect(await screen.findByText("screen")).toBeInTheDocument();
  expect(document.querySelector(".hq-side")).not.toBeNull();
  await act(async () => { prefs.patch({ wsFocus: true }); });
  expect(document.querySelector(".hq-shell.is-focus")).not.toBeNull();
  await act(async () => { prefs.patch({ wsFocus: false }); });
  expect(document.querySelector(".hq-side")).not.toBeNull();
  expect(mounts).toBe(1);
});
