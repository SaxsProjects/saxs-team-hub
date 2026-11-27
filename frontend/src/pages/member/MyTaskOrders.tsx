import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, post } from "../../api/client";
import type { TaskOrder, TaskOrderStatus } from "../../api/types";
import { Dialog, ErrorNote, PageHead, Skeleton, Tabs } from "../../components/ui";
import { fullDay, rands, shortDate } from "../../lib/format";
import "../overview.css";
import "../pages.css";

export const TASK_STATUS: Record<TaskOrderStatus, { label: string; cls: string }> = {
  proposed: { label: "To confirm", cls: "chip-warning" },
  confirmed: { label: "In progress", cls: "chip-brand" },
  submitted: { label: "Awaiting review", cls: "chip-neutral" },
  accepted: { label: "Completed", cls: "chip-success" },
  declined: { label: "Declined", cls: "chip-neutral" },
  cancelled: { label: "Cancelled", cls: "chip-neutral" },
};

type Filter = "all" | "proposed" | "confirmed" | "submitted" | "accepted";

const FEE_TERMS: Record<string, string> = {
  standard: "Fixed fee",
  deferred: "Fixed fee · paid after the first client payment",
};

export function MyTaskOrders() {
  const qc = useQueryClient();
  const orders = useQuery({ queryKey: ["me-task-orders"], queryFn: () => api<TaskOrder[]>("/api/me/task-orders") });
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [declining, setDeclining] = useState(false);
  const [declineNote, setDeclineNote] = useState("");
  const [link, setLink] = useState("");
  const [note, setNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const refresh = () => {
    for (const k of ["me-task-orders", "me-overview", "me-payouts"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const confirm = useMutation({
    mutationFn: (id: number) => post<TaskOrder>(`/api/me/task-orders/${id}/confirm`),
    onSuccess: (t) => (refresh(), setDone(`${t.number} confirmed. You can start the work.`)),
  });
  const decline = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) => post<TaskOrder>(`/api/me/task-orders/${id}/decline`, { note: note.trim() || null }),
    onSuccess: (t) => (refresh(), setDeclining(false), setDeclineNote(""), setDone(`${t.number} declined.`)),
  });
  const submit = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) => post<TaskOrder>(`/api/me/task-orders/${id}/submit`, { note }),
    onSuccess: (t) => (refresh(), setLink(""), setNote(""), setDone(`${t.number} submitted for review.`)),
  });

  if (orders.isError) return <ErrorNote error={orders.error} onRetry={() => orders.refetch()} />;
  const all = [...(orders.data ?? [])].sort((a, b) => b.id - a.id);
  const count = (s: TaskOrderStatus) => all.filter((t) => t.status === s).length;
  const shown = filter === "all" ? all.filter((t) => t.status !== "declined" && t.status !== "cancelled") : all.filter((t) => t.status === filter);
  const selected = all.find((t) => t.id === selectedId) ?? shown[0];
  const current = selected?.status === "confirmed" ? selected : all.find((t) => t.status === "confirmed");
  const actionError = confirm.error ?? decline.error ?? submit.error;
  const reviewing = all.filter((t) => t.status === "submitted" && t.review_due_on).sort((a, b) => a.review_due_on!.localeCompare(b.review_due_on!))[0];

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!current) return;
    const url = link.trim();
    if (url && !/^https?:\/\/\S+$/i.test(url)) return setFormError("The delivery link must start with https://");
    if (!url && note.trim().length < 3) return setFormError("Add a link to the finished work or a short note.");
    setFormError(null);
    setDone(null);
    const text = [url && `Delivery link: ${url}`, note.trim()].filter(Boolean).join("\n\n");
    submit.mutate({ id: current.id, note: text });
  }

  return (
    <div className="page">
      <PageHead title="My Task Orders" sub="Confirm your next task or submit work for review." />
      <Tabs<Filter>
        label="Filter Task Orders"
        value={filter}
        onChange={(f) => (setFilter(f), setSelectedId(null))}
        tabs={[
          { key: "all", label: "All", count: all.filter((t) => t.status !== "declined" && t.status !== "cancelled").length },
          { key: "proposed", label: "To confirm", count: count("proposed") },
          { key: "confirmed", label: "In progress", count: count("confirmed") },
          { key: "submitted", label: "Awaiting review", count: count("submitted") },
          { key: "accepted", label: "Completed", count: count("accepted") },
        ]}
      />
      {!!actionError && <ErrorNote error={actionError} />}
      {done && (
        <p className="form-ok" role="status">
          <CheckCircle2 size={16} aria-hidden="true" /> {done}
        </p>
      )}

      <div className="split">
        <div className="stack">
          <section className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Task Order</th>
                    <th>Fee</th>
                    <th className="hide-sm">Due</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.isPending && (
                    <tr>
                      <td colSpan={3}>
                        <Skeleton h={48} />
                      </td>
                    </tr>
                  )}
                  {orders.data && shown.length === 0 && (
                    <tr>
                      <td colSpan={3} className="empty">
                        No Task Orders here.
                      </td>
                    </tr>
                  )}
                  {shown.map((t) => {
                    const chip = TASK_STATUS[t.status];
                    return (
                      <tr
                        key={t.id}
                        className="selectable"
                        aria-selected={t.id === selected?.id}
                        tabIndex={0}
                        onClick={() => setSelectedId(t.id)}
                        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedId(t.id))}
                      >
                        <td>
                          <p className="row-title">{t.title}</p>
                          <p className="row-sub num">{t.number}</p>
                          <span className={`chip ${chip.cls} row-chip`}>{t.status === "proposed" ? "Awaiting confirmation" : chip.label}</span>
                        </td>
                        <td className="num cell-main">{rands(t.fee_cents)}</td>
                        <td className="hide-sm">{shortDate(t.due_on)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {current && (
            <section className="card">
              <div className="card-head">
                <div>
                  <h3 className="card-title">Ready to submit your current task?</h3>
                  <p className="card-sub num">
                    {current.number} · {current.title}
                  </p>
                </div>
              </div>
              <form className="form-card" onSubmit={onSubmit} noValidate>
                <div className="field">
                  <label htmlFor="delivery-link">Delivery link</label>
                  <input
                    id="delivery-link"
                    className="input"
                    type="url"
                    inputMode="url"
                    placeholder="Add a link to the finished work"
                    value={link}
                    onChange={(e) => setLink(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="delivery-note">Delivery note</label>
                  <div className="form-actions" style={{ justifyContent: "stretch" }}>
                    <textarea
                      id="delivery-note"
                      className="input textarea"
                      placeholder="Summarise what changed…"
                      value={note}
                      maxLength={4000}
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <button className="btn btn-primary" disabled={submit.isPending}>
                      {submit.isPending ? "Submitting…" : "Submit for review"}
                    </button>
                  </div>
                </div>
                {formError && (
                  <p className="form-error" role="alert">
                    {formError}
                  </p>
                )}
              </form>
            </section>
          )}
        </div>

        {selected && (
          <section className="card detail" aria-label="Task Order details">
            <div className="detail-top">
              <span className="detail-ref num">{selected.number}</span>
              <span className={`chip ${TASK_STATUS[selected.status].cls}`}>{TASK_STATUS[selected.status].label}</span>
            </div>
            <h3 className="detail-title">{selected.title}</h3>
            <p className="detail-amount num">{rands(selected.fee_cents)}</p>
            <p className="detail-note">
              {FEE_TERMS[selected.fee_terms] ?? "Fixed fee"} · Due {fullDay(selected.due_on)}
            </p>
            <hr className="divider" />
            <div className="detail-section">
              <p className="detail-h">Deliverable</p>
              <p className="detail-p">{selected.deliverable}</p>
            </div>
            {selected.review_note && (
              <div className="detail-section">
                <p className="detail-h">{selected.status === "confirmed" ? "Changes requested" : "Review note"}</p>
                <p className="detail-p">{selected.review_note}</p>
              </div>
            )}
            <div className="detail-section">
              <p className="detail-h">Submission</p>
              <p className="detail-p">
                {selected.status === "submitted" && selected.review_due_on
                  ? `Submitted. The review is due by ${fullDay(selected.review_due_on)}.`
                  : selected.status === "accepted" && selected.accepted_on
                    ? `Accepted on ${fullDay(selected.accepted_on)}. The fee is on your payouts.`
                    : "Share a link to the finished work and a short note when it’s ready."}
              </p>
            </div>
            {selected.status === "proposed" && (
              <div className="detail-actions">
                <button className="btn btn-primary" onClick={() => (setDone(null), confirm.mutate(selected.id))} disabled={confirm.isPending}>
                  {confirm.isPending ? "Confirming…" : "Confirm task"}
                </button>
                <button className="btn btn-secondary" onClick={() => setDeclining(true)}>
                  Decline
                </button>
              </div>
            )}
          </section>
        )}
      </div>

      <div className="banner">
        <Clock size={18} aria-hidden="true" />
        <div>
          <p className="banner-title">
            {reviewing?.review_due_on ? `Review due by ${fullDay(reviewing.review_due_on)}` : "Review due within 5 days"}
          </p>
          <p className="banner-sub">You’ll be notified when your work is accepted or changes are requested.</p>
        </div>
      </div>

      {declining && selected && (
        <Dialog title={`Decline ${selected.number}?`} onClose={() => setDeclining(false)}>
          <p className="detail-p">The founder will see your reason. This can’t be undone.</p>
          <div className="field">
            <label htmlFor="decline-note">Reason (optional)</label>
            <textarea id="decline-note" className="input textarea" value={declineNote} maxLength={2000} onChange={(e) => setDeclineNote(e.target.value)} />
          </div>
          <div className="form-actions">
            <button className="btn btn-secondary" onClick={() => setDeclining(false)}>
              Keep task
            </button>
            <button
              className="btn btn-primary"
              disabled={decline.isPending}
              onClick={() => (setDone(null), decline.mutate({ id: selected.id, note: declineNote }))}
            >
              Decline task
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
