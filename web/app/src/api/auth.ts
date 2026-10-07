// The ccd token lives in memory, mirrored to sessionStorage (this tab only) or,
// if Jay ticks "remember", localStorage (this browser profile). Never a URL,
// never the page source, never a log line. ccd serves this UI from its own
// origin, so the storage is scoped to http://127.0.0.1:7777 alone.
const KEY = "ccd.token";
let memory: string | null = null;

function read(store: () => Storage): string | null {
  try { return store().getItem(KEY); } catch { return null; }
}

export function getToken(): string | null {
  if (memory) return memory;
  memory = read(() => sessionStorage) ?? read(() => localStorage);
  return memory;
}

export function setToken(token: string, remember = false): void {
  memory = token.trim();
  try { sessionStorage.setItem(KEY, memory); } catch { /* private mode: memory only */ }
  try {
    if (remember) localStorage.setItem(KEY, memory);
    else localStorage.removeItem(KEY);
  } catch { /* ignore */ }
}

export function clearToken(): void {
  memory = null;
  try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

export function isRemembered(): boolean {
  return read(() => localStorage) !== null;
}

export const TOKEN_SHAPE = /^[A-Za-z0-9_-]{32,128}$/;

// A pop-out terminal, room or second Workspace window opened from Command Center normally inherits
// this tab's sessionStorage; when it does not (a browser that does not copy it), it asks the open
// Command Center windows for the token over a same-origin BroadcastChannel. Nothing leaves the origin.
type TokMsg = { t: "tok?" } | { t: "tok"; token: string };
const tokChannel: BroadcastChannel | null = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("cc-token") : null;
tokChannel?.addEventListener("message", (e: MessageEvent<TokMsg>) => {
  if (e.data?.t === "tok?" && getToken()) tokChannel.postMessage({ t: "tok", token: getToken()! } satisfies TokMsg);
});

export function restoreToken(): Promise<void> {
  if (getToken() || !tokChannel) return Promise.resolve();
  return new Promise((resolve) => {
    const done = setTimeout(resolve, 250);
    const once = (e: MessageEvent<TokMsg>) => {
      if (e.data?.t === "tok" && TOKEN_SHAPE.test(e.data.token)) {
        clearTimeout(done); tokChannel.removeEventListener("message", once);
        memory = e.data.token;
        try { sessionStorage.setItem(KEY, memory); } catch { /* memory only */ }
        resolve();
      }
    };
    tokChannel.addEventListener("message", once);
    try { tokChannel.postMessage({ t: "tok?" } satisfies TokMsg); } catch { resolve(); }
  });
}
