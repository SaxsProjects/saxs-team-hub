import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, post } from "../../api/client";
import type { ApiKey, ApiKeyScope, NewApiKey } from "../../api/types";
import { Dialog, Field, FormError, Skeleton } from "../../components/ui";
import { shortDate } from "../../lib/format";

const SCOPES: { key: ApiKeyScope; label: string }[] = [
  { key: "clients:read", label: "Read clients" },
  { key: "quotations:read", label: "Read quotations" },
  { key: "invoices:read", label: "Read invoices" },
  { key: "enquiries:read", label: "Read website enquiries" },
  { key: "proposals:draft", label: "Save draft proposals (you review and issue them)" },
];

/** Keys for other SaxsProjects systems such as SAXI-OS. No key can issue documents, record payments or move money. */
export function ApiKeysCard() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api<ApiKey[]>("/api/api-keys") });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const revoke = useMutation({
    mutationFn: (id: number) => post<ApiKey>(`/api/api-keys/${id}/revoke`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
    onError: setError,
  });

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3 className="card-title">Connected systems</h3>
          <p className="card-sub">Keys for SAXI-OS and other company systems. They can read and save drafts; only you issue documents and handle money.</p>
        </div>
        <button className="btn btn-secondary" onClick={() => setOpen(true)}>
          New key
        </button>
      </div>
      <FormError error={keys.error ?? error} />
      {keys.isPending && <Skeleton h={60} />}
      {keys.data && keys.data.length === 0 && <p className="empty">No keys yet.</p>}
      <ul className="doc-list">
        {keys.data?.map((k) => (
          <li key={k.id} style={{ alignItems: "center" }}>
            <div className="doc-text">
              <p className="row-title">
                {k.name} <span className="row-sub num">{k.prefix}…</span>
              </p>
              <p className="row-sub">
                {k.scopes.join(", ")} · made {shortDate(k.created_at)} · {k.last_used_at ? `last used ${shortDate(k.last_used_at)}` : "never used"}
              </p>
            </div>
            {k.revoked_at ? (
              <span className="chip chip-neutral">Revoked</span>
            ) : (
              <button className="btn btn-ghost" disabled={revoke.isPending} onClick={() => (setError(null), revoke.mutate(k.id))}>
                Revoke
              </button>
            )}
          </li>
        ))}
      </ul>
      {open && <NewKeyDialog onClose={() => setOpen(false)} onMade={() => qc.invalidateQueries({ queryKey: ["api-keys"] })} />}
    </section>
  );
}

function NewKeyDialog({ onClose, onMade }: { onClose: () => void; onMade: () => void }) {
  const [name, setName] = useState("SAXI-OS");
  const [scopes, setScopes] = useState<ApiKeyScope[]>(["clients:read", "enquiries:read", "proposals:draft"]);
  const [error, setError] = useState<unknown>(null);
  const make = useMutation({ mutationFn: () => post<NewApiKey>("/api/api-keys", { name: name.trim(), scopes }), onSuccess: onMade, onError: setError });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) return setError("Give the key a name.");
    if (!scopes.length) return setError("Choose at least one permission.");
    setError(null);
    make.mutate();
  }

  return (
    <Dialog title={make.data ? "Copy the key now" : "New key"} onClose={onClose}>
      {make.data ? (
        <div style={{ display: "grid", gap: 12 }}>
          <p>This is the only time the key is shown. Put it in the other system's secret settings (never in code).</p>
          <input className="input num" readOnly value={make.data.key} aria-label="New API key" onFocus={(e) => e.currentTarget.select()} />
          <div className="detail-actions">
            <button className="btn btn-secondary" onClick={() => navigator.clipboard?.writeText(make.data!.key)}>
              Copy
            </button>
            <button className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
          <Field id="key-name" label="Name">
            <input id="key-name" className="input" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <fieldset style={{ border: 0, padding: 0, display: "grid", gap: 8 }}>
            <legend className="stat-label">Permissions</legend>
            {SCOPES.map((s) => (
              <label key={s.key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={scopes.includes(s.key)}
                  onChange={(e) => setScopes(e.target.checked ? [...scopes, s.key] : scopes.filter((x) => x !== s.key))}
                />
                {s.label}
              </label>
            ))}
          </fieldset>
          <FormError error={error} />
          <div className="detail-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={make.isPending}>
              {make.isPending ? "Making…" : "Make key"}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
