import type { MouseEvent } from "react";
import { prefs, usePrefs } from "../lib/prefs";

/** While the HQ preview is on: a label at the foot of the HQ sidebar, with the way back. So it shows wherever the
 *  sidebar does: not in pop-outs, Workspace Focus or the Connect screen; Settings › General › Interface switches back
 *  there. Nothing in Classic. */
export function HqPreviewTag({ mini = false }: { mini?: boolean }) {
  const ui = usePrefs((p) => p.ui);
  if (ui !== "hq") return null;
  const back = (e: MouseEvent<HTMLButtonElement>) => {
    // The button goes away with the label: keep keyboard focus in the navigation, on the first button below it. In
    // Classic's rail that button stays; the HQ sidebar goes away with HQ, so focus moves to Classic's rail once it is
    // drawn.
    const next = e.currentTarget.closest(".rail")?.querySelector<HTMLElement>(".rail-foot button");
    prefs.patch({ ui: "classic" });
    if (next) next.focus();
    else requestAnimationFrame(() => document.querySelector<HTMLElement>(".rail .rail-foot button")?.focus());
  };
  return <div className="hq-tag">
    {mini
      ? <button type="button" className="btn is-quiet is-sm caps" onClick={back} title="HQ preview. Back to Classic"
          aria-label="HQ preview. Back to Classic">HQ</button>
      : <><span className="caps">HQ preview</span>
        <button type="button" className="btn is-quiet is-sm" onClick={back}>Back to Classic</button></>}
  </div>;
}
