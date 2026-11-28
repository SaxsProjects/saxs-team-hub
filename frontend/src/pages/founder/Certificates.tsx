import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, apiBlob, post } from "../../api/client";
import type { Certificate, CertificateKind, CertificatePreset } from "../../api/types";
import { usePreview, useViewFile } from "../../components/DocumentPreview";
import { Dialog, Done, EmptyRow, ErrorNote, Field, FormError, LoadingRow, PageHead, RowButton } from "../../components/ui";
import { fullDay, shortDay, todaySA } from "../../lib/format";
import "../overview.css";
import "../pages.css";

const KIND_LABEL: Record<CertificateKind, string> = {
  completion: "Completion",
  achievement: "Achievement",
  appreciation: "Appreciation",
  participation: "Participation",
  recognition: "Recognition",
  training: "Training",
  service: "Service",
  project: "Project completion",
  partnership: "Partnership",
  custom: "Custom",
};

async function blobFromResponse(path: string, body: unknown): Promise<Blob> {
  return apiBlob(path, { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
}

export function Certificates() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["certificates"], queryFn: () => api<Certificate[]>("/api/certificates") });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"new" | "revoke" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const view = useViewFile();
  const refresh = () => qc.invalidateQueries({ queryKey: ["certificates"] });

  if (list.isError) return <ErrorNote error={list.error} onRetry={() => list.refetch()} />;
  const rows = list.data ?? [];
  const selected = rows.find((c) => c.id === selectedId) ?? rows[0];

  return (
    <div className="page">
      <PageHead title="Certificates" sub="One official design for every certificate: completion, training, service, partnership and more. Each has a number and a verification link.">
        <button className="btn btn-primary" onClick={() => (setDone(null), setDialog("new"))}>
          <Plus size={16} aria-hidden="true" /> New certificate
        </button>
      </PageHead>
      <Done text={done} />
      <div className="split">
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Certificate</th>
                  <th className="hide-sm">Type</th>
                  <th>Date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {list.isPending && <LoadingRow cols={4} />}
                {list.data && rows.length === 0 && <EmptyRow cols={4} text="No certificates issued yet." />}
                {rows.map((c) => (
                  <RowButton key={c.id} selected={c.id === selected?.id} onSelect={() => setSelectedId(c.id)}>
                    <td>
                      <p className="row-title">{c.recipient_name}</p>
                      <p className="row-sub num">{c.number}</p>
                    </td>
                    <td className="hide-sm muted">{KIND_LABEL[c.kind]}</td>
                    <td>{shortDay(c.issue_date)}</td>
                    <td>
                      <span className={`chip ${c.revoked_at ? "chip-warning" : "chip-success"}`}>{c.revoked_at ? "Revoked" : "Valid"}</span>
                    </td>
                  </RowButton>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        {selected && (
          <section className="card detail" aria-label="Certificate details">
            <span className="detail-icon" aria-hidden="true">
              <Award size={20} />
            </span>
            <h3 className="detail-title" style={{ marginTop: 18 }}>
              {selected.recipient_name}
            </h3>
            <p className="detail-ref num">
              {selected.number} · {[selected.title, selected.subtitle].filter(Boolean).join(" ")}
            </p>
            <p className="row-sub" style={{ marginTop: 8 }}>
              {selected.body}
            </p>
            <hr className="divider" />
            <dl className="kv">
              <div>
                <dt>Date</dt>
                <dd>
                  {fullDay(selected.issue_date)}, {selected.place}
                </dd>
              </div>
              <div>
                <dt>Verification link</dt>
                <dd style={{ wordBreak: "break-all" }}>
                  <a href={selected.verify_url} target="_blank" rel="noopener noreferrer">
                    {selected.verify_url}
                  </a>
                </dd>
              </div>
              {selected.revoked_at && (
                <div>
                  <dt>Revoked</dt>
                  <dd>
                    {fullDay(selected.revoked_at)}: {selected.revoke_reason}
                  </dd>
                </div>
              )}
            </dl>
            <div className="form-row" style={{ gap: 10, marginTop: 14, flexWrap: "wrap" }}>
              <button className="btn btn-primary" onClick={() => view(`/api/certificates/${selected.id}/pdf`, `${selected.number}.pdf`, `Certificate ${selected.number}`)}>
                View PDF
              </button>
              {!selected.revoked_at && (
                <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("revoke"))}>
                  Revoke
                </button>
              )}
            </div>
          </section>
        )}
      </div>
      {dialog === "new" && <NewCertificate onClose={() => setDialog(null)} onIssued={(c) => (refresh(), setSelectedId(c.id), setDialog(null), setDone(`Certificate ${c.number} issued.`))} />}
      {dialog === "revoke" && selected && <Revoke cert={selected} onClose={() => setDialog(null)} onDone={(c) => (refresh(), setDialog(null), setDone(`${c.number} revoked. The verification page now says so.`))} />}
    </div>
  );
}

