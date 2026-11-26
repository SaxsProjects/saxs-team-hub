import { AlertCircle, ArrowLeft } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { API_URL, signOutPending } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AuthLayout } from "../components/AuthLayout";
import { greeting } from "../lib/format";

/** Sign in, then (for anyone with two-factor on) the "One more step." code screen. */
export function SignIn() {
  const { signIn } = useAuth();
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
      const result = await signIn(email.trim(), password, step === "code" ? code : undefined);
      if (result === "totp_required") setStep("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      if (step === "code") setCode("");
    } finally {
      setBusy(false);
    }
  }

  const errorBox = error && (
    <div className="form-error" role="alert">
      <AlertCircle size={16} aria-hidden="true" />
      <span>{error}</span>
    </div>
  );

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
        <div className="auth-row-end">
          <a className="link-btn" href={`${API_URL}/forgot-password`}>
            Forgot password?
          </a>
        </div>
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
