import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSignature, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, apiBlob, post } from "../../api/client";
import type { Client, Proposal, ProposalService, ProposalStatus } from "../../api/types";
import { usePreview } from "../../components/DocumentPreview";
import { Dialog, Done, EmptyRow, ErrorNote, Field, FormError, LoadingRow, PageHead, RowButton, Tabs } from "../../components/ui";
import { centsToInput, fullDay, rands, shortDay } from "../../lib/format";
import { LineEditor, parseLines, type LineDraft } from "./Finance";
import "../overview.css";
import "../pages.css";

const STATUS: Record<ProposalStatus, { label: string; chip: string }> = {
  draft: { label: "Draft", chip: "chip-neutral" },
  issued: { label: "Issued", chip: "chip-brand" },
  accepted: { label: "Accepted", chip: "chip-success" },
  declined: { label: "Declined", chip: "chip-neutral" },
  expired: { label: "Expired", chip: "chip-warning" },
};

type Filter = "all" | ProposalStatus;
type Preset = { key: ProposalService; label: string };

const TEXT_FIELDS = [
  ["introduction", "Introduction"],
  ["need", "The client's need"],
  ["solution", "Our solution"],
  ["scope", "Scope of work (one item per line)"],
  ["timeline", "Timeline"],
  ["why_us", "Why SaxsProjects"],
] as const;