function NewCertificate({ onClose, onIssued }: { onClose: () => void; onIssued: (c: Certificate) => void }) {
  const presets = useQuery({ queryKey: ["certificate-presets"], queryFn: () => api<CertificatePreset[]>("/api/certificates/presets") });
  const [kind, setKind] = useState<CertificateKind>("completion");
  const [f, setF] = useState({ recipient_name: "", body: "", subtitle: "", issue_date: todaySA() });
  const [error, setError] = useState<unknown>(null);
  const [edited, setEdited] = useState(false); // until the text is edited, it follows the chosen type's wording
  const preview = usePreview();
  const p = presets.data?.find((x) => x.kind === kind);
  const text = edited ? f.body : (p?.body ?? "");

  const body = () => ({
    kind,
    recipient_name: f.recipient_name.trim(),
    body: text.trim(),
    subtitle: kind === "custom" ? f.subtitle.trim() : undefined,
    issue_date: f.issue_date || undefined,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.recipient_name.trim().length < 2) return setError("Enter the recipient's full name.");
    const b = body();
    if (b.body.length < 3) return setError("Write what the certificate is for.");
    if (b.body.includes("____")) return setError("Fill in the blanks (____) in the certificate text.");
    setError(null);
    preview({
      title: `Certificate for ${b.recipient_name}`,
      filename: "certificate-preview.pdf",
      note: "Issuing gives it the next SP-CERT number, the director's signature and its own verification link. It cannot be edited afterwards, only revoked.",
      load: () => blobFromResponse("/api/certificates/preview", b),
      confirm: { label: "Issue certificate", run: () => post<Certificate>("/api/certificates", b).then(onIssued) },
    });
  }

  return (
    <Dialog title="New certificate" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="c-kind" label="Type">
            <select
              id="c-kind"
              className="input"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as CertificateKind);
                setEdited(false);
              }}
            >
              {(Object.keys(KIND_LABEL) as CertificateKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </Field>
          <Field id="c-date" label="Date">
            <input id="c-date" className="input" type="date" max={todaySA()} value={f.issue_date} onChange={(e) => setF({ ...f, issue_date: e.target.value })} />
          </Field>
        </div>
        {kind === "custom" && (
          <Field id="c-sub" label="Second title line (e.g. OF EXCELLENCE)">
            <input id="c-sub" className="input" maxLength={40} value={f.subtitle} onChange={(e) => setF({ ...f, subtitle: e.target.value })} />
          </Field>
        )}
        <Field id="c-name" label="Awarded to (full name)">
          <input id="c-name" className="input" maxLength={200} value={f.recipient_name} onChange={(e) => setF({ ...f, recipient_name: e.target.value })} autoFocus />
        </Field>
        <Field id="c-body" label="What it certifies" hint={p ? `${p.lead} [name] ...` : undefined}>
          <textarea id="c-body" className="input textarea" rows={3} maxLength={400} value={text} onChange={(e) => (setEdited(true), setF({ ...f, body: e.target.value }))} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Preview</button>
        </div>
      </form>
    </Dialog>
  );
}

function Revoke({ cert, onClose, onDone }: { cert: Certificate; onClose: () => void; onDone: (c: Certificate) => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({ mutationFn: () => post<Certificate>(`/api/certificates/${cert.id}/revoke`, { reason: reason.trim() }), onSuccess: onDone, onError: setError });
  return (
    <Dialog title={`Revoke ${cert.number}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (reason.trim().length < 3) return setError("Give the reason.");
          save.mutate();
        }}
        noValidate
        style={{ display: "grid", gap: 14 }}
      >
        <p className="row-sub">The certificate stays on record; its verification page will say it was revoked and when.</p>
        <Field id="r-reason" label="Reason">
          <input id="r-reason" className="input" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Revoke certificate
          </button>
        </div>
      </form>
    </Dialog>
  );
}
