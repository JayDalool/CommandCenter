// Stroke icons drawn for the prototype (no icon library). 24×24, currentColor.
const P: Record<string, React.ReactNode> = {
  home: <><path d="M3.5 11 12 4l8.5 7" /><path d="M5.5 9.5V20h13V9.5" /><path d="M10 20v-5h4v5" /></>,
  message: <><path d="M4 5.5h16v11H9l-5 3.5z" /><path d="M8 10h8M8 13h5" /></>,
  shield: <><path d="M12 3.5 19 6v5.5c0 4.2-3 7.4-7 9-4-1.6-7-4.8-7-9V6z" /><path d="m9 12 2 2 4-4" /></>,
  users: <><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" /><circle cx="17" cy="9" r="2.4" /><path d="M16 14.2c2.4 0 4 1.5 4.5 4.3" /></>,
  cube: <><path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z" /><path d="M4 7.5 12 12l8-4.5M12 12v9" /></>,
  wrench: <><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-2z" /></>,
  receipt: <><path d="M6 3.5h12v17l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3-2 1.3z" /><path d="M9 8h6M9 11.5h6M9 15h4" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
  help: <><circle cx="12" cy="12" r="8.5" /><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.5v.7M12 16.8v.1" /></>,
  search: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5" /></>,
  bell: <><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>,
  popout: <><path d="M14 4.5h5.5V10" /><path d="M19.5 4.5 11 13" /><path d="M17 13.5v5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7h5" /></>,
  returnin: <><path d="M10 14 4.5 19.5M4.5 14v5.5H10" /><rect x="9" y="4" width="11" height="11" rx="1.5" /></>,
  x: <><path d="M6 6l12 12M18 6 6 18" /></>,
  chevron: <><path d="m9 6 6 6-6 6" /></>,
  chevdown: <><path d="m6 9 6 6 6-6" /></>,
  arrowr: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
  arrowl: <><path d="M19 12H5M11 6l-6 6 6 6" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  send: <><path d="M4 12 20 4l-6 16-3-7z" /><path d="m11 13 9-9" /></>,
  clip: <><path d="M19 11.5 12 18.5a4.5 4.5 0 0 1-6.4-6.4L13 4.7a3 3 0 0 1 4.3 4.3L10 16.3a1.5 1.5 0 0 1-2.1-2.1L14.5 7.5" /></>,
  smile: <><circle cx="12" cy="12" r="8.5" /><path d="M8.5 14a4 4 0 0 0 7 0M9 9.5v.1M15 9.5v.1" /></>,
  video: <><rect x="3.5" y="6.5" width="12" height="11" rx="2" /><path d="m15.5 10.5 5-3v9l-5-3" /></>,
  phone: <><path d="M5 4.5h3.5l1.5 4-2 1.5a10 10 0 0 0 6 6l1.5-2 4 1.5V19a1.5 1.5 0 0 1-1.5 1.5A15.5 15.5 0 0 1 3.5 6 1.5 1.5 0 0 1 5 4.5z" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 7.8v.1" /></>,
  more: <><circle cx="12" cy="5.5" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="12" cy="18.5" r="1" /></>,
  image: <><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><circle cx="9" cy="10" r="1.8" /><path d="m4 18 5.5-5 3.5 3 3-2.5 4.5 4" /></>,
  layers: <><path d="M12 3.5 21 8l-9 4.5L3 8z" /><path d="m3 12 9 4.5 9-4.5M3 16l9 4.5 9-4.5" /></>,
  chart: <><path d="M4 20V4M4 20h16" /><rect x="7" y="12" width="3" height="5" /><rect x="12" y="8" width="3" height="9" /><rect x="17" y="10" width="3" height="7" /></>,
  heart: <><path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.3 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z" /></>,
  cc: <><path d="M16.5 8.5a5.5 5.5 0 1 0 0 7" strokeWidth="2.4" /></>,
  code: <><path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M13.5 5l-3 14" /></>,
  db: <><ellipse cx="12" cy="6" rx="7" ry="2.5" /><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" /></>,
  mobile: <><rect x="7" y="3" width="10" height="18" rx="2" /><path d="M11 18h2" /></>,
  rocket: <><path d="M14 4c3.5 0 6 2.5 6 6-1.5 3-4.5 6-8 7.5L6.5 12C8 8.5 11 5.5 14 4z" /><circle cx="14.5" cy="9.5" r="1.6" /><path d="M6.5 12 4 12.5 3.5 15l3 1M12 17.5l-.5 2.5 2.5-.5 1-3M7 17l-2.5 2.5" /></>,
  server: <><rect x="4" y="4" width="16" height="7" rx="1.5" /><rect x="4" y="13" width="16" height="7" rx="1.5" /><path d="M7.5 7.5h.1M7.5 16.5h.1M11 7.5h5M11 16.5h5" /></>,
  laptop: <><rect x="5" y="5" width="14" height="10" rx="1.5" /><path d="M3 18.5h18" /></>,
  check: <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.4 2.4 4.6-5" /></>,
  tick: <><path d="m5 12.5 4.5 4.5L19 7.5" /></>,
  star: <><path d="M12 3.5v17M3.5 12h17M6 6l12 12M18 6 6 18" /></>,
  spark: <><path d="M12 2.5v19M2.5 12h19M5.3 5.3l13.4 13.4M18.7 5.3 5.3 18.7M8.3 3.2l7.4 17.6M3.2 8.3l17.6 7.4M15.7 3.2 8.3 20.8M20.8 8.3 3.2 15.7" strokeWidth="1.4" /></>,
  box: <><path d="M12 3.5 19.5 7.5v9L12 20.5l-7.5-4v-9z" /><path d="m4.5 7.5 7.5 4 7.5-4M12 11.5v9" /></>,
  fit: <><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" /></>,
  zoomin: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5M8.5 11h5M11 8.5v5" /></>,
  zoomout: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5M8.5 11h5" /></>,
  filter: <><path d="M4 5h16l-6 7.5V19l-4 1.5v-8z" /></>,
  table: <><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><path d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10" /></>,
  timeline: <><path d="M4 6h9M7 12h11M5 18h7" /><circle cx="15.5" cy="6" r="1.5" /><circle cx="20" cy="12" r="1.5" /><circle cx="14.5" cy="18" r="1.5" /></>,
  graph: <><circle cx="12" cy="5" r="2.2" /><circle cx="5" cy="17" r="2.2" /><circle cx="19" cy="17" r="2.2" /><path d="M11 7 6 15M13 7l5 8M7.2 17h9.6" /></>,
  lock: <><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" /></>,
  doc: <><path d="M6.5 3.5h7l4 4v13h-11z" /><path d="M13.5 3.5v4h4M9 12h6M9 15.5h6" /></>,
  list: <><path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.1M4.5 12h.1M4.5 17.5h.1" /></>,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  flag: <><path d="M5.5 21V4M5.5 4.5h11l-2 3.5 2 3.5h-11" /></>,
  branch: <><circle cx="7" cy="5.5" r="2" /><circle cx="7" cy="18.5" r="2" /><circle cx="17" cy="8" r="2" /><path d="M7 7.5v9M17 10c0 4-10 3-10 6.5" /></>,
  pulse: <><path d="M3 12h4l2.5-6 4 12 2.5-6H21" /></>,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" /></>,
  bulb: <><path d="M9 17.5h6M10 20.5h4M12 3.5a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V17h5v-.6c0-.8.4-1.5 1-2A6 6 0 0 0 12 3.5z" /></>,
  card: <><rect x="3.5" y="5.5" width="17" height="13" rx="2" /><path d="M3.5 9.5h17M7 15h4" /></>,
  calendar: <><rect x="4" y="5.5" width="16" height="14.5" rx="2" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /></>,
  plug: <><path d="M9 3.5v5M15 3.5v5M6.5 8.5h11V12a5.5 5.5 0 0 1-11 0zM12 17.5v3" /></>,
  terminal: <><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><path d="m7 9.5 3 2.5-3 2.5M12.5 15h4.5" /></>,
  slack: <><path d="M9.5 3.5a2 2 0 0 0 0 4h2v-2a2 2 0 0 0-2-2zM3.5 9.5a2 2 0 0 0 2 2h6v-2a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2zM20.5 14.5a2 2 0 0 0-2-2h-6v2a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2zM14.5 20.5a2 2 0 0 0 0-4h-2v2a2 2 0 0 0 2 2z" /></>,
  edit: <><path d="M15 5l4 4L9 19H5v-4z" /></>,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></>,
};

export type IconId = keyof typeof P | string;

export function Icon({ name, size = 18, className, stroke = 1.7, title }: { name: IconId; size?: number; className?: string; stroke?: number; title?: string }) {
  return <svg className={className} viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={stroke}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
    {title && <title>{title}</title>}{P[name] ?? P.box}</svg>;
}

/** The CommandCenter mark: a hexagonal C, electric purple → blue. */
export function Logo({ size = 34 }: { size?: number }) {
  return <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden>
    <defs><linearGradient id="lg-cc" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#8b6bff" /><stop offset="1" stopColor="#3f7bff" /></linearGradient></defs>
    <path d="M20 2.5 35 11v18L20 37.5 5 29V11z" fill="none" stroke="url(#lg-cc)" strokeWidth="3" strokeLinejoin="round" />
    <path d="M26 14.5a8 8 0 1 0 0 11" fill="none" stroke="url(#lg-cc)" strokeWidth="3.4" strokeLinecap="round" />
  </svg>;
}
