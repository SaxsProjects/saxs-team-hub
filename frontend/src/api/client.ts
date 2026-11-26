/**
 * The one place that talks to the Team Hub API.
 * - The sign-in token lives in memory and sessionStorage (cleared when the tab closes), never in
 *   localStorage or cookies, and is only ever sent to the configured API address.
 * - A 401 from any request signs the person out everywhere in the app.
 */

export const API_URL = (import.meta.env.VITE_API_URL ?? "https://saxs-team-hub-api.onrender.com").replace(/\/+$/, "");

const TOKEN_KEY = "teamhub.session";

interface StoredSession {
  token: string;
  expiresAt: number; // epoch ms
}

let session: StoredSession | null = readStored();
const listeners = new Set<() => void>();

function readStored(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSession;
    return parsed.expiresAt > Date.now() ? parsed : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, expiresInSeconds: number): void {
  session = { token, expiresAt: Date.now() + expiresInSeconds * 1000 };
  try {
    sessionStorage.setItem(TOKEN_KEY, JSON.stringify(session));
  } catch {
    /* private mode: the session still works for this page */
  }
  listeners.forEach((l) => l());
}

export function clearSession(): void {
  session = null;
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}

export function hasSession(): boolean {
  return session !== null && session.expiresAt > Date.now();
}

export function sessionExpiresAt(): number | null {
  return session?.expiresAt ?? null;
}

export function onSessionChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** FastAPI errors are {"detail": "..."} or {"detail": [{"msg": ...}]}; turn them into one readable sentence. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return String(body.detail[0].msg).replace(/^Value error, /, "");
  } catch {
    /* not JSON */
  }
  if (res.status >= 500) return "The Team Hub server had a problem. Please try again in a minute.";
  return `Request failed (${res.status})`;
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (session) headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "omit", referrerPolicy: "no-referrer" });
  } catch {
    throw new ApiError(0, "Can't reach the Team Hub. Check your connection; the server may also be waking up (up to a minute).");
  }
  if (res.status === 401 && session && !path.startsWith("/api/auth/login")) clearSession();
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

/** Fetch a protected file (picture, PDF, CSV) as a blob, since <img>/<a> can't send the sign-in token. */
export async function apiBlob(path: string): Promise<Blob> {
  return (await send(path)).blob();
}

/** Download a protected file under a given name. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const url = URL.createObjectURL(await apiBlob(path));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
