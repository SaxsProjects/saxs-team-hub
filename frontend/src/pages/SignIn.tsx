import { AlertCircle, ArrowLeft, Fingerprint } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { API_URL, signOutPending } from "../api/client";
import type { TrustedDeviceInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AuthLayout } from "../components/AuthLayout";
import { greeting } from "../lib/format";
import { cancelled, unlockName } from "../lib/passkey";

/** Phones and the installed apps are personal devices: keep them signed in unless the person says no. */
function personalDevice(): boolean {
  const w = window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } };
  return !!w.Capacitor?.isNativePlatform?.() || /Android|iPhone|iPad|TeamHubDesktop\//.test(navigator.userAgent);
}

/** Sign in. A trusted device gets the "Welcome back" unlock screen; anyone else the full sign-in. */
export function SignIn() {
  const { device } = useAuth();
  const [full, setFull] = useState(false);
  if (device && !full) return <Unlock device={device} onOtherAccount={() => setFull(true)} />;
  return <FullSignIn />;
}

function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="form-error" role="alert">
      <AlertCircle size={16} aria-hidden="true" />
      <span>{error}</span>
    </div>
  );
}

/** "Welcome back": the email is remembered, so only the passkey (or the password) is needed. */
function Unlock({ device, onOtherAccount }: { device: TrustedDeviceInfo; onOtherAccount: () => void }) {
  const { unlock, unlockWithPasskey, forgetDevice } = useAuth();
  const [password, setPassword] = useState("");
  const [usePassword, setUsePassword] = useState(!device.passkey);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tried = useRef(false);
  const method = unlockName();

  const tryPasskey = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      await unlockWithPasskey();
    } catch (e) {
      if (!cancelled(e)) setError(e instanceof Error ? e.message : "That didn't work. Use your password instead.");
      setUsePassword(true);
    } finally {
      setBusy(false);
    }
  }, [unlockWithPasskey]);

  // Ask for the face or fingerprint straight away, once, as the app opens.
  useEffect(() => {
    if (device.passkey && !tried.current) {
      tried.current = true;
      void tryPasskey();
    }
  }, [device.passkey, tryPasskey]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password) return setError("Enter your password.");
    setError(null);
    setBusy(true);
    try {
      await unlock(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unlock failed.");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  const name = device.full_name?.split(" ")[0];
  return (
    <AuthLayout title={name ? `Welcome back, ${name}.` : "Welcome back."} subtitle={device.email}>
      <form className="auth-form" onSubmit={submit} noValidate>
        {device.passkey && (
          <button type="button" className="btn btn-primary btn-block btn-lg" disabled={busy} onClick={() => void tryPasskey()}>
            <Fingerprint size={18} aria-hidden="true" /> {busy && !usePassword ? "Waiting…" : `Unlock with ${method}`}
          </button>
        )}
        {usePassword ? (
          <>
            <input type="email" autoComplete="username" value={device.email} readOnly hidden />
            <div className="field">
              <label htmlFor="unlock-password">Password</label>
              <input
                id="unlock-password"
                className="input"
                type="password"
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                aria-invalid={!!error}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
              />
            </div>
            <ErrorBox error={error} />
            <button className={`btn btn-block btn-lg ${device.passkey ? "btn-secondary" : "btn-primary"}`} disabled={busy}>
              {busy && usePassword ? "Unlocking…" : "Unlock"}
            </button>
          </>
        ) : (
          <>
            <ErrorBox error={error} />
            <button type="button" className="link-btn" onClick={() => setUsePassword(true)}>
              Use password instead
            </button>
          </>
        )}
        <div className="auth-row-end">
          <a className="link-btn" href={`${API_URL}/forgot-password`}>
            Forgot password?
          </a>
        </div>
      </form>
      <hr className="divider auth-sep" />
      <button
        type="button"
        className="link-btn"
        onClick={() => {
          void forgetDevice();
          onOtherAccount();
        }}
      >
        Not you? Use another account
      </button>
    </AuthLayout>
  );
}

/** Sign in, then (for anyone with two-factor on) the "One more step." code screen. */
function FullSignIn() {
  const { signIn } = useAuth();
  const [trust, setTrust] = useState(personalDevice);
  const [step, setStep] = useState<"password" | "code">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "code") codeRef.current?.focus();
  }, [step]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (step === "password" && (!email.trim() || !password)) return setError("Enter your email address and password.");
    if (step === "code" && code.length !== 6) return setError("Enter the 6-digit code.");
    setError(null);
    setBusy(true);
    try {
      const result = await signIn(email.trim(), password, step === "code" ? code : undefined, trust);
      if (result === "totp_required") setStep("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      if (step === "code") setCode("");
    } finally {
      setBusy(false);
    }
  }

  const errorBox = <ErrorBox error={error} />;

  if (step === "code") {
    return (
      <AuthLayout title="One more step." subtitle="Enter the 6-digit code from your authenticator app.">
        <form className="auth-form" onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="code">Authentication code</label>
            <input
              ref={codeRef}
              id="code"
              className="input code-input"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={6}
              placeholder="000000"
              value={code}
              aria-invalid={!!error}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            />
          </div>
          {errorBox}
          <button className="btn btn-primary btn-block btn-lg" disabled={busy}>
            {busy ? "Checking…" : "Verify & sign in"}
          </button>
          <button
            type="button"
            className="link-btn back-link"
            onClick={() => {
              setStep("password");
              setCode("");
              setError(null);
            }}
          >
            <ArrowLeft size={16} aria-hidden="true" /> Back to sign in
          </button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={`${greeting()}.`} subtitle="Sign in to your workspace.">
      {signOutPending() && (
        <p className="form-note" role="status">
          You are signed out here. The server couldn't be reached to confirm it; reload this page once you're online.
        </p>
      )}
      <form className="auth-form" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="username"
            placeholder="you@saxsprojects.co.za"
            value={email}
            aria-invalid={!!error}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            placeholder="Enter your password"
            value={password}
            aria-invalid={!!error}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="auth-row-between">
          <label className="check-row">
            <input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} />
            <span>Keep me signed in on this device</span>
          </label>
          <a className="link-btn" href={`${API_URL}/forgot-password`}>
            Forgot password?
          </a>
        </div>
        {trust && <p className="field-hint">Next time, unlock with your password or {unlockName()}. Only tick this on your own device.</p>}
        {errorBox}
        <button className="btn btn-primary btn-block btn-lg" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <hr className="divider auth-sep" />
      <p className="auth-note">New to the team? Use your invitation email.</p>
    </AuthLayout>
  );
}
