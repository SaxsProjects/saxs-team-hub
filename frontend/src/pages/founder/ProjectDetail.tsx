import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, downloadFile, post } from "../../api/client";
import type { Invoice, Payout, Project, ProjectDetail as Detail, Quotation } from "../../api/types";
import { Dialog, Done, EmptyRow, ErrorNote, Field, FormError, PageHead, Skeleton, StatCard } from "../../components/ui";
import { fullDay, parseRands, percent, plural, rands, shortDay, todaySA } from "../../lib/format";
import { WORKING_STAGES, usePeople } from "../../lib/people";
import { projectRef } from "../member/MyProjects";
import { PROJECT_STATUS } from "./Projects";
import "../overview.css";
import "../pages.css";

export function ProjectDetail() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api<Detail>(`/api/projects/${id}`) });
  const payouts = useQuery({ queryKey: ["payouts"], queryFn: () => api<Payout[]>("/api/payouts") });
  const quotations = useQuery({ queryKey: ["quotations"], queryFn: () => api<Quotation[]>("/api/quotations") });
  const invoices = useQuery({ queryKey: ["invoices"], queryFn: () => api<Invoice[]>("/api/invoices") });
  const people = usePeople();
  const [dialog, setDialog] = useState<null | "edit" | "contributor" | "cost">(null);
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState<unknown>(null);

  const refresh = () => {
    for (const k of [["project", id], ["projects"], ["payouts"], ["dashboard"]]) qc.invalidateQueries({ queryKey: k });
  };
  const lock = useMutation({ mutationFn: () => post(`/api/projects/${id}/lock`), onSuccess: () => (refresh(), setDone("Work shares locked.")), onError: setFailed });
  const remove = useMutation({
    mutationFn: (personId: number) => api(`/api/projects/${id}/contributors/${personId}`, { method: "DELETE" }),
    onSuccess: () => (refresh(), setDone("Contributor removed.")),
    onError: setFailed,
  });

  if (project.isError) return <ErrorNote error={project.error} onRetry={() => project.refetch()} />;
  const p = project.data;
  if (!p)
    return (
      <div className="page">
        <Skeleton h={40} w={300} />
        <Skeleton h={120} />
      </div>
    );

  const mine = (payouts.data ?? []).filter((x) => x.project_id === id && x.kind === "revenue_share");
  const payoutTotal = mine.reduce((s, x) => s + x.amount_cents, 0);
  const lockedAt = p.contributors.map((c) => c.locked_at).find(Boolean);
  const allLocked = p.contributors.length > 0 && p.contributors.every((c) => c.locked_at);
  const shareTotal = p.contributors.reduce((s, c) => s + c.work_share_bp, 0);
  const lastPayment = [...p.payments].sort((a, b) => b.received_at.localeCompare(a.received_at))[0];
  const docs = [
    ...(quotations.data ?? []).filter((q) => q.project_id === id && q.number).map((q) => ({ key: `q${q.id}`, title: "Quotation", sub: `${q.number} · ${q.status === "accepted" ? "Accepted" : q.status === "issued" ? "Issued" : q.status}`, path: `/api/quotations/${q.id}/pdf`, file: `${q.number}.pdf` })),
    ...(invoices.data ?? []).filter((i) => i.project_id === id && i.number).map((i) => ({ key: `i${i.id}`, title: "Invoice", sub: `${i.number} · ${i.status === "paid" ? "Paid" : i.status === "part_paid" ? "Part paid" : "Issued"}`, path: `/api/invoices/${i.id}/pdf`, file: `${i.number}.pdf` })),
  ];

  return (
    <div className="page">
      <PageHead title={p.name} sub={`${projectRef(p.id)} · ${p.client_name}`}>
        <span className={`chip ${PROJECT_STATUS[p.status].cls}`}>{PROJECT_STATUS[p.status].label}</span>
        <button className="btn btn-secondary" onClick={() => setDialog("edit")}>
          Edit project
        </button>
      </PageHead>
      <p className="page-sub" style={{ marginTop: -12 }}>
        <Link to="/projects">← All projects</Link>
      </p>
      {!!failed && <ErrorNote error={failed} />}
      <Done text={done} />

      <div className="stats-4 caps-stats">
        <StatCard label="Client money received" value={rands(p.received_cents)} />
        <StatCard label="Direct costs" value={rands(p.costs_cents)} />
        <StatCard label="Net project income" value={rands(p.net_income_cents)} />
        <StatCard label="Contributor payouts" value={payouts.data ? rands(payoutTotal) : <Skeleton w={120} h={30} />} />
      </div>

      <div className="split">
        <div className="stack">
          <section className="card">
            <div className="card-head">
              <div>
                <h3 className="card-title">Contributors</h3>
                <p className="card-sub">{lockedAt ? `Locked ${fullDay(lockedAt)}` : `Work shares add up to ${percent(shareTotal)}`}</p>
              </div>
              <div className="toolbar" style={{ gap: 10 }}>
                {allLocked ? (
                  <span className="chip chip-success">Shares locked</span>
                ) : (
                  <>
                    <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("contributor"))}>
                      Add contributor
                    </button>
                    {p.contributors.length > 0 && (
                      <button className="btn btn-secondary" disabled={lock.isPending} onClick={() => (setDone(null), setFailed(null), lock.mutate())}>
                        Lock shares
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Contributor</th>
                    <th>Work share</th>
                    <th className="hide-sm">Payment rate</th>
                    <th>Payout</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {p.contributors.length === 0 && <EmptyRow cols={5} text="No contributors yet. Add the people on this project and their agreed work shares." />}
                  {p.contributors.map((c) => (
                    <tr key={c.id}>
                      <td className="row-title">
                        <Link className="row-link" to={`/team/${c.person_id}`}>
                          {people.nameOf(c.person_id)}
                        </Link>
                      </td>
                      <td className="num">{percent(c.work_share_bp)}</td>
                      <td className="num hide-sm">{percent(c.rate_bp)}</td>
                      <td className="num cell-main">{rands(mine.filter((x) => x.person_id === c.person_id).reduce((s, x) => s + x.amount_cents, 0))}</td>
                      <td className="right">
                        {!c.locked_at && (
                          <button className="icon-btn danger" aria-label={`Remove ${people.nameOf(c.person_id)}`} onClick={() => (setDone(null), setFailed(null), remove.mutate(c.person_id))}>
                            <Trash2 size={15} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {lastPayment && <p className="foot-note">Rates shown are each person’s rate when they joined the project; each payment uses the rate on its date.</p>}
          </section>

          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Client payments</h3>
              <span className="th-note">{plural(p.payments.length, "payment")}</span>
            </div>
            {p.payments.length === 0 && <p className="empty">No client payments recorded yet.</p>}
            {[...p.payments]
              .sort((a, b) => b.received_at.localeCompare(a.received_at))
              .map((x) => (
                <div key={x.id} className="pay-row">
                  <div>
                    <p className="row-title">{shortDay(x.received_at)}</p>
                  </div>
                  <div>
                    <p className="momentum-value num" style={{ fontSize: 20 }}>
                      {rands(x.amount_cents)}
                    </p>
                    <p className="row-sub">Reference: {x.reference}</p>
                  </div>
                  <span className="chip chip-success">Received</span>
                </div>
              ))}
          </section>

          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Direct costs</h3>
              <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("cost"))}>
                Add cost
              </button>
            </div>
            {p.costs.length === 0 ? (
              <div className="pay-row" style={{ gridTemplateColumns: "1fr auto" }}>
                <div>
                  <p className="row-title">No direct costs recorded</p>
                  <p className="row-sub">Costs reduce the net income that shares are paid from.</p>
                </div>
                <strong className="num">{rands(0)}</strong>
              </div>
            ) : (
              <ul className="doc-list">
                {p.costs.map((c) => (
                  <li key={c.id}>
                    <div className="doc-text">
                      <p className="row-title">{c.description}</p>
                      <p className="row-sub">{shortDay(c.incurred_at)}</p>
                    </div>
                    <strong className="num">{rands(c.amount_cents)}</strong>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className="stack">
          <RecordPayment projectId={id} canRecord={p.contributors.length > 0} onDone={(msg) => (refresh(), setDone(msg))} />
          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Project documents</h3>
            </div>
            <ul className="doc-list">
              {docs.length === 0 && <li className="empty" style={{ display: "block" }}>Quotations and invoices for this project will appear here.</li>}
              {docs.map((d) => (
                <li key={d.key} style={{ alignItems: "center" }}>
                  <FileText size={18} className="doc-icon" aria-hidden="true" />
                  <div className="doc-text">
                    <p className="row-title">{d.title}</p>
                    <p className="row-sub num">{d.sub}</p>
                  </div>
                  <button className="icon-btn" aria-label={`Download ${d.title.toLowerCase()} ${d.file}`} onClick={() => downloadFile(d.path, d.file).catch(setFailed)}>
                    <Download size={16} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>

      {dialog === "edit" && <EditProject project={p} onClose={() => setDialog(null)} onSaved={() => (refresh(), setDialog(null), setDone("Project updated."))} />}
      {dialog === "contributor" && (
        <AddContributor
          projectId={id}
          taken={new Set(p.contributors.map((c) => c.person_id))}
          remaining={10_000 - shareTotal}
          people={(people.data ?? []).filter((x) => WORKING_STAGES.has(x.status))}
          onClose={() => setDialog(null)}
          onSaved={() => (refresh(), setDialog(null), setDone("Contributor added."))}
        />
      )}
      {dialog === "cost" && <AddCost projectId={id} onClose={() => setDialog(null)} onSaved={() => (refresh(), setDialog(null), setDone("Cost recorded."))} />}
    </div>
  );
}

function RecordPayment({ projectId, canRecord, onDone }: { projectId: number; canRecord: boolean; onDone: (msg: string) => void }) {
  const [f, setF] = useState({ amount: "", received_at: todaySA(), reference: "" });
  const [error, setError] = useState<unknown>(null);
  const record = useMutation({
    mutationFn: (amount: number) =>
      post<{ payouts: Payout[] }>(`/api/projects/${projectId}/payments`, { amount_cents: amount, received_at: f.received_at, reference: f.reference.trim() }),
    onSuccess: (r) => {
      setF({ amount: "", received_at: todaySA(), reference: "" });
      onDone(`Payment recorded. ${plural(r.payouts.length, "contributor payout")} calculated.`);
    },
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const amount = parseRands(f.amount);
    if (!amount) return setError("Enter the amount received, for example 18 000.");
    if (!f.received_at || f.received_at > todaySA()) return setError("The date can’t be in the future.");
    if (!f.reference.trim()) return setError("Add the payment reference.");
    setError(null);
    record.mutate(amount);
  }

  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Record client payment</h3>
      </div>
      <hr className="divider" />
      <form className="form-card" style={{ paddingTop: 16 }} onSubmit={submit} noValidate>
        <Field id="pay-amount" label="Amount received (R)">
          <input id="pay-amount" className="input" inputMode="decimal" placeholder="18 000.00" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
        </Field>
        <Field id="pay-date" label="Received on">
          <input id="pay-date" className="input" type="date" max={todaySA()} value={f.received_at} onChange={(e) => setF({ ...f, received_at: e.target.value })} />
        </Field>
        <Field id="pay-ref" label="Payment reference">
          <input id="pay-ref" className="input" maxLength={120} value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} />
        </Field>
        <FormError error={error ?? (!canRecord ? "Add contributors with agreed work shares before recording a payment." : null)} />
        <button className="btn btn-primary btn-block" disabled={record.isPending || !canRecord}>
          {record.isPending ? "Recording…" : "Record payment"}
        </button>
      </form>
    </section>
  );
}

function EditProject({ project, onClose, onSaved }: { project: Project; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: project.name, client_name: project.client_name, description: project.description ?? "", status: project.status });
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () => api(`/api/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ ...f, description: f.description.trim() || null }) }),
    onSuccess: onSaved,
    onError: setError,
  });
  return (
    <Dialog title="Edit project" onClose={onClose}>
      <form onSubmit={(e) => (e.preventDefault(), save.mutate())} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="e-name" label="Project name">
          <input id="e-name" className="input" value={f.name} maxLength={200} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field id="e-client" label="Client">
          <input id="e-client" className="input" value={f.client_name} maxLength={200} onChange={(e) => setF({ ...f, client_name: e.target.value })} />
        </Field>
        <Field id="e-status" label="Status">
          <select id="e-status" className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as Project["status"] })}>
            {Object.entries(PROJECT_STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id="e-desc" label="Description">
          <textarea id="e-desc" className="input textarea" value={f.description} maxLength={5000} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Save project
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AddContributor({ projectId, taken, remaining, people, onClose, onSaved }: { projectId: number; taken: Set<number>; remaining: number; people: { id: number; full_name: string }[]; onClose: () => void; onSaved: () => void }) {
  const [personId, setPersonId] = useState("");
  const [share, setShare] = useState(remaining > 0 ? String(remaining / 100) : "");
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (bp: number) => api(`/api/projects/${projectId}/contributors`, { method: "PUT", body: JSON.stringify({ person_id: Number(personId), work_share_bp: bp }) }),
    onSuccess: onSaved,
    onError: setError,
  });
  const choices = people.filter((x) => !taken.has(x.id));

  function submit(e: FormEvent) {
    e.preventDefault();
    const pct = Number(share.replace(",", ".").replace("%", ""));
    if (!personId) return setError("Choose a person.");
    if (!(pct > 0 && pct <= 100)) return setError("Enter a work share between 1 and 100%.");
    const bp = Math.round(pct * 100);
    if (bp > remaining) return setError(`Only ${percent(remaining)} of the work is left to share.`);
    setError(null);
    save.mutate(bp);
  }

  return (
    <Dialog title="Add contributor" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="c-person" label="Person" hint={choices.length === 0 ? "Everyone who accepted an offer is already on this project." : undefined}>
          <select id="c-person" className="input" value={personId} onChange={(e) => setPersonId(e.target.value)}>
            <option value="">Choose a person</option>
            {choices.map((x) => (
              <option key={x.id} value={x.id}>
                {x.full_name}
              </option>
            ))}
          </select>
        </Field>
        <Field id="c-share" label="Agreed work share (%)" hint={`${percent(remaining)} still to share. Shares are locked once work begins.`}>
          <input id="c-share" className="input" inputMode="decimal" value={share} onChange={(e) => setShare(e.target.value)} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Add contributor
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AddCost({ projectId, onClose, onSaved }: { projectId: number; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ description: "", amount: "", incurred_at: todaySA() });
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (amount: number) => post(`/api/projects/${projectId}/costs`, { description: f.description.trim(), amount_cents: amount, incurred_at: f.incurred_at }),
    onSuccess: onSaved,
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const amount = parseRands(f.amount);
    if (f.description.trim().length < 2) return setError("Describe the cost.");
    if (!amount) return setError("Enter the amount in rand.");
    if (!f.incurred_at) return setError("Choose the date.");
    setError(null);
    save.mutate(amount);
  }

  return (
    <Dialog title="Add direct cost" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="k-desc" label="Description">
          <input id="k-desc" className="input" maxLength={255} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="k-amount" label="Amount (R)">
            <input id="k-amount" className="input" inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
          </Field>
          <Field id="k-date" label="Date">
            <input id="k-date" className="input" type="date" value={f.incurred_at} onChange={(e) => setF({ ...f, incurred_at: e.target.value })} />
          </Field>
        </div>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Add cost
          </button>
        </div>
      </form>
    </Dialog>
  );
}
