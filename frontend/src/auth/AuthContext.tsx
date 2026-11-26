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
import type { Me, TokenOut } from "../api/types";

export type SignInResult = "ok" | "totp_required";

interface AuthState {
  me: Me | null;
  loading: boolean;
  signIn: (email: string, password: string, totpCode?: string) => Promise<SignInResult>;
  signOut: () => void;
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

  const signIn = useCallback(async (email: string, password: string, totpCode?: string): Promise<SignInResult> => {
    try {
      const out = await post<TokenOut>("/api/auth/login", { email, password, totp_code: totpCode || undefined });
      setSession(out.access_token, out.expires_in);
      return "ok";
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && e.message === "totp_required") return "totp_required";
      throw e;
    }
  }, []);

  const signOut = useCallback(() => void signOutHere(), []);

  const value = useMemo<AuthState>(
    () => ({
      me: signedIn ? (meQuery.data ?? null) : null,
      loading: resuming || (signedIn && meQuery.isPending),
      signIn,
      signOut,
    }),
    [signedIn, resuming, meQuery.data, meQuery.isPending, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
