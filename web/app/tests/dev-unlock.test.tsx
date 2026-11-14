/**
 * Developer Unlock that lasts (flow contract §6, web side): "Remember this device" keeps the session id in
 * localStorage (a plain one stays in sessionStorage), ccd is asked whether a remembered one still stands, a
 * write refused with `reenter` asks for the token once and is sent again, and what Jay pressed carries on
 * after he unlocks.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { vi } from "vitest";
import { Api, ApiError } from "../src/api/client";
import { setToken, clearToken } from "../src/api/auth";
import { askReenter, checkRemembered, devExpired, devSession, developer, restoreDevSession, setDevSession, setReenterAsker } from "../src/api/developer";
import { UnlockDialog, devOr, lockDevMode, reenterDialog, unlockDialogGone, unlockDialogOpen } from "../src/components/DevMode";
import { app } from "../src/store/app";
import { jsonResponse } from "./helpers";

const TOKEN = "k".repeat(43);
const DEV = "s".repeat(43);
const KEY = "ccd.dev";
const REENTER = { ok: false, error: "type the developer token again to use the terminal or write files on this device", reenter: true };

beforeEach(() => { clearToken(); setDevSession(null); localStorage.clear(); sessionStorage.clear(); setReenterAsker(null); });
afterEach(() => { cleanup(); unlockDialogGone(); vi.restoreAllMocks(); });

describe("where the session id is kept", () => {
  it("a remembered device keeps it in localStorage only; a plain unlock in sessionStorage only", () => {
    setDevSession(DEV, 30 * 86400, true);
    expect(developer.get()).toMatchObject({ active: true, remembered: true });
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ id: DEV, remembered: true });
    expect(sessionStorage.getItem(KEY)).toBeNull();

    setDevSession(DEV, 3600);                      // the same browser unlocked again without the box
    expect(developer.get().remembered).toBe(false);
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toContain(DEV);

    setDevSession(DEV, 30 * 86400, true);
    setDevSession(null);                           // Lock clears both
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(devSession()).toBeNull();
  });

  it("never stores the developer token, only the session id", () => {
    setDevSession(DEV, 3600, true);
    expect(Object.keys(JSON.parse(localStorage.getItem(KEY)!)).sort()).toEqual(["expiresAt", "id", "remembered"]);
  });

  it("a new window on a remembered device starts unlocked; an expired or broken entry does not, and is removed", async () => {
    const soon = Date.now() / 1000 + 86400;
    localStorage.setItem(KEY, JSON.stringify({ id: DEV, expiresAt: soon, remembered: true }));
    await restoreDevSession();
    expect(devSession()).toBe(DEV);
    expect(developer.get()).toMatchObject({ active: true, remembered: true });

    setDevSession(null);
    localStorage.setItem(KEY, JSON.stringify({ id: DEV, expiresAt: Date.now() / 1000 - 5, remembered: true }));
    await restoreDevSession();
    expect(devSession()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();

    localStorage.setItem(KEY, "{not json");
    await restoreDevSession();
    expect(devSession()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("the browser's remembered session wins over a restored tab's older plain id, and is not erased by it", async () => {
    const soon = Date.now() / 1000 + 3600;
    localStorage.setItem(KEY, JSON.stringify({ id: DEV, expiresAt: soon, remembered: true }));
    sessionStorage.setItem(KEY, JSON.stringify({ id: "p".repeat(43), expiresAt: soon }));
    await restoreDevSession();
    expect(devSession()).toBe(DEV);
    expect(developer.get().remembered).toBe(true);
    expect(localStorage.getItem(KEY)).toContain(DEV);
    expect(sessionStorage.getItem(KEY)).toBeNull();   // one copy

    setDevSession(null);                           // an entry in localStorage that is not a remembered one is not trusted
    localStorage.setItem(KEY, JSON.stringify({ id: "x".repeat(43), expiresAt: soon }));
    sessionStorage.setItem(KEY, JSON.stringify({ id: DEV, expiresAt: soon }));
    await restoreDevSession();
    expect(devSession()).toBe(DEV);
    expect(developer.get().remembered).toBe(false);
  });
});

describe("a window still on an old plain id while the browser holds a remembered one", () => {
  const OLD = "p".repeat(43);
  // As when another window remembered the device and this one never heard (no BroadcastChannel).
  const seed = async () => {
    setDevSession(OLD, 3600);
    localStorage.setItem(KEY, JSON.stringify({ id: DEV, expiresAt: Date.now() / 1000 + 86400, remembered: true }));
    expect(devSession()).toBe(OLD);
  };

  it("ccd refuses the old id: only that id goes, and the tab carries on with the remembered one", async () => {
    await seed();
    devExpired();
    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ id: DEV, remembered: true });
    expect(devSession()).toBe(DEV);
    expect(developer.get()).toMatchObject({ active: true, remembered: true });

    devExpired();                                  // the remembered one is dead too: now the browser holds nothing
    expect(devSession()).toBeNull();
    expect(developer.get().active).toBe(false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("Lock still clears everything this browser holds", async () => {
    await seed();
    setDevSession(null);
    expect(devSession()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });
});

describe("Lock", () => {
  it("says locked when ccd took it, and when ccd had already dropped the session", async () => {
    const toast = vi.spyOn(app, "toast");
    setDevSession(DEV, 86400, true);
    vi.spyOn(app.api, "lock").mockResolvedValueOnce({ ok: true } as never);
    await lockDevMode();
    expect(toast).toHaveBeenLastCalledWith("Developer Mode locked");
    expect(devSession()).toBeNull();

    setDevSession(DEV, 86400, true);
    vi.spyOn(app.api, "lock").mockRejectedValueOnce(new ApiError(403, "Developer Unlock required"));
    await lockDevMode();
    expect(toast).toHaveBeenLastCalledWith("Developer Mode locked");
  });

  it("a remembered device, ccd unreachable: locked here, and Jay is told the device is still remembered there", async () => {
    const toast = vi.spyOn(app, "toast");
    setDevSession(DEV, 86400, true);
    vi.spyOn(app.api, "lock").mockRejectedValueOnce(new ApiError(0, "ccd unreachable"));
    await lockDevMode();
    expect(devSession()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(toast).toHaveBeenLastCalledWith(expect.stringMatching(/Locked in this browser only.*Lock all devices in Settings/), "bad");

    setDevSession(DEV, 3600);                      // a plain session ends at ccd by itself within hours
    vi.spyOn(app.api, "lock").mockRejectedValueOnce(new ApiError(0, "ccd unreachable"));
    await lockDevMode();
    expect(toast).toHaveBeenLastCalledWith("Developer Mode locked");
  });
});

describe("a remembered session is checked with ccd on start", () => {
  it("locks this browser when ccd no longer knows it (Lock all devices, 30 days)", async () => {
    setDevSession(DEV, 86400, true);
    await checkRemembered(async () => ({ active: false, expiresIn: null }));
    expect(devSession()).toBeNull();
    expect(developer.get().active).toBe(false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("keeps it when ccd confirms it, and when ccd cannot be reached", async () => {
    setDevSession(DEV, 86400, true);
    await checkRemembered(async () => ({ active: true, expiresIn: 1000, remembered: true }));
    expect(developer.get()).toMatchObject({ active: true, remembered: true });
    expect(developer.get().expiresAt! - Date.now() / 1000).toBeLessThan(1001);
    await checkRemembered(async () => { throw new Error("ccd unreachable"); });
    expect(devSession()).toBe(DEV);
    expect(localStorage.getItem(KEY)).toContain(DEV);
  });

  it("does not ask for a plain session, and drops the answer when the session changed meanwhile", async () => {
    setDevSession(DEV, 3600);
    const status = vi.fn(async () => ({ active: false, expiresIn: null }));
    await checkRemembered(status);
    expect(status).not.toHaveBeenCalled();
    expect(devSession()).toBe(DEV);

    setDevSession(DEV, 86400, true);
    const other = "o".repeat(43);
    await checkRemembered(async () => { setDevSession(other, 3600); return { active: false, expiresIn: null }; });
    expect(devSession()).toBe(other);
  });
});

describe("ccd asks for the token again (403 reenter)", () => {
  const refuseThenOk = (seen: { url: string; init: RequestInit }[], refusals = 1) => new Api(async (u, init) => {
    seen.push({ url: String(u), init: init! });
    return seen.length <= refusals ? jsonResponse(REENTER, 403) : jsonResponse({ ok: true, sha256: "x" });
  });

  it("asks once, then sends the same write again", async () => {
    setToken(TOKEN); setDevSession(DEV, 86400, true);
    const asker = vi.fn(async () => true);
    setReenterAsker(asker);
    const seen: { url: string; init: RequestInit }[] = [];
    await expect(refuseThenOk(seen).saveFile("samvision", "a.py", "x", null)).resolves.toMatchObject({ ok: true });
    expect(asker).toHaveBeenCalledTimes(1);
    expect(seen).toHaveLength(2);
    expect(seen[1].url).toBe(seen[0].url);
    expect(seen[1].init.body).toBe(seen[0].init.body);
    expect(developer.get().active).toBe(true);     // asked again is not locked
  });

  it("does not ask twice for one request", async () => {
    setToken(TOKEN); setDevSession(DEV, 86400, true);
    const asker = vi.fn(async () => true);
    setReenterAsker(asker);
    const seen: { url: string; init: RequestInit }[] = [];
    await expect(refuseThenOk(seen, 2).saveFile("samvision", "a.py", "x", null)).rejects.toThrow(/type the developer token again/);
    expect(asker).toHaveBeenCalledTimes(1);
    expect(seen).toHaveLength(2);
  });

  it("fails with ccd's own words when Jay cancels or no dialog is mounted, and stays unlocked", async () => {
    setToken(TOKEN); setDevSession(DEV, 86400, true);
    const seen: { url: string; init: RequestInit }[] = [];
    await expect(refuseThenOk(seen).saveFile("samvision", "a.py", "x", null)).rejects.toThrow(/type the developer token again/);
    setReenterAsker(async () => false);
    await expect(refuseThenOk([]).saveFile("samvision", "a.py", "x", null)).rejects.toThrow(/type the developer token again/);
    expect(seen).toHaveLength(1);
    expect(devSession()).toBe(DEV);
  });

  it("several writes refused at once share one question", async () => {
    setDevSession(DEV, 86400, true);
    let answer!: (ok: boolean) => void;
    const asker = vi.fn(() => new Promise<boolean>((r) => { answer = r; }));
    setReenterAsker(asker);
    const both = Promise.all([askReenter(), askReenter()]);
    answer(true);
    expect(await both).toEqual([true, true]);
    expect(asker).toHaveBeenCalledTimes(1);
    void askReenter();                              // a later refusal asks afresh
    expect(asker).toHaveBeenCalledTimes(2);
    answer(false);
  });

  it("unlock sends `remember` only when the box is ticked, and the token never in a URL", async () => {
    const seen: { url: string; init: RequestInit }[] = [];
    const api = new Api(async (u, init) => { seen.push({ url: String(u), init: init! }); return jsonResponse({ ok: true, session: DEV, expiresIn: 60 }); });
    await api.unlock(TOKEN);
    await api.unlock(TOKEN, true);
    expect(JSON.parse(String(seen[0].init.body))).toEqual({ token: TOKEN });
    expect(JSON.parse(String(seen[1].init.body))).toEqual({ token: TOKEN, remember: true });
    for (const s of seen) expect(s.url).not.toContain(TOKEN);
  });
});

describe("the unlock dialog", () => {
  /** The shell's part: mount the dialog when it is asked for. */
  function Host() {
    const [open, setOpen] = React.useState(false);
    React.useEffect(() => {
      const on = () => setOpen(true);
      window.addEventListener("cc:dev-unlock", on);
      return () => window.removeEventListener("cc:dev-unlock", on);
    }, []);
    return open ? <UnlockDialog onClose={() => setOpen(false)} /> : null;
  }
  const status = (extra: object = {}) => vi.spyOn(app.api, "developerStatus").mockResolvedValue({ active: false, expiresIn: null, tokenFile: null, ...extra });
  const type = (v: string) => fireEvent.change(screen.getByLabelText("Developer token"), { target: { value: v } });
  const box = () => screen.queryByRole("checkbox", { name: /Remember this device for 30 days/ });

  it("offers Remember this device only when this ccd can remember one", async () => {
    status();                                      // an older ccd: no `remembered` in its answer
    render(<Host />);
    act(() => unlockDialogOpen());
    await act(async () => {});
    expect(box()).toBeNull();
    cleanup(); unlockDialogGone();

    status({ remembered: false });
    render(<Host />);
    act(() => unlockDialogOpen());
    await waitFor(() => expect(box()).not.toBeNull());
    expect(box()).not.toBeChecked();
  });

  it("ticked: asks ccd to remember, keeps the id in localStorage, and remembers the tick for next time", async () => {
    status({ remembered: false });
    const unlock = vi.spyOn(app.api, "unlock").mockResolvedValue({ ok: true, session: DEV, expiresIn: 30 * 86400, remembered: true });
    render(<Host />);
    act(() => unlockDialogOpen());
    await waitFor(() => expect(box()).not.toBeNull());
    fireEvent.click(box()!);
    type(TOKEN);
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(developer.get().active).toBe(true));
    expect(unlock).toHaveBeenCalledWith(TOKEN, true);
    expect(developer.get().remembered).toBe(true);
    expect(localStorage.getItem(KEY)).toContain(DEV);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(TOKEN);
    expect(screen.queryByRole("dialog")).toBeNull();

    setDevSession(null);
    act(() => unlockDialogOpen());
    await waitFor(() => expect(box()).not.toBeNull());
    expect(box()).toBeChecked();
  });

  it("not ticked: a plain session, in sessionStorage", async () => {
    status({ remembered: false });
    const unlock = vi.spyOn(app.api, "unlock").mockResolvedValue({ ok: true, session: DEV, expiresIn: 8 * 3600, remembered: false });
    render(<Host />);
    act(() => unlockDialogOpen());
    await waitFor(() => expect(box()).not.toBeNull());
    type(TOKEN);
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(developer.get().active).toBe(true));
    expect(unlock).toHaveBeenCalledWith(TOKEN, false);
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toContain(DEV);
  });

  it("what Jay pressed carries on once he unlocks, once; Cancel drops it", async () => {
    status();
    vi.spyOn(app.api, "unlock").mockResolvedValue({ ok: true, session: DEV, expiresIn: 3600 });
    const approve = vi.fn();
    render(<Host />);
    let went = true;
    act(() => { went = devOr(approve); });
    expect(went).toBe(false);
    expect(approve).not.toHaveBeenCalled();
    expect(screen.getByText(/carries on as soon as this is unlocked/)).toBeInTheDocument();
    type(TOKEN);
    fireEvent.click(screen.getByRole("button", { name: "Unlock and continue" }));
    await waitFor(() => expect(approve).toHaveBeenCalledTimes(1));
    expect(devOr(approve)).toBe(true);             // unlocked now: straight through, nothing queued
    expect(approve).toHaveBeenCalledTimes(1);

    setDevSession(null);
    const merge = vi.fn();
    act(() => { devOr(merge); });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    act(() => unlockDialogOpen());                 // a later, unrelated unlock must not run it
    type(TOKEN);
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(developer.get().active).toBe(true));
    expect(merge).not.toHaveBeenCalled();
  });

  it("a wrong token keeps the dialog open and what was pressed waiting", async () => {
    status();
    const unlock = vi.spyOn(app.api, "unlock").mockRejectedValueOnce(new Error("wrong developer token"))
      .mockResolvedValue({ ok: true, session: DEV, expiresIn: 3600 });
    const approve = vi.fn();
    render(<Host />);
    act(() => { devOr(approve); });
    type("nope");
    fireEvent.click(screen.getByRole("button", { name: "Unlock and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("wrong developer token");
    expect(approve).not.toHaveBeenCalled();
    type(TOKEN);
    fireEvent.click(screen.getByRole("button", { name: "Unlock and continue" }));
    await waitFor(() => expect(approve).toHaveBeenCalledTimes(1));
    expect(unlock).toHaveBeenCalledTimes(2);
  });

  it("asked again on a remembered device: says why, has no SSH sign-in or box, and keeps the device remembered", async () => {
    setDevSession(DEV, 20 * 86400, true);
    status({ active: true, remembered: true, reenterIn: 0 });
    const unlock = vi.spyOn(app.api, "unlock").mockResolvedValue({ ok: true, session: DEV, expiresIn: 20 * 86400, remembered: true });
    render(<Host />);
    let answer: Promise<boolean>;
    act(() => { answer = reenterDialog(); });
    await act(async () => {});
    expect(screen.getByText(/more than 8 hours since the developer token was typed/)).toBeInTheDocument();
    expect(screen.queryByText(/Sign in with SSH/)).toBeNull();
    expect(box()).toBeNull();
    type(TOKEN);
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await expect(answer!).resolves.toBe(true);
    expect(unlock).toHaveBeenCalledWith(TOKEN, true);   // without it ccd would turn the device into a plain session
    expect(developer.get()).toMatchObject({ active: true, remembered: true });
    expect(devSession()).toBe(DEV);
  });

  it("asked again, and another window locks meanwhile: the dialog goes, and no token can remember the device again", async () => {
    setDevSession(DEV, 20 * 86400, true);
    status({ active: true, remembered: true, reenterIn: 0 });
    const unlock = vi.spyOn(app.api, "unlock");
    render(<Host />);
    let answer: Promise<boolean>;
    act(() => { answer = reenterDialog(); });
    await act(async () => {});
    type(TOKEN);
    act(() => setDevSession(null));                // Lock, or Lock all devices, from another window
    await expect(answer!).resolves.toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(unlock).not.toHaveBeenCalled();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("asked again, and another window unlocks without remembering meanwhile: the plain session is not turned into a remembered one", async () => {
    setDevSession(DEV, 20 * 86400, true);
    status({ active: true, remembered: true, reenterIn: 0 });
    const unlock = vi.spyOn(app.api, "unlock");
    render(<Host />);
    let answer: Promise<boolean>;
    act(() => { answer = reenterDialog(); });
    await act(async () => {});
    const plain = "p".repeat(43);
    act(() => setDevSession(plain, 8 * 3600));
    await expect(answer!).resolves.toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(unlock).not.toHaveBeenCalled();
    expect(devSession()).toBe(plain);
    expect(developer.get().remembered).toBe(false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("asked again and cancelled, or the shell gone: the answer is no, and nothing waits for ever", async () => {
    setDevSession(DEV, 20 * 86400, true);
    status({ active: true, remembered: true, reenterIn: 0 });
    render(<Host />);
    let answer: Promise<boolean>;
    act(() => { answer = reenterDialog(); });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await expect(answer!).resolves.toBe(false);
    expect(developer.get().active).toBe(true);

    act(() => { answer = reenterDialog(); });
    act(() => unlockDialogGone());
    await expect(answer!).resolves.toBe(false);
  });
});
