import { prefs, usePrefs } from "../lib/prefs";

/** While the HQ preview is on: a label at the foot of the navigation rail, on every screen, with the way back.
 *  Nothing in Classic, and nothing in pop-outs (they have no rail). */
export function HqPreviewTag({ mini = false }: { mini?: boolean }) {
  const ui = usePrefs((p) => p.ui);
  if (ui !== "hq") return null;
  const back = () => prefs.patch({ ui: "classic" });
  return <div className="hq-tag">
    {mini
      ? <button type="button" className="btn is-quiet is-sm caps" onClick={back} title="HQ preview. Back to Classic"
          aria-label="HQ preview. Back to Classic">HQ</button>
      : <><span className="caps">HQ preview</span>
        <button type="button" className="btn is-quiet is-sm" onClick={back}>Back to Classic</button></>}
  </div>;
}
