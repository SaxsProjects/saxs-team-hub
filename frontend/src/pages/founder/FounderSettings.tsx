import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { api, post } from "../../api/client";
import type { AuditEntry, CompanyDetails, FinanceReadiness, NotificationPrefs } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { TrustedDevices } from "../../components/TrustedDevices";
import { Dialog, Done, Field, FormError, PageHead, Skeleton } from "../../components/ui";
import { describeAudit } from "../../lib/activity";
import { clock, shortDate } from "../../lib/format";
import { PasswordDialog } from "../member/MemberSettings";
import "../overview.css";
import "../pages.css";

/** Emails the backend sends to the founder (jobs.py, me.py, offers.py); each can be switched off. */
const NOTIFICATIONS: { key: keyof NotificationPrefs; title: string; sub: string }[] = [
  { key: "offers", title: "Offer updates", sub: "Offers that pass their deadline without an answer" },
  { key: "reviews", title: "Task Order reviews", sub: "Submissions waiting past the review deadline" },
  { key: "payouts", title: "Payout reminders", sub: "Payment requests and payouts that are due" },
  { key: "invoices", title: "Invoice reminders", sub: "Invoices past their due date" },
  {
    key: "client_reminders",
    title: "Autopilot: client payment reminders",
    sub: "Emails each client a reminder 3 days before an invoice is due, then 1, 7 and 14 days after (once each), with the invoice attached",
  },
  {
    key: "client_statements",
    title: "Autopilot: monthly statements",
    sub: "On the 1st, emails a statement of account (SP-SOA) to every client who owes money",
  },
];

type CompanyField = {
  key: keyof CompanyDetails;
  label: string;
  hint?: string;
  type?: string;
  inputMode?: "numeric" | "email" | "tel" | "url";
  multiline?: boolean;
};

const COMPANY_FIELDS: CompanyField[] = [
  { key: "company_legal_name", label: "Registered name" },
  { key: "company_registration_number", label: "Registration number", hint: "As on your CIPC certificate, e.g. 2026/123456/07." },
  {
    key: "company_vat_number",
    label: "VAT number",
    hint: "Leave empty if not VAT registered. Once set, new invoices are tax invoices with 15% VAT.",
    inputMode: "numeric",
  },
  { key: "company_address", label: "Address", hint: "One line per row, as it should print on documents.", multiline: true },
  { key: "company_email", label: "Accounts email", type: "email", inputMode: "email" },
  { key: "company_phone", label: "Phone", type: "tel", inputMode: "tel" },
  { key: "company_website", label: "Website", inputMode: "url" },
  { key: "company_whatsapp", label: "WhatsApp", type: "tel", inputMode: "tel", hint: "Printed on quotations, invoices and receipts." },
  { key: "signatory_name", label: "Signatory name", hint: "The person whose signature prints on issued documents." },
  { key: "signatory_title", label: "Signatory title" },
];

const BANK_FIELDS: CompanyField[] = [
  { key: "company_bank_name", label: "Bank" },
  { key: "company_bank_account_name", label: "Account holder", hint: "Leave empty to use the registered name." },
  { key: "company_bank_account_number", label: "Account number", inputMode: "numeric" },
  { key: "company_bank_branch_code", label: "Branch code", hint: "6 digits.", inputMode: "numeric" },
  { key: "company_bank_account_type", label: "Account type", hint: "e.g. Business current account." },
];

