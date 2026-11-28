import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, apiBlob, post } from "../../api/client";
import type { Client, ClientKind, CreditNote, FinanceReadiness, Invoice, LineInput, Project, Quotation, Receipt, StatementResult } from "../../api/types";
import { usePreview } from "../../components/DocumentPreview";
import { Dialog, Done, EmptyRow, ErrorNote, Field, FormError, LoadingRow, PageHead, Pager, RowButton, Skeleton, StatCard, Tabs, paginate, useSelectedFromUrl } from "../../components/ui";
import { fullDay, parseRands, plural, rands, shortDay, todaySA } from "../../lib/format";
import { projectRef } from "../member/MyProjects";
import "../overview.css";
import "../pages.css";

export const CLIENT_KINDS: { key: ClientKind; label: string }[] = [
  { key: "company", label: "Company (Pty) Ltd / CC" },
  { key: "sole_proprietor", label: "Sole proprietor" },
  { key: "individual", label: "Individual" },
  { key: "npo", label: "NPO / NGO / school" },
  { key: "government", label: "Government / municipality" },
  { key: "other", label: "Other" },
];

type Tab = "clients" | "quotations" | "invoices" | "receipts" | "credit-notes";
const TABS: { key: Tab; label: string }[] = [
  { key: "clients", label: "Clients" },
  { key: "quotations", label: "Quotations" },
  { key: "invoices", label: "Invoices" },
  { key: "receipts", label: "Receipts" },
  { key: "credit-notes", label: "Credit notes" },
];

const Q_STATUS: Record<Quotation["status"], { label: string; cls: string }> = {
  draft: { label: "Draft", cls: "muted" },
  issued: { label: "Issued", cls: "brand-text" },
  accepted: { label: "Accepted", cls: "success-text" },
  declined: { label: "Declined", cls: "muted" },
  expired: { label: "Expired", cls: "warning-text" },
};

function invoiceState(i: Invoice, today: string): { label: string; cls: string; chip: string } {
  if (i.status === "paid") return { label: "Paid", cls: "success-text", chip: "chip-success" };
  if (i.status === "void") return { label: "Void", cls: "muted", chip: "chip-neutral" };
  if (i.status === "draft") return { label: "Draft", cls: "muted", chip: "chip-neutral" };
  if (i.overdue || (i.due_date && i.due_date < today)) return { label: "Overdue", cls: "warning-text", chip: "chip-warning" };
  return i.status === "part_paid" ? { label: "Part paid", cls: "brand-text", chip: "chip-brand" } : { label: "Issued", cls: "brand-text", chip: "chip-brand" };
}

