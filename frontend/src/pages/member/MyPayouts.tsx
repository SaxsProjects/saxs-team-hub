import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, FileText } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { api, downloadFile, post } from "../../api/client";
import type { MemberOverview, MyProject, Payout } from "../../api/types";
import { ErrorNote, PageHead, Skeleton, StatCard, Tabs } from "../../components/ui";
import { fullDay, percent, rands, shortDay, todaySA } from "../../lib/format";
import { PAYOUT_CHIP, calc, payoutName, payoutState, statementPath } from "../../lib/payouts";
import "../overview.css";
import "../pages.css";

type Filter = "unpaid" | "due" | "upcoming" | "paid";

export function MyPayouts() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const overview = useQuery({ queryKey: ["me-overview"], queryFn: () => api<MemberOverview>("/api/me/overview") });
  const payouts = useQuery({ queryKey: ["me-payouts"], queryFn: () => api<Payout[]>("/api/me/payouts") });
  const projects = useQuery({ queryKey: ["me-projects"], queryFn: () => api<MyProject[]>("/api/me/projects") });
  const [filter, setFilter] = useState<Filter>("unpaid");
  const [failed, setFailed] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  const requestPay = useMutation({
    mutationFn: (id: number) => post<Payout>(`/api/me/payouts/${id}/request-payment`),
    onSuccess: (p) => {
      for (const k of ["me-payouts", "me-overview"]) qc.invalidateQueries({ queryKey: [k] });
      setDone(`Payment requested for ${p.statement_number}. The founder has been told.`);
    },
  });

  if (payouts.isError) return <ErrorNote error={payouts.error} onRetry={() => payouts.refetch()} />;
  const o = overview.data;
  const today = o?.today ?? todaySA();
  const names = new Map((projects.data ?? []).map((p) => [p.project_id, p.project]));
  const all = [...(payouts.data ?? [])].sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999") || a.id - b.id);
  const state = (p: Payout) => payoutState(p, today);
  const groups: Record<Filter, Payout[]> = {
    unpaid: all.filter((p) => !p.paid_at),
    due: all.filter((p) => state(p) === "due" || state(p) === "requested"),
    upcoming: all.filter((p) => state(p) === "upcoming" || state(p) === "waiting"),
    paid: all.filter((p) => !!p.paid_at).reverse(),
  };
  const shown = groups[filter];
  const wanted = Number(params.get("payout"));
  const selected = all.find((p) => p.id === wanted) ?? shown[0];
  const select = (id: number) => setParams({ payout: String(id) }, { replace: true });
  const upcomingCents = groups.upcoming.reduce((s, p) => s + p.amount_cents, 0);
  const download = (p: Payout) => downloadFile(statementPath(p), `${p.statement_number}.pdf`).catch(setFailed);

  return (
    <div className="page">
      <PageHead title="My payouts" sub="See what is due and how each amount was calculated." />
      {!!(failed ?? requestPay.error) && <ErrorNote error={failed ?? requestPay.error} />}
      {done && (
        <p className="form-ok" role="status">
          <CheckCircle2 size={16} aria-hidden="true" /> {done}
        </p>
      )}

      <div className="stats-4">
        <StatCard label="Total owed" value={o ? rands(o.owed_cents) : <Skeleton w={120} h={30} />} />
        <section className="card stat-card tint-success">
          <p className="stat-label">Due now</p>
          <p className="stat-value num">{o ? rands(o.due_now_cents) : <Skeleton w={120} h={30} />}</p>
        </section>
        <StatCard label="Upcoming" value={payouts.data ? rands(upcomingCents) : <Skeleton w={120} h={30} />} />
        <StatCard label="Paid this year" value={o ? rands(o.paid_this_year_cents) : <Skeleton w={120} h={30} />} />
      </div>

      <div className="split">
        <div className="stack">
          <Tabs<Filter>
            label="Filter payouts"
            value={filter}
            onChange={setFilter}
            tabs={[
              { key: "unpaid", label: "Unpaid", count: groups.unpaid.length },
              { key: "due", label: "Due now", count: groups.due.length },
              { key: "upcoming", label: "Upcoming", count: groups.upcoming.length },
              { key: "paid", label: "Paid", count: groups.paid.length },
            ]}
          />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Payout</th>
                    <th>Amount</th>
                    <th className="hide-sm">Due</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {payouts.isPending && (
                    <tr>
                      <td colSpan={4}>
                        <Skeleton h={48} />
                      </td>
                    </tr>
                  )}
                  {payouts.data && shown.length === 0 && (
                    <tr>
                      <td colSpan={4} className="empty">
                        No payouts here.
                      </td>
                    </tr>
                  )}
                  {shown.map((p) => {
                    const chip = PAYOUT_CHIP[state(p)];
                    return (
                      <tr
                        key={p.id}
                        className="selectable"
                        aria-selected={p.id === selected?.id}
                        tabIndex={0}
                        onClick={() => select(p.id)}
                        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), select(p.id))}
                      >
                        <td>
                          <div className="doc-cell">
                            <FileText size={18} className="doc-icon" aria-hidden="true" />
                            <div>
                              <p className="row-title">{payoutName(p, names)}</p>
                              <p className="row-sub num">{p.statement_number}</p>
                              <button className="link-btn" style={{ fontSize: 10, marginTop: 6 }} onClick={(e) => (e.stopPropagation(), download(p))}>
                                View statement
                              </button>
                            </div>
                          </div>
                        </td>
                        <td className="num cell-main">{rands(p.amount_cents)}</td>
                        <td className="hide-sm">{p.due_at ? shortDay(p.due_at) : "—"}</td>
                        <td>
                          <span className={`chip ${chip.cls}`}>{chip.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {selected && (
            <section className="card">
              <div className="card-head">
                <h3 className="card-title">Payout status</h3>
              </div>
              <ol className="steps">
                <Step n={1} title="Due" done={!!selected.due_at && selected.due_at <= today} sub={selected.due_at ? shortDay(selected.due_at) : "After first client payment"} />
                <Step
                  n={2}
                  title="Requested"
                  done={!!selected.payment_requested_at || !!selected.paid_at}
                  sub={selected.payment_requested_at ? shortDay(selected.payment_requested_at) : "Not requested"}
                />
                <Step
                  n={3}
                  title="Paid"
                  done={!!selected.paid_at}
                  sub={selected.paid_at ? `${shortDay(selected.paid_at)}${selected.eft_reference ? ` · ${selected.eft_reference}` : ""}` : "Awaiting reference"}
                />
              </ol>
            </section>
          )}
        </div>

        {selected && <PayoutDetail p={selected} name={payoutName(selected, names)} today={today} busy={requestPay.isPending} onRequest={() => (setDone(null), requestPay.mutate(selected.id))} onDownload={() => download(selected)} />}
      </div>
    </div>
  );
}

function Step({ n, title, sub, done }: { n: number; title: string; sub: string; done: boolean }) {
  return (
    <li className={`step${done ? " done" : ""}`}>
      <span className="step-dot" aria-hidden="true">
        {done ? <Check size={13} strokeWidth={3} /> : n}
      </span>
      <span className="step-title">
        {title}
        <span className="sr-only">{done ? " (done)" : " (not yet)"}</span>
      </span>
      <span className="step-sub num">{sub}</span>
    </li>
  );
}

function PayoutDetail({ p, name, today, busy, onRequest, onDownload }: { p: Payout; name: string; today: string; busy: boolean; onRequest: () => void; onDownload: () => void }) {
  const s = payoutState(p, today);
  const c = calc(p);
  return (
    <section className="card detail" aria-label="Payout details">
      <div className="detail-top">
        <h3 className="card-title" style={{ fontSize: 20 }}>
          {name}
        </h3>
        <span className={`chip ${PAYOUT_CHIP[s].cls}`}>{PAYOUT_CHIP[s].label}</span>
      </div>
      <p className="detail-ref num">{p.statement_number}</p>
      <p className="detail-amount num">{rands(p.amount_cents)}</p>
      <p className={`detail-note${s === "due" ? " success" : ""}`}>
        {p.paid_at ? `Paid ${fullDay(p.paid_at)}` : p.due_at ? `Due ${fullDay(p.due_at)}` : "Due after the first client payment"}
      </p>
      <hr className="divider" />
      <p className="detail-h">Calculation</p>
      {p.kind === "task_fee" ? (
        <dl className="kv">
          <div>
            <dt>Task Order</dt>
            <dd>{c.task_order}</dd>
          </div>
          <div>
            <dt>Fixed fee</dt>
            <dd>{rands(c.fee_cents ?? p.amount_cents)}</dd>
          </div>
          <div>
            <dt>Fee terms</dt>
            <dd>{c.fee_terms === "deferred" ? "After first client payment" : "Standard"}</dd>
          </div>
        </dl>
      ) : (
        <dl className="kv">
          <div>
            <dt>Client money received</dt>
            <dd>{rands(c.received_to_date_cents ?? 0)}</dd>
          </div>
          <div>
            <dt>Direct project costs</dt>
            <dd>{rands(c.costs_to_date_cents ?? 0)}</dd>
          </div>
          <div>
            <dt>Net project income</dt>
            <dd>{rands(c.net_income_cents ?? 0)}</dd>
          </div>
          <div>
            <dt>Revenue-share rate</dt>
            <dd>{percent(c.rate_bp ?? 0)}</dd>
          </div>
          <div>
            <dt>Your work share</dt>
            <dd>{percent(c.work_share_bp ?? 0)}</dd>
          </div>
          {!!c.previously_allocated_cents && (
            <div>
              <dt>Already allocated to you</dt>
              <dd>−{rands(c.previously_allocated_cents)}</dd>
            </div>
          )}
        </dl>
      )}
      <hr className="divider" />
      <div className="kv-total">
        <span>Your payout</span>
        <strong className="num">{rands(p.amount_cents)}</strong>
      </div>
      <div className="detail-actions">
        {s === "due" && (
          <button className="btn btn-primary" onClick={onRequest} disabled={busy}>
            {busy ? "Requesting…" : "Request payment"}
          </button>
        )}
        <button className="btn btn-secondary" onClick={onDownload}>
          Download statement
        </button>
      </div>
    </section>
  );
}
