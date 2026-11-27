import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api, setSession } from "../../api/client";
import type { MaskedBanking, Person, TokenOut } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { TrustedDevices } from "../../components/TrustedDevices";
import { Dialog, ErrorNote, PageHead, Skeleton } from "../../components/ui";
import "../overview.css";
import "../pages.css";

/** The saved banking details (masked), or null when none have been added yet. */
async function banking(): Promise<MaskedBanking | null> {
  try {
    return await api<MaskedBanking>("/api/me/sensitive");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export function MemberSettings() {
  const { me, signOut } = useAuth();
  const profile = useQuery({ queryKey: ["me-profile"], queryFn: () => api<Person>("/api/me/profile") });
  const bank = useQuery({ queryKey: ["me-banking"], queryFn: banking });
  const [editingBank, setEditingBank] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  return (
    <div className="page">
      <PageHead title="Settings" sub="Your profile, banking details and account security." />
      {done && (
        <p className="form-ok" role="status">
          <CheckCircle2 size={16} aria-hidden="true" /> {done}
        </p>
      )}

      <div className="split">
        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Profile</h3>
              <span className="chip chip-brand">Team member</span>
            </div>
            <div className="form-card">
              {profile.isError && <ErrorNote error={profile.error} onRetry={() => profile.refetch()} />}
              <div className="form-row">
                <div className="field">
                  <label htmlFor="full-name">Full name</label>
                  {profile.data ? <input id="full-name" className="input" readOnly value={profile.data.full_name} /> : <Skeleton h={44} />}
                </div>
                <div className="field">
                  <label htmlFor="email">Email address</label>
                  <input id="email" className="input" readOnly value={profile.data?.email ?? me?.email ?? ""} />
                </div>
              </div>
              <hr className="divider" />
              <div className="setting">
                <p className="field-hint">Need to update your name or email?</p>
                <p className="setting-title" style={{ color: "var(--brand)" }}>
                  Contact your founder
                </p>
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Banking details</h3>
              {bank.data && <span className="chip chip-success">Saved</span>}
              {bank.data === null && <span className="chip chip-warning">Not added</span>}
            </div>
            <div className="form-card">
              {bank.isError && <ErrorNote error={bank.error} onRetry={() => bank.refetch()} />}
              {bank.isPending && <Skeleton h={100} />}
              {bank.data && (
                <>
                  <div className="form-row">
                    <ReadField id="bank" label="Bank" value={bank.data.bank_name} />
                    <ReadField id="acct" label="Account number" value={bank.data.account_number.replace(/^\*+/, "•••• •••• ")} />
                  </div>
                  <div className="form-row">
                    <ReadField id="holder" label="Account holder" value={bank.data.account_holder} />
                    <div className="form-actions">
                      <button className="btn btn-secondary" onClick={() => (setDone(null), setEditingBank(true))}>
                        Update banking details
                      </button>
                    </div>
                  </div>
                </>
              )}
              {bank.data === null && !editingBank && (
                <div className="form-actions" style={{ justifyContent: "space-between" }}>
                  <p className="field-hint">Add the account we should pay your payouts into. It’s stored encrypted.</p>
                  <button className="btn btn-primary" onClick={() => (setDone(null), setEditingBank(true))}>
                    Add banking details
                  </button>
                </div>
              )}
              {editingBank && (
                <BankForm
                  initial={bank.data ?? null}
                  onCancel={() => setEditingBank(false)}
                  onSaved={() => (setEditingBank(false), setDone("Banking details saved."))}
                />
              )}
            </div>
          </section>
        </div>

        <div className="stack">
          <section className="card detail">
            <span className="icon-tile" aria-hidden="true">
              <Lock size={18} />
            </span>
            <h3 className="detail-title" style={{ marginTop: 14 }}>
              Account security
            </h3>
            <div className="setting" style={{ marginTop: 14 }}>
              <div className="setting-head">
                <span className="setting-title">Two-factor authentication</span>
                <span className={`chip ${me?.totp_enabled ? "chip-success" : "chip-neutral"}`}>{me?.totp_enabled ? "Enabled" : "Off"}</span>
              </div>
              <p className="field-hint">
                {me?.totp_enabled ? "Authenticator app" : "Sign-in codes aren’t required for team members yet."}
              </p>
            </div>
            <hr className="divider" />
            <div className="setting">
              <span className="setting-title">Password</span>
              <p className="field-hint">Update your password at any time.</p>
              <button className="btn btn-secondary btn-block" style={{ marginTop: 10 }} onClick={() => (setDone(null), setChangingPassword(true))}>
                Change password
              </button>
            </div>
            <hr className="divider" />
            <TrustedDevices />
            <button className="link-btn" style={{ justifySelf: "start", marginTop: 18 }} onClick={() => signOut()}>
              Sign out of this account
            </button>
          </section>
          <section className="card detail">
            <h3 className="card-title" style={{ fontSize: 15 }}>
              Email notifications
            </h3>
            <p className="detail-p" style={{ marginTop: 8 }}>
              Task updates, payout confirmations and account alerts go to your account email.
            </p>
          </section>
        </div>
      </div>

      {changingPassword && <PasswordDialog onClose={() => setChangingPassword(false)} onDone={() => (setChangingPassword(false), setDone("Password changed. Other devices have been signed out."))} />}
    </div>
  );
}

function ReadField({ id, label, value }: { id: string; label: string; value: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="input" readOnly value={value} />
    </div>
  );
}

function BankForm({ initial, onCancel, onSaved }: { initial: MaskedBanking | null; onCancel: () => void; onSaved: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    bank_name: initial?.bank_name ?? "",
    account_holder: initial?.account_holder ?? "",
    account_number: "",
    branch_code: initial?.branch_code ?? "",
    account_type: initial?.account_type ?? "cheque",
  });
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api<void>("/api/me/sensitive", { method: "PUT", body: JSON.stringify(f) }),
    onSuccess: () => {
      for (const k of ["me-banking", "me-onboarding", "me-overview"]) qc.invalidateQueries({ queryKey: [k] });
      onSaved();
    },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.bank_name.trim().length < 2 || f.account_holder.trim().length < 2) return setError("Enter the bank and the account holder’s name.");
    if (!/^[0-9 ]{6,20}$/.test(f.account_number)) return setError("Enter the full account number (digits only).");
    if (!/^[0-9]{4,10}$/.test(f.branch_code)) return setError("Enter the branch code (digits only).");
    setError(null);
    save.mutate();
  }

  return (
    <form onSubmit={submit} noValidate style={{ display: "grid", gap: 16 }}>
      <div className="form-row">
        <div className="field">
          <label htmlFor="b-bank">Bank</label>
          <input id="b-bank" className="input" autoComplete="off" value={f.bank_name} onChange={set("bank_name")} />
        </div>
        <div className="field">
          <label htmlFor="b-holder">Account holder</label>
          <input id="b-holder" className="input" autoComplete="off" value={f.account_holder} onChange={set("account_holder")} />
        </div>
      </div>
      <div className="form-row">
        <div className="field">
          <label htmlFor="b-number">Account number</label>
          <input id="b-number" className="input" inputMode="numeric" autoComplete="off" value={f.account_number} onChange={set("account_number")} />
          {initial && <span className="field-hint">Enter the full number again to change it.</span>}
        </div>
        <div className="field">
          <label htmlFor="b-branch">Branch code</label>
          <input id="b-branch" className="input" inputMode="numeric" autoComplete="off" value={f.branch_code} onChange={set("branch_code")} />
        </div>
      </div>
      <div className="field" style={{ maxWidth: 240 }}>
        <label htmlFor="b-type">Account type</label>
        <select id="b-type" className="input" value={f.account_type} onChange={set("account_type")}>
          <option value="cheque">Cheque / current</option>
          <option value="savings">Savings</option>
          <option value="transmission">Transmission</option>
        </select>
      </div>
      {(error || save.error) && (
        <p className="form-error" role="alert">
          {error ?? (save.error instanceof Error ? save.error.message : "Couldn’t save.")}
        </p>
      )}
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save banking details"}
        </button>
      </div>
    </form>
  );
}

export function PasswordDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () =>
      api<TokenOut>("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: current, new_password: next }) }),
    onSuccess: (t) => (setSession(t.access_token, t.expires_in), onDone()),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!current) return setError("Enter your current password.");
    if (next.length < 10) return setError("The new password needs at least 10 characters.");
    if (next !== again) return setError("The new passwords don’t match.");
    setError(null);
    change.mutate();
  }

  return (
    <Dialog title="Change password" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <div className="field">
          <label htmlFor="pw-current">Current password</label>
          <input id="pw-current" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <label htmlFor="pw-new">New password</label>
          <input id="pw-new" className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <span className="field-hint">At least 10 characters.</span>
        </div>
        <div className="field">
          <label htmlFor="pw-again">Repeat new password</label>
          <input id="pw-again" className="input" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
        </div>
        {(error || change.error) && (
          <p className="form-error" role="alert">
            {error ?? (change.error instanceof Error ? change.error.message : "Couldn’t change the password.")}
          </p>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={change.isPending}>
            {change.isPending ? "Saving…" : "Change password"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