const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T12:00:00Z`) - Date.parse(`${a}T12:00:00Z`)) / 86_400_000);
const yearOf = (d: string) => d.slice(0, 4);

/** Shared data for every finance tab. */
function useFinance() {
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Client[]>("/api/clients") });
  const quotations = useQuery({ queryKey: ["quotations"], queryFn: () => api<Quotation[]>("/api/quotations") });
  const invoices = useQuery({ queryKey: ["invoices"], queryFn: () => api<Invoice[]>("/api/invoices") });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/api/projects") });
  const issued = (invoices.data ?? []).filter((i) => i.number);
  const receipts = useQueries({
    queries: issued.map((i) => ({ queryKey: ["invoice", i.id, "receipts"], queryFn: () => api<Receipt[]>(`/api/invoices/${i.id}/receipts`) })),
  });
  const credits = useQueries({
    queries: issued.map((i) => ({ queryKey: ["invoice", i.id, "credit-notes"], queryFn: () => api<CreditNote[]>(`/api/invoices/${i.id}/credit-notes`) })),
  });
  const clientName = (id: number) => (clients.data ?? []).find((c) => c.id === id)?.name ?? "Client";
  const project = (id: number | null) => (projects.data ?? []).find((p) => p.id === id);
  return {
    clients,
    quotations,
    invoices,
    projects,
    receipts: receipts.flatMap((r) => r.data ?? []),
    receiptsLoading: receipts.some((r) => r.isPending),
    credits: credits.flatMap((r) => r.data ?? []),
    creditsLoading: credits.some((r) => r.isPending),
    clientName,
    project,
  };
}
type FinanceData = ReturnType<typeof useFinance>;

export function Finance() {
  const tab = (useParams().tab ?? "clients") as Tab;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const data = useFinance();
  const readiness = useQuery({ queryKey: ["finance", "readiness"], queryFn: () => api<FinanceReadiness>("/api/finance/readiness") });
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState<unknown>(null);
  const [dialog, setDialog] = useState<null | { kind: "client"; client?: Client } | { kind: "quotation"; clientId?: number } | { kind: "invoice"; quotation?: Quotation }>(null);

  const current = TABS.find((t) => t.key === tab) ?? TABS[0]!;
  const refresh = (msg?: string) => {
    for (const k of ["clients", "quotations", "invoices", "finance", "invoice", "projects", "project", "payouts", "dashboard"]) qc.invalidateQueries({ queryKey: [k] });
    if (msg) setDone(msg);
  };
  const ctx: Ctx = {
    data,
    today: todaySA(),
    readiness: readiness.data,
    onDone: (m) => (setFailed(null), refresh(m)),
    onFailed: (e) => (setDone(null), setFailed(e)),
    openClient: (client) => (setDone(null), setDialog({ kind: "client", client })),
    newQuotation: (clientId) => (setDone(null), setDialog({ kind: "quotation", clientId })),
    newInvoice: (quotation) => (setDone(null), setDialog({ kind: "invoice", quotation })),
  };

  const heads: Record<Tab, { title: string; sub: string; action?: ReactNode }> = {
    clients: { title: "Clients", sub: "Contacts, projects and balances.", action: <button className="btn btn-primary" onClick={() => ctx.openClient()}>Add client</button> },
    quotations: { title: "Quotations", sub: "Proposals from first draft to acceptance.", action: <button className="btn btn-primary" onClick={() => ctx.newQuotation()}>New quotation</button> },
    invoices: { title: "Invoices", sub: "Track balances and record client payments.", action: <button className="btn btn-primary" onClick={() => ctx.newInvoice()}>Create invoice</button> },
    receipts: { title: "Receipts", sub: "Signed receipts for every payment received." },
    "credit-notes": { title: "Credit notes", sub: "Reductions issued against invoices." },
  };
  const head = heads[current.key];

  return (
    <div className="page">
      <PageHead title={head.title} sub={head.sub}>
        {head.action}
      </PageHead>
      <Tabs<Tab> label="Client finance" value={current.key} onChange={(t) => (setDone(null), setFailed(null), navigate(`/finance/${t}`))} tabs={TABS} />
      {readiness.data && readiness.data.missing.length > 0 && (current.key === "quotations" || current.key === "invoices") && (
        <div className="banner warning">
          <div>
            <p className="banner-title">Finish company details before issuing documents</p>
            <p className="banner-sub">
              Missing: {readiness.data.missing.join(", ")}. <Link to="/settings">Open settings</Link>
            </p>
          </div>
        </div>
      )}
      {!!failed && <ErrorNote error={failed} />}
      <Done text={done} />

      {current.key === "clients" && <ClientsTab ctx={ctx} />}
      {current.key === "quotations" && <QuotationsTab ctx={ctx} />}
      {current.key === "invoices" && <InvoicesTab ctx={ctx} />}
      {current.key === "receipts" && <ReceiptsTab ctx={ctx} />}
      {current.key === "credit-notes" && <CreditNotesTab ctx={ctx} />}

      {dialog?.kind === "client" && <ClientDialog client={dialog.client} onClose={() => setDialog(null)} onSaved={(c) => (setDialog(null), ctx.onDone(`${c.name} saved.`))} />}
      {dialog?.kind === "quotation" && (
        <QuotationDialog data={data} clientId={dialog.clientId} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), ctx.onDone("Quotation saved as a draft."), navigate("/finance/quotations"))} />
      )}
      {dialog?.kind === "invoice" && (
        <InvoiceDialog data={data} quotation={dialog.quotation} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), ctx.onDone("Invoice saved as a draft."), navigate("/finance/invoices"))} />
      )}
    </div>
  );
}

interface Ctx {
  data: FinanceData;
  today: string;
  readiness?: FinanceReadiness;
  onDone: (msg: string) => void;
  onFailed: (e: unknown) => void;
  openClient: (c?: Client) => void;
  newQuotation: (clientId?: number) => void;
  newInvoice: (q?: Quotation) => void;
}

/** Search box + status filter above each register, as in the design. */
function ListTools({ search, onSearch, placeholder, status, onStatus, options }: { search: string; onSearch: (s: string) => void; placeholder: string; status: string; onStatus: (s: string) => void; options: [string, string][] }) {
  return (
    <div className="list-tools">
      <input className="input" type="search" placeholder={placeholder} aria-label={placeholder} value={search} onChange={(e) => onSearch(e.target.value)} />
      <select className="input" aria-label="Status" value={status} onChange={(e) => onStatus(e.target.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </div>
  );
}

function useList<T extends { id: number }>(items: T[], match: (t: T, q: string, status: string) => boolean) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useSelectedFromUrl();
  const q = search.trim().toLowerCase();
  const filtered = items.filter((t) => match(t, q, status));
  const view = paginate(filtered, page);
  const selected = items.find((t) => t.id === selectedId) ?? view.rows[0];
  return {
    search,
    status,
    filtered,
    view,
    selected,
    setPage,
    select: setSelectedId,
    onSearch: (s: string) => (setSearch(s), setPage(0), setSelectedId(null)),
    onStatus: (s: string) => (setStatus(s), setPage(0), setSelectedId(null)),
  };
}

/* ---------------- Clients ---------------- */

function ClientsTab({ ctx }: { ctx: Ctx }) {
  const { data } = ctx;
  const year = yearOf(ctx.today);
  const open = (data.invoices.data ?? []).filter((i) => i.status === "issued" || i.status === "part_paid");
  const balance = (id: number) => open.filter((i) => i.client_id === id).reduce((s, i) => s + i.balance_cents, 0);
  const projectsOf = (c: Client) => (data.projects.data ?? []).filter((p) => p.client_name.trim().toLowerCase() === c.name.trim().toLowerCase());
  const active = (c: Client) => projectsOf(c).some((p) => p.status === "planned" || p.status === "in_progress");
  const list = useList([...(data.clients.data ?? [])].sort((a, b) => a.name.localeCompare(b.name)), (c, q, s) => {
    if (s === "active" && !active(c)) return false;
    if (s === "balance" && balance(c.id) <= 0) return false;
    return !q || `${c.name} ${c.contact_name ?? ""} ${c.email ?? ""}`.toLowerCase().includes(q);
  });
  const receivedYear = data.receipts.filter((r) => yearOf(r.received_on) === year).reduce((s, r) => s + r.amount_cents, 0);
  const c = list.selected;

  if (data.clients.isError) return <ErrorNote error={data.clients.error} onRetry={() => data.clients.refetch()} />;
  return (
    <>
      <div className="stats-3">
        <StatCard label="Clients" value={data.clients.data ? data.clients.data.length : <Skeleton w={40} h={30} />} note={`${(data.clients.data ?? []).filter(active).length} with active projects`} />
        <StatCard label="Money received" value={data.receiptsLoading ? <Skeleton w={140} h={30} /> : rands(receivedYear)} note="Year to date" />
        <StatCard label="Outstanding" value={data.invoices.data ? rands(open.reduce((s, i) => s + i.balance_cents, 0)) : <Skeleton w={140} h={30} />} note={`Across ${plural(open.length, "invoice")}`} />
      </div>
      <div className="split">
        <div className="stack">
          <ListTools search={list.search} onSearch={list.onSearch} placeholder="Search clients or contacts" status={list.status} onStatus={list.onStatus} options={[["", "All clients"], ["active", "Active projects"], ["balance", "With a balance"]]} />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th className="hide-sm">Contact</th>
                    <th className="hide-sm">Projects</th>
                    <th>Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {data.clients.isPending && <LoadingRow cols={4} />}
                  {data.clients.data && list.filtered.length === 0 && <EmptyRow cols={4} text={data.clients.data.length ? "No clients match." : "No clients yet. Add your first client."} />}
                  {list.view.rows.map((x) => (
                    <RowButton key={x.id} selected={x.id === c?.id} onSelect={() => list.select(x.id)}>
                      <td className="row-title">{x.name}</td>
                      <td className="hide-sm muted">{x.contact_name ?? "—"}</td>
                      <td className="hide-sm num">{projectsOf(x).length}</td>
                      <td className="num cell-main">{rands(balance(x.id))}</td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
            {list.filtered.length > 0 && <Pager page={list.view.page} pages={list.view.pages} total={list.filtered.length} shown={list.view.rows.length} noun="records" onPage={list.setPage} />}
          </section>
        </div>
        {c && (
          <section className="card detail" aria-label="Client details">
            <h3 className="card-title" style={{ fontSize: 20 }}>
              {c.name}
            </h3>
            <span className={`chip ${active(c) ? "chip-success" : "chip-neutral"}`} style={{ justifySelf: "start", marginTop: 10 }}>
              {active(c) ? "Active client" : "No active project"}
            </span>
            <hr className="divider" />
            <dl className="facts" style={{ marginTop: 0 }}>
              <div>
                <dt>Primary contact</dt>
                <dd>{c.contact_name ?? "—"}</dd>
                {c.email && (
                  <dd style={{ marginTop: 2, fontWeight: 400 }}>
                    <a href={`mailto:${c.email}`}>{c.email}</a>
                  </dd>
                )}
                {c.phone && <dd style={{ marginTop: 2, fontWeight: 400 }}>{c.phone}</dd>}
              </div>
              <div>
                <dt>Billing</dt>
                <dd style={{ fontWeight: 400, whiteSpace: "pre-line" }}>{c.address ?? "No address saved"}</dd>
                {c.registration_number && <dd style={{ marginTop: 2, fontWeight: 400 }}>Reg. {c.registration_number}</dd>}
                {c.vat_number && <dd style={{ marginTop: 2, fontWeight: 400 }}>VAT {c.vat_number}</dd>}
                <dd style={{ marginTop: 2, fontWeight: 400 }} className="row-sub">
                  {CLIENT_KINDS.find((k) => k.key === c.kind)?.label ?? "Company"} · payment reminders {c.reminders_enabled ? (c.email ? "on" : "on (needs an email)") : "off"}
                </dd>
              </div>
              <div>
                <dt>Projects</dt>
                {projectsOf(c).length === 0 && <dd style={{ fontWeight: 400 }}>None yet</dd>}
                {projectsOf(c).map((p) => (
                  <dd key={p.id} style={{ marginTop: 6 }}>
                    <Link to={`/projects/${p.id}`}>{p.name}</Link>
                    <span className="row-sub" style={{ display: "block", fontWeight: 400 }}>
                      {projectRef(p.id)} · {p.status.replace("_", " ")}
                    </span>
                  </dd>
                ))}
              </div>
            </dl>
            <hr className="divider" />
            <p className="stat-label">Outstanding balance</p>
            <p className="detail-amount num" style={{ marginTop: 4 }}>
              {rands(balance(c.id))}
            </p>
            <div className="detail-actions">
              <button className="btn btn-secondary" onClick={() => ctx.openClient(c)}>
                Edit client
              </button>
              <button className="btn btn-primary" onClick={() => ctx.newQuotation(c.id)}>
                Create quotation
              </button>
            </div>
            <StatementActions client={c} />
          </section>
        )}
      </div>
    </>
  );
}

/** Statement of account: preview it, or number it (SP-SOA) and email it to the client. */
function StatementActions({ client }: { client: Client }) {
  const preview = usePreview();
  const [done, setDone] = useState<string | null>(null);
  const open = () => {
    setDone(null);
    preview({
      title: `Statement of account: ${client.name}`,
      filename: `Statement-${client.name}.pdf`,
      note: client.email
        ? `Sending numbers it (SP-SOA) and emails it to ${client.email} with this PDF.`
        : "This client has no email address: add one to send statements.",
      load: () => apiBlob(`/api/clients/${client.id}/statement.pdf`),
      confirm: client.email
        ? {
            label: "Send statement",
            run: () =>
              post<StatementResult>(`/api/clients/${client.id}/statements`, { email: true }).then((r) =>
                setDone(r.emailed ? `Statement ${r.number} emailed to ${client.email}.` : `Statement ${r.number} saved, but the email could not be sent.`),
              ),
          }
        : undefined,
    });
  };
  return (
    <div style={{ marginTop: 12 }}>
      <button className="btn btn-secondary" onClick={open}>
        Statement of account
      </button>
      <Done text={done} />
    </div>
  );
}

/* ---------------- Quotations ---------------- */

function QuotationsTab({ ctx }: { ctx: Ctx }) {
  const { data } = ctx;
  const all = [...(data.quotations.data ?? [])].sort((a, b) => b.id - a.id);
  const list = useList(all, (x, q, s) => (!s || x.status === s) && (!q || `${x.number ?? "draft"} ${x.title} ${data.clientName(x.client_id)} ${data.project(x.project_id)?.name ?? ""}`.toLowerCase().includes(q)));
  const issued = all.filter((x) => x.status === "issued");
  const acceptedMonth = all.filter((x) => x.status === "accepted");
  const drafts = all.filter((x) => x.status === "draft");
  const sel = list.selected;
  const preview = usePreview();

  const act = useMutation({
    mutationFn: ({ q, action }: { q: Quotation; action: "issue" | "accept" | "decline" | "delete" }) =>
      action === "delete" ? api(`/api/quotations/${q.id}`, { method: "DELETE" }) : post<Quotation>(`/api/quotations/${q.id}/${action}`),
    onSuccess: (_r, { q, action }) =>
      ctx.onDone(action === "issue" ? "Quotation issued with its number." : action === "accept" ? `${q.number} marked accepted. You can now invoice it.` : action === "decline" ? `${q.number} marked declined.` : "Draft deleted."),
    onError: ctx.onFailed,
  });

  if (data.quotations.isError) return <ErrorNote error={data.quotations.error} onRetry={() => data.quotations.refetch()} />;
  return (
    <>
      <div className="stats-3">
        <StatCard label="Awaiting an answer" value={data.quotations.data ? rands(issued.reduce((s, x) => s + x.total_cents, 0)) : <Skeleton w={140} h={30} />} note={plural(issued.length, "issued quotation")} />
        <StatCard label="Accepted" value={data.quotations.data ? rands(acceptedMonth.reduce((s, x) => s + x.total_cents, 0)) : <Skeleton w={140} h={30} />} note={plural(acceptedMonth.length, "quotation")} />
        <StatCard label="Drafts" value={data.quotations.data ? drafts.length : <Skeleton w={40} h={30} />} note="Not yet issued" />
      </div>
      <div className="split">
        <div className="stack">
          <ListTools
            search={list.search}
            onSearch={list.onSearch}
            placeholder="Search number, client or project"
            status={list.status}
            onStatus={list.onStatus}
            options={[["", "All statuses"], ...Object.entries(Q_STATUS).map(([k, v]) => [k, v.label] as [string, string])]}
          />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Quotation</th>
                    <th className="hide-sm">Client</th>
                    <th>Total</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.quotations.isPending && <LoadingRow cols={4} />}
                  {data.quotations.data && list.filtered.length === 0 && <EmptyRow cols={4} text={all.length ? "No quotations match." : "No quotations yet."} />}
                  {list.view.rows.map((x) => (
                    <RowButton key={x.id} selected={x.id === sel?.id} onSelect={() => list.select(x.id)}>
                      <td className="row-title num">{x.number ?? "Draft quotation"}</td>
                      <td className="hide-sm muted">{data.clientName(x.client_id)}</td>
                      <td className="num cell-main">{rands(x.total_cents)}</td>
                      <td className={Q_STATUS[x.status].cls} style={{ fontSize: 12, fontWeight: 500 }}>
                        {Q_STATUS[x.status].label}
                      </td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
            {list.filtered.length > 0 && <Pager page={list.view.page} pages={list.view.pages} total={list.filtered.length} shown={list.view.rows.length} noun="records" onPage={list.setPage} />}
          </section>
        </div>
        {sel && (
          <section className="card detail" aria-label="Quotation details">
            <h3 className="card-title num" style={{ fontSize: 20 }}>
              {sel.number ?? "Draft quotation"}
            </h3>
            <span className={`chip ${sel.status === "accepted" ? "chip-success" : sel.status === "issued" ? "chip-brand" : "chip-neutral"}`} style={{ justifySelf: "start", marginTop: 10 }}>
              {Q_STATUS[sel.status].label}
            </span>
            <div className="detail-meta" style={{ marginTop: 16 }}>
              <strong style={{ fontSize: 15 }}>{data.clientName(sel.client_id)}</strong>
              <span className="detail-note">
                {sel.title}
                {sel.project_id ? ` · ${projectRef(sel.project_id)}` : ""}
              </span>
            </div>
            <hr className="divider" />
            {sel.issue_date && (
              <dl className="kv">
                <div>
                  <dt>Issued</dt>
                  <dd>{fullDay(sel.issue_date)}</dd>
                </div>
                {sel.valid_until && (
                  <div>
                    <dt>Valid until</dt>
                    <dd>{fullDay(sel.valid_until)}</dd>
                  </div>
                )}
              </dl>
            )}
            {sel.issue_date && <hr className="divider" />}
            <Lines lines={sel.lines} />
            <Totals vatBp={sel.vat_rate_bp} subtotal={sel.subtotal_cents} vat={sel.vat_cents} total={sel.total_cents} />
            <div className="detail-actions" style={{ flexDirection: "column", alignItems: "stretch" }}>
              {sel.number && (
                <button className="btn btn-secondary btn-block" onClick={() => preview({ title: `Quotation ${sel.number}`, filename: `${sel.number}.pdf`, load: () => apiBlob(`/api/quotations/${sel.id}/pdf`) })}>
                  View PDF
                </button>
              )}
              {sel.status === "draft" && (
                <>
                  <button
                    className="btn btn-primary btn-block"
                    disabled={act.isPending || ctx.readiness?.can_issue_quotations === false}
                    onClick={() =>
                      preview({
                        title: `Quotation: ${sel.title}`,
                        filename: `quotation-draft-${sel.id}.pdf`,
                        load: () => apiBlob(`/api/quotations/${sel.id}/pdf`),
                        note: "This is the draft. Issuing it adds its number, today’s date and your signature, and it can’t be edited after that.",
                        confirm: { label: "Issue quotation", run: () => act.mutateAsync({ q: sel, action: "issue" }) },
                      })
                    }
                  >
                    Preview and issue
                  </button>
                  <button className="btn btn-secondary btn-block" disabled={act.isPending} onClick={() => act.mutate({ q: sel, action: "delete" })}>
                    Delete draft
                  </button>
                </>
              )}
              {sel.status === "issued" && (
                <>
                  <button className="btn btn-primary btn-block" disabled={act.isPending} onClick={() => act.mutate({ q: sel, action: "accept" })}>
                    Record acceptance
                  </button>
                  <button className="btn btn-secondary btn-block" disabled={act.isPending} onClick={() => act.mutate({ q: sel, action: "decline" })}>
                    Mark declined
                  </button>
                </>
              )}
              {sel.status === "accepted" && (
                <button className="btn btn-primary btn-block" onClick={() => ctx.newInvoice(sel)}>
                  Create invoice
                </button>
              )}
            </div>
          </section>
        )}
      </div>
    </>
  );
}

function Lines({ lines }: { lines: { id?: number; description: string; quantity: number; line_total_cents?: number; unit_price_cents: number }[] }) {
  return (
    <dl className="kv">
      {lines.map((l, i) => (
        <div key={l.id ?? i}>
          <dt>
            {l.description}
            {l.quantity !== 1 ? ` × ${l.quantity}` : ""}
          </dt>
          <dd>{rands(l.line_total_cents ?? Math.round(l.quantity * l.unit_price_cents))}</dd>
        </div>
      ))}
    </dl>
  );
}

function Totals({ vatBp, subtotal, vat, total }: { vatBp: number; subtotal: number; vat: number; total: number }) {
  return (
    <>
      <hr className="divider" />
      {vatBp > 0 && (
        <dl className="kv" style={{ marginBottom: 10 }}>
          <div>
            <dt>Subtotal</dt>
            <dd>{rands(subtotal)}</dd>
          </div>
          <div>
            <dt>VAT</dt>
            <dd>{rands(vat)}</dd>
          </div>
        </dl>
      )}
      <div className="kv-total">
        <span>Total</span>
        <span className="num">{rands(total)}</span>
      </div>
    </>
  );
}

/* ---------------- Invoices ---------------- */

function InvoicesTab({ ctx }: { ctx: Ctx }) {
  const { data, today } = ctx;
  const all = [...(data.invoices.data ?? [])].sort((a, b) => b.id - a.id);
  const list = useList(all, (x, q, s) => {
    const st = invoiceState(x, today).label.toLowerCase().replace(" ", "_");
    if (s && st !== s) return false;
    return !q || `${x.number ?? "draft"} ${x.title} ${data.clientName(x.client_id)}`.toLowerCase().includes(q);
  });
  const open = all.filter((i) => i.status === "issued" || i.status === "part_paid");
  const overdue = open.filter((i) => invoiceState(i, today).label === "Overdue");
  const oldest = overdue.map((i) => i.due_date!).sort()[0];
  const receivedYear = data.receipts.filter((r) => yearOf(r.received_on) === yearOf(today)).reduce((s, r) => s + r.amount_cents, 0);
  const sel = list.selected;
  const [paying, setPaying] = useState<Invoice | null>(null);
  const [crediting, setCrediting] = useState<Invoice | null>(null);
  const preview = usePreview();

  const act = useMutation({
    mutationFn: ({ i, action }: { i: Invoice; action: "issue" | "delete" }) => (action === "delete" ? api(`/api/invoices/${i.id}`, { method: "DELETE" }) : post<Invoice>(`/api/invoices/${i.id}/issue`)),
    onSuccess: (_r, { action }) => ctx.onDone(action === "issue" ? "Invoice issued with its number." : "Draft deleted."),
    onError: ctx.onFailed,
  });

  if (data.invoices.isError) return <ErrorNote error={data.invoices.error} onRetry={() => data.invoices.refetch()} />;
  const selReceipts = sel ? data.receipts.filter((r) => r.invoice_id === sel.id) : [];
  const selCredits = sel ? data.credits.filter((r) => r.invoice_id === sel.id) : [];
  const st = sel && invoiceState(sel, today);

  return (
    <>
      <div className="stats-3">
        <StatCard label="Outstanding" value={data.invoices.data ? rands(open.reduce((s, i) => s + i.balance_cents, 0)) : <Skeleton w={140} h={30} />} note={plural(open.length, "unpaid invoice")} />
        <StatCard
          label="Overdue"
          value={data.invoices.data ? rands(overdue.reduce((s, i) => s + i.balance_cents, 0)) : <Skeleton w={140} h={30} />}
          note={overdue.length ? `${plural(overdue.length, "invoice")} · ${plural(daysBetween(oldest!, today), "day")} late` : "Nothing overdue"}
        />
        <StatCard label="Received this year" value={data.receiptsLoading ? <Skeleton w={140} h={30} /> : rands(receivedYear)} note="Including VAT where charged" />
      </div>
      <div className="split">
        <div className="stack">
          <ListTools
            search={list.search}
            onSearch={list.onSearch}
            placeholder="Search invoice number or client"
            status={list.status}
            onStatus={list.onStatus}
            options={[["", "All statuses"], ["draft", "Draft"], ["issued", "Issued"], ["part_paid", "Part paid"], ["overdue", "Overdue"], ["paid", "Paid"], ["void", "Void"]]}
          />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th className="hide-sm">Client</th>
                    <th>Balance</th>
                    <th>Due / status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.invoices.isPending && <LoadingRow cols={4} />}
                  {data.invoices.data && list.filtered.length === 0 && <EmptyRow cols={4} text={all.length ? "No invoices match." : "No invoices yet."} />}
                  {list.view.rows.map((x) => {
                    const s = invoiceState(x, today);
                    return (
                      <RowButton key={x.id} selected={x.id === sel?.id} onSelect={() => list.select(x.id)}>
                        <td className="row-title num">{x.number ?? "Draft invoice"}</td>
                        <td className="hide-sm muted">{data.clientName(x.client_id)}</td>
                        <td className="num cell-main">{rands(x.number ? x.balance_cents : x.total_cents)}</td>
                        <td>
                          <p className="row-title" style={{ fontWeight: 500 }}>
                            {x.due_date ? shortDay(x.due_date) : "—"}
                          </p>
                          <p className={`row-sub ${s.cls}`}>{s.label}</p>
                        </td>
                      </RowButton>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {list.filtered.length > 0 && <Pager page={list.view.page} pages={list.view.pages} total={list.filtered.length} shown={list.view.rows.length} noun="records" onPage={list.setPage} />}
          </section>
        </div>
        {sel && st && (
          <section className="card detail" aria-label="Invoice details">
            <h3 className="card-title num" style={{ fontSize: 20 }}>
              {sel.number ?? "Draft invoice"}
            </h3>
            <span className={`chip ${st.chip}`} style={{ justifySelf: "start", marginTop: 10 }}>
              {st.label === "Overdue" && sel.due_date ? `${plural(daysBetween(sel.due_date, today), "day")} overdue` : st.label}
            </span>
            <div className="detail-meta" style={{ marginTop: 16 }}>
              <strong style={{ fontSize: 15 }}>{data.clientName(sel.client_id)}</strong>
              <span className="detail-note">{sel.due_date ? `Due ${fullDay(sel.due_date)}` : sel.title}</span>
            </div>
            <hr className="divider" />
            <Lines lines={sel.lines} />
            <dl className="kv" style={{ marginTop: 10 }}>
              {sel.vat_rate_bp > 0 && (
                <div>
                  <dt>VAT</dt>
                  <dd>{rands(sel.vat_cents)}</dd>
                </div>
              )}
              <div>
                <dt>Amount received</dt>
                <dd>{rands(sel.paid_cents)}</dd>
              </div>
              {sel.credited_cents > 0 && (
                <div>
                  <dt>Credited</dt>
                  <dd>{rands(sel.credited_cents)}</dd>
                </div>
              )}
            </dl>
            <hr className="divider" />
            <p className="stat-label">{sel.number ? "Balance due" : "Total"}</p>
            <p className="detail-amount num" style={{ marginTop: 4 }}>
              {rands(sel.number ? sel.balance_cents : sel.total_cents)}
            </p>
            {sel.number && (
              <div className="detail-section">
                <p className="detail-h">Payment history</p>
                {selReceipts.length === 0 && selCredits.length === 0 && <p className="detail-p">No payments recorded.</p>}
                <dl className="kv">
                  {selReceipts.map((r) => (
                    <div key={`r${r.id}`}>
                      <dt>
                        {shortDay(r.received_on)} · {r.number}
                      </dt>
                      <dd>{rands(r.amount_cents)}</dd>
                    </div>
                  ))}
                  {selCredits.map((r) => (
                    <div key={`c${r.id}`}>
                      <dt>
                        {shortDay(r.issue_date)} · {r.number}
                      </dt>
                      <dd>−{rands(r.amount_cents)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            <div className="detail-actions" style={{ flexDirection: "column", alignItems: "stretch" }}>
              {(sel.status === "issued" || sel.status === "part_paid") && (
                <button className="btn btn-primary btn-block" onClick={() => setPaying(sel)}>
                  Record payment
                </button>
              )}
              {sel.status === "draft" && (
                <>
                  <button
                    className="btn btn-primary btn-block"
                    disabled={act.isPending || ctx.readiness?.can_issue_invoices === false}
                    onClick={() =>
                      preview({
                        title: `Invoice: ${sel.title}`,
                        filename: `invoice-draft-${sel.id}.pdf`,
                        load: () => apiBlob(`/api/invoices/${sel.id}/pdf`),
                        note: "This is the draft. Issuing it adds its number, today’s date and your signature, and it can’t be edited after that.",
                        confirm: { label: "Issue invoice", run: () => act.mutateAsync({ i: sel, action: "issue" }) },
                      })
                    }
                  >
                    Preview and issue
                  </button>
                  <button className="btn btn-secondary btn-block" disabled={act.isPending} onClick={() => act.mutate({ i: sel, action: "delete" })}>
                    Delete draft
                  </button>
                </>
              )}
              {sel.number && (
                <div className="form-row" style={{ gap: 10 }}>
                  <button className="btn btn-secondary" onClick={() => preview({ title: `Invoice ${sel.number}`, filename: `${sel.number}.pdf`, load: () => apiBlob(`/api/invoices/${sel.id}/pdf`) })}>
                    View PDF
                  </button>
                  {(sel.status === "issued" || sel.status === "part_paid") && (
                    <button className="btn btn-secondary" onClick={() => setCrediting(sel)}>
                      Credit note
                    </button>
                  )}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
      {paying && <PaymentDialog invoice={paying} onClose={() => setPaying(null)} onSaved={(msg) => (setPaying(null), ctx.onDone(msg))} />}
      {crediting && <CreditDialog invoice={crediting} onClose={() => setCrediting(null)} onSaved={(msg) => (setCrediting(null), ctx.onDone(msg))} />}
    </>
  );
}

/* ---------------- Receipts & credit notes ---------------- */

function ReceiptsTab({ ctx }: { ctx: Ctx }) {
  const { data, today } = ctx;
  const preview = usePreview();
  const invoiceOf = (id: number) => (data.invoices.data ?? []).find((i) => i.id === id);
  const all = [...data.receipts].sort((a, b) => b.received_on.localeCompare(a.received_on) || b.id - a.id);
  const list = useList(all, (r, q, s) => (!s || r.method === s) && (!q || `${r.number} ${r.reference} ${invoiceOf(r.invoice_id)?.number ?? ""} ${data.clientName(invoiceOf(r.invoice_id)?.client_id ?? -1)}`.toLowerCase().includes(q)));
  const month = all.filter((r) => r.received_on.slice(0, 7) === today.slice(0, 7));
  const year = all.filter((r) => yearOf(r.received_on) === yearOf(today));
  const sel = list.selected;
  const inv = sel && invoiceOf(sel.invoice_id);
  const loading = data.invoices.isPending || data.receiptsLoading;

  return (
    <>
      <div className="stats-3">
        <StatCard label="Received this month" value={loading ? <Skeleton w={140} h={30} /> : rands(month.reduce((s, r) => s + r.amount_cents, 0))} note={plural(month.length, "receipt")} />
        <StatCard label="Received this year" value={loading ? <Skeleton w={140} h={30} /> : rands(year.reduce((s, r) => s + r.amount_cents, 0))} note={plural(year.length, "receipt")} />
        <StatCard label="Receipts issued" value={loading ? <Skeleton w={40} h={30} /> : all.length} note="Signed PDFs" />
      </div>
      <div className="split">
        <div className="stack">
          <ListTools search={list.search} onSearch={list.onSearch} placeholder="Search receipt, invoice or client" status={list.status} onStatus={list.onStatus} options={[["", "All methods"], ["eft", "EFT"], ["cash", "Cash"], ["card", "Card"], ["other", "Other"]]} />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Receipt</th>
                    <th className="hide-sm">Client</th>
                    <th>Amount</th>
                    <th>Received</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && <LoadingRow cols={4} />}
                  {!loading && list.filtered.length === 0 && <EmptyRow cols={4} text={all.length ? "No receipts match." : "Receipts appear when you record an invoice payment."} />}
                  {list.view.rows.map((r) => (
                    <RowButton key={r.id} selected={r.id === sel?.id} onSelect={() => list.select(r.id)}>
                      <td>
                        <p className="row-title num">{r.number}</p>
                        <p className="row-sub num">{invoiceOf(r.invoice_id)?.number}</p>
                      </td>
                      <td className="hide-sm muted">{data.clientName(invoiceOf(r.invoice_id)?.client_id ?? -1)}</td>
                      <td className="num cell-main">{rands(r.amount_cents)}</td>
                      <td className="muted">{shortDay(r.received_on)}</td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
            {list.filtered.length > 0 && <Pager page={list.view.page} pages={list.view.pages} total={list.filtered.length} shown={list.view.rows.length} noun="records" onPage={list.setPage} />}
          </section>
        </div>
        {sel && (
          <section className="card detail" aria-label="Receipt details">
            <h3 className="card-title num" style={{ fontSize: 20 }}>
              {sel.number}
            </h3>
            <span className="chip chip-success" style={{ justifySelf: "start", marginTop: 10 }}>
              Received
            </span>
            <div className="detail-meta" style={{ marginTop: 16 }}>
              <strong style={{ fontSize: 15 }}>{data.clientName(inv?.client_id ?? -1)}</strong>
              <span className="detail-note num">For {inv?.number}</span>
            </div>
            <hr className="divider" />
            <dl className="kv">
              <div>
                <dt>Received on</dt>
                <dd>{fullDay(sel.received_on)}</dd>
              </div>
              <div>
                <dt>Method</dt>
                <dd>{sel.method.toUpperCase()}</dd>
              </div>
              <div>
                <dt>Reference</dt>
                <dd>{sel.reference}</dd>
              </div>
            </dl>
            <hr className="divider" />
            <p className="stat-label">Amount</p>
            <p className="detail-amount num" style={{ marginTop: 4 }}>
              {rands(sel.amount_cents)}
            </p>
            <div className="detail-actions">
              <button className="btn btn-secondary btn-block" onClick={() => preview({ title: `Receipt ${sel.number}`, filename: `${sel.number}.pdf`, load: () => apiBlob(`/api/receipts/${sel.id}/pdf`) })}>
                View PDF
              </button>
            </div>
          </section>
        )}
      </div>
    </>
  );
}

function CreditNotesTab({ ctx }: { ctx: Ctx }) {
  const { data, today } = ctx;
  const preview = usePreview();
  const invoiceOf = (id: number) => (data.invoices.data ?? []).find((i) => i.id === id);
  const all = [...data.credits].sort((a, b) => b.issue_date.localeCompare(a.issue_date) || b.id - a.id);
  const list = useList(all, (r, q) => !q || `${r.number} ${r.reason} ${invoiceOf(r.invoice_id)?.number ?? ""} ${data.clientName(invoiceOf(r.invoice_id)?.client_id ?? -1)}`.toLowerCase().includes(q));
  const year = all.filter((r) => yearOf(r.issue_date) === yearOf(today));
  const sel = list.selected;
  const inv = sel && invoiceOf(sel.invoice_id);
  const loading = data.invoices.isPending || data.creditsLoading;

  return (
    <>
      <div className="stats-3">
        <StatCard label="Credited this year" value={loading ? <Skeleton w={140} h={30} /> : rands(year.reduce((s, r) => s + r.amount_cents, 0))} note={plural(year.length, "credit note")} />
        <StatCard label="Credit notes" value={loading ? <Skeleton w={40} h={30} /> : all.length} note="All time" />
        <StatCard label="Invoices affected" value={loading ? <Skeleton w={40} h={30} /> : new Set(all.map((r) => r.invoice_id)).size} note="Balances reduced" />
      </div>
      <div className="split">
        <div className="stack">
          <ListTools search={list.search} onSearch={list.onSearch} placeholder="Search credit note, invoice or reason" status={list.status} onStatus={list.onStatus} options={[["", "All credit notes"]]} />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Credit note</th>
                    <th className="hide-sm">Client</th>
                    <th>Amount</th>
                    <th>Issued</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && <LoadingRow cols={4} />}
                  {!loading && list.filtered.length === 0 && <EmptyRow cols={4} text={all.length ? "No credit notes match." : "Credit notes are issued from an invoice."} />}
                  {list.view.rows.map((r) => (
                    <RowButton key={r.id} selected={r.id === sel?.id} onSelect={() => list.select(r.id)}>
                      <td>
                        <p className="row-title num">{r.number}</p>
                        <p className="row-sub num">{invoiceOf(r.invoice_id)?.number}</p>
                      </td>
                      <td className="hide-sm muted">{data.clientName(invoiceOf(r.invoice_id)?.client_id ?? -1)}</td>
                      <td className="num cell-main">{rands(r.amount_cents)}</td>
                      <td className="muted">{shortDay(r.issue_date)}</td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
            {list.filtered.length > 0 && <Pager page={list.view.page} pages={list.view.pages} total={list.filtered.length} shown={list.view.rows.length} noun="records" onPage={list.setPage} />}
          </section>
        </div>
        {sel && (
          <section className="card detail" aria-label="Credit note details">
            <h3 className="card-title num" style={{ fontSize: 20 }}>
              {sel.number}
            </h3>
            <span className="chip chip-neutral" style={{ justifySelf: "start", marginTop: 10 }}>
              Issued {shortDay(sel.issue_date)}
            </span>
            <div className="detail-meta" style={{ marginTop: 16 }}>
              <strong style={{ fontSize: 15 }}>{data.clientName(inv?.client_id ?? -1)}</strong>
              <span className="detail-note num">Against {inv?.number}</span>
            </div>
            <hr className="divider" />
            <p className="detail-h">Reason</p>
            <p className="detail-p">{sel.reason}</p>
            <hr className="divider" />
            <p className="stat-label">Amount credited</p>
            <p className="detail-amount num" style={{ marginTop: 4 }}>
              {rands(sel.amount_cents)}
            </p>
            <div className="detail-actions">
              <button className="btn btn-secondary btn-block" onClick={() => preview({ title: `Credit note ${sel.number}`, filename: `${sel.number}.pdf`, load: () => apiBlob(`/api/credit-notes/${sel.id}/pdf`) })}>
                View PDF
              </button>
            </div>
          </section>
        )}
      </div>
    </>
  );
}

/* ---------------- Dialogs ---------------- */

function ClientDialog({ client, onClose, onSaved }: { client?: Client; onClose: () => void; onSaved: (c: Client) => void }) {
  const [f, setF] = useState({
    name: client?.name ?? "",
    contact_name: client?.contact_name ?? "",
    email: client?.email ?? "",
    phone: client?.phone ?? "",
    registration_number: client?.registration_number ?? "",
    vat_number: client?.vat_number ?? "",
    address: client?.address ?? "",
  });
  const [kind, setKind] = useState<ClientKind>(client?.kind ?? "company");
  const [reminders, setReminders] = useState(client?.reminders_enabled ?? true);
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () => {
      const body = JSON.stringify({
        ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null])),
        kind,
        reminders_enabled: reminders,
      });
      return client ? api<Client>(`/api/clients/${client.id}`, { method: "PATCH", body }) : api<Client>("/api/clients", { method: "POST", body });
    },
    onSuccess: onSaved,
    onError: setError,
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.name.trim().length < 2) return setError("Enter the client’s name.");
    if (f.email.trim() && !/^\S+@\S+\.\S+$/.test(f.email.trim())) return setError("Enter a valid email address, or leave it empty.");
    setError(null);
    save.mutate();
  }

  return (
    <Dialog title={client ? "Edit client" : "Add client"} onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="cl-name" label="Client name">
          <input id="cl-name" className="input" maxLength={200} value={f.name} onChange={set("name")} autoFocus />
        </Field>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="cl-kind" label="Type of client">
            <select id="cl-kind" className="input" value={kind} onChange={(e) => setKind(e.target.value as ClientKind)}>
              {CLIENT_KINDS.map((k) => (
                <option key={k.key} value={k.key}>
                  {k.label}
                </option>
              ))}
            </select>
          </Field>
          <Field id="cl-contact" label="Contact person">
            <input id="cl-contact" className="input" maxLength={200} value={f.contact_name} onChange={set("contact_name")} />
          </Field>
        </div>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="cl-reg" label="Registration number (if any)" hint="Leave empty for individuals and unregistered businesses.">
            <input id="cl-reg" className="input" maxLength={60} value={f.registration_number} onChange={set("registration_number")} />
          </Field>
          <Field id="cl-vat" label="Client VAT number (if any)">
            <input id="cl-vat" className="input" maxLength={32} value={f.vat_number} onChange={set("vat_number")} />
          </Field>
        </div>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="cl-email" label="Email">
            <input id="cl-email" className="input" type="email" value={f.email} onChange={set("email")} />
          </Field>
          <Field id="cl-phone" label="Phone">
            <input id="cl-phone" className="input" type="tel" maxLength={40} value={f.phone} onChange={set("phone")} />
          </Field>
        </div>
        <Field id="cl-address" label="Billing address">
          <textarea id="cl-address" className="input textarea" maxLength={1000} value={f.address} onChange={set("address")} />
        </Field>
        <label className="row-sub" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <input type="checkbox" checked={reminders} onChange={(e) => setReminders(e.target.checked)} style={{ marginTop: 3 }} />
          <span>Email this client payment reminders and monthly statements automatically (needs an email address).</span>
        </label>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Save client
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export type LineDraft = { description: string; quantity: string; price: string };
export const emptyLine = (): LineDraft => ({ description: "", quantity: "1", price: "" });

export function parseLines(lines: LineDraft[]): LineInput[] | string {
  const out: LineInput[] = [];
  for (const l of lines) {
    if (!l.description.trim() && !l.price.trim()) continue;
    const quantity = Number(l.quantity.replace(",", "."));
    const unit = parseRands(l.price);
    if (!l.description.trim()) return "Every line needs a description.";
    if (!(quantity > 0)) return "Quantities must be more than zero.";
    if (!unit) return `Enter a price for “${l.description.trim()}”.`;
    out.push({ description: l.description.trim(), quantity, unit_price_cents: unit });
  }
  return out.length ? out : "Add at least one line.";
}

export function LineEditor({ lines, onChange }: { lines: LineDraft[]; onChange: (l: LineDraft[]) => void }) {
  const set = (i: number, k: keyof LineDraft, v: string) => onChange(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const total = lines.reduce((s, l) => s + (Number(l.quantity.replace(",", ".")) || 0) * (parseRands(l.price) ?? 0), 0);
  return (
    <fieldset className="line-editor">
      <legend className="field-label">Lines</legend>
      {lines.map((l, i) => (
        <div key={i} className="line-row">
          <input className="input" aria-label={`Line ${i + 1} description`} placeholder="Description" maxLength={300} value={l.description} onChange={(e) => set(i, "description", e.target.value)} />
          <input className="input" aria-label={`Line ${i + 1} quantity`} inputMode="decimal" value={l.quantity} onChange={(e) => set(i, "quantity", e.target.value)} />
          <input className="input" aria-label={`Line ${i + 1} unit price`} inputMode="decimal" placeholder="Price (R)" value={l.price} onChange={(e) => set(i, "price", e.target.value)} />
          <button type="button" className="icon-btn danger" aria-label={`Remove line ${i + 1}`} disabled={lines.length === 1} onClick={() => onChange(lines.filter((_, j) => j !== i))}>
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <div className="line-foot">
        <button type="button" className="link-btn" onClick={() => onChange([...lines, emptyLine()])}>
          <Plus size={14} aria-hidden="true" /> Add line
        </button>
        <span className="num">
          Subtotal <strong>{rands(Math.round(total))}</strong>
        </span>
      </div>
    </fieldset>
  );
}

function QuotationDialog({ data, clientId, onClose, onSaved }: { data: FinanceData; clientId?: number; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ client_id: clientId ? String(clientId) : "", project_id: "", title: "", notes: "" });
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (body: object) => post<Quotation>("/api/quotations", body),
    onSuccess: onSaved,
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.client_id) return setError("Choose the client.");
    if (f.title.trim().length < 2) return setError("Give the quotation a title.");
    const parsed = parseLines(lines);
    if (typeof parsed === "string") return setError(parsed);
    setError(null);
    save.mutate({ client_id: Number(f.client_id), project_id: f.project_id ? Number(f.project_id) : null, title: f.title.trim(), notes: f.notes.trim() || null, lines: parsed });
  }

  return (
    <Dialog title="New quotation" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="q-client" label="Client" hint={data.clients.data?.length ? undefined : "Add a client first."}>
            <select id="q-client" className="input" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })}>
              <option value="">Choose a client</option>
              {(data.clients.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field id="q-project" label="Project (optional)">
            <select id="q-project" className="input" value={f.project_id} onChange={(e) => setF({ ...f, project_id: e.target.value })}>
              <option value="">No project</option>
              {(data.projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field id="q-title" label="Title">
          <input id="q-title" className="input" maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        </Field>
        <LineEditor lines={lines} onChange={setLines} />
        <Field id="q-notes" label="Notes (optional)">
          <textarea id="q-notes" className="input textarea" maxLength={5000} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        </Field>
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

function InvoiceDialog({ data, quotation, onClose, onSaved }: { data: FinanceData; quotation?: Quotation; onClose: () => void; onSaved: () => void }) {
  const accepted = (data.quotations.data ?? []).filter((q) => q.status === "accepted");
  const [mode, setMode] = useState<"quotation" | "custom">(quotation || accepted.length ? "quotation" : "custom");
  const [quoteId, setQuoteId] = useState(quotation ? String(quotation.id) : "");
  const [portion, setPortion] = useState("100");
  const [f, setF] = useState({ client_id: "", project_id: "", title: "", notes: "" });
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (body: object) => post<Invoice>("/api/invoices", body),
    onSuccess: onSaved,
    onError: setError,
  });
  const q = accepted.find((x) => String(x.id) === quoteId);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (mode === "quotation") {
      if (!q) return setError("Choose the accepted quotation.");
      const pct = Number(portion);
      if (!(pct > 0 && pct <= 100)) return setError("The portion must be between 1 and 100%.");
      setError(null);
      return save.mutate({ quotation_id: q.id, portion_percent: pct === 100 ? null : pct });
    }
    if (!f.client_id) return setError("Choose the client.");
    if (f.title.trim().length < 2) return setError("Give the invoice a title.");
    const parsed = parseLines(lines);
    if (typeof parsed === "string") return setError(parsed);
    setError(null);
    save.mutate({ client_id: Number(f.client_id), project_id: f.project_id ? Number(f.project_id) : null, title: f.title.trim(), notes: f.notes.trim() || null, lines: parsed });
  }

  return (
    <Dialog title="Create invoice" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Tabs<"quotation" | "custom">
          label="Invoice source"
          value={mode}
          onChange={setMode}
          tabs={[
            { key: "quotation", label: "From a quotation", count: accepted.length },
            { key: "custom", label: "Custom lines" },
          ]}
        />
        {mode === "quotation" ? (
          <>
            <Field id="i-quote" label="Accepted quotation" hint={accepted.length ? undefined : "No accepted quotations yet."}>
              <select id="i-quote" className="input" value={quoteId} onChange={(e) => setQuoteId(e.target.value)}>
                <option value="">Choose a quotation</option>
                {accepted.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.number} · {data.clientName(x.client_id)} · {rands(x.total_cents)}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="i-portion" label="Portion to invoice (%)" hint={q ? `Excl. VAT: ${rands(Math.round((q.subtotal_cents * (Number(portion) || 0)) / 100))} of ${rands(q.subtotal_cents)}. Use 50 for a deposit.` : "Use 50 for a 50% deposit."}>
              <input id="i-portion" className="input" inputMode="numeric" value={portion} onChange={(e) => setPortion(e.target.value)} />
            </Field>
          </>
        ) : (
          <>
            <div className="form-row" style={{ gap: 14 }}>
              <Field id="i-client" label="Client">
                <select id="i-client" className="input" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })}>
                  <option value="">Choose a client</option>
                  {(data.clients.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="i-project" label="Project (optional)">
                <select id="i-project" className="input" value={f.project_id} onChange={(e) => setF({ ...f, project_id: e.target.value })}>
                  <option value="">No project</option>
                  {(data.projects.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field id="i-title" label="Title">
              <input id="i-title" className="input" maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
            </Field>
            <LineEditor lines={lines} onChange={setLines} />
          </>
        )}
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

function PaymentDialog({ invoice, onClose, onSaved }: { invoice: Invoice; onClose: () => void; onSaved: (msg: string) => void }) {
  const [f, setF] = useState({ amount: (invoice.balance_cents / 100).toFixed(2), received_on: todaySA(), method: "eft", reference: "" });
  const [error, setError] = useState<unknown>(null);
  const preview = usePreview();
  const body = (amount: number) => ({ amount_cents: amount, received_on: f.received_on, method: f.method, reference: f.reference.trim() });
  const save = useMutation({
    mutationFn: (amount: number) => post<{ receipt: Receipt; payouts: unknown[] }>(`/api/invoices/${invoice.id}/payments`, body(amount)),
    onSuccess: (r) => onSaved(`Payment recorded. Receipt ${r.receipt.number} issued${r.payouts.length ? ` and ${plural(r.payouts.length, "contributor payout")} calculated` : ""}.`),
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const amount = parseRands(f.amount);
    if (!amount) return setError("Enter the amount received.");
    if (amount > invoice.balance_cents) return setError(`The balance is only ${rands(invoice.balance_cents)}.`);
    if (!f.received_on || f.received_on > todaySA()) return setError("The date can’t be in the future.");
    if (!f.reference.trim()) return setError("Add the payment reference.");
    setError(null);
    preview({
      title: `Receipt for ${invoice.number}`,
      filename: `receipt-preview-${invoice.number}.pdf`,
      load: () => apiBlob(`/api/invoices/${invoice.id}/payments/preview`, { method: "POST", body: JSON.stringify(body(amount)) }),
      note: "Check the receipt. Recording the payment issues it with its number and your signature, and it can’t be changed after that.",
      confirm: { label: "Record payment", run: () => save.mutateAsync(amount) },
    });
  }

  return (
    <Dialog title={`Record payment · ${invoice.number}`} onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="ip-amount" label="Amount (R)" hint={`Balance ${rands(invoice.balance_cents)}`}>
            <input id="ip-amount" className="input" inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
          </Field>
          <Field id="ip-date" label="Received on">
            <input id="ip-date" className="input" type="date" max={todaySA()} value={f.received_on} onChange={(e) => setF({ ...f, received_on: e.target.value })} />
          </Field>
        </div>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="ip-method" label="Method">
            <select id="ip-method" className="input" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
              <option value="eft">EFT</option>
              <option value="cash">Cash</option>
              <option value="card">Card</option>
              <option value="other">Other</option>
            </select>
          </Field>
          <Field id="ip-ref" label="Reference">
            <input id="ip-ref" className="input" maxLength={120} value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} />
          </Field>
        </div>
        <p className="field-hint">A signed receipt is issued, and contributor payouts are calculated if the invoice belongs to a project.</p>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Preview receipt
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function CreditDialog({ invoice, onClose, onSaved }: { invoice: Invoice; onClose: () => void; onSaved: (msg: string) => void }) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const preview = usePreview();
  const save = useMutation({
    mutationFn: (cents: number) => post<{ credit_note: CreditNote }>(`/api/invoices/${invoice.id}/credit-notes`, { amount_cents: cents, reason: reason.trim() }),
    onSuccess: (r) => onSaved(`Credit note ${r.credit_note.number} issued.`),
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const cents = parseRands(amount);
    if (!cents) return setError("Enter the amount to credit.");
    if (cents > invoice.balance_cents) return setError(`You can credit at most the balance, ${rands(invoice.balance_cents)}.`);
    if (reason.trim().length < 3) return setError("Give the reason for the credit.");
    setError(null);
    preview({
      title: `Credit note for ${invoice.number}`,
      filename: `credit-note-preview-${invoice.number}.pdf`,
      load: () => apiBlob(`/api/invoices/${invoice.id}/credit-notes/preview`, { method: "POST", body: JSON.stringify({ amount_cents: cents, reason: reason.trim() }) }),
      note: "Check the credit note. Issuing it adds its number and your signature and lowers what the client owes. It can’t be changed after that.",
      confirm: { label: "Issue credit note", run: () => save.mutateAsync(cents) },
    });
  }

  return (
    <Dialog title={`Credit note · ${invoice.number}`} onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="cn-amount" label="Amount to credit (R)" hint={`Balance ${rands(invoice.balance_cents)}`}>
          <input id="cn-amount" className="input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field id="cn-reason" label="Reason">
          <textarea id="cn-reason" className="input textarea" maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Preview credit note
          </button>
        </div>
      </form>
    </Dialog>
  );
}

