// The HQ pages that replace a Classic screen at the same address while the HQ preview is on (hq/frame/Frame.tsx).
// Every other address shows the Classic screen inside the frame. Classic itself never loads these.
import { Office } from "./Office";

export const HQ_PAGES: Record<string, () => React.JSX.Element> = { dashboard: Office, overview: Office };