export function Proposals() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["proposals"], queryFn: () => api<Proposal[]>("/api/proposals") });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Client[]>("/api/clients") });
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"new" | "edit" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const preview = usePreview();
  const refresh = () => qc.invalidateQueries({ queryKey: ["proposals"] });

  const act = useMutation({
    mutationFn: ({ p, step }: { p: Proposal; step: "accept" | "decline" | "quotation" }) => post<Proposal>(`/api/proposals/${p.id}/${step}`),
    onSuccess: (p, { step }) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["quotations"] });
      setDone(
        step === "quotation"
          ? `Draft quotation created from ${p.number}. Issue it from Client finance.`
          : `${p.number} marked as ${step === "accept" ? "accepted" : "declined"}.`,
      );
    },
  });
  const remove = useMutation({
    mutationFn: (p: Proposal) => api(`/api/proposals/${p.id}`, { method: "DELETE" }),
    onSuccess: () => (refresh(), setSelectedId(null), setDone("Draft deleted.")),
  });

  if (list.isError) return <ErrorNote error={list.error} onRetry={() => list.refetch()} />;
  const rows = list.data ?? [];
  const shown = rows.filter((p) => filter === "all" || p.status === filter);
  const selected = rows.find((p) => p.id === selectedId) ?? shown[0];
  const clientName = (id: number) => clients.data?.find((c) => c.id === id)?.name ?? "Client";

  function show(p: Proposal) {
    setDone(null);
    preview({
      title: p.number ? `Proposal ${p.number}` : `Draft proposal: ${p.title}`,
      filename: `${p.number ?? "proposal-draft"}.pdf`,
      note: p.status === "draft" ? "Issuing numbers it (SP-PRO), signs it and stores it unchanged." : undefined,
      load: () => apiBlob(`/api/proposals/${p.id}/pdf`),
      confirm:
        p.status === "draft"
          ? {
              label: "Issue proposal",
              run: () => post<Proposal>(`/api/proposals/${p.id}/issue`).then((x) => (refresh(), setDone(`Proposal ${x.number} issued.`))),
            }
          : undefined,
    });
  }

  return (
    <div className="page">
      <PageHead title="Proposals" sub="The hub writes the first draft from a service; you set the prices and issue it. Accepted proposals become quotations.">
        <button className="btn btn-primary" onClick={() => (setDone(null), setDialog("new"))}>
          <Sparkles size={16} aria-hidden="true" /> New proposal
        </button>
      </PageHead>
      <Done text={done} />
      <div className="toolbar">
        <Tabs<Filter>
          label="Filter proposals"
          value={filter}
          onChange={(f) => (setFilter(f), setSelectedId(null))}
          tabs={[
            { key: "all", label: "All", count: rows.length },
            ...(Object.keys(STATUS) as ProposalStatus[])
              .filter((k) => rows.some((p) => p.status === k))
              .map((k) => ({ key: k as Filter, label: STATUS[k].label, count: rows.filter((p) => p.status === k).length })),
          ]}
        />
      </div>
      <div className="split">
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Proposal</th>
                  <th className="hide-sm">Client</th>
                  <th>Total</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {list.isPending && <LoadingRow cols={4} />}
                {list.data && shown.length === 0 && <EmptyRow cols={4} text="No proposals yet. Choose a client and a service, and the hub writes the first draft." />}
                {shown.map((p) => (
                  <RowButton key={p.id} selected={p.id === selected?.id} onSelect={() => setSelectedId(p.id)}>
                    <td>
                      <p className="row-title">{p.title}</p>
                      <p className="row-sub num">{p.number ?? "Draft"}</p>
                    </td>
                    <td className="hide-sm muted">{clientName(p.client_id)}</td>
                    <td className="num cell-main">{rands(p.total_cents)}</td>
                    <td>
                      <span className={`chip ${STATUS[p.status].chip}`}>{STATUS[p.status].label}</span>
                    </td>
                  </RowButton>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {selected && (
          <section className="card detail" aria-label="Proposal details">
            <span className="detail-icon" aria-hidden="true">
              <FileSignature size={20} />
            </span>
            <h3 className="detail-title" style={{ marginTop: 18 }}>
              {selected.title}
            </h3>
            <p className="detail-ref num">
              {selected.number ?? "Draft"} · {clientName(selected.client_id)}
            </p>
            <hr className="divider" />
            <dl className="kv">
              <div>
                <dt>Amount excl. VAT</dt>
                <dd className="num">{rands(selected.subtotal_cents)}</dd>
              </div>
              <div>
                <dt>{selected.vat_rate_bp ? "VAT" : "VAT (not registered)"}</dt>
                <dd className="num">{rands(selected.vat_cents)}</dd>
              </div>
              <div>
                <dt>Amount incl. VAT</dt>
                <dd className="num">{rands(selected.total_cents)}</dd>
              </div>
              {selected.issue_date && (
                <div>
                  <dt>Issued</dt>
                  <dd>
                    {fullDay(selected.issue_date)}
                    {selected.valid_until ? ` · valid until ${shortDay(selected.valid_until)}` : ""}
                  </dd>
                </div>
              )}
            </dl>
            {selected.status === "draft" && selected.subtotal_cents === 0 && <p className="row-sub warning-text">Set the prices before issuing (lines start at R0.00).</p>}
            <div className="form-row" style={{ gap: 10, marginTop: 14, flexWrap: "wrap" }}>
              <button className="btn btn-primary" onClick={() => show(selected)}>
                {selected.status === "draft" ? "Preview & issue" : "View PDF"}
              </button>
              {selected.status === "draft" && (
                <>
                  <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("edit"))}>
                    Edit
                  </button>
                  <button className="btn btn-secondary" disabled={remove.isPending} onClick={() => remove.mutate(selected)}>
                    Delete draft
                  </button>
                </>
              )}
              {selected.status === "issued" && (
                <>
                  <button className="btn btn-secondary" disabled={act.isPending} onClick={() => act.mutate({ p: selected, step: "accept" })}>
                    Client accepted
                  </button>
                  <button className="btn btn-secondary" disabled={act.isPending} onClick={() => act.mutate({ p: selected, step: "decline" })}>
                    Client declined
                  </button>
                </>
              )}
              {(selected.status === "issued" || selected.status === "accepted") && !selected.quotation_id && (
                <button className="btn btn-secondary" disabled={act.isPending} onClick={() => act.mutate({ p: selected, step: "quotation" })}>
                  Make quotation
                </button>
              )}
              {selected.quotation_id && (
                <Link className="btn btn-secondary" to={`/finance/quotations?open=${selected.quotation_id}`}>
                  Open quotation
                </Link>
              )}
            </div>
            <FormError error={act.error ?? remove.error} />
          </section>
        )}
      </div>

      {dialog === "new" && (
        <NewProposal clients={clients.data ?? []} onClose={() => setDialog(null)} onSaved={(p) => (refresh(), setSelectedId(p.id), setDialog("edit"), setDone("First draft written. Check the text and set the prices."))} />
      )}
      {dialog === "edit" && selected && <EditProposal proposal={selected} onClose={() => setDialog(null)} onSaved={() => (refresh(), setDialog(null), setDone("Proposal saved."))} />}
    </div>
  );
}

