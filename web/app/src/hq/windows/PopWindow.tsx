// One HQ page in its own window (#/pop/<view>; manager.ts has the rules). A slim header names the page and offers
// Return to main window; the page below is the same component as in the main window, on the same live data. The
// window says it is open every couple of seconds, remembers where it was put, and says when it closes. Closing it
// only closes it.
import { Suspense, useEffect, useMemo, type MouseEvent } from "react";
import "../pages/office.css";
import "./windows.css";
import { href, useRoute } from "../../lib/router";
import { HqBoundary } from "../../components/Shell";
import { DevDot } from "../../components/DevMode";
import { NotificationBell } from "../../components/Notifications";
import { hqPageFor } from "../pages";
import { PageNavProvider, type PageNav } from "../pages/route";
import { hqTitle } from "../frame/nav";
import { Icon } from "../frame/icons";
import { HEARTBEAT_MS, herePlace, onMessage, popViewOf, savePlace, send, type PopView } from "./manager";

const pageRoute = (v: PopView) => ({ screen: v, id: null, params: new URLSearchParams() });

/** Open an address in the main window and bring it forward, so this window keeps showing its page. With no main window
 *  left (or not this app's), open it here: this window becomes an ordinary one. */
function openInMain(h: string) {
  const main = window.opener as Window | null;
  if (main && !main.closed) {
    try { main.location.hash = h; main.focus(); return; } catch { /* not this app's window */ }
  }
  location.hash = h;
}

/** While this window shows `v`: say so, remember where it is, come forward or close when the main window asks. */
function usePopOut(v: PopView) {
  useEffect(() => {
    let last = "";
    const here = () => {
      const place = herePlace();
      const k = JSON.stringify(place);
      if (k !== last) { last = k; savePlace(v, place); }
      send({ t: "here", view: v, place });
    };
    here();
    const t = setInterval(here, HEARTBEAT_MS);
    const off = onMessage((m) => {
      if (m.t === "who") here();
      else if (m.t === "focus" && m.view === v) window.focus();
      else if (m.t === "return" && m.view === v) window.close();
    });
    const bye = () => { savePlace(v, herePlace()); send({ t: "gone", view: v }); };
    window.addEventListener("pagehide", bye);
    // Leaving the page without closing (a link followed here) also ends the pop-out.
    return () => { clearInterval(t); off(); window.removeEventListener("pagehide", bye); bye(); };
  }, [v]);
}

export default function PopWindow() {
  useRoute();   // re-read the address when it changes
  const v = popViewOf(location.hash);
  return v ? <PopBody key={v} v={v} /> : null;
}

function PopBody({ v }: { v: PopView }) {
  usePopOut(v);
  const Page = hqPageFor(pageRoute(v));
  // The page stands for its own address here, not #/pop/<view>, and opening something from it (a task row) goes to
  // the main window, as its links do.
  const nav = useMemo<PageNav>(() => ({ route: pageRoute(v), go: (screen, id, params) => openInMain(href(screen, id, params)) }), [v]);
  const title = hqTitle(v, null, null);
  useEffect(() => { document.title = `${title} · Command Center`; }, [title]);
  // A link here opens in the main window, so this window keeps showing its page. With no main window left, the link
  // opens here and this window becomes an ordinary one.
  const onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const h = (e.target as HTMLElement).closest("a")?.getAttribute("href");
    if (!h?.startsWith("#/")) return;
    e.preventDefault();
    openInMain(h);
  };
  return <div className="hq-popwin" onClick={onClick}>
    <header className="hq-popwin-head">
      <b>{title}</b><small>Own window</small>
      <span className="hq-popwin-fill" />
      <DevDot /><NotificationBell />
      <button type="button" className="hq-btn" onClick={() => { send({ t: "gone", view: v }); window.close(); }}
        title="Close this window and show the page in the main window again"><Icon name="returnin" size={14} />Return to main window</button>
    </header>
    {Page ? <HqBoundary fallback={<p className="hq-popwin-empty">This page could not be shown here. Return it to the main window.</p>}>
      <Suspense fallback={null}><PageNavProvider value={nav}><div className="hq-screen"><Page /></div></PageNavProvider></Suspense></HqBoundary>
      : <p className="hq-popwin-empty">This page cannot open in its own window.</p>}
  </div>;
}
