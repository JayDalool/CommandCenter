import { useId } from "react";
// The approved prototype's stroke icons (design/ui-prototypes/engineering-hq/src/components/Icon.tsx), only the ones
// the frame and the HQ pages use. 24×24, currentColor. "folder" is new: the prototype has no Files page.
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
  popout: <><path d="M14 4.5h5.5V10" /><path d="M19.5 4.5 11 13" /><path d="M17 13.5v5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7h5" /></>,
  returnin: <><path d="M10 14 4.5 19.5M4.5 14v5.5H10" /><rect x="9" y="4" width="11" height="11" rx="1.5" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  monitor: <><rect x="3.5" y="4.5" width="17" height="11.5" rx="1.5" /><path d="M9 20h6M12 16v4" /></>,
  code: <><path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M13.5 5l-3 14" /></>,
  mobile: <><rect x="7" y="3" width="10" height="18" rx="2" /><path d="M11 18h2" /></>,
  rocket: <><path d="M14 4c3.5 0 6 2.5 6 6-1.5 3-4.5 6-8 7.5L6.5 12C8 8.5 11 5.5 14 4z" /><circle cx="14.5" cy="9.5" r="1.6" /><path d="M6.5 12 4 12.5 3.5 15l3 1M12 17.5l-.5 2.5 2.5-.5 1-3M7 17l-2.5 2.5" /></>,
  server: <><rect x="4" y="4" width="16" height="7" rx="1.5" /><rect x="4" y="13" width="16" height="7" rx="1.5" /><path d="M7.5 7.5h.1M7.5 16.5h.1M11 7.5h5M11 16.5h5" /></>,
  laptop: <><rect x="5" y="5" width="14" height="10" rx="1.5" /><path d="M3 18.5h18" /></>,
  check: <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.4 2.4 4.6-5" /></>,
  fit: <><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" /></>,
  zoomin: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5M8.5 11h5M11 8.5v5" /></>,
  zoomout: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5M8.5 11h5" /></>,
  graph: <><circle cx="12" cy="5" r="2.2" /><circle cx="5" cy="17" r="2.2" /><circle cx="19" cy="17" r="2.2" /><path d="M11 7 6 15M13 7l5 8M7.2 17h9.6" /></>,
  list: <><path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.1M4.5 12h.1M4.5 17.5h.1" /></>,
  message: <><path d="M4 5.5h16v11H9l-5 3.5z" /><path d="M8 10h8M8 13h5" /></>,
  receipt: <><path d="M6 3.5h12v17l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3-2 1.3z" /><path d="M9 8h6M9 11.5h6M9 15h4" /></>,
  chart: <><path d="M4 20V4M4 20h16" /><rect x="7" y="12" width="3" height="5" /><rect x="12" y="8" width="3" height="9" /><rect x="17" y="10" width="3" height="7" /></>,
  chevdown: <><path d="m6 9 6 6 6-6" /></>,
  lock: <><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" /></>,
  plug: <><path d="M9 3.5v5M15 3.5v5M6.5 8.5h11V12a5.5 5.5 0 0 1-11 0zM12 17.5v3" /></>,
  bell: <><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>,
  layers: <><path d="M12 3.5 21 8l-9 4.5L3 8z" /><path d="m3 12 9 4.5 9-4.5M3 16l9 4.5 9-4.5" /></>,
  help: <><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.5v.7M12 16.8v.1" /></>,
  grid: <><rect x="4" y="4" width="6.5" height="6.5" rx="1.8" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" /></>,
  more: <><circle cx="5.5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="18.5" cy="12" r="1" /></>,
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
