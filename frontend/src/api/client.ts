/**
 * The one place that talks to the Team Hub API.
 *
 * Sign-in model (see backend/app/sessions.py):
 * - The short access pass (15 min) lives only in memory, never in storage or cookies we can read.
 * - The server also sets an HttpOnly renewal cookie. While the person is active, the app swaps it for
 *   a new pass just before the old one runs out. After 30 minutes without activity the app signs out,
 *   and the server refuses renewals after that long anyway (and after 8–12 hours in any case).
 * - On reload or in a new tab, the cookie restores the sign-in without asking for the password again.
 * - Requests are only ever sent to the configured API address.
 */

export const API_URL = (import.meta.env.VITE_API_URL ?? "https://api.saxsprojects.co.za").replace(/\/+$/, "");

export const IDLE_LIMIT_MS = 30 * 60_000;
const RENEW_BEFORE_MS = 60_000;

interface Session {
  token: string;
  expiresAt: number; // epoch ms
}

let session: Session | null = null;
const listeners = new Set<() => void>();
let lastActivity = 0;
let renewTimer: number | undefined;
let renewing: Promise<boolean> | null = null;

function notify() {
  listeners.forEach((l) => l());
}

// Activity is shared between tabs (a timestamp only), so an idle background tab never signs out
// the tab someone is working in.
const ACTIVITY_KEY = "teamhub.lastActivity";
const SIGNED_OUT_KEY = "teamhub.signedOut";

function storage(kind: "local" | "session"): Storage | null {
  try {
    return kind === "local" ? localStorage : sessionStorage;
  } catch {
    return null;
  }
}

export function noteActivity(): void {
  const now = Date.now();
  if (now - lastActivity < 5_000) return; // throttle: mousemove and scroll fire constantly
  lastActivity = now;
  storage("local")?.setItem(ACTIVITY_KEY, String(now));
}

export function idleFor(): number {
  const shared = Number(storage("local")?.getItem(ACTIVITY_KEY) ?? 0);
  return Date.now() - Math.max(lastActivity, Number.isFinite(shared) ? shared : 0);
}

/** True when a sign-out in this tab hasn't reached the server yet; resuming must not happen. */
export function signOutPending(): boolean {
  return storage("session")?.getItem(SIGNED_OUT_KEY) === "1";
}

export function setSession(token: string, expiresInSeconds: number): void {
  session = { token, expiresAt: Date.now() + expiresInSeconds * 1000 };
  storage("session")?.removeItem(SIGNED_OUT_KEY); // a new sign-in replaces any pending sign-out
  scheduleRenewal();
  notify();
}

export function clearSession(): void {
  const had = session !== null;
  session = null;
  window.clearTimeout(renewTimer);
  if (had) notify();
}

export function hasSession(): boolean {
  return session !== null;
}

export function onSessionChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Renew shortly before the pass runs out, but only if the person has been active recently. */
function scheduleRenewal() {
  window.clearTimeout(renewTimer);
  if (!session) return;
  const wait = Math.max(0, session.expiresAt - Date.now() - RENEW_BEFORE_MS);
  renewTimer = window.setTimeout(() => {
    // Idle people are left to run out; their next click renews, or the idle limit signs them out.
    if (idleFor() < IDLE_LIMIT_MS / 2) void renew();
  }, wait);
}

/** Swap the renewal cookie for a fresh pass. One request at a time, shared by every caller. */
export function renew(): Promise<boolean> {
  renewing ??= (async () => {
    try {
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        referrerPolicy: "no-referrer",
      });
      if (!res.ok) {
        // 401/403: the sign-in has ended. Anything else (busy, restarting) is temporary: keep it.
        if (res.status === 401 || res.status === 403) clearSession();
        return false;
      }
      const body = (await res.json()) as { access_token: string; expires_in: number };
      setSession(body.access_token, body.expires_in);
      return true;
    } catch {
      return false; // offline: keep what we have and try again on the next request
    } finally {
      renewing = null;
    }
  })();
  return renewing;
}

/** Sign out this browser: end the server session (removes the cookie) and forget the pass. */
export async function signOutHere(): Promise<boolean> {
  // Remember the sign-out until the server confirms it, so a reload cannot resume the session.
  storage("session")?.setItem(SIGNED_OUT_KEY, "1");
  clearSession();
  try {
    const res = await fetch(`${API_URL}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
      referrerPolicy: "no-referrer",
    });
    if (res.ok) storage("session")?.removeItem(SIGNED_OUT_KEY);
    return res.ok;
  } catch {
    return false; // retried on the next page load
  }
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

/** Endpoints that set or read the HttpOnly sign-in cookie. Nothing else sends cookies. */
const COOKIE_PATHS = ["/api/auth/login", "/api/auth/change-password"];

async function send(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
  if (session && session.expiresAt - Date.now() < 5_000 && !COOKIE_PATHS.includes(path)) await renew();
  const headers = new Headers(init.headers);
  if (session) headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      credentials: COOKIE_PATHS.includes(path) ? "include" : "omit",
      referrerPolicy: "no-referrer",
    });
  } catch {
    throw new ApiError(0, "Can't reach the Team Hub. Check your connection; the server may also be waking up (up to a minute).");
  }
  if (res.status === 401 && session && !COOKIE_PATHS.includes(path)) {
    // The pass ran out (or was ended): renew once and repeat the request.
    if (!retried && (await renew())) return send(path, init, true);
    clearSession();
  }
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

/** Fetch a protected file (picture, PDF, CSV) as a blob, since <img>/<a> can't send the sign-in pass. */
export async function apiBlob(path: string, init?: RequestInit): Promise<Blob> {
  return (await send(path, init)).blob();
}

/** The Android app's own file saver (MainActivity registers it); absent in a normal browser. */
interface NativeBridge {
  isNativePlatform?: () => boolean;
  nativePromise?: (plugin: string, method: string, options: Record<string, unknown>) => Promise<{ location?: string }>;
}
function nativeBridge(): NativeBridge | null {
  const cap = (window as unknown as { Capacitor?: NativeBridge }).Capacitor;
  return cap?.isNativePlatform?.() && cap.nativePromise ? cap : null;
}

async function toBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/**
 * Save a file the person has already looked at. Browsers download it; the Android app can't download
 * from a web page, so it hands the file to the app, which saves it in Downloads.
 * Returns where it went, for the confirmation message.
 */
export async function saveBlob(blob: Blob, filename: string): Promise<string> {
  const native = nativeBridge();
  if (native?.nativePromise) {
    const r = await native.nativePromise("TeamHubFiles", "save", { data: await toBase64(blob), filename, mimeType: blob.type || "application/octet-stream" });
    return r.location ?? "Downloads";
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return "your downloads";
}

/** Download a protected file under a given name. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  await saveBlob(await apiBlob(path), filename);
}