export function FounderSettings() {
  const { me, signOut } = useAuth();
  const readiness = useQuery({ queryKey: ["finance", "readiness"], queryFn: () => api<FinanceReadiness>("/api/finance/readiness") });
  const company = useQuery({ queryKey: ["company"], queryFn: () => api<CompanyDetails>("/api/company") });
  const security = useQuery({ queryKey: ["audit", "account"], queryFn: () => api<AuditEntry[]>("/api/audit?scope=account&limit=5") });
  const [dialog, setDialog] = useState<null | "password" | "2fa" | "company" | "bank">(null);
  const [done, setDone] = useState<string | null>(null);
  const r = readiness.data;
  const c = company.data;
  const canEdit = !!me?.totp_enabled;

  return (
    <div className="page">
      <PageHead title="Settings" sub="Your workspace, profile and preferences." />
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
            {r && (
              <span className={`chip ${r.missing.length ? "chip-warning" : "chip-success"}`}>{r.missing.length ? "Details missing" : "Ready to invoice"}</span>
            )}
          </div>
          <div className="form-card">
            {(readiness.isPending || company.isPending) && <Skeleton h={160} />}
            <FormError error={company.error ?? readiness.error} />
            {r && c && (
              <>
                <SettingRow title="Trading name" sub={c.company_name}>
                  <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("company"))} disabled={!canEdit}>
                    Edit details
                  </button>
                </SettingRow>
                <hr className="divider" />
                <SettingRow title="Registered name" sub={[c.company_legal_name, c.company_registration_number].filter(Boolean).join(" · ") || "Not set"} />
                <SettingRow title="VAT status" sub={c.company_vat_number ? `VAT no. ${c.company_vat_number}` : "No VAT is charged on invoices"}>
                  <span className={`chip ${r.vat_registered ? "chip-success" : "chip-neutral"}`}>
                    {r.vat_registered ? "VAT registered" : "Not VAT registered"}
                  </span>
                </SettingRow>
                <SettingRow title="Signs documents" sub={c.signatory_name ? `${c.signatory_name}, ${c.signatory_title}` : "Not set"}>
                  <span className={`chip ${r.signature_set ? "chip-success" : "chip-warning"}`}>{r.signature_set ? "Signature on file" : "No signature"}</span>
                </SettingRow>
                <hr className="divider" />
                <SettingRow
                  title="Banking details"
                  sub={r.bank_details_set ? `${c.company_bank_name} · ${maskAccount(c.company_bank_account_number)}` : "Not set: invoices can’t be issued yet"}
                  subClass={r.bank_details_set ? "success-text" : "warning-text"}
                >
                  <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("bank"))} disabled={!canEdit}>
                    Manage securely
                  </button>
                </SettingRow>
                <p className="field-hint">
                  {canEdit
                    ? "These print on quotations, invoices, receipts and statements. Changes need your password, are recorded and are emailed to you."
                    : "Turn on two-factor authentication to edit company details."}
                </p>
              </>
            )}
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Security</h3>
          </div>
          <div className="form-card">
            <SettingRow
              title="Two-factor authentication"
              sub={me?.totp_enabled ? "Enabled" : "Off"}
              subClass={me?.totp_enabled ? "success-text" : "warning-text"}
            >
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
            <hr className="divider" />
            <TrustedDevices />
            <hr className="divider" />
            <div>
              <p className="setting-title">Recent sign-ins and security events</p>
              {security.isPending && <Skeleton h={80} />}
              <FormError error={security.error} />
              {security.data?.length === 0 && <p className="row-sub">Nothing yet.</p>}
              {!!security.data?.length && (
                <ul className="security-log">
                  {security.data.map((e) => {
                    const d = describeAudit(e);
                    return (
                      <li key={e.id} className={d.tone === "amber" ? "warning-text" : undefined}>
                        <span>{d.title}</span>
                        <time dateTime={e.at}>
                          {shortDate(e.at)} · {clock(e.at)}
                        </time>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </section>

        <NotificationsCard />
      </div>

      {dialog === "password" && <PasswordDialog onClose={() => setDialog(null)} onDone={() => (setDialog(null), setDone("Password changed."))} />}
      {dialog === "2fa" && <TwoFactorDialog onClose={() => setDialog(null)} onDone={() => (setDialog(null), setDone("Two-factor authentication is on."))} />}
      {(dialog === "company" || dialog === "bank") && c && (
        <CompanyDialog bank={dialog === "bank"} current={c} onClose={() => setDialog(null)} onDone={(text) => (setDialog(null), setDone(text))} />
      )}
    </div>
  );
}

function maskAccount(n: string): string {
  return n ? `•••• ${n.slice(-4)}` : "";
}

/** Switches save as soon as they're flipped, like any on/off switch; a failed save flips back and says why. */
function NotificationsCard() {
  const qc = useQueryClient();
  const saved = useQuery({ queryKey: ["notifications"], queryFn: () => api<NotificationPrefs>("/api/auth/notifications") });
  const [status, setStatus] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (next: NotificationPrefs) => api<NotificationPrefs>("/api/auth/notifications", { method: "PUT", body: JSON.stringify(next) }),
    onMutate: (next) => {
      const before = qc.getQueryData<NotificationPrefs>(["notifications"]);
      qc.setQueryData(["notifications"], next);
      setStatus(null);
      return { before };
    },
    onError: (_e, _next, ctx) => qc.setQueryData(["notifications"], ctx?.before),
    onSuccess: (data) => (qc.setQueryData(["notifications"], data), setStatus("Saved")),
  });
  const prefs = saved.data;

  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Notifications</h3>
        <span className={`th-note ${status && !save.isPending ? "success-text" : ""}`} role="status" aria-live="polite">
          {save.isPending ? "Saving…" : (status ?? "Emails to you and your clients; the bell always shows everything")}
        </span>
      </div>
      <div className="form-card">
        {saved.isPending && <Skeleton h={160} />}
        <FormError error={saved.error ?? save.error} />
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
                  disabled={save.isPending}
                  onClick={() => save.mutate({ ...prefs, [n.key]: !prefs[n.key] })}
                >
                  <span className="switch-knob" />
                </button>
              </SettingRow>
            </div>
          ))}
      </div>
    </section>
  );
}