function NewProposal({ clients, onClose, onSaved }: { clients: Client[]; onClose: () => void; onSaved: (p: Proposal) => void }) {
  const presets = useQuery({ queryKey: ["proposal-presets"], queryFn: () => api<Preset[]>("/api/proposals/presets") });
  const [f, setF] = useState({ client_id: "", service: "website" as ProposalService, need: "" });
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () => post<Proposal>("/api/proposals/generate", { client_id: Number(f.client_id), service: f.service, need: f.need.trim() || null }),
    onSuccess: onSaved,
    onError: setError,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.client_id) return setError("Choose the client.");
    setError(null);
    save.mutate();
  }
  return (
    <Dialog title="New proposal" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="p-client" label="Client" hint={clients.length ? undefined : "Add the client in Client finance first."}>
            <select id="p-client" className="input" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })} autoFocus>
              <option value="">Choose a client</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field id="p-service" label="Service">
            <select id="p-service" className="input" value={f.service} onChange={(e) => setF({ ...f, service: e.target.value as ProposalService })}>
              {(presets.data ?? [{ key: "website", label: "Business website" }]).map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field id="p-need" label="What the client told you they need (optional)" hint="Used as the 'need' section; otherwise the service's standard wording is used.">
          <textarea id="p-need" className="input textarea" maxLength={4000} value={f.need} onChange={(e) => setF({ ...f, need: e.target.value })} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Write first draft
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function EditProposal({ proposal, onClose, onSaved }: { proposal: Proposal; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(proposal.title);
  const [text, setText] = useState(() => Object.fromEntries(TEXT_FIELDS.map(([k]) => [k, proposal[k] ?? ""])) as Record<(typeof TEXT_FIELDS)[number][0], string>);
  const [lines, setLines] = useState<LineDraft[]>(() =>
    proposal.items.length
      ? proposal.items.map((i) => ({ description: i.description, quantity: String(i.quantity), price: i.unit_price_cents ? centsToInput(i.unit_price_cents) : "" }))
      : [{ description: "", quantity: "1", price: "" }],
  );
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (body: object) => api<Proposal>(`/api/proposals/${proposal.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: onSaved,
    onError: setError,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length < 2) return setError("Give the proposal a title.");
    const items = parseLines(lines);
    if (typeof items === "string") return setError(items);
    setError(null);
    save.mutate({ title: title.trim(), ...Object.fromEntries(Object.entries(text).map(([k, v]) => [k, v.trim() || null])), items });
  }
  return (
    <Dialog title="Edit proposal" onClose={onClose} className="dialog-wide">
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="pe-title" label="Title">
          <input id="pe-title" className="input" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        {TEXT_FIELDS.map(([key, label]) => (
          <Field key={key} id={`pe-${key}`} label={label}>
            <textarea id={`pe-${key}`} className="input textarea" rows={key === "scope" ? 6 : 3} maxLength={8000} value={text[key]} onChange={(e) => setText({ ...text, [key]: e.target.value })} />
          </Field>
        ))}
        <LineEditor lines={lines} onChange={setLines} />
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Save draft
          </button>
        </div>
      </form>
    </Dialog>
  );
}
