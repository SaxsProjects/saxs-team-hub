import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, post } from "../../api/client";
import { useViewFile } from "../../components/DocumentPreview";
import type { Dashboard, Payout, Project } from "../../api/types";
import { Done, EmptyRow, ErrorNote, Field, FormError, LoadingRow, PageHead, RowButton, Skeleton, StatCard, Tabs, useSelectedFromUrl } from "../../components/ui";
import { fullDay, plural, rands, shortDate, shortDay, todaySA } from "../../lib/format";
import { calc, statementPath } from "../../lib/payouts";
import { usePeople } from "../../lib/people";
import "../overview.css";
import "../pages.css";

type Filter = "due" | "requested" | "upcoming" | "deferred" | "paid";

function bucket(p: Payout, today: string): Filter {
  if (p.paid_at) return "paid";
  if (!p.due_at) return "deferred";
  if (p.payment_requested_at) return "requested";
  return p.due_at <= today ? "due" : "upcoming";
}

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function Payouts() {
  const view = useViewFile();
  const qc = useQueryClient();
  const payouts = useQuery({ queryKey: ["payouts"], queryFn: () => api<Payout[]>("/api/payouts") });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/api/projects") });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard") });
  const people = usePeople();
  const [filter, setFilter] = useState<Filter>("due");
  const [selectedId, setSelectedId] = useSelectedFromUrl();
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState<unknown>(null);

  if (payouts.isError) return <ErrorNote error={payouts.error} onRetry={() => payouts.refetch()} />;
  const today = dashboard.data?.today ?? todaySA();
  const projectName = new Map((projects.data ?? []).map((p) => [p.id, p.name]));
  const all = [...(payouts.data ?? [])].sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999") || a.id - b.id);
  const groups = { due: [], requested: [], upcoming: [], deferred: [], paid: [] } as Record<Filter, Payout[]>;
  for (const p of all) groups[bucket(p, today)].push(p);
  groups.paid.reverse();
  // "Due now" in the design covers everything payable today, requested or not.
  const dueNow = [...groups.due, ...groups.requested.filter((p) => p.due_at! <= today)];
  const shown = filter === "due" ? dueNow : groups[filter];
  const selected = all.find((p) => p.id === selectedId) ?? shown[0];
  const sum = (list: Payout[]) => list.reduce((s, p) => s + p.amount_cents, 0);
  const week = addDays(today, 7);
  const next7 = all.filter((p) => !p.paid_at && p.due_at && p.due_at > today && p.due_at <= week);
  const deferredTaskFees = all.filter((p) => !p.paid_at && p.kind === "task_fee" && calc(p).fee_terms === "deferred");
  const source = (p: Payout) => (p.kind === "task_fee" ? `Task fee · ${calc(p).task_order ?? ""}` : (projectName.get(p.project_id ?? -1) ?? "Project share"));
  const nextOf = (list: Payout[]) => list.map((p) => p.due_at).filter(Boolean).sort()[0];

  const exportList = () => (setFailed(null), view("/api/payment-list.csv", `payment-list-${today}.csv`, "Payment list"));

  return (
    <div className="page">
      <PageHead title="Payouts" sub="Prepare payment lists and record completed EFTs.">
        <button className="btn btn-primary" onClick={exportList}>
          Export payment list
        </button>
      </PageHead>
      {!!failed && <ErrorNote error={failed} />}
      <Done text={done} />

      <div className="stats-4">
        <StatCard label="Due now" value={payouts.data ? rands(sum(dueNow)) : <Skeleton w={120} h={30} />} note={plural(dueNow.length, "payout")} />
        <StatCard label="Payment requested" value={payouts.data ? rands(sum(groups.requested)) : <Skeleton w={120} h={30} />} note={plural(groups.requested.length, "payout")} />
        <StatCard
          label="Due in 7 days"
          value={payouts.data ? rands(sum(next7)) : <Skeleton w={120} h={30} />}
          note={nextOf(next7) ? `Due ${shortDay(nextOf(next7)!)}` : "Nothing due this week"}
        />
        <StatCard
          label="Deferred terms"
          value={payouts.data ? rands(sum(deferredTaskFees)) : <Skeleton w={120} h={30} />}
          note={nextOf(deferredTaskFees) ? `Due ${shortDay(nextOf(deferredTaskFees)!)}` : "After first client payment"}
        />
      </div>

      <div className="split">
        <div className="stack">
          <Tabs<Filter>
            label="Filter payouts"
            value={filter}
            onChange={(f) => (setFilter(f), setSelectedId(null))}
            tabs={[
              { key: "due", label: "Due now", count: dueNow.length },
              { key: "requested", label: "Requested", count: groups.requested.length },
              { key: "upcoming", label: "Upcoming", count: groups.upcoming.length },
              { key: "deferred", label: "Deferred", count: groups.deferred.length },
              { key: "paid", label: "Paid", count: groups.paid.length },
            ]}
          />
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Member / source</th>
                    <th>Amount</th>
                    <th className="hide-sm">{filter === "paid" ? "Paid" : "Due"}</th>
                    <th>{filter === "paid" ? "EFT reference" : "Request"}</th>
                  </tr>
                </thead>
                <tbody>
                  {payouts.isPending && <LoadingRow cols={4} />}
                  {payouts.data && shown.length === 0 && <EmptyRow cols={4} text="No payouts here." />}
                  {shown.map((p) => (
                    <RowButton key={p.id} selected={p.id === selected?.id} onSelect={() => setSelectedId(p.id)}>
                      <td>
                        <p className="row-title">{people.nameOf(p.person_id)}</p>
                        <p className="row-sub num">
                          {source(p)} · {p.statement_number}
                        </p>
                      </td>
                      <td className="num cell-main">{rands(p.amount_cents)}</td>
                      <td className="hide-sm">{p.paid_at ? shortDate(p.paid_at) : p.due_at ? shortDate(p.due_at) : "After 1st payment"}</td>
                      <td>
                        {p.paid_at ? (
                          <span className="num">{p.eft_reference}</span>
                        ) : (
                          <span className={`chip ${p.payment_requested_at ? "chip-success" : "chip-neutral"}`}>
                            {p.payment_requested_at ? "Requested" : "Not requested"}
                          </span>
                        )}
                      </td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
            {shown.length > 0 && (
              <div className="pager">
                <span>{plural(shown.length, filter === "due" ? "due payout" : "payout")}</span>
                <strong className="num" style={{ color: "var(--ink)" }}>
                  {rands(sum(shown))} total
                </strong>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h3 className="card-title">Deferred fee schedule</h3>
                <p className="card-sub">Task fees on deferred terms are paid after the first client payment.</p>
              </div>
            </div>
            <ul className="doc-list">
              {deferredTaskFees.length === 0 && <li className="empty" style={{ display: "block" }}>No deferred task fees outstanding.</li>}
              {deferredTaskFees.map((p) => (
                <li key={p.id} style={{ alignItems: "center" }}>
                  <div className="doc-text">
                    <p className="row-title">{people.nameOf(p.person_id)}</p>
                    <p className="row-sub num">{calc(p).task_order}</p>
                  </div>
                  <span className="num cell-main" style={{ flex: 1 }}>
                    {rands(p.amount_cents)}
                  </span>
                  <span className="chip chip-warning">{p.due_at ? `Due ${shortDay(p.due_at)}` : "After 1st client payment"}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {selected && (
          <RecordEft
            key={selected.id}
            payout={selected}
            name={people.nameOf(selected.person_id)}
            source={source(selected)}
            today={today}
            onFailed={setFailed}
            onPaid={(p) => {
              for (const k of ["payouts", "dashboard"]) qc.invalidateQueries({ queryKey: [k] });
              setDone(`${p.statement_number} marked as paid (${p.eft_reference}).`);
            }}
          />
        )}
      </div>
    </div>
  );
}

function RecordEft({ payout: p, name, source, today, onPaid }: { payout: Payout; name: string; source: string; today: string; onPaid: (p: Payout) => void; onFailed: (e: unknown) => void }) {
  const [ref, setRef] = useState("");
  const view = useViewFile();
  const [error, setError] = useState<unknown>(null);
  const pay = useMutation({
    mutationFn: () => post<Payout>(`/api/payouts/${p.id}/paid`, { eft_reference: ref.trim() }),
    onSuccess: onPaid,
    onError: setError,
  });
  const state = bucket(p, today);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ref.trim().length < 2) return setError("Enter the EFT reference from your bank.");
    setError(null);
    pay.mutate();
  }

  return (
    <section className="card detail" aria-label="Payout details">
      <h3 className="card-title" style={{ fontSize: 19 }}>
        {p.paid_at ? "Completed EFT" : "Record completed EFT"}
      </h3>
      <span className={`chip ${state === "paid" ? "chip-success" : state === "due" || state === "requested" ? "chip-success" : "chip-brand"}`} style={{ justifySelf: "start", marginTop: 12 }}>
        {state === "paid" ? "Paid" : state === "deferred" ? "Deferred" : state === "upcoming" ? "Upcoming" : "Due now"}
      </span>
      <div className="detail-meta" style={{ marginTop: 16 }}>
        <strong style={{ fontSize: 16 }}>{name}</strong>
        <span className="detail-note num">
          {source} · {p.statement_number}
        </span>
      </div>
      <hr className="divider" />
      <p className="stat-label">Amount</p>
      <p className="detail-amount num" style={{ marginTop: 4 }}>
        {rands(p.amount_cents)}
      </p>
      {p.paid_at ? (
        <dl className="kv" style={{ marginTop: 18 }}>
          <div>
            <dt>Paid on</dt>
            <dd>{fullDay(p.paid_at)}</dd>
          </div>
          <div>
            <dt>EFT reference</dt>
            <dd>{p.eft_reference}</dd>
          </div>
        </dl>
      ) : (
        <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14, marginTop: 18 }}>
          <Field id="paid-on" label="Payment date" hint="Recorded as today when you mark it paid.">
            <input id="paid-on" className="input" readOnly value={fullDay(today)} />
          </Field>
          <Field id="eft-ref" label="EFT reference">
            <input id="eft-ref" className="input" placeholder={`EFT-${today.replaceAll("-", "").slice(2)}-${p.id}`} value={ref} maxLength={120} onChange={(e) => setRef(e.target.value)} />
          </Field>
          <FormError error={error} />
          <div className="detail-actions" style={{ marginTop: 4 }}>
            <button type="button" className="btn btn-secondary" onClick={() => view(statementPath(p), `${p.statement_number}.pdf`, `Payout statement ${p.statement_number}`)}>
              View statement
            </button>
            <button className="btn btn-primary" disabled={pay.isPending}>
              {pay.isPending ? "Saving…" : "Mark as paid"}
            </button>
          </div>
        </form>
      )}
      {p.paid_at && (
        <div className="detail-actions">
          <button className="btn btn-secondary" onClick={() => view(statementPath(p), `${p.statement_number}.pdf`, `Payout statement ${p.statement_number}`)}>
            View statement
          </button>
        </div>
      )}
    </section>
  );
}
