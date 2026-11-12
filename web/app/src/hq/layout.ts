// One fact both Classic's shell and HQ's frame need: in a window up to 1440px wide the HQ sidebar is icons only, as in
// the prototype (hq/tokens.css, --hq-side-w). Kept out of the frame's chunk so Shell.tsx can read it without loading it.
export const HQ_NARROW = "(max-width: 1440px)";
export const hqMedia = (): MediaQueryList | null =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(HQ_NARROW) : null;
