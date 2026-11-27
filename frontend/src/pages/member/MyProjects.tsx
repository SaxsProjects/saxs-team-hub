import { useViewFile } from "../../components/DocumentPreview";
import { useQuery } from "@tanstack/react-query";
import { FileText, Folder } from "lucide-react";
import { Link } from "react-router";
import { api } from "../../api/client";
import type { DocumentInfo, MemberOverview, MyProject, Payout, RatePeriod } from "../../api/types";
import { ErrorNote, PageHead, Skeleton, StatCard } from "../../components/ui";
import { fullDay, percent, plural, rands, shortDay, todaySA } from "../../lib/format";
import { calc, payoutState, statementPath } from "../../lib/payouts";
import "../overview.css";
import "../pages.css";

const STATUS_CHIP: Record<MyProject["status"], { label: string; cls: string }> = {
  planned: { label: "Planned", cls: "chip-neutral" },
  in_progress: { label: "In progress", cls: "chip-brand" },
  completed: { label: "Completed", cls: "chip-success" },
  cancelled: { label: "Cancelled", cls: "chip-neutral" },
};

export const projectRef = (id: number) => `SP-${String(id).padStart(3, "0")}`;

export function MyProjects() {
  const projects = useQuery({ queryKey: ["me-projects"], queryFn: () => api<MyProject[]>("/api/me/projects") });
  const payouts = useQuery({ queryKey: ["me-payouts"], queryFn: () => api<Payout[]>("/api/me/payouts") });
  const overview = useQuery({ queryKey: ["me-overview"], queryFn: () => api<MemberOverview>("/api/me/overview") });
  const rates = useQuery({ queryKey: ["me-rates"], queryFn: () => api<RatePeriod[]>("/api/me/rates") });
  const docs = useQuery({ queryKey: ["me-documents"], queryFn: () => api<DocumentInfo[]>("/api/me/documents") });

  if (projects.isError) return <ErrorNote error={projects.error} onRetry={() => projects.refetch()} />;
  const today = overview.data?.today ?? todaySA();
  const list = projects.data ?? [];
  const all = payouts.data ?? [];
  const shares = all.filter((p) => p.kind === "revenue_share");
  const unpaidShares = shares.filter((p) => !p.paid_at).reduce((s, p) => s + p.amount_cents, 0);
  const active = list.filter((p) => p.status === "in_progress" || p.status === "planned").length;

  const sortedRates = [...(rates.data ?? [])].sort((a, b) => b.effective_from.localeCompare(a.effective_from));
  const currentRate = sortedRates.find((r) => r.effective_from <= today) ?? sortedRates[0];
  const agreement = (docs.data ?? []).filter((d) => d.kind === "agreement").sort((a, b) => b.version - a.version)[0];

  const view = useViewFile();
  const download = (path: string, name: string) => view(path, name);

  return (
    <div className="page">
      <PageHead title="My projects" sub="Your contributions, shares and earnings." />

      <div className="stats-3">
        <StatCard label="Active projects" value={projects.data ? active : <Skeleton w={40} h={30} />} />
        <StatCard
          label="Current rate"
          value={overview.data ? percent(overview.data.current_rate_bp) : <Skeleton w={60} h={30} />}
        />
        <StatCard label="Earned and unpaid" value={payouts.data ? rands(unpaidShares) : <Skeleton w={120} h={30} />} />
      </div>

      {projects.isPending && <Skeleton h={220} />}
      {projects.data && list.length === 0 && (
        <section className="card empty">
          <strong>No projects yet</strong>Projects you’re added to will appear here with your share and payouts.
        </section>
      )}

      <div className="grid-2">
        {list.map((p) => {
          const mine = shares.filter((s) => s.project_id === p.project_id);
          const latest = [...mine].sort((a, b) => b.id - a.id)[0];
          const c = latest ? calc(latest) : undefined;
          const next = mine.filter((s) => !s.paid_at).sort((a, b) => (a.due_at ?? "9").localeCompare(b.due_at ?? "9"))[0];
          const chip = STATUS_CHIP[p.status];
          return (
            <section key={p.project_id} className="card project-card">
              <div className="project-head">
                <span className="detail-icon" aria-hidden="true">
                  <Folder size={20} />
                </span>
                <div className="project-name">
                  <h3 className="card-title" style={{ fontSize: 20 }}>
                    {p.project}
                  </h3>
                  <p className="card-sub">
                    {projectRef(p.project_id)} · {p.client}
                  </p>
                </div>
                <span className={`chip ${chip.cls}`}>{chip.label}</span>
              </div>
              <hr className="divider" />
              <dl className="kv project-kv">
                <div>
                  <dt>Client money received</dt>
                  <dd>{c?.received_to_date_cents !== undefined ? rands(c.received_to_date_cents) : "No payments yet"}</dd>
                </div>
                <div>
                  <dt>Direct costs</dt>
                  <dd>{c?.costs_to_date_cents !== undefined ? rands(c.costs_to_date_cents) : "—"}</dd>
                </div>
                <div>
                  <dt>Your rate × work share</dt>
                  <dd>
                    {percent(p.current_rate_bp)} × {percent(p.work_share_bp)}
                  </dd>
                </div>
              </dl>
              <hr className="divider" />
              <div className="project-foot">
                <div>
                  <p className="stat-label">{next ? "Your payout" : "Paid to you"}</p>
                  <p className="momentum-value num">
                    {next ? rands(next.amount_cents) : rands(mine.reduce((s, x) => s + x.amount_cents, 0))}
                  </p>
                </div>
                {next && (
                  <span className={`project-due${payoutState(next, today) === "due" ? " success" : ""}`}>
                    {next.due_at ? `Due ${shortDay(next.due_at)}` : "After first client payment"}
                  </span>
                )}
                <Link className="btn btn-secondary" to={next ? `/my/payouts?payout=${next.id}` : "/my/payouts"}>
                  View payout
                </Link>
              </div>
            </section>
          );
        })}
      </div>

      <div className="split">
        <section className="card">
          <div className="card-head">
            <div>
              <h3 className="card-title">Project documents</h3>
              <p className="card-sub">Your agreement and payout statements</p>
            </div>
          </div>
          <ul className="doc-list">
            {agreement && (
              <li>
                <FileText size={18} className="doc-icon" aria-hidden="true" />
                <div className="doc-text">
                  <p className="row-title">Contribution agreement</p>
                  <p className="row-sub">
                    Version {agreement.version} · Added {shortDay(agreement.created_at)}
                  </p>
                </div>
                <button className="link-btn" onClick={() => download(`/api/documents/${agreement.id}`, agreement.filename)}>
                  Open
                </button>
              </li>
            )}
            {shares.map((s) => (
              <li key={s.id}>
                <FileText size={18} className="doc-icon" aria-hidden="true" />
                <div className="doc-text">
                  <p className="row-title">Payout statement</p>
                  <p className="row-sub num">
                    {s.statement_number} · {rands(s.amount_cents)}
                  </p>
                </div>
                <button className="link-btn" onClick={() => download(statementPath(s), `${s.statement_number}.pdf`)}>
                  Open
                </button>
              </li>
            ))}
          </ul>
          {docs.data && payouts.data && !agreement && shares.length === 0 && <p className="empty">No project documents yet.</p>}
        </section>

        <section className="card detail">
          <div className="detail-top">
            <h3 className="card-title">Rate history</h3>
            {currentRate && <span className="chip chip-success">Current</span>}
          </div>
          {rates.isPending ? (
            <Skeleton h={80} />
          ) : currentRate ? (
            <>
              <p className="detail-amount num" style={{ marginTop: 24 }}>
                {percent(currentRate.rate_bp)}
              </p>
              <p className="detail-note">Effective {fullDay(currentRate.effective_from)}</p>
              <hr className="divider" />
              <p className="detail-h">Written review</p>
              <p className="detail-p">{currentRate.review_note || "No rate reviews recorded yet."}</p>
              {sortedRates.length > 1 && (
                <dl className="kv" style={{ marginTop: 16 }}>
                  {sortedRates.slice(1).map((r) => (
                    <div key={r.id}>
                      <dt>From {shortDay(r.effective_from)}</dt>
                      <dd>{percent(r.rate_bp)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          ) : (
            <p className="detail-p" style={{ marginTop: 16 }}>
              No rate recorded yet.
            </p>
          )}
        </section>
      </div>

      {projects.data && <p className="page-sub">{plural(list.length, "project")}</p>}
    </div>
  );
}
