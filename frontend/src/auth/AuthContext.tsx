import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  hasSession,
  IDLE_LIMIT_MS,
  idleFor,
  noteActivity,
  onSessionChange,
  post,
  renew,
  setSession,
  signOutHere,
  signOutPending,
} from "../api/client";
import type { Me, PasskeyOptions, TokenOut, TrustedDeviceInfo } from "../api/types";
import { signWithPasskey } from "../lib/passkey";

export type SignInResult = "ok" | "totp_required";

interface AuthState {
  me: Me | null;
  loading: boolean;
  /** This phone or computer is trusted: it unlocks with a passkey or the password, without two-factor. */
  device: TrustedDeviceInfo | null;
  signIn: (email: string, password: string, totpCode?: string, trust?: boolean) => Promise<SignInResult>;
  unlock: (password: string) => Promise<void>;
  unlockWithPasskey: (signal?: AbortSignal) => Promise<void>;
  /** "Use another account": stop trusting this device. */
  forgetDevice: () => Promise<void>;
  signOut: () => void;
}

/** On a trusted device the app locks after this long in the background (another app, screen off). */
export const BACKGROUND_LOCK_MS = 5 * 60_000;

async function thisDevice(): Promise<TrustedDeviceInfo | null> {
  try {
    const info = await api<TrustedDeviceInfo>("/api/auth/device");
    return info && typeof info.email === "string" ? info : null;
  } catch {
    return null; // not trusted (401), or offline: the normal sign-in
  }
}

/** The app names itself to the server so the device list says "Team Hub Android app". */
function appDeviceName(): string | undefined {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean; getPlatform?: () => string } }).Capacitor;
  if (cap?.isNativePlatform?.()) return cap.getPlatform?.() === "ios" ? "Team Hub iPhone app" : "Team Hub Android app";
  return /TeamHubDesktop\//.test(navigator.userAgent) ? "Team Hub Windows app" : undefined;
}

const AuthContext = createContext<AuthState | null>(null);
const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "scroll", "touchstart"] as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [signedIn, setSignedIn] = useState(hasSession());
  // On first load, try the renewal cookie so a reload or new tab keeps the person signed in.
  const [resuming, setResuming] = useState(!hasSession());

  useEffect(() => {
    if (!resuming) return;
    let cancelled = false;
    // A sign-out that didn't reach the server is retried first, and the session is not resumed.
    const start = signOutPending() ? signOutHere() : renew();
    void start.finally(() => !cancelled && setResuming(false));
    return () => {
      cancelled = true;
    };
  }, [resuming]);

  useEffect(
    () =>
      onSessionChange(() => {
        const now = hasSession();
        setSignedIn(now);
        if (!now) queryClient.clear(); // drop every cached screen so nothing lingers after sign-out
      }),
    [queryClient],
  );

  // Track activity; after 30 minutes without any, sign out on this device.
  useEffect(() => {
    if (!signedIn) return;
    noteActivity();
    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, noteActivity, { passive: true, capture: true }));
    const check = window.setInterval(() => {
      if (idleFor() >= IDLE_LIMIT_MS) void signOutHere();
    }, 30_000);
    return () => {
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, noteActivity, { capture: true }));
      window.clearInterval(check);
    };
  }, [signedIn]);

  const meQuery = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/auth/me"), enabled: signedIn, staleTime: 60_000 });
  // Asked once per sign-in state; the cache is cleared on sign-out, so it is asked again then.
  const deviceQuery = useQuery({ queryKey: ["device"], queryFn: thisDevice, enabled: !resuming, staleTime: Infinity, retry: false });
  const device = deviceQuery.data ?? null;

  // A trusted phone locks when it has been in the background for 5 minutes; it opens with a passkey or password.
  useEffect(() => {
    if (!signedIn || !device) return;
    let hiddenAt = document.hidden ? Date.now() : 0;
    const onChange = () => {
      if (document.hidden) hiddenAt = Date.now();
      else if (hiddenAt && Date.now() - hiddenAt >= BACKGROUND_LOCK_MS) void signOutHere();
      else hiddenAt = 0;
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, [signedIn, device]);

  const signIn = useCallback(
    async (email: string, password: string, totpCode?: string, trust = false): Promise<SignInResult> => {
      try {
        const out = await post<TokenOut>("/api/auth/login", {
          email,
          password,
          totp_code: totpCode || undefined,
          trust_device: trust,
          device_name: trust ? appDeviceName() : undefined,
        });
        setSession(out.access_token, out.expires_in);
        if (out.device_trusted) void queryClient.invalidateQueries({ queryKey: ["device"] });
        return "ok";
      } catch (e) {
        if (e instanceof ApiError && e.status === 401 && e.message === "totp_required") return "totp_required";
        throw e;
      }
    },
    [queryClient],
  );

  const afterUnlockFailure = useCallback(
    (e: unknown) => {
      // The device was untrusted (removed elsewhere, expired, too many wrong passwords): back to the full sign-in.
      if (e instanceof ApiError && e.status === 401 && /Sign in/.test(e.message)) void queryClient.invalidateQueries({ queryKey: ["device"] });
      throw e;
    },
    [queryClient],
  );

  const unlock = useCallback(
    async (password: string) => {
      try {
        const out = await post<TokenOut>("/api/auth/unlock", { password });
        setSession(out.access_token, out.expires_in);
      } catch (e) {
        afterUnlockFailure(e);
      }
    },
    [afterUnlockFailure],
  );

  const unlockWithPasskey = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const { challenge_id, options } = await post<PasskeyOptions>("/api/auth/unlock/passkey/options");
        const credential = await signWithPasskey(options, signal);
        const out = await post<TokenOut>("/api/auth/unlock/passkey", { challenge_id, credential });
        setSession(out.access_token, out.expires_in);
      } catch (e) {
        afterUnlockFailure(e);
      }
    },
    [afterUnlockFailure],
  );

  const forgetDevice = useCallback(async () => {
    await post("/api/auth/forget-device").catch(() => undefined);
    queryClient.setQueryData(["device"], null);
  }, [queryClient]);

  const signOut = useCallback(() => void signOutHere(), []);

  const value = useMemo<AuthState>(
    () => ({
      me: signedIn ? (meQuery.data ?? null) : null,
      loading: resuming || (signedIn && meQuery.isPending) || (!signedIn && deviceQuery.isPending),
      device,
      signIn,
      unlock,
      unlockWithPasskey,
      forgetDevice,
      signOut,
    }),
    [signedIn, resuming, meQuery.data, meQuery.isPending, deviceQuery.isPending, device, signIn, unlock, unlockWithPasskey, forgetDevice, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
