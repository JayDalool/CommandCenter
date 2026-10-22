// Motion preference: follow the OS setting (default) or always reduce. CSS reads <html data-motion="reduce">.
import { Store } from "./store";

export type MotionPref = "system" | "reduce";
const KEY = "hq.motion";
const load = (): MotionPref => { try { return localStorage.getItem(KEY) === "reduce" ? "reduce" : "system"; } catch { return "system"; } };
export const motionPref = new Store<MotionPref>(load());
const apply = () => { if (typeof document !== "undefined") document.documentElement.dataset.motion = motionPref.get(); };
apply();
motionPref.subscribe(apply);
export function setMotionPref(p: MotionPref) { motionPref.set(p); try { localStorage.setItem(KEY, p); } catch { /* ignore */ } }
