import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, post } from "../../api/client";
import type { FinanceReadiness, NotificationPrefs } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Dialog, Done, Field, FormError, PageHead, Skeleton } from "../../components/ui";
import { PasswordDialog } from "../member/MemberSettings";
import "../overview.css";
import "../pages.css";

/** Emails the backend sends to the founder (jobs.py, me.py, offers.py); each can be switched off. */
const NOTIFICATIONS: { key: keyof NotificationPrefs; title: string; sub: string }[] = [
  { key: "offers", title: "Offer updates", sub: "Offers that pass their deadline without an answer" },
  { key: "reviews", title: "Task Order reviews", sub: "Submissions waiting past the review deadline" },
  { key: "payouts", title: "Payout reminders", sub: "Payment requests and payouts that are due" },
  { key: "invoices", title: "Invoice reminders", sub: "Invoices past their due date" },
];

export function FounderSettings() {
  const { me, signOut } = useAuth();
  const readiness = useQuery({ queryKey: ["finance", "readiness"], queryFn: () => api<FinanceReadiness>("/api/finance/readiness") });
  const [dialog, setDialog] = useState<null | "password" | "2fa">(null);
  const [done, setDone] = useState<string | null>(null);
  const r = readiness.data;
  const qc = useQueryClient();
  const saved = useQuery({ queryKey: ["notifications"], queryFn: () => api<NotificationPrefs>("/api/auth/notifications") });
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  useEffect(() => {
    if (saved.data) setPrefs(saved.data);
  }, [saved.data]);
  const dirty = !!prefs && !!saved.data && NOTIFICATIONS.some((n) => prefs[n.key] !== saved.data[n.key]);
  const save = useMutation({
    mutationFn: () => api<NotificationPrefs>("/api/auth/notifications", { method: "PUT", body: JSON.stringify(prefs) }),
    onSuccess: (data) => (qc.setQueryData(["notifications"], data), setDone("Notification settings saved.")),
  });

  return (
    <div className="page">
      <PageHead title="Settings" sub="Your workspace, profile and preferences.">
        <button className="btn btn-primary" disabled={!dirty || save.isPending} onClick={() => (setDone(null), save.mutate())}>
          Save changes
        </button>
      </PageHead>
      <FormError error={save.error ?? saved.error} />
      <Done text={done} />

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Your profile</h3>
          </div>
          <div className="form-card">
            <Field id="s-name" label="Full name">
              <input id="s-name" className="input" readOnly value={me?.full_name ?? "Phathutshedzo Mamagau"} />
            </Field>
            <Field id="s-email" label="Email address">
              <input id="s-email" className="input" readOnly value={me?.email ?? ""} />
            </Field>
            <Field id="s-tz" label="Time zone" hint="All dates and deadlines use South African time.">
              <input id="s-tz" className="input" readOnly value="Africa/Johannesburg · SAST" />
            </Field>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Company</h3>
            {r && <span className={`chip ${r.missing.length ? "chip-warning" : "chip-success"}`}>{r.missing.length ? "Details missing" : "Ready to invoice"}</span>}
          </div>
          <div className="form-card">
            {!r && <Skeleton h={160} />}
            {r && (
              <>
                <Status title="VAT status" ok={r.vat_registered} okText="VAT registered" offText="Not VAT registered" neutral />
                <Status title="Registration number" ok={r.registration_number_set} />
                <Status title="Banking details" ok={r.bank_details_set} />
                <Status title="Signatory name" ok={r.signatory_name_set} />
                <Status title="Signature" ok={r.signature_set} />
                <p className="field-hint">Company details are kept in the server settings so they can’t be changed from a browser. They print on quotations, invoices and receipts.</p>
              </>
            )}
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Security</h3>
          </div>
          <div className="form-card">
            <SettingRow title="Two-factor authentication" sub={me?.totp_enabled ? "Enabled" : "Off"} subClass={me?.totp_enabled ? "success-text" : "warning-text"}>
              {!me?.totp_enabled && (
                <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("2fa"))}>
                  Turn on 2FA
                </button>
              )}
            </SettingRow>
            <hr className="divider" />
            <SettingRow title="Password" sub="Change it at any time">
              <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("password"))}>
                Change password
              </button>
            </SettingRow>
            <hr className="divider" />
            <SettingRow title="This session" sub="Signed in on this device">
              <button className="btn btn-secondary" onClick={() => signOut()}>
                Sign out
              </button>
            </SettingRow>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Notifications</h3>
            <span className="th-note">Emailed to you</span>
          </div>
          <div className="form-card">
            {!prefs && !saved.error && <Skeleton h={160} />}
            {prefs &&
              NOTIFICATIONS.map((n, i) => (
                <div key={n.key}>
                  {i > 0 && <hr className="divider" style={{ marginBottom: 14 }} />}
                  <SettingRow title={n.title} sub={n.sub}>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={prefs[n.key]}
                      aria-label={n.title}
                      className="switch"
                      onClick={() => setPrefs({ ...prefs, [n.key]: !prefs[n.key] })}
                    >
                      <span className="switch-knob" />
                    </button>
                  </SettingRow>
                </div>
              ))}
          </div>
        </section>
      </div>

      {dialog === "password" && <PasswordDialog onClose={() => setDialog(null)} onDone={() => (setDialog(null), setDone("Password changed."))} />}
      {dialog === "2fa" && <TwoFactorDialog onClose={() => setDialog(null)} onDone={() => (setDialog(null), setDone("Two-factor authentication is on."))} />}
    </div>
  );
}

function SettingRow({ title, sub, subClass, children }: { title: string; sub: string; subClass?: string; children?: ReactNode }) {
  return (
    <div className="setting-row">
      <div>
        <p className="setting-title">{title}</p>
        <p className={`row-sub ${subClass ?? ""}`}>{sub}</p>
      </div>
      {children}
    </div>
  );
}

function Status({ title, ok, okText = "Configured", offText = "Missing", neutral }: { title: string; ok: boolean; okText?: string; offText?: string; neutral?: boolean }) {
  return (
    <SettingRow title={title} sub="">
      <span className={`chip ${ok ? "chip-success" : neutral ? "chip-neutral" : "chip-warning"}`}>{ok ? okText : offText}</span>
    </SettingRow>
  );
}

function TwoFactorDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const setup = useQuery({ queryKey: ["2fa-setup"], queryFn: () => post<{ secret: string; otpauth_uri: string }>("/api/auth/2fa/setup"), staleTime: Infinity, gcTime: 0, retry: false });
  const enable = useMutation({
    mutationFn: () => post("/api/auth/2fa/enable", { code: code.trim() }),
    onSuccess: () => (qc.invalidateQueries({ queryKey: ["me"] }), onDone()),
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!/^\d{6}$/.test(code.trim())) return setError("Enter the 6-digit code from your authenticator app.");
    setError(null);
    enable.mutate();
  }

  return (
    <Dialog title="Turn on two-factor" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <p className="detail-p">In your authenticator app, add an account using this setup key, then enter the 6-digit code it shows.</p>
        {setup.isPending && <Skeleton h={44} />}
        <FormError error={setup.error} />
        {setup.data && (
          <Field id="tf-key" label="Setup key">
            <input id="tf-key" className="input num" readOnly value={setup.data.secret.replace(/(.{4})/g, "$1 ").trim()} onFocus={(e) => e.target.select()} />
          </Field>
        )}
        <Field id="tf-code" label="6-digit code">
          <input id="tf-code" className="input num" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={enable.isPending || !setup.data}>
            Turn on
          </button>
        </div>
      </form>
    </Dialog>
  );
}
