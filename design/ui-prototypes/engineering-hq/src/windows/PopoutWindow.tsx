// The window behind `#/pop/<view id>`: one view, its own context header, Return to main window.
import { useEffect, useState, type ReactNode } from "react";
import { useRoute } from "../lib/router";
import { Icon, Logo } from "../components/Icon";
import { Demo } from "../components/ui";
import { claimAsPopout, mainAlive, returnHere } from "./manager";
import { viewById } from "./views";
import { useDocTitle } from "./Detachable";

export function PopoutWindow({ render }: { render: (id: string) => ReactNode }) {
  const route = useRoute();
  const id = route.id ?? "";
  const def = viewById(id);
  const [lost, setLost] = useState(false);
  const [orphan, setOrphan] = useState(false);
  useDocTitle(def ? `CommandCenter · ${def.title}` : "CommandCenter");
  useEffect(() => {
    if (!def) return;
    document.body.classList.add("is-popout");
    const stop = claimAsPopout(id, () => { setLost(true); setTimeout(() => { try { window.close(); } catch { /* not closable */ } }, 150); });
    return () => { stop(); document.body.classList.remove("is-popout"); };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const t = setInterval(() => { void mainAlive().then((a) => setOrphan(!a)); }, 2000);
    return () => clearInterval(t);
  }, []);
  if (!def) return <div className="pop-msg"><h1>Unknown view</h1><p>This pop-out link does not name a view.</p></div>;
  if (lost) return <div className="pop-msg"><Icon name="returnin" size={34} /><h1>Returned to the main window</h1><p><b>{def.title}</b> is back in the main CommandCenter window. You can close this window.</p>
    <button type="button" className="btn" onClick={() => window.close()}>Close window</button></div>;
  const becomeMain = () => { returnHere(id); location.hash = def.hash; location.reload(); };
  return <div className="popwin" data-testid="popout-window">
    <header className="pop-head">
      <Logo size={24} /><span className="pop-kind"><Icon name="popout" size={14} /> Detached</span>
      {def.color && <i className="tab-dot" style={{ background: def.color }} />}<b>{def.title}</b>{def.sub && <span className="muted">· {def.sub}</span>}
      <span className="sp" /><Demo label="Prototype" />
      <button type="button" className="btn btn-sm" onClick={() => { returnHere(id); window.close(); }} title="Put this view back in the main window" aria-label="Return to main window"><Icon name="returnin" size={15} /><span className="btn-text"> Return to main window</span></button>
    </header>
    {orphan && <div className="pop-orphan" role="status"><Icon name="info" size={16} /> The main CommandCenter window is closed. This window keeps working.
      <button type="button" className="btn btn-sm" onClick={becomeMain}>Make this the main window</button></div>}
    <main className="pop-body">{render(id)}</main>
  </div>;
}
