import { useId } from "react";
// The approved prototype's stroke icons (design/ui-prototypes/engineering-hq/src/components/Icon.tsx), only the ones
// the frame uses. 24×24, currentColor. "folder" is new: the prototype has no Files page.
const P: Record<string, React.ReactNode> = {
  home: <><path d="M3.5 11 12 4l8.5 7" /><path d="M5.5 9.5V20h13V9.5" /><path d="M10 20v-5h4v5" /></>,
  shield: <><path d="M12 3.5 19 6v5.5c0 4.2-3 7.4-7 9-4-1.6-7-4.8-7-9V6z" /><path d="m9 12 2 2 4-4" /></>,
  wrench: <><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-2z" /></>,
  terminal: <><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><path d="m7 9.5 3 2.5-3 2.5M12.5 15h4.5" /></>,
  pulse: <><path d="M3 12h4l2.5-6 4 12 2.5-6H21" /></>,
  users: <><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" /><circle cx="17" cy="9" r="2.4" /><path d="M16 14.2c2.4 0 4 1.5 4.5 4.3" /></>,
  cube: <><path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z" /><path d="M4 7.5 12 12l8-4.5M12 12v9" /></>,
  folder: <><path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2H19a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
  search: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5" /></>,
  x: <><path d="M6 6l12 12M18 6 6 18" /></>,
  chevl: <><path d="m15 6-6 6 6 6" /></>,
  chevron: <><path d="m9 6 6 6-6 6" /></>,
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.7}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden>{P[name] ?? null}</svg>;
}

/** The CommandCenter mark: a hexagonal C, purple to blue. Each copy has its own gradient id. */
export function Logo({ size = 34 }: { size?: number }) {
  const id = `hq-logo-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden>
    <defs><linearGradient id={id} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#8b6bff" /><stop offset="1" stopColor="#3f7bff" /></linearGradient></defs>
    <path d="M20 2.5 35 11v18L20 37.5 5 29V11z" fill="none" stroke={`url(#${id})`} strokeWidth="3" strokeLinejoin="round" />
    <path d="M26 14.5a8 8 0 1 0 0 11" fill="none" stroke={`url(#${id})`} strokeWidth="3.4" strokeLinecap="round" />
  </svg>;
}
