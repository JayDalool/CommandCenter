// POP-OUT WINDOWS (spec §15, §16): one terminal pane, or a whole room, in its own Command Center
// window — drag it to another monitor. Both attach to the EXACT same ccd session by name, so no
// Claude, Codex or shell is started twice, and the slot they left on the wall is free.
//
//   Return to Workspace   puts it back on the wall (this window closes)
//   Close Window / Detach closes only this window; the session keeps running (listed to reattach)
//   End Session           the explicit, confirmed way to stop the work itself
import { useEffect, useState } from "react";
import { app } from "../store/app";
import { useSelector } from "../lib/store";
import { useRoute } from "../lib/router";
import { pjVar, stageOf } from "../lib/control";
import { EmptyState } from "../components/ui";
import { DevDot } from "../components/DevMode";
import { PaneBody, RoomView, useRoom, useWsProjects } from "../workspace/Room";
import { StagePill } from "../workspace/Dossier";
import { TOOL_LABEL, TOOLS, detachPane, detachRoom, layout, reattachPane, returnRoom, sessionName, type Tool } from "../workspace/rooms";

function homeWall(): string {
  const l = layout.get();
  return Object.keys(l.walls).find((w) => l.walls[w].length < 4) ?? "1";
}

export function RoomWindow() {
  const route = useRoute();
  const id = route.id ?? "";
  const room = useRoom(id);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    const off = () => detachRoom(id);   // the OS close button: detach, never stop
    window.addEventListener("pagehide", off);
    return () => window.removeEventListener("pagehide", off);
  }, [id]);
  // Brought back to a wall from another window: this one is no longer needed.
  useEffect(() => { if (room && room.where === "wall" && !closing) { setClosing(true); window.close(); } }, [room, closing]);
  useEffect(() => { document.title = room ? `${room.key ?? room.project} · Command Center` : "Command Center"; }, [room]);
  if (!room) return <EmptyState title="This room is no longer open" hint="Reopen it from the Workspace." />;
  if (room.where === "wall") return <EmptyState title="Back on the Workspace" hint="You can close this window." />;
  return <div className="popwin">
    <RoomView room={room} popped extra={<>
      <DevDot />
      <button type="button" className="btn is-sm" onClick={() => {
        if (returnRoom(room.id, homeWall())) window.close(); else app.toast("Every Workspace window is full", "bad");
      }}>Return to Workspace</button>
      <button type="button" className="btn is-sm is-quiet" onClick={() => { detachRoom(room.id); window.close(); }}
        title="Closes this window only; every session keeps running">Close Window / Detach</button>
    </>} />
  </div>;
}

export function PaneWindow() {
  const route = useRoute();
  const [rid, tool] = (route.id ?? "").split("/") as [string, Tool];
  const room = useRoom(rid);
  const { rows } = useWsProjects();
  const ticket = useSelector(app.store, (d) => (room?.key ? d.tickets.find((t) => t.key === room.key) ?? null : null));
  const pname = useSelector(app.store, (d) => d.state?.projects.find((p) => p.key === room?.project)?.name ?? room?.project ?? "");
  const [ended, setEnded] = useState(false);
  const state = room?.out[tool];
  useEffect(() => {
    const off = () => detachPane(rid, tool);
    window.addEventListener("pagehide", off);
    return () => window.removeEventListener("pagehide", off);
  }, [rid, tool]);
  useEffect(() => { if (room && state === undefined && room.slots.includes(tool)) window.close(); }, [room, state, tool]);
  useEffect(() => { document.title = room ? `${TOOL_LABEL[tool] ?? tool} · ${room.key ?? pname} · Command Center` : "Command Center"; }, [room, tool, pname]);
  if (!room || !TOOLS.includes(tool)) return <EmptyState title="This terminal is no longer popped out" hint="Reopen it from its room." />;
  const proj = rows?.find((p) => p.key === room.project) ?? null;
  const name = proj ? sessionName(room, tool, proj.prefix) : null;
  const end = async () => {
    const what = tool === "claude" ? "Close this Claude attach? The Claude session itself keeps running in herdr." : `End the ${TOOL_LABEL[tool]} session? Anything running in it stops.`;
    if (!name || !window.confirm(what)) return;
    if (await app.action(() => app.api.ptyClose(name), `${TOOL_LABEL[tool]} session ended`)) setEnded(true);
  };
  return <div className="popwin" style={pjVar(room.project)}>
    <header className="room-head">
      <b className="room-title">{room.kind === "task" ? `${room.key} · ${pname}` : `${pname} · Project Console`}</b>
      <span className="pane-name">{TOOL_LABEL[tool].toUpperCase()}</span>
      {ticket && <StagePill stage={stageOf(ticket)} />}
      <span className="sl-fill" />
      <DevDot />
      <button type="button" className="btn is-sm" onClick={() => { reattachPane(rid, tool); window.close(); }}
        title="Put this terminal back into its room">Reattach to room</button>
      <button type="button" className="btn is-sm is-quiet" onClick={() => { detachPane(rid, tool); window.close(); }}
        title="Closes this window only; the session keeps running">Close Window / Detach</button>
      <button type="button" className="btn is-sm is-danger" onClick={() => void end()} disabled={ended || !name}>End Session</button>
    </header>
    <div className="pane-body is-pop">{proj ? <PaneBody room={room} tool={tool} proj={proj} active /> : <EmptyState title="Loading…" />}</div>
  </div>;
}
