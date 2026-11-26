import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, clearSession, hasSession, onSessionChange, post, sessionExpiresAt, setSession } from "../api/client";
import type { Me, TokenOut } from "../api/types";

export type SignInResult = "ok" | "totp_required";

interface AuthState {
  me: Me | null;
  loading: boolean;
  signIn: (email: string, password: string, totpCode?: string) => Promise<SignInResult>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [signedIn, setSignedIn] = useState(hasSession());

  useEffect(
    () =>
      onSessionChange(() => {
        const now = hasSession();
        setSignedIn(now);
        if (!now) queryClient.clear(); // drop every cached screen so nothing lingers after sign-out
      }),
    [queryClient],
  );

  // Sign out on the dot when the 60-minute session ends, instead of failing on the next click.
  useEffect(() => {
    const expiresAt = sessionExpiresAt();
    if (!signedIn || !expiresAt) return;
    const timer = window.setTimeout(clearSession, Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
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

  const value = useMemo<AuthState>(
    () => ({
      me: signedIn ? (meQuery.data ?? null) : null,
      loading: signedIn && meQuery.isPending,
      signIn,
      signOut: clearSession,
    }),
    [signedIn, meQuery.data, meQuery.isPending, signIn],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
