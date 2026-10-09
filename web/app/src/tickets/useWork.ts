// One ticket's durable work state (GET /api/tasks/{key}/work), cached per key and refetched whenever
// the ticket changes (every pipeline step bumps updatedAt and arrives as a task.* event).
import { useCallback, useEffect } from "react";
import { app } from "../store/app";
import { Store, useSelector } from "../lib/store";
import { ApiError } from "../api/client";
import type { TicketWork } from "../api/types";

export const works = new Store<Record<string, TicketWork | "missing">>({});
const inflight = new Map<string, Promise<void>>();

export function loadWork(key: string): Promise<void> {
  const have = inflight.get(key);
  if (have) return have;
  const p = app.api.taskWork(key).then((w) => { works.patch({ [key]: w }); })
    .catch((e) => { if (e instanceof ApiError && (e.status === 404 || e.status === 503)) works.patch({ [key]: "missing" }); })
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

export function useWork(key: string | null): [TicketWork | null, (w: TicketWork) => void] {
  const w = useSelector(works, (d) => (key ? d[key] : undefined));
  const stamp = useSelector(app.store, (d) => (key ? d.tickets.find((t) => t.key === key)?.updatedAt ?? null : null));
  useEffect(() => { if (key) void loadWork(key); }, [key, stamp]);
  const set = useCallback((next: TicketWork) => { if (key) { works.patch({ [key]: next }); void app.refreshTicket(key); } }, [key]);
  return [w && w !== "missing" ? w : null, set];
}
