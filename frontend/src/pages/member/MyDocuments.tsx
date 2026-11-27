import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useState } from "react";
import { api, downloadFile } from "../../api/client";
import type { DocumentInfo, MemberOverview, MyProject, Payout } from "../../api/types";
import { ErrorNote, PageHead, Skeleton, Tabs } from "../../components/ui";
import { fileSize, fullDay, shortDay, todaySA } from "../../lib/format";
import { PAYOUT_CHIP, payoutName, payoutState, statementPath } from "../../lib/payouts";
import "../overview.css";
import "../pages.css";

type Group = "agreements" | "statements" | "policies";
type Filter = "all" | Group;

interface Row {
  key: string;
  group: Group;
  title: string;
  ref: string;
  added: string;
  chip: { label: string; cls: string };
  path: string;
  filename: string;
  fileType: string;
  size?: number;
  facts: [string, string][];
}

const DOC_KIND: Record<string, { title: string; group: Group; chip: { label: string; cls: string } }> = {
  agreement: { title: "Contractor agreement", group: "agreements", chip: { label: "Signed", cls: "chip-success" } },
  acceptance: { title: "Offer acceptance record", group: "agreements", chip: { label: "Accepted", cls: "chip-success" } },
  offer_pdf: { title: "Offer letter", group: "agreements", chip: { label: "Issued", cls: "chip-brand" } },
  policy: { title: "Team policies", group: "policies", chip: { label: "Available", cls: "chip-brand" } },
};

function typeLabel(contentType: string): string {
  if (contentType === "application/pdf") return "PDF document";
  if (contentType.startsWith("image/")) return "Image";
  return contentType;
}

export function MyDocuments() {
  const docs = useQuery({ queryKey: ["me-documents"], queryFn: () => api<DocumentInfo[]>("/api/me/documents") });
  const payouts = useQuery({ queryKey: ["me-payouts"], queryFn: () => api<Payout[]>("/api/me/payouts") });
  const projects = useQuery({ queryKey: ["me-projects"], queryFn: () => api<MyProject[]>("/api/me/projects") });
  const overview = useQuery({ queryKey: ["me-overview"], queryFn: () => api<MemberOverview>("/api/me/overview") });
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [failed, setFailed] = useState<unknown>(null);

  if (docs.isError) return <ErrorNote error={docs.error} onRetry={() => docs.refetch()} />;
  const today = overview.data?.today ?? todaySA();
  const names = new Map((projects.data ?? []).map((p) => [p.project_id, p.project]));

  const rows: Row[] = [
    ...(docs.data ?? []).map((d): Row => {
      const kind = DOC_KIND[d.kind] ?? { title: d.filename, group: "agreements" as Group, chip: { label: "Available", cls: "chip-brand" } };
      return {
        key: `d${d.id}`,
        group: kind.group,
        title: kind.title,
        ref: `${d.filename.replace(/\.[a-z]+$/i, "")} · Version ${d.version}`,
        added: d.created_at,
        chip: kind.chip,
        path: `/api/documents/${d.id}`,
        filename: d.filename,
        fileType: typeLabel(d.content_type),
        size: d.size,
        facts: [[kind.chip.label, fullDay(d.created_at)]],
      };
    }),
    ...(payouts.data ?? []).map((p): Row => {
      const s = payoutState(p, today);
      return {
        key: `p${p.id}`,
        group: "statements",
        title: `${payoutName(p, names)} statement`,
        ref: `${p.statement_number} · PDF`,
        added: p.due_at ?? p.paid_at ?? today,
        chip: PAYOUT_CHIP[s],
        path: statementPath(p),
        filename: `${p.statement_number}.pdf`,
        fileType: "PDF document",
        facts: [p.paid_at ? ["Paid", fullDay(p.paid_at)] : ["Due", p.due_at ? fullDay(p.due_at) : "After first client payment"]],
      };
    }),
  ].sort((a, b) => b.added.localeCompare(a.added));

  const q = search.trim().toLowerCase();
  const shown = rows.filter((r) => (filter === "all" || r.group === filter) && (!q || `${r.title} ${r.ref}`.toLowerCase().includes(q)));
  const selected = rows.find((r) => r.key === selectedKey) ?? shown[0];
  const count = (g: Group) => rows.filter((r) => r.group === g).length;
  const loading = docs.isPending || payouts.isPending;

  return (
    <div className="page">
      <PageHead title="My documents" sub="Your agreements, statements and team policies." />
      <div className="toolbar">
        <input
          className="input"
          type="search"
          placeholder="Search documents"
          aria-label="Search documents"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Tabs<Filter>
          label="Filter documents"
          value={filter}
          onChange={(f) => (setFilter(f), setSelectedKey(null))}
          tabs={[
            { key: "all", label: "All", count: rows.length },
            { key: "agreements", label: "Agreements", count: count("agreements") },
            { key: "statements", label: "Statements", count: count("statements") },
            { key: "policies", label: "Policies", count: count("policies") },
          ]}
        />
      </div>
      {!!failed && <ErrorNote error={failed} />}

      <div className="split">
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th className="hide-sm">Added</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={3}>
                      <Skeleton h={48} />
                    </td>
                  </tr>
                )}
                {!loading && shown.length === 0 && (
                  <tr>
                    <td colSpan={3} className="empty">
                      {q ? "No documents match your search." : filter === "policies" ? "No team policies shared yet." : "No documents here yet."}
                    </td>
                  </tr>
                )}
                {shown.map((r) => (
                  <tr
                    key={r.key}
                    className="selectable"
                    aria-selected={r.key === selected?.key}
                    tabIndex={0}
                    onClick={() => setSelectedKey(r.key)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedKey(r.key))}
                  >
                    <td>
                      <div className="doc-cell">
                        <FileText size={18} className="doc-icon" aria-hidden="true" />
                        <div>
                          <p className="row-title">{r.title}</p>
                          <p className="row-sub num">{r.ref}</p>
                        </div>
                      </div>
                    </td>
                    <td className="hide-sm">{shortDay(r.added)}</td>
                    <td>
                      <span className={`chip ${r.chip.cls}`}>{r.chip.label}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {selected && (
          <section className="card detail" aria-label="Document details">
            <span className="detail-icon" aria-hidden="true">
              <FileText size={20} />
            </span>
            <h3 className="detail-title" style={{ marginTop: 18 }}>
              {selected.title}
            </h3>
            <p className="detail-ref num">{selected.ref}</p>
            <span className={`chip ${selected.chip.cls}`} style={{ marginTop: 12, justifySelf: "start" }}>
              {selected.chip.label}
            </span>
            <hr className="divider" />
            <dl className="kv">
              {selected.facts.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
              <div>
                <dt>File type</dt>
                <dd>{selected.fileType}</dd>
              </div>
              {selected.size !== undefined && (
                <div>
                  <dt>File size</dt>
                  <dd>{fileSize(selected.size)}</dd>
                </div>
              )}
            </dl>
            <div className="detail-actions">
              <button className="btn btn-primary" onClick={() => downloadFile(selected.path, selected.filename).catch(setFailed)}>
                Download PDF
              </button>
            </div>
          </section>
        )}
      </div>

      <div className="banner">
        <FileText size={18} aria-hidden="true" />
        <div>
          <p className="banner-title">Your signed records, in one place</p>
          <p className="banner-sub">Download the original copy of an agreement or statement whenever you need it.</p>
        </div>
      </div>
    </div>
  );
}
