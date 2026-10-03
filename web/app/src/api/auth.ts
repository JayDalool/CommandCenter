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
