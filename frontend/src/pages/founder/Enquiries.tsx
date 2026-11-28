import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, MessageCircle, Phone } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, post } from "../../api/client";
import type { Enquiry, EnquiryStatus } from "../../api/types";
import { Done, EmptyRow, ErrorNote, LoadingRow, PageHead, RowButton, Tabs, useSelectedFromUrl } from "../../components/ui";
import { longDate, shortDate } from "../../lib/format";
import "../pages.css";

const LABEL: Record<EnquiryStatus, string> = { new: "New", contacted: "Contacted", converted: "Client", closed: "Closed" };
const CHIP: Record<EnquiryStatus, string> = { new: "chip-warning", contacted: "chip-brand", converted: "chip-success", closed: "chip-neutral" };

/** Enquiries sent from the company website's contact form. */
export function Enquiries() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["enquiries"], queryFn: () => api<Enquiry[]>("/api/enquiries") });
  const [filter, setFilter] = useState<EnquiryStatus | "all">("new");
  const [selectedId, setSelectedId] = useSelectedFromUrl();
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const refresh = (e: Enquiry, text: string) => {
    for (const k of ["enquiries", "assistant", "clients"]) qc.invalidateQueries({ queryKey: [k] });
    setDone(text);
    setSelectedId(e.id);
  };
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: EnquiryStatus }) => api<Enquiry>(`/api/enquiries/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: (e) => refresh(e, `Marked as ${LABEL[e.status].toLowerCase()}.`),
    onError: setError,
  });
  const toClient = useMutation({
    mutationFn: (id: number) => post<Enquiry>(`/api/enquiries/${id}/client`, {}),
    onSuccess: (e) => refresh(e, "Client created. Complete the details on the client's page."),
    onError: setError,
  });

  if (list.isError) return <ErrorNote error={list.error} onRetry={() => list.refetch()} />;
  const all = list.data ?? [];
  const count = (s: EnquiryStatus) => all.filter((e) => e.status === s).length;
  const shown = filter === "all" ? all : all.filter((e) => e.status === filter);
  const sel = all.find((e) => e.id === selectedId) ?? shown[0];

  return (
    <div className="page">
      <PageHead title="Enquiries" sub="Messages from the contact form on saxsprojects.co.za. The website promises a reply within one business day." />
      {!!error && <ErrorNote error={error} />}
      <Done text={done} />
      <div className="split">
        <div className="stack">
          <Tabs<EnquiryStatus | "all">
            label="Filter enquiries"
            value={filter}
            onChange={(f) => (setFilter(f), setSelectedId(null))}
            tabs={[
              { key: "new", label: "New", count: count("new") },
              { key: "contacted", label: "Contacted", count: count("contacted") },
              { key: "converted", label: "Clients", count: count("converted") },
              { key: "closed", label: "Closed", count: count("closed") },
              { key: "all", label: "All", count: all.length },
            ]}
          />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>From</th>
                    <th className="hide-sm">Service</th>
                    <th>Received</th>
                  </tr>
                </thead>
                <tbody>
                  {list.isPending && <LoadingRow cols={3} />}
                  {list.data && shown.length === 0 && <EmptyRow cols={3} text="No enquiries here." />}
                  {shown.map((e) => (
                    <RowButton key={e.id} selected={e.id === sel?.id} onSelect={() => setSelectedId(e.id)}>
                      <td>
                        <p className="row-title">{e.name}</p>
                        <p className="row-sub">{e.organisation ?? e.email ?? e.phone}</p>
                      </td>
                      <td className="hide-sm">{e.service ?? "General"}</td>
                      <td>{shortDate(e.created_at)}</td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        {sel && (
          <section className="card detail" aria-label="Enquiry details">
            <h3 className="card-title" style={{ fontSize: 19 }}>
              {sel.name}
            </h3>
            <span className={`chip ${CHIP[sel.status]}`} style={{ justifySelf: "start", marginTop: 10 }}>
              {LABEL[sel.status]}
            </span>
            <dl className="kv" style={{ marginTop: 16 }}>
              {sel.organisation && (
                <div>
                  <dt>Organisation</dt>
                  <dd>{sel.organisation}</dd>
                </div>
              )}
              <div>
                <dt>Service</dt>
                <dd>{sel.service ?? "General"}</dd>
              </div>
              <div>
                <dt>Received</dt>
                <dd>{longDate(sel.created_at)}</dd>
              </div>
            </dl>
            <p style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>{sel.message}</p>
            <div className="detail-actions">
              {sel.email && (
                <a className="btn btn-secondary" href={`mailto:${sel.email}?subject=${encodeURIComponent("Your enquiry to SaxsProjects")}`}>
                  <Mail size={16} aria-hidden="true" /> Email
                </a>
              )}
              {sel.phone && (
                <>
                  <a className="btn btn-secondary" href={`tel:${sel.phone}`}>
                    <Phone size={16} aria-hidden="true" /> Call
                  </a>
                  <a className="btn btn-secondary" href={`https://wa.me/${sel.phone.replace(/\D/g, "").replace(/^0/, "27")}`} target="_blank" rel="noopener noreferrer">
                    <MessageCircle size={16} aria-hidden="true" /> WhatsApp
                  </a>
                </>
              )}
            </div>
            <div className="detail-actions">
              {sel.status === "new" && (
                <button className="btn btn-secondary" disabled={setStatus.isPending} onClick={() => (setError(null), setStatus.mutate({ id: sel.id, status: "contacted" }))}>
                  Mark contacted
                </button>
              )}
              {sel.client_id ? (
                <Link className="btn btn-secondary" to={`/finance/clients?open=${sel.client_id}`}>
                  Open client
                </Link>
              ) : (
                <button className="btn btn-primary" disabled={toClient.isPending} onClick={() => (setError(null), toClient.mutate(sel.id))}>
                  Make client
                </button>
              )}
              {sel.status !== "closed" && sel.status !== "converted" && (
                <button className="btn btn-ghost" disabled={setStatus.isPending} onClick={() => (setError(null), setStatus.mutate({ id: sel.id, status: "closed" }))}>
                  Close
                </button>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
