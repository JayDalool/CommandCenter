// ?ui=hq and ?ui=classic: a link that switches this browser between Classic and the HQ preview, exactly as
// Settings › General › Interface does. Read from the query before the "#" (/?ui=hq#/dashboard), saved, then removed
// from the address so a reload or a copied link does not switch again. Every other parameter is kept as it was
// written, and so is the whole hash, so the SSH sign-in code (#/?signin=…) still redeems first. The link carries no
// credential and changes nothing on the server.
import { prefs, type Prefs } from "./prefs";

type Loc = Pick<Location, "search" | "pathname" | "hash">;
type Hist = Pick<History, "replaceState" | "state">;

const isUi = (part: string) => {
  try { return decodeURIComponent(part.split("=")[0].replace(/\+/g, " ")) === "ui"; } catch { return false; }
};

/** Saves the interface named by `?ui=` (any other value is ignored) and takes `ui` out of the address. */
export function takeUiFromUrl(loc: Loc = location, hist: Hist = history): Prefs["ui"] | null {
  const parts = loc.search.replace(/^\?/, "").split("&");
  if (!parts.some(isUi)) return null;
  const value = new URLSearchParams(loc.search).get("ui");
  const ui = value === "hq" || value === "classic" ? value : null;
  if (ui) prefs.patch({ ui });
  const rest = parts.filter((p) => !isUi(p)).join("&");
  try { hist.replaceState(hist.state, "", `${loc.pathname}${rest ? `?${rest}` : ""}${loc.hash}`); }
  catch { /* the address keeps ?ui=; the choice is saved either way */ }
  return ui;
}