function CompanyDialog({ bank, current, onClose, onDone }: { bank: boolean; current: CompanyDetails; onClose: () => void; onDone: (text: string) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<CompanyDetails>(current);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const fields = bank ? BANK_FIELDS : COMPANY_FIELDS;
  const save = useMutation({
    mutationFn: () => api<CompanyDetails>("/api/company", { method: "PUT", body: JSON.stringify({ ...form, current_password: password }) }),
    onSuccess: (data) => {
      qc.setQueryData(["company"], data);
      qc.invalidateQueries({ queryKey: ["finance", "readiness"] });
      onDone(`${bank ? "Banking" : "Company"} details saved. A confirmation email is on its way to you.`);
    },
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!bank && form.company_legal_name.trim().length < 2) return setError("Enter the company’s registered name.");
    if (!password) return setError("Enter your current password to save these changes.");
    setError(null);
    save.mutate();
  }

  return (
    <Dialog title={bank ? "Banking details" : "Company details"} onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        {bank && (
          <p className="detail-p">
            This is the account clients pay into. It prints on every invoice, so changing it needs your password and is emailed to you.
          </p>
        )}
        {fields.map((f, i) => (
          <Field key={f.key} id={`co-${f.key}`} label={f.label} hint={f.hint}>
            {f.multiline ? (
              // Stored as "line|line|line" on the server; edited as real lines here.
              <textarea
                id={`co-${f.key}`}
                className="input"
                rows={3}
                value={form[f.key].replace(/\|/g, "\n")}
                onChange={(e) => setForm({ ...form, [f.key]: e.target.value.replace(/\r?\n/g, "|") })}
              />
            ) : (
              <input
                id={`co-${f.key}`}
                className="input"
                type={f.type ?? "text"}
                inputMode={f.inputMode}
                autoFocus={i === 0}
                value={form[f.key]}
                onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              />
            )}
          </Field>
        ))}
        <Field id="co-password" label="Your current password" hint="Needed for any change: these details tell clients how to pay you.">
          <input
            id="co-password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function SettingRow({ title, sub, subClass, children }: { title: string; sub: string; subClass?: string; children?: ReactNode }) {
  return (
    <div className="setting-row">
      <div>
        <p className="setting-title">{title}</p>
        {sub && <p className={`row-sub ${subClass ?? ""}`}>{sub}</p>}
      </div>
      {children}
    </div>
  );
}

function TwoFactorDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const setup = useQuery({
    queryKey: ["2fa-setup"],
    queryFn: () => post<{ secret: string; otpauth_uri: string }>("/api/auth/2fa/setup"),
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  });
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
          <input
            id="tf-code"
            className="input num"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
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
