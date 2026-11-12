// How an HQ page reads live data: Classic's store, as it is (store/app.ts), through the pure builders in hq/data.
// Nothing here fetches or writes. The clock ticks so a feed that stops reporting turns Unknown without a new event.
import { useMemo } from "react";
import { app, type AppData } from "../../store/app";
import { useSelector } from "../../lib/store";
import { nowS } from "../../lib/time";
import { useTick } from "../../components/Shell";
import { evidence, type Evidence } from "../data";

/** The store and the moment it is read at, re-read every `ms` and on every store change. */
export function useHqData(ms = 5000): { src: AppData; ev: Evidence } {
  useTick(ms);
  const src: AppData = useSelector(app.store, (d) => d);
  const now = Math.floor(nowS() / (ms / 1000)) * (ms / 1000);
  const ev = useMemo(() => evidence(src, now), [src, now]);
  return { src, ev };
}
