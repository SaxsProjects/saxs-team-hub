import { useQuery } from "@tanstack/react-query";
import { FileBarChart } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import type { FinanceReport } from "../../api/types";
import { useViewFile } from "../../components/DocumentPreview";
import { ErrorNote, PageHead, Skeleton, StatCard } from "../../components/ui";
import { plural, rands, todaySA } from "../../lib/format";
import "../overview.css";
import "../pages.css";

function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y ?? 2026, (m ?? 1) - 1, 1)).toLocaleDateString("en-ZA", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** The monthly finance report: what was invoiced, received, owed and paid out. Emailed on the 1st automatically. */
export function Reports() {
  const thisMonth = todaySA().slice(0, 7);
  const [month, setMonth] = useState(thisMonth);
  const report = useQuery({ queryKey: ["report", month], queryFn: () => api<FinanceReport>(`/api/reports/finance?month=${month}`) });
  const view = useViewFile();
  const r = report.data;

  return (
    <div className="page">
      <PageHead title="Reports" sub="Management figures from the documents issued in the hub. Last month's report is emailed to you on the 1st.">
        <button className="btn btn-primary" onClick={() => view(`/api/reports/finance.pdf?month=${month}`, `SaxsProjects_Finance_Report_${month}.pdf`, `Finance report, ${monthLabel(month)}`)}>
          <FileBarChart size={16} aria-hidden="true" /> Report PDF
        </button>
      </PageHead>
      <div className="toolbar">
        <label className="row-sub" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          Month
          <input className="input" type="month" max={thisMonth} value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} style={{ width: 180 }} />
        </label>
      </div>
      {report.isError ? (
        <ErrorNote error={report.error} onRetry={() => report.refetch()} />
      ) : (
        <>
          <div className="stats-4">
            <StatCard label="Invoiced (excl. VAT)" value={r ? rands(r.totals.invoiced_excl_cents) : <Skeleton w={140} h={30} />} note={r ? `VAT ${rands(r.totals.vat_cents)} · incl. ${rands(r.totals.invoiced_incl_cents)}` : undefined} />
            <StatCard label="Received from clients" value={r ? rands(r.totals.received_cents) : <Skeleton w={140} h={30} />} note={r?.totals.credited_cents ? `${rands(r.totals.credited_cents)} credited` : "No credit notes"} />
            <StatCard label="Paid out" value={r ? rands(r.totals.payouts_paid_cents + r.totals.costs_cents) : <Skeleton w={140} h={30} />} note={r ? `Payouts ${rands(r.totals.payouts_paid_cents)} · costs ${rands(r.totals.costs_cents)}` : undefined} />
            <StatCard
              label="Net cash"
              value={r ? rands(r.totals.net_cash_cents) : <Skeleton w={140} h={30} />}
              note="Received less payouts and costs"
              noteTone={r && r.totals.net_cash_cents < 0 ? "warning" : undefined}
            />
          </div>
          <div className="grid-2-1">
            <section className="card">
              <div className="card-head">
                <h3 className="card-title">Invoiced per client, {monthLabel(month)}</h3>
              </div>
              {!r ? (
                <Skeleton h={80} />
              ) : r.clients.length === 0 ? (
                <p className="empty">No invoices issued this month.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Client</th>
                        <th>Invoices</th>
                        <th>Amount incl. VAT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.clients.map((c) => (
                        <tr key={c.name}>
                          <td className="row-title">{c.name}</td>
                          <td className="num">{c.count}</td>
                          <td className="num cell-main">{rands(c.total_cents)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <section className="card">
              <div className="card-head">
                <h3 className="card-title">Position at month end</h3>
              </div>
              {!r ? (
                <Skeleton h={80} />
              ) : (
                <dl className="kv">
                  <div>
                    <dt>Open invoices</dt>
                    <dd className="num">
                      {plural(r.position.open_count, "invoice")} · {rands(r.position.outstanding_cents)}
                    </dd>
                  </div>
                  <div>
                    <dt>Overdue</dt>
                    <dd className={`num ${r.position.overdue_cents ? "warning-text" : ""}`}>
                      {plural(r.position.overdue_count, "invoice")} · {rands(r.position.overdue_cents)}
                    </dd>
                  </div>
                  <div>
                    <dt>Payouts still unpaid</dt>
                    <dd className="num">{rands(r.position.payouts_unpaid_cents)}</dd>
                  </div>
                  <div>
                    <dt>Awaiting the client</dt>
                    <dd>
                      {plural(r.position.quotations_open, "quotation")} · {plural(r.position.proposals_open, "proposal")}
                    </dd>
                  </div>
                  <div>
                    <dt>VAT</dt>
                    <dd style={{ fontWeight: 400 }}>{r.vat.message}</dd>
                  </div>
                </dl>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
